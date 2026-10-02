"""Jarvis' vows: time-boxed rules the bot really keeps, not just a promise in recent history.

2026-10-02: Юра spent the boss-event MVP privilege («любое изменение в боте на неделю») on
«всю неделю все твои сообщения только эмодзи — и викторина, и вордл». Jarvis agreed in chat,
but a promise that lives only in the history window is forgotten a few hours later, and the
prophecy/quiz/Wordle generators never saw it. A vow is stored with its deadline and enforced
on the way out: every message, edit, caption, button, poll and toast the bot sends to that chat.

Enforcement is two-step: an LLM rewrites the text into emoji (cheap free-tier model, cached),
then a deterministic guard strips any letter that survived and turns digits into keycaps —
so even when the model fails, not a single word reaches the chat.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

EMOJI_ONLY = "emoji_only"
EMOJIFY_MODEL = "gemini-2.5-flash-lite"
EMOJIFY_TIMEOUT = 12
REFRESH_SECS = 60
_CACHE_LIMIT = 500

CREATE_SQL = (
    "CREATE TABLE IF NOT EXISTS bot_vows ("
    " id SERIAL PRIMARY KEY,"
    " chat_id BIGINT NOT NULL,"
    " kind TEXT NOT NULL,"
    " note TEXT NOT NULL DEFAULT '',"
    " ends_at TIMESTAMPTZ NOT NULL,"
    " created_by BIGINT,"
    " cancelled BOOLEAN NOT NULL DEFAULT FALSE,"
    " created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
)

PERSONA_OVERLAY = (
    "ОБЕТ (действует до {until}): {note}. Ты отвечаешь ТОЛЬКО эмодзи — ни одной буквы, ни на каком языке, "
    "ни в одном сообщении. Смысл, юмор и ответ на вопрос передавай эмодзи; числа — эмодзи-цифрами (2️⃣0️⃣2️⃣6️⃣). "
    "Сорвёшься хоть на одно слово — тебя назовут пиздаболом, и будут правы."
)

EMOJIFY_PROMPT = """Ты переводишь сообщения Telegram-бота в эмодзи: бот поклялся неделю писать ТОЛЬКО эмодзи.
Перепиши каждую строку ниже так, чтобы в ней не осталось ни одной буквы (ни русской, ни английской, никакой),
но смысл читался: эмодзи-ребус, эмодзи-цифры (1️⃣2️⃣), флаги, стрелки, символы. Сохраняй порядок и структуру,
не добавляй ничего от себя, не теряй факты (кто, что, сколько, когда). Длинный текст можно сжать.
Если строки — варианты ответа викторины, они ОБЯЗАНЫ отличаться друг от друга и оставаться угадываемыми.
Верни ТОЛЬКО JSON-массив строк той же длины и в том же порядке.

