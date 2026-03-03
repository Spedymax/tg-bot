# Ollama Wake-on-LAN with Admin Notifications

**Date:** 2026-03-03
**Status:** Approved

---

## Problem

The Windows PC (192.168.1.3) running Ollama is not always on. When it's asleep, bot features
that call `_call_ollama_direct()` silently fail and return empty strings. There's no way to
wake it remotely, and no feedback to users or admin.

---

## Goals

- Wake the PC automatically when Ollama is needed
- Show users a "waking up, please wait" message, then auto-reply when ready
- Fall back to Claude (OpenClaw) after 3 minutes if the PC doesn't respond
- Notify admin via Telegram DM when PC wakes up or goes to sleep
- Put the PC to sleep automatically after 15 min of combined bot + user idle time

---

## Architecture

### State Machine: `OllamaWakeManager`

```
ONLINE ──(heartbeat fails)──▶ OFFLINE ──(WoL sent)──▶ WAKING ──(poll ok)──▶ ONLINE
                                                           │
                                                   (3 min timeout)
                                                           ▼
                                                  fallback to Claude
```

**States:**
- `ONLINE` — Ollama is reachable; requests are served synchronously
- `OFFLINE` — Ollama unreachable; WoL packet sent, requests queued
- `WAKING` — WoL sent, polling every 5s; "waking up" message shown to users

**Singleton:** One shared instance on the bot process; all callers share state.

---

## Components

### 1. Heartbeat Thread
- Polls `http://192.168.1.3:11434/api/tags` every **30 seconds** while `ONLINE`
- On failure: transitions to `OFFLINE`, sends admin DM "😴 PC went to sleep"
- Does NOT send WoL — only queued requests trigger wake

### 2. Wake Flow
- First request that arrives while `OFFLINE` or `WAKING`:
  - Sends WoL magic packet to Windows PC MAC address
  - Transitions to `WAKING`
  - Sends "⏳ Ollama is waking up… (~1–3 min)" to user
  - Enqueues `(prompt, chat_id, reply_fn)`
- Subsequent requests while `WAKING`: enqueued only (no duplicate WoL)
- Poll thread checks every **5 seconds** until Ollama responds or 3 min elapses
- On success: transitions to `ONLINE`, drains queue, sends admin DM "✅ PC is online"
- On timeout: drains queue using Claude fallback, sends admin DM "⚠️ PC did not wake (timeout)"

### 3. In-Memory Queue
- `list[WakeRequest]` where `WakeRequest = (prompt, chat_id, message_id, reply_fn)`
- Cleared after drain (success or fallback)
- Lost on bot restart (acceptable — wake cycle < 3 min)

### 4. Sleep Control (idle-based)
- A **sleep-check timer** runs every **5 minutes**
- Sleep condition: **bot idle > 15 min** AND **Windows user idle > 15 min**
- Bot idle: tracked as time since last `_call_ollama_direct()` call
- Windows user idle: SSH to `192.168.1.3`, run PowerShell `GetLastInputInfo` one-liner
- Sleep command: SSH → `rundll32.exe powrprof.dll,SetSuspendState 0,1,0`
- Admin DM: "😴 PC going to sleep (bot + user idle 15 min)"
- No changes to Windows power plan — preserves existing lock-screen bubble behavior

### 5. Bot Integration
- `_call_ollama_direct()` is replaced/wrapped by `wake_manager.call(prompt, bot, message)`
- When `ONLINE`: synchronous, no user-visible change
- When `OFFLINE`/`WAKING`: async path — handler sends "waking up" and returns; background
  thread sends the reply when ready

---

## Windows WoL Prerequisites (one-time manual setup)

1. **BIOS:** Enable "Wake on LAN" or "Power On by PCI-E" in power management settings
2. **NIC driver:** Device Manager → Network Adapter → Properties → Power Management →
   check "Allow this device to wake the computer" + "Only allow a magic packet to wake"
3. **Fast Startup:** Disable via `powercfg /h off` in elevated PowerShell
   (Fast Startup can prevent WoL from working from S3/S4 sleep)
4. **Verify:** `powercfg /devicequery wake_armed` should list the NIC

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| WoL packet fails to send | Log error, still queue request, retry WoL on next poll cycle |
| PC wakes but Ollama not ready within 3 min | Fallback to Claude, admin DM with warning |
| SSH idle check fails | Assume user is active (conservative — don't sleep) |
| SSH sleep command fails | Log error, admin DM, skip sleep cycle |
| Bot restarts while queue non-empty | Queue lost; users need to re-request (acceptable) |

---

## Configuration (`.env`)

```
LOCAL_LLM_URL=http://192.168.1.3:11434       # existing
LOCAL_LLM_MODEL=qwen2.5:14b                  # existing
PC_MAC_ADDRESS=XX:XX:XX:XX:XX:XX             # Windows PC MAC for WoL
PC_SSH_HOST=192.168.1.3                      # Windows PC IP
PC_SSH_USER=Spedy                            # SSH user
PC_SSH_KEY=~/.ssh/id_ed25519                 # SSH key (already configured)
OLLAMA_IDLE_SLEEP_MINUTES=15                 # idle timeout before sleep
ADMIN_TELEGRAM_ID=<your_id>                  # for DM notifications
```

---

## Dependencies

- `wakeonlan` (Python package) — sends magic packet
- `paramiko` or `subprocess ssh` — SSH to Windows for idle check + sleep command
- No new infrastructure required (no Redis, no DB changes)
