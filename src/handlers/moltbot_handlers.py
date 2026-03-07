import json
import logging
import os
import random
import re
import threading
import time
import httpx
import google.generativeai as genai
from datetime import datetime, timezone, timedelta
from config.settings import Settings

CHAT_SUMMARY_PATH = os.path.expanduser("~/.openclaw/workspace/memory/chat-summary.md")
STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "moltbot_state.json")


class _AIConnectionError(Exception):
    """Raised when AI backend is unreachable or timed out."""

class _AIRefusalError(Exception):
    """Raised when AI explicitly refuses to respond."""


def _load_chat_summary() -> str:
    """Load the long-term chat summary written by the AI."""
    try:
        with open(CHAT_SUMMARY_PATH, encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.warning(f"MoltBot: could not read chat summary: {e}")
        return ""


logger = logging.getLogger(__name__)

# Known group members: Telegram user_id → friendly name
KNOWN_MEMBERS = {
    741542965: "Макс",
    742272644: "Юра",
    855951767: "Богдан",
}

# Chat ID → stable user key for MoltBot memory
CHAT_KEYS = {
    -1001294162183: "tg-group-main",
    -1002491624152: "tg-group-secondary",
}

# Proactive messaging config
PROACTIVE_CHAT_ID = -1001294162183  # tg-group-main
PROACTIVE_SCHEDULE_TIMES = ["13:00", "21:00"]
SPIKE_THRESHOLD = 15       # messages in 30 min
SPIKE_COOLDOWN_HOURS = 2
SPIKE_DELAY_MIN, SPIKE_DELAY_MAX = 5 * 60, 20 * 60  # seconds

# Smart summary config
SUMMARY_UPDATE_INTERVAL = 40  # update chat-summary.md every N group messages
SUMMARY_FETCH_LIMIT = 600     # messages to analyze when updating


class MoltbotHandlers:
    def __init__(self, bot, db_manager):
        self.bot = bot
        self.db = db_manager
        self._bot_username = None  # lazily cached
        self._history_reset_time: dict[int, datetime] = {}  # chat_id → reset timestamp
        self._user_key_suffix: dict[int, str] = {}  # chat_id → suffix added after reset
        self._gemini_model = None
        self._last_proactive_sent: dict[int, datetime] = {}
        self._proactive_queued: set[int] = set()
        self._last_probabilistic_sent: dict[int, datetime] = {}
        self._last_reaction_time: dict[int, datetime] = {}
        self._messages_since_summary: int = 0
        self._active_danetka: dict[int, dict] = {}
        self._load_state()
        self._init_gemini()
        self._ensure_danetki_table()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load_state(self):
        """Load persisted reset state from disk (survives bot restarts)."""
        try:
            with open(STATE_PATH, encoding="utf-8") as f:
                data = json.load(f)
            for chat_id_str, suffix in data.get("user_key_suffix", {}).items():
                self._user_key_suffix[int(chat_id_str)] = suffix
            for chat_id_str, ts in data.get("history_reset_time", {}).items():
                self._history_reset_time[int(chat_id_str)] = datetime.fromisoformat(ts)
            logger.info(f"MoltBot: loaded state for {len(self._user_key_suffix)} chat(s)")
        except FileNotFoundError:
            pass  # first run, nothing to load
        except Exception as e:
            logger.warning(f"MoltBot: could not load state: {e}")

    def _save_state(self):
        """Persist reset state to disk."""
        try:
            data = {
                "user_key_suffix": {
                    str(k): v for k, v in self._user_key_suffix.items()
                },
                "history_reset_time": {
                    str(k): v.isoformat() for k, v in self._history_reset_time.items()
                },
            }
            with open(STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"MoltBot: could not save state: {e}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_bot_username(self) -> str:
        if not self._bot_username:
            self._bot_username = self.bot.get_me().username
        return self._bot_username

    def _resolve_sender_name(self, user) -> str:
        """Return friendly name for known members, otherwise first_name."""
        return KNOWN_MEMBERS.get(user.id, user.first_name or "Кто-то")

    def _resolve_user_key(self, message) -> str:
        """Return a stable key for MoltBot's per-conversation memory.
        After a reset, a timestamp suffix is appended to start a fresh OpenClaw thread."""
        chat = message.chat
        if chat.type == 'private':
            base = f"tg-private-{message.from_user.id}"
        else:
            base = CHAT_KEYS.get(chat.id, f"tg-group-{chat.id}")
        suffix = self._user_key_suffix.get(chat.id, "")
        return f"{base}{suffix}" if suffix else base

    def _get_chat_context(self, message) -> str:
        """Return a human-readable description of where the message was sent from."""
        chat = message.chat
        if chat.type == 'private':
            sender_name = self._resolve_sender_name(message.from_user)
            return f"Telegram, личный чат один на один с {sender_name}"
        elif chat.type in ('group', 'supergroup'):
            title = chat.title or "групповой чат"
            return f"Telegram, групповой чат «{title}»"
        return ""

    def _is_bot_mentioned(self, message) -> bool:
        """Return True if @ggallmute2_bot appears in message entities."""
        if not message.entities or not message.text:
            return False
        bot_username = self._get_bot_username().lower()
        for entity in message.entities:
            if entity.type == 'mention':
                name = message.text[entity.offset:entity.offset + entity.length].lstrip('@').lower()
                if name == bot_username:
                    return True
        return False

    def _is_bot_mentioned_in_caption(self, message) -> bool:
        """Return True if @botname appears in photo/video caption entities."""
        if not message.caption_entities or not message.caption:
            return False
        bot_username = self._get_bot_username().lower()
        for entity in message.caption_entities:
            if entity.type == 'mention':
                name = message.caption[entity.offset:entity.offset + entity.length].lstrip('@').lower()
                if name == bot_username:
                    return True
        return False

    def _extract_user_text(self, message) -> str:
        """Strip @botname mention(s) from message text."""
        text = message.text or ""
        bot_username = self._get_bot_username().lower()
        parts = []
        last = 0
        for entity in sorted(message.entities or [], key=lambda e: e.offset):
            if entity.type == 'mention':
                name = text[entity.offset:entity.offset + entity.length].lstrip('@').lower()
                if name == bot_username:
                    parts.append(text[last:entity.offset])
                    last = entity.offset + entity.length
        parts.append(text[last:])
        return "".join(parts).strip()

    def _extract_caption_text(self, message) -> str:
        """Strip @botname mention(s) from photo caption."""
        text = message.caption or ""
        bot_username = self._get_bot_username().lower()
        parts = []
        last = 0
        for entity in sorted(message.caption_entities or [], key=lambda e: e.offset):
            if entity.type == 'mention':
                name = text[entity.offset:entity.offset + entity.length].lstrip('@').lower()
                if name == bot_username:
                    parts.append(text[last:entity.offset])
                    last = entity.offset + entity.length
        parts.append(text[last:])
        return "".join(parts).strip()

    def _init_gemini(self):
        """Initialize Gemini model for image analysis."""
        try:
            genai.configure(api_key=Settings.GEMINI_API_KEY)
            self._gemini_model = genai.GenerativeModel('gemini-2.5-flash-lite')
            logger.info("MoltBot: Gemini vision initialized (gemini-2.5-flash-lite)")
        except Exception as e:
            logger.warning(f"MoltBot: Gemini init failed: {e}")

    def _analyze_image_with_gemini(self, image_bytes: bytes, user_question: str) -> str:
        """Send image to Gemini and get a description / answer to the question."""
        if not self._gemini_model:
            return "[Анализ изображения недоступен — Gemini не настроен]"
        try:
            prompt = "Подробно опиши что изображено на картинке. Если есть текст — прочитай его дословно."
            if user_question:
                prompt += f" Также ответь на вопрос: {user_question}"
            response = self._gemini_model.generate_content([
                {"mime_type": "image/jpeg", "data": image_bytes},
                prompt,
            ])
            return response.text
        except Exception as e:
            logger.error(f"MoltBot: Gemini image analysis failed: {e}")
            return "[Не удалось проанализировать изображение]"

    def _store_bot_reply(self, text: str, msg_id: int | None = None):
        """Store Jarvis bot reply in the messages table."""
        try:
            self.db.execute_query(
                "INSERT INTO messages (user_id, message_text, timestamp, name, message_id) "
                "VALUES (%s, %s, CURRENT_TIMESTAMP, %s, %s)",
                (0, text, "Jarvis", msg_id),
            )
        except Exception as e:
            logger.warning(f"MoltBot: failed to store bot reply: {e}")

    def _get_recent_group_messages(self, limit: int = 50, chat_id: int | None = None) -> list[str]:
        """Fetch last `limit` messages from the group chat history in DB."""
        try:
            reset_time = self._history_reset_time.get(chat_id) if chat_id else None
            if reset_time:
                query = """
                    SELECT name, message_text
                    FROM messages
                    WHERE timestamp >= %s
                    ORDER BY timestamp DESC
                    LIMIT %s
                """
                rows = self.db.execute_query(query, (reset_time, limit))
            else:
                query = """
                    SELECT name, message_text
                    FROM messages
                    ORDER BY timestamp DESC
                    LIMIT %s
                """
                rows = self.db.execute_query(query, (limit,))
            if not rows:
                return []
            # Rows come newest-first; reverse to get chronological order
            return [f"{row[0] or 'Аноним'}: {row[1]}" for row in reversed(rows)]
        except Exception as e:
            logger.error(f"MoltBot: error fetching chat history: {e}")
            return []

    def _call_openclaw(self, content: str, user_key: str, model: str = "openclaw:main") -> str:
        """Raw API call to OpenClaw. Returns response text or empty string on error.
        Only retries on connection errors — NOT on timeouts, because OpenClaw is stateful
        (tracks history per user_key) and a timeout means the message was already received."""
        last_exc = None
        for attempt in range(3):
            try:
                logger.info(f"MoltBot: OpenClaw request model={model} user={user_key} attempt={attempt + 1} prompt_len={len(content)}")
                with httpx.Client() as client:
                    r = client.post(
                        Settings.JARVIS_URL,
                        headers={"Authorization": f"Bearer {Settings.JARVIS_TOKEN}"},
                        json={
                            "model": model,
                            "user": user_key,
                            "messages": [{"role": "user", "content": content}],
                        },
                        timeout=120,
                    )
                    logger.info(f"MoltBot: OpenClaw response status={r.status_code} model={model}")
                    r.raise_for_status()
                    raw = r.json()
                    text = raw["choices"][0]["message"]["content"]
                    logger.info(f"MoltBot: OpenClaw raw response text={repr(text[:200])}")
                    if not text:
                        return ""
                    # Strip action error lines injected by OpenClaw
                    lines = text.split('\n')
                    stripped = [l for l in lines if ('⚠' in l and ('failed' in l.lower() or 'action' in l.lower() or 'target' in l.lower() or 'rate limit' in l.lower() or 'try again' in l.lower()))]
                    if stripped:
                        logger.warning(f"MoltBot: OpenClaw stripped error lines: {stripped}")
                    lines = [l for l in lines if l not in stripped]
                    text = '\n'.join(lines).strip()
                    if "no response" in text.lower() and "openclaw" in text.lower():
                        logger.info("MoltBot: OpenClaw returned NO_REPLY signal, skipping response")
                        return ""
                    return text
            except httpx.TimeoutException as e:
                # Timeout = OpenClaw already received the message, don't retry (would cause duplicates)
                logger.warning(f"MoltBot: OpenClaw timed out (attempt {attempt + 1}), not retrying to avoid duplicate context")
                raise _AIConnectionError("timed out") from e
            except Exception as e:
                last_exc = e
                if attempt < 2:
                    logger.warning(f"MoltBot: OpenClaw attempt {attempt + 1} failed: {e}, retrying...")
                    import time; time.sleep(2)
        logger.error(f"MoltBot: OpenClaw all retries failed: {last_exc}")
        raise _AIConnectionError(str(last_exc))

    def _call_ollama_direct(self, content: str, bot=None, message=None) -> str:
        """Call Ollama directly. Routes through OllamaWakeManager for auto-wake."""
        from services.ollama_wake_manager import OllamaWakeManager, WakeState
        manager = OllamaWakeManager()

        # Future use: if message context provided, use async wake flow
        if bot is not None and message is not None:
            result = manager.call(content, bot=bot, message=message)
            return result if result is not None else ""

        # Synchronous path (internal calls — no user waiting for this specific response)
        if manager.state == WakeState.OFFLINE:
            manager._trigger_wake()
            logger.info("MoltBot: Ollama offline, WoL triggered, returning empty")
            return ""
        if manager.state == WakeState.WAKING:
            logger.info("MoltBot: Ollama waking up, returning empty")
            return ""

        try:
            return manager._call_ollama_raw(content)
        except Exception as e:
            logger.warning(f"MoltBot: Ollama call failed: {e}, triggering wake")
            manager._set_state(WakeState.OFFLINE)
            manager._trigger_wake()
            return ""

    def _ask_moltbot(self, sender_name: str, user_text: str,
                     chat_context: str, user_key: str,
                     history: list[str] | None = None,
                     model: str = "openclaw:main") -> str:
        """Call the local MoltBot/OpenClaw API synchronously."""
        context_prefix = f"[Сообщение отправлено из: {chat_context}]\n" if chat_context else ""

        summary = _load_chat_summary()
        if summary:
            context_prefix += f"[Долгосрочная память о чате:\n{summary}\n]\n"

        if history:
            history_block = "\n".join(history)
            context_prefix += f"[История чата (последние {len(history)} сообщений):\n{history_block}\n]\n"

        user_content = (
            f"{context_prefix}{sender_name}: {user_text}"
            if user_text else
            f"{context_prefix}{sender_name}: Привет!"
        )

        return self._call_openclaw(user_content, user_key, model=model)

    def _count_recent_messages(self, minutes: int) -> int:
        """Count messages in DB written in the last `minutes` minutes."""
        try:
            rows = self.db.execute_query(
                "SELECT COUNT(*) FROM messages WHERE timestamp > NOW() - INTERVAL '%s minutes'",
                (minutes,)
            )
            return rows[0][0] if rows else 0
        except Exception as e:
            logger.error(f"MoltBot: error counting recent messages: {e}")
            return 0

    def _send_proactive_message(self, chat_id: int):
        """Build context and send a proactive (unprompted) message to the chat."""
        try:
            history = self._get_recent_group_messages(30, chat_id)
            summary = _load_chat_summary()

            context_prefix = ""
            if summary:
                context_prefix += f"[Долгосрочная память о чате:\n{summary}\n]\n"
            if history:
                history_block = "\n".join(history)
                context_prefix += f"[История чата (последние {len(history)} сообщений):\n{history_block}\n]\n"

            topic = self._get_current_topic(history) if history else ""
            topic_hint = f"[Текущая тема разговора: {topic}]\n" if topic else ""

            user_content = (
                f"{context_prefix}{topic_hint}"
                "[Ты сам захотел что-то написать в чат — не в ответ на обращение, "
                "а потому что тебе пришла мысль или хочется поучаствовать. "
                "Напиши одно короткое сообщение как участник разговора.]"
            )

            user_key = CHAT_KEYS.get(chat_id, f"tg-group-{chat_id}")
            reply = self._call_openclaw(user_content, user_key)

            # Reply to the most recent stored message if we have its Telegram message_id
            reply_to = None
            try:
                rows = self.db.execute_query(
                    "SELECT message_id FROM messages WHERE message_id IS NOT NULL ORDER BY timestamp DESC LIMIT 1"
                )
                if rows and rows[0][0]:
                    reply_to = rows[0][0]
            except Exception:
                pass

            self.bot.send_message(chat_id, reply, reply_to_message_id=reply_to)
            self._last_proactive_sent[chat_id] = datetime.now(timezone.utc)
            logger.info(f"MoltBot: proactive message sent to chat {chat_id}")
        except Exception as e:
            logger.error(f"MoltBot: failed to send proactive message to {chat_id}: {e}")

    def _check_activity_spike(self, chat_id: int):
        """Queue a proactive message if chat activity is high and cooldown has passed."""
        if chat_id in self._proactive_queued:
            return
        last = self._last_proactive_sent.get(chat_id)
        if last and (datetime.now(timezone.utc) - last) < timedelta(hours=SPIKE_COOLDOWN_HOURS):
            return
        count = self._count_recent_messages(30)
        if count >= SPIKE_THRESHOLD:
            self._proactive_queued.add(chat_id)
            delay = random.randint(SPIKE_DELAY_MIN, SPIKE_DELAY_MAX)
            logger.info(f"MoltBot: activity spike ({count} msgs), queuing proactive in {delay}s")
            threading.Timer(delay, self._fire_spike_proactive, args=[chat_id]).start()

    def _fire_spike_proactive(self, chat_id: int):
        """Called after spike delay — send proactive message and clear queue flag."""
        self._proactive_queued.discard(chat_id)
        self._send_proactive_message(chat_id)

    # ── Smart summary ─────────────────────────────────────────────────────────

    def _update_summary_via_qwen(self):
        """Fetch recent messages and ask Qwen to rewrite chat-summary.md."""
        try:
            rows = self.db.execute_query(
                "SELECT name, message_text FROM messages ORDER BY timestamp DESC LIMIT %s",
                (SUMMARY_FETCH_LIMIT,),
            )
            if not rows:
                return
            messages = [f"{r[0] or 'Аноним'}: {r[1]}" for r in reversed(rows)]
            history_text = "\n".join(messages)

            current_summary = _load_chat_summary()
            now = datetime.now().strftime("%Y-%m-%d %H:%M")

            prompt = f"""[СЛУЖЕБНЫЙ ЗАПРОС — обновление долгосрочной памяти чата]

Ты Джарвис. Тебя попросили обновить файл chat-summary.md на основе последних сообщений группового чата.

== ТЕКУЩИЙ SUMMARY ==
{current_summary or '(пусто)'}

== ПОСЛЕДНИЕ {len(messages)} СООБЩЕНИЙ ==
{history_text}

== ИНСТРУКЦИЯ ==
Обнови summary. Правила:
- Сохрани всё важное из текущего summary: персонажи, правила, мемы, внутренние шутки, проекты, незакрытые темы
- Добавь новое что появилось в последних сообщениях: шутки, события, пари, внутренние мемы, новые темы
- Убери то, что явно устарело и больше не актуально
- Держи размер ~4000 слов — сохраняй все детали, выкидывай только совсем устаревшее и неактуальное
- Обнови поле "Последнее обновление" на {now}
- Верни ТОЛЬКО текст нового summary в формате markdown, без пояснений, без обёртки в ```"""

            new_summary = self._call_ollama_direct(prompt)
            if not new_summary or len(new_summary) < 100:
                logger.warning("MoltBot: Qwen returned suspiciously short summary, skipping save")
                return

            os.makedirs(os.path.dirname(CHAT_SUMMARY_PATH), exist_ok=True)
            with open(CHAT_SUMMARY_PATH, "w", encoding="utf-8") as f:
                f.write(new_summary)
            logger.info(f"MoltBot: chat-summary.md updated via Qwen ({len(new_summary)} chars)")
        except Exception as e:
            logger.error(f"MoltBot: summary update failed: {e}")

    def _maybe_update_summary(self):
        """Increment message counter and trigger summary update every N messages."""
        self._messages_since_summary += 1
        if self._messages_since_summary >= SUMMARY_UPDATE_INTERVAL:
            self._messages_since_summary = 0
            threading.Thread(target=self._update_summary_via_qwen, daemon=True,
                             name="moltbot-summary").start()
            logger.info("MoltBot: triggered background summary update")

    # ── Topic detection ───────────────────────────────────────────────────────

    def _get_current_topic(self, history: list[str]) -> str:
        """Ask Qwen to summarise the current chat topic in a few words."""
        if not history:
            return ""
        snippet = "\n".join(history[-15:])
        prompt = (
            f"Вот последние сообщения из группового чата:\n{snippet}\n\n"
            "Определи текущую тему разговора в 3-6 словах. "
            "Если тем несколько — выбери самую последнюю/активную. "
            "Верни ТОЛЬКО краткое описание темы, без лишних слов."
        )
        try:
            result = self._call_ollama_direct(prompt)
            return result.strip()
        except Exception as e:
            logger.warning(f"MoltBot: topic detection error: {e}")
            return ""

    def _classify_complexity(self, user_text: str, history: list[str] | None = None) -> str:
        """Ask Qwen if the question is simple or complex. Returns 'simple' or 'complex'."""
        history_block = "\n".join(history[-5:]) if history else ""
        context_part = f"Контекст разговора:\n{history_block}\n\n" if history_block else ""
        prompt = (
            f"{context_part}"
            f"Вопрос или сообщение: {user_text}\n\n"
            "Оцени сложность: требует ли это глубокого анализа, написания кода, длинного объяснения "
            "или работы с большим объёмом информации?\n"
            "Ответь одним словом: simple или complex"
        )
        try:
            result = self._call_ollama_direct(prompt)
            result = result.strip().lower()
            return "complex" if "complex" in result else "simple"
        except Exception as e:
            logger.warning(f"MoltBot: classifier error, defaulting to complex: {e}")
            return "complex"

    _DISSATISFIED_PATTERNS = [
        "не понял", "непонял", "не понятно", "непонятно", "не понимаю",
        "не то", "не так", "не правильно", "неправильно", "не верно", "неверно",
        "объясни", "поясни", "расскажи подробнее", "подробнее", "поподробнее",
        "ещё раз", "еще раз", "повтори",
        "что ты имеешь", "что имеешь в виду", "ты о чём", "о чём ты",
        "то есть", "т.е.", "иными словами",
        "не помог", "не помогло", "не работает", "всё равно", "все равно",
        "а что если", "а если", "но что если", "но если",
        "почему именно", "зачем именно", "как именно",
    ]

    def _is_dissatisfied_or_followup(self, text: str) -> bool:
        """Return True if message looks like dissatisfaction or a clarifying follow-up."""
        lower = text.lower()
        return any(p in lower for p in self._DISSATISFIED_PATTERNS)

    def _ask_moltbot_routed(self, sender_name: str, user_text: str,
                            chat_context: str, user_key: str,
                            history: list[str] | None = None) -> str:
        """Classify complexity, then route to Qwen (simple) or Claude (complex)."""
        # Fast pre-check: dissatisfaction / follow-up → always Claude
        if self._is_dissatisfied_or_followup(user_text):
            logger.info(f"MoltBot: dissatisfied/followup → claude for: {user_text[:60]}")
            return self._ask_moltbot(sender_name, user_text, chat_context, user_key, history)

        complexity = self._classify_complexity(user_text, history)
        logger.info(f"MoltBot: complexity={complexity} for: {user_text[:60]}")
        if complexity == "simple":
            try:
                reply = self._ask_moltbot(sender_name, user_text, chat_context,
                                          user_key, history, model="ollama/qwen3.5:9b")
                if reply and reply.strip():
                    return reply
            except (_AIConnectionError, _AIRefusalError) as e:
                logger.info(f"MoltBot: Qwen failed ({e}), falling back to Claude")
            else:
                logger.info("MoltBot: Qwen returned empty, falling back to Claude")
        return self._ask_moltbot(sender_name, user_text, chat_context, user_key, history)

    def _maybe_reply_probabilistic(self, message) -> bool:
        """Ask local LLM if the bot should reply to this message. Returns True if replied."""
        # Cooldown: max once per 15 minutes per chat
        chat_id = message.chat.id
        last = self._last_probabilistic_sent.get(chat_id)
        if last and (datetime.now(timezone.utc) - last) < timedelta(minutes=15):
            return False

        sender_name = self._resolve_sender_name(message.from_user)
        user_text = message.text or ""

        history = self._get_recent_group_messages(limit=30, chat_id=chat_id)
        history_block = "\n".join(history) if history else "(нет истории)"
        summary = _load_chat_summary()
        summary_block = f"[Долгосрочная память о чате:\n{summary}\n]\n" if summary else ""

        prompt = (
            f"{summary_block}"
            f"[История чата (последние {len(history)} сообщений):\n{history_block}\n]\n\n"
            f"Новое сообщение от {sender_name}: {user_text}\n\n"
            "[Ты участник этого группового чата. Реши: стоит ли тебе вмешаться в разговор?\n"
            "- Если разговор между людьми и тебя не касается — НЕ отвечай\n"
            "- Если вопрос адресован другому участнику — НЕ отвечай\n"
            "- НЕ самоидентифицируйся со словами из разговора (игрушка, лиса, бот и т.п.) если тебя прямо не имеют в виду\n"
            "- При сомнении — НЕ отвечай, лучше промолчать чем встрять невпопад\n"
            "- Отвечай только если тебе есть что добавить уместно и по делу (1-2 предложения)\n"
            "- Если не стоит отвечать — верни ровно пустую строку без пробелов\n"
            "Ответ (только текст сообщения или пустая строка):]"
        )

        user_key = CHAT_KEYS.get(chat_id, f"tg-group-{chat_id}")
        try:
            reply = self._call_openclaw(prompt, user_key, model="ollama/qwen3.5:9b")
            reply = reply.strip()
            if not reply:
                return False
            self.bot.reply_to(message, reply)
            self._last_probabilistic_sent[chat_id] = datetime.now(timezone.utc)
            logger.info(f"MoltBot: probabilistic reply sent in chat {chat_id}")
            return True
        except Exception as e:
            logger.error(f"MoltBot: probabilistic reply error: {e}")
            return False

    # Valid Telegram emoji reactions
    _REACTION_EMOJIS = [
        '👍', '👎', '❤', '🔥', '🥰', '👏', '😁', '🤯', '😱',
        '😢', '🎉', '🤩', '💩', '🙏', '👌', '🤡', '🥱', '😍', '💯',
        '🤣', '⚡', '🏆', '💔', '😴', '🤓', '👻', '👀', '😇', '🤗',
        '🤪', '🗿', '🆒', '😘', '😎', '🫡', '🤝', '🫶', '💅', '🥶',
        '🤨', '😏', '🥲', '😤', '🤬', '😈', '☠', '🤮', '🫠', '🤌',
        '💀', '🙈', '🙉', '🙊', '🐳', '🦄', '🍾', '🎸', '🎯', '🎲',
        '🚀', '🛸', '🌚', '🌝', '🌞', '🍕', '🤑', '💸', '🎃', '👾',
        '🧠', '💪', '🦾', '🦿', '🎭', '🎪', '🫣', '🤫', '🤭', '🫀',
    ]

    # Probability of asking Qwen at all (saves calls on boring messages)
    _REACTION_PROBABILITY = 0.25
    # Minimum seconds between reactions in the same chat
    _REACTION_COOLDOWN_SECS = 300

    def _maybe_react(self, message) -> None:
        """Probabilistically ask Qwen to pick a reaction; enforces per-chat cooldown."""
        chat_id = message.chat.id
        text = message.text or ""

        # Skip short/trivial messages early
        if len(text) < 3:
            return

        # Cooldown: don't spam reactions in the same chat
        last = self._last_reaction_time.get(chat_id)
        if last and (datetime.now(timezone.utc) - last).total_seconds() < self._REACTION_COOLDOWN_SECS:
            return

        # Random gate — only consider reacting ~45% of the time
        if random.random() > self._REACTION_PROBABILITY:
            return

        if not hasattr(self, '_last_used_emoji'):
            self._last_used_emoji: dict[int, list[str]] = {}
        recent = self._last_used_emoji.get(chat_id, [])
        avoid_hint = f"Не используй эти (недавно ставил): {' '.join(recent)}\n" if recent else ""

        # Shuffle so Qwen doesn't always pick from the same start of list
        shuffled = self._REACTION_EMOJIS.copy()
        random.shuffle(shuffled)
        emoji_list = ' '.join(shuffled)

        prompt = (
            f"Сообщение: {text}\n\n"
            "По умолчанию верни пустую строку — не реагируй.\n"
            "Поставь реакцию ТОЛЬКО если сообщение тебя реально зацепило: "
            "очень смешно, неожиданно, дерзко, трогательно или эпично.\n"
            "Обычный разговор, бытовые фразы, вопросы, короткие ответы — пустая строка.\n"
            "Если решил реагировать — выбери один emoji из списка: "
            f"{emoji_list}\n"
            f"{avoid_hint}"
            "Выбирай точно под настроение сообщения, не дефолтные.\n"
            "Верни ТОЛЬКО один emoji или пустую строку. Никакого текста."
        )

        try:
            result = self._call_ollama_direct(prompt)
            result = result.strip()
            result = result.split()[0] if result else ""
            if result not in self._REACTION_EMOJIS:
                logger.debug(f"MoltBot: no reaction (got {repr(result)}) for msg {message.message_id}")
                return
            token = Settings.TELEGRAM_BOT_TOKEN
            with httpx.Client() as client:
                client.post(
                    f"https://api.telegram.org/bot{token}/setMessageReaction",
                    json={
                        "chat_id": chat_id,
                        "message_id": message.message_id,
                        "reaction": [{"type": "emoji", "emoji": result}],
                        "is_big": False,
                    },
                    timeout=10,
                )
            self._last_reaction_time[chat_id] = datetime.now(timezone.utc)
            recent_list = self._last_used_emoji.get(chat_id, [])
            recent_list.append(result)
            self._last_used_emoji[chat_id] = recent_list[-3:]
            logger.info(f"MoltBot: reacted {result} to msg {message.message_id} in {chat_id}")
        except Exception as e:
            logger.warning(f"MoltBot: reaction error: {e}")

    # ── Данетка ───────────────────────────────────────────────────────────────

    def _ensure_danetki_table(self):
        try:
            self.db.execute_query(
                "CREATE TABLE IF NOT EXISTS danetki ("
                "id SERIAL PRIMARY KEY, "
                "situation TEXT NOT NULL, "
                "answer TEXT NOT NULL, "
                "used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
                ()
            )
        except Exception as e:
            logger.error(f"MoltBot: failed to create danetki table: {e}")

    def _get_used_situations(self, limit: int = 25) -> list[str]:
        try:
            rows = self.db.execute_query(
                "SELECT situation FROM danetki ORDER BY used_at DESC LIMIT %s",
                (limit,)
            )
            return [r[0] for r in rows] if rows else []
        except Exception:
            return []

    def _generate_danetka(self) -> dict | None:
        used = self._get_used_situations()
        used_text = "\n".join(f"- {s[:80]}" for s in used) if used else "(нет)"
        prompt = (
            "Придумай данетку (логическую загадку) для игры в групповом чате.\n\n"
            "Верни ТОЛЬКО JSON без лишнего текста:\n"
            '{"situation": "загадочная ситуация в 1-3 предложениях", '
            '"answer": "полное объяснение что произошло на самом деле"}\n\n'
            "Требования:\n"
            "- Ситуация должна быть загадочной и неочевидной\n"
            "- Хорошие темы: бытовые парадоксы, природные явления, исторические казусы, "
            "психологические ситуации, криминальные загадки\n"
            "- Пиши на русском языке\n"
            f"- Не повторяй эти уже использованные ситуации:\n{used_text}"
        )
        try:
            raw = self._call_ollama_direct(prompt)
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if not match:
                return None
            data = json.loads(match.group())
            if 'situation' in data and 'answer' in data:
                return data
        except Exception as e:
            logger.error(f"MoltBot: danetka generation error: {e}")
        return None

    def _save_danetka(self, situation: str, answer: str):
        try:
            self.db.execute_query(
                "INSERT INTO danetki (situation, answer) VALUES (%s, %s)",
                (situation, answer)
            )
        except Exception as e:
            logger.error(f"MoltBot: failed to save danetka: {e}")

    def _judge_danetka(self, question: str, answer: str) -> str:
        prompt = (
            f"Ты ведущий игры «данетка».\n"
            f"Правильный ответ (только ты знаешь): {answer}\n\n"
            f"Игрок написал: {question}\n\n"
            "Выбери ОДИН вариант:\n"
            "- «Да» — если утверждение верное\n"
            "- «Нет» — если неверное\n"
            "- «Не важно» — если не относится к ситуации\n"
            "- «Близко! 🔥» — если очень близко к разгадке\n"
            "- «УГАДАЛ! 🎉» — ТОЛЬКО если игрок полностью раскрыл суть\n\n"
            "Верни только один из этих вариантов, ничего больше."
        )
        try:
            result = self._call_ollama_direct(prompt).strip()
            for v in ["УГАДАЛ! 🎉", "Близко! 🔥", "Да", "Нет", "Не важно"]:
                if v.lower() in result.lower():
                    return v
            return "Не важно"
        except Exception as e:
            logger.error(f"MoltBot: danetka judge error: {e}")
            return "Не важно"

    def _handle_danetka_reply(self, message):
        chat_id = message.chat.id
        active = self._active_danetka.get(chat_id)
        if not active:
            return
        question = (message.text or "").strip()
        if not question:
            return
        active['questions_count'] = active.get('questions_count', 0) + 1
        judgment = self._judge_danetka(question, active['answer'])
        self.bot.reply_to(message, judgment)
        if "УГАДАЛ" in judgment:
            del self._active_danetka[chat_id]
            self.bot.send_message(
                chat_id,
                f"🎉 Правильно! Вот полный ответ:\n\n{active['answer']}\n\n"
                f"Вопросов задано: {active['questions_count']}"
            )

    # ── Недельная аналитика ───────────────────────────────────────────────────

    def _send_weekly_analytics(self, chat_id: int):
        try:
            total_rows = self.db.execute_query(
                "SELECT COUNT(*) FROM messages WHERE timestamp > NOW() - INTERVAL '7 days'",
                ()
            )
            total = total_rows[0][0] if total_rows else 0
            if total == 0:
                self.bot.send_message(chat_id, "📊 За эту неделю сообщений не было.")
                return

            per_person = self.db.execute_query(
                "SELECT name, COUNT(*) FROM messages "
                "WHERE timestamp > NOW() - INTERVAL '7 days' "
                "GROUP BY name ORDER BY COUNT(*) DESC LIMIT 10",
                ()
            )
            top_hours = self.db.execute_query(
                "SELECT EXTRACT(HOUR FROM timestamp)::int, COUNT(*) FROM messages "
                "WHERE timestamp > NOW() - INTERVAL '7 days' "
                "GROUP BY 1 ORDER BY 2 DESC LIMIT 3",
                ()
            )

            # Qwen topic summary
            recent = self._get_recent_group_messages(limit=300, chat_id=chat_id)
            topics = ""
            if recent:
                snippet = "\n".join(recent[-200:])
                try:
                    raw_topics = self._call_ollama_direct(
                        f"Вот сообщения из чата за неделю:\n{snippet}\n\n"
                        "Выдели 3-5 главных тем этой недели. "
                        "Каждую тему — одной строкой с подходящим emoji. "
                        "Только список на русском языке, без вступлений и пояснений."
                    )
                    import re as _re
                    topics = _re.sub(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\u3000-\u303f\uff00-\uffef]+', '', raw_topics).strip()
                except Exception:
                    pass

            lines = ["📊 *Аналитика чата за неделю*", f"Всего сообщений: *{total}*", ""]

            if per_person:
                lines.append("👥 *Кто писал:*")
                medals = ["🥇", "🥈", "🥉"]
                for i, row in enumerate(per_person):
                    medal = medals[i] if i < 3 else "▫️"
                    lines.append(f"{medal} {row[0]}: {row[1]} сообщ.")
                lines.append("")

            if top_hours:
                hours_str = ", ".join(f"{r[0]}:00" for r in top_hours)
                lines.append(f"🕐 *Самые активные часы:* {hours_str}")
                lines.append("")

            if topics:
                lines.append("💬 *Темы недели:*")
                lines.append(topics)

            self.bot.send_message(chat_id, "\n".join(lines), parse_mode="Markdown")
            logger.info(f"MoltBot: weekly analytics sent to {chat_id}")
        except Exception as e:
            logger.error(f"MoltBot: weekly analytics error: {e}")

    def start_proactive_scheduler(self, chat_id: int):
        """Start scheduled (2x/day) and activity-spike proactive messaging."""
        def _scheduled_loop():
            """Fire proactive messages at fixed times using a simple polling loop."""
            sent_today: set[str] = set()
            while True:
                now = datetime.now()
                day_key = now.strftime("%Y-%m-%d")
                hhmm = now.strftime("%H:%M")
                for t in PROACTIVE_SCHEDULE_TIMES:
                    job_key = f"{day_key}-{t}"
                    if hhmm == t and job_key not in sent_today:
                        sent_today.add(job_key)
                        # Only send if chat was active recently
                        if self._count_recent_messages(8 * 60) >= 5:
                            self._send_proactive_message(chat_id)
                        else:
                            logger.info(f"MoltBot: skipping {t} proactive — chat inactive")
                # Weekly analytics: Sunday 21:00
                weekly_key = f"{day_key}-weekly"
                if now.weekday() == 6 and hhmm == "21:00" and weekly_key not in sent_today:
                    sent_today.add(weekly_key)
                    threading.Thread(target=self._send_weekly_analytics, args=(chat_id,),
                                     daemon=True, name="moltbot-analytics").start()
                # Purge old day keys to avoid unbounded growth
                if len(sent_today) > 20:
                    sent_today = {k for k in sent_today if k.startswith(day_key)}
                time.sleep(30)

        def _monitor_loop():
            while True:
                time.sleep(600)
                try:
                    self._check_activity_spike(chat_id)
                except Exception as e:
                    logger.error(f"MoltBot: proactive monitor error: {e}")

        threading.Thread(target=_scheduled_loop, daemon=True, name="moltbot-scheduler").start()
        threading.Thread(target=_monitor_loop, daemon=True, name="moltbot-monitor").start()
        logger.info(f"MoltBot: proactive scheduler started for chat {chat_id}")

    # ── Handlers ──────────────────────────────────────────────────────────────

    def setup_handlers(self):
        @self.bot.message_handler(func=lambda m: self._is_bot_mentioned(m))
        def handle_mention(message):
            sender_name = self._resolve_sender_name(message.from_user)
            user_text = self._extract_user_text(message)
            chat_context = self._get_chat_context(message)
            user_key = self._resolve_user_key(message)

            # Fetch group history only for group chats
            history = None
            if message.chat.type in ('group', 'supergroup'):
                history = self._get_recent_group_messages(limit=100, chat_id=message.chat.id)

            # threading.Thread(target=self._maybe_react, args=(message,), daemon=True).start()
            try:
                reply = self._ask_moltbot_routed(sender_name, user_text, chat_context, user_key, history)
                if reply and reply.strip():
                    sent = self.bot.reply_to(message, reply)
                    self._store_bot_reply(reply, sent.message_id)
            except _AIConnectionError:
                self.bot.reply_to(message, "⚠️ Не могу подключиться к AI, попробуй позже")
            except _AIRefusalError:
                self.bot.reply_to(message, "🤐 AI отказался отвечать на это сообщение")
            except Exception as e:
                logger.error(f"MoltBot API error: {e}")
                self.bot.reply_to(message, "Не могу связаться с AI. Попробуй позже.")

        @self.bot.message_handler(commands=['данетка', 'danetka'])
        def handle_danetka_start(message):
            chat_id = message.chat.id
            if chat_id in self._active_danetka:
                self.bot.reply_to(message, "⚠️ Игра уже идёт! Используй /сдаюсь чтобы сдаться.")
                return
            waiting = self.bot.reply_to(message, "🎲 Придумываю данетку...")

            def generate_and_post():
                danetka = self._generate_danetka()
                if not danetka:
                    self.bot.edit_message_text("❌ Не смог придумать, попробуй ещё раз.",
                                               chat_id, waiting.message_id)
                    return
                self._save_danetka(danetka['situation'], danetka['answer'])
                self.bot.edit_message_text(
                    f"🎲 *Данетка!*\n\n{danetka['situation']}\n\n"
                    "_Задавайте вопросы — отвечаю только Да / Нет / Не важно_\n"
                    "Используй /сдаюсь чтобы узнать ответ",
                    chat_id, waiting.message_id, parse_mode="Markdown"
                )
                # waiting.message_id == edited message_id (editing doesn't change it)
                self._active_danetka[chat_id] = {
                    'situation': danetka['situation'],
                    'answer': danetka['answer'],
                    'message_id': waiting.message_id,
                    'started_at': datetime.now(timezone.utc),
                    'questions_count': 0,
                }

            threading.Thread(target=generate_and_post, daemon=True).start()

        @self.bot.message_handler(commands=['сдаюсь', 'sdayus'])
        def handle_danetka_surrender(message):
            chat_id = message.chat.id
            active = self._active_danetka.pop(chat_id, None)
            if not active:
                self.bot.reply_to(message, "Нет активной игры.")
                return
            self.bot.reply_to(
                message,
                f"🏳️ Сдаётесь! Вот ответ:\n\n{active['answer']}\n\n"
                f"Вопросов было задано: {active.get('questions_count', 0)}"
            )

        @self.bot.message_handler(commands=['аналитика', 'analitika'])
        def handle_analytics_command(message):
            if message.from_user.id not in Settings.ADMIN_IDS:
                self.bot.reply_to(message, "У вас нет доступа.")
                return
            self.bot.reply_to(message, "📊 Собираю статистику...")
            threading.Thread(target=self._send_weekly_analytics, args=(message.chat.id,),
                             daemon=True).start()

        @self.bot.message_handler(func=lambda m: (
            m.reply_to_message is not None
            and m.reply_to_message.from_user is not None
            and m.reply_to_message.from_user.id == self.bot.get_me().id
            and not self._is_bot_mentioned(m)
        ))
        def handle_reply_to_bot(message):
            chat_id = message.chat.id
            # Route to danetka: any reply to bot while game is active
            if chat_id in self._active_danetka:
                threading.Thread(target=self._handle_danetka_reply, args=(message,),
                                 daemon=True).start()
                return

            sender_name = self._resolve_sender_name(message.from_user)
            user_text = message.text or ""
            chat_context = self._get_chat_context(message)
            user_key = self._resolve_user_key(message)

            history = None
            if message.chat.type in ('group', 'supergroup'):
                history = self._get_recent_group_messages(limit=100, chat_id=message.chat.id)

            # threading.Thread(target=self._maybe_react, args=(message,), daemon=True).start()
            try:
                reply = self._ask_moltbot_routed(sender_name, user_text, chat_context, user_key, history)
                if reply and reply.strip():
                    sent = self.bot.reply_to(message, reply)
                    self._store_bot_reply(reply, sent.message_id)
            except _AIConnectionError:
                self.bot.reply_to(message, "⚠️ Не могу подключиться к AI, попробуй позже")
            except _AIRefusalError:
                self.bot.reply_to(message, "🤐 AI отказался отвечать на это сообщение")
            except Exception as e:
                logger.error(f"MoltBot API error (reply): {e}")
                self.bot.reply_to(message, "Не могу связаться с AI. Попробуй позже.")

        def _has_other_mention(m) -> bool:
            """True if message mentions any user that is NOT the bot."""
            if not m.entities or not m.text:
                return False
            bot_username = self._get_bot_username().lower()
            return any(
                e.type == 'mention'
                and m.text[e.offset:e.offset + e.length].lstrip('@').lower() != bot_username
                for e in m.entities
            )

        @self.bot.message_handler(func=lambda m: (
            m.chat.type in ('group', 'supergroup')
            and m.text
            and not m.text.startswith('/')
            and not m.from_user.is_bot
            and not self._is_bot_mentioned(m)
            and not _has_other_mention(m)
            and not (m.reply_to_message and m.reply_to_message.from_user
                     and m.reply_to_message.from_user.id == self.bot.get_me().id)
        ))
        def handle_probabilistic(message):
            self._maybe_update_summary()
            threading.Thread(
                target=self._maybe_reply_probabilistic,
                args=(message,),
                daemon=True,
            ).start()
            # threading.Thread(
            #     target=self._maybe_react,
            #     args=(message,),
            #     daemon=True,
            # ).start()

        @self.bot.message_handler(func=lambda m: (
            m.chat.type == 'private'
            and m.text
            and not m.text.startswith('/')
            and not m.from_user.is_bot
        ))
        def handle_dm_reaction(message):
            pass
            # threading.Thread(
            #     target=self._maybe_react,
            #     args=(message,),
            #     daemon=True,
            # ).start()

        @self.bot.message_handler(
            content_types=['photo'],
            func=lambda m: self._is_bot_mentioned_in_caption(m),
        )
        def handle_photo_mention(message):
            sender_name = self._resolve_sender_name(message.from_user)
            user_question = self._extract_caption_text(message)
            chat_context = self._get_chat_context(message)
            user_key = self._resolve_user_key(message)

            history = None
            if message.chat.type in ('group', 'supergroup'):
                history = self._get_recent_group_messages(limit=100, chat_id=message.chat.id)

            try:
                file_info = self.bot.get_file(message.photo[-1].file_id)
                image_bytes = self.bot.download_file(file_info.file_path)
            except Exception as e:
                logger.error(f"MoltBot: failed to download photo: {e}")
                self.bot.reply_to(message, "Не могу загрузить картинку. Попробуй ещё раз.")
                return

            image_analysis = self._analyze_image_with_gemini(image_bytes, user_question)

            if user_question:
                combined_text = f"[Картинка: {image_analysis}]\n{user_question}"
            else:
                combined_text = f"[Картинка: {image_analysis}]"

            try:
                reply = self._ask_moltbot(sender_name, combined_text, chat_context, user_key, history)
                if reply and reply.strip():
                    sent = self.bot.reply_to(message, reply)
                    self._store_bot_reply(reply, sent.message_id)
            except _AIConnectionError:
                self.bot.reply_to(message, "⚠️ Не могу подключиться к AI, попробуй позже")
            except _AIRefusalError:
                self.bot.reply_to(message, "🤐 AI отказался отвечать на это сообщение")
            except Exception as e:
                logger.error(f"MoltBot API error (photo): {e}")
                self.bot.reply_to(message, "Не могу связаться с AI. Попробуй позже.")

        @self.bot.message_handler(commands=['мут_сброс', 'mut_reset'])
        def handle_reset(message):
            """Reset chat history context and OpenClaw thread. Survives bot restarts."""
            now = datetime.now(timezone.utc)
            self._history_reset_time[message.chat.id] = now
            self._user_key_suffix[message.chat.id] = f"-{int(now.timestamp())}"
            self._save_state()
            logger.info(f"MoltBot: history reset for chat {message.chat.id} by {message.from_user.id}")
            self.bot.reply_to(message, "⚙️ Контекст сброшен. Начинаю с чистого листа.")
