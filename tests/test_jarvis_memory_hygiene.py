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


# ── reactions instead of filler replies ──────────────────────────────────────

def _react_handler():
    h = _handler()
    h._last_reaction_time = {}
    h._last_used_emoji = {}
    h._reaction_day_counts = {}
    return h


def test_reaction_gate_blocks_short_cooldown_cap_and_kill_switch(monkeypatch):
    h = _react_handler()
    now = datetime(2026, 9, 22, 18, 0, tzinfo=timezone.utc)
    assert h._reaction_gate(CHAT, "ок", now) == "short"
    assert h._reaction_gate(CHAT, "я наконец апнул титана", now) is None
    h._last_reaction_time[CHAT] = now - _mod.timedelta(minutes=3)
    assert h._reaction_gate(CHAT, "я наконец апнул титана", now) == "cooldown"
    h._last_reaction_time.clear()
    h._reaction_day_counts[CHAT] = (datetime(2026, 9, 22).date(), h._REACTION_DAILY_CAP)
    assert h._reaction_gate(CHAT, "я наконец апнул титана", now) == "daily_cap"
    h._reaction_day_counts.clear()
    monkeypatch.setenv("JARVIS_REACTIONS", "false")
    assert h._reaction_gate(CHAT, "я наконец апнул титана", now) == "disabled"


def test_parse_reaction_decision_accepts_only_valid_fresh_emoji():
    h = _react_handler()
    assert h._parse_reaction_decision('{"action": "react", "emoji": "🏆", "why": "x"}', []) == "🏆"
    assert h._parse_reaction_decision('```json\n{"action": "react", "emoji": "❤️"}\n```', []) == "❤"
    assert h._parse_reaction_decision('{"action": "ignore"}', []) is None
    assert h._parse_reaction_decision('{"action": "react", "emoji": "🚀"}', []) is None   # not a Telegram reaction
    assert h._parse_reaction_decision('{"action": "react", "emoji": "🏆"}', ["🏆"]) is None  # repeated
    assert h._parse_reaction_decision("garbage", []) is None


@pytest.mark.asyncio
async def test_maybe_react_sets_reaction_and_traces(monkeypatch):
    from unittest.mock import MagicMock
    monkeypatch.setattr(_mod.Settings, "OPENROUTER_API_KEY", "x", raising=False)
    monkeypatch.delenv("JARVIS_REACTIONS", raising=False)
    h = _react_handler()
    h.bot = MagicMock()
    h.bot.set_message_reaction = AsyncMock()
    h._get_recent_group_messages = AsyncMock(return_value=["[20:00 22.09] Богдан.: гг"])
    h._openrouter_post = AsyncMock(return_value={"choices": [{"message": {
        "content": '{"action": "react", "emoji": "🏆", "why": "эпично"}'}}], "usage": {"cost": 0.00005}})
    persisted = []
    monkeypatch.setattr(llm_trace, "persist_in_background", lambda trace, db: persisted.append(trace))
    message = MagicMock()
    message.chat.id, message.message_id, message.text = CHAT, 42, "я наконец апнул титана, 6 лет шёл"
    message.from_user.id, message.from_user.first_name = 742272644, "Юра"

    await h._maybe_react(message)

    kwargs = h.bot.set_message_reaction.await_args.kwargs
    assert kwargs["message_id"] == 42 and kwargs["reaction"][0].emoji == "🏆"
    assert h._last_used_emoji[CHAT] == ["🏆"]
    (trace,) = persisted
    assert trace.kind == "reaction" and trace.outcome == "react:🏆"
    assert trace.attempts[0].cost_usd == pytest.approx(0.00005)


