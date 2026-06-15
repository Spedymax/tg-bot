#!/bin/bash
# Jarvis self-improve loop — MODE B (propose-only).
# Deterministic I/O here; `claude -p` is used ONLY for analysis (text in, text out, no tools).
# Scheduled by launchd (com.spedymax.jarvis-loop) at 13:00 daily.
set -uo pipefail

REPO="/Users/mso/PycharmProjects/tg-bot"
CLAUDE="/Users/mso/.local/bin/claude"
PY="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
# Reach the server via CloudFlare Access (ssh.spedymax.org, headless service token in
# ~/.ssh/cf-env via the ProxyCommand in ~/.ssh/config) — NOT the LAN IP. The LAN path only
# worked when this Mac happened to be on the home network at 13:00; off-LAN it timed out and
# the empty result was silently mistaken for "no new messages" (see connectivity guard below).
SSH="ssh -i $HOME/.ssh/mac-max -o ConnectTimeout=30 -o BatchMode=yes spedymax@ssh.spedymax.org"
LOG="$REPO/docs/loop/decisions.md"
RUNLOG="$REPO/.omc/loop-run.log"
cd "$REPO" || exit 1
mkdir -p "$REPO/.omc"
ts() { date "+%F %T"; }
echo "[$(ts)] loop start" >> "$RUNLOG"

# 0. connectivity guard — a failed SSH (server down, CF Access hiccup, etc.) must NOT be
#    mistaken for "no new messages". Verify the server is reachable BEFORE trusting an empty
#    query result; perl alarm hard-bounds a hung handshake (macOS has no `timeout`).
if ! perl -e 'alarm 50; exec @ARGV' $SSH "true" 2>>"$RUNLOG"; then
  echo "[$(ts)] server UNREACHABLE (ssh/CF Access failed) — aborting, NOT a quiet cycle" >> "$RUNLOG"
  exit 1
fi

# 1. pull messages SINCE the current persona was deployed — so the loop only ever judges
#    the CURRENT bot (no stale pre-fix behavior). Capped at 7 days so a long-stable persona
#    doesn't drag in months of history.
CUTOFF=$($SSH "export LC_ALL=C; echo '123' | sudo -S -u postgres psql -d server-tg-pisunchik -t -A -c \"SELECT created_at FROM prompt_versions ORDER BY created_at DESC LIMIT 1;\"" 2>/dev/null | grep -vi 'locale\|\[sudo\]' | sed -n '1s/^ *//p')
DATA=$($SSH "export LC_ALL=C; echo '123' | sudo -S -u postgres psql -d server-tg-pisunchik -t -A -F'|' -c \"SELECT m.name, CASE WHEN r.message_id IS NOT NULL THEN '[↩ '||COALESCE(r.name,'?')||': '||left(r.message_text,60)||'] '||m.message_text ELSE m.message_text END FROM messages m LEFT JOIN messages r ON m.reply_to_message_id = r.message_id WHERE m.timestamp >= GREATEST((SELECT created_at FROM prompt_versions ORDER BY created_at DESC LIMIT 1), NOW() - INTERVAL '7 days') ORDER BY m.timestamp ASC LIMIT 400;\"" 2>/dev/null | grep -vi 'locale\|\[sudo\]')
if [ -z "$DATA" ]; then
  echo "[$(ts)] no messages since persona deploy ($CUTOFF), quiet cycle, skip" >> "$RUNLOG"; exit 0
fi

# 2. previous decision-log entry (state)
PREV=$(awk '/^## /{c++} c==1{print} c==2{exit}' "$LOG")

# 3. analyze (claude as pure analyst — no tools)
REPORT=$(printf '%s\n\n=== PREVIOUS DECISION ===\n%s\n\n=== MESSAGES SINCE CURRENT PERSONA DEPLOY (%s) — chronological, name|text; Jarvis=bot. A leading [↩ NAME: ...] marks what that message is replying to — use it to judge whether consecutive Jarvis lines answer DIFFERENT messages (not a double-reply). EVERY Jarvis reply below is the CURRENT persona, so anything wrong here is current behavior (not stale). ===\n%s\n' \
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
scp -i "$HOME/.ssh/mac-max" -o ConnectTimeout=30 -o BatchMode=yes /tmp/loop_digest.txt spedymax@ssh.spedymax.org:/tmp/loop_digest.txt >/dev/null 2>&1
$SSH "cd /home/spedymax/tg-bot; TOKEN=\$(grep '^TELEGRAM_BOT_TOKEN=' .env | cut -d= -f2- | tr -d '\"'\"'\"' \r'); curl -s \"https://api.telegram.org/bot\$TOKEN/sendMessage\" -d chat_id=741542965 --data-urlencode 'text@/tmp/loop_digest.txt' -o /dev/null -w 'tg %{http_code}\n'" >> "$RUNLOG" 2>&1

echo "[$(ts)] loop done" >> "$RUNLOG"
