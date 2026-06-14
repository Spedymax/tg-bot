# Self-Improve Loop — Decision Log

Newest entry on top. Each cycle appends one entry. See `self-improve-loop.md` for the process.

---

## 2026-06-14 — auto cycle (propose mode)
- **Prev fix held?** частично — в нейтральных темах Дания не всплывает, но в треде где Denmark реально в контексте — 2/3 Jarvis-реплик всё равно используют Данию подряд; цель «1/6» в реальном чате не достигнута
- **Data:** ~120 msgs reviewed, 6 Jarvis replies
- **Findings:**
  - **over-reliance-on-one-fact (Дания) ×2** — «Так ты ж в Дании, это элитный экспорт» + «Сдал бы ему твою датскую жопу» — обе в одном треде, одна за другой
  - **false-refusal ×2** — «Не вмешиваюсь в викторину 🤐» triggered на «Words can't describe how much I disrespect and hate this person» и «ебало завали чушка» — не триvia вообще; exact canned reply с emoji 🤐 = hardcode в коде, LLM так не пишет
- **Proposed fix:** усилить существующую строку про Дания:
  `если уже упомянул факт о ком-то в этой же цепочке реплик (например, что Макс в Дании) — не возвращайся к нему, смени угол`
- **Queued for Max:** «Не вмешиваюсь в викторину 🤐» — кодовый handler в `moltbot_handlers.py` с проверкой active-trivia state слишком широкий: триггерится на любые сообщения пока викторина активна, а не только на реплаи к quiz-вопросу. Нужно добавить условие (сообщение = reply на bot-message с викториной, или явный текст вопроса в контексте).

---

---

## 2026-06-14 — cycle 1
- **Prev fix held?** n/a (first cycle)
- **Data:** replay of real bot-directed messages mined from `messages` table (mentions/replies to Jarvis) + a 7-turn chain in Max's style.
- **Findings:** bot is otherwise strong — trivia distraction, roast-back, dark humor, factual + search discipline, identity probes all OK. One drift: **over-reliance-on-one-fact** — the "Дания" callback appeared in ~most replies.
- **Auto-fixed:** persona one-liner added — «не зацикливайся на одном факте про человека (например, Дания), это приедается» → `prompt_versions` **v9** (note "cycle1: stop over-using Дания callback").
- **Verified:** re-ran 6 Дания-prone probes on v9 → callback dropped to **1/6** (was ~all). Fix works.
- **Queued for Max:** none.
- **Notified:** yes (TG DM via Jarvis token).

---

<!-- ENTRY TEMPLATE (copy, fill, prepend above this line):
## YYYY-MM-DD — cycle N
- **Prev fix held?** <yes/no/n-a — did last cycle's change actually help?>
- **Data:** <N messages reviewed, window>
- **Findings:** <labels + 1-2 verbatim examples>
- **Auto-fixed:** <what + prompt_version id, or "none">
- **Queued for Max:** <items needing approval, or "none">
- **Notified:** <yes/no>
-->
