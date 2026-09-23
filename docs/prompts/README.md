# Identity prompts

Production source of truth is the `prompt_versions` table. Files here are review fixtures:
the text of each version as it was evaluated, so changes can be diffed and replayed
(`python -m evals.replay --config '{"name":"x","model":"x-ai/grok-4.7","identity_path":"docs/prompts/identity-v28.md"}'`).

| file | status | notes |
|---|---|---|
| identity-v27.md | prod since 2026-09-10 | 8.8K chars |
| identity-v28a-rejected.md | rejected | 4.4K chars; blind pairwise vs v27 lost 10–20 (natural 9–22): too earnest, lost the voice |
| identity-v27g-variant.md | not used | v27 + grounding block; pairwise 15–19 vs v27 (parity) |
| identity-v28.md | prod 2026-09-22 → 09-23 | 6.2K chars (−30%): v27 voice kept verbatim + structure + grounding (attribution, own messages, date, chat words, callbacks, bio). Pairwise 17–20 vs v27 (parity), grounded 10–8, clearly better on attribution/own-message/refusal seeds, replies ~13% shorter |
| identity-v29.md | prod since 2026-09-23 | v28 + «игры бота — это ты» (викторина/Wordle/Пуджинио…, ✅ ставишь ты за верный ответ) + «не видишь опоры — скажи „не вижу“, а не „выдумал“; не меняй ответ под давлением». Инцидент с галочками 23.09. Pairwise vs v28: 12–9 (grounded 7–3, natural 13–8); сцены инцидента: quiz-checkmarks 4/4, pressure 4/4, no-source 1/4 (Grok всё ещё «признаётся»; в проде опора теперь в истории) |
