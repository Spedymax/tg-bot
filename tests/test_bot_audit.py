from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiogram.types import FSInputFile
from psycopg.conninfo import conninfo_to_dict

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from config.settings import Settings
from database import db_manager
from handlers.pet_handlers import PetHandlers
from handlers.shop_handlers import ShopHandlers
from handlers.entertainment_handlers import EntertainmentHandlers
from handlers.health_alert_handlers import HealthAlertHandlers
from handlers.weekly_highlight_handlers import WeeklyHighlightHandlers
from models.player import Player
from services.game_service import GameService
from services.stock_service import StockService
from services.quiz_scheduler import QuizScheduler
from states.pet import PetStates


def pet_handler():
    player = Player(1, 'Test', pet={'name': 'Test', 'stage': 'baby', 'is_alive': True, 'is_locked': True})
    players = SimpleNamespace(get_player=AsyncMock(return_value=player), save_player=AsyncMock(return_value=True))
    handler = PetHandlers(AsyncMock(), players, GameService(players))
    handler.show_pet_menu = AsyncMock()
    return handler, player


def call(data='pet_name'):
    return SimpleNamespace(from_user=SimpleNamespace(id=1),
                           message=SimpleNamespace(chat=SimpleNamespace(id=-100), message_id=10),
                           data=data, answer=AsyncMock())


def message(text='Name', photo=None):
    return SimpleNamespace(from_user=SimpleNamespace(id=1), chat=SimpleNamespace(id=-100),
                           text=text, photo=photo, reply=AsyncMock())


@pytest.mark.asyncio
async def test_pet_name_and_image_use_fsm_and_finish():
    handler, player = pet_handler()
    state = SimpleNamespace(set_state=AsyncMock(), clear=AsyncMock())
    await handler.handle_pet_callback(call(), state)
    state.set_state.assert_awaited_once_with(PetStates.waiting_name)
    await handler.process_name_input(message('<New & name>'), state)
    assert player.pet['name'] == '&lt;New &amp; name&gt;'
    assert '&lt;New &amp; name&gt;' in handler.bot.send_message.call_args.args[1]
    state.clear.assert_awaited_once()
    await handler.handle_pet_callback(call('pet_image'), state)
    state.set_state.assert_awaited_with(PetStates.waiting_image)
    await handler.process_image_input(message(None, [SimpleNamespace(file_id='small'), SimpleNamespace(file_id='large')]), state)
    assert player.pet['image_file_id'] == 'large'
    assert state.clear.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('text', [' ', 'A' * 51])
async def test_pet_invalid_name_keeps_input_state(text):
    handler, player = pet_handler()
    before = deepcopy(player.pet)
    state = SimpleNamespace(clear=AsyncMock())
    await handler.process_name_input(message(text), state)
    assert player.pet == before
    state.clear.assert_not_awaited()
    handler.player_service.save_player.assert_not_awaited()


@pytest.mark.asyncio
async def test_pet_photo_filter_accepts_photos_and_ignores_commands():
    handler, _ = pet_handler()
    callback = next(h for h in handler.router.message.handlers if h.callback.__name__ == 'pet_image_input')
    assert (await callback.check(message(None, [SimpleNamespace(file_id='photo')]), raw_state=PetStates.waiting_image.state))[0]
    assert not (await callback.check(message('/cancel'), raw_state=PetStates.waiting_image.state))[0]


@pytest.mark.asyncio
async def test_pet_old_create_button_preserves_existing_pet():
    handler, player = pet_handler()
    original = deepcopy(player.pet)
    await handler.create_pet(call('pet_create'))
    assert player.pet == original
    handler.player_service.save_player.assert_not_awaited()


@pytest.mark.asyncio
async def test_pet_reviving_alive_pet_does_not_spend_revive():
    handler, player = pet_handler()
    await handler.revive_pet(call('pet_revive'))
    assert player.pet_revives_used == 0
    handler.player_service.save_player.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('confirm', [False, True])
