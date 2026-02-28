# Pet Feedback & Death Awareness Design

**Date:** 2026-02-28
**Status:** Approved

## Overview

The pet system has solid mechanics but feels raw: the pet dies silently, the ulta button gives no timing info, and game output doesn't reflect the pet's state. This design adds state-aware feedback embedded into existing game output — no standalone bot messages.

---

## Section 1: State Badge in Game Output

The existing stage badge (`🐣`) is extended with a hunger/happiness label appended to trivia, roll, casino, and pisunchik result lines.

### Badge format

| Hunger | Badge |
|--------|-------|
| 60–100, happiness < 80 | `🐣` (no label) |
| 60–100, happiness ≥ 80 | `🐣 [Счастлив 😊]` |
| 30–59 | `🐣 [Голоден 😟]` |
| 10–29 | `🐣 [Очень голоден 😫]` |
| 1–9 | `🐣 [Умирает! 💀]` |

Happiness < 20 appends `[Подавлен]` alongside the hunger label when hunger is also low.

### Implementation

New method `pet_service.get_pet_badge(player) -> str` replaces all existing badge call sites. Returns empty string if pet is dead, None, or not locked.

---

## Section 2: Ulta Cooldown Timer

The "not ready" button now shows remaining time instead of a generic message.

| State | Button label |
|-------|-------------|
| Ready | `⚡ Оракул` |
| Cooldown, hours remaining | `⚡ Оракул (через 6ч)` |
| Cooldown, < 1h remaining | `⚡ Оракул (через 45м)` |
| Cooldown with depressed penalty (48h) | `⚡ Оракул (через 14ч) 😢` |

New helper: `pet_service.get_ulta_cooldown_remaining(player) -> Optional[timedelta]`. Used in `pet_handlers._get_pet_buttons()` to build the label.

---

## Section 3: Death Awareness

### 3a. "Умирает" badge in group output

When hunger is 1–9, the `[Умирает! 💀]` label appears in every game result line. The group sees it and can remind the player to feed their pet.

### 3b. Death notification on next game command

When `apply_hunger_decay()` returns `True` (pet just died during lazy decay), a new flag `pet_death_pending_notify: bool` is set to `True` on the player and saved.

On the player's next game command (trivia answer, roll, casino spin, pisunchik), the handler prepends to the result:

```
💀 Барсик умер от голода! Используй /pet чтобы возродить.
```

The flag is cleared immediately after — one-shot, no spam.

### New player field

- `pet_death_pending_notify: bool = False`
- DB migration: `ALTER TABLE pisunchik_data ADD COLUMN IF NOT EXISTS pet_death_pending_notify BOOLEAN DEFAULT FALSE;`

---

## Section 4: Revives Reminder

Dead pet menu shows contextual messaging based on remaining revives:

| Remaining | Display |
|-----------|---------|
| 2–5 | `Возрождений: X/5 осталось` *(unchanged)* |
| 1 | `⚠️ Последнее возрождение!` |
| 0 | `💀 Возрождений больше нет в этом месяце` |

When 0 revives remain, the revive button changes to `❤️ Возродить (нет возрождений)` — still visible, clicking gives the existing "нет возрождений" toast.

---

## Files Changed

| File | Change |
|------|--------|
| `src/services/pet_service.py` | Add `get_pet_badge()`, `get_ulta_cooldown_remaining()` |
| `src/handlers/pet_handlers.py` | Use cooldown timer in button; update revives display |
| `src/handlers/trivia_handlers.py` | Use `get_pet_badge()`; check `pet_death_pending_notify` |
| `src/handlers/game_handlers.py` | Use `get_pet_badge()`; check `pet_death_pending_notify` |
| `src/models/player.py` | Add `pet_death_pending_notify` field |
| `src/database/player_service.py` | Include `pet_death_pending_notify` in save/load |
| `src/database/migrations/` | New migration SQL for `pet_death_pending_notify` |

---

## Out of Scope

- Standalone bot messages about pet state
- Outcome-based pet commentary (e.g. pet reacting to good/bad rolls)
- Evolution announcements to group chat
- Pet name in the badge
