# Self-Improve Loop — Jarvis bot quality tuner

**Brain:** Claude Code (this playbook is the `-p` prompt run headlessly).
**Schedule:** daily 13:00 (local), via launchd on the Mac (`com.spedymax.jarvis-loop`).
**Goal:** catch subtle drift in Jarvis's chat quality and fix it; big stuff → ask Max.

You are running one cycle of the self-improve loop. Follow these steps exactly.

## 0. Read state
Read `docs/loop/decisions.md` (newest entry on top). Note the last cycle's findings and
any fix it applied — you must check whether that fix held this cycle.

## 1. Pull fresh data from the server (read-only)
```
ssh -i ~/.ssh/mac-max spedymax@192.168.1.35 "export LC_ALL=C; echo '123' | sudo -S -u postgres psql -d server-tg-pisunchik -t -A -F'|' -c \"
SELECT name, message_text FROM messages ORDER BY timestamp DESC LIMIT 120;\"" 2>&1 | grep -vi 'locale\|\[sudo\]'
```
This gives the last 120 messages (Jarvis replies are name='Jarvis', interleaved with users).
Reconstruct (trigger → Jarvis reply) pairs by adjacency.

## 2. Evaluate against the rubric
Label each Jarvis reply: ok / false-refusal / cringe(forced meme) / robotic-distant /
factual-error / broke-character(admitted being a bot) / over-search / repetition /
over-reliance-on-one-fact (e.g. always mentioning "Дания"). Also scan for: the SAME
canned reply repeated 3+ times (red flag), users reacting with «кринж/тупой/не отвечай»,
or replies that got ignored. Produce a short findings list with verbatim examples.

## 3. Decide fixes — TIERED (this is the autonomy contract)
- **AUTO (apply silently, then notify):** single-line additions/edits to the persona
  (`docs/identity-jarvis-v8.md`) OR memory-prompt rule tweaks. Reversible via prompt_versions.
- **ASK (do NOT apply — put in the digest for Max to approve):** rewriting whole persona
  sections, ANY code change, model swap, anything you're unsure about.
- Apply at most **2 auto-fixes per cycle**. If nothing's wrong, change nothing.

## 4. Apply an AUTO fix (if any)
1. Edit `docs/identity-jarvis-v8.md`.
2. Insert it as a new prompt version (dollar-quoted to handle cyrillic):
   build `/tmp/insert_vN.sql` with `INSERT INTO prompt_versions (content, author_id, author_name, note) VALUES ($p$<content>$p$, 741542965, 'loop', '<note>');`
   then `scp` to server `/tmp/` and `ssh ... "echo '123' | sudo -S -u postgres psql -d server-tg-pisunchik -f /tmp/insert_vN.sql"`.
3. Commit `docs/identity-jarvis-v8.md` + push, then `ssh ... "cd /home/spedymax/tg-bot && git pull"` (post-merge hook restarts; cache reloads on restart).
4. Verify: service active, 1 main.py proc, no 409.

## 5. Append a decision-log entry
Prepend to `docs/loop/decisions.md` (newest on top) using the template at its bottom.
Record: date, findings, what was auto-fixed, what's queued for Max, and whether the
PREVIOUS cycle's fix held.

## 6. Notify Max (Telegram DM via Jarvis token)
```
TOKEN=$(grep '^TELEGRAM_BOT_TOKEN=' .env | cut -d= -f2-)
curl -s "https://api.telegram.org/bot$TOKEN/sendMessage" -d chat_id=741542965 --data-urlencode "text=<digest>"
```
Digest = 1-line summary + what was auto-fixed + any items needing his tap. Keep it short.
If there were zero findings, send a one-liner "цикл прошёл, всё чисто" (or skip if quiet).

## Guardrails
- Never apply more than 2 auto-fixes/cycle. Always keep prompt_versions rollbackable.
- Sensitive/relationship content in the persona is MANUAL only — never auto-edit it.
- The decision log is the audit trail. Always write it, even on a no-op cycle.
