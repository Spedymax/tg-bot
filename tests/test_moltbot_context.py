"""Tests for moltbot context building helpers."""
import sys, os, importlib.util

# Load moltbot_handlers directly to avoid handlers/__init__.py pulling in psycopg
_src = os.path.join(os.path.dirname(__file__), '..', 'src')
sys.path.insert(0, _src)

# Stub out heavy dependencies before importing the module
import types
for _mod in ('psycopg', 'psycopg_pool', 'google.generativeai'):
    sys.modules.setdefault(_mod, types.ModuleType(_mod))

_spec = importlib.util.spec_from_file_location(
    "handlers.moltbot_handlers",
    os.path.join(_src, "handlers", "moltbot_handlers.py"),
)
_moltbot_mod = importlib.util.module_from_spec(_spec)
sys.modules["handlers.moltbot_handlers"] = _moltbot_mod
_spec.loader.exec_module(_moltbot_mod)
MoltbotHandlers = _moltbot_mod.MoltbotHandlers

import pytest
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import AsyncMock, MagicMock, patch

CPH = ZoneInfo("Europe/Copenhagen")


class TestTimestampFormatting:
    def test_utc_to_copenhagen(self):
        dt = datetime(2026, 3, 14, 15, 30, 0, tzinfo=ZoneInfo("UTC"))
        assert MoltbotHandlers._format_ts(dt) == "[16:30 14.03]"

    def test_naive_datetime_treated_as_utc(self):
        dt = datetime(2026, 3, 14, 15, 30, 0)
        assert MoltbotHandlers._format_ts(dt) == "[16:30 14.03]"

    def test_summer_time_cest(self):
        dt = datetime(2026, 7, 1, 12, 0, 0, tzinfo=ZoneInfo("UTC"))
        assert MoltbotHandlers._format_ts(dt) == "[14:00 01.07]"

    def test_midnight_rolls_date(self):
        dt = datetime(2026, 3, 14, 23, 30, 0, tzinfo=ZoneInfo("UTC"))
        assert MoltbotHandlers._format_ts(dt) == "[00:30 15.03]"

    def test_none_returns_empty(self):
        assert MoltbotHandlers._format_ts(None) == ""


class TestGetRecentGroupMessages:
    @pytest.mark.asyncio
    async def test_messages_include_timestamps(self):
        db = AsyncMock()
        # DB returns newest-first; code reverses to get chronological order
        db.execute_query = AsyncMock(return_value=[
            ("Юра", "здарова", datetime(2026, 3, 14, 15, 5, 0)),
            ("Богдан", "привет", datetime(2026, 3, 14, 15, 0, 0)),
        ])

        with patch.object(MoltbotHandlers, '__init__', lambda self, *a, **kw: None):
            handler = MoltbotHandlers.__new__(MoltbotHandlers)
            handler.db = db
            handler._history_reset_time = {}

            result = await handler._get_recent_group_messages(limit=50)

        assert len(result) == 2
        assert "[16:00 14.03] Богдан: привет" in result[0]
        assert "[16:05 14.03] Юра: здарова" in result[1]

    @pytest.mark.asyncio
    async def test_null_timestamp_handled(self):
        db = AsyncMock()
        db.execute_query = AsyncMock(return_value=[
            ("Юра", "old msg", None),
        ])

        with patch.object(MoltbotHandlers, '__init__', lambda self, *a, **kw: None):
            handler = MoltbotHandlers.__new__(MoltbotHandlers)
            handler.db = db
            handler._history_reset_time = {}

            result = await handler._get_recent_group_messages(limit=50)

        assert len(result) == 1
        assert "Юра: old msg" in result[0]


class TestAskMoltbotContext:
    @pytest.mark.asyncio
    async def test_history_block_includes_time_header_and_instruction(self):
        with patch.object(MoltbotHandlers, '__init__', lambda self, *a, **kw: None):
            handler = MoltbotHandlers.__new__(MoltbotHandlers)
            handler._user_key_suffix = {}

            captured = {}
            async def capture_openclaw(content, user_key, model="openclaw:main"):
                captured['content'] = content
                return "test reply"
            handler._call_openclaw = capture_openclaw

            with patch.object(_moltbot_mod, '_load_chat_summary', return_value=''):
                await handler._ask_moltbot(
                    "Юра", "привет", "групповой чат", "key",
                    history=["[16:00 14.03] Богдан: тест"]
                )

            content = captured['content']
            assert "[Сейчас:" in content
            assert "Copenhagen]" in content
            assert "фоновый контекст" in content
            assert "Не поднимай старые темы" in content