async def test_oracle_does_not_bypass_pisunchik_cooldown(confirm):
    handler, player = pet_handler()
    player.last_used = datetime.now(timezone.utc)
    player.pet_ulta_oracle_preview = {'size_change': 5, 'coins_change': 50}
    before = deepcopy(player)
    if confirm:
        await handler.oracle_confirm(call('pet_oracle_yes'))
    else:
        await handler._ulta_oracle(call('pet_ulta'), player)
    assert player == before
    handler.player_service.save_player.assert_not_awaited()


@pytest.mark.parametrize('amount', [-1, float('-inf'), float('inf'), float('nan')])
def test_invalid_spending_never_adds_coins(amount):
    player = Player(1, 'Test', coins=100)
    assert not player.spend_coins(amount)
    assert player.coins == 100


@pytest.mark.asyncio
@pytest.mark.parametrize('rolls', [-1, 0, 101, True, 1.5])
async def test_invalid_roll_count_preserves_coins_and_free_roll(rolls):
    player = Player(1, 'Test', coins=100, pet_ulta_free_roll_pending=True)
    players = SimpleNamespace(save_player=AsyncMock())
    result = await GameService(players).execute_roll_command(player, rolls)
    assert not result['success']
    assert player.coins == 100 and player.pet_ulta_free_roll_pending
    players.save_player.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('characteristic,levels', [('Titan', -1), ('Titan', 0), ('Unknown', 1), ('Gold', 1)])
async def test_invalid_upgrade_preserves_player(characteristic, levels):
    player = Player(1, 'Test', coins=1000, characteristics=['Titan:1'])
    original = deepcopy(player)
    players = SimpleNamespace(save_player=AsyncMock())
    result = await GameService(players).upgrade_characteristic(player, characteristic, levels)
    assert not result['success'] and player == original
    players.save_player.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('command', ['execute_pisunchik_command', 'execute_casino_command', 'execute_roll_command', 'upgrade_characteristic', 'use_masturbator'])
async def test_failed_player_save_never_reports_success(command):
    player = Player(1, 'Test', coins=1000, pisunchik_size=20, characteristics=['Titan:1'], items=['masturbator'])
    players = SimpleNamespace(save_player=AsyncMock(return_value=False), remove_from_cache=AsyncMock())
    args = {'execute_roll_command': [1], 'upgrade_characteristic': ['Titan', 1], 'use_masturbator': [1]}.get(command, [])
    result = await getattr(GameService(players), command)(player, *args)
    assert not result['success']
    players.remove_from_cache.assert_awaited_once_with(1)


def test_stock_company_names_match_exactly():
    stocks, price = StockService().process_stock_transaction({'AB:10', 'A:1'}, 'A', 1, 5, True)
    assert stocks == {'AB:10', 'A:2'} and price == 5


@pytest.mark.parametrize('quantity', [0, -1, 1.5])
def test_invalid_stock_quantities_rejected(quantity):
    with pytest.raises(ValueError):
        StockService().process_stock_transaction({'A:1'}, 'A', quantity, 5, True)


def test_stock_sale_cannot_exceed_holdings():
    with pytest.raises(ValueError, match='Not enough'):
        StockService().process_stock_transaction({'A:1'}, 'A', 2, 5, False)


@pytest.mark.asyncio
async def test_database_uses_configured_port_and_quotes_password(monkeypatch):
    monkeypatch.setattr(Settings, 'DB_CONFIG', {'host': 'localhost', 'port': 5433, 'dbname': 'test', 'user': 'test', 'password': "mock pa'ss"})
    pool = SimpleNamespace(open=AsyncMock())
    factory = Mock(return_value=pool)
    monkeypatch.setattr(db_manager, 'AsyncConnectionPool', factory)
    await db_manager.DatabaseManager().init_pool()
    config = conninfo_to_dict(factory.call_args.kwargs['conninfo'])
    assert config['port'] == '5433' and config['password'] == "mock pa'ss"


