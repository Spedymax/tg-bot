# Jarvis evals

Golden scenes + replay + judge. Everything runs from the repo root with the bot's venv
(`/home/spedymax/venv/bin/python`) and reads the DB / OpenRouter key from `/home/spedymax/tg-bot/.env`.

| шаг | команда | что делает |
|---|---|---|
| 1 | `python -m evals.extract pull --days 45` | все ответы Джарвиса с контекстом, который он видел (как в проде) → `data/evals/candidates.jsonl` |
| 2 | `python -m evals.extract label` | LLM черново размечает категорию, критерии, «не должен», нужен ли поиск, политику callback'ов, реакцию людей |
| 3 | `python -m evals.extract select --n 60` | golden set: все сцены с фрустрацией + round-robin по категориям → `data/evals/golden-v1.jsonl` |
| 4 | `python -m evals.replay --config prod --config grok47` | прогон кандидатов на тех же входах (реальный ContextBuilder, часы заморожены на время сцены, поиск застаблен) |
| 5 | `python -m evals.judge score <run> <run>` | оценка по критериям сцены + осям natural/funny/useful/grounded/not_annoying + флаги → markdown-отчёт |
| 6 | `python -m evals.judge pair <runA> <runB>` | слепое попарное сравнение (порядок перемешан, модель скрыта), tie/both_bad разрешены |
| ★ | `python -m evals.compare --cand '{"identity_path": "docs/prompts/identity-vNN.md"}'` | **одна команда**: прод-конфиг (модель, reasoning, последний промпт из БД) vs кандидат на наборе `quick` (26 сцен) / `full` / `seeds`, слепой pairwise |

- Реальные сцены — приватная переписка: лежат только в `data/evals/` (gitignored). В git — код и
  `evals/seed_scenes.jsonl` (синтетические сцены на дату, внутряки, атрибуцию, газлайтинг, оверлей, отказ…).
- Сцена хранит ожидаемое *поведение*, а не «идеальный ответ». После `label` критерии стоит просмотреть руками.
- **Дёшево по умолчанию** (с 23.09): судья — прямой Gemini по бесплатному ключу бота (`--judge anthropic/claude-sonnet-5`
  для важных решений); кэш ответов `data/evals/cache/replies.jsonl` — одинаковый запрос (модель, настройки, сообщения, seed)
  не оплачивается повторно, поэтому база прода платится один раз; `session_id` на прогон → системный промпт из кэша
  провайдера. Типичная проверка нового промпта на `quick`: ~$0.2–0.3 вместо ~$1.
- Бюджет: ключ OpenRouter общий с продом. Каждый шаг сначала проверяет остаток и отказывается стартовать, если
  после него останется меньше `EVAL_PROD_RESERVE_USD` (по умолчанию $3). Ориентиры: разметка ~$0.013/сцена,
  прогон ~$0.01–0.03/ответ, судья ~$0.012/ответ → полный bake-off 4 конфигов на ~75 сценах ≈ $10–12.
