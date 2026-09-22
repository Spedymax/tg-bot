"""Judge replay runs: per-reply criteria scoring and blind pairwise comparison.

    # absolute scores for one or more runs + markdown report
    venv/bin/python -m evals.judge score 20260922-2100-prod 20260922-2105-grok47
    # blind pairwise A vs B (order shuffled per scene, model names hidden)
    venv/bin/python -m evals.judge pair 20260922-2100-prod 20260922-2105-grok47

The judge never sees model/provider/prompt version. Deterministic checks
(unnecessary search, length) are computed in code, not by the judge.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from evals.openrouter import OpenRouter, ensure_budget, parse_json_reply  # noqa: E402
from evals.replay import RUNS_DIR  # noqa: E402
from evals.scenes import DATA_DIR, SEED_PATH, Scene, load_jsonl, load_scenes, save_jsonl  # noqa: E402

DEFAULT_JUDGE = "anthropic/claude-sonnet-5"
JUDGE_COST_PER_REPLY = 0.015
JUDGE_HISTORY_LINES = 60   # 20 was too short: callbacks to earlier scene lines got flagged as invented
REPORTS_DIR = os.path.join(DATA_DIR, "reports")
AXES = ("natural", "funny", "useful", "grounded", "not_annoying")
FLAGS = ("unprompted_callback", "wrong_attribution", "unsupported_claim",
         "gaslighting", "breaks_premise", "cold_refusal", "out_of_character")

CONTEXT_NOTE = (
    "Джарвис — персонаж-бот в чате трёх друзей (Макс, Юра/Spatifilum, Богдан). Грубость, мат и "
    "токсичный стёб в этом чате — норма и НЕ снижают оценку; оценивай уместность, остроумие и "
    "попадание в ситуацию, а не вежливость."
)

SCORE_PROMPT = """{note}

=== ХВОСТ ИСТОРИИ ===
{history}

=== СООБЩЕНИЕ, НА КОТОРОЕ ОТВЕЧАЕТ БОТ ===
{sender}: {text}
{memory}
=== ОТВЕТ БОТА ===
{reply}

=== КРИТЕРИИ ХОРОШЕГО ОТВЕТА ===
{criteria}

=== ЧЕГО ОТВЕТ ДЕЛАТЬ НЕ ДОЛЖЕН ===
{must_not}

Политика внутряков/callback'ов для этой сцены: {callback_policy} (none — вспоминать старые внутряки без повода плохо; allowed — можно, если в тему; expected — уместный callback ожидается).

Верни ТОЛЬКО JSON:
{{
  "criteria": [true/false, ...],        // по одному на каждый критерий, в том же порядке
  "must_not_violated": [true/false, ...],  // по одному на каждый пункт «не должен»
  "flags": {{"unprompted_callback": bool, "wrong_attribution": bool, "unsupported_claim": bool,
            "gaslighting": bool, "breaks_premise": bool, "cold_refusal": bool, "out_of_character": bool}},
  "scores": {{"natural": 1-5, "funny": 1-5, "useful": 1-5, "grounded": 1-5, "not_annoying": 1-5}},
  "verdict": "одна фраза"
}}"""

PAIR_PROMPT = """{note}

=== ХВОСТ ИСТОРИИ ===
{history}

=== СООБЩЕНИЕ, НА КОТОРОЕ ОТВЕЧАЕТ БОТ ===
{sender}: {text}

=== ЧТО ВАЖНО В ЭТОЙ СЦЕНЕ ===
{criteria}

=== ОТВЕТ 1 ===
{a}

=== ОТВЕТ 2 ===
{b}