@pytest.mark.asyncio
async def test_maybe_react_ignore_does_not_touch_telegram(monkeypatch):
    from unittest.mock import MagicMock
    monkeypatch.setattr(_mod.Settings, "OPENROUTER_API_KEY", "x", raising=False)
    h = _react_handler()
    h.bot = MagicMock()
    h.bot.set_message_reaction = AsyncMock()
    h._get_recent_group_messages = AsyncMock(return_value=[])
    h._openrouter_post = AsyncMock(return_value={"choices": [{"message": {"content": '{"action": "ignore"}'}}]})
    monkeypatch.setattr(llm_trace, "persist_in_background", lambda trace, db: None)
    message = MagicMock()
    message.chat.id, message.message_id, message.text = CHAT, 43, "во сколько завтра встречаемся?"
    await h._maybe_react(message)
    h.bot.set_message_reaction.assert_not_awaited()
    assert CHAT not in h._last_reaction_time


# ── memory v2 shadow / inject ────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["shadow", "inject"])
async def test_memory_v2_shadow_logs_but_only_inject_changes_prompt(monkeypatch, mode):
    monkeypatch.setattr(_mod, "MEMORY_V2_MODE", mode)
    h = _handler()
    store = AsyncMock()
    store.retrieve = AsyncMock(return_value=[{"id": 6, "kind": "profile_fact", "confidence": 0.9,
                                              "text": "Юра работает на складе с книгами"}])
    h._memory_store = store
    trace, token = llm_trace.begin("persona", CHAT)
    try:
        with patch.object(_mod, '_load_chat_summary', return_value=''), \
                patch.object(_mod, '_load_chat_lore', return_value=''):
            messages = await h._build_persona_messages("Макс", "что там у Юры на работе?", "", [], CHAT)
            # provider fallback rebuilds the snapshot: retrieval must not run twice
            await h._build_persona_messages("Макс", "что там у Юры на работе?", "", [], CHAT)
    finally:
        llm_trace.end(token)
    assert trace.memory_ids == [6] and trace.memory_mode == mode
    assert store.retrieve.await_count == 1
    assert store.retrieve.await_args.args[3] == {742272644}      # Юра detected from «у Юры»
    injected = "Юра работает на складе" in messages[0]["content"]
    assert injected is (mode == "inject")


# ── fallback chain, feedback, AI health ─────────────────────────────────────

@pytest.mark.asyncio
async def test_persona_falls_back_to_gemini_before_together():
    h = _handler()
    h._call_openrouter = AsyncMock(side_effect=RuntimeError("402 credits"))
    h._call_gemini_text = AsyncMock(return_value="от джемини")
    h._call_together = AsyncMock(return_value="от together")
    assert await h._call_persona("Юра", "привет", "", [], CHAT) == "от джемини"
    h._call_together.assert_not_awaited()
    h._call_gemini_text = AsyncMock(side_effect=RuntimeError("safety"))
    assert await h._call_persona("Юра", "привет", "", [], CHAT) == "от together"


@pytest.mark.asyncio
async def test_summary_llm_prefers_openrouter_then_gemini_never_ollama(monkeypatch):
    from unittest.mock import MagicMock
    monkeypatch.setattr(_mod.Settings, "OPENROUTER_API_KEY", "x", raising=False)
    h = _handler()
    h._call_ollama_direct = MagicMock(side_effect=AssertionError("must not wake the PC"))
    h._openrouter_post = AsyncMock(side_effect=RuntimeError("down"))
    h._gemini_model = MagicMock()
    h._gemini_model.generate_content = MagicMock(return_value=MagicMock(text="Богдан провёл урок"))
    assert await h._summarize_llm("sys", "prompt") == "Богдан провёл урок"


def test_reaction_polarity():
    assert llm_trace.reaction_polarity("🤣") == 1
    assert llm_trace.reaction_polarity("❤️") == 1
    assert llm_trace.reaction_polarity("👎") == -1
    assert llm_trace.reaction_polarity("🤔") == 0


