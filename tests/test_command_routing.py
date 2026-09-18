"""Commands must bypass conversational catch-alls, including replies and mentions."""
import ast
from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest
from aiogram import Router
from aiogram.types import Message, Chat, User, MessageEntity

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from handlers.moltbot_handlers import MoltbotHandlers
from handlers.court_handlers import CourtHandlers


def commands_in_main_bot():
    result = set()
    for path in (Path(__file__).resolve().parents[1] / 'src/handlers').glob('*.py'):
        if path.name == 'music_handlers.py':  # Separate legacy module, not included in main.py.
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'Command':
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        result.add(arg.value)
                for kw in node.keywords:
                    if kw.arg == 'commands' and isinstance(kw.value, (ast.List, ast.Tuple)):
                        result.update(n.value for n in kw.value.elts if isinstance(n, ast.Constant))
    return sorted(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('command', commands_in_main_bot())
async def test_commands_in_replies_and_with_mentions_bypass_ai(command):
    handler = object.__new__(MoltbotHandlers)
    handler.router = Router()
    handler._register()
    message = Message(message_id=1, date=datetime.now(timezone.utc),
                      chat=Chat(id=-100, type='supergroup'), from_user=User(id=1, is_bot=False, first_name='Test'),
                      text=f'/{command} @someone', entities=[MessageEntity(type='mention', offset=len(command)+2, length=8)],
                      reply_to_message=Message(message_id=2, date=datetime.now(timezone.utc),
                                               chat=Chat(id=-100, type='supergroup'),
                                               from_user=User(id=99, is_bot=True, first_name='Bot'), text='Bot post'))
    for registered in handler.router.message.handlers:
        if registered.callback.__name__ in ('handle_mention', 'handle_reply_to_bot', 'handle_probabilistic'):
            matched, _ = await registered.check(message, raw_state=None)
            assert not matched, registered.callback.__name__


@pytest.mark.asyncio
async def test_command_reply_bypasses_active_court_speech_handler():
    handler = object.__new__(CourtHandlers)
    handler.router = Router()
    handler._bot_id = 99
    handler._pending_speech = {-100: {}}
    handler._active_game_chats = {-100}
    handler._register()
    message = Message(message_id=1, date=datetime.now(timezone.utc),
                      chat=Chat(id=-100, type='supergroup'), from_user=User(id=1, is_bot=False, first_name='Test'),
                      text='/kazik', reply_to_message=Message(message_id=2, date=datetime.now(timezone.utc),
                      chat=Chat(id=-100, type='supergroup'), from_user=User(id=99, is_bot=True, first_name='Bot'), text='Say something'))
    registered = next(h for h in handler.router.message.handlers if h.callback.__name__ == 'handle_group_reply')
    matched, _ = await registered.check(message, raw_state=None)
    assert not matched


@pytest.mark.asyncio
async def test_cancel_clears_fsm_without_pending_admin_action():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from handlers.admin_handlers import AdminHandlers
    handler = object.__new__(AdminHandlers)
    handler.router = Router()
    handler.admin_actions = {}
    handler._register()
    callback = next(h.callback for h in handler.router.message.handlers if h.callback.__name__ == 'cancel_admin_action')
    message = SimpleNamespace(from_user=SimpleNamespace(id=1), reply=AsyncMock())
    state = SimpleNamespace(get_state=AsyncMock(return_value='GameStates:waiting_donation'), clear=AsyncMock())
    await callback(message, state)
    state.clear.assert_awaited_once()
    assert 'отменено' in message.reply.call_args.args[0]


@pytest.mark.asyncio
async def test_command_bypasses_pending_admin_text_action():
    from handlers.admin_handlers import AdminHandlers
    handler = object.__new__(AdminHandlers)
    handler.router = Router()
    handler.admin_actions = {1: {'action': 'give_coins'}}
    handler._register()
    message = Message(message_id=1, date=datetime.now(timezone.utc),
                      chat=Chat(id=-100, type='supergroup'), from_user=User(id=1, is_bot=False, first_name='Test'), text='/kazik')
    registered = next(h for h in handler.router.message.handlers if h.callback.__name__ == 'handle_admin_text_input')
    matched, _ = await registered.check(message, raw_state=None)
    assert not matched