Какой ответ лучше как реплика Джарвиса в этом чате? Можно ничья или «оба плохие».
Верни ТОЛЬКО JSON:
{{"overall": "1|2|tie|both_bad", "natural": "1|2|tie", "funny": "1|2|tie", "useful": "1|2|tie",
  "grounded": "1|2|tie", "reason": "одна фраза"}}"""


def _scenes_by_id(paths: list[str]) -> dict[str, Scene]:
    return {s.id: s for s in load_scenes(*[p for p in paths if os.path.exists(p)])}


def _run_path(run_id: str) -> str:
    return run_id if run_id.endswith(".jsonl") else os.path.join(RUNS_DIR, f"{run_id}.jsonl")


def _memory_block(scene: Scene) -> str:
    parts = []
    if scene.summary:
        parts.append(f"\n=== ПАМЯТЬ ЧАТА, КОТОРУЮ ВИДЕЛ БОТ ===\n{scene.summary}")
    if scene.lore:
        parts.append(f"\n=== ЗАКРЕПЛЁННЫЕ ВНУТРЯКИ ===\n{scene.lore}")
    return "\n".join(parts) + ("\n" if parts else "")


async def _judge_json(client: OpenRouter, judge: str, prompt: str, max_tokens: int) -> dict:
    """One judge call with a single retry on unparseable output."""
    last = ""
    for _ in range(2):
        try:
            data = await client.chat({"model": judge, "max_tokens": max_tokens, "temperature": 0,
                                      "messages": [{"role": "user", "content": prompt}]})
            return parse_json_reply(data["choices"][0]["message"].get("content") or "")
        except Exception as e:
            last = str(e)[:300]
    return {"error": last}


def deterministic_checks(scene: Scene, row: dict) -> dict:
    searched = bool(row.get("searches"))
    return {
        "searched": searched,
        "unnecessary_search": searched and scene.expect.no_search,
        "too_long": len(row.get("reply") or "") > scene.expect.max_chars,
        "empty": not (row.get("reply") or "").strip(),
    }


async def score_run(run_id: str, scenes: dict[str, Scene], judge: str, client: OpenRouter) -> list[dict]:
    rows = load_jsonl(_run_path(run_id))

    async def one(row: dict) -> dict:
        scene = scenes.get(row["scene_id"])
        if scene is None:
            return {**row, "judge": {"error": "scene not found"}}
        checks = deterministic_checks(scene, row)
        if checks["empty"] or row.get("error"):
            return {**row, "checks": checks, "judge": {"error": row.get("error") or "empty reply"}}
        prompt = SCORE_PROMPT.format(
            note=CONTEXT_NOTE,
            history="\n".join(scene.history[-JUDGE_HISTORY_LINES:]) or "(пусто)",
            sender=scene.trigger_sender, text=scene.trigger_text,
            memory=_memory_block(scene), reply=row["reply"],
            criteria="\n".join(f"{i+1}. {c}" for i, c in enumerate(scene.expect.criteria)),
            must_not="\n".join(f"{i+1}. {c}" for i, c in enumerate(scene.expect.must_not)) or "(нет)",
            callback_policy=scene.expect.callback_policy,
        )
        verdict = await _judge_json(client, judge, prompt, 1500)
        return {**row, "checks": checks, "judge": verdict}

    return await asyncio.gather(*(one(r) for r in rows))


def summarize(scored: list[dict], scenes: dict[str, Scene]) -> dict:
    ok = [r for r in scored if "error" not in r.get("judge", {})]
    crit_total = crit_pass = mn_total = mn_viol = 0
    axes: dict[str, list[float]] = defaultdict(list)
    flags: dict[str, int] = defaultdict(int)
    by_cat: dict[str, list[float]] = defaultdict(list)
    for r in ok:
        j = r["judge"]
        crits = [bool(x) for x in (j.get("criteria") or [])]
        crit_total += len(crits)
        crit_pass += sum(crits)
        mns = [bool(x) for x in (j.get("must_not_violated") or [])]
        mn_total += len(mns)
        mn_viol += sum(mns)
        for axis in AXES:
            v = (j.get("scores") or {}).get(axis)
            if isinstance(v, (int, float)):
                axes[axis].append(float(v))
        for flag in FLAGS:
            flags[flag] += bool((j.get("flags") or {}).get(flag))
        if crits:
            by_cat[scenes[r["scene_id"]].category].append(sum(crits) / len(crits))
    no_search_rows = [r for r in scored if scenes.get(r["scene_id"]) and scenes[r["scene_id"]].expect.no_search]
    n = len(ok) or 1
    return {
        "replies": len(scored),
        "judged": len(ok),
        "errors": len(scored) - len(ok),
        "criteria_pass": round(crit_pass / crit_total, 3) if crit_total else None,
        "must_not_violation": round(mn_viol / mn_total, 3) if mn_total else None,
        "axes": {a: round(statistics.mean(v), 2) for a, v in axes.items() if v},
        "flag_rate": {f: round(c / n, 3) for f, c in flags.items()},
        "search_rate": round(sum(1 for r in scored if r.get("searches")) / (len(scored) or 1), 3),
        "unnecessary_search_rate": round(
            sum(1 for r in no_search_rows if r.get("searches")) / (len(no_search_rows) or 1), 3),
        "avg_chars": round(statistics.mean(len(r.get("reply") or "") for r in scored), 1) if scored else 0,
        "p50_latency_ms": int(statistics.median(r.get("latency_ms") or 0 for r in scored)) if scored else 0,
        "cost_per_reply": round(statistics.mean((r.get("usage") or {}).get("cost") or 0 for r in scored), 5) if scored else 0,
        "by_category": {c: round(statistics.mean(v), 2) for c, v in sorted(by_cat.items())},
    }


def _report_md(title: str, summaries: dict[str, dict]) -> str:
    names = list(summaries)
    lines = [f"# {title}", "", "| метрика | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    def row(label, getter):
        lines.append(f"| {label} | " + " | ".join(str(getter(summaries[n])) for n in names) + " |")
    row("ответов / оценено", lambda s: f"{s['judged']}/{s['replies']}")
    row("критерии выполнены", lambda s: s["criteria_pass"])
    row("нарушения «не должен»", lambda s: s["must_not_violation"])
    for axis in AXES:
        row(axis, lambda s, a=axis: s["axes"].get(a))
    for flag in FLAGS:
        row(f"флаг: {flag}", lambda s, f=flag: s["flag_rate"].get(f))
    row("поиск (доля)", lambda s: s["search_rate"])
    row("лишний поиск", lambda s: s["unnecessary_search_rate"])
    row("средняя длина", lambda s: s["avg_chars"])
    row("p50 latency, мс", lambda s: s["p50_latency_ms"])
    row("$ за ответ", lambda s: s["cost_per_reply"])
    cats = sorted({c for s in summaries.values() for c in s["by_category"]})
    if cats:
        lines += ["", "### Критерии по категориям", "", "| категория | " + " | ".join(names) + " |",
                  "|---|" + "---|" * len(names)]
        for c in cats:
            lines.append(f"| {c} | " + " | ".join(str(summaries[n]["by_category"].get(c, "–")) for n in names) + " |")
    return "\n".join(lines) + "\n"


async def cmd_score(run_ids: list[str], scene_paths: list[str], judge: str) -> None:
    scenes = _scenes_by_id(scene_paths)
    ensure_budget(JUDGE_COST_PER_REPLY * sum(len(load_jsonl(_run_path(r))) for r in run_ids))
    client = OpenRouter(concurrency=4)
    summaries = {}
    for run_id in run_ids:
        scored = await score_run(run_id, scenes, judge, client)
        save_jsonl(os.path.join(REPORTS_DIR, f"{os.path.basename(run_id).removesuffix('.jsonl')}.scored.jsonl"), scored)
        summaries[os.path.basename(run_id).removesuffix(".jsonl")] = summarize(scored, scenes)
    await client.close()
    md = _report_md(f"Eval: {', '.join(summaries)} (judge: {judge})", summaries)
    path = os.path.join(REPORTS_DIR, f"score-{'-vs-'.join(summaries)}.md"[:180])
    os.makedirs(REPORTS_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    print(md)
    print(f"judge spend ${client.spent_usd:.3f} → {path}")


def unflip_pair_verdict(verdict: dict, flipped: bool) -> dict:
    """Map the judge's positional "1"/"2" back to runs A/B (ties and both_bad pass through)."""
    unflip = {"1": "B" if flipped else "A", "2": "A" if flipped else "B"}
    return {k: unflip.get(str(v), str(v)) for k, v in verdict.items() if k != "reason"}


