"""Record every message the bot itself sends or edits into `messages`.

Only Jarvis' persona replies used to be stored. Quiz questions, Wordle posts, boss
lobbies, prophecies… were invisible to history and reply chains, so Jarvis lost them
one hop later — and since they are sent from the same bot account, he also took them
for his own words. 2026-09-23: he correctly said «все уже галочку поставили» about a
quiz, then, no longer seeing it, «admitted» he had made it up, then claimed he had set
the checkmarks himself.

This request middleware sees every outgoing call. The author label comes from the
module that sent it (quiz → «Викторина», boss → «Пуджинио», moltbot → «Jarvis»), so the
persona model can tell game posts from its own replies. Rows get user_id = 0: Memory v2
and the summary already ignore bot-authored rows. Writes are fire-and-forget and never
break or slow down sending.
"""
from __future__ import annotations

import asyncio
import logging
import sys

from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.methods import (EditMessageCaption, EditMessageText, SendAnimation, SendMessage, SendPhoto,
                             SendPoll, SendVideo)

logger = logging.getLogger(__name__)

# module (by prefix) → author shown in history. Anything unmatched is the bot speaking as Jarvis.
AUTHORS = (
    ("handlers.trivia_handlers", "Викторина"),
    ("services.trivia_service", "Викторина"),
    ("services.quiz_scheduler", "Викторина"),
    ("handlers.wordle_handlers", "Wordle"),
    ("handlers.boss_handlers", "Пуджинио"),
    ("services.boss_service", "Пуджинио"),
    ("handlers.dungeon_handlers", "Данж"),
    ("handlers.daily_prophecy_handlers", "Пророчество"),
    ("handlers.weekly_highlight_handlers", "Хайлайт недели"),
    ("handlers.court_handlers", "Суд"),
    ("services.court_service", "Суд"),
    ("handlers.game_handlers", "Игра"),
    ("handlers.shop_handlers", "Магазин"),
    ("handlers.pet_handlers", "Питомец"),
    ("handlers.entertainment_handlers", "Развлечения"),
    ("handlers.admin_handlers", "Бот"),
    ("handlers.health_alert_handlers", "Бот"),
    ("handlers.prompt_handlers", "Бот"),
    ("handlers.miniapp_handlers", "Казино"),
    ("handlers.moltbot_handlers", "Jarvis"),
)
DEFAULT_AUTHOR = "Jarvis"
_SEND = (SendMessage, SendPhoto, SendAnimation, SendVideo, SendPoll)
_EDIT = (EditMessageText, EditMessageCaption)


def _caller_author() -> str:
    """Walk the live await chain for the first bot module that initiated the request."""
    frame = sys._getframe(2)
    while frame is not None:
        module = frame.f_globals.get("__name__", "")
        if module.startswith(("handlers.", "services.")):
            for prefix, author in AUTHORS:
                if module.startswith(prefix):
                    return author
            return DEFAULT_AUTHOR
        frame = frame.f_back
    return DEFAULT_AUTHOR


def _text_of(method) -> str:
    if isinstance(method, SendPoll):
        options = [getattr(o, "text", o) for o in (method.options or [])]
        return f"[Опрос] {method.question}" + (f" ({' / '.join(map(str, options))})" if options else "")
    if isinstance(method, (SendMessage, EditMessageText)):
        return method.text or ""
    label = {SendPhoto: "[Фото]", SendAnimation: "[GIF]", SendVideo: "[Видео]"}.get(type(method), "")
    caption = getattr(method, "caption", None) or ""
    return f"{label} {caption}".strip()


def _reply_to(method) -> int | None:
    params = getattr(method, "reply_parameters", None)
    if params is not None and getattr(params, "message_id", None):
        return int(params.message_id)
    rid = getattr(method, "reply_to_message_id", None)
    return int(rid) if rid else None


class OutgoingMessageLogger(BaseRequestMiddleware):
    def __init__(self, db):
        self.db = db

    async def __call__(self, make_request, bot, method):
        response = await make_request(bot, method)
        try:
            if isinstance(method, _SEND + _EDIT):
                self._record(method, response, _caller_author())
        except Exception as e:  # never let bookkeeping affect sending
            logger.debug(f"outgoing: skip record: {e}")
        return response

    def _record(self, method, response, author: str) -> None:
        result = getattr(response, "result", None)
        chat = getattr(result, "chat", None)
        message_id = getattr(result, "message_id", None)
        if chat is None or message_id is None or chat.type not in ("group", "supergroup"):
            return
        text = _text_of(method)
        if not text:
            return
        edit = isinstance(method, _EDIT)
        asyncio.get_running_loop().create_task(
            self._store(chat.id, message_id, text, author, _reply_to(method), edit))

    async def _store(self, chat_id: int, message_id: int, text: str, author: str,
                     reply_to: int | None, edit: bool) -> None:
        try:
            if edit:
                # Edits (quiz checkmarks, boss HP bar) replace the text but keep who sent it.
                await self.db.execute_query(
                    "INSERT INTO messages (chat_id, user_id, message_text, timestamp, name, message_id) "
                    "VALUES (%s, 0, %s, CURRENT_TIMESTAMP, %s, %s) "
                    "ON CONFLICT (chat_id, message_id) WHERE message_id IS NOT NULL "
                    "DO UPDATE SET message_text = EXCLUDED.message_text",
                    (chat_id, text, author, message_id))
            else:
                await self.db.execute_query(
                    "INSERT INTO messages (chat_id, user_id, message_text, timestamp, name, message_id, "
                    "reply_to_message_id) VALUES (%s, 0, %s, CURRENT_TIMESTAMP, %s, %s, %s) "
                    "ON CONFLICT (chat_id, message_id) WHERE message_id IS NOT NULL DO NOTHING",
                    (chat_id, text, author, message_id, reply_to))
        except Exception as e:
            logger.warning(f"outgoing: store failed for {chat_id}/{message_id}: {e}")
