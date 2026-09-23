"""One-command A/B: production config vs a candidate, cheap by default.

    # new prompt draft vs prod, 26 scenes, free Gemini judge
    venv/bin/python -m evals.compare --cand '{"identity_path": "docs/prompts/identity-v30.md"}'
    # other model / reasoning; bigger set; paid judge for an important call
    venv/bin/python -m evals.compare --cand '{"reasoning": "low"}' --set full --judge anthropic/claude-sonnet-5

Cost control:
- prod replies come from the reply cache (evals/replay.py) — the baseline is paid for once;
- the judge is the bot's free Gemini key unless --judge says otherwise;
- one provider session per run, so the shared system prompt is served from the prompt cache.
Typical `quick` run with a new prompt: ~26 fresh candidate replies ≈ $0.2–0.3, judge $0.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from evals import judge as judge_mod  # noqa: E402
from evals.replay import load_identities, replay  # noqa: E402
from evals.scenes import DATA_DIR, SEED_PATH, load_scenes  # noqa: E402

HARD_PATH = os.path.join(os.path.dirname(__file__), "hard_scenes.jsonl")
SETS = {
    "quick": [SEED_PATH, os.path.join(DATA_DIR, "prompt-check-10.jsonl")],
    "full": [os.path.join(DATA_DIR, "golden-v1.jsonl"), SEED_PATH, HARD_PATH],
    "seeds": [SEED_PATH],
}
PROD = {"name": "prod", "model": "x-ai/grok-4.7", "reasoning": "minimal"}


async def main_async(args) -> None:
    paths = [p for p in SETS[args.set] if os.path.exists(p)]
    scenes = load_scenes(*paths)
    latest = max(await load_identities())
    base = {**PROD, "prompt_version": latest}
    cand = {**PROD, "prompt_version": latest, "name": "candidate", **json.loads(args.cand)}
    if cand.get("identity_path"):
        cand.pop("prompt_version", None)
    print(f"{len(scenes)} scenes ({args.set}); prod = {base['model']}/{base['reasoning']}/v{latest}; "
          f"candidate = {json.dumps({k: v for k, v in cand.items() if k != 'name'}, ensure_ascii=False)}")
    base_run, _ = await replay(base, scenes, args.seeds, args.concurrency)
    cand_run, _ = await replay(cand, scenes, args.seeds, args.concurrency)
    await judge_mod.cmd_pair(base_run, cand_run, paths, args.judge, 7)
    print("A = prod, B = candidate. Cost above: replay lines (OpenRouter) + judge line"
          + (" ($0 — free Gemini)." if args.judge == judge_mod.GEMINI_DIRECT else "."))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cand", required=True, help='JSON overrides, e.g. {"identity_path": "..."} or {"reasoning": "low"}')
    ap.add_argument("--set", choices=list(SETS), default="quick")
    ap.add_argument("--judge", default=judge_mod.DEFAULT_JUDGE)
    ap.add_argument("--seeds", type=int, nargs="+", default=[1])
    ap.add_argument("--concurrency", type=int, default=6)
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
