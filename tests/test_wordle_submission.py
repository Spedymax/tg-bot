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
from services.wordle_service import record_guess


class WordleDatabase:
    def __init__(self):
        self.state = [0, [], False, False]
        self.lock = asyncio.Lock()

    @asynccontextmanager
    async def connection(self):
        yield self

    @asynccontextmanager
    async def transaction(self):
        async with self.lock:
            yield

    async def execute(self, query, params):
        await asyncio.sleep(0)
        if query.startswith('SELECT attempts'):
            return SimpleNamespace(fetchone=AsyncMock(return_value=deepcopy(self.state)))
        if query.startswith('UPDATE wordle_games'):
            self.state = [params[0], json.loads(params[1]), params[2], params[3]]
        return SimpleNamespace()


@pytest.mark.asyncio
async def test_double_submit_uses_one_attempt():
    db = WordleDatabase()
    results = await asyncio.gather(*(record_guess(
        db, date(2026, 9, 18), 1, 'Player', 'apple', 'crane', 0) for _ in range(2)))
    assert db.state[0] == 1
    assert len(db.state[1]) == 1
    assert sum(bool(game.get('duplicate')) for game, _ in results) == 1


@pytest.mark.asyncio
async def test_stale_tab_returns_current_guesses_without_consuming_attempt():
    db = WordleDatabase()
    await record_guess(db, date(2026, 9, 18), 1, 'Player', 'apple', 'crane', 0)
    game, finished = await record_guess(db, date(2026, 9, 18), 1, 'Player', 'cigar', 'crane', 0)
    assert not finished
    assert game['duplicate']
    assert game['guesses'] == db.state[1]
    assert db.state[0] == 1
