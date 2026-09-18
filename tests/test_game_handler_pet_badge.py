from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from handlers.game_handlers import GameHandlers
from models.player import Player
from services.game_service import GameService
from services import boss_service


@pytest.mark.asyncio
@pytest.mark.parametrize('target,expected', [
    ('MAX', ['vor_yura', 'vor_bogdan']),
    ('YURA', ['vor_max', 'vor_bogdan']),
    ('BODYA', ['vor_max', 'vor_yura']),
])
async def test_theft_target_keyboard_uses_configured_player_ids(target, expected):
    from config.settings import Settings
    player_id = Settings.PLAYER_IDS[target]
    players = SimpleNamespace(get_player=AsyncMock(return_value=Player(player_id=player_id, player_name='Test')))
    game = SimpleNamespace(can_steal=lambda player: (True, None))
    bot = AsyncMock()
    handler = GameHandlers(bot, players, game)
    callback = next(h.callback for h in handler.router.message.handlers if h.callback.__name__ == 'theft_command')
    message = SimpleNamespace(from_user=SimpleNamespace(id=player_id, username=None),
                              chat=SimpleNamespace(id=-100), reply=AsyncMock())
    await callback(message)
    markup = bot.send_message.call_args.kwargs['reply_markup']
    assert [button.callback_data for row in markup.inline_keyboard for button in row] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize('with_pet', [False, True])
async def test_pisunchik_sends_result_and_damages_boss_once(monkeypatch, with_pet):
    player = Player(player_id=1, player_name='Test')
    if with_pet:
        player.pet = {'is_alive': True, 'is_locked': True, 'stage': 'baby'}
    players = SimpleNamespace(get_player=AsyncMock(return_value=player), save_player=AsyncMock())
    boss = SimpleNamespace(deal_damage=AsyncMock())
    monkeypatch.setattr(boss_service, 'get_boss_service', lambda: boss)
    handlers = GameHandlers(AsyncMock(), players, GameService(players))
    callback = next(h.callback for h in handlers.router.message.handlers
                    if h.callback.__name__ == 'pisunchik_command')
    message = SimpleNamespace(from_user=SimpleNamespace(id=1), chat=SimpleNamespace(id=-100), reply=AsyncMock())
    await callback(message)
    text = message.reply.call_args.args[0]
    assert 'Ваш писюнчик' in text and 'Также вы получили:' in text
    assert ('🐣' in text) == with_pet
    assert player.last_used.year > 2000
    boss.deal_damage.assert_awaited_once_with(1, 'Test', 'pisunchik')
    await callback(message)
    assert 'Осталось времени:' in message.reply.call_args.args[0]
    assert boss.deal_damage.await_count == 1


@pytest.mark.asyncio
async def test_roll_sends_result_with_synchronous_pet_badge():
    player = Player(player_id=1, player_name='Test')
    player.pet = {'is_alive': True, 'is_locked': True, 'stage': 'baby'}
    players = SimpleNamespace(get_player=AsyncMock(return_value=player), save_player=AsyncMock())
    game = SimpleNamespace(execute_roll_command=AsyncMock(return_value={
        'success': True, 'results': [3], 'cost': 10, 'new_size': 5, 'jackpots': 0}))
    bot = AsyncMock()
    handlers = GameHandlers(bot, players, game)
    callback = next(h.callback for h in handlers.router.callback_query.handlers
                    if h.callback.__name__ == 'handle_roll_callback')
    call = SimpleNamespace(data='roll_1', from_user=SimpleNamespace(id=1),
                           message=SimpleNamespace(chat=SimpleNamespace(id=-100), message_id=10))
    await callback(call)
    assert 'Писюнчик 🐣: 5 см' in bot.send_message.call_args.args[1]


@pytest.mark.asyncio
@pytest.mark.parametrize('telegram_failure', [False, True])
async def test_kazik_delivers_summary_and_persists_winnings(monkeypatch, telegram_failure):
    from handlers import game_handlers
    player = Player(player_id=1, player_name='Test')
    players = SimpleNamespace(get_player=AsyncMock(return_value=player), save_player=AsyncMock())
    bot = AsyncMock()
    dice = [SimpleNamespace(message_id=i, dice=SimpleNamespace(value=v))
            for i, v in enumerate([1, 2, 22, 3, 43, 64], 1)]
    bot.send_dice.side_effect = dice if not telegram_failure else dice[:2] + [RuntimeError('Telegram unavailable')]
    monkeypatch.setattr(game_handlers, 'asyncio', SimpleNamespace(sleep=AsyncMock()))
    handler = GameHandlers(bot, players, GameService(players))
    callback = next(h.callback for h in handler.router.message.handlers if h.callback.__name__ == 'casino_command')
    message = SimpleNamespace(from_user=SimpleNamespace(id=1), chat=SimpleNamespace(id=-100), reply=AsyncMock())
    await callback(message)
    assert player.casino_usage_count == 1
    assert player.coins == (300 if telegram_failure else 1200)
    players.save_player.assert_awaited()
    bot.send_message.assert_awaited_once()
    text = bot.send_message.call_args.args[1]
    assert ('только 2 из 6' in text) == telegram_failure
    assert ('1/6' if telegram_failure else '4/6') in text


@pytest.mark.asyncio
async def test_masturbator_uses_fsm_and_retries_invalid_input():
    player = Player(player_id=1, player_name='Test', pisunchik_size=20, items=['masturbator'])
    players = SimpleNamespace(get_player=AsyncMock(return_value=player), save_player=AsyncMock())
    handler = GameHandlers(AsyncMock(), players, GameService(players))
    command = next(h.callback for h in handler.router.message.handlers if h.callback.__name__ == 'masturbator_command')
    input_handler = next(h.callback for h in handler.router.message.handlers if h.callback.__name__ == 'masturbator_input')
    message = SimpleNamespace(from_user=SimpleNamespace(id=1), chat=SimpleNamespace(id=-100), reply=AsyncMock(), text='wrong')
    state = SimpleNamespace(set_state=AsyncMock(), clear=AsyncMock())
    await command(message, state)
    state.set_state.assert_awaited_once()
    await input_handler(message, state)
    assert 'корректное число' in message.reply.call_args.args[0]
    state.clear.assert_not_awaited()
    message.text = '5'
    await input_handler(message, state)
    assert player.pisunchik_size == 15
    assert 'задонатили 5' in message.reply.call_args.args[0]
    state.clear.assert_awaited_once()


@pytest.mark.asyncio
async def test_trivia_question_helper_awaits_generation():
    from handlers.trivia_handlers import TriviaHandlers
    handler = object.__new__(TriviaHandlers)
    handler.trivia_service = SimpleNamespace(generate_question=AsyncMock(return_value={
        'success': True, 'question': {'text': 'Вопрос?', 'correct_answer': 'Да', 'options': ['Да', 'Нет']}}))
    result = await handler.get_question_from_gemini()
    assert result['answer'] == 'Да' and result['wrong_answers'] == ['Нет']
    handler.trivia_service.generate_question.assert_awaited_once()
