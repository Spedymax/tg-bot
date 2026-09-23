#!/home/spedymax/venv/bin/python
"""Telegram bots → Prometheus textfile metrics (run every minute from cron).

node_exporter's textfile collector picks up textfile/tg_bots.prom. Everything here is
cheap and read-only: process table, the tail of the bot logs, a few indexed SQL counts,
and (hourly, cached) the OpenRouter credit balance.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import psutil
import psycopg
from dotenv import dotenv_values

OUT = "/home/spedymax/monitoring/textfile/tg_bots.prom"
ENV = dotenv_values("/home/spedymax/tg-bot/.env")
STATE = "/home/spedymax/tg-bot/moltbot_state.json"
CREDITS_CACHE = "/home/spedymax/monitoring/.openrouter_credits.json"
MAIN_CHAT = -1001294162183
BOTS = {  # label → substring of the process command line
    "main": "tg-bot/src/main.py",
    "casino_miniapp": "run_miniapp.py",
    "btc": "scripts/btc.py",
    "love": "scripts/love.py",
    "bot_manager": "bot_manager",
}
LOGS = {"main": "/home/spedymax/logs/main-bot.log"}
LOG_TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ - [\w.]+ - (ERROR|WARNING|CRITICAL) - ")

lines: list[str] = []


def metric(name: str, value, help_: str | None = None, mtype: str = "gauge", **labels) -> None:
    if help_ and not any(l.startswith(f"# HELP {name} ") for l in lines):
        lines.append(f"# HELP {name} {help_}")
        lines.append(f"# TYPE {name} {mtype}")
    lab = ",".join(f'{k}="{v}"' for k, v in labels.items())
    lines.append(f"{name}{{{lab}}} {value}" if lab else f"{name} {value}")


def processes() -> None:
    now = time.time()
    found: dict[str, list[psutil.Process]] = {k: [] for k in BOTS}
    for p in psutil.process_iter(["cmdline", "create_time", "name"]):
        cmd = " ".join(p.info.get("cmdline") or [])
        if "tg_bots_exporter" in cmd:
            continue
        for label, needle in BOTS.items():
            if needle in cmd and ("python" in cmd or "gunicorn" in cmd):
                found[label].append(p)
    for label, procs in found.items():
        metric("tg_bot_up", 1 if procs else 0, "1 if the bot process is running", bot=label)
        metric("tg_bot_processes", len(procs), "number of matching processes (>1 for main = duplicate polling!)", bot=label)
        if procs:
            try:
                oldest = min(p.info["create_time"] for p in procs)
                rss = sum(p.memory_info().rss for p in procs)
                cpu = sum(sum(p.cpu_times()[:2]) for p in procs)
            except psutil.Error:
                continue
            metric("tg_bot_uptime_seconds", round(now - oldest), "seconds since the oldest matching process started", bot=label)
            metric("tg_bot_rss_bytes", rss, "resident memory of the bot processes", bot=label)
            metric("tg_bot_cpu_seconds_total", round(cpu, 2), "user+system CPU seconds", "counter", bot=label)


def log_errors() -> None:
    cutoff = datetime.now() - timedelta(minutes=5)
    for label, path in LOGS.items():
        counts = {"ERROR": 0, "WARNING": 0, "CRITICAL": 0}
        try:
            with open(path, "rb") as f:
                f.seek(0, 2)
                f.seek(max(0, f.tell() - 400_000))
                for raw in f.read().decode("utf-8", "replace").splitlines():
                    m = LOG_TS.match(raw)
                    if m and datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S") >= cutoff:
                        counts[m.group(2)] += 1
        except FileNotFoundError:
            pass
        for level, n in counts.items():
            metric("tg_bot_log_lines_5m", n, "log lines of that level in the last 5 minutes", log=label, level=level.lower())


def database() -> None:
    dsn = dict(host=ENV.get("DB_HOST") or "localhost", port=ENV.get("DB_PORT") or 5432,
               user=ENV.get("DB_USER") or "postgres", password=ENV.get("DB_PASSWORD"),
               dbname=ENV.get("DB_NAME") or "server-tg-pisunchik", connect_timeout=5)
    with psycopg.connect(**dsn) as conn, conn.cursor() as cur:
        cur.execute("SET statement_timeout = '5s'")
        cur.execute("SELECT EXTRACT(EPOCH FROM (NOW() AT TIME ZONE 'UTC' - MAX(timestamp) FILTER (WHERE user_id <> 0))), "
                    "EXTRACT(EPOCH FROM (NOW() AT TIME ZONE 'UTC' - MAX(timestamp) FILTER (WHERE user_id = 0))) "
                    "FROM messages WHERE chat_id = %s AND timestamp > NOW() - INTERVAL '30 days'", (MAIN_CHAT,))
        human, bot = cur.fetchone()
        if human is not None:
            metric("tg_chat_last_message_age_seconds", round(human), "seconds since the last message", who="human")
        if bot is not None:
            metric("tg_chat_last_message_age_seconds", round(bot), who="jarvis")
        cur.execute("SELECT COUNT(*) FILTER (WHERE user_id <> 0), COUNT(*) FILTER (WHERE user_id = 0) FROM messages "
                    "WHERE chat_id = %s AND timestamp > NOW() - INTERVAL '1 hour'", (MAIN_CHAT,))
        h, b = cur.fetchone()
        metric("tg_chat_messages_1h", h, "messages in the main chat in the last hour", who="human")
        metric("tg_chat_messages_1h", b, who="jarvis")
        cur.execute("SELECT kind, COUNT(*), COALESCE(SUM(cost_usd), 0) FROM llm_traces "
                    "WHERE created_at > date_trunc('day', NOW() AT TIME ZONE 'Europe/Kyiv') AT TIME ZONE 'Europe/Kyiv' GROUP BY kind")
        for kind, n, cost in cur.fetchall():
            metric("tg_llm_calls_today", n, "LLM calls since Kyiv midnight", kind=kind)
            metric("tg_llm_cost_usd_today", round(float(cost), 5), "LLM spend since Kyiv midnight (OpenRouter-reported)", kind=kind)
        cur.execute("SELECT COUNT(*) FROM memory_items WHERE chat_id = %s AND status = 'active' "
                    "AND (expires_at IS NULL OR expires_at > NOW())", (MAIN_CHAT,))
        metric("tg_memory_active_items", cur.fetchone()[0], "active Memory v2 items")
        cur.execute("SELECT EXTRACT(EPOCH FROM NOW() - updated_at) FROM memory_extract_state WHERE chat_id = %s", (MAIN_CHAT,))
        row = cur.fetchone()
        if row:
            metric("tg_memory_extract_age_seconds", round(row[0]), "seconds since the last Memory v2 extraction")
        cur.execute("SELECT id, name, hp, max_hp, phase, rage, status, EXTRACT(EPOCH FROM ends_at - NOW()) "
                    "FROM boss_events ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        if row:
            eid, name, hp, max_hp, phase, rage, status, ends_in = row
            active = 1 if status == "active" else 0
            metric("tg_boss_active", active, "1 while the Pudge event is running", event=eid)
            metric("tg_boss_hp", hp, "current boss HP (captures nightly regen, unlike the damage log)", event=eid)
            metric("tg_boss_max_hp", max_hp, "boss max HP", event=eid)
            metric("tg_boss_phase", phase or 0, "0 normal, 1 hijack, 2 rage", event=eid)
            metric("tg_boss_rage", 1 if rage else 0, "rage (x2 damage) active", event=eid)
            if ends_in is not None:
                metric("tg_boss_ends_in_seconds", max(0, round(ends_in)), "seconds until the event ends", event=eid)


def reasoning_level() -> None:
    try:
        level = json.load(open(STATE)).get("reasoning_effort") or "minimal"
    except Exception:
        return
    for lv in ("minimal", "low", "medium", "high"):
        metric("tg_jarvis_reasoning_level", 1 if lv == level else 0, "active /reasoning level (1 = current)", level=lv)


def openrouter_credits() -> None:
    key = ENV.get("OPENROUTER_API_KEY")
    if not key:
        return
    cache = {}
    try:
        cache = json.load(open(CREDITS_CACHE))
    except Exception:
        pass
    if time.time() - cache.get("at", 0) > 3600:
        req = urllib.request.Request("https://openrouter.ai/api/v1/credits", headers={"Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)["data"]
        cache = {"at": time.time(), "left": float(data["total_credits"]) - float(data["total_usage"])}
        tmp = CREDITS_CACHE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(cache, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, CREDITS_CACHE)
    metric("tg_openrouter_credits_usd", round(cache["left"], 3), "OpenRouter balance left (refreshed hourly)")


def ollama() -> None:
    try:
        with urllib.request.urlopen("http://192.168.1.3:11434/api/tags", timeout=2) as r:
            metric("tg_ollama_up", 1 if r.status == 200 else 0, "local Ollama on the Windows PC reachable")
    except Exception:
        metric("tg_ollama_up", 0, "local Ollama on the Windows PC reachable")


def main() -> None:
    for step in (processes, log_errors, database, reasoning_level, openrouter_credits, ollama):
        try:
            step()
            metric("tg_exporter_step_ok", 1, "1 if this exporter step succeeded", step=step.__name__)
        except Exception:
            metric("tg_exporter_step_ok", 0, "1 if this exporter step succeeded", step=step.__name__)
    metric("tg_exporter_last_run_timestamp", int(time.time()), "unix time of the last exporter run")
    tmp = OUT + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, OUT)


if __name__ == "__main__":
    main()
