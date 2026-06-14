#!/bin/bash
# Jarvis self-improve loop — MODE B (propose-only).
# Deterministic I/O here; `claude -p` is used ONLY for analysis (text in, text out, no tools).
# Scheduled by launchd (com.spedymax.jarvis-loop) at 13:00 daily.
set -uo pipefail

REPO="/Users/mso/PycharmProjects/tg-bot"
CLAUDE="/Users/mso/.local/bin/claude"
PY="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
SSH="ssh -i $HOME/.ssh/mac-max -o ConnectTimeout=20 spedymax@192.168.1.35"
LOG="$REPO/docs/loop/decisions.md"
RUNLOG="$REPO/.omc/loop-run.log"
cd "$REPO" || exit 1
mkdir -p "$REPO/.omc"
ts() { date "+%F %T"; }
echo "[$(ts)] loop start" >> "$RUNLOG"

# 1. pull messages SINCE the current persona was deployed — so the loop only ever judges
#    the CURRENT bot (no stale pre-fix behavior). Capped at 7 days so a long-stable persona
#    doesn't drag in months of history.
CUTOFF=$($SSH "export LC_ALL=C; echo '123' | sudo -S -u postgres psql -d server-tg-pisunchik -t -A -c \"SELECT created_at FROM prompt_versions ORDER BY created_at DESC LIMIT 1;\"" 2>/dev/null | grep -vi 'locale\|\[sudo\]' | sed -n '1s/^ *//p')
DATA=$($SSH "export LC_ALL=C; echo '123' | sudo -S -u postgres psql -d server-tg-pisunchik -t -A -F'|' -c \"SELECT name, message_text FROM messages WHERE timestamp >= GREATEST((SELECT created_at FROM prompt_versions ORDER BY created_at DESC LIMIT 1), NOW() - INTERVAL '7 days') ORDER BY timestamp ASC LIMIT 400;\"" 2>/dev/null | grep -vi 'locale\|\[sudo\]')
if [ -z "$DATA" ]; then
  echo "[$(ts)] no messages since persona deploy ($CUTOFF), quiet cycle, skip" >> "$RUNLOG"; exit 0
fi

# 2. previous decision-log entry (state)
PREV=$(awk '/^## /{c++} c==1{print} c==2{exit}' "$LOG")

# 3. analyze (claude as pure analyst — no tools)
REPORT=$(printf '%s\n\n=== PREVIOUS DECISION ===\n%s\n\n=== MESSAGES SINCE CURRENT PERSONA DEPLOY (%s) — chronological, name|text; Jarvis=bot. EVERY Jarvis reply below is the CURRENT persona, so anything wrong here is current behavior (not stale). ===\n%s\n' \
  "$(cat "$REPO/docs/loop/analysis-prompt.md")" "$PREV" "$CUTOFF" "$DATA" \
  | "$CLAUDE" -p --model sonnet 2>>"$RUNLOG")
if [ -z "$REPORT" ]; then echo "[$(ts)] empty report, abort" >> "$RUNLOG"; exit 1; fi

# 4. split LOG / DIGEST sections
LOGBODY=$(printf '%s' "$REPORT" | awk '/^=== LOG ===/{f=1;next} /^=== DIGEST ===/{f=0} f')
DIGEST=$(printf '%s' "$REPORT" | awk '/^=== DIGEST ===/{f=1;next} f')
[ -z "$DIGEST" ] && DIGEST="Петля: цикл прошёл (детали в логе)."

# 5. prepend a decision-log entry (newest on top, right after the first '---')
ENTRY=$(printf '## %s — auto cycle (propose mode)\n%s\n\n---\n' "$(date +%F)" "$LOGBODY")
ENTRY="$ENTRY" "$PY" - "$LOG" <<'PYEOF'
import os, sys
path = sys.argv[1]
entry = os.environ["ENTRY"]
t = open(path, encoding="utf-8").read()
marker = "\n---\n"
i = t.find(marker)
if i == -1:
    t = t.rstrip() + "\n\n---\n\n" + entry + "\n"
else:
    j = i + len(marker)
    t = t[:j] + "\n" + entry + "\n" + t[j:]
open(path, "w", encoding="utf-8").write(t)
PYEOF

# 6. commit the log entry
git add docs/loop/decisions.md >/dev/null 2>&1
git commit -q -m "loop: auto cycle decision-log entry ($(date +%F))" >/dev/null 2>&1 && git push -q origin main >/dev/null 2>&1

# 7. notify Max (DM via Jarvis token on the server). Digest goes via a file to avoid
#    any shell-escaping of its content (backticks, quotes, $).
printf '%s' "$DIGEST" > /tmp/loop_digest.txt
scp -i "$HOME/.ssh/mac-max" -o ConnectTimeout=20 /tmp/loop_digest.txt spedymax@192.168.1.35:/tmp/loop_digest.txt >/dev/null 2>&1
$SSH "cd /home/spedymax/tg-bot; TOKEN=\$(grep '^TELEGRAM_BOT_TOKEN=' .env | cut -d= -f2- | tr -d '\"'\"'\"' \r'); curl -s \"https://api.telegram.org/bot\$TOKEN/sendMessage\" -d chat_id=741542965 --data-urlencode 'text@/tmp/loop_digest.txt' -o /dev/null -w 'tg %{http_code}\n'" >> "$RUNLOG" 2>&1

echo "[$(ts)] loop done" >> "$RUNLOG"
