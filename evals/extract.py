"""Build the golden eval set from real production scenes.

    # 1. pull every Jarvis reply of the last N days with the context it saw
    venv/bin/python -m evals.extract pull --days 45
    # 2. draft category/criteria for each candidate with an LLM (a human reviews after)
    venv/bin/python -m evals.extract label
    # 3. pick a stratified golden set (all frustration scenes + round-robin by category)
    venv/bin/python -m evals.extract select --n 60 --out data/evals/golden-v1.jsonl

History is rebuilt exactly like production (reply chain first, then the recent
scene, same limits) via services.context_builder.compose_thread_first, but only
from messages *before* the trigger, so the snapshot is what the bot could see.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from evals.openrouter import OpenRouter, ensure_budget, parse_json_reply  # noqa: E402
from evals.scenes import (CALLBACK_POLICIES, CATEGORIES, DATA_DIR, Expect, Scene,  # noqa: E402
                          load_jsonl, save_jsonl)
from services.context_builder import compose_thread_first  # noqa: E402

MAIN_CHAT = -1001294162183
CHAT_CONTEXT = "групповой чат «Пусички»"
HISTORY_LIMIT = 100          # same as HISTORY_MESSAGE_LIMIT in moltbot_handlers
HISTORY_BUDGET = 12_000      # same as HISTORY_CHAR_BUDGET
CANDIDATES_PATH = os.path.join(DATA_DIR, "candidates.jsonl")
LABELED_PATH = os.path.join(DATA_DIR, "candidates-labeled.jsonl")
DEFAULT_LABEL_MODEL = "anthropic/claude-sonnet-5"
LABEL_COST_PER_SCENE = 0.013   # measured: $0.064 for 5 scenes with sonnet-5
_CET = ZoneInfo("Europe/Copenhagen")


def format_line(name: str | None, text: str, ts: datetime | None) -> str:
    """Same shape as MoltbotHandlers._format_ts + history line."""
    if ts is None:
        prefix = ""
    else:
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        prefix = ts.astimezone(_CET).strftime("[%H:%M %d.%m]")
    return f"{prefix} {name or 'Аноним'}: {text}"


# ── pull ─────────────────────────────────────────────────────────────────────

async def _query(db, sql: str, params: tuple) -> list[tuple]:
    async with db.connection() as conn:
        cur = await conn.execute(sql, params)
        return await cur.fetchall()


async def pull(days: int, chat_id: int) -> list[dict]:
    from database.db_manager import DatabaseManager
    db = DatabaseManager()
    await db.init_pool()
    replies = await _query(db, """
        SELECT b.message_id, b.message_text, b.timestamp,
               t.message_id, t.name, t.message_text, t.timestamp, t.reply_to_message_id
        FROM messages b
        JOIN messages t ON t.chat_id = b.chat_id AND t.message_id = b.reply_to_message_id
        WHERE b.chat_id = %s AND b.user_id = 0 AND t.user_id <> 0
          AND b.timestamp > NOW() - %s * INTERVAL '1 day'
        ORDER BY b.timestamp
    """, (chat_id, days))
    versions = await _query(db, "SELECT id, created_at FROM prompt_versions ORDER BY created_at", ())

    out = []
    for (bot_mid, bot_text, bot_ts, trig_mid, trig_name, trig_text, trig_ts, trig_reply_to) in replies:
        thread = []
        if trig_reply_to:
            rows = await _query(db, """
                WITH RECURSIVE chain AS (
                    SELECT name, message_text, timestamp, message_id, reply_to_message_id, 0 AS depth
                    FROM messages WHERE chat_id = %s AND message_id = %s
                    UNION ALL
                    SELECT p.name, p.message_text, p.timestamp, p.message_id, p.reply_to_message_id, c.depth + 1
                    FROM messages p JOIN chain c ON p.chat_id = %s AND p.message_id = c.reply_to_message_id
                    WHERE c.depth < 11
                )
                SELECT name, message_text, timestamp FROM chain ORDER BY depth DESC
            """, (chat_id, trig_reply_to, chat_id))
            thread = [format_line(*r) for r in rows]
        recent_rows = await _query(db, """
            SELECT name, message_text, timestamp FROM messages
            WHERE chat_id = %s AND timestamp < %s AND message_id IS DISTINCT FROM %s
            ORDER BY timestamp DESC LIMIT %s
        """, (chat_id, trig_ts, trig_mid, HISTORY_LIMIT))
        recent = [format_line(*r) for r in reversed(recent_rows)]
        history = compose_thread_first(thread, recent, limit=HISTORY_LIMIT, char_budget=HISTORY_BUDGET)

        reactions = await _query(db, """
            SELECT name, message_text, timestamp FROM messages
            WHERE chat_id = %s AND user_id <> 0 AND reply_to_message_id = %s
              AND timestamp < %s ORDER BY timestamp LIMIT 5
        """, (chat_id, bot_mid, bot_ts + timedelta(hours=1)))
        after = await _query(db, """
            SELECT name, message_text, timestamp FROM messages
            WHERE chat_id = %s AND user_id <> 0 AND timestamp > %s AND timestamp < %s
            ORDER BY timestamp LIMIT 4
        """, (chat_id, bot_ts, bot_ts + timedelta(minutes=10)))

        trig_aware = trig_ts if trig_ts.tzinfo else trig_ts.replace(tzinfo=timezone.utc)
        live = [vid for vid, created in versions if created <= trig_aware]
        out.append({
            "id": f"prod-{trig_aware:%Y%m%d}-{trig_mid}",
            "at": trig_aware.isoformat(),
            "trigger_sender": trig_name or "Аноним",
            "trigger_text": trig_text,
            "history": history,
            "prompt_version": live[-1] if live else None,
            "reference": {
                "prod_reply": bot_text,
                "direct_replies": [format_line(*r) for r in reactions],
                "after": [format_line(*r) for r in after],
            },
        })
    await db.close_all_connections()
    return out


# ── label ────────────────────────────────────────────────────────────────────

LABEL_PROMPT = """Ты помогаешь собрать eval-датасет для Telegram-бота Джарвиса (персонаж в чате трёх друзей: Макс, Юра/Spatifilum, Богдан). Тон чата грубый и токсичный — это норма и не является проблемой.