@pytest.mark.asyncio
async def test_reaction_on_jarvis_message_is_stored_with_trace():
    from unittest.mock import MagicMock
    from types import SimpleNamespace as NS
    db = AsyncMock()
    db.execute_query = AsyncMock(side_effect=[[("trace123",)], None, None])
    h = _handler(db)
    event = NS(chat=NS(id=CHAT), message_id=555, user=NS(id=742272644),
               old_reaction=[], new_reaction=[NS(type="emoji", emoji="🤣"), NS(type="emoji", emoji="👎")])
    await h._record_reaction_feedback(event)
    inserts = [c.args[1] for c in db.execute_query.await_args_list if "INSERT INTO llm_feedback" in c.args[0]]
    assert inserts == [(CHAT, 555, "trace123", 742272644, "reaction", "🤣", 1),
                       (CHAT, 555, "trace123", 742272644, "reaction", "👎", -1)]


@pytest.mark.asyncio
async def test_reaction_on_human_message_is_ignored():
    from types import SimpleNamespace as NS
    db = AsyncMock()
    db.execute_query = AsyncMock(side_effect=[[], []])
    h = _handler(db)
    event = NS(chat=NS(id=CHAT), message_id=1, user=None, old_reaction=[],
               new_reaction=[NS(type="emoji", emoji="🔥")])
    await h._record_reaction_feedback(event)
    assert not any("INSERT" in c.args[0] for c in db.execute_query.await_args_list)


def test_text_feedback_patterns():
    neg, pos = MoltbotHandlers._NEGATIVE_FEEDBACK_RE, MoltbotHandlers._POSITIVE_FEEDBACK_RE
    assert neg.search("опять ты про лисёнка, не тащи это")
    assert neg.search("кринж")
    assert pos.search("ахахах база") and pos.search("ору")
    assert not neg.search("а что ты думаешь про патч") and not pos.search("а что ты думаешь про патч")


@pytest.mark.asyncio
async def test_ai_health_alerts_have_their_own_cooldown(monkeypatch):
    from services.health_monitor import HealthMonitor
    hm = HealthMonitor(None, AsyncMock(), None)
    hm._check_ai_jobs = AsyncMock(return_value={"memory_stale": "Memory v2 stale"})
    hm._check_openrouter_credits = AsyncMock(return_value={"openrouter_credits": "OpenRouter: $0.80"})
    first = await hm._ai_issues()
    assert sorted(first) == ["Memory v2 stale", "OpenRouter: $0.80"]
    assert await hm._ai_issues() == []          # same issues within 6h stay quiet


def test_no_placeholders_inside_sql_interval_literals():
    import re as _re
    src = open(os.path.join(_src, "handlers", "moltbot_handlers.py"), encoding="utf-8").read()
    assert not _re.search(r"INTERVAL '%s", src)


LORE = ("- Эдик Коваленко — мем-персонаж чата («латентный коллаборант из Геническа»); его «торсионные генераторы» — "
        "пародия на лженауку/РЕН-ТВ, тема регулярно всплывает.\n"
        "Лисёнок — прошлая фембой-личность бота; Богдан шантажирует Джарвиса, угрожая попросить Макса вернуть этот код.")


@pytest.mark.parametrize("text,history,expected", [
    ("джарвис а помнишь кто торсионные генераторы продавал?", [], ["Эдик"]),
    ("Помнишь свою личность лисёнка?", [], ["Лисёнок"]),
    ("джарвис что скажешь", ["[20:00] Юра: эдик опять в новостях"], ["Эдик"]),
    ("джарвис как в питоне отсортировать список", [], []),
    ("Богдан, а ты этот курсач сдал? спроси у Макса", [], []),     # names alone never pull a legend
    ("купил новый генератор для дачи", [], []),                     # generic stem alone doesn't either
])
def test_lore_is_visible_only_when_the_scene_touches_it(text, history, expected):
    picked = _mod._select_lore(LORE, text, history)
    assert [name for name in ("Эдик", "Лисёнок") if name in picked] == expected
