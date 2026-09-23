#!/usr/bin/env python3
"""Build and upload the «Telegram-боты» Grafana dashboard.

Data: Postgres views in schema `grafana` (role grafana_ro, no message/memory text) via the
`tgbot-pg` datasource, plus Prometheus textfile metrics from tg_bots_exporter.py.
Re-run to update:  python3 /home/spedymax/monitoring/grafana_tg_bots_dashboard.py
"""
import base64
import json
import re
import urllib.request

PG = {"type": "grafana-postgresql-datasource", "uid": "tgbot-pg"}
PROM = {"type": "prometheus", "uid": "aeufknklz6waof"}
UID = "tg-bots"

panels: list[dict] = []
_y = 0
_next_id = 1


def _pid() -> int:
    global _next_id
    _next_id += 1
    return _next_id


def row(title: str) -> None:
    global _y
    panels.append({"type": "row", "title": title, "id": _pid(), "collapsed": False,
                   "gridPos": {"h": 1, "w": 24, "x": 0, "y": _y}, "panels": []})
    _y += 1


class Line:
    """Lay panels left→right; start a new line when the width runs out."""

    def __init__(self, h: int):
        self.h, self.x = h, 0

    def place(self, panel: dict, w: int) -> None:
        global _y
        if self.x + w > 24:
            _y += self.h
            self.x = 0
        panel["gridPos"] = {"h": self.h, "w": w, "x": self.x, "y": _y}
        panel["id"] = _pid()
        panels.append(panel)
        self.x += w

    def end(self) -> None:
        global _y
        _y += self.h


def pg(sql: str, fmt: str = "time_series", ref: str = "A") -> dict:
    return {"datasource": PG, "format": fmt, "rawQuery": True, "editorMode": "code", "rawSql": sql.strip(), "refId": ref}


def prom(expr: str, legend: str = "", ref: str = "A", instant: bool = False) -> dict:
    t = {"datasource": PROM, "expr": expr, "legendFormat": legend, "refId": ref}
    if instant:
        t.update({"instant": True, "range": False})
    return t


def stat(title, targets, unit="none", thresholds=None, desc="", mappings=None, decimals=None, color_mode="background",
         text_mode="auto", graph=False):
    steps = thresholds or [{"color": "green", "value": None}]
    p = {"type": "stat", "title": title, "description": desc, "targets": targets,
         "fieldConfig": {"defaults": {"unit": unit, "thresholds": {"mode": "absolute", "steps": steps},
                                      "mappings": mappings or [], "color": {"mode": "thresholds"}}, "overrides": []},
         "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                     "colorMode": color_mode, "graphMode": "area" if graph else "none", "textMode": text_mode,
                     "justifyMode": "auto", "orientation": "auto"}}
    if decimals is not None:
        p["fieldConfig"]["defaults"]["decimals"] = decimals
    return p


def ts(title, targets, unit="none", stack=False, desc="", draw="line", fill=15, legend_calcs=None, max_=None, min_=None,
       overrides=None):
    d = {"unit": unit, "custom": {"drawStyle": draw, "lineWidth": 2, "fillOpacity": fill, "showPoints": "auto",
                                  "spanNulls": True, "stacking": {"mode": "normal" if stack else "none", "group": "A"},
                                  "barAlignment": 0}}
    if max_ is not None:
        d["max"] = max_
    if min_ is not None:
        d["min"] = min_
    return {"type": "timeseries", "title": title, "description": desc, "targets": targets,
            "fieldConfig": {"defaults": d, "overrides": overrides or []},
            "options": {"legend": {"displayMode": "table" if legend_calcs else "list", "placement": "bottom",
                                   "calcs": legend_calcs or []},
                        "tooltip": {"mode": "multi", "sort": "desc"}}}


def bars(title, targets, unit="none", desc="", horizontal=True, stack=False):
    return {"type": "barchart", "title": title, "description": desc, "targets": targets,
            "fieldConfig": {"defaults": {"unit": unit, "color": {"mode": "palette-classic"},
                                         "custom": {"fillOpacity": 80, "lineWidth": 1}}, "overrides": []},
            "options": {"orientation": "horizontal" if horizontal else "vertical", "showValue": "auto",
                        "stacking": "normal" if stack else "none", "legend": {"displayMode": "list", "placement": "bottom"},
                        "xTickLabelMaxLength": 24, "barWidth": 0.8}}


