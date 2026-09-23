"""Every outgoing bot message is recorded with the author = the module that sent it."""
import asyncio
import os
import sys
import types
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from aiogram.methods import EditMessageText, SendMessage
from aiogram.types import ReplyParameters

from middleware.outgoing_messages import OutgoingMessageLogger


def _module(name: str):
    """A function whose frame globals say it lives in `name` (like a real handler module)."""
    mod = types.ModuleType(name)
    exec("async def send(mw, method, resp):\n"
         "    async def make_request(bot, m):\n"
         "        return resp\n"
         "    return await mw(make_request, None, method)\n", mod.__dict__)
    return mod.send


def _resp(message_id=100, chat_type="supergroup"):
    return NS(result=NS(chat=NS(id=-1001294162183, type=chat_type), message_id=message_id))


async def _drain():
    await asyncio.sleep(0)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_quiz_post_is_recorded_as_quiz_and_edit_updates_text():
    db = AsyncMock()
    mw = OutgoingMessageLogger(db)
    send = _module("handlers.trivia_handlers")
    await send(mw, SendMessage(chat_id=1, text="Какой материк самый холодный?"), _resp(160780))
    await send(mw, EditMessageText(chat_id=1, message_id=160780, text="Какой материк…\n\nМакс ✅"), _resp(160780))
    await _drain()
    insert, edit = [c.args for c in db.execute_query.await_args_list]
    assert insert[1][2] == "Викторина" and insert[1][3] == 160780
    assert "DO UPDATE SET message_text" in edit[0] and edit[1][1].endswith("Макс ✅")


@pytest.mark.asyncio
async def test_jarvis_reply_keeps_jarvis_name_and_reply_link():
    db = AsyncMock()
    mw = OutgoingMessageLogger(db)
    send = _module("handlers.moltbot_handlers")
    await send(mw, SendMessage(chat_id=1, text="здарова", reply_parameters=ReplyParameters(message_id=55)), _resp(200))
    await _drain()
    (args,) = [c.args for c in db.execute_query.await_args_list]
    assert args[1][2] == "Jarvis" and args[1][4] == 55


@pytest.mark.asyncio
async def test_private_chats_and_db_errors_never_break_sending():
    db = AsyncMock()
    db.execute_query = AsyncMock(side_effect=RuntimeError("db down"))
    mw = OutgoingMessageLogger(db)
    send = _module("handlers.boss_handlers")
    resp = _resp(300)
    assert await send(mw, SendMessage(chat_id=1, text="HP 1500"), resp) is resp   # error swallowed
    await _drain()
    db2 = AsyncMock()
    await _module("handlers.boss_handlers")(OutgoingMessageLogger(db2), SendMessage(chat_id=1, text="x"),
                                            _resp(301, chat_type="private"))
    await _drain()
    db2.execute_query.assert_not_awaited()
