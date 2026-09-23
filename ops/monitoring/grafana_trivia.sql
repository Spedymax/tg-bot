CREATE OR REPLACE VIEW grafana.trivia_results AS
WITH sent AS (
    SELECT q.question, MAX(h.sent_at) AS sent_at
    FROM public.chat_question_history h JOIN public.questions q ON q.id = h.question_id
    GROUP BY q.question
), answers AS (
    SELECT qs.original_question,
           CASE WHEN qs.players_responses::jsonb ? 'players_responses'
                THEN qs.players_responses::jsonb -> 'players_responses'
                ELSE qs.players_responses::jsonb END AS resp
    FROM public.question_state qs
)
SELECT s.sent_at,
       -- names carried pet badges for a while («Макс 🦅 [Голоден 😟] ✅») → keep the first word
       split_part(btrim(CASE WHEN r.value IN ('✅', '❌') THEN r.key
                             ELSE regexp_replace(r.value, '\s*[✅❌]\s*$', '') END), ' ', 1) AS player_name,
       (r.value LIKE '%✅') AS correct
FROM answers a
JOIN sent s ON s.question = a.original_question
CROSS JOIN LATERAL jsonb_each_text(a.resp) r
WHERE r.value LIKE '%✅' OR r.value LIKE '%❌';
GRANT SELECT ON grafana.trivia_results TO grafana_ro;