def pie(title, targets, desc="", unit="none"):
    return {"type": "piechart", "title": title, "description": desc, "targets": targets,
            "fieldConfig": {"defaults": {"unit": unit, "color": {"mode": "palette-classic"}}, "overrides": []},
            "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": True},
                        "pieType": "donut", "legend": {"displayMode": "table", "placement": "right", "values": ["value", "percent"]},
                        "displayLabels": []}}


def table(title, targets, desc="", overrides=None):
    return {"type": "table", "title": title, "description": desc, "targets": targets,
            "fieldConfig": {"defaults": {"custom": {"align": "auto", "cellOptions": {"type": "auto"}}}, "overrides": overrides or []},
            "options": {"showHeader": True, "cellHeight": "sm", "footer": {"show": False}}}


def gauge(title, targets, unit="none", max_=None, thresholds=None, desc=""):
    d = {"unit": unit, "min": 0, "thresholds": {"mode": "absolute", "steps": thresholds or [{"color": "green", "value": None}]}}
    if max_ is not None:
        d["max"] = max_
    return {"type": "gauge", "title": title, "description": desc, "targets": targets,
            "fieldConfig": {"defaults": d, "overrides": []},
            "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                        "showThresholdLabels": False, "showThresholdMarkers": True}}


def last24h(panel: dict) -> dict:
    """Prometheus history starts 2026-09-23: on a 7-day range the auto step (~20 min) finds no samples yet."""
    panel["timeFrom"] = "24h"
    return panel


UPDOWN = [{"type": "value", "options": {"0": {"text": "DOWN", "color": "red"}, "1": {"text": "UP", "color": "green"}}}]
RED_GREEN = [{"color": "red", "value": None}, {"color": "green", "value": 1}]

# ═════════════════════════════ 1. Обзор ═════════════════════════════
row("🟢 Обзор")
L = Line(4)
for label, title in [("main", "Основной бот"), ("bot_manager", "Bot manager"), ("casino_miniapp", "Казино-миниапп"), ("btc", "BTC-бот")]:
    L.place(stat(title, [prom(f'max(tg_bot_up{{bot="{label}"}})', instant=True)], mappings=UPDOWN, thresholds=RED_GREEN,
                 desc="Процесс найден в таблице процессов (экспортёр раз в минуту)"), 3)
L.place(stat("Процессов main.py", [prom('max(tg_bot_processes{bot="main"})', instant=True)],
             thresholds=[{"color": "red", "value": None}, {"color": "green", "value": 1}, {"color": "red", "value": 2}],
             desc="Должен быть ровно 1. Два = двойной поллинг (409 от Telegram)."), 3)
L.place(stat("Аптайм бота", [prom('max(tg_bot_uptime_seconds{bot="main"})', instant=True)], unit="s", color_mode="none"), 3)
L.place(stat("Ошибки в логе (5 мин)", [prom('sum(tg_bot_log_lines_5m{level=~"error|critical"})', instant=True)],
             thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 1}, {"color": "red", "value": 5}]), 3)
L.place(stat("OpenRouter баланс", [prom("max(tg_openrouter_credits_usd)", instant=True)], unit="currencyUSD", decimals=2,
             thresholds=[{"color": "red", "value": None}, {"color": "orange", "value": 1.5}, {"color": "green", "value": 5}],
             desc="Общий ключ прода и evals. Алерт в личку при < $1.5"), 3)
L.end()
L = Line(4)
L.place(stat("Ollama (ПК)", [prom("max(tg_ollama_up)", instant=True)], mappings=UPDOWN, thresholds=RED_GREEN,
             desc="Локальная модель на Windows-ПК; DOWN = ПК спит, работают фоллбэки"), 3)
L.place(stat("Reasoning", [prom('max by (level) (tg_jarvis_reasoning_level) == 1', "{{level}}", instant=True)],
             text_mode="name", color_mode="none", desc="Текущий /reasoning (сбрасывается на minimal через 3 ч тишины)"), 3)
L.place(stat("Последнее сообщение людей", [prom('max(tg_chat_last_message_age_seconds{who="human"})', instant=True)],
             unit="s", color_mode="none"), 3)
L.place(stat("Ответов Джарвиса сегодня", [prom('sum(tg_llm_calls_today{kind="persona"})', instant=True)], color_mode="none"), 3)
L.place(stat("Потрачено сегодня", [prom("sum(tg_llm_cost_usd_today)", instant=True)], unit="currencyUSD", decimals=3,
             color_mode="none", desc="Сумма стоимости по OpenRouter с полуночи по Киеву (Gemini бесплатный — 0)"), 3)
L.place(stat("Память v2: записей", [prom("max(tg_memory_active_items)", instant=True)], color_mode="none"), 3)
L.place(stat("Память v2: последний разбор", [prom("max(tg_memory_extract_age_seconds)", instant=True)], unit="s",
             thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 43200}, {"color": "red", "value": 86400}]), 3)
