"""Roadmap P0: memory hygiene, date grounding, overlay framing and LLM telemetry."""
import sys, os, importlib.util, types, json
from datetime import datetime, timezone

_src = os.path.join(os.path.dirname(__file__), '..', 'src')
sys.path.insert(0, _src)
for _mod in ('psycopg', 'psycopg_pool', 'google.generativeai'):
    sys.modules.setdefault(_mod, types.ModuleType(_mod))

_spec = importlib.util.spec_from_file_location(
    "handlers.moltbot_handlers",
    os.path.join(_src, "handlers", "moltbot_handlers.py"),
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["handlers.moltbot_handlers"] = _mod
_spec.loader.exec_module(_mod)
MoltbotHandlers = _mod.MoltbotHandlers

from services import llm_trace
from services.context_builder import ContextBuilder, OVERLAY_HEADER

import pytest
from unittest.mock import AsyncMock, patch

CHAT = -1001294162183


@pytest.fixture
def memory_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(_mod, "CHAT_SUMMARY_PATH", str(tmp_path / "chat-summary.md"))
    monkeypatch.setattr(_mod, "CHAT_LORE_PATH", str(tmp_path / "chat-lore.md"))
    monkeypatch.setattr(_mod, "CHAT_LORE_CANDIDATES_PATH", str(tmp_path / "chat-lore-candidates.md"))
    return tmp_path


def _handler(db=None):
    h = MoltbotHandlers.__new__(MoltbotHandlers)
    h.db = db or AsyncMock()
    h._last_summary_update = {}
    h._memory_cursor = {}
    h._history_reset_time = {}
    return h


# ── date grounding & overlays ────────────────────────────────────────────────

def test_clock_text_uses_kyiv_date_and_cet_time():
    now = datetime(2026, 9, 22, 21, 30, tzinfo=timezone.utc)
    text = MoltbotHandlers._clock_text(now)
    assert text.startswith("среда, 23 сентября 2026, 00:30 по Киеву")
    assert "23:30" in text


def test_builder_puts_clock_in_system_and_frames_overlay():
    snapshot = ContextBuilder({"Jarvis"}).build(
        identity="ID", hard_rules="", chat_context="", summary="", lore="",
        history=[], sender_name="Юра", user_text="какое сегодня число",
        post_prompt="POST", clock="вторник, 22 сентября 2026", overlay="ТЫ ПУДЖИНИО",
    )
    messages = snapshot.as_messages()
    assert "вторник, 22 сентября 2026" in messages[0]["content"]
    post = messages[-2]["content"]
    assert post.startswith("POST")
    assert OVERLAY_HEADER in post and "ТЫ ПУДЖИНИО" in post
    assert post.index("ТЫ ПУДЖИНИО") < post.index("не отрицай")
    assert snapshot.section_chars["overlay"] == len("ТЫ ПУДЖИНИО")


def test_builder_without_overlay_keeps_plain_post_prompt():
    snapshot = ContextBuilder({"Jarvis"}).build(
        identity="ID", hard_rules="", chat_context="", summary="", lore="",
        history=[], sender_name="Юра", user_text="х", post_prompt="POST",
    )
    assert snapshot.as_messages()[-2] == {"role": "system", "content": "POST"}


# ── self-reinforcing memory ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_summary_uses_only_human_messages_and_not_previous_summary(memory_dir, monkeypatch):
    (memory_dir / "chat-summary.md").write_text("СТАРЫЙ ВНУТРЯК ПРО ЛИСЁНКА", encoding="utf-8")
    db = AsyncMock()
    db.execute_query = AsyncMock(return_value=[("Юра", "го в доту в субботу", datetime(2026, 9, 22, 12))])
    h = _handler(db)
    captured = {}

    async def fake_post(payload, timeout):
        captured["prompt"] = payload["messages"][1]["content"]
        return {"choices": [{"message": {"content": "== ЧТО ПРОИСХОДИТ СЕЙЧАС ==\nЮра зовёт в доту в субботу 26.09\n== ЖИВЫЕ ВНУТРЯКИ =="}}]}

    h._together_post = fake_post
    monkeypatch.setattr(_mod.Settings, "TOGETHER_API_KEY", "x", raising=False)
    ok, detail = await h._update_summary(CHAT)

    assert ok, detail
    sql = db.execute_query.await_args.args[0]
    assert "user_id <> 0" in sql
    assert "СТАРЫЙ ВНУТРЯК" not in captured["prompt"]
    assert "го в доту" in captured["prompt"]
    assert "Юра зовёт" in (memory_dir / "chat-summary.md").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_pin_proposals_become_candidates_not_lore(memory_dir, monkeypatch):
    db = AsyncMock()
    db.execute_query = AsyncMock(return_value=[("Юра", "эдик опять", datetime(2026, 9, 22, 12))])
    h = _handler(db)
    h._together_post = AsyncMock(return_value={"choices": [{"message": {"content":
        "== ЧТО ПРОИСХОДИТ СЕЙЧАС ==\nчто-то происходит, достаточно длинно для сохранения\n"
        "== НА ЗАКРЕП ==\n- Лисёнок — вечный спутник Джарвиса"}}]})
    monkeypatch.setattr(_mod.Settings, "TOGETHER_API_KEY", "x", raising=False)

    ok, detail = await h._update_summary(CHAT)

    assert ok and "кандидатов в закреп: 1" in detail
    assert not (memory_dir / "chat-lore.md").exists()
    assert _mod._lore_candidate_lines(CHAT) == ["Лисёнок — вечный спутник Джарвиса"]
    assert "НА ЗАКРЕП" not in (memory_dir / "chat-summary.md").read_text(encoding="utf-8")


def test_propose_lore_dedups_against_existing_lore_and_queue(memory_dir):
    _mod._save_lore_lines(["Эдик Коваленко — торсионные генераторы"], CHAT)
    h = _handler()
    assert h._propose_lore("- Коваленко снова продаёт генераторы", CHAT) == []
    assert h._propose_lore("- Кубы и поршень — вечный спор", CHAT) == ["Кубы и поршень — вечный спор"]
    assert h._propose_lore("- Кубы и поршень — вечный спор", CHAT) == []


@pytest.mark.asyncio
async def test_summary_failure_reports_and_schedules_retry_soon(memory_dir):
    db = AsyncMock()
    db.execute_query = AsyncMock(return_value=[])
    h = _handler(db)
    ok, detail = await h._update_summary(CHAT)
    assert not ok and "нет новых" in detail
    retry_at = h._last_summary_update[CHAT] + _mod.timedelta(hours=_mod.SUMMARY_UPDATE_HOURS)
    minutes_left = (retry_at - datetime.now(timezone.utc)).total_seconds() / 60
    assert 50 < minutes_left <= 60


@pytest.mark.asyncio
async def test_memory_cursor_limits_rebuild_window(memory_dir):
    db = AsyncMock()
    db.execute_query = AsyncMock(return_value=[])
    h = _handler(db)
    cursor = datetime(2026, 9, 22, 18, tzinfo=timezone.utc)
    h._memory_cursor[CHAT] = cursor
    await h._update_summary(CHAT)
    params = db.execute_query.await_args.args[1]
    assert params[2] == cursor and params[3] == cursor


def test_atomic_write_leaves_no_temp_file(tmp_path):
    path = tmp_path / "x" / "m.md"
    _mod._atomic_write(str(path), "hello")
    assert path.read_text(encoding="utf-8") == "hello"
    assert not (tmp_path / "x" / "m.md.tmp").exists()


# ── telemetry ────────────────────────────────────────────────────────────────

def test_provider_ids_are_opaque_and_change_with_context_epoch():
    h = _handler()
    first = h._provider_ids(CHAT)
    assert str(CHAT) not in json.dumps(first)
    assert first["user"] == llm_trace.opaque_id("chat", CHAT)
    h._history_reset_time[CHAT] = datetime(2026, 9, 22, tzinfo=timezone.utc)
    second = h._provider_ids(CHAT)
    assert second["user"] == first["user"]
    assert second["session_id"] != first["session_id"]


def test_apply_response_sums_usage_across_tool_rounds():
    attempt = llm_trace.Attempt(provider="openrouter", model="x-ai/grok")
    llm_trace.apply_response(attempt, {"id": "gen-1", "provider": "xAI", "model": "x-ai/grok-4.6",
                                       "usage": {"prompt_tokens": 100, "completion_tokens": 5, "cost": 0.001}})
    llm_trace.apply_response(attempt, {"id": "gen-2", "usage": {"prompt_tokens": 150, "completion_tokens": 20, "cost": 0.002}})
    assert (attempt.prompt_tokens, attempt.completion_tokens) == (250, 25)
    assert attempt.cost_usd == pytest.approx(0.003)
    assert attempt.upstream == "xAI" and attempt.request_id == "gen-2"


@pytest.mark.asyncio
async def test_routed_reply_records_fallback_chain_and_persists(monkeypatch):
    monkeypatch.setattr(_mod.Settings, "OPENROUTER_API_KEY", "x", raising=False)
    monkeypatch.setattr(_mod.Settings, "TOGETHER_API_KEY", "x", raising=False)
    h = _handler()
    persisted = []
    monkeypatch.setattr(llm_trace, "persist_in_background", lambda trace, db: persisted.append(trace))

    async def openrouter(*a, **kw):
        return await h._traced_attempt("openrouter", "grok", AsyncMock(side_effect=RuntimeError("503")))

    async def together(*a, **kw):
        return await h._traced_attempt("together", "qwen", AsyncMock(return_value="здарова"))

    async def persona(*a, **kw):
        try:
            return await openrouter()
        except RuntimeError:
            return await together()

    h._call_persona = persona
    out = await h._ask_moltbot_routed("Юра", "привет", "", None, CHAT)

    assert out == "здарова"
    (trace,) = persisted
    assert trace.outcome == "ok" and trace.chat_id == CHAT
    assert [(a.provider, a.ok) for a in trace.attempts] == [("openrouter", False), ("together", True)]
    assert "503" in trace.attempts[0].error
    assert llm_trace.current() is None


@pytest.mark.asyncio
async def test_persist_writes_row_without_raising():
    trace = llm_trace.LLMTrace(kind="persona", chat_id=CHAT)
    a = trace.start_attempt("openrouter", "grok")
    a.ok, a.prompt_tokens, a.completion_tokens, a.cost_usd = True, 10, 2, 0.5
    trace.finish("ok", "ответ")
    db = AsyncMock()
    await llm_trace.persist(trace, db)
    params = db.execute_query.await_args.args[1]
    assert params[0] == trace.trace_id and params[5] == "grok" and params[9] == 10
    db.execute_query = AsyncMock(side_effect=Exception("db down"))
    await llm_trace.persist(trace, db)  # must not raise
