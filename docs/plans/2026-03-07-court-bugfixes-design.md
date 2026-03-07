# Court Game Bug Fixes — Design Document

**Date:** 2026-03-07
**Status:** Approved

---

## Scope

Six bugs in `src/handlers/court_handlers.py` and `src/services/court_service.py`.
No DB schema changes. No new dependencies.

---

## Bug 1+2: API failure / missing signal tag → game hangs

**Root cause:** `judge_react()` can return `("", None)` on API error, or `(text, None)` when LLM omits the signal tag. Both lead to `_handle_judge_signal(None)` → fallback timer fires with no explanation to players.

**Fix in `court_service.py` → `judge_react()`:**
1. If `raw` is empty after LLM call → skip to fallback immediately
2. If `raw` is non-empty but `parse_judge_signal` returns `signal=None` → retry LLM once
3. If retry still has no tag → use fallback
4. Fallback reaction text: `"Суд принял к сведению. Продолжаем заседание."` (neutral, in-character)
5. Fallback signal: `ЗАЩИТА_ВАШ_ХОД` if role is `prosecutor`, else `ПРОКУРОР_ВАШ_ХОД` (or `ФИНАЛ` if `is_last_round`)

Same fix applies to `judge_react_to_reply()`.

---

## Bug 4: Race condition — two players press card button simultaneously

**Root cause:** Phase check and phase update are not atomic. Both players pass `current_phase == 'defense'` check before either sets `defense_speech`.

**Fix in `court_handlers.py`:**
- Add `self._game_locks: dict[int, threading.Lock]` — one lock per `game_id`
- In `handle_play_card` callback: acquire `self._game_locks.setdefault(game_id, threading.Lock())` **before** the phase check, release after `set_phase()` call
- Use `with` statement to guarantee release on exception

---

## Bug 7: Fallback fires while player is typing reply

**Root cause:** `on_timeout()` changes phase to `prosecution`/`defense`/`final`, then player's reply arrives — `_process_judge_reply` processes it in wrong phase, judge emits signal that corrupts game state.

**Fix in `court_handlers.py` → `_process_judge_reply()`:**
- At the start, fetch fresh game state
- If `game['current_phase'] != 'judge'` → return silently (game already moved on)

---

## Bug 8: No specific message when defense already answered

**Root cause:** Generic "Защита уже ответила в этом раунде!" doesn't tell the second player who specifically already played.

**Fix in `court_handlers.py` → `handle_play_card`:**
- When `defense_played` check triggers, determine which role played this round:
  - Find `p['role']` from `played_cards` for current round
  - If `'lawyer'` played → `"🛡️ Адвокат уже ответил в этом раунде!"`
  - If `'witness'` played → `"👁️ Свидетель уже ответил в этом раунде!"`

---

## Bug 9: Verdict LLM skips `---` separators → empty blocks

**Root cause:** LLM sometimes writes all 4 blocks as continuous text without `---` separators (especially when JUDGE_SYSTEM_PROMPT's tag requirement interferes).

**Fix in `court_service.py` → `generate_verdict()`:**
1. After first LLM call: if `len(parts) < 4` → retry once
2. After retry: if still `< 4` → use entire raw response as block 4 (ПРИГОВОР), leave others empty
3. Add explicit format example to prompt:

```
Пример правильного формата:
Обвинение настаивает на...
---
Защита утверждает что...
---
Ключевое противоречие состоит в...
---
**ВИНОВЕН**
Приговор: ...
```

---

## Files changed

| File | Changes |
|------|---------|
| `src/services/court_service.py` | `judge_react()`: retry + fallback; `judge_react_to_reply()`: same; `generate_verdict()`: retry + format example |
| `src/handlers/court_handlers.py` | `__init__`: add `_game_locks`; `handle_play_card`: lock around phase check; `_process_judge_reply`: phase guard; defense-already-played message |