L.place(stat("Экспортёр", [prom("time() - max(tg_exporter_last_run_timestamp)", instant=True)], unit="s",
             thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 180}],
             desc="Сколько секунд назад отработал tg_bots_exporter.py (cron раз в минуту)"), 3)
L.end()

# ═════════════════════════════ 2. Джарвис ═════════════════════════════
row("🤖 Джарвис — ответы, задержка, деньги")
L = Line(8)
L.place(ts("Ответы Джарвиса по итогу", [pg("""
SELECT $__timeGroupAlias(created_at, $__interval, 0), outcome AS metric, COUNT(*) AS value
FROM traces WHERE kind = 'persona' AND $__timeFilter(created_at) GROUP BY 1, 2 ORDER BY 1""")],
           stack=True, draw="bars", fill=80, desc="ok / empty / error:* / refusal"), 8)
L.place(ts("Задержка ответа", [pg("""
SELECT $__timeGroupAlias(created_at, $__interval),
       percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) AS "p50",
       percentile_cont(0.9) WITHIN GROUP (ORDER BY latency_ms) AS "p90",
       MAX(latency_ms) AS "max"
FROM traces WHERE kind = 'persona' AND $__timeFilter(created_at) GROUP BY 1 ORDER BY 1""")],
           unit="ms", legend_calcs=["mean", "max"], desc="От получения сообщения до готового ответа (вкл. поиск и фоллбэки)"), 8)
L.place(ts("Стоимость по типу вызова", [pg("""
SELECT $__timeGroupAlias(created_at, $__interval, 0), kind AS metric, SUM(cost_usd) AS value
FROM traces WHERE $__timeFilter(created_at) GROUP BY 1, 2 ORDER BY 1""")],
           unit="currencyUSD", stack=True, draw="bars", fill=80, legend_calcs=["sum"]), 8)
L.end()
L = Line(8)
L.place(ts("Токены (ответы)", [pg("""
SELECT $__timeGroupAlias(created_at, $__interval, 0), SUM(prompt_tokens) AS "вход", SUM(cached_tokens) AS "из кэша",
       SUM(completion_tokens) AS "выход (вкл. reasoning)"
FROM traces WHERE kind = 'persona' AND $__timeFilter(created_at) GROUP BY 1 ORDER BY 1""")], legend_calcs=["sum"]), 8)
L.place(ts("Кэш промпта, % входных токенов", [pg("""
SELECT $__timeGroupAlias(created_at, $__interval), 100.0 * SUM(cached_tokens) / NULLIF(SUM(prompt_tokens), 0) AS "кэш %"
FROM traces WHERE kind = 'persona' AND $__timeFilter(created_at) GROUP BY 1 ORDER BY 1""")],
           unit="percent", max_=100, min_=0, desc="Сколько входа отдал кэш провайдера (дешевле ~в 3 раза)"), 8)
