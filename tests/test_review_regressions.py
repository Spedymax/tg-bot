import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from config.settings import Settings
from handlers.shop_handlers import ShopHandlers
from handlers.trivia_handlers import TriviaHandlers
from services.dungeon_service import DungeonService
from services import dungeon_logic as logic


def initial_run():
    room = {'type': 'fight', 'index': 0, 'balance_version': 2,
            'enemy': {'name': 'Test', 'emoji': '🗿', 'hp': 1, 'max_hp': 1, 'atk': 1}}
    return logic.new_run('review', [room])


class RunDatabase:
    def __init__(self, state=None):
        self.state = deepcopy(state)
        self.lock = asyncio.Lock()
        self.fail_write = False

    @asynccontextmanager
    async def connection(self):
        yield self

    @asynccontextmanager
    async def transaction(self):
        async with self.lock:
            before = deepcopy(self.state)
            try:
                yield
            except BaseException:
                self.state = before
                raise

    async def execute(self, query, params):
        await asyncio.sleep(0)
        if query.startswith('SELECT state'):
            row = (deepcopy(self.state),) if self.state is not None else None
            return SimpleNamespace(fetchone=AsyncMock(return_value=row))
        if query.startswith('INSERT INTO dungeon_runs'):
            if self.fail_write:
                raise RuntimeError('Database unavailable')
            if self.state is None or 'DO NOTHING' not in query:
                self.state = json.loads(params[3])
        return SimpleNamespace(fetchone=AsyncMock(return_value=None))

    async def execute_query_strict(self, query, params):
        if query.startswith('SELECT state'):
            return [(deepcopy(self.state),)] if self.state is not None else []
        await self.execute(query, params)
        return None


@pytest.mark.asyncio
async def test_dungeon_parallel_actions_clear_room_only_once():
    db = RunDatabase(initial_run())
    svc = DungeonService(db, {})
    svc._tables_ready = True
    first, second = await asyncio.gather(svc.act(1, 'Player', 'attack'), svc.act(1, 'Player', 'attack'))
    assert sum(result[1]['rooms_delta'] for result in [first, second]) == 1
    assert db.state['rooms_cleared'] == 1
    assert len(db.state['history']) == 1


@pytest.mark.asyncio
async def test_dungeon_opening_stale_tab_preserves_progress():
    progressed = initial_run()
    logic.apply_action(progressed, 'attack', {})
    db = RunDatabase(progressed)
    svc = DungeonService(db, {})
    svc._tables_ready = True
    original_get = svc.get_run
    reads = 0

    async def stale_first_read(*args):
        nonlocal reads
        reads += 1
        return None if reads == 1 else await original_get(*args)

    svc.get_run = stale_first_read
    svc.get_or_create_daily = AsyncMock(return_value=initial_run()['rooms'])
    state = await svc.get_or_create_run(date(2026, 9, 18), 1, 'Player')
    assert state == progressed == db.state


@pytest.mark.asyncio
async def test_dungeon_failed_save_does_not_report_success_or_commit_action():
    original = initial_run()
    db = RunDatabase(original)
    db.fail_write = True
    svc = DungeonService(db, {})
    svc._tables_ready = True
    with pytest.raises(RuntimeError, match='Database unavailable'):
        await svc.act(1, 'Player', 'attack')
    assert db.state == original


@pytest.mark.asyncio
@pytest.mark.parametrize('restored', [False, True])
async def test_trivia_existing_answer_rejected_before_rewards(restored):
    svc = object.__new__(TriviaHandlers)
    user_id = 741542965
    responses = {user_id: 'Player ✅'}
    if restored:
        responses = json.loads(json.dumps(responses))
    svc.question_messages = {} if restored else {10: {'players_responses': responses, 'options': ['Yes']}}
    svc.load_question_state_from_db = AsyncMock(return_value={'players_responses': responses, 'options': ['Yes']})
    svc.player_service = SimpleNamespace(get_player=AsyncMock(), save_player=AsyncMock())
    call = SimpleNamespace(message=SimpleNamespace(message_id=10),
                           from_user=SimpleNamespace(id=user_id, first_name='Player'),
                           data='answer_0', answer=AsyncMock())
    await svc.handle_answer_callback(call)
    call.answer.assert_awaited_once_with('Вы уже ответили на этот вопрос')
    svc.player_service.get_player.assert_not_awaited()
    svc.player_service.save_player.assert_not_awaited()


