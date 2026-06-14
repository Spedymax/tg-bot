# Self-Improve Loop — Decision Log

Newest entry on top. Each cycle appends one entry. See `self-improve-loop.md` for the process.

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
