# Pet System Enhancement Design

**Date:** 2026-02-25
**Status:** Approved

## Overview

Enhance the existing pet system from an isolated XP tracker into a living, social, integrated game feature. The pet gains hunger and happiness stats, gives real in-game bonuses via stage-unique "ульты", and becomes visible to the group through badges and evolution announcements.

---

## Phase 1 — Hunger, Happiness & Food Economy

### Голод (Hunger)

- Range: 0–100, starts at 100 on pet creation
- Decay: −10 every 12 hours
- Effects by level:
  - 60–100: Нормально — no effect
  - 30–59: Голодный 😟 — XP gain −50%
  - 10–29: Очень голодный 😫 — XP stopped, ульта disabled
  - 1–9: Умирает 💀 — pet will die on next decay tick
  - 0: Умер 💀 — pet dies (triggers existing `is_alive = False` mechanic)

### Настроение (Happiness)

- Range: 0–100, starts at 50 on pet creation
- Decay: −10 every 24 hours of inactivity
- Gains: any game activity (trivia, casino, pisunchik) increases happiness
- Effects by level:
  - 80–100: Счастливый 😊 — XP +20% bonus
  - 50–79: Доволен 🙂 — no effect
  - 20–49: Грустный 😔 — titles cannot be earned
  - 0–19: Подавлен 😢 — ульта cooldown ×2

### Food Economy

**Game drops (automatic, no command needed):**
| Source | Chance | Reward |
|--------|--------|--------|
| Trivia correct answer | 25% | +1 Корм |
| Casino win | 15% | +1 Корм |
| Pisunchik (any use) | 20% | +1 Корм |

**Shop items (new additions):**
| Item | Cost | Effect |
|------|------|--------|
| 🍖 Корм (basic feed) | 50 BTC | +30 Голод |
| 🍗 Деликатес (deluxe feed) | 200 BTC | +60 Голод, +20 Настроение |

**Feeding mechanic:**
- Food stored as items in player inventory (e.g. `pet_food_basic`, `pet_food_deluxe`)
- "Покормить" button in `/pet` menu opens food selection
- Player taps a food item to consume it

### Player Model Changes

New fields on `Player`:
- `pet_hunger: int = 100`
- `pet_happiness: int = 50`
- `pet_hunger_last_decay: Optional[datetime] = None`
- `pet_happiness_last_activity: Optional[datetime] = None`
- `pet_ulta_used_date: Optional[datetime] = None` — tracks 24h cooldown

### Decay Implementation

Decay is calculated lazily on pet access (not via a background scheduler):
- On each `/pet` open or XP award, compute elapsed time since last decay tick
- Apply accumulated decay ticks to hunger and happiness
- Update `pet_hunger_last_decay` and save

---

## Phase 2 — Ульты & Group Visibility

### Ульты (Stage Abilities)

One use per 24 hours. Disabled if Голод < 10 or Настроение < 20.

| Стадия | Ульта | Эффект |
|--------|-------|--------|
| 🥚 Яйцо | **Казино+** | +2 дополнительных попытки казино сегодня (добавляется к дневному лимиту) |
| 🐣 Малыш | **Халявный ролл** | Следующий Roll game бесплатный — монеты не списываются |
| 🐤 Взрослый | **Оракул** | Перед следующим писюнчиком бот показывает результат заранее. Игрок решает: бросать или нет. Если нет — кулдаун не тратится |
| 🦅 Легендарный | **Халява** | Следующий вопрос викторины засчитывается как правильный автоматически (+XP + стрик) |

**Cooldown tracking:** `pet_ulta_used_date` stores last use timestamp. Ready again after 24h.
**State flags for pending ульты:**
- `pet_ulta_free_roll_pending: bool` — Малыш, consumed on next roll
- `pet_ulta_oracle_pending: bool` — Взрослый, consumed on next pisunchik
- `pet_ulta_trivia_pending: bool` — Легендарный, consumed on next trivia question

### Group Visibility

**Evolution announcement** — posted to chat when stage changes:
```
🎉 Питомец «Барсик» игрока @player эволюционировал!
🥚 Яйцо → 🐣 Малыш
```

**Passive badge** — appended to trivia result and pisunchik result lines:
```
✅ @player 🐤 [Оракул готов] +15 BTC
✅ @player 🥚 +10 BTC
```
- Shows stage emoji always (if pet is alive and active)
- Shows ульта-ready indicator only if ульта is available
- Badge is silent (no extra message) — integrated into existing result strings

---

## Integration Points

| System | Phase 1 | Phase 2 |
|--------|---------|---------|
| `trivia_handlers.py` | food drop on correct answer; happiness +5 | Халява flag check; badge in result |
| `game_handlers.py` (pisunchik) | food drop; happiness +2 | Оракул preview flow; badge in result |
| `game_handlers.py` (casino) | food drop on win; happiness +3 | Казино+ extra spins |
| `game_handlers.py` (roll) | happiness +2 | Халявный ролл free flag |
| `pet_handlers.py` | decay calc; hunger display; feed button | Ульта button; use flow |
| `pet_service.py` | hunger/happiness logic | ульта eligibility checks |
| `shop_handlers.py` | add food items to shop data | — |
| `player.py` | new fields + DB migration | new pending flags |

---

## Out of Scope

- Background scheduler for decay (lazy calculation on access instead)
- Stocks integration (deprecated)
- Vor integration (niche — requires Glowing characteristic)
- Pisunchik cooldown reset (already exists as shop item)
- Multiplayer pet battles
