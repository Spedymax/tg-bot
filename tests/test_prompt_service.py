"""Tests for PromptService cache and validation logic.

Uses mocked DB connection — no real Postgres needed.
"""
import sys, os, types
import pytest

_src = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, _src)

# Stub heavy deps before importing service
for _mod in ("psycopg", "psycopg_pool"):
    sys.modules.setdefault(_mod, types.ModuleType(_mod))

# psycopg_pool needs AsyncConnectionPool attribute
_pool_mod = sys.modules["psycopg_pool"]
if not hasattr(_pool_mod, "AsyncConnectionPool"):
    _pool_mod.AsyncConnectionPool = type("AsyncConnectionPool", (), {})

from services.prompt_service import PromptService  # noqa: E402


class _FakeCursor:
    def __init__(self, rows=None, description=None):
        self._rows = rows or []
        self.description = description or []

    async def fetchone(self):
        return self._rows[0] if self._rows else None

    async def fetchall(self):
        return list(self._rows)


class _FakeConn:
    def __init__(self):
        self.executed: list[tuple] = []
        self._next_response: _FakeCursor = _FakeCursor()

    async def execute(self, query, params=None):
        self.executed.append((query, params))
        return self._next_response


class _FakeDB:
    """Minimal db_manager stub with async-context-manager `.connection()`."""

    def __init__(self):
        self.conn = _FakeConn()

    def connection(self):
        db = self

        class _Ctx:
            async def __aenter__(self_inner):
                return db.conn

            async def __aexit__(self_inner, *args):
                return False

        return _Ctx()


@pytest.mark.asyncio
async def test_set_identity_updates_cache():
    db = _FakeDB()
    svc = PromptService(db)
    db.conn._next_response = _FakeCursor(rows=[(42,)], description=[("id",)])
    new_id = await svc.set_identity("new content", author_id=1, author_name="me")
    assert new_id == 42
    assert svc._cached_identity == "new content"
    assert svc._cache_version_id == 42


@pytest.mark.asyncio
async def test_get_current_identity_uses_cache():
    db = _FakeDB()
    svc = PromptService(db)
    svc._cached_identity = "cached"
    result = await svc.get_current_identity()
    assert result == "cached"
    assert db.conn.executed == []


@pytest.mark.asyncio
async def test_get_current_identity_fallback_on_db_error():
    db = _FakeDB()
    svc = PromptService(db)

    async def boom(*args, **kwargs):
        raise RuntimeError("db down")

    db.conn.execute = boom
    result = await svc.get_current_identity()
    assert isinstance(result, str) and len(result) > 0


@pytest.mark.asyncio
async def test_rollback_to_missing_version_returns_none():
    db = _FakeDB()
    svc = PromptService(db)
    db.conn._next_response = _FakeCursor(rows=[])
    result = await svc.rollback_to(999, author_id=1, author_name="me")
    assert result is None


@pytest.mark.asyncio
async def test_revoke_refuses_bootstrap_admin():
    db = _FakeDB()
    svc = PromptService(db)
    db.conn._next_response = _FakeCursor(rows=[(None,)])
    ok, msg = await svc.revoke(123)
    assert ok is False
    assert "bootstrap" in msg