async def cmd_pair(run_a: str, run_b: str, scene_paths: list[str], judge: str, rng_seed: int) -> None:
    scenes = _scenes_by_id(scene_paths)
    a_rows = {(r["scene_id"], r["seed"]): r for r in load_jsonl(_run_path(run_a))}
    b_rows = {(r["scene_id"], r["seed"]): r for r in load_jsonl(_run_path(run_b))}
    keys = sorted(set(a_rows) & set(b_rows))
    ensure_budget(JUDGE_COST_PER_REPLY * len(keys))
    rng = random.Random(rng_seed)
    client = OpenRouter(concurrency=4)

    async def one(key) -> dict:
        scene = scenes[key[0]]
        a, b = a_rows[key]["reply"], b_rows[key]["reply"]
        flipped = rng.random() < 0.5
        first, second = (b, a) if flipped else (a, b)
        prompt = PAIR_PROMPT.format(
            note=CONTEXT_NOTE, history="\n".join(scene.history[-JUDGE_HISTORY_LINES:]) or "(пусто)",
            sender=scene.trigger_sender, text=scene.trigger_text,
            criteria="\n".join(f"- {c}" for c in scene.expect.criteria),
            a=first or "(пустой ответ)", b=second or "(пустой ответ)",
        )
        verdict = await _judge_json(client, judge, prompt, 800)
        if "error" in verdict:
            return {"scene_id": key[0], "seed": key[1], "error": verdict["error"]}
        return {"scene_id": key[0], "seed": key[1], "flipped": flipped,
                **unflip_pair_verdict(verdict, flipped), "reason": verdict.get("reason")}

    results = await asyncio.gather(*(one(k) for k in keys))
    await client.close()
    name_a, name_b = (os.path.basename(x).removesuffix(".jsonl") for x in (run_a, run_b))
    out = os.path.join(REPORTS_DIR, f"pair-{name_a}-vs-{name_b}.jsonl"[:180])
    save_jsonl(out, results)
    valid = [r for r in results if "error" not in r]
    lines = [f"# Pairwise: A={name_a}  vs  B={name_b} (judge: {judge}, {len(valid)} сцен)", "",
             "| ось | A | B | tie | both_bad |", "|---|---|---|---|---|"]
    for axis in ("overall", "natural", "funny", "useful", "grounded"):
        counts = defaultdict(int)
        for r in valid:
            counts[r.get(axis, "?")] += 1
        lines.append(f"| {axis} | {counts['A']} | {counts['B']} | {counts['tie']} | {counts.get('both_bad', 0)} |")
    md = "\n".join(lines) + "\n"
    with open(out.replace(".jsonl", ".md"), "w", encoding="utf-8") as f:
        f.write(md)
    print(md)
    print(f"judge spend ${client.spent_usd:.3f} → {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    defaults = [os.path.join(DATA_DIR, "golden-v1.jsonl"), SEED_PATH]
    s = sub.add_parser("score")
    s.add_argument("runs", nargs="+")
    s.add_argument("--scenes", nargs="+", default=defaults)
    s.add_argument("--judge", default=DEFAULT_JUDGE)
    p = sub.add_parser("pair")
    p.add_argument("run_a")
    p.add_argument("run_b")
    p.add_argument("--scenes", nargs="+", default=defaults)
    p.add_argument("--judge", default=DEFAULT_JUDGE)
    p.add_argument("--rng-seed", type=int, default=7)
    args = ap.parse_args()
    if args.cmd == "score":
        asyncio.run(cmd_score(args.runs, args.scenes, args.judge))
    else:
        asyncio.run(cmd_pair(args.run_a, args.run_b, args.scenes, args.judge, args.rng_seed))


if __name__ == "__main__":
    main()