@pytest.mark.asyncio
async def test_stocks_update_non_admin_is_rejected_without_database_access():
    players = SimpleNamespace(db=SimpleNamespace(connection=AsyncMock()))
    svc = ShopHandlers(AsyncMock(), players, SimpleNamespace())
    callback = next(h.callback for h in svc.router.message.handlers if h.callback.__name__ == 'stocks_update')
    message = SimpleNamespace(from_user=SimpleNamespace(id=0), chat=SimpleNamespace(id=-100))
    assert message.from_user.id not in Settings.ADMIN_IDS
    await callback(message)
    assert 'Вы не админ' in svc.bot.send_message.call_args.args[1]
    players.db.connection.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('database_decimal', [False, True])
async def test_stocks_update_supports_numeric_database_prices(monkeypatch, database_decimal):
    from decimal import Decimal
    from handlers import shop_handlers
    price = Decimal('100.00') if database_decimal else 100.0
    updated = []

    async def execute(query, params=None):
        if query.startswith('UPDATE'):
            updated.append(params)
            return SimpleNamespace()
        return SimpleNamespace(fetchall=AsyncMock(return_value=[('Test', updated[0][0] if updated else price)]))

    conn = SimpleNamespace(execute=execute, commit=AsyncMock())

    @asynccontextmanager
    async def connection():
        yield conn

    players = SimpleNamespace(db=SimpleNamespace(connection=connection))
    svc = ShopHandlers(AsyncMock(), players, SimpleNamespace())
    callback = next(h.callback for h in svc.router.message.handlers if h.callback.__name__ == 'stocks_update')
    monkeypatch.setattr(shop_handlers.random, 'uniform', lambda low, high: 0.1)
    await callback(SimpleNamespace(from_user=SimpleNamespace(id=Settings.ADMIN_IDS[0]),
                                   chat=SimpleNamespace(id=-100)))
    assert updated == [(Decimal('110.00'), 'Test')]
    assert 'Test: 110.00 BTC' in svc.bot.send_message.call_args_list[0].args[1]
    assert svc.bot.send_message.await_count == 2


class WordleDatabase(RunDatabase):
    async def execute(self, query, params):
        await asyncio.sleep(0)
        if query.startswith('SELECT attempts'):
            return SimpleNamespace(fetchone=AsyncMock(return_value=deepcopy(self.state)))
        if query.startswith('UPDATE wordle_games'):
            if self.fail_write:
                raise RuntimeError('Database unavailable')
            self.state = [params[0], json.loads(params[1]), params[2], params[3]]
        return SimpleNamespace()


@pytest.mark.asyncio
async def test_wordle_parallel_guesses_preserve_both_attempts():
    from services.wordle_service import record_guess
    db = WordleDatabase([0, [], False, False])
    results = await asyncio.gather(*(record_guess(db, date(2026, 9, 18), 1, 'Player', guess, 'crane')
                                    for guess in ['apple', 'cigar']))
    assert db.state[0] == 2
    assert {g['guess'] for g in db.state[1]} == {'apple', 'cigar'}
    assert all(not already for _, already in results)


@pytest.mark.asyncio
async def test_wordle_stale_double_submit_does_not_use_another_attempt():
    from services.wordle_service import record_guess
    db = WordleDatabase([0, [], False, False])
    results = await asyncio.gather(*(record_guess(
        db, date(2026, 9, 18), 1, 'Player', 'apple', 'crane', 0) for _ in range(2)))
    assert db.state[0] == 1
    assert len(db.state[1]) == 1
    assert sum(bool(game.get('duplicate')) for game, _ in results) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('win', [False, True])
async def test_wordle_parallel_finish_reports_only_one_reward(win):
    from services.wordle_service import record_guess
    previous = [] if win else [{'guess': 'apple', 'marks': ['absent'] * 5}] * 5
    db = WordleDatabase([len(previous), previous, False, False])
    guess = 'crane' if win else 'apple'
    results = await asyncio.gather(*(record_guess(db, date(2026, 9, 18), 1, 'Player', guess, 'crane')
                                    for _ in range(10)))
    assert sum(not already and game['finished'] for game, already in results) == 1
    assert db.state[0] == (1 if win else 6)
    assert db.state[2:] == [win, True]


@pytest.mark.asyncio
async def test_wordle_failed_save_rolls_back_attempt():
    from services.wordle_service import record_guess
    original = [0, [], False, False]
    db = WordleDatabase(original)
    db.fail_write = True
    with pytest.raises(RuntimeError, match='Database unavailable'):
        await record_guess(db, date(2026, 9, 18), 1, 'Player', 'crane', 'crane')
    assert db.state == original


@pytest.mark.asyncio
async def test_wordle_invalid_word_does_not_consume_attempt():
    from services.wordle_service import record_guess
    original = [0, [], False, False]
    db = WordleDatabase(original)
    with pytest.raises(ValueError, match='not_a_word'):
        await record_guess(db, date(2026, 9, 18), 1, 'Player', 'aaaaa', 'crane')
    assert db.state == original
