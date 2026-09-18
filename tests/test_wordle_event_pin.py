from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from handlers import wordle_handlers


@pytest.mark.asyncio
@pytest.mark.parametrize('event, lookup_failure, should_pin', [
    ({'chat_id': -100}, False, False),
    ({'chat_id': -200}, False, True),
    (None, False, True),
    (None, True, False),
])
async def test_daily_wordle_posts_but_keeps_event_pin(monkeypatch, event, lookup_failure, should_pin):
    bot = AsyncMock()
    bot.send_message.return_value = SimpleNamespace(message_id=99)
    db = SimpleNamespace(execute_query=AsyncMock(side_effect=[[], [(55,)], [], None]))
    boss = SimpleNamespace(get_active_event=AsyncMock(return_value=event))
    if lookup_failure:
        boss.get_active_event.side_effect = RuntimeError('database unavailable')
    monkeypatch.setattr(wordle_handlers, 'get_boss_service', lambda manager: boss)
    handler = wordle_handlers.WordleHandlers(bot, db)
    handler._ensure_tables = AsyncMock()

    await handler.post_daily_wordle(-100)

    bot.send_message.assert_awaited_once()
    # Cleanup targets yesterday's Wordle only, never the event's message.
    bot.unpin_chat_message.assert_awaited_once_with(-100, message_id=55)
    assert bot.pin_chat_message.await_count == int(should_pin)
    if should_pin:
        bot.pin_chat_message.assert_awaited_once_with(-100, 99, disable_notification=True)
    assert 'INSERT INTO wordle_daily' in db.execute_query.call_args.args[0]
