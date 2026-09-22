# Identity prompts

Production source of truth is the `prompt_versions` table. Files here are review fixtures:
the text of each version as it was evaluated, so changes can be diffed and replayed
(`python -m evals.replay --config '{"name":"x","model":"x-ai/grok-4.7","identity_path":"docs/prompts/identity-v28.md"}'`).

| file | status | notes |
|---|---|---|
| identity-v27.md | prod since 2026-09-10 | 8.8K chars |
| identity-v28a-rejected.md | rejected | 4.4K chars; blind pairwise vs v27 lost 10–20 (natural 9–22): too earnest, lost the voice |
| identity-v27g-variant.md | not used | v27 + grounding block; pairwise 15–19 vs v27 (parity) |
| identity-v28.md | candidate | 6.2K chars (−30%): v27 voice kept verbatim + structure + grounding (attribution, own messages, date, chat words, callbacks, bio). Pairwise 17–20 vs v27 (parity), grounded 10–8, clearly better on attribution/own-message/refusal seeds, replies ~13% shorter |
