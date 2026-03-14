# Probabilistic Replies Redesign — Design Spec

**Date:** 2026-03-14
**Status:** Approved
**Scope:** `src/handlers/moltbot_handlers.py` — `_maybe_reply_probabilistic` and related

---

## Problem

Bot's probabilistic replies are cringe — wrong timing (butts in when not needed) and wrong content (generic, no personality). Current implementation uses Qwen for both decision AND response generation in a single prompt, which produces low quality on both fronts.

## Design

### Two-stage architecture

**Stage 1 — Activity gate (no AI call)**
- Minimum message length: 10 characters (filters "ок", "лол", "👍")
- Activity threshold: 6+ messages in last 10 minutes (chat must be alive)
- Global cooldown: 2 hours between "sessions"
- Session cooldown: 20 minutes between replies within an active session

**Stage 2a — Cold start (first reply in 2+ hours)**
Claude receives last 6 messages and picks which one to reply to:
```
[Последние 6 сообщений из чата]
{messages}

Ты участник чата и хочешь вмешаться. Выбери одно сообщение
на которое стоит ответить и напиши короткий комментарий.
Подъёбка, шутка, или полезный коммент если тема серьёзная.
1-2 предложения максимум. Не представляйся, не начинай с обращения.
Если ни одно сообщение не стоит ответа — верни пустую строку.
```

**Stage 2b — Warm session (subsequent replies within session)**
Qwen filter (fast, free) → Claude response (smart, personality-aware).

Qwen filter prompt (10 messages context):
```
Вот последние сообщения из группового чата:
{history}

Новое сообщение от {sender}: {text}

Ты Джарвис — участник чата. Реши: стоит ли тебе вмешаться?
Отвечай YES только если:
- Тема тебя касается (дота, философия, жизнь, шансон, зона)
- Кто-то сказал явную глупость и это смешно прокомментировать
- Разговор сам просится на твой комментарий
Отвечай NO если:
- Это просто болтовня между людьми
- Сообщение короткое и бессмысленное
- Вопрос адресован конкретному человеку
- При любых сомнениях — NO
Ответь одним словом: YES или NO
```

Claude response prompt (30 messages context):
```
[История чата — последние {N} сообщений]
{history}

Новое сообщение от {sender}: {text}

[Ты решил вмешаться в разговор. Напиши короткий комментарий
как участник чата — подъёбка, шутка, или полезный коммент если тема серьёзная.
1-2 предложения максимум. Не представляйся, не начинай с обращения.
Если передумал — верни пустую строку.]
```

### Parameters

| Parameter | Value |
|-----------|-------|
| Min message length | 10 chars |
| Activity threshold | 6 messages in 10 minutes |
| Global cooldown (between sessions) | 2 hours |
| Session cooldown (between replies) | 20 minutes |
| Qwen filter history | 10 messages |
| Claude response history | 30 messages |
| Summary | NOT included (too noisy) |

### State tracking

New instance variables:
- `_prob_session_start: dict[int, datetime]` — when the current session started (for 2h global cooldown)
- `_last_probabilistic_sent` — already exists, reuse for 20min session cooldown

Cold start detection: if `_prob_session_start[chat_id]` is None or older than 2 hours → cold start.

### Flow diagram

```
Message arrives (group, text, not command, not bot mention)
    │
    ├─ len(text) < 10 → skip
    │
    ├─ count_recent_messages(10 min) < 6 → skip
    │
    ├─ last_probabilistic < 20 min ago → skip
    │
    ├─ session_start > 2h ago or None → COLD START
    │   ├─ Fetch last 6 messages
    │   ├─ Send to Claude (openclaw:main)
    │   ├─ If reply → send, update session_start + last_sent
    │   └─ If empty → skip
    │
    └─ session_start < 2h ago → WARM SESSION
        ├─ Send to Qwen filter (YES/NO)
        ├─ If NO → skip
        ├─ If YES → Send to Claude for response
        ├─ If reply → send, update last_sent
        └─ If empty → skip
```

## Files modified

| File | Changes |
|------|---------|
| `src/handlers/moltbot_handlers.py` | Rewrite `_maybe_reply_probabilistic`, add `_prob_session_start`, add `_qwen_should_reply` filter |

## Not changed

- `handle_probabilistic` handler filter — stays the same
- Reaction system — separate feature, not touched
- Proactive messages — separate feature, not touched
