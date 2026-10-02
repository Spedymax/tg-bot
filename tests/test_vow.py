"""Vows: the emoji-only week is enforced on everything the bot sends to the vowed chat."""
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage, SendPhoto, SendPoll
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from middleware.vow_enforcer import apply_vow
from services import vow_service as vs

CHAT, OTHER = -1001294162183, 741542965
NOW = datetime.now(timezone.utc)


def _service(active=True, emoji=None):
    svc = vs.VowService(db=AsyncMock())
    if active:
        svc._active = {CHAT: {"kind": vs.EMOJI_ONLY, "note": "Юра: неделя эмодзи", "ends_at": NOW + timedelta(days=7)}}
    svc._ask = AsyncMock(side_effect=lambda items: [emoji.get(s, "🙂") for s in items] if emoji else
                         ["🙂" for _ in items])
    return svc


def test_guard_never_lets_a_letter_through():
    assert vs.guard("<b>Привет</b> hello 🍊 2026") == "🍊 2️⃣0️⃣2️⃣6️⃣"
    assert vs.guard("1️⃣ уже keycap") == "1️⃣"
    assert vs.guard("только слова") == "🤐"
    assert vs.guard("🇺🇦👤") == "🇺🇦👤"
    assert not vs.has_letters(vs.guard("Ёж, Їжак, ελλάδα, Straße — ok 👍"))


def test_overlay_only_for_the_vowed_chat_and_until_the_deadline():
    svc = _service()
    assert "ТОЛЬКО эмодзи" in svc.persona_overlay(CHAT) and "Юра: неделя эмодзи" in svc.persona_overlay(CHAT)
    assert svc.persona_overlay(OTHER) == ""
    svc._active[CHAT]["ends_at"] = NOW - timedelta(minutes=1)
    assert svc.persona_overlay(CHAT) == "" and not svc.any_active()


@pytest.mark.asyncio
async def test_message_text_and_inline_buttons_are_emojified_callback_data_kept():
    svc = _service(emoji={"Какая страна победила в 1930?": "🌍🏆❓ 1930", "Уругвай": "🇺🇾", "Бразилия": "🇧🇷"})
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Уругвай", callback_data="ans_0")],
        [InlineKeyboardButton(text="Бразилия", callback_data="ans_1")],
    ])
    method = SendMessage(chat_id=CHAT, text="Какая страна победила в 1930?", reply_markup=markup, parse_mode="HTML")
    out = await apply_vow(svc, method)
    assert out.text == "🌍🏆❓ 1️⃣9️⃣3️⃣0️⃣" and out.parse_mode is None
    labels = [(b.text, b.callback_data) for row in out.reply_markup.inline_keyboard for b in row]
    assert labels == [("🇺🇾", "ans_0"), ("🇧🇷", "ans_1")]
    svc._ask.assert_awaited_once()


@pytest.mark.asyncio
async def test_other_chats_and_emoji_replies_pass_untouched():
    svc = _service()
    dm = SendMessage(chat_id=OTHER, text="Health alert: OpenRouter")
    assert await apply_vow(svc, dm) is dm
    native = SendMessage(chat_id=CHAT, text="🍊🟠")
    assert await apply_vow(svc, native) is native
    svc._ask.assert_not_awaited()
    assert await apply_vow(_service(active=False), SendMessage(chat_id=CHAT, text="текст")) is not None


@pytest.mark.asyncio
async def test_edits_captions_polls_and_toasts():
    svc = _service()
    edit = await apply_vow(svc, EditMessageText(chat_id=CHAT, message_id=5, text="Макс ✅"))
    assert edit.text == "🙂"
    photo = await apply_vow(svc, SendPhoto(chat_id=CHAT, photo="file", caption="Подпись"))
    assert photo.caption == "🙂"
    poll = await apply_vow(svc, SendPoll(chat_id=CHAT, question="Кто?", options=["Юра", "Богдан"]))
    assert poll.question == "🙂" and [getattr(o, "text", o) for o in poll.options] == ["🙂", "🙂"]
    toast = await apply_vow(svc, AnswerCallbackQuery(callback_query_id="1", text="Верно!"))
    assert toast.text == "🙂"
    wordle = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text="🎮 Играть в Wordle", web_app=WebAppInfo(url="https://casino.spedymax.org/wordle"))]])
    post = await apply_vow(svc, SendMessage(chat_id=CHAT, text="WORDLE ДНЯ", reply_markup=wordle))
    assert post.reply_markup.inline_keyboard[0][0].web_app.url.endswith("/wordle")


@pytest.mark.asyncio
async def test_model_failure_still_sends_no_words_and_cache_avoids_repeat_calls():
    svc = _service()
    svc._ask = AsyncMock(side_effect=RuntimeError("quota"))
    out = await apply_vow(svc, SendMessage(chat_id=CHAT, text="Пуджинио: HP 967/2500 🩸"))
    assert out.text == "9️⃣6️⃣7️⃣/2️⃣5️⃣0️⃣0️⃣ 🩸"
    ok = _service()
    await ok.emojify(["Привет"])
    await ok.emojify(["Привет"])
    ok._ask.assert_awaited_once()