@pytest.mark.asyncio
async def test_quiz_schedule_preserves_daily_answers_and_invalid_input_keeps_schedule():
    scheduler = QuizScheduler(AsyncMock(), SimpleNamespace(), SimpleNamespace())
    scheduler.start()
    try:
        assert scheduler.update_schedule(['13:00'])
        jobs = {job.id: job for job in scheduler._scheduler.get_jobs()}
        assert set(jobs) == {'quiz:13:00', 'daily_answers'}
        assert str(jobs['daily_answers'].trigger.timezone) == Settings.ANSWERS_BROADCAST_TIMEZONE
        assert not scheduler.update_schedule(['99:00'])
        assert scheduler.quiz_times == ['13:00']
        assert {job.id for job in scheduler._scheduler.get_jobs()} == set(jobs)
    finally:
        scheduler.stop()


@pytest.mark.asyncio
async def test_manual_quiz_reports_failure_when_no_quiz_sent():
    scheduler = QuizScheduler(AsyncMock(), SimpleNamespace(), SimpleNamespace())
    scheduler.send_quiz_to_chat = AsyncMock(return_value=False)
    assert not (await scheduler.manual_quiz())['success']


@pytest.mark.asyncio
async def test_failed_quiz_send_does_not_mark_question_used():
    trivia = SimpleNamespace(get_unused_question_for_chat=AsyncMock(return_value=(1, {'question': 'Test'})),
                             record_question_sent_to_chat=AsyncMock())
    scheduler = QuizScheduler(AsyncMock(), SimpleNamespace(), trivia)
    scheduler._send_quiz_message = AsyncMock(return_value=None)
    assert not await scheduler.send_quiz_to_chat(-100)
    trivia.record_question_sent_to_chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_health_alert_buttons_are_admin_only(tmp_path):
    handler = HealthAlertHandlers(AsyncMock())
    handler.alert_history_file = str(tmp_path / 'history.json')
    callback = handler.router.callback_query.handlers[0].callback
    query = call('health_resolved_main-bot_process_down')
    query.from_user.id = 0
    await callback(query)
    query.answer.assert_awaited_once_with('Нет доступа.', show_alert=True)
    assert not Path(handler.alert_history_file).exists()


def test_weekly_vote_text_escapes_chat_messages():
    handler = object.__new__(WeeklyHighlightHandlers)
    text = handler._build_vote_text([{'name': '<Name>', 'text': 'x < y & z'}], {})
    assert '&lt;Name&gt;' in text and 'x &lt; y &amp; z' in text


@pytest.mark.asyncio
async def test_stale_registration_approval_preserves_existing_player():
    from handlers.game_handlers import GameHandlers
    player = Player(Settings.MAX_ID, 'Test', coins=1000, pisunchik_size=50)
    players = SimpleNamespace(get_player=AsyncMock(return_value=player), create_player=AsyncMock())
    handler = GameHandlers(AsyncMock(), players, SimpleNamespace())
    callback = next(h.callback for h in handler.router.callback_query.handlers if h.callback.__name__ == 'registration_approve')
    query = call(f'reg_approve_{player.player_id}_New_name')
    query.from_user.id = Settings.ADMIN_IDS[0]
    await callback(query)
    players.create_player.assert_not_awaited()
    assert player.coins == 1000 and player.pisunchik_size == 50


@pytest.mark.parametrize('name', ['А' * 50, '🦅' * 50, 'Test_Name' * 20])
def test_registration_button_respects_telegram_byte_limit(name):
    from utils.helpers import registration_callback_data
    payload = registration_callback_data(741542965, name)
    assert len(payload.encode('utf-8')) <= 64
    assert payload.startswith('reg_approve_741542965_')
    assert name.startswith(payload.split('_', 3)[3])


