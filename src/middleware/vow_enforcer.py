"""Enforce an active vow on everything the bot sends (see services/vow_service.py).

Registered before OutgoingMessageLogger, so history stores what the chat actually saw.
Inline button labels are rewritten too, callback_data is untouched — quiz and Wordle keep
working. Reply-keyboard labels are left alone: Telegram sends them back as user text.
"""
from __future__ import annotations

import logging

from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.methods import (AnswerCallbackQuery, EditMessageCaption, EditMessageReplyMarkup, EditMessageText,
                             SendAnimation, SendMessage, SendPhoto, SendPoll, SendVideo)
from aiogram.types import InlineKeyboardMarkup

from services import vow_service

logger = logging.getLogger(__name__)

_TEXT = (SendMessage, EditMessageText)
_CAPTION = (SendPhoto, SendAnimation, SendVideo, EditMessageCaption)
_ALL = _TEXT + _CAPTION + (SendPoll, EditMessageReplyMarkup, AnswerCallbackQuery)


def _chat_id(method) -> int | None:
    try:
        return int(getattr(method, "chat_id", None))
    except (TypeError, ValueError):
        return None


async def apply_vow(vows: vow_service.VowService, method):
    """Return `method` rewritten under the chat's vow (or unchanged)."""
    if isinstance(method, AnswerCallbackQuery):
        # A toast has no chat; quiz answers in the vowed chat are what it is for.
        if not (method.text and vows.any_active()):
            return method
    else:
        vow = vows.active(_chat_id(method))
        if not vow or vow["kind"] != vow_service.EMOJI_ONLY:
            return method

    slots: list[tuple[str, object]] = []          # (kind, ref) in the order of `items`
    items: list[str] = []

    def add(kind: str, ref, text) -> None:
        if isinstance(text, str) and text:
            slots.append((kind, ref))
            items.append(text)

    if isinstance(method, _TEXT) or isinstance(method, AnswerCallbackQuery):
        add("text", None, method.text)
    if isinstance(method, _CAPTION):
        add("caption", None, method.caption)
    if isinstance(method, SendPoll):
        add("question", None, method.question)
        add("explanation", None, method.explanation)
        for i, option in enumerate(method.options or []):
            add("option", i, getattr(option, "text", option))
    markup = getattr(method, "reply_markup", None)
    if isinstance(markup, InlineKeyboardMarkup):
        for r, row in enumerate(markup.inline_keyboard):
            for c, button in enumerate(row):
                add("button", (r, c), button.text)

    if not any(vow_service.has_letters(s) for s in items) and not any(ch.isdigit() for s in items for ch in s):
        return method
    out = await vows.emojify(items)

    update: dict = {}
    options = list(method.options or []) if isinstance(method, SendPoll) else None
    rows = [list(row) for row in markup.inline_keyboard] if isinstance(markup, InlineKeyboardMarkup) else None
    for (kind, ref), new in zip(slots, out):
        if kind == "option":
            old = options[ref]
            options[ref] = old.model_copy(update={"text": new}) if hasattr(old, "model_copy") else new
        elif kind == "button":
            r, c = ref
            rows[r][c] = rows[r][c].model_copy(update={"text": new})
        else:
            update[kind] = new
    if "text" in update and isinstance(method, _TEXT):
        update.update(parse_mode=None, entities=None)
    if "caption" in update:
        update.update(parse_mode=None, caption_entities=None)
    if isinstance(method, SendPoll):
        update.update(options=options, question_parse_mode=None, explanation_parse_mode=None)
    if rows is not None:
        update["reply_markup"] = InlineKeyboardMarkup(inline_keyboard=rows)
    return method.model_copy(update=update)


class VowEnforcer(BaseRequestMiddleware):
    def __init__(self, vows: vow_service.VowService):
        self.vows = vows

    async def __call__(self, make_request, bot, method):
        if isinstance(method, _ALL):
            try:
                method = await apply_vow(self.vows, method)
            except Exception as e:
                # The vow must not take the bot down; worst case one message goes out as is.
                logger.error(f"Vow: enforcement failed for {type(method).__name__}: {e}")
        return await make_request(bot, method)