L.place(ts("Фоллбэки и поиск", [pg("""
SELECT $__timeGroupAlias(created_at, $__interval, 0),
       COUNT(*) FILTER (WHERE attempts > 1) AS "фоллбэк (>1 провайдера)",
       COUNT(*) FILTER (WHERE search_calls > 0) AS "был веб-поиск",
       COUNT(*) FILTER (WHERE memory_hits > 0) AS "нашлась память v2"
FROM traces WHERE kind = 'persona' AND $__timeFilter(created_at) GROUP BY 1 ORDER BY 1""")], draw="bars", fill=70), 8)
L.end()
L = Line(8)
L.place(pie("Кто отвечал (провайдер)", [pg("""
SELECT COALESCE(final_provider, '—') AS provider, COUNT(*) AS n FROM traces
WHERE kind = 'persona' AND $__timeFilter(created_at) GROUP BY 1 ORDER BY 2 DESC""", "table")]), 6)
L.place(pie("Reasoning", [pg("""
SELECT COALESCE(NULLIF(reasoning, ''), '—') AS level, COUNT(*) AS n FROM traces
WHERE kind = 'persona' AND $__timeFilter(created_at) GROUP BY 1""", "table")]), 6)
L.place(pie("Версия промпта", [pg("""
SELECT 'v' || COALESCE(prompt_version::text, '?') AS version, COUNT(*) AS n FROM traces
WHERE kind = 'persona' AND $__timeFilter(created_at) GROUP BY 1""", "table")]), 6)
L.place(pie("Причины веб-поиска", [pg("""
SELECT COALESCE(reason, '—') AS reason, COUNT(*) AS n FROM trace_tools
WHERE tool = 'web_search' AND $__timeFilter(created_at) GROUP BY 1""", "table")]), 6)
L.end()
L = Line(8)
L.place(bars("Размер контекста по секциям (средн. символов)", [pg("""
SELECT key AS section, ROUND(AVG(value::text::numeric)) AS chars
FROM traces, jsonb_each(sections)
WHERE kind = 'persona' AND $__timeFilter(created_at) AND value::text ~ '^[0-9]+$'
GROUP BY 1 HAVING AVG(value::text::numeric) > 0 ORDER BY 2 DESC""", "table")], desc="Что уходит в промпт: личность, история, сводка, память, время…"), 8)
L.place(ts("Длина ответа", [pg("""
SELECT $__timeGroupAlias(created_at, $__interval), AVG(reply_chars) AS "средняя", MAX(reply_chars) AS "макс"
FROM traces WHERE kind = 'persona' AND outcome = 'ok' AND $__timeFilter(created_at) GROUP BY 1 ORDER BY 1""")], unit="none"), 8)
_errors = table("Ошибки провайдеров", [pg("""
SELECT created_at AS "время", kind AS "тип", provider AS "провайдер", model AS "модель", latency_ms AS "мс", LEFT(error, 160) AS "ошибка"
FROM trace_attempts WHERE NOT ok AND $__timeFilter(created_at) ORDER BY created_at DESC LIMIT 50""", "table")])
_errors["fieldConfig"]["defaults"]["noValue"] = "Ошибок нет ✅"
L.place(_errors, 8)
L.end()
L = Line(9)
L.place(table("Последние ответы Джарвиса (трейсы)", [pg("""
SELECT created_at AS "время", outcome AS "итог", final_model AS "модель", final_provider AS "провайдер",
       reasoning, 'v' || prompt_version AS "промпт", latency_ms AS "мс", prompt_tokens AS "вход", cached_tokens AS "кэш",
       completion_tokens AS "выход", ROUND(cost_usd::numeric, 4) AS "$", search_calls AS "поиск", memory_hits AS "память",
       attempts AS "попыток", reply_chars AS "символов", trace_id
FROM traces WHERE kind = 'persona' AND $__timeFilter(created_at) ORDER BY created_at DESC LIMIT 40""", "table")],
      desc="trace_id → /trace в чате показывает то же подробно"), 24)
L.end()

# ═════════════════════════════ 3. Реакции и фидбек ═════════════════════════════
row("😀 Реакции бота и фидбек людей")
L = Line(8)
L.place(ts("Реакции бота: поставил / промолчал", [pg("""
SELECT $__timeGroupAlias(created_at, $__interval, 0),
       COUNT(*) FILTER (WHERE outcome LIKE 'react:%') AS "поставил реакцию",
       COUNT(*) FILTER (WHERE outcome = 'ignore') AS "промолчал",
       COUNT(*) FILTER (WHERE outcome LIKE 'error%') AS "ошибка"
FROM traces WHERE kind = 'reaction' AND $__timeFilter(created_at) GROUP BY 1 ORDER BY 1""")], draw="bars", fill=80, stack=True), 8)
L.place(bars("Какие эмодзи ставит бот", [pg("""
SELECT SUBSTRING(outcome FROM 7) AS emoji, COUNT(*) AS n FROM traces
WHERE kind = 'reaction' AND outcome LIKE 'react:%' AND $__timeFilter(created_at) GROUP BY 1 ORDER BY 2 DESC""", "table")]), 8)
L.place(ts("Фидбек людей на сообщения Джарвиса", [pg("""
SELECT $__timeGroupAlias(created_at, $__interval, 0),
       COUNT(*) FILTER (WHERE polarity > 0) AS "👍 позитив",
       COUNT(*) FILTER (WHERE polarity < 0) AS "👎 негатив",
       COUNT(*) FILTER (WHERE polarity = 0) AS "нейтрально"
FROM feedback WHERE $__timeFilter(created_at) GROUP BY 1 ORDER BY 1""")], draw="bars", fill=80, stack=True,
           desc="Реакции людей на ответы Джарвиса + фразы «не тащи/кринж/база/ору» в ответ ему"), 8)