@pytest.mark.asyncio
async def test_create_player_returns_existing_progress():
    from database.player_service import PlayerService
    service = PlayerService(SimpleNamespace())
    existing = Player(1, 'Test', coins=1000)
    service.get_player = AsyncMock(return_value=existing)
    service.save_player = AsyncMock()
    assert await service.create_player(1, 'New name') is existing
    service.save_player.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_only_save_never_updates_existing_player():
    from database.player_service import PlayerService
    cursor = SimpleNamespace(fetchone=AsyncMock(return_value=(1,)))

    @asynccontextmanager
    async def transaction():
        yield

    conn = SimpleNamespace(execute=AsyncMock(return_value=cursor), transaction=transaction)

    @asynccontextmanager
    async def connection():
        yield conn

    service = PlayerService(SimpleNamespace(connection=connection))
    service._cache_player = AsyncMock()
    assert not await service.save_player(Player(1, 'New'), create_only=True)
    conn.execute.assert_awaited_once()
    assert conn.execute.call_args.args[0].startswith('SELECT player_id')
    service._cache_player.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('sell', [False, True])
@pytest.mark.parametrize('text', ['0', '-1', 'abc'])
async def test_invalid_stock_input_keeps_state_for_retry(sell, text):
    handler = ShopHandlers(AsyncMock(), SimpleNamespace(get_player=AsyncMock()), SimpleNamespace())
    name = 'handle_sell_quantity_selection' if sell else 'handle_quantity_selection'
    callback = next(h.callback for h in handler.router.message.handlers if h.callback.__name__ == name)
    state = SimpleNamespace(get_data=AsyncMock(return_value={}), clear=AsyncMock())
    await callback(message(text), state)
    state.clear.assert_not_awaited()
    handler.player_service.get_player.assert_not_awaited()


@pytest.mark.asyncio
async def test_fractional_stock_price_cannot_create_free_shares():
    from decimal import Decimal
    player = Player(1, 'Test', coins=1)
    cursor = SimpleNamespace(fetchone=AsyncMock(return_value=(Decimal('0.50'),)))

    @asynccontextmanager
    async def connection():
        yield SimpleNamespace(execute=AsyncMock(return_value=cursor))

    players = SimpleNamespace(get_player=AsyncMock(return_value=player), save_player=AsyncMock(return_value=True),
                              db=SimpleNamespace(connection=connection))
    handler = ShopHandlers(AsyncMock(), players, SimpleNamespace())
    callback = next(h.callback for h in handler.router.message.handlers if h.callback.__name__ == 'handle_quantity_selection')
    state = SimpleNamespace(get_data=AsyncMock(return_value={'company': 'A'}), clear=AsyncMock())
    await callback(message('1'), state)
    assert player.coins == 0 and player.player_stocks == ['A:1']
    state.clear.assert_awaited_once()


@pytest.mark.asyncio
async def test_pirate_audio_upload_uses_aiogram_input_file(monkeypatch):
    from handlers import entertainment_handlers
    handler = object.__new__(EntertainmentHandlers)
    handler.bot = AsyncMock()
    monkeypatch.setattr(entertainment_handlers.os, 'listdir', lambda folder: ['test.mp3'])
    await handler.send_pirate_song(message())
    upload = handler.bot.send_audio.call_args.args[1]
    assert isinstance(upload, FSInputFile) and str(upload.path).endswith('test.mp3')


@pytest.mark.asyncio
async def test_quiz_refill_runs_blocking_generation_in_worker_thread():
    import threading
    from services.trivia_service import Question
    current_thread = threading.get_ident()
    called_threads = []

    def generate(count, existing):
        called_threads.append(threading.get_ident())
        return [Question(question='Test?', correct_answer='Yes', wrong_answers=['No'])]

    trivia = SimpleNamespace(get_recent_question_texts=AsyncMock(return_value=[]),
                             generate_questions_batch_with_ai=generate,
                             is_duplicate_question=AsyncMock(return_value=False),
                             save_question_to_database=AsyncMock(return_value=1))
    scheduler = QuizScheduler(AsyncMock(), SimpleNamespace(), trivia)
    assert (await scheduler.refill_question_pool(1))['added'] == 1
    assert called_threads and called_threads[0] != current_thread


