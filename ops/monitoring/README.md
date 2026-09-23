# Grafana: дашборд «Telegram-боты»

Живёт в `~/monitoring` на сервере (docker compose: grafana, prometheus, node_exporter, loki…). Здесь — копии под git.

| файл | что делает |
|---|---|
| `grafana_schema.sql` | схема `grafana` с read-only view (без текстов сообщений/памяти/фидбека) + роль `grafana_ro` (read-only, statement_timeout 15s) |
| `tg_bots_exporter.py` | cron раз в минуту → `~/monitoring/textfile/tg_bots.prom` (textfile-коллектор node_exporter): процессы ботов, ошибки в логе за 5 мин, давность сообщений, вызовы/стоимость LLM за день, память v2, HP/фаза/ярость босса, баланс OpenRouter, Ollama, уровень reasoning |
| `grafana_tg_bots_dashboard.py` | генерирует и заливает дашборд через API Grafana (`python3 grafana_tg_bots_dashboard.py`) |

Доступ Grafana → Postgres:
- datasource `tgbot-pg` (grafana-postgresql-datasource) → `172.18.0.1:5432`, пользователь `grafana_ro`
  (пароль: `~/monitoring/.grafana_ro_password`, 600);
- `pg_hba.conf`: `host server-tg-pisunchik grafana_ro 172.18.0.0/16 scram-sha-256` (бэкап `pg_hba.conf.bak-20260923`);
- ufw: `allow from 172.18.0.0/16 to any port 5432 proto tcp`.

Крон: `* * * * * /home/spedymax/venv/bin/python /home/spedymax/monitoring/tg_bots_exporter.py >> ~/logs/tg-bots-exporter.log 2>&1`

Секции дашборда: обзор · Джарвис (итоги, задержка p50/p90, стоимость, токены, кэш, фоллбэки, поиск, провайдеры,
reasoning, версия промпта, контекст по секциям, ошибки провайдеров, последние трейсы) · реакции и фидбек ·
память v2 · служебные LLM · активность чата · ивент Пуджа (HP во времени с регеном, урон по игрокам/источникам,
гонка за MVP, данж, последние удары) · игры · процессы.
