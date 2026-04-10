import asyncio
import json
import logging
import os
import random
import re
import httpx
import google.generativeai as genai
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from aiogram import Router, F, Bot
from aiogram.filters import Command, StateFilter
from aiogram.types import Message

from config.settings import Settings
from services.circuit_breaker import ollama_breaker, together_breaker

_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
CHAT_SUMMARY_PATH = os.path.join(_BASE_DIR, 'data', 'chat-summary.md')
STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "moltbot_state.json")


class _AIConnectionError(Exception):
    """Raised when AI backend is unreachable or timed out."""

class _AIRefusalError(Exception):
    """Raised when AI explicitly refuses to respond."""


def _get_summary_mtime() -> datetime | None:
    """Return the modification time of chat-summary.md, or None if missing."""
    try:
        mtime = os.path.getmtime(CHAT_SUMMARY_PATH)
        return datetime.fromtimestamp(mtime, tz=timezone.utc)
    except Exception:
        return None


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
SUMMARY_UPDATE_HOURS = 24     # update chat-summary.md every N hours
SUMMARY_FETCH_HOURS = 48      # fetch messages from last N hours for summary
CPH_TZ = ZoneInfo("Europe/Copenhagen")


class MoltbotHandlers:
    def __init__(self, bot: Bot, db_manager):
        self.bot = bot
        self.db = db_manager
        self.router = Router()
        self._bot_username = None  # lazily cached
        self._history_reset_time: dict[int, datetime] = {}  # chat_id → reset timestamp
        self._gemini_model = None
        self._last_proactive_sent: dict[int, datetime] = {}
        self._proactive_queued: set[int] = set()
        self._last_probabilistic_sent: dict[int, datetime] = {}
        self._last_reaction_time: dict[int, datetime] = {}
        self._last_summary_update: datetime | None = _get_summary_mtime()
        self._active_danetka: dict[int, dict] = {}
        self._photo_context: dict[int, str] = {}  # bot_reply_msg_id → original photo file_id
        self._prob_session_start: dict[int, datetime] = {}  # chat_id → when probabilistic session started
        self._load_state()
        self._init_gemini()
        asyncio.ensure_future(self._ensure_danetki_table())
        self._register()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load_state(self):
        """Load persisted reset state from disk (survives bot restarts)."""
        try:
            with open(STATE_PATH, encoding="utf-8") as f:
                data = json.load(f)
            for chat_id_str, ts in data.get("history_reset_time", {}).items():
                self._history_reset_time[int(chat_id_str)] = datetime.fromisoformat(ts)
            logger.info(f"MoltBot: loaded state for {len(self._history_reset_time)} chat(s)")
        except FileNotFoundError:
            pass  # first run, nothing to load
        except Exception as e:
            logger.warning(f"MoltBot: could not load state: {e}")

    def _save_state(self):
        """Persist reset state to disk."""
        try:
            data = {
                "history_reset_time": {
                    str(k): v.isoformat() for k, v in self._history_reset_time.items()
                },
            }
            with open(STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"MoltBot: could not save state: {e}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _get_bot_username(self) -> str:
        if not self._bot_username:
            me = await self.bot.get_me()
            self._bot_username = me.username
        return self._bot_username

    def _resolve_sender_name(self, user) -> str:
        """Return friendly name for known members, otherwise first_name."""
        return KNOWN_MEMBERS.get(user.id, user.first_name or "Кто-то")

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

    @staticmethod
    def _format_ts(dt: datetime | None) -> str:
        """Format a DB timestamp as [HH:MM DD.MM] in Copenhagen timezone."""
        if dt is None:
            return ""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        local = dt.astimezone(CPH_TZ)
        return local.strftime("[%H:%M %d.%m]")

    @staticmethod
    def _should_greet(user_text: str, reply_to) -> str | None:
        """Return greeting if empty tag with no reply, else None."""
        if not user_text.strip() and reply_to is None:
            return "Чё надо?"
        return None

    async def _build_reply_context(self, message) -> str:
        """Extract reply-to message info for AI context.

        Returns formatted string like:
        [Юра отвечает на сообщение Богдана [16:30 14.03]: "текст"]
        Or empty string if message is not a reply.
        """
        reply = message.reply_to_message
        if reply is None:
            return ""

        # Author name (who wrote the replied-to message)
        if reply.from_user is None:
            author = "Аноним"
        elif reply.from_user.is_bot:
            author = reply.from_user.first_name or "Jarvis"
        else:
            author = self._resolve_sender_name(reply.from_user)

        # Sender name (who is replying)
        sender = self._resolve_sender_name(message.from_user) if message.from_user else "Аноним"

        # Timestamp
        ts = self._format_ts(reply.date) if reply.date else ""

        # Content extraction
        parts = []

        # Photo in reply
        if reply.photo:
            try:
                file = await self.bot.get_file(reply.photo[-1].file_id)
                bio = await self.bot.download_file(file.file_path)
                image_bytes = bio.read()
                desc = await asyncio.to_thread(
                    self._analyze_image_with_gemini, image_bytes, ""
                )
                parts.append(f"[Картинка: {desc}]")
            except Exception as e:
                logger.warning(f"MoltBot: failed to analyze reply photo: {e}")
                parts.append("[Картинка]")

        # Text or caption
        text = reply.text or reply.caption or ""
        if text:
            parts.append(f'"{text}"')

        # Fallback content types (no text, no photo)
        if not parts:
            if reply.sticker:
                emoji = reply.sticker.emoji or ""
                parts.append(f"[Стикер: {emoji}]")
            elif reply.voice:
                parts.append("[Голосовое сообщение]")
            elif reply.video_note:
                parts.append("[Видеосообщение]")
            elif reply.animation:
                parts.append("[GIF]")
            elif reply.document:
                fname = reply.document.file_name or "файл"
                parts.append(f"[Документ: {fname}]")
            elif reply.video:
                parts.append("[Видео]")
            else:
                parts.append("[Сообщение без текста]")

        content = " ".join(parts)
        return f"[{sender} отвечает на сообщение {author} {ts}: {content}]"

    async def _is_bot_mentioned(self, message) -> bool:
        """Return True if @ggallmute2_bot appears in message entities."""
        if not message.entities or not message.text:
            return False
        bot_username = (await self._get_bot_username()).lower()
        for entity in message.entities:
            if entity.type == 'mention':
                name = message.text[entity.offset:entity.offset + entity.length].lstrip('@').lower()
                if name == bot_username:
                    return True
        return False

    async def _is_bot_mentioned_in_caption(self, message) -> bool:
        """Return True if @botname appears in photo/video caption entities."""
        if not message.caption_entities or not message.caption:
            return False
        bot_username = (await self._get_bot_username()).lower()
        for entity in message.caption_entities:
            if entity.type == 'mention':
                name = message.caption[entity.offset:entity.offset + entity.length].lstrip('@').lower()
                if name == bot_username:
                    return True
        return False

    async def _extract_user_text(self, message) -> str:
        """Strip @botname mention(s) from message text."""
        text = message.text or ""
        bot_username = (await self._get_bot_username()).lower()
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

    async def _extract_caption_text(self, message) -> str:
        """Strip @botname mention(s) from photo caption."""
        text = message.caption or ""
        bot_username = (await self._get_bot_username()).lower()
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
            self._gemini_model = genai.GenerativeModel('gemini-3-flash-preview')
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
            result = response.text
            logger.info(f"MoltBot: Gemini image analysis: {result[:200]}")
            return result
        except Exception as e:
            logger.error(f"MoltBot: Gemini image analysis failed: {e}")
            return "[Не удалось проанализировать изображение]"

    async def _store_user_message(self, message):
        """Store a user message in the messages table (for analytics)."""
        try:
            if message.text and message.from_user and not message.from_user.is_bot:
                name = message.from_user.first_name or message.from_user.username or 'Аноним'
                await self.db.execute_query(
                    "INSERT INTO messages (user_id, message_text, timestamp, name, message_id) "
                    "VALUES (%s, %s, CURRENT_TIMESTAMP, %s, %s)",
                    (message.from_user.id, message.text, name, message.message_id),
                )
        except Exception as e:
            logger.warning(f"MoltBot: failed to store user message: {e}")

    async def _store_bot_reply(self, text: str, msg_id: int | None = None):
        """Store Jarvis bot reply in the messages table."""
        try:
            await self.db.execute_query(
                "INSERT INTO messages (user_id, message_text, timestamp, name, message_id) "
                "VALUES (%s, %s, CURRENT_TIMESTAMP, %s, %s)",
                (0, text, "Jarvis", msg_id),
            )
        except Exception as e:
            logger.warning(f"MoltBot: failed to store bot reply: {e}")

    async def _get_recent_group_messages(self, limit: int = 50, chat_id: int | None = None) -> list[str]:
        """Fetch last `limit` messages from the group chat history in DB."""
        try:
            reset_time = self._history_reset_time.get(chat_id) if chat_id else None
            if reset_time:
                query = """
                    SELECT name, message_text, timestamp
                    FROM messages
                    WHERE timestamp >= %s
                    ORDER BY timestamp DESC
                    LIMIT %s
                """
                rows = await self.db.execute_query(query, (reset_time, limit))
            else:
                query = """
                    SELECT name, message_text, timestamp
                    FROM messages
                    ORDER BY timestamp DESC
                    LIMIT %s
                """
                rows = await self.db.execute_query(query, (limit,))
            if not rows:
                return []
            # Rows come newest-first; reverse to get chronological order
            return [
                f"{self._format_ts(row[2])} {row[0] or 'Аноним'}: {row[1]}"
                for row in reversed(rows)
            ]
        except Exception as e:
            logger.error(f"MoltBot: error fetching chat history: {e}")
            return []

    async def _call_together_simple(self, prompt: str) -> str:
        """Call Together.ai with a raw prompt + IDENTITY. Used for proactive/probabilistic messages."""
        if not Settings.TOGETHER_API_KEY:
            raise _AIConnectionError("TOGETHER_API_KEY not set")
        if not together_breaker.allow_request():
            raise _AIConnectionError("together circuit breaker open")
        try:
            with open(self._IDENTITY_PATH, encoding="utf-8") as f:
                identity = f.read()
        except Exception:
            identity = ""
        system_msg = "\n\n".join([self._HARD_RULES, identity])
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    "https://api.together.xyz/v1/chat/completions",
                    headers={"Authorization": f"Bearer {Settings.TOGETHER_API_KEY}"},
                    json={
                        "model": Settings.TOGETHER_MODEL,
                        "messages": [
                            {"role": "system", "content": system_msg},
                            {"role": "user", "content": prompt},
                        ],
                        "max_tokens": 500,
                        "temperature": 0.9,
                    },
                    timeout=120,
                )
                r.raise_for_status()
                text = r.json()["choices"][0]["message"]["content"]
                text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
                text = re.sub(r'\*[^*]{2,80}\*', '', text)
                text = re.sub(r'\n\s*\n\s*\n', '\n\n', text).strip()
                together_breaker.record_success()
                return text
        except Exception as e:
            together_breaker.record_failure()
            logger.error(f"MoltBot: Together.ai simple call failed: {e}")
            raise _AIConnectionError(str(e))

    def _call_ollama_direct(self, content: str, bot=None, message=None) -> str:
        """Call Ollama directly. Routes through OllamaWakeManager for auto-wake.
        This is a sync method — wrap with asyncio.to_thread when calling from async context."""
        if not ollama_breaker.allow_request():
            logger.warning("MoltBot: Ollama circuit open, skipping direct call")
            return ""
        from services.ollama_wake_manager import OllamaWakeManager, WakeState
        manager = OllamaWakeManager()

        # Future use: if message context provided, use async wake flow
        if bot is not None and message is not None:
            result = manager.call(content, bot=bot, message=message)
            if result:
                ollama_breaker.record_success()
            else:
                ollama_breaker.record_failure()
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
            result = manager._call_ollama_raw(content)
            ollama_breaker.record_success()
            return result
        except Exception as e:
            ollama_breaker.record_failure()
            logger.warning(f"MoltBot: Ollama call failed: {e}, triggering wake")
            manager._set_state(WakeState.OFFLINE)
            manager._trigger_wake()
            return ""

    async def _call_gemini_text(self, sender_name: str, user_text: str,
                               chat_context: str, history: list[str] | None = None) -> str:
        """Call Gemini for text generation. INTERNET fallback — Gemini has fresher knowledge."""
        if not self._gemini_model:
            raise _AIConnectionError("Gemini not initialized")
        try:
            with open(self._IDENTITY_PATH, encoding="utf-8") as f:
                identity = f.read()
        except Exception:
            identity = ""
        summary = _load_chat_summary()
        parts = []
        if identity:
            parts.append(f"[Твоя личность:\n{identity}]")
        parts.append("Обычно 3-5 предложений, до 8-9 если тема горячая. Простой вопрос — 1-2. Не выдумывай факты.")
        if chat_context:
            parts.append(f"[Сообщение из: {chat_context}]")
        if summary:
            parts.append(f"[Долгосрочная память о чате:\n{summary}]")
        if history:
            parts.append("[История чата:\n" + "\n".join(history[-20:]) + "]")
        parts.append(f"{sender_name}: {user_text}")

        prompt = "\n\n".join(parts)
        response = await asyncio.to_thread(self._gemini_model.generate_content, prompt)
        return response.text

    async def _count_recent_messages(self, minutes: int) -> int:
        """Count messages in DB written in the last `minutes` minutes."""
        try:
            rows = await self.db.execute_query(
                "SELECT COUNT(*) FROM messages WHERE timestamp > NOW() - INTERVAL '1 minute' * %s",
                (minutes,)
            )
            return rows[0][0] if rows else 0
        except Exception as e:
            logger.error(f"MoltBot: error counting recent messages: {e}")
            return 0

    async def _send_proactive_message(self, chat_id: int):
        """Build context and send a proactive (unprompted) message to the chat."""
        try:
            history = await self._get_recent_group_messages(30, chat_id)
            summary = _load_chat_summary()

            context_prefix = ""
            if summary:
                context_prefix += f"[Долгосрочная память о чате:\n{summary}\n]\n"
            if history:
                history_block = "\n".join(history)
                context_prefix += f"[История чата (последние {len(history)} сообщений):\n{history_block}\n]\n"

            topic = await asyncio.to_thread(self._get_current_topic, history) if history else ""
            topic_hint = f"[Текущая тема разговора: {topic}]\n" if topic else ""

            user_content = (
                f"{context_prefix}{topic_hint}"
                "[Ты сам захотел что-то написать в чат — не в ответ на обращение, "
                "а потому что тебе пришла мысль или хочется поучаствовать. "
                "Напиши одно короткое сообщение как участник разговора.]"
            )

            reply = await self._call_together_simple(user_content)

            # Reply to the most recent stored message if we have its Telegram message_id
            reply_to = None
            try:
                rows = await self.db.execute_query(
                    "SELECT message_id FROM messages WHERE message_id IS NOT NULL ORDER BY timestamp DESC LIMIT 1"
                )
                if rows and rows[0][0]:
                    reply_to = rows[0][0]
            except Exception:
                pass

            await self.bot.send_message(chat_id, reply, reply_to_message_id=reply_to)
            self._last_proactive_sent[chat_id] = datetime.now(timezone.utc)
            logger.info(f"MoltBot: proactive message sent to chat {chat_id}")
        except Exception as e:
            logger.error(f"MoltBot: failed to send proactive message to {chat_id}: {e}")

    async def _check_activity_spike(self, chat_id: int):
        """Queue a proactive message if chat activity is high and cooldown has passed."""
        if chat_id in self._proactive_queued:
            return
        last = self._last_proactive_sent.get(chat_id)
        if last and (datetime.now(timezone.utc) - last) < timedelta(hours=SPIKE_COOLDOWN_HOURS):
            return
        count = await self._count_recent_messages(30)
        if count >= SPIKE_THRESHOLD:
            self._proactive_queued.add(chat_id)
            delay = random.randint(SPIKE_DELAY_MIN, SPIKE_DELAY_MAX)
            logger.info(f"MoltBot: activity spike ({count} msgs), queuing proactive in {delay}s")
            asyncio.create_task(self._fire_spike_proactive(chat_id, delay))

    async def _fire_spike_proactive(self, chat_id: int, delay: int):
        """Wait for spike delay then send proactive message and clear queue flag."""
        await asyncio.sleep(delay)
        self._proactive_queued.discard(chat_id)
        await self._send_proactive_message(chat_id)

    # ── Smart summary ─────────────────────────────────────────────────────────

    async def _update_summary(self):
        """Fetch recent messages and ask Together.ai to rewrite chat-summary.md."""
        try:
            rows = await self.db.execute_query(
                "SELECT name, message_text, timestamp FROM messages "
                "WHERE timestamp >= NOW() - INTERVAL '%s hours' "
                "ORDER BY timestamp ASC",
                (SUMMARY_FETCH_HOURS,),
            )
            if not rows:
                return
            messages = [
                f"{self._format_ts(r[2])} {r[0] or 'Аноним'}: {r[1]}"
                for r in rows
            ]
            history_text = "\n".join(messages)

            current_summary = _load_chat_summary()
            now = datetime.now().strftime("%Y-%m-%d %H:%M")

            prompt = f"""[СЛУЖЕБНЫЙ ЗАПРОС — обновление долгосрочной памяти чата]

== УЧАСТНИКИ ЧАТА ==
- Макс (Max) — программист и геймер, создатель бота, живёт в Дании
- Юра (Юрочка, Spatifilum) — геймер
- Богдан (Бодя, @lofiSnitch) — учится в Германии (Эрланген)
- Шева — друг, иногда играет в доту с ребятами, не в чате
- Кеша/Иннокентий (Jarvis в ТГ) — бот, четвёртый друг в чате
Все мужчины. Используй правильный род!

== ТЕКУЩИЙ SUMMARY ==
{current_summary or '(пусто)'}

== СООБЩЕНИЯ ЗА ПОСЛЕДНИЕ {SUMMARY_FETCH_HOURS} ЧАСОВ ==
{history_text}

== ЗАДАЧА ==
Обнови summary: добавь новое из сообщений выше. Старое НЕ удаляй если оно не устарело.

Стиль:
- Пиши как заметки для себя, не как статью. Коротко и по делу.
- Без академизма, канцелярита и анализа "динамики общения"
- Формат: буллеты и короткие абзацы, не простыни текста

Что сохранять:
- Внутренние шутки, мемы, приколы — это самое важное
- Кто что сказал если это важно или смешно
- Пари, споры, незакрытые темы
- Важные события (игры, фильмы, новости которые обсуждали)

Что НЕ надо:
- Бытовой мусор (привет/пока, тесты бота, технические сообщения)
- Пересказ каждого сообщения — только суть
- Выводы и "анализ атмосферы"
- НЕ интерпретируй и НЕ додумывай. Не пиши "ирония", "возможно отсылка к", "неясно что именно". Записывай факт как есть, без догадок.

Формат:
- Группируй по темам, не по хронологии
- Помечай когда было актуально: (апрель 2026)
- Размер: до 2000 слов. Лучше короче и по делу чем длинно и водянисто.
- Обнови "Последнее обновление: {now}"
- Верни ТОЛЬКО markdown текст, без обёртки в ```"""

            if not Settings.TOGETHER_API_KEY:
                logger.warning("MoltBot: TOGETHER_API_KEY not set, falling back to Ollama for summary")
                new_summary = await asyncio.to_thread(self._call_ollama_direct, prompt)
            else:
                try:
                    async with httpx.AsyncClient() as client:
                        r = await client.post(
                            "https://api.together.xyz/v1/chat/completions",
                            headers={"Authorization": f"Bearer {Settings.TOGETHER_API_KEY}"},
                            json={
                                "model": Settings.TOGETHER_MODEL,
                                "messages": [
                                    {"role": "system", "content": "Ты обновляешь файл заметок о групповом чате. Пиши коротко и по делу."},
                                    {"role": "user", "content": prompt},
                                ],
                                "max_tokens": 4000,
                                "temperature": 0.4,
                            },
                            timeout=180,
                        )
                        r.raise_for_status()
                        new_summary = r.json()["choices"][0]["message"]["content"]
                        new_summary = re.sub(r'<think>.*?</think>', '', new_summary, flags=re.DOTALL).strip()
                except Exception as e:
                    logger.warning(f"MoltBot: Together.ai summary failed, falling back to Ollama: {e}")
                    new_summary = await asyncio.to_thread(self._call_ollama_direct, prompt)

            if not new_summary or len(new_summary) < 100:
                logger.warning("MoltBot: LLM returned suspiciously short summary, skipping save")
                return

            os.makedirs(os.path.dirname(CHAT_SUMMARY_PATH), exist_ok=True)
            with open(CHAT_SUMMARY_PATH, "w", encoding="utf-8") as f:
                f.write(new_summary)
            logger.info(f"MoltBot: chat-summary.md updated ({len(new_summary)} chars)")
        except Exception as e:
            logger.error(f"MoltBot: summary update failed: {e}")

    def _maybe_update_summary(self):
        """Trigger summary update if enough time has passed (every SUMMARY_UPDATE_HOURS)."""
        now = datetime.now(timezone.utc)
        if self._last_summary_update and (now - self._last_summary_update) < timedelta(hours=SUMMARY_UPDATE_HOURS):
            return
        self._last_summary_update = now
        asyncio.create_task(self._update_summary())
        logger.info("MoltBot: triggered background summary update (24h timer)")

    # ── Topic detection ───────────────────────────────────────────────────────

    def _get_current_topic(self, history: list[str]) -> str:
        """Ask Qwen to summarise the current chat topic in a few words. Sync."""
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
        """Ask Qwen if the question is simple or complex. Returns 'simple' or 'complex'. Sync."""
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

    _TG_MAX_LENGTH = 4096

    async def _send_long_reply(self, message, text: str):
        """Send a reply, splitting into multiple messages if > 4096 chars."""
        if len(text) <= self._TG_MAX_LENGTH:
            return await message.reply(text)
        # Split on double newline, single newline, or hard cut
        chunks = []
        while text:
            if len(text) <= self._TG_MAX_LENGTH:
                chunks.append(text)
                break
            cut = text.rfind("\n\n", 0, self._TG_MAX_LENGTH)
            if cut == -1:
                cut = text.rfind("\n", 0, self._TG_MAX_LENGTH)
            if cut == -1:
                cut = self._TG_MAX_LENGTH
            chunks.append(text[:cut])
            text = text[cut:].lstrip("\n")
        sent = None
        for chunk in chunks:
            if chunk.strip():
                sent = await message.reply(chunk)
        return sent

    _IDENTITY_PATH = os.path.join(_BASE_DIR, 'docs', 'openclaw-identity-lolita.md')

    _HARD_RULES = (
        "ПРАВИЛА:\n"
        "1. Отвечай КОРОТКО: 1-3 предложения обычно. Больше только когда реально нужно.\n"
        "2. НЕ выдумывай факты, события, разговоры которых не было. Не знаешь — скажи.\n"
        "3. Долгосрочная память — фоновые знания. Не тащи оттуда темы сам. "
        "НЕ пересказывай, НЕ развивай и НЕ додумывай то что написано в памяти. "
        "Если тебя спросили о чём-то из памяти — отвечай только то что там написано, не дорисовывай детали.\n"
        "4. Если нужна актуальная информация из интернета "
        "(погода, новости, курсы, события) — ответь ОДНИМ словом: INTERNET."
    )

    # Bot names used to identify assistant messages in history
    _BOT_NAMES = {"Кеша", "Иннокентий", "Лолита", "Ло", "Лола", "Jarvis"}

    def _history_to_messages(self, history: list[str], sender_name: str,
                             user_text: str) -> list[dict]:
        """Convert history strings to OpenAI-style message dicts.
        History format: '14:30 Макс: текст' or '14:30 Лолита: текст'."""
        messages = []
        for line in (history or [])[-15:]:
            # Strip timestamp prefix: "14:30 Name: text" → "Name: text"
            parts = line.split(" ", 1)
            if len(parts) < 2:
                continue
            rest = parts[1] if ":" in parts[1] else line
            colon_idx = rest.find(":")
            if colon_idx == -1:
                continue
            name = rest[:colon_idx].strip()
            text = rest[colon_idx + 1:].strip()
            if not text:
                continue
            role = "assistant" if name in self._BOT_NAMES else "user"
            content = text if role == "assistant" else f"{name}: {text}"
            # Merge consecutive same-role messages
            if messages and messages[-1]["role"] == role:
                messages[-1]["content"] += f"\n{content}"
            else:
                messages.append({"role": role, "content": content})
        # Add current message
        messages.append({"role": "user", "content": f"{sender_name}: {user_text}"})
        return messages

    async def _call_together(self, sender_name: str, user_text: str,
                             chat_context: str, history: list[str] | None = None) -> str:
        """Call Together.ai with IDENTITY.md as system prompt and proper multi-turn."""
        if not Settings.TOGETHER_API_KEY:
            raise _AIConnectionError("TOGETHER_API_KEY not set")
        try:
            with open(self._IDENTITY_PATH, encoding="utf-8") as f:
                identity = f.read()
        except Exception:
            identity = ""
        summary = _load_chat_summary()
        # Hard rules prepended before IDENTITY — models follow start of prompt best
        system_parts = [self._HARD_RULES, identity]
        if chat_context:
            system_parts.append(f"[Сообщение отправлено из: {chat_context}]")
        if summary:
            system_parts.append(f"[Долгосрочная память о чате:\n{summary}]")
        system_msg = "\n\n".join(system_parts)

        messages = [{"role": "system", "content": system_msg}]
        messages.extend(self._history_to_messages(history, sender_name, user_text))

        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://api.together.xyz/v1/chat/completions",
                headers={"Authorization": f"Bearer {Settings.TOGETHER_API_KEY}"},
                json={
                    "model": Settings.TOGETHER_MODEL,
                    "messages": messages,
                    "max_tokens": 500,
                    "temperature": 0.9,
                },
                timeout=120,
            )
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
            # Strip thinking tags if present
            text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
            # Strip asterisk actions (*действие*) — model ignores prompt rules about this
            text = re.sub(r'\*[^*]{2,80}\*', '', text)
            # Clean up leftover whitespace from stripped actions
            text = re.sub(r'\n\s*\n\s*\n', '\n\n', text).strip()
            return text

    async def _call_qwen_with_identity(self, sender_name: str, user_text: str,
                                        chat_context: str, history: list[str] | None = None) -> str:
        """Call Qwen directly with IDENTITY.md as system prompt, bypassing OpenClaw.
        Used as fallback when Together.ai is unavailable."""
        import httpx as _httpx
        try:
            with open(self._IDENTITY_PATH, encoding="utf-8") as f:
                identity = f.read()
        except Exception:
            identity = ""
        summary = _load_chat_summary()
        system_msg = self._HARD_RULES + "\n" + identity
        context_prefix = f"[Сообщение отправлено из: {chat_context}]\n" if chat_context else ""
        summary_block = f"[Долгосрочная память о чате: {summary}]\n" if summary else ""
        history_block = "\n".join(history[-30:]) + "\n" if history else ""
        user_msg = f"{context_prefix}{summary_block}{history_block}{sender_name}: {user_text}"

        def _call():
            r = _httpx.post(
                f"{Settings.LOCAL_LLM_URL}/api/chat",
                json={"model": Settings.LOCAL_LLM_MODEL,
                      "think": False,
                      "stream": False,
                      "messages": [
                          {"role": "system", "content": system_msg},
                          {"role": "user", "content": user_msg},
                      ]},
                timeout=180,
            )
            r.raise_for_status()
            import re as _re
            text = r.json()["message"]["content"]
            text = _re.sub(r'<think>.*?</think>', '', text, flags=_re.DOTALL).strip()
            text = text.split('<|endoftext|>')[0].split('<|im_start|>')[0].strip()
            return text

        return await asyncio.to_thread(_call)

    def _would_gemini_block(self, user_text: str) -> bool:
        """Ask Qwen whether Gemini would likely block this message due to safety filters."""
        prompt = (
            "Ты фильтр безопасности. Определи, заблокирует ли Google Gemini это сообщение "
            "из-за safety filters (секс, наркотики, насилие, расизм, NSFW контент и т.д.).\n"
            f"Сообщение: {user_text[:500]}\n"
            "Ответь ОДНИМ словом: YES или NO"
        )
        try:
            result = self._call_ollama_direct(prompt)
            answer = result.strip().upper().split()[0] if result else "NO"
            return answer.startswith("YES")
        except Exception:
            return False

    async def _ask_moltbot_routed(self, sender_name: str, user_text: str,
                                  chat_context: str,
                                  history: list[str] | None = None) -> str:
        """Route: Together.ai primary → Gemini (INTERNET) → Qwen local (fallback)."""
        # Together.ai as primary model for all messages
        if Settings.TOGETHER_API_KEY:
            try:
                logger.info(f"MoltBot: together.ai for: {user_text[:60]}")
                reply = await self._call_together(sender_name, user_text, chat_context, history)
                if reply and reply.strip():
                    if reply.strip().upper() == "INTERNET":
                        logger.info(f"MoltBot: together.ai requested INTERNET → gemini for: {user_text[:60]}")
                        try:
                            return await self._call_gemini_text(sender_name, user_text, chat_context, history)
                        except Exception as ge:
                            logger.warning(f"MoltBot: Gemini INTERNET fallback failed ({ge}), trying Qwen")
                    else:
                        return reply
            except Exception as e:
                logger.warning(f"MoltBot: Together.ai failed ({e}), falling back to Qwen")
        # Fallback to local Qwen
        return await self._call_qwen_with_identity(sender_name, user_text, chat_context, history)

    async def _qwen_should_reply(self, sender_name: str, user_text: str,
                                history: list[str]) -> bool:
        """Ask Qwen if the bot should reply. Returns True/False. Fast filter."""
        snippet = "\n".join(history[-10:]) if history else "(нет истории)"
        prompt = (
            f"Вот последние сообщения из группового чата:\n{snippet}\n\n"
            f"Новое сообщение от {sender_name}: {user_text}\n\n"
            "Ты Джарвис — участник чата. Реши: стоит ли тебе вмешаться?\n"
            "Отвечай YES только если:\n"
            "- Тема тебя касается (дота, философия, жизнь, шансон, зона)\n"
            "- Кто-то сказал явную глупость и это смешно прокомментировать\n"
            "- Разговор сам просится на твой комментарий\n"
            "Отвечай NO если:\n"
            "- Это просто болтовня между людьми\n"
            "- Сообщение короткое и бессмысленное\n"
            "- Вопрос адресован конкретному человеку\n"
            "- При любых сомнениях — NO\n"
            "Ответь одним словом: YES или NO"
        )
        try:
            result = await asyncio.to_thread(self._call_ollama_direct, prompt)
            answer = result.strip().upper()
            logger.info(f"MoltBot: Qwen filter says {answer} for: {user_text[:60]}")
            return "YES" in answer
        except Exception as e:
            logger.warning(f"MoltBot: Qwen filter error: {e}")
            return False

    async def _maybe_reply_probabilistic(self, message) -> bool:
        """Two-stage probabilistic reply: activity gate → Qwen filter → Claude response."""
        chat_id = message.chat.id
        user_text = message.text or ""
        now = datetime.now(timezone.utc)

        # Gate 1: minimum message length
        if len(user_text) < 10:
            return False

        # Gate 2: activity threshold — 6+ messages in last 10 minutes
        recent_count = await self._count_recent_messages(10)
        if recent_count < 6:
            return False

        # Gate 3: session cooldown — 20 minutes between replies
        last = self._last_probabilistic_sent.get(chat_id)
        if last and (now - last) < timedelta(minutes=20):
            return False

        # Determine cold start vs warm session
        session_start = self._prob_session_start.get(chat_id)
        is_cold_start = session_start is None or (now - session_start) > timedelta(hours=2)

        sender_name = self._resolve_sender_name(message.from_user)

        try:
            if is_cold_start:
                # Cold start: picks from last 6 messages
                history = await self._get_recent_group_messages(limit=6, chat_id=chat_id)
                if not history:
                    return False
                history_block = "\n".join(history)
                prompt = (
                    f"[Последние 6 сообщений из чата]\n{history_block}\n\n"
                    "Ты участник чата и хочешь вмешаться. Выбери одно сообщение "
                    "на которое стоит ответить и напиши короткий комментарий.\n"
                    "Подъёбка, шутка, или полезный коммент если тема серьёзная.\n"
                    "1-2 предложения максимум. Не представляйся, не начинай с обращения.\n"
                    "Если ни одно сообщение не стоит ответа — верни пустую строку."
                )
                reply = await self._call_together_simple(prompt)
                logger.info(f"MoltBot: cold start probabilistic for chat {chat_id}")
            else:
                # Warm session: Qwen filter → Claude response
                history = await self._get_recent_group_messages(limit=30, chat_id=chat_id)
                should = await self._qwen_should_reply(sender_name, user_text, history)
                if not should:
                    return False

                history_block = "\n".join(history) if history else "(нет истории)"
                prompt = (
                    f"[История чата — последние {len(history)} сообщений]\n{history_block}\n\n"
                    f"Новое сообщение от {sender_name}: {user_text}\n\n"
                    "[Ты решил вмешаться в разговор. Напиши короткий комментарий "
                    "как участник чата — подъёбка, шутка, или полезный коммент если тема серьёзная.\n"
                    "1-2 предложения максимум. Не представляйся, не начинай с обращения.\n"
                    "Если передумал — верни пустую строку.]"
                )
                reply = await self._call_together_simple(prompt)
                logger.info(f"MoltBot: warm session probabilistic for chat {chat_id}")

            reply = reply.strip()
            if not reply:
                return False

            sent = await self._send_long_reply(message, reply)
            await self._store_bot_reply(reply, sent.message_id)
            self._last_probabilistic_sent[chat_id] = now
            if is_cold_start:
                self._prob_session_start[chat_id] = now
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

    async def _maybe_react(self, message) -> None:
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
            result = await asyncio.to_thread(self._call_ollama_direct, prompt)
            result = result.strip()
            result = result.split()[0] if result else ""
            if result not in self._REACTION_EMOJIS:
                logger.debug(f"MoltBot: no reaction (got {repr(result)}) for msg {message.message_id}")
                return
            token = Settings.TELEGRAM_BOT_TOKEN
            async with httpx.AsyncClient() as client:
                await client.post(
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

    async def _ensure_danetki_table(self):
        try:
            await self.db.execute_query(
                "CREATE TABLE IF NOT EXISTS danetki ("
                "id SERIAL PRIMARY KEY, "
                "situation TEXT NOT NULL, "
                "answer TEXT NOT NULL, "
                "used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
                ()
            )
        except Exception as e:
            logger.error(f"MoltBot: failed to create danetki table: {e}")

    async def _get_used_situations(self, limit: int = 25) -> list[str]:
        try:
            rows = await self.db.execute_query(
                "SELECT situation FROM danetki ORDER BY used_at DESC LIMIT %s",
                (limit,)
            )
            return [r[0] for r in rows] if rows else []
        except Exception:
            return []

    async def _generate_danetka(self) -> dict | None:
        used = await self._get_used_situations()
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
            raw = await asyncio.to_thread(self._call_ollama_direct, prompt)
            clean = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
            # If nothing outside think tags, search the full raw text
            search_in = clean if clean else raw
            match = re.search(r'\{.*\}', search_in, re.DOTALL)
            if not match:
                logger.warning(f"MoltBot: danetka no JSON found in: {search_in[:300]!r}")
                return None
            data = json.loads(match.group())
            if 'situation' in data and 'answer' in data:
                return data
        except Exception as e:
            logger.error(f"MoltBot: danetka generation error: {e}")
        return None

    async def _save_danetka(self, situation: str, answer: str):
        try:
            await self.db.execute_query(
                "INSERT INTO danetki (situation, answer) VALUES (%s, %s)",
                (situation, answer)
            )
        except Exception as e:
            logger.error(f"MoltBot: failed to save danetka: {e}")

    async def _judge_danetka(self, question: str, answer: str) -> str:
        is_question = "?" in question
        hint = (
            "Это ВОПРОС (есть знак ?). Отвечай Да/Нет/Не важно."
            if is_question else
            "Это УТВЕРЖДЕНИЕ (нет знака ?). Если суть верная - отвечай УГАДАЛ."
        )
        prompt = (
            f"Ты ведущий игры «данетка».\n"
            f"Правильный ответ (только ты знаешь): {answer}\n\n"
            f"Игрок написал: {question}\n"
            f"{hint}\n\n"
            "Варианты ответа:\n"
            "- Да — ответ на вопрос, если факт верный\n"
            "- Нет — ответ на вопрос, если факт неверный\n"
            "- Не важно — вопрос не связан с разгадкой\n"
            "- Близко! 🔥 — игрок близок к разгадке но не назвал главное\n"
            "- УГАДАЛ! 🎉 — игрок назвал ключевую суть разгадки\n\n"
            "Верни только один вариант."
        )
        try:
            result = (await asyncio.to_thread(self._call_ollama_direct, prompt)).strip()
            for v in ["УГАДАЛ! 🎉", "Близко! 🔥", "Да", "Нет", "Не важно"]:
                if v.lower() in result.lower():
                    return v
            return "Не важно"
        except Exception as e:
            logger.error(f"MoltBot: danetka judge error: {e}")
            return "Не важно"

    async def _handle_danetka_reply(self, message):
        chat_id = message.chat.id
        active = self._active_danetka.get(chat_id)
        if not active:
            return
        question = (message.text or "").strip()
        if not question:
            return
        active['questions_count'] = active.get('questions_count', 0) + 1
        judgment = await self._judge_danetka(question, active['answer'])
        await message.reply(judgment)
        if "УГАДАЛ" in judgment:
            del self._active_danetka[chat_id]
            await self.bot.send_message(
                chat_id,
                f"🎉 Правильно! Вот полный ответ:\n\n{active['answer']}\n\n"
                f"Вопросов задано: {active['questions_count']}"
            )

    # ── Недельная аналитика ───────────────────────────────────────────────────

    async def _send_weekly_analytics(self, chat_id: int):
        try:
            total_rows = await self.db.execute_query(
                "SELECT COUNT(*) FROM messages WHERE timestamp > NOW() - INTERVAL '7 days' AND user_id != 0",
                ()
            )
            total = total_rows[0][0] if total_rows else 0
            if total == 0:
                await self.bot.send_message(chat_id, "📊 За эту неделю сообщений не было.")
                return

            per_person = await self.db.execute_query(
                "SELECT name, COUNT(*) FROM messages "
                "WHERE timestamp > NOW() - INTERVAL '7 days' AND user_id != 0 "
                "GROUP BY name ORDER BY COUNT(*) DESC LIMIT 10",
                ()
            )
            top_hours = await self.db.execute_query(
                "SELECT EXTRACT(HOUR FROM timestamp)::int, COUNT(*) FROM messages "
                "WHERE timestamp > NOW() - INTERVAL '7 days' AND user_id != 0 "
                "GROUP BY 1 ORDER BY 2 DESC LIMIT 3",
                ()
            )

            # Qwen topic summary
            recent = await self._get_recent_group_messages(limit=300, chat_id=chat_id)
            topics = ""
            if recent:
                snippet = "\n".join(recent[-200:])
                try:
                    raw_topics = await asyncio.to_thread(
                        self._call_ollama_direct,
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
                # strip markdown special chars from AI-generated text
                clean = topics.replace('*', '').replace('_', '').replace('`', '').replace('[', '').replace(']', '')
                lines.append(clean)

            await self.bot.send_message(chat_id, "\n".join(lines), parse_mode="Markdown")
            logger.info(f"MoltBot: weekly analytics sent to {chat_id}")
        except Exception as e:
            logger.error(f"MoltBot: weekly analytics error: {e}")

    def start_proactive_scheduler(self, chat_id: int):
        """Start scheduled (2x/day) and activity-spike proactive messaging via asyncio tasks."""
        # TODO: re-enable when personality is tuned
        # asyncio.create_task(self._proactive_scheduled_loop(chat_id))
        # asyncio.create_task(self._proactive_monitor_loop(chat_id))
        # logger.info(f"MoltBot: proactive scheduler started for chat {chat_id}")
        return

    async def _proactive_scheduled_loop(self, chat_id: int):
        """Fire proactive messages at fixed times using an async polling loop."""
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
                    if await self._count_recent_messages(8 * 60) >= 5:
                        await self._send_proactive_message(chat_id)
                    else:
                        logger.info(f"MoltBot: skipping {t} proactive — chat inactive")
            # Weekly analytics: Sunday 21:00
            weekly_key = f"{day_key}-weekly"
            if now.weekday() == 6 and hhmm == "21:00" and weekly_key not in sent_today:
                sent_today.add(weekly_key)
                asyncio.create_task(self._send_weekly_analytics(chat_id))
            # Purge old day keys to avoid unbounded growth
            if len(sent_today) > 20:
                sent_today = {k for k in sent_today if k.startswith(day_key)}
            await asyncio.sleep(30)

    async def _proactive_monitor_loop(self, chat_id: int):
        """Periodically check for activity spikes."""
        while True:
            await asyncio.sleep(600)
            try:
                await self._check_activity_spike(chat_id)
            except Exception as e:
                logger.error(f"MoltBot: proactive monitor error: {e}")

    # ── Handlers ──────────────────────────────────────────────────────────────

    def _register(self):
        router = self.router

        @router.message(StateFilter(None), F.func(lambda m: bool(
            m.entities and m.text and any(e.type == 'mention' for e in m.entities)
        )))
        async def handle_mention(message: Message):
            await self._store_user_message(message)
            # Check actual bot mention asynchronously
            if not await self._is_bot_mentioned(message):
                return
            sender_name = self._resolve_sender_name(message.from_user)
            user_text = await self._extract_user_text(message)
            if not user_text.strip() and message.reply_to_message is None:
                user_text = "(тегнули без текста)"
            reply_ctx = await self._build_reply_context(message)
            if reply_ctx:
                user_text = f"{reply_ctx}\n{user_text}" if user_text else reply_ctx
            chat_context = self._get_chat_context(message)

            # Fetch group history only for group chats
            history = None
            if message.chat.type in ('group', 'supergroup'):
                history = await self._get_recent_group_messages(limit=100, chat_id=message.chat.id)

            try:
                reply = await self._ask_moltbot_routed(sender_name, user_text, chat_context, history)
                if reply and reply.strip():
                    sent = await self._send_long_reply(message, reply)
                    await self._store_bot_reply(reply, sent.message_id)
                else:
                    await message.reply("🤐 AI отказался отвечать на это сообщение")
            except _AIConnectionError:
                await message.reply("⚠️ Не могу подключиться к AI, попробуй позже")
            except Exception as e:
                logger.error(f"MoltBot API error: {e}")
                await message.reply("Не могу связаться с AI. Попробуй позже.")

        @router.message(Command(commands=['данетка', 'danetka']))
        async def handle_danetka_start(message: Message):
            chat_id = message.chat.id
            if chat_id in self._active_danetka:
                await message.reply("⚠️ Игра уже идёт! Используй /сдаюсь чтобы сдаться.")
                return
            waiting = await message.reply("🎲 Придумываю данетку...")

            async def generate_and_post():
                danetka = await self._generate_danetka()
                if not danetka:
                    await self.bot.edit_message_text("❌ Не смог придумать, попробуй ещё раз.",
                                                     chat_id=chat_id, message_id=waiting.message_id)
                    return
                await self._save_danetka(danetka['situation'], danetka['answer'])
                await self.bot.edit_message_text(
                    f"🎲 *Данетка!*\n\n{danetka['situation']}\n\n"
                    "_Задавайте вопросы — отвечаю только Да / Нет / Не важно_\n"
                    "Используй /сдаюсь чтобы узнать ответ",
                    chat_id=chat_id, message_id=waiting.message_id, parse_mode="Markdown"
                )
                self._active_danetka[chat_id] = {
                    'situation': danetka['situation'],
                    'answer': danetka['answer'],
                    'message_id': waiting.message_id,
                    'started_at': datetime.now(timezone.utc),
                    'questions_count': 0,
                }

            asyncio.create_task(generate_and_post())

        @router.message(Command(commands=['сдаюсь', 'sdayus']))
        async def handle_danetka_surrender(message: Message):
            chat_id = message.chat.id
            active = self._active_danetka.pop(chat_id, None)
            if not active:
                await message.reply("Нет активной игры.")
                return
            await message.reply(
                f"🏳️ Сдаётесь! Вот ответ:\n\n{active['answer']}\n\n"
                f"Вопросов было задано: {active.get('questions_count', 0)}"
            )

        @router.message(Command(commands=['аналитика', 'analitika']))
        async def handle_analytics_command(message: Message):
            if message.from_user.id not in Settings.ADMIN_IDS:
                await message.reply("У вас нет доступа.")
                return
            await message.reply("📊 Собираю статистику...")
            asyncio.create_task(self._send_weekly_analytics(message.chat.id))

        @router.message(Command(commands=['мут_сброс', 'mut_reset']))
        async def handle_reset(message: Message):
            """Reset chat history context in ALL chats. Bot won't see messages before this point."""
            now = datetime.now(timezone.utc)
            # Reset all known chats + current chat
            all_chat_ids = set(CHAT_KEYS.keys()) | {message.chat.id}
            for chat_id in all_chat_ids:
                self._history_reset_time[chat_id] = now
            self._save_state()
            logger.info(f"MoltBot: history reset for ALL chats ({len(all_chat_ids)}) by {message.from_user.id}")
            await message.reply(f"⚙️ Контекст сброшен во всех чатах ({len(all_chat_ids)}). Чистый лист.")

        @router.message(StateFilter(None), F.func(lambda m: (
            m.reply_to_message is not None
            and m.reply_to_message.from_user is not None
            and m.reply_to_message.from_user.is_bot
        )))
        async def handle_reply_to_bot(message: Message):
            await self._store_user_message(message)
            chat_id = message.chat.id
            # Route to danetka: any reply to bot while game is active
            if chat_id in self._active_danetka:
                asyncio.create_task(self._handle_danetka_reply(message))
                return

            # Only handle replies to THIS bot
            bot_info = await self.bot.get_me()
            if message.reply_to_message.from_user.id != bot_info.id:
                return
            if await self._is_bot_mentioned(message):
                return

            sender_name = self._resolve_sender_name(message.from_user)
            user_text = message.text or message.caption or ""

            # New photo in reply to bot — analyze via Gemini
            if message.photo:
                try:
                    file = await self.bot.get_file(message.photo[-1].file_id)
                    bio = await self.bot.download_file(file.file_path)
                    image_bytes = bio.read()
                    image_analysis = await asyncio.to_thread(
                        self._analyze_image_with_gemini, image_bytes, user_text
                    )
                    user_text = f"[Картинка: {image_analysis}]\n{user_text}" if user_text else f"[Картинка: {image_analysis}]"
                except Exception as e:
                    logger.warning(f"MoltBot: reply photo analysis failed: {e}")

            # If replying to a bot message that was about a photo, add context note (no re-analysis)
            replied_msg_id = message.reply_to_message.message_id
            photo_file_id = self._photo_context.get(replied_msg_id)
            if photo_file_id and not message.photo:
                user_text = f"[Продолжение разговора о картинке — контекст в истории чата]\n{user_text}"

            reply_ctx = await self._build_reply_context(message)
            if reply_ctx:
                user_text = f"{reply_ctx}\n{user_text}" if user_text else reply_ctx
            chat_context = self._get_chat_context(message)

            history = None
            if message.chat.type in ('group', 'supergroup'):
                history = await self._get_recent_group_messages(limit=100, chat_id=message.chat.id)

            try:
                reply = await self._ask_moltbot_routed(sender_name, user_text, chat_context, history)
                if reply and reply.strip():
                    sent = await self._send_long_reply(message, reply)
                    await self._store_bot_reply(reply, sent.message_id)
                else:
                    await message.reply("🤐 AI отказался отвечать на это сообщение")
            except _AIConnectionError:
                await message.reply("⚠️ Не могу подключиться к AI, попробуй позже")
            except Exception as e:
                logger.error(f"MoltBot API error (reply): {e}")
                await message.reply("Не могу связаться с AI. Попробуй позже.")

        @router.message(StateFilter(None), F.func(lambda m: (
            m.chat.type in ('group', 'supergroup')
            and bool(m.text)
            and not m.text.startswith('/')
            and m.from_user is not None
            and not m.from_user.is_bot
            and not (m.reply_to_message and m.reply_to_message.from_user
                     and m.reply_to_message.from_user.is_bot)
            and not (m.entities and any(e.type == 'mention' for e in m.entities))
        )))
        async def handle_probabilistic(message: Message):
            await self._store_user_message(message)
            self._maybe_update_summary()
            # asyncio.create_task(self._maybe_reply_probabilistic(message))

        @router.message(StateFilter(None), F.photo, F.func(lambda m: (
            m.caption_entities is not None
            and any(e.type == 'mention' for e in m.caption_entities)
        )))
        async def handle_photo_mention(message: Message):
            if not await self._is_bot_mentioned_in_caption(message):
                return
            sender_name = self._resolve_sender_name(message.from_user)
            user_question = await self._extract_caption_text(message)
            reply_ctx = await self._build_reply_context(message)
            chat_context = self._get_chat_context(message)

            history = None
            if message.chat.type in ('group', 'supergroup'):
                history = await self._get_recent_group_messages(limit=100, chat_id=message.chat.id)

            try:
                file = await self.bot.get_file(message.photo[-1].file_id)
                bio = await self.bot.download_file(file.file_path)
                image_bytes = bio.read()
            except Exception as e:
                logger.error(f"MoltBot: failed to download photo: {e}")
                await message.reply("Не могу загрузить картинку. Попробуй ещё раз.")
                return

            image_analysis = await asyncio.to_thread(
                self._analyze_image_with_gemini, image_bytes, user_question
            )

            parts = []
            if reply_ctx:
                parts.append(reply_ctx)
            parts.append(f"[Картинка: {image_analysis}]")
            if user_question:
                parts.append(user_question)
            combined_text = "\n".join(parts)

            try:
                reply = await self._ask_moltbot_routed(sender_name, combined_text, chat_context, history)
                if reply and reply.strip():
                    sent = await self._send_long_reply(message, reply)
                    await self._store_bot_reply(reply, sent.message_id)
                    self._photo_context[sent.message_id] = message.photo[-1].file_id
                else:
                    await message.reply("🤐 AI отказался отвечать на это сообщение")
            except _AIConnectionError:
                await message.reply("⚠️ Не могу подключиться к AI, попробуй позже")
            except Exception as e:
                logger.error(f"MoltBot API error (photo): {e}")
                await message.reply("Не могу связаться с AI. Попробуй позже.")
