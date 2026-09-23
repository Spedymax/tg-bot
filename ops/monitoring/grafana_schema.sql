BEGIN;
CREATE SCHEMA IF NOT EXISTS grafana;
COMMENT ON SCHEMA grafana IS 'Read-only views for Grafana dashboards: no message/memory/feedback text';

CREATE OR REPLACE VIEW grafana.traces AS
SELECT trace_id, created_at, chat_id, kind, prompt_version, reasoning, final_model, final_provider, outcome,
       latency_ms, prompt_tokens, completion_tokens, cost_usd, search_calls, reply_chars, reply_message_id,
       jsonb_array_length(COALESCE(data->'attempts','[]'::jsonb)) AS attempts,
       (SELECT COALESCE(SUM((a->>'cached_tokens')::int),0) FROM jsonb_array_elements(COALESCE(data->'attempts','[]'::jsonb)) a) AS cached_tokens,
       jsonb_array_length(COALESCE(data->'memory_ids','[]'::jsonb)) AS memory_hits,
       data->>'memory_mode' AS memory_mode,
       COALESCE(data->'sections','{}'::jsonb) AS sections,
       (SELECT COUNT(*) FROM jsonb_array_elements(COALESCE(data->'tools','[]'::jsonb))) AS tool_calls
FROM public.llm_traces;

CREATE OR REPLACE VIEW grafana.trace_attempts AS
SELECT t.trace_id, t.created_at, t.kind, a->>'provider' AS provider, a->>'model' AS model, a->>'upstream' AS upstream,
       (a->>'ok')::boolean AS ok, (a->>'latency_ms')::int AS latency_ms, NULLIF(a->>'error','') AS error,
       COALESCE((a->>'prompt_tokens')::int,0) AS prompt_tokens, COALESCE((a->>'completion_tokens')::int,0) AS completion_tokens,
       COALESCE((a->>'cached_tokens')::int,0) AS cached_tokens, COALESCE((a->>'cost_usd')::float,0) AS cost_usd
FROM public.llm_traces t, jsonb_array_elements(COALESCE(t.data->'attempts','[]'::jsonb)) a;

CREATE OR REPLACE VIEW grafana.trace_tools AS
SELECT t.trace_id, t.created_at, x->>'name' AS tool, x->>'reason' AS reason, (x->>'ok')::boolean AS ok, (x->>'latency_ms')::int AS latency_ms
FROM public.llm_traces t, jsonb_array_elements(COALESCE(t.data->'tools','[]'::jsonb)) x;

CREATE OR REPLACE VIEW grafana.messages AS
SELECT id, chat_id, user_id, COALESCE(name,'?') AS name, "timestamp" AS ts, (user_id = 0) AS is_bot,
       (reply_to_message_id IS NOT NULL) AS is_reply, length(message_text) AS chars
FROM public.messages;

CREATE OR REPLACE VIEW grafana.feedback AS
SELECT id, created_at, chat_id, trace_id, kind, polarity, CASE WHEN kind = 'reaction' THEN value END AS emoji
FROM public.llm_feedback;

CREATE OR REPLACE VIEW grafana.memory_items AS
SELECT id, chat_id, subject_name, kind, claim_type, confidence, status, sensitive, first_seen_at, last_seen_at,
       expires_at, use_count, last_used_at, created_by, created_at
FROM public.memory_items;

CREATE OR REPLACE VIEW grafana.memory_audit AS
SELECT id, chat_id, item_id, action, created_at, detail->>'reason' AS reason FROM public.memory_audit;

CREATE OR REPLACE VIEW grafana.media AS SELECT kind, created_at FROM public.media_descriptions;
CREATE OR REPLACE VIEW grafana.prompt_versions AS SELECT id, created_at, author_name, note, length(content) AS chars FROM public.prompt_versions;
CREATE OR REPLACE VIEW grafana.reminders AS SELECT id, created_at, remind_at, sent FROM public.reminders;
CREATE OR REPLACE VIEW grafana.prophecies AS SELECT id, created_at, style, format_key FROM public.daily_prophecies;
CREATE OR REPLACE VIEW grafana.boss_events AS SELECT id, name, max_hp, hp, status, started_at, ends_at, phase, rage, last_damage_at FROM public.boss_events;
CREATE OR REPLACE VIEW grafana.boss_damage AS SELECT id, event_id, created_at, player_name, source, amount FROM public.boss_damage_log;
CREATE OR REPLACE VIEW grafana.dungeon_runs AS SELECT date, player_name, finished, won, rooms_cleared, created_at, finished_at FROM public.dungeon_runs;
CREATE OR REPLACE VIEW grafana.wordle_games AS SELECT id, date, player_name, attempts, won, finished, finished_at FROM public.wordle_games;
CREATE OR REPLACE VIEW grafana.trivia_answers AS
SELECT a.date_added, COALESCE(p.player_name, a.user_id::text) AS player_name
FROM public.answered_questions a LEFT JOIN public.pisunchik_data p ON p.player_id = a.user_id;
CREATE OR REPLACE VIEW grafana.players AS SELECT player_name, pisunchik_size, coins, casino_usage_count FROM public.pisunchik_data;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grafana_ro') THEN
    CREATE ROLE grafana_ro LOGIN;
  END IF;
END $$;
ALTER ROLE grafana_ro SET default_transaction_read_only = on;
ALTER ROLE grafana_ro SET statement_timeout = '15s';
ALTER ROLE grafana_ro SET search_path = grafana;
GRANT CONNECT ON DATABASE "server-tg-pisunchik" TO grafana_ro;
GRANT USAGE ON SCHEMA grafana TO grafana_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA grafana TO grafana_ro;
REVOKE ALL ON SCHEMA public FROM grafana_ro;
COMMIT;