L.end()
L = Line(7)
L.place(pie("Эмодзи людей на Джарвиса", [pg("""
SELECT emoji, COUNT(*) AS n FROM feedback WHERE emoji IS NOT NULL AND $__timeFilter(created_at) GROUP BY 1 ORDER BY 2 DESC""", "table")]), 8)
L.place(stat("Доля ответов с реакцией людей", [pg("""
SELECT 100.0 * COUNT(DISTINCT t.trace_id) FILTER (WHERE f.trace_id IS NOT NULL) / NULLIF(COUNT(DISTINCT t.trace_id), 0) AS pct
FROM traces t LEFT JOIN feedback f ON f.trace_id = t.trace_id
WHERE t.kind = 'persona' AND $__timeFilter(t.created_at)""", "table")], unit="percent", decimals=0, color_mode="none"), 8)
L.place(stat("Позитив / негатив", [pg("""
SELECT COUNT(*) FILTER (WHERE polarity > 0) AS "позитив", COUNT(*) FILTER (WHERE polarity < 0) AS "негатив"
FROM feedback WHERE $__timeFilter(created_at)""", "table")], color_mode="none"), 8)
L.end()

# ═════════════════════════════ 4. Память v2 ═════════════════════════════
row("🧠 Память v2")
L = Line(8)
L.place(bars("Активные записи по типу", [pg("""
SELECT kind, COUNT(*) AS n FROM memory_items WHERE status = 'active' AND (expires_at IS NULL OR expires_at > NOW())
GROUP BY 1 ORDER BY 2 DESC""", "table")]), 6)
L.place(bars("Записи по людям", [pg("""
SELECT COALESCE(subject_name, 'общее') AS subject, COUNT(*) AS n FROM memory_items
WHERE status IN ('active', 'candidate') AND (expires_at IS NULL OR expires_at > NOW()) GROUP BY 1 ORDER BY 2 DESC""", "table")]), 6)
L.place(ts("Решения политики записи", [pg("""
SELECT $__timeGroupAlias(created_at, $__interval, 0), action AS metric, COUNT(*) AS value
FROM memory_audit WHERE $__timeFilter(created_at) GROUP BY 1, 2 ORDER BY 1""")], draw="bars", fill=80, stack=True,
           desc="insert / confirm / supersede / reject / forget / correct / pin"), 6)
L.place(table("Почему отклонено", [pg("""
SELECT reason AS "причина", COUNT(*) AS "сколько" FROM memory_audit
WHERE action = 'reject' AND $__timeFilter(created_at) GROUP BY 1 ORDER BY 2 DESC""", "table")]), 6)
L.end()
L = Line(7)
L.place(ts("Разборы памяти", [pg("""
SELECT $__timeGroupAlias(created_at, $__interval, 0), outcome AS metric, COUNT(*) AS value
FROM traces WHERE kind = 'memory_extract' AND $__timeFilter(created_at) GROUP BY 1, 2 ORDER BY 1""")], draw="bars", fill=80, stack=True), 8)
L.place(ts("Ответы, где нашлась память", [pg("""
SELECT $__timeGroupAlias(created_at, $__interval), 100.0 * COUNT(*) FILTER (WHERE memory_hits > 0) / COUNT(*) AS "% ответов с памятью"
FROM traces WHERE kind = 'persona' AND $__timeFilter(created_at) GROUP BY 1 ORDER BY 1""")], unit="percent", max_=100, min_=0,
           desc="В режиме shadow память ищется и логируется, но в промпт не попадает"), 8)
L.place(table("Самые используемые записи", [pg("""
SELECT id, COALESCE(subject_name, '—') AS "про кого", kind AS "тип", use_count AS "использований", last_used_at AS "последний раз",
       ROUND(confidence::numeric, 2) AS "уверенность", expires_at AS "истекает"
FROM memory_items WHERE status = 'active' ORDER BY use_count DESC, last_seen_at DESC LIMIT 20""", "table")],
      desc="Тексты записей здесь намеренно не показываются — смотри /mem в чате"), 8)
L.end()

