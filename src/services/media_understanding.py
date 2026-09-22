"""One place that turns Telegram media into text Jarvis can reason about.

Voice notes and video notes are transcribed, stickers and GIFs described, all
through the Gemini model the bot already uses for photos. Results are cached by
Telegram's file_unique_id (same sticker/voice quoted again = no new call).
When analysis is impossible the fragment says so explicitly, so the persona
model knows the content is unknown instead of inventing it.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

MAX_VOICE_SECONDS = 300
MAX_VIDEO_NOTE_SECONDS = 60
MAX_FILE_BYTES = 20 * 1024 * 1024
UNCLEAR_MARK = "[неразборчиво]"

CREATE_TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS media_descriptions ("
    " file_unique_id TEXT PRIMARY KEY,"
    " kind TEXT NOT NULL,"
    " text TEXT NOT NULL,"
    " created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
)

TRANSCRIBE_PROMPT = (
    "Дословно транскрибируй речь из этой записи на языке оригинала (обычно русский/украинский, "
    "бывают английские слова). Без пояснений, без таймкодов, без исправления мата. "
    f"Неразборчивые места помечай {UNCLEAR_MARK}. Если речи нет — верни {UNCLEAR_MARK}."
)
VIDEO_NOTE_PROMPT = (
    "Это видеосообщение-кружок из Telegram. Верни две строки:\n"
    "Речь: дословная транскрипция (неразборчивое — " + UNCLEAR_MARK + ", нет речи — «нет»)\n"
    "Кадр: одной короткой фразой, что видно (кто/где/что делает)."
)
STICKER_PROMPT = (
    "Это стикер из Telegram. Одной короткой фразой: кто или что на нём и какую эмоцию/реакцию "
    "он выражает. Если есть текст — процитируй его."
)
PHOTO_PROMPT = ("Подробно опиши, что на картинке: кто/что, обстановка, настроение. Если есть текст — "
                "процитируй дословно. Если это мем или скриншот переписки — перескажи суть.")
GIF_PROMPT = "Это гифка (мем или реакция, без звука). Одной-двумя фразами: что происходит и какая реакция."


class MediaUnderstanding:
    def __init__(self, bot, db, model_getter: Callable[[], Any]):
        self.bot = bot
        self.db = db
        self._model_getter = model_getter
        self._memory: dict[str, str] = {}

    async def ensure_table(self) -> None:
        try:
            await self.db.execute_query(CREATE_TABLE_SQL)
        except Exception as e:
            logger.warning(f"media: table setup failed: {e}")

    # ── cache ────────────────────────────────────────────────────────────
    async def _cached(self, key: str) -> str | None:
        if key in self._memory:
            return self._memory[key]
        try:
            rows = await self.db.execute_query(
                "SELECT text FROM media_descriptions WHERE file_unique_id = %s", (key,))
            if rows:
                self._memory[key] = rows[0][0]
                return rows[0][0]
        except Exception:
            pass
        return None

    async def _store(self, key: str, kind: str, text: str) -> None:
        self._memory[key] = text
        try:
            await self.db.execute_query(
                "INSERT INTO media_descriptions (file_unique_id, kind, text) VALUES (%s, %s, %s) "
                "ON CONFLICT (file_unique_id) DO UPDATE SET text = EXCLUDED.text",
                (key, kind, text))
        except Exception as e:
            logger.warning(f"media: cache write failed: {e}")

    # ── model calls ──────────────────────────────────────────────────────
    async def _download(self, file_id: str) -> bytes:
        file = await self.bot.get_file(file_id)
        bio = await self.bot.download_file(file.file_path)
        return bio.read()

    async def _ask(self, data: bytes, mime: str, prompt: str) -> str:
        model = self._model_getter()
        if model is None:
            raise RuntimeError("Gemini не настроен")
        response = await asyncio.to_thread(model.generate_content, [{"mime_type": mime, "data": data}, prompt])
        return (response.text or "").strip()

    async def _analyze(self, key: str, kind: str, file_id: str, mime: str, prompt: str) -> str:
        cached = await self._cached(key)
        if cached is not None:
            return cached
        data = await self._download(file_id)
        text = await self._ask(data, mime, prompt)
        if text:
            await self._store(key, kind, text)
        return text

    # ── public API ───────────────────────────────────────────────────────
    async def transcribe_voice(self, voice) -> tuple[str | None, str]:
        """(transcript or None, reason). Works for Message.voice and Message.audio."""
        duration = getattr(voice, "duration", 0) or 0
        if duration > MAX_VOICE_SECONDS or (getattr(voice, "file_size", 0) or 0) > MAX_FILE_BYTES:
            return None, f"слишком длинное ({duration} с)"
        try:
            mime = getattr(voice, "mime_type", None) or "audio/ogg"
            text = await self._analyze(voice.file_unique_id, "voice", voice.file_id, mime, TRANSCRIBE_PROMPT)
        except Exception as e:
            logger.warning(f"media: transcription failed: {e}")
            return None, "не удалось расшифровать"
        if not text or text.strip() == UNCLEAR_MARK:
            return None, "речь неразборчива"
        return text, ""

    async def fragment(self, message) -> str | None:
        """Prompt fragment for a media message (voice/audio/video note/sticker/GIF), or None
        if the message carries none of these. Never raises."""
        try:
            if getattr(message, "photo", None):
                photo = message.photo[-1]
                if (getattr(photo, "file_size", 0) or 0) > MAX_FILE_BYTES:
                    return "[Картинка: слишком большая, содержание неизвестно]"
                desc = await self._analyze(photo.file_unique_id, "photo", photo.file_id, "image/jpeg", PHOTO_PROMPT)
                return f"[Картинка: {desc}]" if desc else "[Картинка: содержание неизвестно]"
            if message.voice or message.audio:
                media = message.voice or message.audio
                text, reason = await self.transcribe_voice(media)
                label = "Голосовое" if message.voice else "Аудио"
                dur = getattr(media, "duration", 0) or 0
                if text is None:
                    return f"[{label} ({dur} с): содержание неизвестно — {reason}]"
                low = " (местами неразборчиво)" if UNCLEAR_MARK in text else ""
                return f"[{label} ({dur} с), расшифровка{low}: «{text}»]"
            if message.video_note:
                vn = message.video_note
                if (vn.duration or 0) > MAX_VIDEO_NOTE_SECONDS:
                    return f"[Кружок ({vn.duration} с): слишком длинный, содержание неизвестно]"
                text = await self._analyze(vn.file_unique_id, "video_note", vn.file_id, "video/mp4",
                                           VIDEO_NOTE_PROMPT)
                return f"[Кружок ({vn.duration} с): {text}]" if text else "[Кружок: содержание неизвестно]"
            if message.sticker:
                st = message.sticker
                emoji = st.emoji or ""
                set_name = f", набор «{st.set_name}»" if st.set_name else ""
                # Animated (.tgs) and video (.webm) stickers: the static thumbnail is enough.
                if st.is_animated or st.is_video:
                    thumb = st.thumbnail
                    if thumb is None:
                        return f"[Стикер {emoji}{set_name}: изображение недоступно]"
                    desc = await self._analyze(thumb.file_unique_id, "sticker", thumb.file_id,
                                               "image/webp", STICKER_PROMPT)
                else:
                    desc = await self._analyze(st.file_unique_id, "sticker", st.file_id, "image/webp",
                                               STICKER_PROMPT)
                return f"[Стикер {emoji}{set_name}: {desc}]" if desc else f"[Стикер {emoji}{set_name}]"
            if message.animation:
                an = message.animation
                if (getattr(an, "file_size", 0) or 0) > MAX_FILE_BYTES:
                    return "[GIF: слишком большой, содержание неизвестно]"
                desc = await self._analyze(an.file_unique_id, "gif", an.file_id, "video/mp4", GIF_PROMPT)
                return f"[GIF: {desc}]" if desc else "[GIF: содержание неизвестно]"
        except Exception as e:
            logger.warning(f"media: fragment failed: {e}")
            kind = ("Картинка" if getattr(message, "photo", None) else "Голосовое" if message.voice else "Кружок" if message.video_note
                    else "Стикер" if message.sticker else "GIF" if message.animation else "Медиа")
            return f"[{kind}: не удалось разобрать, содержание неизвестно]"
        return None
