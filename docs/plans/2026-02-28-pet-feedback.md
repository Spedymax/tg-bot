# Pet Feedback & Death Awareness Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the pet feel alive by adding state-aware badges to game output, a death notification, a cooldown timer on the ulta button, and better revives messaging.

**Architecture:** Four independent improvements: (1) unified `get_pet_badge()` in PetService replaces two duplicated inline badge builders; (2) cooldown helper computes remaining time for the ulta button; (3) death flag on the Player model triggers a one-shot chat notification on the next game command; (4) revives display in the dead-pet menu becomes contextual.

**Tech Stack:** Python 3.11, pyTelegramBotAPI, PostgreSQL/psycopg2, pytest

**Design doc:** `docs/plans/2026-02-28-pet-feedback-design.md`

---

### Task 1: Add `pet_death_pending_notify` field

**Files:**
- Modify: `src/models/player.py` (add field near line 57)
- Modify: `src/database/player_service.py` (ALLOWED_PLAYER_FIELDS, UPDATE query ~line 101, INSERT query ~line 149, INSERT values ~line 154, from_db_row ~line 84)
- Create: `src/database/migrations/add_pet_death_notify.sql`

**Step 1: Write the failing test**

```python
# tests/test_pet_death_notify.py
from models.player import Player

def test_player_has_death_pending_notify_field():
    p = Player(player_id=1, player_name='Test')
    assert hasattr(p, 'pet_death_pending_notify')
    assert p.pet_death_pending_notify is False
```

**Step 2: Run test to verify it fails**

```bash
cd /home/spedymax/tg-bot && python -m pytest tests/test_pet_death_notify.py -v
```
Expected: FAIL — `AttributeError` or assertion error.

**Step 3: Add the field to Player**

In `src/models/player.py`, after `pet_ulta_oracle_preview` (around line 58), add:

```python
pet_death_pending_notify: bool = False
```

**Step 4: Add to player_service.py**

In `ALLOWED_PLAYER_FIELDS` (line ~22), add to the set:
```python
'pet_death_pending_notify',
```

In the UPDATE query string (line ~101), after `pet_ulta_oracle_preview = %s`, add:
```sql
pet_death_pending_notify = %s,
```
(before the `WHERE player_id = %s`)

In the UPDATE values tuple (line ~134), after the `pet_ulta_oracle_preview` value, add:
```python
getattr(player, 'pet_death_pending_notify', False),
```

In the INSERT column list (line ~149), add `pet_death_pending_notify,` after `pet_ulta_oracle_preview`.

In the INSERT VALUES placeholder string, add one more `%s,`.

In the INSERT values tuple (line ~177), add after the `pet_ulta_oracle_preview` value:
```python
getattr(player, 'pet_death_pending_notify', False),
```

**Step 5: Create migration SQL**

```sql
-- src/database/migrations/add_pet_death_notify.sql
ALTER TABLE pisunchik_data
ADD COLUMN IF NOT EXISTS pet_death_pending_notify BOOLEAN DEFAULT FALSE;
```

**Step 6: Run test to verify it passes**

```bash
python -m pytest tests/test_pet_death_notify.py -v
```
Expected: PASS.

**Step 7: Commit**

```bash
git add src/models/player.py src/database/player_service.py src/database/migrations/add_pet_death_notify.sql tests/test_pet_death_notify.py
git commit -m "feat: add pet_death_pending_notify field"
```

---

### Task 2: `get_pet_badge()` in PetService

This unifies two duplicated badge builders:
- `trivia_handlers.py:40-44` — `_get_pet_badge()` instance method
- `game_handlers.py:46-52` — inline badge building

**Files:**
- Modify: `src/services/pet_service.py`
- Test: `tests/test_pet_service.py` (create if missing)

**Step 1: Write the failing tests**

