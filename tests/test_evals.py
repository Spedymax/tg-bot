"""Offline tests for the eval pipeline (no network, no DB)."""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from evals import extract, judge, replay
from evals.openrouter import BudgetError, ensure_budget, parse_json_reply
from evals.scenes import SEED_PATH, Expect, Scene, load_scenes, save_jsonl
from services.context_builder import OVERLAY_HEADER, compose_thread_first
from services.persona_tools import WEB_SEARCH_TOOL


def _scene(**kw):
    base = dict(id="s1", category="banter", at="2026-09-22T18:40:00+00:00",
                trigger_sender="Юра", trigger_text="джарвис какое число",
                history=["[20:31 22.09] Богдан.: привет", "[20:32 22.09] Jarvis: здарова"],
                expect=Expect(criteria=["ok"], no_search=True))
    base.update(kw)
    return Scene(**base)


def test_seed_scenes_are_valid_and_unique():
    scenes = load_scenes(SEED_PATH)
    assert len(scenes) >= 10
    assert not [p for s in scenes for p in s.validate()]


def test_scene_roundtrip(tmp_path):
    path = str(tmp_path / "s.jsonl")
    save_jsonl(path, [_scene().to_dict()])
    (loaded,) = load_scenes(path)
    assert loaded.expect.no_search is True and loaded.history[1].endswith("здарова")


def test_duplicate_ids_rejected(tmp_path):
    path = str(tmp_path / "s.jsonl")
    save_jsonl(path, [_scene().to_dict(), _scene().to_dict()])
    with pytest.raises(ValueError):
        load_scenes(path)


def test_replay_prompt_matches_production_shape():
    messages = replay.build_messages(_scene(overlay="ТЫ ПУДЖИНИО"), identity="IDENTITY")
    assert messages[0]["role"] == "system" and messages[0]["content"].startswith("IDENTITY")
    # frozen clock from the scene time, not "now"; next to the turn so the system prefix caches
    assert "вторник, 22 сентября 2026, 21:40 по Киеву" in messages[-2]["content"]
    assert messages[-1] == {"role": "user", "content": "Юра: джарвис какое число"}
    assert messages[-2]["role"] == "system" and OVERLAY_HEADER in messages[-2]["content"]
    assert {"role": "assistant", "content": "здарова"} in messages


def test_replay_uses_production_tool_definition():
    text = open(os.path.join(os.path.dirname(__file__), "..", "src", "handlers", "moltbot_handlers.py"),
                encoding="utf-8").read()
    assert "_WEB_SEARCH_TOOL = WEB_SEARCH_TOOL" in text
    assert "reason" in WEB_SEARCH_TOOL["function"]["parameters"]["properties"]


def test_extract_format_line_matches_prod_timestamp_shape():
    line = extract.format_line("Юра", "привет", datetime(2026, 9, 22, 17, 3))
    assert line == "[19:03 22.09] Юра: привет"


def test_select_keeps_all_frustration_then_round_robins():
    def row(i, cat, frustration=False, keep=True):
        return {"id": f"r{i}", "at": f"2026-09-{10 + i:02d}T00:00:00+00:00",
                "label": {"keep": keep, "category": cat, "criteria": ["c"], "frustration": frustration}}
    rows = [row(1, "banter"), row(2, "banter"), row(3, "banter"), row(4, "serious"),
            row(5, "correction", frustration=True), row(6, "banter", keep=False)]
    chosen = [r["id"] for r in extract.select(rows, 3)]
    assert "r5" in chosen and "r4" in chosen and "r6" not in chosen
    assert len(chosen) == 3


def test_deterministic_checks_flag_unnecessary_search():
    scene = _scene()
    checks = judge.deterministic_checks(scene, {"reply": "x" * 700, "searches": [{"query": "ревил"}]})
    assert checks["unnecessary_search"] and checks["too_long"] and not checks["empty"]


def test_summarize_aggregates_scores_and_flags():
    scenes = {"s1": _scene(), "s2": _scene(id="s2", category="serious", expect=Expect(criteria=["a", "b"]))}
    scored = [
        {"scene_id": "s1", "reply": "ok", "searches": [{"query": "q"}], "latency_ms": 100, "usage": {"cost": 0.01},
         "judge": {"criteria": [True], "must_not_violated": [], "scores": {"natural": 4, "funny": 5},
                   "flags": {"unprompted_callback": True}}},
        {"scene_id": "s2", "reply": "okok", "searches": [], "latency_ms": 300, "usage": {"cost": 0.03},
         "judge": {"criteria": [True, False], "must_not_violated": [True], "scores": {"natural": 2}, "flags": {}}},
    ]
    s = judge.summarize(scored, scenes)
    assert s["criteria_pass"] == round(2 / 3, 3)
    assert s["must_not_violation"] == 1.0
    assert s["axes"]["natural"] == 3.0
    assert s["flag_rate"]["unprompted_callback"] == 0.5
    assert s["unnecessary_search_rate"] == 1.0   # s1 is no_search and searched
    assert s["by_category"] == {"banter": 1.0, "serious": 0.5}


def test_pair_verdict_unflips_positions():
    verdict = {"overall": "1", "funny": "2", "useful": "tie", "reason": "x"}
    assert judge.unflip_pair_verdict(verdict, flipped=False) == {"overall": "A", "funny": "B", "useful": "tie"}
    assert judge.unflip_pair_verdict(verdict, flipped=True) == {"overall": "B", "funny": "A", "useful": "tie"}


def test_parse_json_reply_tolerates_fences_and_think():
    assert parse_json_reply('<think>hm</think>```json\n{"a": 1}\n```') == {"a": 1}


def test_budget_guard_protects_production_reserve(monkeypatch):
    monkeypatch.setattr("evals.openrouter.remaining_credits", lambda key=None: 4.0)
    assert ensure_budget(0.5, reserve_usd=3.0) == 4.0
    with pytest.raises(BudgetError):
        ensure_budget(1.5, reserve_usd=3.0)


def test_compose_thread_first_prioritises_reply_chain():
    out = compose_thread_first(["t1", "t2"], ["r1", "t2", "r2", "r3"], limit=4, char_budget=100)
    assert out == ["t1", "t2", "r2", "r3"]


@pytest.mark.asyncio
async def test_reply_cache_skips_paid_call(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    monkeypatch.setattr(replay, "CACHE_PATH", str(tmp_path / "replies.jsonl"))
    monkeypatch.setattr(replay, "_cache", None)
    client = AsyncMock()
    client.chat = AsyncMock(return_value={"choices": [{"message": {"content": "здарова"}}], "_latency_ms": 5,
                                          "usage": {"prompt_tokens": 100, "completion_tokens": 5, "cost": 0.01}})
    cfg = {"name": "prod", "model": "x-ai/grok-4.7", "reasoning": "minimal"}
    first = await replay.run_scene(client, cfg, _scene(), "IDENTITY", 1)
    second = await replay.run_scene(client, {**cfg, "name": "candidate"}, _scene(), "IDENTITY", 1)
    assert first["reply"] == second["reply"] == "здарова"
    assert client.chat.await_count == 1 and second["from_cache"] and second["usage"]["cost"] == 0.0
    await replay.run_scene(client, cfg, _scene(), "IDENTITY v2", 1)      # different prompt → paid again
    assert client.chat.await_count == 2
    sent = client.chat.await_args_list[0].args[0]
    assert sent["session_id"].startswith("eval-")                       # sticky routing for prompt cache


def test_default_judge_is_free():
    assert judge.DEFAULT_JUDGE == judge.GEMINI_DIRECT
