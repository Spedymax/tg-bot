"""Replay golden scenes through candidate persona configs.

    venv/bin/python -m evals.replay --config prod --scenes data/evals/golden-v1.jsonl evals/seed_scenes.jsonl
    venv/bin/python -m evals.replay --config '{"name":"grok47","model":"x-ai/grok-4.7","reasoning":"low"}'

Every candidate sees the same immutable input: the prompt is assembled by the
production ContextBuilder (same sections, same post-prompt, frozen clock at
the scene time, the identity version live at that moment unless the config
pins one). web_search is offered but stubbed: the call is recorded (to measure
unnecessary search) and the model must answer without results.
Output: data/evals/runs/<run_id>.jsonl — one row per scene × seed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from evals.openrouter import OpenRouter, ensure_budget  # noqa: E402
from evals.scenes import DATA_DIR, SEED_PATH, Scene, load_scenes, save_jsonl  # noqa: E402
from services.context_builder import PERSONA_POST_PROMPT, ContextBuilder, format_clock  # noqa: E402
from services.persona_tools import WEB_SEARCH_TOOL  # noqa: E402

BOT_NAMES = {"Кеша", "Иннокентий", "Лолита", "Ло", "Лола", "Jarvis", "Джарвис", "MoltBot"}
RUNS_DIR = os.path.join(DATA_DIR, "runs")

PRESETS = {
    "prod": {"name": "prod", "model": "x-ai/grok-4.7", "reasoning": "low"},
    "grok47": {"name": "grok47", "model": "x-ai/grok-4.7", "reasoning": "low"},
    "glm-flash": {"name": "glm-flash", "model": "z-ai/glm-5.3-flash", "reasoning": None},
    "gpt55": {"name": "gpt55", "model": "openai/gpt-5.5", "reasoning": "low"},
    "prod-medium": {"name": "prod-medium", "model": "x-ai/grok-4.6", "reasoning": "medium"},
}

SEARCH_STUB = ("[eval] Поиск сейчас недоступен. Ответь без него: если факт не знаешь — "
               "честно скажи, не выдумывай.")


def clean_reply(text: str) -> str:
    """Same post-processing as MoltbotHandlers._clean_persona_reply."""
    text = re.sub(r"<think>.*?(?:</think>|$)", "", text or "", flags=re.DOTALL).strip()
    text = re.sub(r"\*[^*]{2,80}\*", "", text)
    return re.sub(r"\n\s*\n\s*\n", "\n\n", text).strip()


async def load_identities() -> dict[int, str]:
    from database.db_manager import DatabaseManager
    db = DatabaseManager()
    await db.init_pool()
    async with db.connection() as conn:
        cur = await conn.execute("SELECT id, content FROM prompt_versions ORDER BY id")
        rows = await cur.fetchall()
    await db.close_all_connections()
    return {vid: content for vid, content in rows}


def build_messages(scene: Scene, identity: str, overlay: str | None = None) -> list[dict]:
    at = datetime.fromisoformat(scene.at)
    snapshot = ContextBuilder(BOT_NAMES).build(
        identity=identity, hard_rules="", chat_context=scene.chat_context,
        summary=scene.summary, lore=scene.lore, history=scene.history,
        sender_name=scene.trigger_sender, user_text=scene.trigger_text,
        post_prompt=PERSONA_POST_PROMPT, clock=format_clock(at),
        overlay=scene.overlay if overlay is None else overlay,
    )
    return snapshot.as_messages()


async def run_scene(client: OpenRouter, config: dict, scene: Scene, identity: str, seed: int) -> dict:
    messages = build_messages(scene, identity)
    base = {"model": config["model"], "max_tokens": config.get("max_tokens", 3000),
            "temperature": config.get("temperature", 0.8), "seed": seed}
    if config.get("reasoning"):
        base["reasoning"] = {"effort": config["reasoning"]}
    searches: list[dict] = []
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0}
    latency = 0
    reply, error = "", ""
    try:
        for round_no in range(2):
            req = {**base, "messages": messages, "tools": [WEB_SEARCH_TOOL],
                   "tool_choice": "auto" if round_no == 0 else "none"}
            data = await client.chat(req)
            latency += data["_latency_ms"]
            u = data.get("usage") or {}
            usage["prompt_tokens"] += int(u.get("prompt_tokens") or 0)
            usage["completion_tokens"] += int(u.get("completion_tokens") or 0)
            usage["cost"] += float(u.get("cost") or 0)
            msg = data["choices"][0]["message"]
            calls = msg.get("tool_calls") or []
            if not calls or round_no == 1:
                reply = clean_reply(msg.get("content") or "")
                break
            messages = messages + [{"role": "assistant", "content": msg.get("content") or None, "tool_calls": calls}]
            for call in calls:
                fn = call.get("function") or {}
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except Exception:
                    args = {"query": fn.get("arguments")}
                searches.append({"query": args.get("query"), "reason": args.get("reason")})
                messages.append({"role": "tool", "tool_call_id": call.get("id") or "call_0",
                                 "name": fn.get("name") or "web_search", "content": SEARCH_STUB})
    except Exception as e:
        error = str(e)[:300]
    return {
        "scene_id": scene.id, "config": config["name"], "model": config["model"],
        "reasoning": config.get("reasoning"), "seed": seed,
        "prompt_version": config.get("prompt_version") or scene.prompt_version,
        "reply": reply, "error": error, "searches": searches,
        "latency_ms": latency, "usage": usage,
    }


async def replay(config: dict, scenes: list[Scene], seeds: list[int], concurrency: int) -> tuple[str, list[dict]]:
    ensure_budget(config.get("est_cost_per_reply", 0.02) * len(scenes) * len(seeds))
    identities = await load_identities()
    current = identities[max(identities)]
    client = OpenRouter(concurrency=concurrency)
    tasks = []
    for scene in scenes:
        vid = config.get("prompt_version") or scene.prompt_version
        identity = identities.get(vid, current) if vid else current
        for seed in seeds:
            tasks.append(run_scene(client, config, scene, identity, seed))
    rows = await asyncio.gather(*tasks)
    await client.close()
    run_id = f"{datetime.now(timezone.utc):%Y%m%d-%H%M}-{config['name']}"
    save_jsonl(os.path.join(RUNS_DIR, f"{run_id}.jsonl"), rows)
    errors = sum(1 for r in rows if r["error"])
    print(f"{run_id}: {len(rows)} replies, {errors} errors, ${client.spent_usd:.3f}")
    return run_id, rows


def parse_config(raw: str) -> dict:
    if raw in PRESETS:
        return dict(PRESETS[raw])
    config = json.loads(raw)
    if "name" not in config or "model" not in config:
        raise SystemExit("config needs at least name and model")
    return config


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", action="append", required=True,
                    help=f"preset ({', '.join(PRESETS)}) or JSON; repeatable")
    ap.add_argument("--scenes", nargs="+", default=[os.path.join(DATA_DIR, "golden-v1.jsonl"), SEED_PATH])
    ap.add_argument("--seeds", type=int, nargs="+", default=[1])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()
    scenes = load_scenes(*[p for p in args.scenes if os.path.exists(p)])[: args.limit or None]
    for raw in args.config:
        asyncio.run(replay(parse_config(raw), scenes, args.seeds, args.concurrency))


if __name__ == "__main__":
    main()