```python
# tests/test_pet_service.py
import pytest
from unittest.mock import MagicMock
from services.pet_service import PetService

@pytest.fixture
def svc():
    s = PetService.__new__(PetService)
    s.titles = []
    s.xp_thresholds = {'egg_to_baby': 50, 'baby_to_adult': 150, 'adult_to_legendary': 350, 'max_xp': 700}
    s.level_ranges = {}
    s.streak_for_title = 3
    s.max_revives = 5
    return s

def make_player(svc, hunger=100, happiness=50, stage='baby', alive=True, locked=True):
    p = MagicMock()
    p.pet = {'is_alive': alive, 'is_locked': locked, 'stage': stage}
    p.pet_hunger = hunger
    p.pet_happiness = happiness
    return p

def test_badge_no_pet(svc):
    p = MagicMock()
    p.pet = None
    assert svc.get_pet_badge(p) == ''

def test_badge_dead_pet(svc):
    p = make_player(svc, alive=False)
    assert svc.get_pet_badge(p) == ''

def test_badge_healthy(svc):
    p = make_player(svc, hunger=80, happiness=50)
    assert svc.get_pet_badge(p) == ' 🐣'

def test_badge_hungry(svc):
    p = make_player(svc, hunger=45, happiness=50)
    assert svc.get_pet_badge(p) == ' 🐣 [Голоден 😟]'

def test_badge_very_hungry(svc):
    p = make_player(svc, hunger=20, happiness=50)
    assert svc.get_pet_badge(p) == ' 🐣 [Очень голоден 😫]'

def test_badge_dying(svc):
    p = make_player(svc, hunger=5, happiness=50)
    assert svc.get_pet_badge(p) == ' 🐣 [Умирает! 💀]'

def test_badge_happy(svc):
    p = make_player(svc, hunger=90, happiness=85)
    assert svc.get_pet_badge(p) == ' 🐣 [Счастлив 😊]'

def test_badge_depressed_adds_label(svc):
    p = make_player(svc, hunger=40, happiness=10)
    badge = svc.get_pet_badge(p)
    assert '[Голоден 😟]' in badge
    assert '[Подавлен]' in badge
```

**Step 2: Run to verify they fail**

```bash
python -m pytest tests/test_pet_service.py -v
```
Expected: FAIL — `AttributeError: 'PetService' object has no attribute 'get_pet_badge'`.

**Step 3: Add `get_pet_badge()` to PetService**

Add after `get_ulta_name()` at the bottom of `src/services/pet_service.py`:

```python
def get_pet_badge(self, player) -> str:
    """Return state-aware pet badge for appending to game result lines.
    Returns empty string if pet is absent, dead, or not yet confirmed.
    """
    pet = getattr(player, 'pet', None)
    if not pet or not pet.get('is_alive') or not pet.get('is_locked'):
        return ''

    stage_emoji = self.get_stage_emoji(pet.get('stage', ''))
    hunger = getattr(player, 'pet_hunger', 100)
    happiness = getattr(player, 'pet_happiness', 50)

    if hunger <= 0:
        return ''  # dead — caller should not reach here, but guard anyway

    parts = []
    if hunger < 10:
        parts.append('[Умирает! 💀]')
    elif hunger < 30:
        parts.append('[Очень голоден 😫]')
    elif hunger < 60:
        parts.append('[Голоден 😟]')
    elif happiness >= 80:
        parts.append('[Счастлив 😊]')

    if happiness < 20 and hunger >= 60:
        parts.append('[Подавлен]')
    elif happiness < 20 and parts:
        parts.append('[Подавлен]')

    badge = f' {stage_emoji}'
    if parts:
        badge += ' ' + ' '.join(parts)
    return badge
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_pet_service.py -v
```
Expected: all PASS.

**Step 5: Commit**

```bash
git add src/services/pet_service.py tests/test_pet_service.py
git commit -m "feat: add get_pet_badge() to PetService"
```

---

### Task 3: Replace duplicated badge builders with `get_pet_badge()`

**Files:**
- Modify: `src/handlers/trivia_handlers.py` (lines 40–44, 283)
- Modify: `src/handlers/game_handlers.py` (lines 46–52)