@pytest.mark.asyncio
async def test_unsaved_trivia_question_is_not_sent_as_success():
    from services.trivia_service import Question, TriviaService
    handler = object.__new__(TriviaService)
    handler.generate_question_with_ai = Mock(return_value=Question(question='Test?', correct_answer='Yes', wrong_answers=['No']))
    handler.is_duplicate_question = AsyncMock(return_value=False)
    handler.save_question_to_database = AsyncMock(return_value=None)
    assert not (await handler.generate_question('1', 'Test'))['success']


@pytest.mark.asyncio
async def test_court_cards_escape_special_characters():
    from handlers.court_handlers import CourtHandlers
    handler = object.__new__(CourtHandlers)
    handler.bot = AsyncMock()
    await handler._send_cards_dm(1, 1, 'prosecutor', ['a < b & c'], ['<partner>'], 'lawyer')
    text = handler.bot.send_message.call_args.args[1]
    assert 'a &lt; b &amp; c' in text and '&lt;partner&gt;' in text


@pytest.mark.asyncio
async def test_failed_cache_refresh_removes_stale_player_cache():
    from database.player_service import PlayerService
    redis = SimpleNamespace(set=AsyncMock(side_effect=RuntimeError('Cache full')), delete=AsyncMock())
    service = PlayerService(SimpleNamespace(), redis=redis)
    await service._cache_player(Player(1, 'Test'))
    redis.delete.assert_awaited_once_with('player:1')


@pytest.mark.parametrize('fresh_ulta', [False, True])
def test_new_casino_day_keeps_only_fresh_ulta_bonus(fresh_ulta):
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    player = Player(1, 'Test', casino_last_used=now - timedelta(days=2), casino_usage_count=3,
                    pet_casino_extra_spins=2,
                    pet_ulta_used_date=now - timedelta(hours=1 if fresh_ulta else 25))
    assert GameService(SimpleNamespace()).can_use_casino(player)[0]
    assert player.casino_usage_count == 0
    assert player.pet_casino_extra_spins == (2 if fresh_ulta else 0)


@pytest.mark.asyncio
async def test_weekly_close_serializes_overlapping_requests():
    import asyncio
    handler = object.__new__(WeeklyHighlightHandlers)
    handler._close_locks = {}
    active = 0
    peak = 0

    async def close(chat_id):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1

    handler._close_weekly_highlight = close
    await asyncio.gather(*(handler.close_weekly_highlight(-100) for _ in range(10)))
    assert peak == 1


@pytest.mark.asyncio
async def test_duplicate_statuette_is_not_charged():
    player = Player(1, 'Test', coins=100, statuetki=['Pudginio'])
    players = SimpleNamespace(get_player=AsyncMock(return_value=player), save_player=AsyncMock())
    handler = ShopHandlers(AsyncMock(), players, SimpleNamespace())
    handler.statuetki_data = {'prices': {'Pudginio': 10}}
    callback = next(h.callback for h in handler.router.callback_query.handlers if h.callback.__name__ == 'confirm_statuetka_purchase')
    query = call('statuetka_confirm_Pudginio')
    query.message.edit_reply_markup = AsyncMock()
    await callback(query)
    assert player.coins == 100 and player.statuetki == ['Pudginio']
    players.save_player.assert_not_awaited()


@pytest.mark.asyncio
async def test_shop_does_not_report_failed_save_as_purchase():
    player = Player(1, 'Test', coins=100)
    players = SimpleNamespace(get_player=AsyncMock(return_value=player), save_player=AsyncMock(return_value=False))
    game = SimpleNamespace(calculate_shop_discount=lambda player, price: price)
    handler = ShopHandlers(AsyncMock(), players, game)
    handler.shop_data = {'prices': {'test': 10}}
    callback = next(h.callback for h in handler.router.callback_query.handlers if h.callback.__name__ == 'confirm_shop_purchase')
    query = call('buy_confirm_test')
    query.message.edit_reply_markup = AsyncMock()
    await callback(query)
    assert 'Не удалось сохранить покупку' in handler.bot.send_message.call_args.args[1]
    assert handler.bot.send_message.await_count == 1
