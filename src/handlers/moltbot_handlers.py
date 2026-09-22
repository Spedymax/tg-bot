import asyncio
import json
import logging
import os
import random
import re
import time
import httpx
import google.generativeai as genai
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from aiogram import Router, F, Bot
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, ReactionTypeEmoji
from aiogram.utils.chat_action import ChatActionSender
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config.settings import Settings
from services.circuit_breaker import ollama_breaker, together_breaker, openrouter_breaker
from services.context_builder import ContextBuilder, ContextSnapshot, PERSONA_POST_PROMPT, compose_thread_first, format_clock
from services import llm_trace
from services.persona_tools import WEB_SEARCH_TOOL

_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
CHAT_SUMMARY_PATH = os.path.join(_BASE_DIR, 'data', 'chat-summary.md')
# Pinned lore — permanent in-jokes/legends that survive the rolling summary rewrite.
CHAT_LORE_PATH = os.path.join(_BASE_DIR, 'data', 'chat-lore.md')
# Lore the summarizer proposes. Never injected into prompts — an admin promotes
# entries by hand (/memory_pin к<N>) so the bot can't make its own jokes permanent.
CHAT_LORE_CANDIDATES_PATH = os.path.join(_BASE_DIR, 'data', 'chat-lore-candidates.md')
STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "moltbot_state.json")

# Live-switchable reasoning depth for the OpenRouter/Grok persona model.
# "low" is the everyday default (fast, cheap, same tone); people bump it to
# "high" from the chat for a serious talk. After REASONING_RESET_AFTER of chat
# silence it falls back to the default on its own.
REASONING_LEVELS = ("low", "medium", "high")
REASONING_DEFAULT = "low"
REASONING_RESET_AFTER = timedelta(hours=3)
_REASONING_ALIASES = {
    "low": "low", "lo": "low", "лоу": "low", "мало": "low", "выкл": "low", "off": "low", "норм": "low",
    "medium": "medium", "mid": "medium", "med": "medium", "мид": "medium", "средне": "medium", "средний": "medium",
    "high": "high", "hi": "high", "хай": "high", "макс": "high", "max": "high", "много": "high", "серьёзно": "high", "серьезно": "high",
}


def _parse_reasoning_level(arg: str) -> str | None:
    """Map a user-typed level ("high", "хай", "макс", ...) to low/medium/high, or None."""
    return _REASONING_ALIASES.get((arg or "").strip().lower())


class _AIConnectionError(Exception):
    """Raised when AI backend is unreachable or timed out."""

class _AIRefusalError(Exception):
    """Raised when AI explicitly refuses to respond."""


def _chat_memory_path(base_path: str, chat_id: int | None) -> str:
    """Keep legacy filenames for the main group; isolate every other chat."""
    resolved_chat_id = chat_id if chat_id is not None else Settings.CHAT_IDS['main']
    if resolved_chat_id == Settings.CHAT_IDS['main']:
        return base_path
    stem, ext = os.path.splitext(base_path)
    return f"{stem}-{resolved_chat_id}{ext}"


def _get_summary_mtime(chat_id: int | None = None) -> datetime | None:
    """Return the modification time of chat-summary.md, or None if missing."""
    try:
        mtime = os.path.getmtime(_chat_memory_path(CHAT_SUMMARY_PATH, chat_id))
        return datetime.fromtimestamp(mtime, tz=timezone.utc)
    except Exception:
        return None