Строки:
{items}"""

_LETTERS = re.compile(r"[A-Za-zÀ-ɏͰ-ϿЀ-ӿ]")
_TAGS = re.compile(r"<[^>]+>")
_DIGIT = re.compile(r"(\d)(?!️?⃣)")


def has_letters(text: str | None) -> bool:
    return bool(text and _LETTERS.search(_TAGS.sub("", text)))


def guard(text: str) -> str:
    """Deterministic last line: no tags, no letters, digits as keycaps, markup-safe."""
    text = _TAGS.sub("", text or "")
    text = _LETTERS.sub("", text)
    text = text.replace("&", "").replace("<", "").replace(">", "")
    text = _DIGIT.sub(lambda m: f"{m.group(1)}️⃣", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [ln.strip(" \t.,:;!?—–-") for ln in text.split("\n")]   # «Пуджинио: 967» → «9️⃣6️⃣7️⃣», not «: 9️⃣…»
    text = "\n".join(ln for ln in lines if re.search(r"[^\s.,:;!?()\[\]«»\"'—–\-_/|*#+=~`]", ln) or not ln)
    return text.strip() or "🤐"


class VowService:
    def __init__(self, db, model_getter=None):
        self.db = db
        self._model_getter = model_getter
        self._active: dict[int, dict] = {}
        self._cache: dict[str, str] = {}

    async def ensure_table(self) -> None:
        await self.db.execute_query(CREATE_SQL)

    async def refresh(self) -> None:
        rows = await self.db.execute_query(
            "SELECT DISTINCT ON (chat_id) chat_id, kind, note, ends_at FROM bot_vows "
            "WHERE NOT cancelled AND ends_at > NOW() ORDER BY chat_id, created_at DESC")
        self._active = {r[0]: {"kind": r[1], "note": r[2], "ends_at": r[3]} for r in rows or []}

    async def run_refresh_loop(self) -> None:
        try:
            await self.ensure_table()
        except Exception as e:
            logger.error(f"Vow: table failed: {e}")
        while True:
            try:
                await self.refresh()
            except Exception as e:
                logger.warning(f"Vow: refresh failed: {e}")
            await asyncio.sleep(REFRESH_SECS)

    # ── state ────────────────────────────────────────────────────────────
    def active(self, chat_id: int | None, now: datetime | None = None) -> dict | None:
        vow = self._active.get(chat_id) if chat_id is not None else None
        if vow and vow["ends_at"] > (now or datetime.now(timezone.utc)):
            return vow
        return None

    def any_active(self) -> bool:
        return any(self.active(chat_id) for chat_id in list(self._active))

    def persona_overlay(self, chat_id: int | None) -> str:
        vow = self.active(chat_id)
        if not vow or vow["kind"] != EMOJI_ONLY:
            return ""
        from zoneinfo import ZoneInfo
        until = vow["ends_at"].astimezone(ZoneInfo("Europe/Kyiv")).strftime("%d.%m %H:%M по Киеву")
        return PERSONA_OVERLAY.format(until=until, note=vow["note"] or "только эмодзи")

    async def start(self, chat_id: int, kind: str, note: str, ends_at: datetime, by: int | None) -> None:
        await self.db.execute_query(
            "INSERT INTO bot_vows (chat_id, kind, note, ends_at, created_by) VALUES (%s, %s, %s, %s, %s)",
            (chat_id, kind, note, ends_at, by))
        await self.refresh()

    async def cancel(self, chat_id: int) -> None:
        await self.db.execute_query("UPDATE bot_vows SET cancelled = TRUE WHERE chat_id = %s AND NOT cancelled",
                                    (chat_id,))
        await self.refresh()

    # ── enforcement ──────────────────────────────────────────────────────
    async def emojify(self, items: list[str]) -> list[str]:
        """Strings → emoji-only strings (same order). Never returns a letter."""
        todo = [s for s in dict.fromkeys(items) if has_letters(s) and s not in self._cache]
        if todo:
            try:
                for src, out in zip(todo, await self._ask(todo)):
                    self._cache[src] = guard(out)
            except Exception as e:
                logger.warning(f"Vow: emojify failed ({len(todo)} items), letters stripped instead: {e}")
            if len(self._cache) > _CACHE_LIMIT:
                for key in list(self._cache)[:len(self._cache) - _CACHE_LIMIT]:
                    del self._cache[key]
        return [self._cache.get(s) or guard(s) for s in items]

    async def _ask(self, items: list[str]) -> list[str]:
        model = self._model_getter() if self._model_getter else None
        if model is None:
            raise RuntimeError("Gemini не настроен")
        import google.generativeai as genai
        from services import llm_trace
        lite = genai.GenerativeModel(EMOJIFY_MODEL)
        prompt = EMOJIFY_PROMPT.format(items=json.dumps([_TAGS.sub("", s) for s in items], ensure_ascii=False))
        response = await llm_trace.call("vow", "gemini", EMOJIFY_MODEL, lambda: asyncio.wait_for(
            asyncio.to_thread(lite.generate_content, prompt), EMOJIFY_TIMEOUT))
        raw = response.text or ""
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        out = json.loads(match.group(0)) if match else []
        if not isinstance(out, list) or len(out) != len(items):
            raise ValueError(f"expected {len(items)} strings, got {raw[:200]!r}")
        return [str(x) for x in out]


_instance: VowService | None = None


def get_vow_service(db=None, model_getter=None) -> VowService | None:
    global _instance
    if _instance is None and db is not None:
        _instance = VowService(db, model_getter)
    return _instance
