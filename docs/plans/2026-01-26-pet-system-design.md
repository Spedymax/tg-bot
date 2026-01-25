# Pet System Design

## Overview

A pet system tied to trivia participation. Players create and grow a virtual pet by answering trivia questions. Missing a day kills the pet (with limited monthly revives). Purely cosmetic - no gameplay bonuses.

## Core Mechanics

### Pet Lifecycle
- Player creates pet via `/pet` → chooses name → uploads image
- Pet starts at **Level 1 (Egg stage)**
- Each trivia answer: **+1 XP**
- Correct trivia answer: **+3 bonus XP**
- XP thresholds trigger level ups and evolutions

### Evolution Stages
| Stage | Levels | XP Required |
|-------|--------|-------------|
| Egg | 1-10 | 0 |
| Baby | 11-25 | 50 |
| Adult | 26-50 | 150 |
| Legendary | 51-100 | 350 |

Max level 100 at ~700 XP total.

### Death & Revival
- **Miss one day of trivia** → pet dies (goes dormant)
- Dead pet stays with player, shown as "sleeping/dead" status
- **Revive**: brings pet back, continues from where it left off (max **5 per month**, resets on 1st)
- **Kill permanently**: deletes pet, allows creating a new one

## Title System

- Every **3 correct answers in a row** → earn a random title
- Titles collected permanently (streak resets on wrong answer, titles stay)
- Player can select active title to display
- Displayed as: `Барсик the Мудрець`

### Title Pool
```json
[
  "Мудрець", "Воїн", "Легенда", "Хитрун", "Щасливчик",
  "Геній", "Везунчик", "Чемпіон", "Знавець", "Майстер",
  "Гуру", "Експерт", "Профі", "Ас", "Титан"
]
```
Player can't earn duplicates - re-rolls if already owned.

## Customization

### Customization Phase (at creation & each evolution)
- **Unlimited** name/image changes until locked
- Player uploads their own images (no restrictions)
- Once confirmed, pet is locked until next evolution

### Lock Behavior
- Locked pet: no changes to name/image allowed
- Unlocks again at:
  - Next evolution stage
  - Player kills and recreates pet

## Data Model

### New Player Fields (or separate Pet table)
```python
pet = {
    "name": str,              # "Барсик"
    "image_file_id": str,     # Telegram file_id for uploaded image
    "level": int,             # 1-100
    "xp": int,                # Current XP
    "stage": str,             # "egg", "baby", "adult", "legendary"
    "is_alive": bool,         # True/False
    "is_locked": bool,        # Customization locked?
    "created_at": datetime,   # For tracking
}

pet_titles: list[str]         # ["Мудрець", "Воїн", "Легенда"]
pet_active_title: str | None  # Currently displayed title
pet_revives_used: int         # 0-5, resets monthly
pet_revives_reset_date: date  # When counter was last reset
trivia_streak: int            # Current correct answer streak
```

## UI Design

### Single Command: `/pet`
All interactions via inline buttons. No other commands needed.

### No Pet Exists
```
У тебе ще немає улюбленця!

[🥚 Створити улюбленця]
```

### Pet Unlocked (Customization Phase)
```
[Pet Image]
Ім'я: Барсик
Статус: Налаштування...

[✏️ Змінити ім'я] [🖼 Змінити фото]
[✅ Підтвердити]
```

### Pet Alive & Locked
```
[Pet Image]
🐣 Барсик the Мудрець
Рівень: 15 (Baby)
XP: 45/150
Статус: Живий ✅
Серія правильних: 5 🔥

[🏷 Титули] [💀 Вбити]
```

### Pet Dead
```
[Pet Image]
💀 Барсик the Мудрець
Рівень: 15 (Baby)
Статус: Мертвий 💀
Відродження: 3/5 залишилось

[❤️ Відродити] [🗑 Видалити назавжди]
```

### Title Selection Screen
```
🏷 Твої титули:

• Мудрець ✅ (активний)
• Воїн
• Легенда
• Хитрун

[Мудрець] [Воїн] [Легенда] [Хитрун]
[⬅️ Назад]
```

### Name Change Flow
Button pressed → Bot sends:
```
Напиши нове ім'я для улюбленця:
```
Bot waits for text message, updates name, returns to pet view.

### Image Change Flow
Button pressed → Bot sends:
```
Надішли нове фото для улюбленця:
```
Bot waits for photo message, updates image, returns to pet view.

### Delete Confirmation
```
⚠️ Ти впевнений? Улюбленця буде видалено назавжди!

[❌ Ні, залишити] [✅ Так, видалити]
```

## Notifications

All notifications tag the player at the start of the message.

**Format (with username):**
- Level up: `@username, 🎉 Барсик досяг рівня 15!`
- Evolution: `@username, ✨ Барсик еволюціонував у Baby! Натисни /pet щоб налаштувати.`
- New title: `@username, 🏷 Ти отримав титул "Геній"! 3 правильних відповіді поспіль!`
- Pet died: `@username, 💀 Барсик помер... Ти пропустив день. /pet щоб відродити.`

**For users without username (HTML mention):**
```python
f'<a href="tg://user?id={user_id}">{player_name}</a>, 🎉 Барсик досяг рівня 15!'
```

## Integration Points

### Trivia Handlers (trivia_handlers.py)
- On any trivia answer → if pet alive & locked: +1 XP
- On correct answer → +3 bonus XP, increment streak
- On wrong answer → reset streak to 0
- Every 3 streak → award random title, notify player
- On level up → notify player
- On evolution → notify player, unlock customization

### Quiz Scheduler (quiz_scheduler.py)
- At end of day (midnight), check who didn't answer any trivia
- Mark their pets as dead
- Send death notification to affected players

### Monthly Reset
- On any revive attempt, check `pet_revives_reset_date`
- If new month → reset `pet_revives_used` to 0

## Files to Create/Modify

### New Files
- `src/handlers/pet_handlers.py` - Pet command and callback handlers
- `src/services/pet_service.py` - Pet business logic
- `src/data/pet_titles.json` - Title pool configuration

### Modified Files
- `src/models/player.py` - Add pet fields to Player model
- `src/database/player_service.py` - Add pet CRUD operations
- `src/handlers/trivia_handlers.py` - Integrate XP/streak/death logic
- `src/services/quiz_scheduler.py` - Add daily pet death check
- `src/main.py` - Register pet handlers