def _load_chat_summary(chat_id: int | None = None) -> str:
    """Load the long-term chat summary written by the AI."""
    try:
        with open(_chat_memory_path(CHAT_SUMMARY_PATH, chat_id), encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.warning(f"MoltBot: could not read chat summary: {e}")
        return ""


def _load_chat_lore(chat_id: int | None = None) -> str:
    """Load pinned lore — permanent in-jokes the rolling summary must never drop."""
    try:
        with open(_chat_memory_path(CHAT_LORE_PATH, chat_id), encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""
    except Exception as e:
        logging.getLogger(__name__).warning(f"MoltBot: could not read chat lore: {e}")
        return ""


def _lore_lines(chat_id: int | None = None) -> list[str]:
    """Pinned lore as a list of non-empty lines."""
    return [ln.strip() for ln in _load_chat_lore(chat_id).splitlines() if ln.strip()]


def _atomic_write(path: str, text: str) -> None:
    """Write via temp file + rename so a crash never leaves a half-written memory file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def _save_lore_lines(lines: list[str], chat_id: int | None = None) -> None:
    _atomic_write(_chat_memory_path(CHAT_LORE_PATH, chat_id),
                  "\n".join(lines).strip() + ("\n" if lines else ""))


def _lore_candidate_lines(chat_id: int | None = None) -> list[str]:
    try:
        with open(_chat_memory_path(CHAT_LORE_CANDIDATES_PATH, chat_id), encoding="utf-8") as f:
            return [ln.strip() for ln in f if ln.strip()]
    except FileNotFoundError:
        return []


def _save_lore_candidate_lines(lines: list[str], chat_id: int | None = None) -> None:
    _atomic_write(_chat_memory_path(CHAT_LORE_CANDIDATES_PATH, chat_id),
                  "\n".join(lines).strip() + ("\n" if lines else ""))


def _remove_memory_file(base_path: str, chat_id: int | None) -> bool:
    path = _chat_memory_path(base_path, chat_id)
    if not os.path.exists(path):
        return False
    os.remove(path)
    return True


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
SUMMARY_MAX_MESSAGES = 800    # newest human messages considered per rebuild
SUMMARY_CHAR_BUDGET = 60_000  # keeps the summarizer input bounded in a busy chat
HISTORY_MESSAGE_LIMIT = 100
# Cheap classifier for "react with an emoji or stay silent" on ambient messages.
REACTION_MODEL = os.getenv("JARVIS_REACTION_MODEL", "z-ai/glm-5.3-flash")
HISTORY_CHAR_BUDGET = 12_000  # conservative ~3K-token cap before prompt/memory
CPH_TZ = ZoneInfo("Europe/Copenhagen")


class MoltbotHandlers:
    def __init__(self, bot: Bot, db_manager):
        self.bot = bot
        self.db = db_manager
        self.router = Router()
        self._bot_username = None  # lazily cached
        self._history_reset_time: dict[int, datetime] = {}  # chat_id → reset timestamp
        # chat_id → memory is rebuilt only from messages after this point (/memory_clear)
        self._memory_cursor: dict[int, datetime] = {}
        self._gemini_model = None
        self._last_proactive_sent: dict[int, datetime] = {}
        self._proactive_queued: set[int] = set()
        self._last_probabilistic_sent: dict[int, datetime] = {}
        self._last_reaction_time: dict[int, datetime] = {}
        self._last_summary_update: dict[int, datetime | None] = {
            chat_id: _get_summary_mtime(chat_id) for chat_id in CHAT_KEYS
        }
        self._active_danetka: dict[int, dict] = {}
        self._photo_context: dict[int, str] = {}  # bot_reply_msg_id → original photo file_id
        self._prob_session_start: dict[int, datetime] = {}  # chat_id → when probabilistic session started
        self._reasoning_effort: str = REASONING_DEFAULT
        self._reasoning_last_activity: datetime | None = None  # last chat activity seen (for auto-reset)
        self._context_builder = ContextBuilder(self._BOT_NAMES)
        self._load_state()
        self._init_gemini()
        asyncio.ensure_future(self._ensure_danetki_table())
        asyncio.ensure_future(llm_trace.ensure_table(self.db))
        asyncio.ensure_future(self._reminder_loop())
        self._register()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load_state(self):
        """Load persisted reset state from disk (survives bot restarts)."""
        try:
            with open(STATE_PATH, encoding="utf-8") as f:
                data = json.load(f)
            for chat_id_str, ts in data.get("history_reset_time", {}).items():
                self._history_reset_time[int(chat_id_str)] = datetime.fromisoformat(ts)
            for chat_id_str, ts in data.get("memory_cursor", {}).items():
                self._memory_cursor[int(chat_id_str)] = datetime.fromisoformat(ts)
            if data.get("reasoning_effort") in REASONING_LEVELS:
                self._reasoning_effort = data["reasoning_effort"]
            if data.get("reasoning_last_activity"):
                self._reasoning_last_activity = datetime.fromisoformat(data["reasoning_last_activity"])
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
                "memory_cursor": {
                    str(k): v.isoformat() for k, v in getattr(self, "_memory_cursor", {}).items()
                },
                "reasoning_effort": self._reasoning_effort,
                "reasoning_last_activity": (
                    self._reasoning_last_activity.isoformat() if self._reasoning_last_activity else None
                ),
            }
            with open(STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"MoltBot: could not save state: {e}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _touch_reasoning_activity(self) -> None:
        """Record chat activity; the auto-reset countdown for reasoning depth starts from here."""
        self._reasoning_last_activity = datetime.now(timezone.utc)

    def _current_reasoning_effort(self) -> str:
        """Effective reasoning level for the next persona call.

        Lazily falls back to REASONING_DEFAULT once the chat has been silent for
        REASONING_RESET_AFTER — no timer needed, the check runs on every call.
        """
        if self._reasoning_effort != REASONING_DEFAULT and self._reasoning_last_activity is not None:
            idle = datetime.now(timezone.utc) - self._reasoning_last_activity
            if idle >= REASONING_RESET_AFTER:
                logger.info(f"MoltBot: reasoning {self._reasoning_effort} → {REASONING_DEFAULT} "
                            f"after {idle} of chat silence")
                self._reasoning_effort = REASONING_DEFAULT
                self._save_state()
        return self._reasoning_effort

    def _set_reasoning_effort(self, level: str) -> None:
        if level not in REASONING_LEVELS:
            raise ValueError(f"bad reasoning level: {level}")
        self._reasoning_effort = level
        self._touch_reasoning_activity()
        self._save_state()
        logger.info(f"MoltBot: reasoning effort set to {level}")

    def _reasoning_reset_in(self) -> timedelta | None:
        """Time left until auto-reset, or None when already at the default."""
        if self._reasoning_effort == REASONING_DEFAULT or self._reasoning_last_activity is None:
            return None
        left = REASONING_RESET_AFTER - (datetime.now(timezone.utc) - self._reasoning_last_activity)
        return max(left, timedelta(0))

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
            logger.info(f"MoltBot: Gemini image analysis: {result}")
            return result
        except Exception as e:
            logger.error(f"MoltBot: Gemini image analysis failed: {e}")
            return "[Не удалось проанализировать изображение]"

    def _analyze_animation_with_gemini(self, animation_bytes: bytes, user_question: str) -> str:
        """Send a GIF (Telegram animation, silent mp4) to Gemini and get a description / answer."""
        if not self._gemini_model:
            return "[Анализ гифки недоступен — Gemini не настроен]"
        try:
            prompt = "Это гифка (обычно мем или реакция, без звука). Опиши что на ней происходит."
            if user_question:
                prompt += f" Также ответь на вопрос: {user_question}"
            response = self._gemini_model.generate_content([
                {"mime_type": "video/mp4", "data": animation_bytes},
                prompt,
            ])
            result = response.text
            logger.info(f"MoltBot: Gemini animation analysis: {result}")
            return result
        except Exception as e:
            logger.error(f"MoltBot: Gemini animation analysis failed: {e}")
            return "[Не удалось проанализировать гифку]"

    async def _store_user_message(self, message):
        """Store a user message in the messages table (for analytics)."""
        self._touch_reasoning_activity()
        try:
            if message.text and message.from_user and not message.from_user.is_bot:
                name = message.from_user.first_name or message.from_user.username or 'Аноним'
                reply_to = message.reply_to_message.message_id if message.reply_to_message else None
                await self.db.execute_query(
                    "INSERT INTO messages (chat_id, user_id, message_text, timestamp, name, message_id, reply_to_message_id) "
                    "VALUES (%s, %s, %s, CURRENT_TIMESTAMP, %s, %s, %s) "
                    "ON CONFLICT (chat_id, message_id) WHERE message_id IS NOT NULL DO NOTHING",
                    (message.chat.id, message.from_user.id, message.text, name, message.message_id, reply_to),
                )
        except Exception as e:
            logger.warning(f"MoltBot: failed to store user message: {e}")

    async def _store_bot_reply(self, text: str, chat_id: int,
                               msg_id: int | None = None, reply_to: int | None = None):
        """Store Jarvis bot reply in the messages table.
        `reply_to` = message_id of the user message this reply answers (for reply-thread context)."""
        try:
            await self.db.execute_query(
                "INSERT INTO messages (chat_id, user_id, message_text, timestamp, name, message_id, reply_to_message_id) "
                "VALUES (%s, %s, %s, CURRENT_TIMESTAMP, %s, %s, %s) "
                "ON CONFLICT (chat_id, message_id) WHERE message_id IS NOT NULL DO NOTHING",
                (chat_id, 0, text, "Jarvis", msg_id, reply_to),
            )
        except Exception as e:
            logger.warning(f"MoltBot: failed to store bot reply: {e}")

    async def _get_recent_group_messages(self, chat_id: int, limit: int = 50,
                                         exclude_message_id: int | None = None) -> list[str]:
        """Fetch last `limit` messages from the group chat history in DB."""
        try:
            reset_time = self._history_reset_time.get(chat_id)
            if reset_time:
                query = """
                    SELECT name, message_text, timestamp
                    FROM messages
                    WHERE chat_id = %s
                      AND timestamp >= %s
                      AND (%s IS NULL OR message_id IS DISTINCT FROM %s)
                    ORDER BY timestamp DESC
                    LIMIT %s
                """
                rows = await self.db.execute_query(
                    query, (chat_id, reset_time, exclude_message_id, exclude_message_id, limit)
                )
            else:
                query = """
                    SELECT name, message_text, timestamp
                    FROM messages
                    WHERE chat_id = %s
                      AND (%s IS NULL OR message_id IS DISTINCT FROM %s)
                    ORDER BY timestamp DESC
                    LIMIT %s
                """
                rows = await self.db.execute_query(
                    query, (chat_id, exclude_message_id, exclude_message_id, limit)
                )
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

    async def _get_reply_chain(self, chat_id: int, reply_to_message_id: int | None,
                               limit: int = 12) -> list[str]:
        """Return the quoted Telegram branch, oldest ancestor first."""
        if reply_to_message_id is None:
            return []
        try:
            rows = await self.db.execute_query(
                """
                WITH RECURSIVE reply_chain AS (
                    SELECT name, message_text, timestamp, message_id,
                           reply_to_message_id, 0 AS depth,
                           ARRAY[message_id]::BIGINT[] AS path
                    FROM messages
                    WHERE chat_id = %s AND message_id = %s

                    UNION ALL

                    SELECT parent.name, parent.message_text, parent.timestamp,
                           parent.message_id, parent.reply_to_message_id,
                           child.depth + 1,
                           child.path || parent.message_id
                    FROM messages parent
                    JOIN reply_chain child
                      ON parent.chat_id = %s
                     AND parent.message_id = child.reply_to_message_id
                    WHERE child.depth < %s
                      AND NOT parent.message_id = ANY(child.path)
                )
                SELECT name, message_text, timestamp
                FROM reply_chain
                ORDER BY depth DESC
                """,
                (chat_id, reply_to_message_id, chat_id, max(0, limit - 1)),
            )
            return [
                f"{self._format_ts(row[2])} {row[0] or 'Аноним'}: {row[1]}"
                for row in (rows or [])
            ]
        except Exception as e:
            logger.error(f"MoltBot: error fetching reply chain: {e}")
            return []

    async def _build_thread_first_history(self, chat_id: int,
                                          reply_to_message_id: int | None,
                                          current_message_id: int | None,
                                          recent_limit: int = HISTORY_MESSAGE_LIMIT,
                                          char_budget: int = HISTORY_CHAR_BUDGET) -> list[str]:
        """Compose reply branch first, then the broader scene without duplicates."""
        thread = await self._get_reply_chain(chat_id, reply_to_message_id)
        recent = await self._get_recent_group_messages(
            chat_id, limit=recent_limit, exclude_message_id=current_message_id
        )
        return compose_thread_first(thread, recent, limit=recent_limit, char_budget=char_budget)

    async def _together_post(self, payload: dict, timeout: float) -> dict:
        """POST to Together.ai (streaming) with retry on 5xx and transient errors.

        Always streams — some models (e.g. Qwen3.7-Max) only support streaming,
        and it's harmless for the rest — then accumulates the SSE deltas back into
        the standard non-streaming response shape so callers stay unchanged.
        3 attempts total with 1.5s/3s backoff. Returns
        {"choices": [{"message": {"content": <full text>}}]} or raises last error."""
        url = "https://api.together.xyz/v1/chat/completions"
        headers = {"Authorization": f"Bearer {Settings.TOGETHER_API_KEY}"}
        payload = {**payload, "stream": True}
        delays = [0, 1.5, 3.0]
        last_exc: Exception | None = None
        async with httpx.AsyncClient() as client:
            for attempt, delay in enumerate(delays, start=1):
                if delay:
                    await asyncio.sleep(delay)
                try:
                    async with client.stream("POST", url, headers=headers,
                                             json=payload, timeout=timeout) as r:
                        if r.status_code in (429, 502, 503, 504):
                            await r.aread()
                            last_exc = httpx.HTTPStatusError(
                                f"Together.ai {r.status_code}", request=r.request, response=r
                            )
                            logger.warning(f"MoltBot: Together.ai {r.status_code}, retry {attempt}/3")
                            continue
                        if r.status_code != 200:
                            body = (await r.aread()).decode(errors="replace")[:300]
                            raise _AIConnectionError(f"Together.ai {r.status_code}: {body}")
                        chunks: list[str] = []
                        tool_calls: dict[int, dict] = {}
                        async for line in r.aiter_lines():
                            if not line or not line.startswith("data: "):
                                continue
                            data = line[6:]
                            if data.strip() == "[DONE]":
                                break
                            try:
                                delta = json.loads(data)["choices"][0].get("delta") or {}
                            except Exception:
                                continue
                            piece = delta.get("content")
                            if piece:
                                chunks.append(piece)
                            # Function-calling deltas arrive in pieces keyed by index
                            for tc in delta.get("tool_calls") or []:
                                idx = tc.get("index", 0)
                                acc = tool_calls.setdefault(idx, {
                                    "id": None, "type": "function",
                                    "function": {"name": "", "arguments": ""},
                                })
                                if tc.get("id"):
                                    acc["id"] = tc["id"]
                                fn = tc.get("function") or {}
                                if fn.get("name"):
                                    acc["function"]["name"] += fn["name"]
                                if fn.get("arguments"):
                                    acc["function"]["arguments"] += fn["arguments"]
                        message: dict = {"content": "".join(chunks)}
                        if tool_calls:
                            message["tool_calls"] = [tool_calls[i] for i in sorted(tool_calls)]
                        return {"choices": [{"message": message}]}
                except (httpx.TransportError, httpx.TimeoutException) as e:
                    last_exc = e
                    logger.warning(f"MoltBot: Together.ai transient error ({e!r}), retry {attempt}/3")
                    continue
        raise last_exc if last_exc else _AIConnectionError("Together.ai retry exhausted")

    async def _call_together_simple(self, prompt: str, chat_id: int | None = None) -> str:
        """Call Together.ai with a raw prompt + IDENTITY. Used for proactive/probabilistic messages."""
        if not Settings.TOGETHER_API_KEY:
            raise _AIConnectionError("TOGETHER_API_KEY not set")
        if not together_breaker.allow_request():
            raise _AIConnectionError("together circuit breaker open")
        messages = await self._build_persona_messages(
            "Служебная задача", prompt, "проактивное участие в групповом чате", None, chat_id
        )
        try:
            text = await self._complete_with_tools(
                self._together_post,
                {
                    "model": Settings.TOGETHER_MODEL,
                    "messages": messages,
                    "max_tokens": 500,
                    "temperature": 0.8,
                },
                timeout=120,
            )
            together_breaker.record_success()
            return self._clean_persona_reply(text)
        except Exception as e:
            together_breaker.record_failure()
            logger.error(f"MoltBot: Together.ai simple call failed: {e}")
            raise _AIConnectionError(str(e))

    async def _call_openrouter_simple(self, prompt: str, chat_id: int | None = None) -> str:
        """Call OpenRouter (Grok) with a raw prompt + IDENTITY. Primary for proactive/probabilistic messages."""
        if not Settings.OPENROUTER_API_KEY:
            raise _AIConnectionError("OPENROUTER_API_KEY not set")
        if not openrouter_breaker.allow_request():
            raise _AIConnectionError("openrouter circuit breaker open")
        messages = await self._build_persona_messages(
            "Служебная задача", prompt, "проактивное участие в групповом чате", None, chat_id
        )
        try:
            text = await self._complete_with_tools(
                self._openrouter_post,
                {
                    "model": Settings.OPENROUTER_MODEL,
                    "messages": messages,
                    "max_tokens": 500,
                    "temperature": 0.8,
                    "reasoning": {"effort": self._current_reasoning_effort()},
                },
                timeout=120,
            )
            openrouter_breaker.record_success()
            return self._clean_persona_reply(text)
        except Exception as e:
            openrouter_breaker.record_failure()
            logger.warning(f"MoltBot: OpenRouter simple call failed: {e}")
            raise

    async def _call_persona_simple(self, prompt: str, chat_id: int | None = None) -> str:
        """Primary entry point for proactive/probabilistic messages: OpenRouter/Grok first, Together.ai on failure."""
        try:
            return await self._call_openrouter_simple(prompt, chat_id)
        except Exception as e:
            logger.info(f"MoltBot: falling back to Together.ai (simple) after OpenRouter failure ({e})")
            return await self._call_together_simple(prompt, chat_id)

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
                               chat_context: str, history: list[str] | None = None,
                               chat_id: int | None = None) -> str:
        """Call Gemini for text generation. INTERNET fallback — Gemini has fresher knowledge."""
        if not self._gemini_model:
            raise _AIConnectionError("Gemini not initialized")
        snapshot = await self._build_context_snapshot(
            sender_name, user_text, chat_context, history, chat_id
        )
        prompt = self._get_context_builder().flatten(snapshot)

        async def generate():
            response = await asyncio.to_thread(self._gemini_model.generate_content, prompt)
            return response.text

        return await self._traced_attempt("gemini", "gemini-2.5-flash-lite", generate)

    async def _count_recent_messages(self, chat_id: int, minutes: int) -> int:
        """Count messages in DB written in the last `minutes` minutes."""
        try:
            rows = await self.db.execute_query(
                "SELECT COUNT(*) FROM messages WHERE chat_id = %s "
                "AND timestamp > NOW() - INTERVAL '1 minute' * %s",
                (chat_id, minutes)
            )
            return rows[0][0] if rows else 0
        except Exception as e:
            logger.error(f"MoltBot: error counting recent messages: {e}")
            return 0

    async def _send_proactive_message(self, chat_id: int):
        """Build context and send a proactive (unprompted) message to the chat."""
        try:
            history = await self._get_recent_group_messages(chat_id, limit=50)

            context_prefix = ""
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

            reply = await self._call_persona_simple(user_content, chat_id)

            # Reply to the most recent stored message if we have its Telegram message_id
            reply_to = None
            try:
                rows = await self.db.execute_query(
                    "SELECT message_id FROM messages WHERE chat_id = %s AND message_id IS NOT NULL "
                    "ORDER BY timestamp DESC LIMIT 1",
                    (chat_id,),
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
        count = await self._count_recent_messages(chat_id, 30)
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

    async def _update_summary(self, chat_id: int) -> tuple[bool, str]:
        """Rebuild chat-summary.md from recent HUMAN messages only.

        Deliberately not fed with the previous summary or Jarvis' own replies:
        both let the bot's jokes and stale items survive as "facts" (see the
        2026-09-22 audit — Лисёнок: 2 human vs 39 bot mentions). Lore proposals
        go to a review file instead of being pinned automatically.
        Returns (ok, human-readable detail) for /memory_refresh.
        """
        try:
            ok, detail = await self._rebuild_summary(chat_id)
        except Exception as e:
            ok, detail = False, f"ошибка: {e}"
            logger.error(f"MoltBot: summary update failed: {e}")
        if not ok:
            # Retry in ~1h instead of waiting another full day.
            self._last_summary_update[chat_id] = (
                datetime.now(timezone.utc) - timedelta(hours=SUMMARY_UPDATE_HOURS - 1)
            )
        return ok, detail

    async def _rebuild_summary(self, chat_id: int) -> tuple[bool, str]:
        cursor = getattr(self, "_memory_cursor", {}).get(chat_id)
        rows = await self.db.execute_query(
            "SELECT name, message_text, timestamp FROM messages "
            "WHERE chat_id = %s AND user_id <> 0 "
            "AND timestamp >= NOW() - INTERVAL '%s hours' "
            "AND (%s::timestamptz IS NULL OR timestamp >= %s::timestamptz) "
            "ORDER BY timestamp DESC LIMIT %s",
            (chat_id, SUMMARY_FETCH_HOURS, cursor, cursor, SUMMARY_MAX_MESSAGES),
        )
        if not rows:
            return False, "нет новых человеческих сообщений"
        messages: list[str] = []
        used = 0
        for r in rows:  # newest first → keep the freshest within the budget
            line = f"{self._format_ts(r[2])} {r[0] or 'Аноним'}: {r[1]}"
            if used + len(line) > SUMMARY_CHAR_BUDGET:
                break
            messages.append(line)
            used += len(line)
        history_text = "\n".join(reversed(messages))

        current_lore = _load_chat_lore(chat_id)

        prompt = f"""[СЛУЖЕБНЫЙ ЗАПРОС — пересборка короткой памяти чата]

Ты ведёшь короткую память о групповом чате друзей. Собери её с нуля ТОЛЬКО по сообщениям ниже — всё, чего в них нет, считается неактуальным. Память состоит из двух секций (+ опциональная третья — НА ЗАКРЕП).

== УЧАСТНИКИ (для атрибуции, все мужчины — правильный род) ==
- Макс (Max, Spedymax) — программист, создатель бота, живёт в Дании
- Юра (Юрочка, Spatifilum) — геймер
- Богдан (Бодя, @lofiSnitch) — учится в Эрлангене
- Шева — друг, иногда в доте, не в чате
- Кеша/Джарвис — это сам бот; его реплик здесь нет специально

== УЖЕ ЗАКРЕПЛЕНО НАВСЕГДА (НЕ дублируй это в секции НА ЗАКРЕП) ==
{current_lore or '(пусто)'}

== СООБЩЕНИЯ ЛЮДЕЙ ЗА ПОСЛЕДНИЕ {SUMMARY_FETCH_HOURS} ЧАСОВ ==
{history_text}

== ФОРМАТ ПАМЯТИ (именно такие заголовки) ==

== ЧТО ПРОИСХОДИТ СЕЙЧАС ==
Чем сейчас живут ребята: дела, планы, события, повторяющиеся темы. Коротко, по факту, с датой, если она важна («в субботу 26.09 играют»), а не «недавно»/«скоро».

== ЖИВЫЕ ВНУТРЯКИ ==
Фраза/прикол попадает сюда ТОЛЬКО если он реально повторялся в этих сообщениях — к нему возвращались, цитировали или переспрашивали минимум 2 раза (в идеале разные люди). Одноразовая смешная фраза, случайный мат, эмоциональный вскрик ("ЕБАТЬ", "НАЛИВАЙ") — это НЕ внутряк, не записывай. Сомневаешься — не пиши.
Максимум 8 штук. Для каждого: сам внутряк + одной короткой фразой что значит.

== НА ЗАКРЕП ==
Кандидаты в легенду чата: внутряк/персонаж/мем, который люди поднимают снова и снова. Если такого нет — оставь секцию ПУСТОЙ (это норма). Максимум 1-2. НЕ дублируй «УЖЕ ЗАКРЕПЛЕНО». НИКОГДА не предлагай ничего про несовершеннолетних или реальное насилие. Каждый — одной строкой: суть + что значит.

== ПРАВИЛА ==
- Только факты из сообщений. НЕ интерпретируй и не додумывай ("ирония", "возможно отсылка", "неясно что").
- Слова одного человека о другом записывай как «Юра говорит, что Богдан…», а не как факт.
- Не записывай оскорбления, сексуальные характеристики, диагнозы и прочие чувствительные оценки людей.
- Память (первые две секции) — не длиннее ~1500 символов. Лучше пустая секция, чем мусор.
- Верни ТОЛЬКО текст (две секции памяти + при необходимости НА ЗАКРЕП), без markdown-решёток, обёрток и пояснений."""

        if not Settings.TOGETHER_API_KEY:
            logger.warning("MoltBot: TOGETHER_API_KEY not set, falling back to Ollama for summary")
            new_summary = await asyncio.to_thread(self._call_ollama_direct, prompt)
        else:
            try:
                data = await self._together_post(
                    {
                        "model": Settings.TOGETHER_MODEL,
                        "messages": [
                            {"role": "system", "content": "Ты ведёшь короткую память о групповом чате. Только факты, строгая планка для внутряков, без воды."},
                            {"role": "user", "content": prompt},
                        ],
                        "max_tokens": 900,
                        "temperature": 0.4,
                    },
                    timeout=180,
                )
                new_summary = data["choices"][0]["message"]["content"]
                new_summary = re.sub(r'<think>.*?(?:</think>|$)', '', new_summary, flags=re.DOTALL).strip()
            except Exception as e:
                logger.warning(f"MoltBot: Together.ai summary failed, falling back to Ollama: {e}")
                new_summary = await asyncio.to_thread(self._call_ollama_direct, prompt)

        if not new_summary or len(new_summary) < 50:
            logger.warning("MoltBot: LLM returned suspiciously short summary, skipping save")
            return False, "модель вернула пустой/слишком короткий ответ, старая память оставлена"
        # Separate the optional pin section from the rolling summary so it never
        # pollutes chat-summary.md; it becomes a candidate for manual review.
        summary_text, pin_block = new_summary, ""
        parts = re.split(r'==\s*НА\s+ЗАКРЕП\s*==', new_summary, maxsplit=1)
        if len(parts) == 2:
            summary_text, pin_block = parts[0].strip(), parts[1].strip()
        # Hard backstop against runaway growth (prompt asks for ~1500)
        summary_text = summary_text[:2500].strip()

        _atomic_write(_chat_memory_path(CHAT_SUMMARY_PATH, chat_id), summary_text)
        logger.info(f"MoltBot: summary updated for chat {chat_id} ({len(summary_text)} chars, "
                    f"{len(messages)} human msgs)")
        proposed = self._propose_lore(pin_block, chat_id) if pin_block else []
        detail = f"{len(summary_text)} симв. из {len(messages)} сообщений"
        if proposed:
            detail += f"; кандидатов в закреп: {len(proposed)}"
        return True, detail

    _LORE_CAP = 20
    _MEMORY_CLEAR_SCOPES = {
        "rolling": "rolling", "summary": "rolling", "текущую": "rolling", "текущая": "rolling",
        "lore": "lore", "лор": "lore", "закреп": "lore",
        "all": "all", "всё": "all", "все": "all",
    }
    _LORE_CANDIDATES_CAP = 10

    def _propose_lore(self, pin_block: str, chat_id: int) -> list[str]:
        """Queue LLM-proposed in-jokes for admin review (dedup against lore + queue).
        Never auto-pins: the bot must not be able to make its own jokes permanent."""
        def _sig_words(s: str) -> set:
            # proper nouns (Capitalized+lowercase tail) — the real key of an in-joke
            # ("Коваленко", "Фреско"); topical lowercase words are ignored to avoid
            # over-suppressing distinct jokes that merely share a theme word.
            return {w.lower() for w in re.findall(r'[A-ZА-ЯЁ][a-zа-яё]{3,}', s)}

        try:
            lore = _lore_lines(chat_id)
            queued = _lore_candidate_lines(chat_id)
            kept = lore + queued
            kept_lc = [l.lower() for l in kept]
            kept_sig = [_sig_words(l) for l in kept]
            added = []
            for raw in pin_block.splitlines():
                cand = re.sub(r'^\s*[-•*]?\s*\d{0,2}[.)]?\s*', '', raw).strip()
                if len(cand) < 8 or cand.startswith('(') or cand.startswith('=='):
                    continue
                cl = cand.lower()
                csig = _sig_words(cand)
                # dup if substring overlap OR shares a distinctive token with an existing pin
                if any(cl in e or e in cl for e in kept_lc) or any(csig & ks for ks in kept_sig):
                    continue
                kept.append(cand)
                kept_lc.append(cl)
                kept_sig.append(csig)
                added.append(cand)
            if added:
                queued = (queued + added)[-self._LORE_CANDIDATES_CAP:]
                _save_lore_candidate_lines(queued, chat_id)
                logger.info(f"MoltBot: queued {len(added)} lore candidate(s) for review: {added}")
            return added
        except Exception as e:
            logger.error(f"MoltBot: lore proposal failed: {e}")
            return []

    def _maybe_update_summary(self, chat_id: int):
        """Trigger summary update if enough time has passed (every SUMMARY_UPDATE_HOURS)."""
        now = datetime.now(timezone.utc)
        last_update = self._last_summary_update.get(chat_id)
        if last_update and (now - last_update) < timedelta(hours=SUMMARY_UPDATE_HOURS):
            return
        self._last_summary_update[chat_id] = now
        asyncio.create_task(self._update_summary(chat_id))
        logger.info(f"MoltBot: triggered background summary update for chat {chat_id} (24h timer)")

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

    _HARD_RULES = ""

    _POST_PROMPT_BASE = PERSONA_POST_PROMPT

    @staticmethod
    def _persona_overlay() -> str:
        """Whatever the boss event wants to inject (Pudginio hijack, MVP respect).
        A sync cache refreshed by BossHandlers' tick; ContextBuilder frames it so it
        may change the voice but not facts, dates or grounding."""
        try:
            from services.boss_service import get_boss_service
            _boss = get_boss_service()
            return (_boss.persona_injection if _boss else "") or ""
        except Exception:
            return ""

    @property
    def _POST_PROMPT(self) -> str:
        """Post-prompt as the model sees it, overlay framing aside (kept for scripts)."""
        inj = self._persona_overlay()
        return f"{self._POST_PROMPT_BASE}\n\n{inj}" if inj else self._POST_PROMPT_BASE

    @staticmethod
    def _clock_text(now: datetime | None = None) -> str:
        return format_clock(now)

    # Bot names used to identify assistant messages in history
    _BOT_NAMES = {
        "Кеша", "Иннокентий", "Лолита", "Ло", "Лола",
        "Jarvis", "Джарвис", "MoltBot",
    }

    def _get_context_builder(self) -> ContextBuilder:
        # Tests and a few maintenance scripts instantiate the handler via __new__.
        builder = getattr(self, '_context_builder', None)
        if builder is None:
            builder = ContextBuilder(self._BOT_NAMES)
            self._context_builder = builder
        return builder

    def _history_to_messages(self, history: list[str], sender_name: str,
                             user_text: str) -> list[dict]:
        """Compatibility wrapper around the canonical ContextBuilder parser."""
        messages = self._get_context_builder().history_to_messages(history)
        messages.append({"role": "user", "content": f"{sender_name}: {user_text}"})
        return messages

    async def _build_context_snapshot(self, sender_name: str, user_text: str,
                                      chat_context: str, history: list[str] | None,
                                      chat_id: int | None = None) -> ContextSnapshot:
        """Load dynamic inputs once and build the provider-neutral context snapshot."""
        prompt_version = None
        try:
            from services.prompt_service import get_prompt_service
            prompt_service = get_prompt_service()
            identity = await prompt_service.get_current_identity()
            prompt_version = getattr(prompt_service, "_cache_version_id", None)
        except Exception:
            identity = ""
        snapshot = self._get_context_builder().build(
            identity=identity,
            hard_rules=self._HARD_RULES,
            chat_context=chat_context,
            summary=_load_chat_summary(chat_id),
            lore=_load_chat_lore(chat_id),
            history=history,
            sender_name=sender_name,
            user_text=user_text,
            post_prompt=self._POST_PROMPT_BASE,
            clock=self._clock_text(),
            overlay=self._persona_overlay(),
        )
        trace = llm_trace.current()
        if trace:
            trace.sections = dict(snapshot.section_chars)
            trace.prompt_version = prompt_version
        return snapshot

    async def _build_persona_messages(self, sender_name: str, user_text: str,
                                      chat_context: str, history: list[str] | None,
                                      chat_id: int | None = None) -> list[dict]:
        """Build the system+history+user message list shared by every persona-chat provider."""
        snapshot = await self._build_context_snapshot(
            sender_name, user_text, chat_context, history, chat_id
        )
        return snapshot.as_messages()

    @staticmethod
    def _clean_persona_reply(text: str) -> str:
        text = re.sub(r'<think>.*?(?:</think>|$)', '', text, flags=re.DOTALL).strip()
        text = re.sub(r'\*[^*]{2,80}\*', '', text)
        text = re.sub(r'\n\s*\n\s*\n', '\n\n', text).strip()
        return text

    def _provider_ids(self, chat_id: int | None) -> dict:
        """Opaque OpenRouter identifiers: session = (chat, context epoch) for sticky
        routing / prompt cache; trace_id links provider logs to llm_traces."""
        if chat_id is None:
            return {}
        epoch = getattr(self, "_history_reset_time", {}).get(chat_id)
        ids = {
            "user": llm_trace.opaque_id("chat", chat_id),
            "session_id": llm_trace.opaque_id("session", chat_id, epoch.isoformat() if epoch else "0"),
        }
        trace = llm_trace.current()
        if trace:
            ids["trace"] = {"trace_id": trace.trace_id, "generation_name": trace.kind}
        return ids

    async def _traced_attempt(self, provider: str, model: str, call):
        """Run one provider call, recording it as an attempt on the current trace."""
        trace = llm_trace.current()
        attempt = trace.start_attempt(provider, model) if trace else None
        started = time.monotonic()
        try:
            result = await call()
            if attempt:
                attempt.ok = bool(result and str(result).strip())
                if not attempt.ok:
                    attempt.error = "empty"
            return result
        except Exception as e:
            if attempt:
                attempt.error = f"{type(e).__name__}: {str(e)[:200]}"
            raise
        finally:
            if attempt:
                attempt.latency_ms = int((time.monotonic() - started) * 1000)

    async def _call_together(self, sender_name: str, user_text: str,
                             chat_context: str, history: list[str] | None = None,
                             chat_id: int | None = None) -> str:
        """Call Together.ai with IDENTITY.md as system prompt and proper multi-turn."""
        if not Settings.TOGETHER_API_KEY:
            raise _AIConnectionError("TOGETHER_API_KEY not set")
        messages = await self._build_persona_messages(
            sender_name, user_text, chat_context, history, chat_id
        )
        text = await self._traced_attempt("together", Settings.TOGETHER_MODEL, lambda: self._complete_with_tools(
            self._together_post,
            {
                "model": Settings.TOGETHER_MODEL,
                "messages": messages,
                "max_tokens": 3000,
                "temperature": 0.8,
            },
            timeout=120,
        ))
        return self._clean_persona_reply(text)

    async def _openrouter_post(self, payload: dict, timeout: float) -> dict:
        """POST to OpenRouter (non-streaming) with retry on 5xx/429 and transient errors."""
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {"Authorization": f"Bearer {Settings.OPENROUTER_API_KEY}"}
        delays = [0, 1.5, 3.0]
        last_exc: Exception | None = None
        async with httpx.AsyncClient() as client:
            for attempt, delay in enumerate(delays, start=1):
                if delay:
                    await asyncio.sleep(delay)
                try:
                    r = await client.post(url, headers=headers, json=payload, timeout=timeout)
                    if r.status_code in (429, 502, 503, 504):
                        last_exc = httpx.HTTPStatusError(
                            f"OpenRouter {r.status_code}", request=r.request, response=r
                        )
                        logger.warning(f"MoltBot: OpenRouter {r.status_code}, retry {attempt}/3")
                        continue
                    if r.status_code != 200:
                        raise _AIConnectionError(f"OpenRouter {r.status_code}: {r.text[:300]}")
                    data = r.json()
                    if "choices" not in data:
                        raise _AIConnectionError(f"OpenRouter bad response: {str(data)[:300]}")
                    return data
                except (httpx.TransportError, httpx.TimeoutException) as e:
                    last_exc = e
                    logger.warning(f"MoltBot: OpenRouter transient error ({e!r}), retry {attempt}/3")
                    continue
        raise last_exc if last_exc else _AIConnectionError("OpenRouter retry exhausted")

    async def _call_openrouter(self, sender_name: str, user_text: str,
                               chat_context: str, history: list[str] | None = None,
                               chat_id: int | None = None) -> str:
        """Call OpenRouter (Grok by default) — primary persona-chat model.

        Grok was picked over Together's Qwen after a direct A/B test: on a real
        chat scene where the bot got called out for dodging ("а че ты woke такой"),
        Qwen/Llama kept deflecting ("это спам/шиза") instead of giving an actual
        opinion, while Grok gave a real take without moralizing. See v25 identity
        test in chat 2026-08-14/17.
        """
        if not Settings.OPENROUTER_API_KEY:
            raise _AIConnectionError("OPENROUTER_API_KEY not set")
        if not openrouter_breaker.allow_request():
            raise _AIConnectionError("openrouter circuit breaker open")
        messages = await self._build_persona_messages(
            sender_name, user_text, chat_context, history, chat_id
        )
        effort = self._current_reasoning_effort()
        trace = llm_trace.current()
        if trace:
            trace.reasoning = effort
        try:
            text = await self._traced_attempt("openrouter", Settings.OPENROUTER_MODEL, lambda: self._complete_with_tools(
                self._openrouter_post,
                {
                    "model": Settings.OPENROUTER_MODEL,
                    "messages": messages,
                    "max_tokens": 3000,
                    "temperature": 0.8,
                    "reasoning": {"effort": effort},
                    **self._provider_ids(chat_id),
                },
                timeout=120,
            ))
            openrouter_breaker.record_success()
            return self._clean_persona_reply(text)
        except Exception as e:
            openrouter_breaker.record_failure()
            logger.warning(f"MoltBot: OpenRouter call failed: {e}")
            raise

    async def _call_persona(self, sender_name: str, user_text: str,
                            chat_context: str, history: list[str] | None = None,
                            chat_id: int | None = None) -> str:
        """Primary persona-chat entry point: OpenRouter/Grok first, Together.ai on failure."""
        try:
            return await self._call_openrouter(sender_name, user_text, chat_context, history, chat_id)
        except Exception as e:
            logger.info(f"MoltBot: falling back to Together.ai after OpenRouter failure ({e})")
            return await self._call_together(sender_name, user_text, chat_context, history, chat_id)

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

    # Brave free tier allows about one request per second, while the model
    # happily asks for 3-5 searches in a single turn. Requests are therefore
    # serialized process-wide with a minimum gap, a 429 is retried once, and
    # repeated queries (the model likes spelling variants of the same name)
    # are answered from a short-lived in-process cache.
    _BRAVE_MIN_INTERVAL = 1.2      # seconds between two Brave requests
    _BRAVE_RETRY_DELAY = 1.5       # extra pause before the single retry on 429
    _BRAVE_CACHE_TTL = 600         # seconds a query result stays reusable
    _BRAVE_CACHE_MAX = 128
    _brave_last_call = 0.0
    _brave_cache: dict = {}
    _brave_lock = None
    _brave_lock_loop = None

    @classmethod
    def _get_brave_lock(cls) -> asyncio.Lock:
        """One lock per event loop (a Lock is bound to the loop that first used it)."""
        loop = asyncio.get_running_loop()
        if cls._brave_lock is None or cls._brave_lock_loop is not loop:
            cls._brave_lock = asyncio.Lock()
            cls._brave_lock_loop = loop
        return cls._brave_lock

    @classmethod
    def _brave_cache_get(cls, key: str):
        hit = cls._brave_cache.get(key)
        if hit is None:
            return None
        cached_at, value = hit
        if time.monotonic() - cached_at > cls._BRAVE_CACHE_TTL:
            cls._brave_cache.pop(key, None)
            return None
        return value

    @classmethod
    def _brave_cache_put(cls, key: str, value: str):
        if len(cls._brave_cache) >= cls._BRAVE_CACHE_MAX:
            oldest = min(cls._brave_cache, key=lambda k: cls._brave_cache[k][0])
            cls._brave_cache.pop(oldest, None)
        cls._brave_cache[key] = (time.monotonic(), value)

    @classmethod
    async def _brave_wait_turn(cls):
        """Hold the next Brave request until _BRAVE_MIN_INTERVAL has passed."""
        gap = cls._BRAVE_MIN_INTERVAL - (time.monotonic() - cls._brave_last_call)
        if gap > 0:
            await asyncio.sleep(gap)
        cls._brave_last_call = time.monotonic()

    async def _brave_request(self, query: str, count: int) -> str:
        """One Brave API call. Raises httpx.HTTPStatusError on a bad status."""
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={"X-Subscription-Token": Settings.BRAVE_API_KEY,
                         "Accept": "application/json"},
                params={"q": query, "count": count},
                timeout=10,
            )
            r.raise_for_status()
            data = r.json()
            results = []
            for item in (data.get("web", {}).get("results") or [])[:count]:
                title = item.get("title", "")
                desc = item.get("description", "")
                results.append(f"- {title}: {desc}")
            return "\n".join(results) if results else ""

    async def _brave_search(self, query: str, count: int = 5) -> str:
        """Search the web via Brave Search API. Returns formatted results."""
        if not Settings.BRAVE_API_KEY:
            return ""
        key = " ".join(query.lower().split())
        cached = self._brave_cache_get(key)
        if cached is not None:
            logger.info(f"MoltBot: Brave cache hit for '{query}'")
            return cached
        async with self._get_brave_lock():
            # Another call may have searched the same thing while we waited
            cached = self._brave_cache_get(key)
            if cached is not None:
                logger.info(f"MoltBot: Brave cache hit for '{query}'")
                return cached
            for attempt in range(2):
                await self._brave_wait_turn()
                try:
                    results = await self._brave_request(query, count)
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429 and attempt == 0:
                        logger.warning(f"MoltBot: Brave rate-limited on '{query}', retrying once")
                        await asyncio.sleep(self._BRAVE_RETRY_DELAY)
                        continue
                    logger.warning(f"MoltBot: Brave search failed: {e}")
                    return ""
                except Exception as e:
                    logger.warning(f"MoltBot: Brave search failed: {e}")
                    return ""
                self._brave_cache_put(key, results)
                return results
        return ""

    # ------------------------------------------------------------------
    # Web search as a native tool call (OpenAI-compatible function calling).
    # The model calls web_search(query) instead of emitting "SEARCH: ..." as
    # text — text markers leaked into the chat whenever the intercept missed.
    # ------------------------------------------------------------------
    _WEB_SEARCH_TOOL = WEB_SEARCH_TOOL
    # How many rounds of tool calls we allow before forcing a plain answer
    _MAX_TOOL_ROUNDS = 2
    # The model often asks for a batch of searches at once, and Brave is paced at
    # ~1 request/second, so the search phase of one reply is capped by wall clock
    # rather than by call count: whatever fits in the budget runs, the rest is
    # reported back to the model as skipped.
    _SEARCH_TIME_BUDGET = 10.0

    async def _execute_tool_call(self, tool_call: dict, deadline: float = None) -> str:
        """Run one tool call from the model and return its result as text.

        `deadline` is a `time.monotonic()` stamp: past it, searches are skipped
        instead of making the reply wait even longer.
        """
        fn = tool_call.get("function") or {}
        name = fn.get("name") or ""
        raw_args = fn.get("arguments") or "{}"
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
        except Exception:
            args = {"query": str(raw_args)}
        if name != "web_search":
            logger.warning(f"MoltBot: model called unknown tool {name!r}")
            return f"Ошибка: инструмента {name!r} нет. Доступен только web_search."
        query = str(args.get("query") or "").strip()
        if not query:
            return "Ошибка: пустой запрос. Передай query."
        if deadline is not None and time.monotonic() >= deadline:
            logger.info(f"MoltBot: search budget spent, skipping '{query}'")
            return (
                f"Поиск по запросу '{query}' пропущен: лимит времени на поиск исчерпан. "
                "Отвечай тем, что уже нашёл, и не выдумывай."
            )
        reason = str(args.get("reason") or "unspecified")
        logger.info(f"MoltBot: web_search tool → '{query}' (reason: {reason})")
        started = time.monotonic()
        results = await self._brave_search(query)
        trace = llm_trace.current()
        if trace:
            trace.record_tool("web_search", reason, bool(results),
                              int((time.monotonic() - started) * 1000))
        if not results:
            return f"По запросу '{query}' ничего не нашлось. Скажи честно, что не нашёл, не выдумывай."
        return (
            f"Результаты поиска по запросу '{query}':\n{results}\n"
            "Используй эту информацию чтобы ответить. Отвечай коротко, своими словами, "
            "не пересказывай список результатов."
        )

    async def _complete_with_tools(self, post, payload: dict, timeout: float) -> str:
        """Chat-completion loop with the web_search tool.

        `post` is a provider poster (`_openrouter_post` / `_together_post`) returning the
        OpenAI-style {"choices": [{"message": {...}}]} shape. If the model answers with
        tool_calls we run them, append the results as `tool` messages and call again.
        After `_MAX_TOOL_ROUNDS` rounds the tool is disabled (tool_choice=none) so the
        model has to answer in plain text. Returns the final text content.
        """
        messages = list(payload["messages"])
        base = {k: v for k, v in payload.items() if k != "messages"}
        tools_supported = True
        # One budget for the whole reply, shared by every round
        search_deadline = time.monotonic() + self._SEARCH_TIME_BUDGET
        for round_no in range(self._MAX_TOOL_ROUNDS + 1):
            req = {**base, "messages": messages}
            if tools_supported:
                req["tools"] = [self._WEB_SEARCH_TOOL]
                req["tool_choice"] = "none" if round_no == self._MAX_TOOL_ROUNDS else "auto"
            try:
                data = await post(req, timeout)
            except _AIConnectionError as e:
                # Provider/model without function calling → retry once without tools
                if tools_supported and round_no == 0 and "400" in str(e) and "tool" in str(e).lower():
                    logger.warning(f"MoltBot: provider rejected tools, retrying without: {e}")
                    tools_supported = False
                    data = await post({**base, "messages": messages}, timeout)
                else:
                    raise
            trace = llm_trace.current()
            if trace and trace.attempts:
                llm_trace.apply_response(trace.attempts[-1], data)
            msg = data["choices"][0]["message"]
            content = msg.get("content") or ""
            tool_calls = msg.get("tool_calls") or []
            if not tool_calls or round_no == self._MAX_TOOL_ROUNDS:
                return content
            messages.append({"role": "assistant", "content": content or None, "tool_calls": tool_calls})
            for tc in tool_calls:
                result = await self._execute_tool_call(tc, deadline=search_deadline)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id") or f"call_{round_no}",
                    "name": (tc.get("function") or {}).get("name") or "web_search",
                    "content": result,
                })
        return ""

    # Legacy text marker. Kept only as a safety net for prompt versions that still
    # say "ответь словом SEARCH:" — the model should be using the web_search tool.
    # Uppercase-only on purpose: the marker is always uppercase, ordinary text isn't.
    _SEARCH_MARKER_RE = re.compile(r"SEARCH\s*:\s*([^\n\]]+)")
    _SEARCH_LINE_RE = re.compile(r"(?m)^[ \t]*(?:\[?[^\n:]{0,20}:[ \t]*)?\[?[ \t]*SEARCH\s*:[^\n]*$")

    @classmethod
    def _extract_search_query(cls, text: str) -> str | None:
        """Extract search query from a legacy 'SEARCH: ...' marker anywhere in the reply."""
        if not text:
            return None
        m = cls._SEARCH_MARKER_RE.search(text)
        if not m:
            return None
        query = m.group(1).strip()
        if query:
            logger.info(f"MoltBot: legacy SEARCH marker found → '{query}'")
        return query or None

    @classmethod
    def _strip_search_markers(cls, text: str) -> str:
        """Remove any leftover 'SEARCH: ...' markers so they never reach the chat."""
        if not text:
            return text
        cleaned = cls._SEARCH_LINE_RE.sub("", text)          # whole marker lines
        cleaned = cls._SEARCH_MARKER_RE.sub("", cleaned)     # inline leftovers
        return re.sub(r"\n\s*\n\s*\n", "\n\n", cleaned).strip()

    async def _maybe_search(self, reply: str, sender_name: str, user_text: str,
                            chat_context: str, history: list[str] | None,
                            chat_id: int | None = None) -> str | None:
        """Legacy net: if reply contains a SEARCH: marker, search and re-generate. Returns new reply or None."""
        query = self._extract_search_query(reply)
        if not query:
            return None
        logger.info(f"MoltBot: SEARCH requested → '{query}'")
        results = await self._brave_search(query)
        if results:
            search_context = (
                f"[Результаты поиска по запросу '{query}':\n"
                f"{results}\n"
                f"Используй эту информацию чтобы ответить. Отвечай коротко, своими словами.]"
            )
            augmented_text = f"{user_text}\n\n{search_context}"
            try:
                return await self._call_persona(
                    sender_name, augmented_text, chat_context, history, chat_id
                )
            except Exception as e:
                logger.warning(f"MoltBot: re-call after search failed: {e}")
        # Search failed or no results — try Gemini
        try:
            return await self._call_gemini_text(
                sender_name, user_text, chat_context, history, chat_id
            )
        except Exception as ge:
            logger.warning(f"MoltBot: Gemini fallback failed ({ge})")
        return None

    async def _ask_moltbot_routed(self, sender_name: str, user_text: str,
                                  chat_context: str,
                                  history: list[str] | None = None,
                                  chat_id: int | None = None) -> str:
        """Traced persona reply: one llm_traces row per call, whatever route answers."""
        if llm_trace.current() is not None:  # nested call (e.g. re-ask after search)
            return await self._ask_moltbot_routed_untraced(
                sender_name, user_text, chat_context, history, chat_id
            )
        trace, token = llm_trace.begin("persona", chat_id)
        reply = None
        try:
            reply = await self._ask_moltbot_routed_untraced(
                sender_name, user_text, chat_context, history, chat_id
            )
            trace.finish("ok" if reply and reply.strip() else "empty", reply)
            return reply
        except _AIRefusalError:
            trace.finish("refusal")
            raise
        except Exception as e:
            trace.finish(f"error:{type(e).__name__}")
            raise
        finally:
            llm_trace.end(token)
            llm_trace.persist_in_background(trace, getattr(self, "db", None))

    async def _ask_moltbot_routed_untraced(self, sender_name: str, user_text: str,
                                           chat_context: str,
                                           history: list[str] | None = None,
                                           chat_id: int | None = None) -> str:
        """Route: OpenRouter/Grok → Together.ai fallback. Web search is a native tool call
        (web_search → Brave); legacy SEARCH:/INTERNET text markers are intercepted as a fallback."""
        if not Settings.OPENROUTER_API_KEY and not Settings.TOGETHER_API_KEY:
            raise _AIConnectionError("Neither OPENROUTER_API_KEY nor TOGETHER_API_KEY set")
        logger.info(f"MoltBot: persona call for: {user_text[:60]}")
        reply = await self._call_persona(sender_name, user_text, chat_context, history, chat_id)
        if not reply or not reply.strip():
            return reply
        logger.info(f"MoltBot: routed got reply ({len(reply)} chars): {reply[:100]!r}")
        # Legacy text markers (SEARCH: / INTERNET) — search is a tool call now,
        # but old prompt versions may still emit them. Never let them reach the chat.
        if self._extract_search_query(reply):
            searched = await self._maybe_search(
                reply, sender_name, user_text, chat_context, history, chat_id
            )
            if searched and not self._extract_search_query(searched):
                logger.info(f"MoltBot: legacy SEARCH resolved, returning: {searched[:100]!r}")
                return searched
            stripped = self._strip_search_markers(searched or reply)
            if stripped:
                logger.warning("MoltBot: legacy SEARCH marker stripped from reply")
                return stripped
            raise _AIConnectionError("reply was only a SEARCH marker and search failed")
        if reply.strip().upper() == "INTERNET":
            logger.info(f"MoltBot: INTERNET → gemini for: {user_text[:60]}")
            return await self._call_gemini_text(
                sender_name, user_text, chat_context, history, chat_id
            )
        return reply

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
        recent_count = await self._count_recent_messages(chat_id, 10)
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
                history = await self._get_recent_group_messages(chat_id, limit=6)
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
                reply = await self._call_persona_simple(prompt, chat_id)
                logger.info(f"MoltBot: cold start probabilistic for chat {chat_id}")
            else:
                # Warm session: Qwen filter → Claude response
                history = await self._get_recent_group_messages(chat_id, limit=50)
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
                reply = await self._call_persona_simple(prompt, chat_id)
                logger.info(f"MoltBot: warm session probabilistic for chat {chat_id}")

            reply = reply.strip()
            if not reply:
                return False

            # Legacy SEARCH: marker in probabilistic replies (search is a tool call now)
            search_q = self._extract_search_query(reply)
            if search_q:
                logger.info(f"MoltBot: probabilistic legacy SEARCH → '{search_q}'")
                results = await self._brave_search(search_q)
                if results:
                    augmented = f"{prompt}\n\n[Результаты поиска '{search_q}':\n{results}\nОтвечай коротко.]"
                    reply = await self._call_persona_simple(augmented, chat_id)
                reply = self._strip_search_markers(reply)
                if not reply:
                    return False

            sent = await self._send_long_reply(message, reply)
            await self._store_bot_reply(reply, chat_id, sent.message_id)
            self._last_probabilistic_sent[chat_id] = now
            if is_cold_start:
                self._prob_session_start[chat_id] = now
            logger.info(f"MoltBot: probabilistic reply sent in chat {chat_id}")
            return True
        except Exception as e:
            logger.error(f"MoltBot: probabilistic reply error: {e}")
            return False

    # Telegram's standard reaction set (setMessageReaction rejects anything else).
    _REACTION_EMOJIS = [
        '👍', '👎', '❤', '🔥', '🥰', '👏', '😁', '🤔', '🤯', '😱', '🤬', '😢', '🎉',
        '🤩', '🤮', '💩', '🙏', '👌', '🕊', '🤡', '🥱', '🥴', '😍', '🐳', '🌚', '💯',
        '🤣', '⚡', '🍌', '🏆', '💔', '🤨', '😐', '🍾', '💋', '🖕', '😈', '😴', '😭',
        '🤓', '👻', '👀', '🎃', '🙈', '😇', '😨', '🤝', '✍', '🤗', '🫡', '💅', '🤪',
        '🗿', '🆒', '💘', '🙉', '🦄', '😘', '💊', '🙊', '😎', '👾', '🤷', '😡',
    ]
    _REACTION_MIN_CHARS = 8
    _REACTION_COOLDOWN_SECS = 600      # one reaction per chat per 10 min at most
    _REACTION_DAILY_CAP = 12           # per chat per Kyiv day
    _REACTION_RECENT_EMOJI = 5         # don't repeat the last N emoji

    _REACTION_PROMPT = (
        "Ты Джарвис — участник группового чата трёх друзей (грубый дружеский тон — норма). "
        "Тебе не писали напрямую. Реши, поставить ли РЕАКЦИЮ-эмодзи на последнее сообщение "
        "вместо того, чтобы молчать.\n\n"
        "=== ПОСЛЕДНИЕ СООБЩЕНИЯ ===\n{history}\n\n"
        "=== СООБЩЕНИЕ ===\n{sender}: {text}\n\n"
        "Реагируй, только если сообщение правда зацепило: очень смешно, эпичный фейл или "
        "победа, дерзко, трогательно, важная новость человека. Обычный трёп, вопросы "
        "другим людям, логистика, короткие ответы — ignore. По умолчанию ignore.\n"
        "Эмодзи — строго один из: {emojis}\n"
        "Не бери эти (недавно ставил): {recent}\n"
        'Верни ТОЛЬКО JSON: {{"action": "ignore" | "react", "emoji": "…", "why": "3-6 слов"}}'
    )

    def _reaction_gate(self, chat_id: int, text: str, now: datetime) -> str | None:
        """Cheap checks before any model call. Returns the reason to skip, or None."""
        if os.getenv("JARVIS_REACTIONS", "true").lower() in ("0", "false", "off", "no"):
            return "disabled"
        if len(text.strip()) < self._REACTION_MIN_CHARS:
            return "short"
        last = self._last_reaction_time.get(chat_id)
        if last and (now - last).total_seconds() < self._REACTION_COOLDOWN_SECS:
            return "cooldown"
        day = now.astimezone(ZoneInfo("Europe/Kyiv")).date()
        counts = getattr(self, "_reaction_day_counts", {})
        if chat_id in counts and counts[chat_id][0] == day and counts[chat_id][1] >= self._REACTION_DAILY_CAP:
            return "daily_cap"
        return None

    def _parse_reaction_decision(self, raw: str, recent: list[str]) -> str | None:
        """Model JSON → emoji to set, or None. Anything unexpected means no reaction."""
        try:
            match = re.search(r"\{.*\}", re.sub(r"<think>.*?(?:</think>|$)", "", raw or "", flags=re.DOTALL),
                              flags=re.DOTALL)
            data = json.loads(match.group(0)) if match else {}
        except Exception:
            return None
        if data.get("action") != "react":
            return None
        emoji = str(data.get("emoji") or "").strip().replace("️", "")
        if emoji not in self._REACTION_EMOJIS or emoji in recent:
            return None
        return emoji

    async def _maybe_react(self, message) -> None:
        """Decide ignore/react for a group message not addressed to Jarvis; set the reaction.

        Replaces a filler text reply: when Jarvis has nothing to add, an emoji keeps him
        present without cluttering the chat. Decisions are traced (kind="reaction").
        """
        chat_id = message.chat.id
        text = message.text or ""
        now = datetime.now(timezone.utc)
        if not hasattr(self, "_last_used_emoji"):
            self._last_used_emoji: dict[int, list[str]] = {}
        if not hasattr(self, "_reaction_day_counts"):
            self._reaction_day_counts: dict[int, tuple] = {}
        skip = self._reaction_gate(chat_id, text, now)
        if skip or not Settings.OPENROUTER_API_KEY:
            return

        recent = self._last_used_emoji.get(chat_id, [])
        history = await self._get_recent_group_messages(chat_id, limit=6, exclude_message_id=message.message_id)
        prompt = self._REACTION_PROMPT.format(
            history="\n".join(history[-5:]) or "(пусто)",
            sender=self._resolve_sender_name(message.from_user), text=text[:600],
            emojis=" ".join(self._REACTION_EMOJIS), recent=" ".join(recent) or "—",
        )
        trace, token = llm_trace.begin("reaction", chat_id)
        emoji = None
        try:
            data = await self._traced_attempt(REACTION_MODEL, REACTION_MODEL, lambda: self._openrouter_post(
                # GLM Flash can't disable reasoning; "minimal" keeps it ~1s and the
                # budget has to cover the hidden reasoning tokens too.
                {"model": REACTION_MODEL, "max_tokens": 1500, "temperature": 0.3,
                 "reasoning": {"effort": "minimal"},
                 "messages": [{"role": "user", "content": prompt}], **self._provider_ids(chat_id)},
                timeout=20,
            ))
            llm_trace.apply_response(trace.attempts[-1] if trace.attempts else None, data)
            raw = data["choices"][0]["message"].get("content") or ""
            emoji = self._parse_reaction_decision(raw, recent)
            if emoji:
                await self.bot.set_message_reaction(
                    chat_id=chat_id, message_id=message.message_id,
                    reaction=[ReactionTypeEmoji(emoji=emoji)],
                )
                self._last_reaction_time[chat_id] = now
                self._last_used_emoji[chat_id] = (recent + [emoji])[-self._REACTION_RECENT_EMOJI:]
                day = now.astimezone(ZoneInfo("Europe/Kyiv")).date()
                prev_day, count = self._reaction_day_counts.get(chat_id, (day, 0))
                self._reaction_day_counts[chat_id] = (day, (count if prev_day == day else 0) + 1)
                logger.info(f"MoltBot: reacted {emoji} to msg {message.message_id} in {chat_id}")
            trace.finish(f"react:{emoji}" if emoji else "ignore", raw)
        except Exception as e:
            trace.finish(f"error:{type(e).__name__}")
            logger.warning(f"MoltBot: reaction error: {e}")
        finally:
            llm_trace.end(token)
            llm_trace.persist_in_background(trace, getattr(self, "db", None))

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

    async def _danetka_llm(self, prompt: str) -> str:
        """Ollama, а если винда спит — raw Together (без persona)."""
        try:
            raw = await asyncio.to_thread(self._call_ollama_direct, prompt)
            if raw.strip():
                return raw
        except Exception as e:
            logger.warning(f"MoltBot: danetka ollama failed, falling back to Together: {e}")
        data = await self._together_post(
            {
                "model": Settings.TOGETHER_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 600,
                "temperature": 0.8,
            },
            timeout=120,
        )
        return data["choices"][0]["message"]["content"]

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
            raw = await self._danetka_llm(prompt)
            clean = re.sub(r'<think>.*?(?:</think>|$)', '', raw, flags=re.DOTALL).strip()
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
            result = (await self._danetka_llm(prompt)).strip()
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

    # ── Ивенты / напоминания ─────────────────────────────────────────────────

    async def _ensure_reminders_table(self):
        try:
            await self.db.execute_query(
                "CREATE TABLE IF NOT EXISTS reminders ("
                "id SERIAL PRIMARY KEY, "
                "chat_id BIGINT NOT NULL, "
                "text TEXT NOT NULL, "
                "remind_at TIMESTAMP NOT NULL, "
                "sent BOOLEAN DEFAULT FALSE, "
                "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
                ()
            )
        except Exception as e:
            logger.error(f"MoltBot: failed to create reminders table: {e}")

    async def _parse_reminder(self, user_text: str) -> dict | None:
        """LLM-парсинг свободного текста в {text, remind_at}. Без persona — только JSON."""
        now = datetime.now(CPH_TZ)
        weekday = ['понедельник', 'вторник', 'среда', 'четверг',
                   'пятница', 'суббота', 'воскресенье'][now.weekday()]
        prompt = (
            f"Сейчас {now.strftime('%Y-%m-%d %H:%M')}, {weekday}.\n"
            f"Пользователь просит поставить напоминание: «{user_text}»\n\n"
            "Верни ТОЛЬКО JSON без лишнего текста:\n"
            '{"text": "текст напоминания", "remind_at": "YYYY-MM-DD HH:MM"}\n\n'
            "Правила:\n"
            "- remind_at — когда прислать напоминание, обязательно в будущем\n"
            "- Если время суток не указано, ставь 12:00\n"
            '- Если дату определить невозможно, верни {"error": "причина"}'
        )
        try:
            data = await self._together_post(
                {
                    "model": Settings.TOGETHER_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 200,
                    "temperature": 0.1,
                },
                timeout=60,
            )
            raw = data["choices"][0]["message"]["content"]
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            return json.loads(match.group()) if match else None
        except Exception as e:
            logger.error(f"MoltBot: reminder parse failed: {e}")
            return None

    async def _reminder_loop(self):
        await self._ensure_reminders_table()
        while True:
            try:
                now = datetime.now(CPH_TZ).replace(tzinfo=None)
                rows = await self.db.execute_query(
                    "SELECT id, chat_id, text FROM reminders WHERE NOT sent AND remind_at <= %s",
                    (now,)
                )
                for rid, chat_id, text in rows or []:
                    # ponytail: sent=TRUE до отправки — потерять одно напоминание лучше, чем спамить каждую минуту при ошибке
                    await self.db.execute_query(
                        "UPDATE reminders SET sent = TRUE WHERE id = %s", (rid,)
                    )
                    await self.bot.send_message(chat_id, f"🔔 Напоминание: {text}")
            except Exception as e:
                logger.error(f"MoltBot: reminder loop error: {e}")
            await asyncio.sleep(60)

    # ── Недельная аналитика ───────────────────────────────────────────────────

    def start_weekly_analytics_scheduler(self, chat_id: int):
        """Schedule weekly analytics independently of the proactive-message loop
        so disabling proactive messages can never silently take stats down with it."""
        tz = ZoneInfo("Europe/Kyiv")
        self._analytics_scheduler = AsyncIOScheduler(timezone=tz)
        self._analytics_scheduler.add_job(
            self._send_weekly_analytics,
            CronTrigger(day_of_week='sun', hour=21, minute=0, timezone=tz),
            args=[chat_id],
        )
        self._analytics_scheduler.start()
        logger.info(f"MoltBot: weekly analytics scheduler started for chat {chat_id} (Sun 21:00 Europe/Kyiv)")

    async def _send_weekly_analytics(self, chat_id: int):
        try:
            total_rows = await self.db.execute_query(
                "SELECT COUNT(*) FROM messages WHERE chat_id = %s "
                "AND timestamp > NOW() - INTERVAL '7 days' AND user_id != 0",
                (chat_id,)
            )
            total = total_rows[0][0] if total_rows else 0
            if total == 0:
                await self.bot.send_message(chat_id, "📊 За эту неделю сообщений не было.")
                return

            per_person = await self.db.execute_query(
                "SELECT name, COUNT(*) FROM messages "
                "WHERE chat_id = %s AND timestamp > NOW() - INTERVAL '7 days' AND user_id != 0 "
                "GROUP BY name ORDER BY COUNT(*) DESC LIMIT 10",
                (chat_id,)
            )
            top_hours = await self.db.execute_query(
                "SELECT EXTRACT(HOUR FROM timestamp)::int, COUNT(*) FROM messages "
                "WHERE chat_id = %s AND timestamp > NOW() - INTERVAL '7 days' AND user_id != 0 "
                "GROUP BY 1 ORDER BY 2 DESC LIMIT 3",
                (chat_id,)
            )

            # Qwen topic summary
            recent = await self._get_recent_group_messages(chat_id, limit=300)
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
                    if await self._count_recent_messages(chat_id, 8 * 60) >= 5:
                        await self._send_proactive_message(chat_id)
                    else:
                        logger.info(f"MoltBot: skipping {t} proactive — chat inactive")
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

        @router.message(StateFilter(None), ~F.text.startswith('/'), F.func(lambda m: bool(
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
                history = await self._build_thread_first_history(
                    message.chat.id,
                    message.reply_to_message.message_id if message.reply_to_message else None,
                    message.message_id,
                )

            try:
                async with ChatActionSender.typing(bot=self.bot, chat_id=message.chat.id):
                    reply = await self._ask_moltbot_routed(
                        sender_name, user_text, chat_context, history, message.chat.id
                    )
                if reply and reply.strip():
                    sent = await self._send_long_reply(message, reply)
                    await self._store_bot_reply(
                        reply, message.chat.id, sent.message_id, reply_to=message.message_id
                    )
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

        @router.message(Command(commands=['ивент', 'напомни', 'event', 'remind']))
        async def handle_event_create(message: Message):
            parts = (message.text or '').split(maxsplit=1)
            if len(parts) < 2:
                await message.reply(
                    "Напиши что и когда:\n/ивент позвать Юру играть в факторио завтра в 19:00"
                )
                return
            waiting = await message.reply("⏳ Ставлю напоминание...")
            parsed = await self._parse_reminder(parts[1])
            if not parsed or 'error' in parsed or not parsed.get('remind_at'):
                reason = (parsed or {}).get('error', '')
                await waiting.edit_text(f"🤷 Не понял, когда напомнить. {reason}".strip())
                return
            try:
                remind_at = datetime.strptime(parsed['remind_at'], '%Y-%m-%d %H:%M')
            except ValueError:
                await waiting.edit_text("🤷 Не смог разобрать дату, попробуй сформулировать иначе.")
                return
            text = parsed.get('text') or parts[1]
            await self.db.execute_query(
                "INSERT INTO reminders (chat_id, text, remind_at) VALUES (%s, %s, %s)",
                (message.chat.id, text, remind_at)
            )
            await waiting.edit_text(
                f"✅ Напомню {remind_at.strftime('%d.%m.%Y в %H:%M')}: {text}"
            )

        @router.message(Command(commands=['ивенты', 'events']))
        async def handle_event_list(message: Message):
            rows = await self.db.execute_query(
                "SELECT id, remind_at, text FROM reminders "
                "WHERE NOT sent AND chat_id = %s ORDER BY remind_at LIMIT 20",
                (message.chat.id,)
            )
            if not rows:
                await message.reply("📅 Нет запланированных ивентов.")
                return
            lines = [f"#{rid} • {dt.strftime('%d.%m %H:%M')} — {txt}" for rid, dt, txt in rows]
            await message.reply("📅 Запланировано:\n" + "\n".join(lines))

        @router.message(Command(commands=['ивент_удали', 'event_del']))
        async def handle_event_delete(message: Message):
            parts = (message.text or '').split(maxsplit=1)
            if len(parts) < 2 or not parts[1].lstrip('#').isdigit():
                await message.reply("Укажи номер из /ивенты: /ивент_удали 3")
                return
            await self.db.execute_query(
                "DELETE FROM reminders WHERE id = %s AND chat_id = %s",
                (int(parts[1].lstrip('#')), message.chat.id)
            )
            await message.reply("🗑 Удалил.")

        @router.message(Command(commands=['аналитика', 'analitika']))
        async def handle_analytics_command(message: Message):
            if message.from_user.id not in Settings.ADMIN_IDS:
                await message.reply("У вас нет доступа.")
                return
            await message.reply("📊 Собираю статистику...")
            asyncio.create_task(self._send_weekly_analytics(message.chat.id))

        @router.message(Command(commands=['мут_сброс', 'mut_reset', 'context_reset']))
        async def handle_reset(message: Message):
            """Reset short-term history of THIS chat only. Long-term memory is untouched."""
            chat_id = message.chat.id
            self._history_reset_time[chat_id] = datetime.now(timezone.utc)
            self._save_state()
            logger.info(f"MoltBot: history reset for chat {chat_id} by {message.from_user.id}")
            await message.reply(
                "⚙️ Краткосрочный контекст этого чата сброшен: сообщения до этого момента "
                "я больше не вижу. Долгая память и закреп не тронуты — это /memory_clear."
            )

        @router.message(Command(commands=['reasoning', 'ризонинг', 'думай']))
        async def handle_reasoning(message: Message):
            """Everyone in the chat may switch how hard Grok thinks: low for banter, high for a serious talk."""
            parts = (message.text or "").split(maxsplit=1)
            arg = parts[1] if len(parts) > 1 else ""
            current = self._current_reasoning_effort()
            if not arg.strip():
                left = self._reasoning_reset_in()
                tail = ""
                if left is not None:
                    mins = int(left.total_seconds() // 60)
                    tail = f"\nСброс на {REASONING_DEFAULT} через {mins // 60}ч {mins % 60:02d}м тишины в чате."
                await message.reply(
                    f"🧠 Ризонинг сейчас: {current}{tail}\n"
                    "Поменять: /reasoning low | medium | high"
                )
                return
            level = _parse_reasoning_level(arg)
            if level is None:
                await message.reply(f"Не понял «{arg.strip()}». Варианты: low, medium, high.")
                return
            self._set_reasoning_effort(level)
            hours = int(REASONING_RESET_AFTER.total_seconds() // 3600)
            if level == REASONING_DEFAULT:
                await message.reply(f"🧠 Ризонинг: {level}. Обычный режим, думаю быстро.")
            else:
                await message.reply(
                    f"🧠 Ризонинг: {level}. Думаю глубже, отвечаю медленнее. "
                    f"Через {hours}ч тишины в чате сам вернусь на {REASONING_DEFAULT}."
                )

        @router.message(Command(commands=['memory', 'память']))
        async def handle_memory_view(message: Message):
            if message.from_user.id not in Settings.ADMIN_IDS:
                await message.reply("У вас нет доступа.")
                return
            mem = _load_chat_summary(message.chat.id)
            lines = _lore_lines(message.chat.id)
            candidates = _lore_candidate_lines(message.chat.id)
            pinned = ("\n\n📌 Закреплённые внутряки:\n" +
                      "\n".join(f"{i+1}. {ln}" for i, ln in enumerate(lines))) if lines else "\n\n📌 Закреплённых внутряков нет."
            queued = ("\n\n🕓 Кандидаты в закреп (бот их не использует, пока не закрепишь: /memory_pin к<номер>):\n" +
                      "\n".join(f"к{i+1}. {ln}" for i, ln in enumerate(candidates))) if candidates else ""
            body = (f"🧠 Память чата ({len(mem)} симв.):\n\n{mem}" if mem else "🧠 Память пуста.") + pinned + queued
            await self._send_long_reply(message, body)

        @router.message(Command(commands=['memory_refresh']))
        async def handle_memory_refresh(message: Message):
            if message.from_user.id not in Settings.ADMIN_IDS:
                await message.reply("У вас нет доступа.")
                return
            await message.reply("🧠 Пересобираю память (займёт несколько секунд)...")
            chat_id = message.chat.id
            self._last_summary_update[chat_id] = datetime.now(timezone.utc)

            async def refresh_and_report():
                ok, detail = await self._update_summary(chat_id)
                prefix = "✅ Память пересобрана" if ok else "⚠️ Память не обновлена"
                try:
                    await message.reply(f"{prefix}: {detail}.")
                except Exception as e:
                    logger.warning(f"MoltBot: could not report memory refresh: {e}")

            asyncio.create_task(refresh_and_report())

        @router.message(Command(commands=['memory_clear']))
        async def handle_memory_wipe(message: Message):
            if message.from_user.id not in Settings.ADMIN_IDS:
                await message.reply("У вас нет доступа.")
                return
            parts = (message.text or "").split(maxsplit=1)
            scope = self._MEMORY_CLEAR_SCOPES.get(parts[1].strip().lower() if len(parts) > 1 else "")
            if scope is None:
                await message.reply(
                    "Что стереть?\n"
                    "/memory_clear rolling — текущую память (что происходит + внутряки)\n"
                    "/memory_clear lore — закреплённые внутряки и кандидатов\n"
                    "/memory_clear all — всё сразу\n"
                    "Краткосрочный контекст сбрасывается отдельно: /context_reset"
                )
                return
            chat_id = message.chat.id
            try:
                removed = []
                if scope in ("rolling", "all"):
                    _remove_memory_file(CHAT_SUMMARY_PATH, chat_id)
                    # Rebuilds only look at messages after this point, otherwise the
                    # last 48h would quietly restore what was just wiped.
                    self._memory_cursor[chat_id] = datetime.now(timezone.utc)
                    self._save_state()
                    removed.append("текущая память (пересоберётся только из новых сообщений)")
                if scope in ("lore", "all"):
                    _remove_memory_file(CHAT_LORE_PATH, chat_id)
                    _remove_memory_file(CHAT_LORE_CANDIDATES_PATH, chat_id)
                    removed.append("закреплённые внутряки и кандидаты")
                logger.info(f"MoltBot: memory_clear {scope} for chat {chat_id} by {message.from_user.id}")
                await message.reply("🧠 Стёрто: " + "; ".join(removed) + ".")
            except Exception as e:
                await message.reply(f"Ошибка: {e}")

        @router.message(Command(commands=['memory_pin', 'память_закрепи', 'закрепи']))
        async def handle_memory_pin(message: Message):
            if message.from_user.id not in Settings.ADMIN_IDS:
                await message.reply("У вас нет доступа.")
                return
            text = (message.text or "").split(maxsplit=1)
            if len(text) < 2 or not text[1].strip():
                await message.reply("Что закрепить? `/память_закрепи <внутряк одной строкой>`")
                return
            chat_id = message.chat.id
            arg = text[1].strip()
            candidate_ref = re.fullmatch(r'[кk](\d+)', arg.lower())
            if candidate_ref:
                candidates = _lore_candidate_lines(chat_id)
                idx = int(candidate_ref.group(1)) - 1
                if idx < 0 or idx >= len(candidates):
                    await message.reply(f"Нет такого кандидата (всего {len(candidates)}). Список: /memory")
                    return
                entry = candidates.pop(idx)
                _save_lore_candidate_lines(candidates, chat_id)
            else:
                entry = arg.replace("\n", " ")
            lines = _lore_lines(chat_id)
            lines.append(entry)
            _save_lore_lines(lines, chat_id)
            await message.reply(f"📌 Закреплено ({len(lines)} всего): {entry}")

        @router.message(Command(commands=['memory_unpin', 'память_открепи', 'открепи']))
        async def handle_memory_unpin(message: Message):
            if message.from_user.id not in Settings.ADMIN_IDS:
                await message.reply("У вас нет доступа.")
                return
            lines = _lore_lines(message.chat.id)
            if not lines:
                await message.reply("Закреплённых внутряков нет.")
                return
            arg = (message.text or "").split(maxsplit=1)
            if len(arg) < 2 or not arg[1].strip().isdigit():
                listing = "\n".join(f"{i+1}. {ln}" for i, ln in enumerate(lines))
                await message.reply(f"Какой открепить? `/память_открепи <номер>`\n\n{listing}")
                return
            idx = int(arg[1].strip()) - 1
            if idx < 0 or idx >= len(lines):
                await message.reply(f"Нет такого номера (всего {len(lines)}).")
                return
            removed = lines.pop(idx)
            _save_lore_lines(lines, message.chat.id)
            await message.reply(f"🗑 Откреплено: {removed}")

        @router.message(StateFilter(None), ~F.text.startswith('/'), F.func(lambda m: (
            m.reply_to_message is not None
            and m.reply_to_message.from_user is not None
            and m.reply_to_message.from_user.is_bot
            and m.pinned_message is None
            and (m.from_user is None or not m.from_user.is_bot)
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

            # New GIF in reply to bot — analyze via Gemini (Telegram GIFs can't carry a caption+mention, so this is the main entry point)
            elif message.animation:
                try:
                    file = await self.bot.get_file(message.animation.file_id)
                    bio = await self.bot.download_file(file.file_path)
                    animation_bytes = bio.read()
                    animation_analysis = await asyncio.to_thread(
                        self._analyze_animation_with_gemini, animation_bytes, user_text
                    )
                    user_text = f"[Гифка: {animation_analysis}]\n{user_text}" if user_text else f"[Гифка: {animation_analysis}]"
                except Exception as e:
                    logger.warning(f"MoltBot: reply animation analysis failed: {e}")

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
                history = await self._build_thread_first_history(
                    message.chat.id,
                    message.reply_to_message.message_id if message.reply_to_message else None,
                    message.message_id,
                )

            try:
                async with ChatActionSender.typing(bot=self.bot, chat_id=message.chat.id):
                    reply = await self._ask_moltbot_routed(
                        sender_name, user_text, chat_context, history, message.chat.id
                    )
                if reply and reply.strip():
                    sent = await self._send_long_reply(message, reply)
                    await self._store_bot_reply(
                        reply, message.chat.id, sent.message_id, reply_to=message.message_id
                    )
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
            self._maybe_update_summary(message.chat.id)
            # Text interjections stay off; a fitting emoji is the low-noise alternative.
            asyncio.create_task(self._maybe_react(message))

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
                history = await self._build_thread_first_history(
                    message.chat.id,
                    message.reply_to_message.message_id if message.reply_to_message else None,
                    message.message_id,
                )

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
                async with ChatActionSender.typing(bot=self.bot, chat_id=message.chat.id):
                    reply = await self._ask_moltbot_routed(
                        sender_name, combined_text, chat_context, history, message.chat.id
                    )
                if reply and reply.strip():
                    sent = await self._send_long_reply(message, reply)
                    await self._store_bot_reply(
                        reply, message.chat.id, sent.message_id, reply_to=message.message_id
                    )
                    self._photo_context[sent.message_id] = message.photo[-1].file_id
                else:
                    await message.reply("🤐 AI отказался отвечать на это сообщение")
            except _AIConnectionError:
                await message.reply("⚠️ Не могу подключиться к AI, попробуй позже")
            except Exception as e:
                logger.error(f"MoltBot API error (photo): {e}")
                await message.reply("Не могу связаться с AI. Попробуй позже.")

        @router.message(StateFilter(None), F.animation, F.func(lambda m: (
            m.caption_entities is not None
            and any(e.type == 'mention' for e in m.caption_entities)
        )))
        async def handle_animation_mention(message: Message):
            if not await self._is_bot_mentioned_in_caption(message):
                return
            sender_name = self._resolve_sender_name(message.from_user)
            user_question = await self._extract_caption_text(message)
            reply_ctx = await self._build_reply_context(message)
            chat_context = self._get_chat_context(message)

            history = None
            if message.chat.type in ('group', 'supergroup'):
                history = await self._build_thread_first_history(
                    message.chat.id,
                    message.reply_to_message.message_id if message.reply_to_message else None,
                    message.message_id,
                )

            try:
                file = await self.bot.get_file(message.animation.file_id)
                bio = await self.bot.download_file(file.file_path)
                animation_bytes = bio.read()
            except Exception as e:
                logger.error(f"MoltBot: failed to download animation: {e}")
                await message.reply("Не могу загрузить гифку. Попробуй ещё раз.")
                return

            animation_analysis = await asyncio.to_thread(
                self._analyze_animation_with_gemini, animation_bytes, user_question
            )

            parts = []
            if reply_ctx:
                parts.append(reply_ctx)
            parts.append(f"[Гифка: {animation_analysis}]")
            if user_question:
                parts.append(user_question)
            combined_text = "\n".join(parts)

            try:
                async with ChatActionSender.typing(bot=self.bot, chat_id=message.chat.id):
                    reply = await self._ask_moltbot_routed(
                        sender_name, combined_text, chat_context, history, message.chat.id
                    )
                if reply and reply.strip():
                    sent = await self._send_long_reply(message, reply)
                    await self._store_bot_reply(
                        reply, message.chat.id, sent.message_id, reply_to=message.message_id
                    )
                else:
                    await message.reply("🤐 AI отказался отвечать на это сообщение")
            except _AIConnectionError:
                await message.reply("⚠️ Не могу подключиться к AI, попробуй позже")
            except Exception as e:
                logger.error(f"MoltBot API error (animation): {e}")
                await message.reply("Не могу связаться с AI. Попробуй позже.")