# ═════════════════════════════ 5. Служебные LLM ═════════════════════════════
row("🛠 Служебные вызовы LLM (сводка, напоминания, медиа, викторина, пророчества…)")
L = Line(8)
L.place(ts("Вызовы по типу", [pg("""
SELECT $__timeGroupAlias(created_at, $__interval, 0), kind AS metric, COUNT(*) AS value
FROM traces WHERE kind <> 'persona' AND $__timeFilter(created_at) GROUP BY 1, 2 ORDER BY 1""")], draw="bars", fill=80, stack=True), 12)
L.place(table("Итоги по типам", [pg("""
SELECT kind AS "тип", COUNT(*) AS "вызовов", COUNT(*) FILTER (WHERE outcome NOT IN ('ok', 'ignore', 'skip') AND outcome NOT LIKE 'react:%') AS "ошибок",
       ROUND(AVG(latency_ms)) AS "ср. мс", ROUND(SUM(cost_usd)::numeric, 4) AS "$", SUM(prompt_tokens) AS "вход", SUM(completion_tokens) AS "выход"
FROM traces WHERE $__timeFilter(created_at) GROUP BY 1 ORDER BY 2 DESC""", "table")]), 12)
L.end()
L = Line(7)
L.place(pie("Провайдеры (все вызовы)", [pg("""
SELECT provider, COUNT(*) AS n FROM trace_attempts WHERE $__timeFilter(created_at) GROUP BY 1""", "table")]), 8)
L.place(pie("Модели (все вызовы)", [pg("""
SELECT model, COUNT(*) AS n FROM trace_attempts WHERE $__timeFilter(created_at) GROUP BY 1 ORDER BY 2 DESC""", "table")]), 8)
L.place(bars("Медиа: что разбирал Gemini", [pg("""
SELECT kind, COUNT(*) AS n FROM media WHERE $__timeFilter(created_at) GROUP BY 1 ORDER BY 2 DESC""", "table")],
      desc="Голосовые, кружки, стикеры, GIF, фото — описания кэшируются по файлу"), 8)
L.end()

# ═════════════════════════════ 6. Активность чата ═════════════════════════════
row("💬 Активность чата")
L = Line(8)
L.place(ts("Сообщения по людям", [pg("""
SELECT $__timeGroupAlias(ts, $__interval, 0), name AS metric, COUNT(*) AS value
FROM messages WHERE NOT is_bot AND chat_id = -1001294162183 AND $__timeFilter(ts) GROUP BY 1, 2 ORDER BY 1""")],
           draw="bars", fill=80, stack=True, legend_calcs=["sum"]), 12)
L.place(ts("Люди vs Джарвис", [pg("""
SELECT $__timeGroupAlias(ts, $__interval, 0), COUNT(*) FILTER (WHERE NOT is_bot) AS "люди", COUNT(*) FILTER (WHERE is_bot) AS "Джарвис"
FROM messages WHERE chat_id = -1001294162183 AND $__timeFilter(ts) GROUP BY 1 ORDER BY 1""")], legend_calcs=["sum"]), 12)
L.end()
L = Line(7)
L.place(bars("Кто больше пишет", [pg("""
SELECT name, COUNT(*) AS "сообщений" FROM messages WHERE NOT is_bot AND chat_id = -1001294162183 AND $__timeFilter(ts)
GROUP BY 1 ORDER BY 2 DESC LIMIT 10""", "table")]), 8)
L.place(bars("Активность по часам (Киев)", [pg("""
SELECT LPAD(EXTRACT(HOUR FROM (ts AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Kyiv'))::int::text, 2, '0') AS hour, COUNT(*) AS "сообщений"
FROM messages WHERE NOT is_bot AND chat_id = -1001294162183 AND $__timeFilter(ts) GROUP BY 1 ORDER BY 1""", "table")], horizontal=False), 8)
L.place(stat("Сообщений за период", [pg("""
SELECT COUNT(*) FILTER (WHERE NOT is_bot) AS "люди", COUNT(*) FILTER (WHERE is_bot) AS "Джарвис",
       COUNT(*) FILTER (WHERE NOT is_bot AND is_reply) AS "реплаев"
FROM messages WHERE chat_id = -1001294162183 AND $__timeFilter(ts)""", "table")], color_mode="none"), 8)
L.end()

# ═════════════════════════════ 7. Ивент Пуджа ═════════════════════════════
row("🗿 Ивент «Месть Пуджинио-Фамозы»")
CUR_EVENT = "(SELECT MAX(id) FROM boss_events)"
L = Line(7)
L.place(gauge("HP босса", [prom("max(tg_boss_hp)", "HP", instant=True)], max_=2500,
              thresholds=[{"color": "red", "value": None}, {"color": "orange", "value": 825}, {"color": "green", "value": 1650}],
              desc="≤66% — захват Джарвиса, ≤33% — ярость (x2 урон)"), 5)
L.place(stat("HP %", [prom("100 * max(tg_boss_hp) / max(tg_boss_max_hp)", instant=True)], unit="percent", decimals=1,
             thresholds=[{"color": "red", "value": None}, {"color": "orange", "value": 33}, {"color": "green", "value": 66}]), 4)
L.place(stat("Фаза", [prom("max(tg_boss_phase)", instant=True)], color_mode="background",
             mappings=[{"type": "value", "options": {"0": {"text": "обычная", "color": "green"}, "1": {"text": "захват Джарвиса", "color": "orange"},
                                                      "2": {"text": "ЯРОСТЬ", "color": "red"}}}]), 4)