**Step 1: Update trivia_handlers.py**

Remove the `_get_pet_badge()` method (lines 40–44). It looks like:
```python
def _get_pet_badge(self, player) -> str:
    """Get pet stage badge for appending to game result messages."""
    if not player.pet or not player.pet.get('is_alive') or not player.pet.get('is_locked'):
        return ''
    emojis = {'egg': '🥚', 'baby': '🐣', 'adult': '🐤', 'legendary': '🦅'}
    ...
```

Replace the call site at line ~283:
```python
# Before:
_pet_badge = self._get_pet_badge(player) if player else ''
# After:
_pet_badge = self.pet_service.get_pet_badge(player) if player else ''
```

(Note: `self.pet_service` is already available in `TriviaHandlers` — verify it's set in `__init__`.)

**Step 2: Update game_handlers.py**

Replace the inline block at lines 46–52:
```python
# Before:
# Build pet badge
pet_badge = ''
if player.pet and player.pet.get('is_alive') and player.pet.get('is_locked'):
    _stage_emojis = {'egg': '🥚', 'baby': '🐣', 'adult': '🐤', 'legendary': '🦅'}
    pet_badge = _stage_emojis.get(player.pet.get('stage', ''), '')
    if pet_badge:
        pet_badge = f' {pet_badge}'
```

With:
```python
# After:
pet_badge = self.pet_service.get_pet_badge(player)
```

(Note: verify `self.pet_service` exists in `GameHandlers.__init__`; if not, add it the same way `TriviaHandlers` does.)

**Step 3: Run the existing test suite to ensure nothing broke**

```bash
python -m pytest tests/ -v
```
Expected: all previously passing tests still PASS.

**Step 4: Commit**

```bash
git add src/handlers/trivia_handlers.py src/handlers/game_handlers.py
git commit -m "refactor: use pet_service.get_pet_badge() everywhere"
```

---

### Task 4: Ulta cooldown timer

**Files:**
- Modify: `src/services/pet_service.py`
- Modify: `src/handlers/pet_handlers.py` (`_get_pet_buttons`, lines 80–119)

**Step 1: Write the failing test**

Add to `tests/test_pet_service.py`:

```python
from datetime import datetime, timezone, timedelta

def test_ulta_cooldown_none_when_never_used(svc):
    p = make_player(svc)
    p.pet_ulta_used_date = None
    p.pet_happiness = 50
    assert svc.get_ulta_cooldown_remaining(p) is None

def test_ulta_cooldown_returns_timedelta_when_active(svc):
    p = make_player(svc)
    p.pet_happiness = 50
    p.pet_ulta_used_date = datetime.now(timezone.utc) - timedelta(hours=10)
    remaining = svc.get_ulta_cooldown_remaining(p)
    assert remaining is not None
    assert remaining.total_seconds() > 0
    assert remaining.total_seconds() < 14 * 3600  # less than 14h

def test_ulta_cooldown_none_when_ready(svc):
    p = make_player(svc)
    p.pet_happiness = 50
    p.pet_ulta_used_date = datetime.now(timezone.utc) - timedelta(hours=25)
    assert svc.get_ulta_cooldown_remaining(p) is None
```

**Step 2: Run to verify they fail**

```bash
python -m pytest tests/test_pet_service.py::test_ulta_cooldown_none_when_never_used -v
```
Expected: FAIL.

**Step 3: Add `get_ulta_cooldown_remaining()` to PetService**

Add after `get_pet_badge()` in `src/services/pet_service.py`:

```python
def get_ulta_cooldown_remaining(self, player) -> 'Optional[timedelta]':
    """Return remaining cooldown as timedelta, or None if ready/never used."""
    from datetime import timedelta
    used = getattr(player, 'pet_ulta_used_date', None)
    if used is None:
        return None
    happiness = getattr(player, 'pet_happiness', 50)
    cooldown_h = 48 if happiness < 20 else 24
    elapsed = (datetime.now(timezone.utc) - used).total_seconds()
    remaining_s = cooldown_h * 3600 - elapsed
    if remaining_s <= 0:
        return None
    return timedelta(seconds=remaining_s)
```

**Step 4: Update `_get_pet_buttons()` in pet_handlers.py**

Find the block (around line 112–115):
```python
else:
    markup.add(types.InlineKeyboardButton(
        "⚡ Ульта (не готова)", callback_data="pet_ulta_info"
    ))
```

Replace with:
```python
else:
    remaining = self.pet_service.get_ulta_cooldown_remaining(player)
    if remaining is not None:
        total_minutes = int(remaining.total_seconds() // 60)
        if total_minutes >= 60:
            hours = total_minutes // 60
            label = f"⚡ {ulta_name} (через {hours}ч)"
        else:
            label = f"⚡ {ulta_name} (через {total_minutes}м)"
        happiness = getattr(player, 'pet_happiness', 50)
        if happiness < 20:
            label += ' 😢'
    else:
        label = f"⚡ {ulta_name} (не готова)"
    markup.add(types.InlineKeyboardButton(label, callback_data="pet_ulta_info"))
```

Note: `ulta_name` is already computed just above this block — reuse it.

**Step 5: Run tests**

```bash
python -m pytest tests/test_pet_service.py -v
```
Expected: all PASS.

**Step 6: Commit**

```bash
git add src/services/pet_service.py src/handlers/pet_handlers.py tests/test_pet_service.py
git commit -m "feat: show ulta cooldown timer in pet menu"
```

---

### Task 5: Revives display in dead-pet menu

**Files:**
- Modify: `src/services/pet_service.py` (`format_pet_display`, line ~188)
- Modify: `src/handlers/pet_handlers.py` (`_get_pet_buttons`, line ~86)

**Step 1: Update `format_pet_display` in pet_service.py**

Find (around line 188):
```python
if not pet['is_alive']:
    remaining = self.max_revives - revives_used
    text += f"Возрождений: {remaining}/{self.max_revives} осталось\n"
```

Replace with:
```python
if not pet['is_alive']:
    remaining = self.max_revives - revives_used
    if remaining == 0:
        text += f"💀 Возрождений больше нет в этом месяце\n"
    elif remaining == 1:
        text += f"⚠️ Последнее возрождение! (1/{self.max_revives})\n"
    else:
        text += f"Возрождений: {remaining}/{self.max_revives} осталось\n"
```

**Step 2: Update revive button in `_get_pet_buttons` in pet_handlers.py**

Find (around line 86):
```python
if not pet.get('is_alive'):
    markup.add(types.InlineKeyboardButton("❤️ Возродить", callback_data="pet_revive"))
    markup.add(types.InlineKeyboardButton("🗑 Удалить навсегда", callback_data="pet_delete_confirm"))
```

Replace with:
```python
if not pet.get('is_alive'):
    revives_used = getattr(player, 'pet_revives_used', 0)
    revives_remaining = self.pet_service.max_revives - revives_used
    if revives_remaining <= 0:
        markup.add(types.InlineKeyboardButton("❤️ Возродить (нет возрождений)", callback_data="pet_revive"))
    else:
        markup.add(types.InlineKeyboardButton("❤️ Возродить", callback_data="pet_revive"))
    markup.add(types.InlineKeyboardButton("🗑 Удалить навсегда", callback_data="pet_delete_confirm"))
```

**Step 3: Run tests**

```bash
python -m pytest tests/ -v
```
Expected: all PASS.

**Step 4: Commit**

```bash
git add src/services/pet_service.py src/handlers/pet_handlers.py
git commit -m "feat: contextual revives display in dead-pet menu"
```

---

### Task 6: Death notification — set flag when pet dies

**Files:**
- Modify: `src/services/pet_service.py` (`apply_hunger_decay`)

**Step 1: Write the failing test**

Add to `tests/test_pet_service.py`:

```python
def test_death_sets_notify_flag(svc):
    from datetime import timedelta
    p = make_player(svc, hunger=10)
    p.pet_hunger = 10
    p.pet_death_pending_notify = False
    # Set last decay 12h ago so one tick fires
    p.pet_hunger_last_decay = datetime.now(timezone.utc) - timedelta(hours=13)
    died = svc.apply_hunger_decay(p, datetime.now(timezone.utc))
    assert died is True
    assert p.pet['is_alive'] is False
    assert p.pet_death_pending_notify is True
```

**Step 2: Run to verify it fails**

```bash
python -m pytest tests/test_pet_service.py::test_death_sets_notify_flag -v
```
Expected: FAIL — `pet_death_pending_notify` not set.

**Step 3: Update `apply_hunger_decay` in pet_service.py**

Find the return-True block (around line 241):
```python
if player.pet_hunger == 0:
    player.pet['is_alive'] = False
    return True
return False
```

Replace with:
```python
if player.pet_hunger == 0:
    player.pet['is_alive'] = False
    player.pet_death_pending_notify = True
    return True
return False
```

**Step 4: Run tests**

```bash
python -m pytest tests/test_pet_service.py -v
```
Expected: all PASS.

**Step 5: Commit**

```bash
git add src/services/pet_service.py tests/test_pet_service.py
git commit -m "feat: set pet_death_pending_notify when pet starves"
```

---

### Task 7: Death notification — show message on next game command

**Files:**
- Modify: `src/handlers/trivia_handlers.py`
- Modify: `src/handlers/game_handlers.py`

**Context:** The flag `pet_death_pending_notify` is True after the pet dies from hunger. We clear it and show a message on the player's next game interaction. The message is prepended to (or sent before) the game result.

**Step 1: Add helper to check and clear the flag**

In each handler file, add this pattern where player data is loaded and results are sent:

```python
def _maybe_send_death_notice(self, chat_id: int, player) -> None:
    """Send one-shot death notification if pet just died from hunger."""
    if getattr(player, 'pet_death_pending_notify', False):
        player.pet_death_pending_notify = False
        pet_name = ''
        if player.pet:
            from utils.helpers import escape_html
            pet_name = escape_html(player.pet.get('name', 'Питомец'))
        self.bot.send_message(
            chat_id,
            f"💀 {pet_name} умер от голода! Используй /pet чтобы возродить.",
            parse_mode='HTML'
        )
```

Add this method to both `TriviaHandlers` and `GameHandlers`.

**Step 2: Call it in trivia_handlers.py**

Find where a correct trivia answer is processed and `save_player` is called for the player. Just before saving, add:

```python
self._maybe_send_death_notice(chat_id, player)
```

Then ensure `save_player` is called after (it already is — verify).

**Step 3: Call it in game_handlers.py**

Add the same call in the pisunchik handler, roll handler, and casino handler — wherever `player` is loaded and the result is sent. Place it just before sending the result message.

**Step 4: Run full test suite**

```bash
python -m pytest tests/ -v
```
Expected: all PASS.

**Step 5: Run the migration on the server**

```bash
# SSH to the server, then:
sudo -u postgres psql -d server-tg-pisunchik -f /home/spedymax/tg-bot/src/database/migrations/add_pet_death_notify.sql
```

**Step 6: Commit**

```bash
git add src/handlers/trivia_handlers.py src/handlers/game_handlers.py
git commit -m "feat: one-shot death notification on next game command"
```

---

### Task 8: End-to-end smoke test

**Step 1: Restart bot on server**

```bash
sudo systemctl restart bot-manager.service
sudo systemctl status bot-manager.service
```

Expected: `Active: active (running)`, no errors in last 10 lines.

**Step 2: Manual test checklist**

1. Open `/pet` — verify ulta button shows "через Xч" not "не готова" (if used recently)
2. Play trivia — verify pet badge appears after username in result (e.g. `🐣 [Голоден 😟]`)
3. Check dead pet menu — verify revives count shows contextual message when ≤ 1
4. Check logs for any errors: `journalctl -u bot-manager.service -n 50`