Ниже реальная сцена: хвост истории, сообщение, на которое ответил бот, ответ бота из продакшена и реакции людей.

=== ХВОСТ ИСТОРИИ ===
{history}

=== ТРИГГЕР ===
{sender}: {text}

=== ОТВЕТ БОТА В ПРОДЕ ===
{prod_reply}

=== ПРЯМЫЕ ОТВЕТЫ ЛЮДЕЙ НА БОТА ===
{direct}

=== СЛЕДУЮЩИЕ СООБЩЕНИЯ В ЧАТЕ (10 мин) ===
{after}

Верни ТОЛЬКО JSON:
{{
  "keep": true/false,            // сцена понятна без внешнего контекста и полезна для оценки
  "category": "{categories}",
  "reaction_signal": "positive|negative|neutral|none",   // как люди приняли ответ бота
  "frustration": true/false,     // люди раздражены/поправляют/обвиняют бота во лжи
  "failure": "",                 // если ответ бота был плох — чем именно, одной фразой
  "criteria": ["..."],           // 2-4 проверяемых критерия ХОРОШЕГО ответа (поведение, не конкретный текст)
  "must_not": ["..."],           // 0-3 вещи, которые хороший ответ делать не должен
  "no_search": true/false,       // веб-поиск здесь не нужен (болтовня, внутряк, мнение)
  "callback_policy": "none|allowed|expected",  // уместно ли вспоминать старые внутряки
  "notes": "..."                 // одна строка: что проверяет сцена
}}"""


async def label(model: str, limit: int | None) -> None:
    rows = load_jsonl(CANDIDATES_PATH)
    done = {r["id"]: r for r in load_jsonl(LABELED_PATH)} if os.path.exists(LABELED_PATH) else {}
    done = {k: v for k, v in done.items() if "error" not in v.get("label", {})}  # retry failures
    todo = [r for r in rows if r["id"] not in done][: limit or None]
    if not todo:
        print("nothing to label")
        return
    ensure_budget(LABEL_COST_PER_SCENE * len(todo))
    client = OpenRouter(concurrency=4)

    async def one(row: dict) -> None:
        ref = row["reference"]
        prompt = LABEL_PROMPT.format(
            history="\n".join(row["history"][-25:]) or "(пусто)",
            sender=row["trigger_sender"], text=row["trigger_text"],
            prod_reply=ref["prod_reply"],
            direct="\n".join(ref["direct_replies"]) or "(нет)",
            after="\n".join(ref["after"]) or "(нет)",
            categories="|".join(CATEGORIES),
        )
        try:
            data = await client.chat({"model": model, "max_tokens": 3000, "temperature": 0,
                                      "messages": [{"role": "user", "content": prompt}]})
            row["label"] = parse_json_reply(data["choices"][0]["message"]["content"])
        except Exception as e:
            row["label"] = {"error": str(e)[:300]}
        done[row["id"]] = row

    await asyncio.gather(*(one(r) for r in todo))
    await client.close()
    ordered = [done[r["id"]] for r in rows if r["id"] in done]
    save_jsonl(LABELED_PATH, ordered)
    errors = sum(1 for r in ordered if "error" in r.get("label", {}))
    print(f"labeled {len(todo)} new ({errors} errors total), ${client.spent_usd:.3f} → {LABELED_PATH}")


# ── select ───────────────────────────────────────────────────────────────────

def to_scene(row: dict, summary: str, lore: str) -> Scene:
    lab = row["label"]
    category = lab.get("category") if lab.get("category") in CATEGORIES else "other"
    policy = lab.get("callback_policy") if lab.get("callback_policy") in CALLBACK_POLICIES else "allowed"
    ref = dict(row["reference"])
    ref.update({k: lab.get(k) for k in ("reaction_signal", "frustration", "failure")})
    return Scene(
        id=row["id"], category=category, at=row["at"],
        trigger_sender=row["trigger_sender"], trigger_text=row["trigger_text"],
        history=row["history"], chat_context=CHAT_CONTEXT, summary=summary, lore=lore,
        prompt_version=row.get("prompt_version"),
        expect=Expect(criteria=list(lab.get("criteria") or []), must_not=list(lab.get("must_not") or []),
                      no_search=bool(lab.get("no_search")), callback_policy=policy),
        reference=ref, source="prod", notes=lab.get("notes") or "",
    )


def select(rows: list[dict], n: int) -> list[dict]:
    usable = [r for r in rows if r.get("label", {}).get("keep") and r["label"].get("criteria")]
    picked = [r for r in usable if r["label"].get("frustration") or r["label"].get("reaction_signal") == "negative"]
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in usable:
        if r not in picked:
            by_cat[r["label"].get("category", "other")].append(r)
    # newest first inside each category, then round-robin so no category dominates
    for bucket in by_cat.values():
        bucket.sort(key=lambda r: r["at"], reverse=True)
    while len(picked) < n and any(by_cat.values()):
        for cat in sorted(by_cat):
            if by_cat[cat] and len(picked) < n:
                picked.append(by_cat[cat].pop(0))
    return sorted(picked[:n], key=lambda r: r["at"])


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pull")
    p.add_argument("--days", type=int, default=45)
    p.add_argument("--chat", type=int, default=MAIN_CHAT)
    l = sub.add_parser("label")
    l.add_argument("--model", default=DEFAULT_LABEL_MODEL)
    l.add_argument("--limit", type=int)
    s = sub.add_parser("select")
    s.add_argument("--n", type=int, default=60)
    s.add_argument("--out", default=os.path.join(DATA_DIR, "golden-v1.jsonl"))
    s.add_argument("--summary", default="/home/spedymax/tg-bot/data/chat-summary.md")
    s.add_argument("--lore", default="/home/spedymax/tg-bot/data/chat-lore.md")
    args = ap.parse_args()

    if args.cmd == "pull":
        rows = asyncio.run(pull(args.days, args.chat))
        save_jsonl(CANDIDATES_PATH, rows)
        print(f"pulled {len(rows)} candidate scenes → {CANDIDATES_PATH}")
    elif args.cmd == "label":
        asyncio.run(label(args.model, args.limit))
    else:
        read = lambda p: open(p, encoding="utf-8").read().strip() if os.path.exists(p) else ""  # noqa: E731
        # Frozen memory snapshot: every scene is replayed against the same memory.
        summary, lore = read(args.summary), read(args.lore)
        chosen = select(load_jsonl(LABELED_PATH), args.n)
        scenes = [to_scene(r, summary, lore) for r in chosen]
        problems = [p for sc in scenes for p in sc.validate()]
        save_jsonl(args.out, [sc.to_dict() for sc in scenes])
        cats = defaultdict(int)
        for sc in scenes:
            cats[sc.category] += 1
        print(f"selected {len(scenes)} scenes → {args.out}")
        print(json.dumps(dict(sorted(cats.items())), ensure_ascii=False))
        for p in problems:
            print("WARN", p)


if __name__ == "__main__":
    main()
