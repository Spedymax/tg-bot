import json
import logging
import os
import httpx
import google.generativeai as genai
from datetime import datetime, timezone
from config.settings import Settings

CHAT_SUMMARY_PATH = os.path.expanduser("~/.openclaw/workspace/memory/chat-summary.md")
STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "moltbot_state.json")


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


class MoltbotHandlers:
    def __init__(self, bot, db_manager):
        self.bot = bot
        self.db = db_manager
        self._bot_username = None  # lazily cached
        self._history_reset_time: dict[int, datetime] = {}  # chat_id → reset timestamp
        self._user_key_suffix: dict[int, str] = {}  # chat_id → suffix added after reset
        self._gemini_model = None
        self._load_state()
        self._init_gemini()

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
            self._gemini_model = genai.GenerativeModel('gemini-3-flash-preview')
            logger.info("MoltBot: Gemini vision initialized (gemini-3-flash-preview)")
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

    def _ask_moltbot(self, sender_name: str, user_text: str,
                     chat_context: str, user_key: str,
                     history: list[str] | None = None) -> str:
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

        with httpx.Client() as client:
            r = client.post(
                Settings.JARVIS_URL,
                headers={"Authorization": f"Bearer {Settings.JARVIS_TOKEN}"},
                json={
                    "model": "openclaw:main",
                    "user": user_key,
                    "messages": [
                        {"role": "user", "content": user_content},
                    ],
                },
                timeout=60,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

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
                history = self._get_recent_group_messages(limit=50, chat_id=message.chat.id)

            try:
                reply = self._ask_moltbot(sender_name, user_text, chat_context, user_key, history)
                self.bot.reply_to(message, reply)
            except Exception as e:
                logger.error(f"MoltBot API error: {e}")
                self.bot.reply_to(message, "Не могу связаться с AI. Попробуй позже.")

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
                history = self._get_recent_group_messages(limit=50, chat_id=message.chat.id)

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
                self.bot.reply_to(message, reply)
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
