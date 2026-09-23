"""Tests for the live-switchable reasoning depth (/reasoning) and its idle auto-reset."""
import sys, os, importlib.util, types, json
from datetime import datetime, timezone, timedelta

_src = os.path.join(os.path.dirname(__file__), '..', 'src')
sys.path.insert(0, _src)
for _mod in ('psycopg', 'psycopg_pool', 'google.generativeai'):
    sys.modules.setdefault(_mod, types.ModuleType(_mod))
_spec = importlib.util.spec_from_file_location(
    "handlers.moltbot_handlers", os.path.join(_src, "handlers", "moltbot_handlers.py"))
_m = importlib.util.module_from_spec(_spec)
sys.modules["handlers.moltbot_handlers"] = _m
_spec.loader.exec_module(_m)

import pytest
from unittest.mock import patch


def _handler(tmp_path):
    with patch.object(_m.MoltbotHandlers, '__init__', lambda self, *a, **kw: None):
        h = _m.MoltbotHandlers.__new__(_m.MoltbotHandlers)
    h._history_reset_time = {}
    h._reasoning_effort = _m.REASONING_DEFAULT
    h._reasoning_last_activity = None
    return h


class TestParse:
    @pytest.mark.parametrize("raw,expected", [
        ("high", "high"), ("HIGH", "high"), (" хай ", "high"), ("макс", "high"),
        ("medium", "medium"), ("мид", "medium"),
        ("low", "low"), ("лоу", "low"), ("выкл", "minimal"), ("minimal", "minimal"), ("мало", "minimal"),
        ("turbo", None), ("", None), (None, None),
    ])
    def test_aliases(self, raw, expected):
        assert _m._parse_reasoning_level(raw) == expected


class TestAutoReset:
    def test_default_is_minimal(self, tmp_path):
        h = _handler(tmp_path)
        with patch.object(_m, 'STATE_PATH', str(tmp_path / 's.json')):
            assert h._current_reasoning_effort() == "minimal"

    def test_high_sticks_while_chat_active(self, tmp_path):
        h = _handler(tmp_path)
        with patch.object(_m, 'STATE_PATH', str(tmp_path / 's.json')):
            h._set_reasoning_effort("high")
            h._reasoning_last_activity = datetime.now(timezone.utc) - timedelta(hours=2, minutes=59)
            assert h._current_reasoning_effort() == "high"

    def test_high_resets_after_three_idle_hours(self, tmp_path):
        h = _handler(tmp_path)
        with patch.object(_m, 'STATE_PATH', str(tmp_path / 's.json')):
            h._set_reasoning_effort("high")
            h._reasoning_last_activity = datetime.now(timezone.utc) - timedelta(hours=3, seconds=1)
            assert h._current_reasoning_effort() == "minimal"
            # and the reset is persisted
            assert json.load(open(tmp_path / 's.json'))["reasoning_effort"] == "minimal"

    def test_activity_pushes_reset_forward(self, tmp_path):
        h = _handler(tmp_path)
        with patch.object(_m, 'STATE_PATH', str(tmp_path / 's.json')):
            h._set_reasoning_effort("high")
            h._reasoning_last_activity = datetime.now(timezone.utc) - timedelta(hours=2, minutes=50)
            h._touch_reasoning_activity()  # someone wrote in chat
            h._reasoning_last_activity -= timedelta(hours=2, minutes=50)  # another 2h50 pass
            assert h._current_reasoning_effort() == "high"

    def test_reset_in_countdown(self, tmp_path):
        h = _handler(tmp_path)
        with patch.object(_m, 'STATE_PATH', str(tmp_path / 's.json')):
            assert h._reasoning_reset_in() is None
            h._set_reasoning_effort("medium")
            left = h._reasoning_reset_in()
            assert timedelta(hours=2, minutes=59) < left <= timedelta(hours=3)


class TestPersistence:
    def test_roundtrip_through_state_file(self, tmp_path):
        h = _handler(tmp_path)
        with patch.object(_m, 'STATE_PATH', str(tmp_path / 's.json')):
            h._set_reasoning_effort("high")
            h2 = _handler(tmp_path)
            h2._load_state()
            assert h2._reasoning_effort == "high"
            assert h2._reasoning_last_activity is not None

    def test_bad_level_in_state_ignored(self, tmp_path):
        p = tmp_path / 's.json'
        p.write_text(json.dumps({"history_reset_time": {}, "reasoning_effort": "ultra"}))
        h = _handler(tmp_path)
        with patch.object(_m, 'STATE_PATH', str(p)):
            h._load_state()
        assert h._reasoning_effort == "minimal"

    def test_old_saved_low_default_migrates_but_new_choice_sticks(self, tmp_path):
        p = tmp_path / 's.json'
        p.write_text(json.dumps({"history_reset_time": {}, "reasoning_effort": "low"}))
        h = _handler(tmp_path)
        with patch.object(_m, 'STATE_PATH', str(p)):
            h._load_state()
        assert h._reasoning_effort == "minimal"          # pre-2026-09-23 default, not a choice
        p.write_text(json.dumps({"history_reset_time": {}, "reasoning_effort": "low",
                                 "reasoning_default_minimal": True}))
        with patch.object(_m, 'STATE_PATH', str(p)):
            h._load_state()
        assert h._reasoning_effort == "low"              # chosen after the switch: kept

    def test_set_rejects_unknown(self, tmp_path):
        h = _handler(tmp_path)
        with pytest.raises(ValueError):
            h._set_reasoning_effort("ultra")