L.place(stat("Ярость (x2)", [prom("max(tg_boss_rage)", instant=True)],
             mappings=[{"type": "value", "options": {"0": {"text": "нет", "color": "green"}, "1": {"text": "ДА", "color": "red"}}}]), 3)
L.place(stat("До конца ивента", [prom("max(tg_boss_ends_in_seconds)", instant=True)], unit="s", color_mode="none"), 4)
L.place(stat("Статус", [prom("max(tg_boss_active)", instant=True)],
             mappings=[{"type": "value", "options": {"0": {"text": "не идёт", "color": "text"}, "1": {"text": "идёт", "color": "green"}}}]), 4)
L.end()
L = Line(8)
L.place(last24h(ts("HP во времени", [prom("max(tg_boss_hp)", "HP"), prom("max(tg_boss_max_hp) * 0.66", "порог захвата (66%)", "B"),
                             prom("max(tg_boss_max_hp) * 0.33", "порог ярости (33%)", "C")],
           desc="Из метрики экспортёра — учитывает ночной реген (в журнале урона его нет). История — с 23.09.",
           overrides=[{"matcher": {"id": "byRegexp", "options": "порог.*"},
                       "properties": [{"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [10, 10]}},
                                      {"id": "custom.fillOpacity", "value": 0}]}])), 12)
L.place(ts("Урон по источникам (текущий ивент)", [pg(f"""
SELECT $__timeGroupAlias(created_at, $__interval, 0), source AS metric, SUM(amount) AS value
FROM boss_damage WHERE event_id = {CUR_EVENT} AND $__timeFilter(created_at) GROUP BY 1, 2 ORDER BY 1""")],
           draw="bars", fill=80, stack=True, legend_calcs=["sum"]), 12)
L.end()
L = Line(8)
L.place(bars("Урон по игрокам (весь ивент)", [pg(f"""
SELECT player_name AS "игрок", SUM(amount) AS "урон" FROM boss_damage WHERE event_id = {CUR_EVENT}
GROUP BY 1 ORDER BY 2 DESC""", "table")], desc="Лидер = MVP: неделя уважения Джарвиса + власть над ботом"), 8)
L.place(pie("Урон по источникам (весь ивент)", [pg(f"""
SELECT source, SUM(amount) AS dmg FROM boss_damage WHERE event_id = {CUR_EVENT} GROUP BY 1 ORDER BY 2 DESC""", "table")]), 8)
L.place(ts("Накопленный урон по игрокам", [pg(f"""
SELECT created_at AS time, player_name AS metric,
       SUM(amount) OVER (PARTITION BY player_name ORDER BY created_at) AS value
FROM boss_damage WHERE event_id = {CUR_EVENT} ORDER BY 1""")], draw="line", fill=0,
           desc="Гонка за MVP"), 8)
L.end()
L = Line(8)
L.place(bars("Данж по дням: победы / поражения", [pg("""
SELECT to_char(date, 'DD.MM') AS day, COUNT(*) FILTER (WHERE won) AS "победы", COUNT(*) FILTER (WHERE finished AND NOT won) AS "поражения",
       COUNT(*) FILTER (WHERE NOT finished) AS "не закончен"
FROM dungeon_runs WHERE date >= (SELECT MIN(started_at)::date FROM boss_events WHERE id = (SELECT MAX(id) FROM boss_events))
GROUP BY date ORDER BY date""", "table")], horizontal=False, stack=True), 8)
L.place(bars("Данж: комнат пройдено по игрокам", [pg("""
SELECT player_name AS "игрок", SUM(rooms_cleared) AS "комнат", COUNT(*) FILTER (WHERE won) AS "побед"
FROM dungeon_runs WHERE date >= (SELECT MIN(started_at)::date FROM boss_events WHERE id = (SELECT MAX(id) FROM boss_events))
GROUP BY 1 ORDER BY 2 DESC""", "table")]), 8)
L.place(table("Последние удары", [pg(f"""
SELECT created_at AS "время", player_name AS "игрок", source AS "источник", amount AS "урон"
FROM boss_damage WHERE event_id = {CUR_EVENT} ORDER BY created_at DESC LIMIT 30""", "table")]), 8)
L.end()
L = Line(6)
L.place(table("Все ивенты", [pg("""
SELECT id, name AS "босс", status AS "статус", max_hp AS "макс HP", hp AS "HP", started_at AS "начало", ends_at AS "конец",
       phase AS "фаза", rage AS "ярость", last_damage_at AS "последний урон"
FROM boss_events ORDER BY id DESC""", "table")]), 24)
L.end()

# ═════════════════════════════ 8. Игры ═════════════════════════════
row("🎮 Игры: викторина и Wordle")
L = Line(8)
L.place(ts("Викторина: правильные ответы по дням", [pg("""
SELECT $__timeGroupAlias(sent_at, '1d', 0), player_name AS metric, COUNT(*) FILTER (WHERE correct) AS value
FROM trivia_results WHERE $__timeFilter(sent_at) GROUP BY 1, 2 ORDER BY 1""")], draw="bars", fill=80, stack=True,
           legend_calcs=["sum"], desc="Из question_state (✅/❌ по игрокам), дата — когда вопрос отправлен в чат"), 8)
_acc = table("Викторина: точность за период", [pg("""
SELECT player_name AS "игрок", COUNT(*) AS "ответов", COUNT(*) FILTER (WHERE correct) AS "верно",
       ROUND(100.0 * COUNT(*) FILTER (WHERE correct) / COUNT(*)) AS "точность %"
FROM trivia_results WHERE $__timeFilter(sent_at) GROUP BY 1 ORDER BY 4 DESC""", "table")])
_acc["fieldConfig"]["defaults"]["noValue"] = "За период викторин не было"
L.place(_acc, 6)
L.place(bars("Wordle: победы и средние попытки", [pg("""
SELECT player_name AS "игрок", COUNT(*) FILTER (WHERE won) AS "побед", COUNT(*) FILTER (WHERE finished AND NOT won) AS "проигрышей",
       ROUND(AVG(attempts) FILTER (WHERE won), 1) AS "ср. попыток"
FROM wordle_games WHERE $__timeFilter(date::timestamp) GROUP BY 1 ORDER BY 2 DESC""", "table")]), 10)
L.end()

# ═════════════════════════════ 9. Процессы ═════════════════════════════
row("🖥 Процессы ботов")
L = Line(8)
L.place(last24h(ts("Память процессов", [prom("max by (bot) (tg_bot_rss_bytes)", "{{bot}}")], unit="bytes",
                   legend_calcs=["last", "max"])), 8)
L.place(last24h(ts("CPU процессов", [prom("sum by (bot) (rate(tg_bot_cpu_seconds_total[5m]))", "{{bot}}")],
                   unit="percentunit", legend_calcs=["mean", "max"])), 8)
L.place(last24h(ts("Ошибки и предупреждения в логе (окно 5 мин)",
                   [prom('max by (level) (tg_bot_log_lines_5m{log="main"})', "{{level}}")], draw="bars", fill=70)), 8)
L.end()
L = Line(7)
L.place(last24h(ts("Живы ли процессы", [prom("max by (bot) (tg_bot_up)", "{{bot}}")], min_=0, max_=1.2, draw="line", fill=0,
                   desc="Провал до 0 = бот лежал; частые короткие провалы = рестарты")), 12)
L.place(last24h(ts("Баланс OpenRouter", [prom("max(tg_openrouter_credits_usd)", "$")], unit="currencyUSD")), 12)
L.end()

dashboard = {
    "uid": UID, "title": "Telegram-боты", "tags": ["telegram", "jarvis", "bots"], "timezone": "Europe/Kyiv",
    "schemaVersion": 39, "refresh": "1m", "time": {"from": "now-7d", "to": "now"}, "editable": True,
    "description": "Джарвис (AI), реакции, фидбек, память v2, служебные LLM, активность чата, ивент Пуджа, игры, процессы.",
    "panels": panels,
}

if __name__ == "__main__":
    compose = open("/home/spedymax/monitoring/docker-compose.yml").read()
    password = re.search(r"GF_SECURITY_ADMIN_PASSWORD=([^\s\"']+)", compose).group(1)
    auth = "Basic " + base64.b64encode(f"admin:{password}".encode()).decode()

    def api(method, path, body=None):
        req = urllib.request.Request("http://127.0.0.1:3000" + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": auth, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    code, folders = api("GET", "/api/folders")
    folder = next((f for f in folders if f.get("title") == "Telegram-боты"), None) if code == 200 else None
    if folder is None:
        code, folder = api("POST", "/api/folders", {"title": "Telegram-боты", "uid": "tg-bots-folder"})
    code, res = api("POST", "/api/dashboards/db", {"dashboard": dashboard, "folderUid": folder["uid"], "overwrite": True,
                                                   "message": "tg-bots dashboard (generated)"})
    print(code, res.get("status"), res.get("url"), res.get("message", ""), f"panels={len(panels)}")
