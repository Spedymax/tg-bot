# Pet System Enhancement Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enhance the pet system with hunger/happiness stats, food economy, stage ульты, and group visibility.

**Architecture:** Lazy decay (calculated on pet access, not scheduled), new Player fields persisted via existing PostgreSQL migration pattern, ulta state stored as boolean flags on Player. All game integrations (trivia, casino, pisunchik, roll) receive minimal hook calls to pet logic.

**Tech Stack:** Python, telebot, psycopg2/PostgreSQL, existing PlayerService/PetService pattern.

---

## Phase 1 — Hunger, Happiness, Food Economy

---

### Task 1: DB Migration — Add New Pet Columns

**Files:**
- Create: `src/database/migrations/add_pet_hunger_happiness.sql`

**Step 1: Write the migration SQL**

```sql
-- Add hunger/happiness/ulta fields to pisunchik_data table
ALTER TABLE pisunchik_data
ADD COLUMN IF NOT EXISTS pet_hunger INTEGER DEFAULT 100,
ADD COLUMN IF NOT EXISTS pet_happiness INTEGER DEFAULT 50,
ADD COLUMN IF NOT EXISTS pet_hunger_last_decay TIMESTAMP WITH TIME ZONE DEFAULT NULL,
ADD COLUMN IF NOT EXISTS pet_happiness_last_activity TIMESTAMP WITH TIME ZONE DEFAULT NULL,
ADD COLUMN IF NOT EXISTS pet_ulta_used_date TIMESTAMP WITH TIME ZONE DEFAULT NULL,
ADD COLUMN IF NOT EXISTS pet_ulta_free_roll_pending BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS pet_ulta_oracle_pending BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS pet_ulta_trivia_pending BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS pet_casino_extra_spins INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS pet_ulta_oracle_preview JSONB DEFAULT NULL;
```

**Step 2: Run the migration**

```bash
psql $DATABASE_URL -f src/database/migrations/add_pet_hunger_happiness.sql
```

Expected: `ALTER TABLE` with no errors.

**Step 3: Verify columns exist**

```bash
psql $DATABASE_URL -c "\d pisunchik_data" | grep pet_hunger
```

Expected: `pet_hunger | integer | ...`

**Step 4: Commit**

```bash
git add src/database/migrations/add_pet_hunger_happiness.sql
git commit -m "feat: add pet hunger/happiness/ulta DB columns"
```

---

### Task 2: Player Model — Add New Fields

**Files:**
- Modify: `src/models/player.py`

**Step 1: Write the failing test**

```python
# tests/test_pet_enhancement.py
from models.player import Player

def test_player_has_pet_hunger_default():
    p = Player(player_id=1, player_name="Test")
    assert p.pet_hunger == 100
    assert p.pet_happiness == 50
    assert p.pet_ulta_free_roll_pending == False
    assert p.pet_ulta_oracle_pending == False
    assert p.pet_ulta_trivia_pending == False
    assert p.pet_casino_extra_spins == 0
    assert p.pet_ulta_oracle_preview is None
```

**Step 2: Run test to verify it fails**

```bash
cd src && python -m pytest ../tests/test_pet_enhancement.py::test_player_has_pet_hunger_default -v
```

Expected: FAIL — `Player has no attribute 'pet_hunger'`

**Step 3: Add fields to Player dataclass**

In `src/models/player.py`, after the existing pet system fields (line ~43), add:

```python
    # Pet hunger/happiness stats
    pet_hunger: int = 100
    pet_happiness: int = 50
    pet_hunger_last_decay: Optional[datetime] = None
    pet_happiness_last_activity: Optional[datetime] = None

    # Ulta system
    pet_ulta_used_date: Optional[datetime] = None
    pet_ulta_free_roll_pending: bool = False
    pet_ulta_oracle_pending: bool = False
    pet_ulta_trivia_pending: bool = False
    pet_casino_extra_spins: int = 0
    pet_ulta_oracle_preview: Optional[Dict[str, Any]] = None
```

**Step 4: Update `from_db_row` — datetime fields**

In `from_db_row`, extend the optional datetime fields list (line ~70):

```python
        for field_name in ['pet_revives_reset_date', 'last_trivia_date',
                           'pet_hunger_last_decay', 'pet_happiness_last_activity',
                           'pet_ulta_used_date']:
```

**Step 5: Update `to_db_dict` — serialize oracle preview**

In `to_db_dict`, extend the JSON fields list (line ~84):

```python
        for field_name in ['items', 'characteristics', 'player_stocks', 'statuetki',
                          'chat_id', 'correct_answers', 'nnn_checkins', 'pet', 'pet_titles',
                          'pet_ulta_oracle_preview']:
```

**Step 6: Run test to verify it passes**

```bash
cd src && python -m pytest ../tests/test_pet_enhancement.py::test_player_has_pet_hunger_default -v
```

Expected: PASS

**Step 7: Commit**

```bash
git add src/models/player.py tests/test_pet_enhancement.py
git commit -m "feat: add pet hunger/happiness/ulta fields to Player model"
```

---

### Task 3: PetService — Decay & XP Multiplier Logic

**Files:**
- Modify: `src/services/pet_service.py`

**Step 1: Write the failing tests**

```python
# tests/test_pet_enhancement.py (append)
from datetime import datetime, timezone, timedelta
from models.player import Player
from services.pet_service import PetService

def make_player_with_live_pet():
    p = Player(player_id=1, player_name="Test")
    p.pet = {'name': 'X', 'level': 1, 'xp': 0, 'stage': 'egg',
             'is_alive': True, 'is_locked': True,
             'created_at': datetime.now(timezone.utc).isoformat()}
    return p

def test_get_xp_multiplier_normal():
    svc = PetService()
    p = make_player_with_live_pet()
    p.pet_hunger = 70
    p.pet_happiness = 60
    assert svc.get_xp_multiplier(p) == 1.0

def test_get_xp_multiplier_happy_bonus():
    svc = PetService()
    p = make_player_with_live_pet()
    p.pet_hunger = 70
    p.pet_happiness = 85
    assert svc.get_xp_multiplier(p) == 1.2

def test_get_xp_multiplier_hungry_halved():
    svc = PetService()
    p = make_player_with_live_pet()
    p.pet_hunger = 45
    p.pet_happiness = 60
    assert svc.get_xp_multiplier(p) == 0.5

def test_get_xp_multiplier_very_hungry_stopped():
    svc = PetService()
    p = make_player_with_live_pet()
    p.pet_hunger = 20
    p.pet_happiness = 60
    assert svc.get_xp_multiplier(p) == 0.0

def test_hunger_decay_applies_ticks():
    svc = PetService()
    p = make_player_with_live_pet()
    p.pet_hunger = 100
    now = datetime.now(timezone.utc)
    p.pet_hunger_last_decay = now - timedelta(hours=25)  # 2 ticks
    died = svc.apply_hunger_decay(p, now)
    assert p.pet_hunger == 80
    assert died == False

def test_hunger_decay_kills_pet():
    svc = PetService()
    p = make_player_with_live_pet()
    p.pet_hunger = 5
    now = datetime.now(timezone.utc)
    p.pet_hunger_last_decay = now - timedelta(hours=12)
    died = svc.apply_hunger_decay(p, now)
    assert p.pet_hunger == 0
    assert died == True
    assert p.pet['is_alive'] == False

def test_happiness_decay_applies():
    svc = PetService()
    p = make_player_with_live_pet()
    p.pet_happiness = 70
    now = datetime.now(timezone.utc)
    p.pet_happiness_last_activity = now - timedelta(hours=48)
    svc.apply_happiness_decay(p, now)
    assert p.pet_happiness == 50

def test_record_game_activity_increases_happiness():
    svc = PetService()
    p = make_player_with_live_pet()
    p.pet_happiness = 50
    now = datetime.now(timezone.utc)
    svc.record_game_activity(p, 'trivia', now)
    assert p.pet_happiness == 55
```

**Step 2: Run tests to verify they fail**

```bash
cd src && python -m pytest ../tests/test_pet_enhancement.py -k "multiplier or decay or activity" -v
```

Expected: FAIL — `PetService has no attribute 'get_xp_multiplier'`

**Step 3: Add methods to PetService**

Add to `src/services/pet_service.py` after `format_pet_display`:

```python
    # ─── Hunger / Happiness ───────────────────────────────────────

    def get_xp_multiplier(self, player) -> float:
        """Return XP multiplier based on hunger and happiness."""
        if not player.pet or not player.pet.get('is_alive'):
            return 0.0
        hunger = getattr(player, 'pet_hunger', 100)
        if hunger <= 9:
            return 0.0
        if hunger <= 29:
            return 0.0  # very hungry — XP stopped
        multiplier = 0.5 if hunger <= 59 else 1.0
        happiness = getattr(player, 'pet_happiness', 50)
        if happiness >= 80:
            multiplier *= 1.2
        return multiplier

    def apply_hunger_decay(self, player, now: datetime) -> bool:
        """Apply accumulated hunger decay ticks (every 12h = -10).
        Returns True if pet just died."""
        if not player.pet or not player.pet.get('is_alive'):
            return False
        last = getattr(player, 'pet_hunger_last_decay', None)
        if last is None:
            player.pet_hunger_last_decay = now
            return False
        ticks = int((now - last).total_seconds() // (12 * 3600))
        if ticks <= 0:
            return False
        player.pet_hunger = max(0, getattr(player, 'pet_hunger', 100) - ticks * 10)
        player.pet_hunger_last_decay = last + timedelta(hours=12 * ticks)
        if player.pet_hunger == 0:
            player.pet['is_alive'] = False
            return True
        return False

    def apply_happiness_decay(self, player, now: datetime):
        """Apply accumulated happiness decay ticks (every 24h = -10)."""
        if not player.pet or not player.pet.get('is_alive'):
            return
        last = getattr(player, 'pet_happiness_last_activity', None)
        if last is None:
            player.pet_happiness_last_activity = now
            return
        ticks = int((now - last).total_seconds() // (24 * 3600))
        if ticks <= 0:
            return
        player.pet_happiness = max(0, getattr(player, 'pet_happiness', 50) - ticks * 10)
        # Don't advance last_activity — only game actions reset the timer

    def record_game_activity(self, player, activity: str, now: datetime):
        """Boost happiness on any game action and reset inactivity timer."""
        if not player.pet or not player.pet.get('is_alive') or not player.pet.get('is_locked'):
            return
        gains = {'trivia': 5, 'casino': 3, 'pisunchik': 2, 'roll': 2}
        player.pet_happiness = min(100, getattr(player, 'pet_happiness', 50) + gains.get(activity, 2))
        player.pet_happiness_last_activity = now
```

Also add `from datetime import timedelta` to the imports at the top if not already there.

**Step 4: Run tests to verify they pass**

```bash
cd src && python -m pytest ../tests/test_pet_enhancement.py -k "multiplier or decay or activity" -v
```

Expected: all PASS

**Step 5: Commit**

```bash
git add src/services/pet_service.py tests/test_pet_enhancement.py
git commit -m "feat: add hunger/happiness decay and XP multiplier to PetService"
```

---

### Task 4: Apply Decay on Pet Access + Hook Into XP Award

**Files:**
- Modify: `src/handlers/pet_handlers.py`
- Modify: `src/handlers/trivia_handlers.py`

**Step 1: Apply decay in `show_pet_menu`**

In `src/handlers/pet_handlers.py`, inside `show_pet_menu` after loading `player` (line ~42), add:

```python
        # Apply lazy decay
        if player.pet and player.pet.get('is_alive') and player.pet.get('is_locked'):
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            died = self.pet_service.apply_hunger_decay(player, now)
            self.pet_service.apply_happiness_decay(player, now)
            if died:
                self.player_service.save_player(player)
```

**Step 2: Apply XP multiplier in trivia correct-answer handler**

In `src/handlers/trivia_handlers.py`, around line 272, replace:

```python
                    if player.pet and player.pet.get('is_alive') and player.pet.get('is_locked'):
                        player.pet, _, _ = self.pet_service.add_xp(player.pet, 10)
```

With:

```python
                    if player.pet and player.pet.get('is_alive') and player.pet.get('is_locked'):
                        now = datetime.now(timezone.utc)
                        self.pet_service.apply_hunger_decay(player, now)
                        self.pet_service.record_game_activity(player, 'trivia', now)
                        multiplier = self.pet_service.get_xp_multiplier(player)
                        xp_gain = int(10 * multiplier)
                        if xp_gain > 0:
                            old_stage = player.pet.get('stage')
                            player.pet, _, evolved = self.pet_service.add_xp(player.pet, xp_gain)
                            if evolved:
                                self._announce_evolution(chat_id, player, old_stage)
```

**Step 3: Commit**

```bash
git add src/handlers/pet_handlers.py src/handlers/trivia_handlers.py
git commit -m "feat: apply lazy decay on pet access and hook XP multiplier into trivia"
```

---

### Task 5: Food Drops From Games

**Files:**
- Modify: `src/handlers/trivia_handlers.py`
- Modify: `src/handlers/game_handlers.py`

**Step 1: Trivia food drop**

In `src/handlers/trivia_handlers.py`, after `self.player_service.save_player(player)` on the correct-answer path (~line 279), add before the save:

```python
                    # Food drop (25% chance)
                    import random as _rand
                    if player.pet and player.pet.get('is_alive') and _rand.random() < 0.25:
                        player.add_item('pet_food_basic')
```

**Step 2: Pisunchik food drop**

In `src/handlers/game_handlers.py`, in `pisunchik_command` after `result = self.game_service.execute_pisunchik_command(player)` succeeds (after the `if not result['success']` check), before building `reply_message`, add:

```python
            # Pet activity + food drop
            import random as _rand
            from datetime import datetime, timezone
            from services.pet_service import PetService as _PS
            _ps = _PS()
            _ps.record_game_activity(player, 'pisunchik', datetime.now(timezone.utc))
            if player.pet and player.pet.get('is_alive') and _rand.random() < 0.20:
                player.add_item('pet_food_basic')
            self.player_service.save_player(player)
```

Note: `execute_pisunchik_command` already saves player internally — check that we don't double-save. If it does, load player fresh after the call instead:

```python
            result = self.game_service.execute_pisunchik_command(player)
            if result['success']:
                # reload to avoid stale state from service's internal save
                player = self.player_service.get_player(player_id)
```

**Step 3: Casino food drop**

In `src/handlers/game_handlers.py`, in `casino_command` after `self.player_service.save_player(player)` (line ~82), add before the save:

```python
                import random as _rand
                from datetime import datetime, timezone
                from services.pet_service import PetService as _PS
                _ps = _PS()
                _ps.record_game_activity(player, 'casino', datetime.now(timezone.utc))
                if total_wins > 0 and player.pet and player.pet.get('is_alive') and _rand.random() < 0.15:
                    player.add_item('pet_food_basic')
```

**Step 4: Commit**

```bash
git add src/handlers/trivia_handlers.py src/handlers/game_handlers.py
git commit -m "feat: add food drops from trivia/pisunchik/casino and pet activity tracking"
```

---

### Task 6: Add Food Items to Shop

**Files:**
- Modify: `assets/data/shop.json`

**Step 1: Add prices**

In `assets/data/shop.json`, inside `"prices"`, add:

```json
    "pet_food_basic": 50,
    "pet_food_deluxe": 200
```

**Step 2: Add names**

In `"names"`, add:

```json
    "pet_food_basic": "🍖 Корм для питомца",
    "pet_food_deluxe": "🍗 Деликатес для питомца"
```

**Step 3: Add descriptions**

In `"description"`, add:

```json
    "pet_food_basic": "{Питомец} Восстанавливает 30 голода питомцу. Использование: кнопка Покормить в /pet",
    "pet_food_deluxe": "{Питомец} Восстанавливает 60 голода и 20 настроения питомцу. Использование: кнопка Покормить в /pet"
```

**Step 4: Commit**

```bash
git add assets/data/shop.json
git commit -m "feat: add pet food items to shop"
```

---

### Task 7: Pet Display — Show Hunger/Happiness Bars

**Files:**
- Modify: `src/services/pet_service.py`

**Step 1: Write the failing test**

```python
# tests/test_pet_enhancement.py (append)
def test_format_pet_display_shows_hunger_bar():
    svc = PetService()
    p = make_player_with_live_pet()
    p.pet_hunger = 70
    p.pet_happiness = 60
    text = svc.format_pet_display(p.pet, None, 0, 0, p)
    assert 'Голод' in text
    assert 'Настроение' in text
```

**Step 2: Update `format_pet_display` signature and body**

In `src/services/pet_service.py`, update `format_pet_display` to accept `player` as an optional parameter:

```python
    def format_pet_display(self, pet: Dict[str, Any], active_title: Optional[str],
                           revives_used: int, streak: int, player=None) -> str:
```

At the end of the method, before `return text`, add:

```python
        if player and pet.get('is_alive') and pet.get('is_locked'):
            hunger = getattr(player, 'pet_hunger', 100)
            happiness = getattr(player, 'pet_happiness', 50)

            def _bar(val: int, length: int = 8) -> str:
                filled = max(0, min(length, int(val / 100 * length)))
                return '█' * filled + '░' * (length - filled)

            hunger_icon = '😊' if hunger >= 60 else ('😟' if hunger >= 30 else '😫')
            happy_icon = '😊' if happiness >= 80 else ('🙂' if happiness >= 50 else ('😔' if happiness >= 20 else '😢'))

            text += f"\n🍖 Голод: {_bar(hunger)} {hunger}%  {hunger_icon}"
            text += f"\n🎭 Настроение: {_bar(happiness)} {happiness}%  {happy_icon}"
```

**Step 3: Update all callers of `format_pet_display`**

In `src/handlers/pet_handlers.py` in `show_pet_menu` (~line 59):

```python
        text = self.pet_service.format_pet_display(pet, active_title, revives_used, streak, player)
```

**Step 4: Run test to verify it passes**

```bash
cd src && python -m pytest ../tests/test_pet_enhancement.py::test_format_pet_display_shows_hunger_bar -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add src/services/pet_service.py src/handlers/pet_handlers.py tests/test_pet_enhancement.py
git commit -m "feat: show hunger/happiness bars in pet display"
```

---

### Task 8: Feed Flow in Pet Handlers

**Files:**
- Modify: `src/handlers/pet_handlers.py`

**Step 1: Add feed button to `_get_pet_buttons`**

In the `else` block (alive + locked), after the titles button (line ~97):

```python
            markup.add(types.InlineKeyboardButton("🍖 Покормить", callback_data="pet_feed"))
```

**Step 2: Add routing entries**

In `handle_pet_callback` handlers dict, add:

```python
            'feed':        lambda: self.show_feed_menu(call),
            'feed_basic':  lambda: self.feed_pet(call, 'basic'),
            'feed_deluxe': lambda: self.feed_pet(call, 'deluxe'),
            'feed_back':   lambda: self._dismiss_and_reopen(call),
```

**Step 3: Implement `show_feed_menu`**

```python
    def show_feed_menu(self, call):
        user_id = call.from_user.id
        player = self.player_service.get_player(user_id)
        if not player or not player.pet:
            self.bot.answer_callback_query(call.id)
            return

        basic_count = player.items.count('pet_food_basic')
        deluxe_count = player.items.count('pet_food_deluxe')

        if basic_count == 0 and deluxe_count == 0:
            self.bot.answer_callback_query(call.id, "У тебя нет еды для питомца!")
            return

        self.bot.answer_callback_query(call.id)
        markup = types.InlineKeyboardMarkup()
        if basic_count > 0:
            markup.add(types.InlineKeyboardButton(
                f"🍖 Корм ({basic_count} шт.) +30 голод",
                callback_data="pet_feed_basic"
            ))
        if deluxe_count > 0:
            markup.add(types.InlineKeyboardButton(
                f"🍗 Деликатес ({deluxe_count} шт.) +60 голод +20 настроение",
                callback_data="pet_feed_deluxe"
            ))
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="pet_feed_back"))
        self._replace_with_text(call, "🍽 Чем покормить питомца?", markup)
```

**Step 4: Implement `feed_pet`**

```python
    def feed_pet(self, call, food_type: str):
        from datetime import datetime, timezone
        user_id = call.from_user.id
        player = self.player_service.get_player(user_id)
        if not player or not player.pet:
            self.bot.answer_callback_query(call.id, "Питомец не найден")
            return

        item_key = 'pet_food_basic' if food_type == 'basic' else 'pet_food_deluxe'
        effects = {
            'pet_food_basic':  {'hunger': 30, 'happiness': 0,  'name': 'Корм'},
            'pet_food_deluxe': {'hunger': 60, 'happiness': 20, 'name': 'Деликатес'},
        }
        effect = effects[item_key]

        if not player.remove_item(item_key):
            self.bot.answer_callback_query(call.id, "Еда не найдена!")
            return

        now = datetime.now(timezone.utc)
        self.pet_service.apply_hunger_decay(player, now)
        player.pet_hunger = min(100, getattr(player, 'pet_hunger', 100) + effect['hunger'])
        if effect['happiness'] > 0:
            player.pet_happiness = min(100, getattr(player, 'pet_happiness', 50) + effect['happiness'])

        self.player_service.save_player(player)
        self.bot.answer_callback_query(call.id, f"🐾 {effect['name']} съеден!")
        self.show_pet_menu(call.message.chat.id, user_id,
                           delete_message_id=call.message.message_id)
```

**Step 5: Commit**

```bash
git add src/handlers/pet_handlers.py
git commit -m "feat: add feed button and feed flow to pet handlers"
```

---

## Phase 2 — Ульты & Group Visibility

---

### Task 9: PetService — Ulta Eligibility & Cooldown

**Files:**
- Modify: `src/services/pet_service.py`

**Step 1: Write the failing tests**

```python
# tests/test_pet_enhancement.py (append)
def test_ulta_available_when_ready():
    svc = PetService()
    p = make_player_with_live_pet()
    p.pet_hunger = 70
    p.pet_happiness = 60
    p.pet_ulta_used_date = None
    assert svc.is_ulta_available(p) == True

def test_ulta_not_available_on_cooldown():
    svc = PetService()
    p = make_player_with_live_pet()
    p.pet_hunger = 70
    p.pet_happiness = 60
    p.pet_ulta_used_date = datetime.now(timezone.utc) - timedelta(hours=10)
    assert svc.is_ulta_available(p) == False

def test_ulta_not_available_when_hungry():
    svc = PetService()
    p = make_player_with_live_pet()
    p.pet_hunger = 5
    p.pet_happiness = 60
    assert svc.is_ulta_available(p) == False

def test_ulta_cooldown_doubled_when_depressed():
    svc = PetService()
    p = make_player_with_live_pet()
    p.pet_hunger = 70
    p.pet_happiness = 15  # depressed
    p.pet_ulta_used_date = datetime.now(timezone.utc) - timedelta(hours=25)
    # Normal 24h would be ready, but depressed = 48h
    assert svc.is_ulta_available(p) == False
```

**Step 2: Add methods to PetService**

```python
    # ─── Ulta system ──────────────────────────────────────────────

    ULTA_NAMES = {
        'egg':       '🎰 Казино+',
        'baby':      '🎲 Халявный ролл',
        'adult':     '🔮 Оракул',
        'legendary': '✅ Халява',
    }

    def is_ulta_available(self, player) -> bool:
        """Check if ulta can be used right now."""
        if not player.pet or not player.pet.get('is_alive') or not player.pet.get('is_locked'):
            return False
        hunger = getattr(player, 'pet_hunger', 100)
        happiness = getattr(player, 'pet_happiness', 50)
        if hunger < 10 or happiness < 20:
            return False
        used = getattr(player, 'pet_ulta_used_date', None)
        if used is None:
            return True
        cooldown_h = 48 if happiness < 20 else 24
        return (datetime.now(timezone.utc) - used).total_seconds() >= cooldown_h * 3600

    def mark_ulta_used(self, player):
        player.pet_ulta_used_date = datetime.now(timezone.utc)

    def get_ulta_name(self, stage: str) -> str:
        return self.ULTA_NAMES.get(stage, '⚡ Ульта')
```

**Step 3: Run tests to verify they pass**

```bash
cd src && python -m pytest ../tests/test_pet_enhancement.py -k "ulta" -v
```

Expected: all PASS

**Step 4: Commit**

```bash
git add src/services/pet_service.py tests/test_pet_enhancement.py
git commit -m "feat: add ulta eligibility and cooldown logic to PetService"
```

---

### Task 10: Ulta Button & Activation UI in Pet Handlers

**Files:**
- Modify: `src/handlers/pet_handlers.py`

**Step 1: Add ulta button to `_get_pet_buttons`**

In `_get_pet_buttons`, in the alive+locked block, after the titles row, add:

```python
            stage = pet.get('stage', 'egg')
            if self.pet_service.is_ulta_available(player):
                ulta_name = self.pet_service.get_ulta_name(stage)
                markup.add(types.InlineKeyboardButton(
                    f"⚡ {ulta_name}", callback_data="pet_ulta"
                ))
            else:
                markup.add(types.InlineKeyboardButton(
                    "⚡ Ульта (не готова)", callback_data="pet_ulta_info"
                ))
```

**Step 2: Add routing**

In `handle_pet_callback` handlers dict:

```python
            'ulta':      lambda: self.activate_ulta(call),
            'ulta_info': lambda: self._show_ulta_info(call),
            'oracle_yes': lambda: self.oracle_confirm(call),
            'oracle_no':  lambda: self.oracle_cancel(call),
```

**Step 3: Implement `activate_ulta` dispatcher**

```python
    def activate_ulta(self, call):
        user_id = call.from_user.id
        player = self.player_service.get_player(user_id)
        if not player or not player.pet:
            self.bot.answer_callback_query(call.id, "Питомец не найден")
            return
        if not self.pet_service.is_ulta_available(player):
            self.bot.answer_callback_query(call.id, "Ульта ещё не готова!")
            return

        stage = player.pet.get('stage', 'egg')
        dispatch = {
            'egg':       self._ulta_casino_plus,
            'baby':      self._ulta_free_roll,
            'adult':     self._ulta_oracle,
            'legendary': self._ulta_khalyava,
        }
        handler = dispatch.get(stage)
        if handler:
            handler(call, player)
        else:
            self.bot.answer_callback_query(call.id, "Неизвестная стадия")

    def _show_ulta_info(self, call):
        self.bot.answer_callback_query(call.id,
            "Ульта будет готова через 24 часа после последнего использования. "
            "Также убедись, что питомец не голоден и не подавлен.", show_alert=True)
```

**Step 4: Commit**

```bash
git add src/handlers/pet_handlers.py
git commit -m "feat: add ulta button and activation dispatcher to pet handlers"
```

---

### Task 11: Ульта — Казино+ (Egg)

**Files:**
- Modify: `src/handlers/pet_handlers.py`
- Modify: `src/services/game_service.py`

**Step 1: Implement `_ulta_casino_plus` in pet_handlers**

```python
    def _ulta_casino_plus(self, call, player):
        player.pet_casino_extra_spins = getattr(player, 'pet_casino_extra_spins', 0) + 2
        self.pet_service.mark_ulta_used(player)
        self.player_service.save_player(player)
        self.bot.answer_callback_query(call.id, "🎰 Казино+: +2 попытки казино сегодня!", show_alert=True)
        self.show_pet_menu(call.message.chat.id, call.from_user.id,
                           delete_message_id=call.message.message_id)
```

**Step 2: Modify `can_use_casino` in game_service.py**

Find the CASINO_DAILY_LIMIT check (~line 117) and change:

```python
            if time_elapsed < timedelta(hours=24) and player.casino_usage_count >= GameConfig.CASINO_DAILY_LIMIT:
```

To:

```python
            extra = getattr(player, 'pet_casino_extra_spins', 0)
            effective_limit = GameConfig.CASINO_DAILY_LIMIT + extra
            if time_elapsed < timedelta(hours=24) and player.casino_usage_count >= effective_limit:
```

Also reset extra spins when the daily counter resets (after `player.casino_usage_count = 0`):

```python
                player.casino_usage_count = 0
                player.pet_casino_extra_spins = 0  # reset daily extra spins
```

**Step 3: Commit**

```bash
git add src/handlers/pet_handlers.py src/services/game_service.py
git commit -m "feat: implement Казино+ ulta (egg stage) with extra casino spins"
```

---

### Task 12: Ульта — Халявный ролл (Baby)

**Files:**
- Modify: `src/handlers/pet_handlers.py`
- Modify: `src/services/game_service.py`

**Step 1: Implement `_ulta_free_roll` in pet_handlers**

```python
    def _ulta_free_roll(self, call, player):
        player.pet_ulta_free_roll_pending = True
        self.pet_service.mark_ulta_used(player)
        self.player_service.save_player(player)
        self.bot.answer_callback_query(call.id, "🎲 Халявный ролл активирован! Следующий /roll бесплатный.", show_alert=True)
        self.show_pet_menu(call.message.chat.id, call.from_user.id,
                           delete_message_id=call.message.message_id)
```

**Step 2: Modify `execute_roll_command` in game_service.py**

Find `cost = self.calculate_roll_cost(rolls, player)` (~line 172) and replace:

```python
        if getattr(player, 'pet_ulta_free_roll_pending', False):
            cost = 0
            player.pet_ulta_free_roll_pending = False
        else:
            cost = self.calculate_roll_cost(rolls, player)
```

**Step 3: Commit**

```bash
git add src/handlers/pet_handlers.py src/services/game_service.py
git commit -m "feat: implement Халявный ролл ulta (baby stage) — free roll"
```

---

### Task 13: Ульта — Оракул (Adult)

**Files:**
- Modify: `src/handlers/pet_handlers.py`
- Modify: `src/services/game_service.py`

**Step 1: Add `preview_pisunchik` to game_service.py**

```python
    def preview_pisunchik_result(self, player: Player) -> Dict:
        """Pre-generate a pisunchik result without applying it."""
        import random
        size_change = random.randint(GameConfig.PISUNCHIK_MIN_CHANGE, GameConfig.PISUNCHIK_MAX_CHANGE)
        coins_change = random.randint(GameConfig.PISUNCHIK_MIN_COINS, GameConfig.PISUNCHIK_MAX_COINS)
        # Apply item effects read-only
        if player.has_item('bdsm_kostumchik') and random.random() <= GameConfig.ITEM_EFFECTS['bdsm_kostumchik']['probability']:
            size_change += GameConfig.ITEM_EFFECTS['bdsm_kostumchik']['bonus']
        return {'size_change': size_change, 'coins_change': coins_change}
```

**Step 2: Implement `_ulta_oracle` in pet_handlers**

```python
    def _ulta_oracle(self, call, player):
        preview = self.game_service.preview_pisunchik_result(player)
        player.pet_ulta_oracle_pending = True
        player.pet_ulta_oracle_preview = preview
        self.pet_service.mark_ulta_used(player)
        self.player_service.save_player(player)
        self.bot.answer_callback_query(call.id)

        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("✅ Бросить!", callback_data="pet_oracle_yes"),
            types.InlineKeyboardButton("❌ Пропустить", callback_data="pet_oracle_no"),
        )
        sign = '+' if preview['size_change'] >= 0 else ''
        text = (
            f"🔮 Оракул предсказывает:\n\n"
            f"Изменение: {sign}{preview['size_change']} см\n"
            f"Монеты: +{preview['coins_change']} BTC\n\n"
            f"Бросать?"
        )
        try:
            self.bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        self.bot.send_message(call.message.chat.id, text, reply_markup=markup)
```

**Step 3: Implement `oracle_confirm` and `oracle_cancel`**

```python
    def oracle_confirm(self, call):
        """Player chose to use the oracle result — execute pisunchik with stored preview."""
        user_id = call.from_user.id
        player = self.player_service.get_player(user_id)
        if not player or not player.pet_ulta_oracle_preview:
            self.bot.answer_callback_query(call.id, "Предсказание устарело")
            return
        preview = player.pet_ulta_oracle_preview
        player.pet_ulta_oracle_pending = False
        player.pet_ulta_oracle_preview = None
        # Apply the previewed result
        player.pisunchik_size += preview['size_change']
        player.add_coins(preview['coins_change'])
        player.last_used = __import__('datetime').datetime.now(__import__('datetime').timezone.utc)
        self.player_service.save_player(player)
        self.bot.answer_callback_query(call.id)
        sign = '+' if preview['size_change'] >= 0 else ''
        self.bot.send_message(call.message.chat.id,
            f"🔮 Бросок совершён!\n"
            f"Ваш писюнчик: {player.pisunchik_size} см ({sign}{preview['size_change']} см)\n"
            f"Монеты: +{preview['coins_change']} BTC")

    def oracle_cancel(self, call):
        """Player skipped — no cooldown consumed (ulta already marked used above)."""
        user_id = call.from_user.id
        player = self.player_service.get_player(user_id)
        if player:
            player.pet_ulta_oracle_pending = False
            player.pet_ulta_oracle_preview = None
            self.player_service.save_player(player)
        self.bot.answer_callback_query(call.id, "Пропущено. Писюнчик не брошен.")
        self.show_pet_menu(call.message.chat.id, user_id,
                           delete_message_id=call.message.message_id)
```

**Step 4: Commit**

```bash
git add src/handlers/pet_handlers.py src/services/game_service.py
git commit -m "feat: implement Оракул ulta (adult stage) — preview pisunchik result"
```

---

### Task 14: Ульта — Халява (Legendary)

**Files:**
- Modify: `src/handlers/pet_handlers.py`
- Modify: `src/handlers/trivia_handlers.py`

**Step 1: Implement `_ulta_khalyava` in pet_handlers**

```python
    def _ulta_khalyava(self, call, player):
        player.pet_ulta_trivia_pending = True
        self.pet_service.mark_ulta_used(player)
        self.player_service.save_player(player)
        self.bot.answer_callback_query(call.id,
            "✅ Халява активирована! Следующий вопрос викторины засчитается автоматически.", show_alert=True)
        self.show_pet_menu(call.message.chat.id, call.from_user.id,
                           delete_message_id=call.message.message_id)
```

**Step 2: Check flag in trivia answer handler**

In `src/handlers/trivia_handlers.py`, in the answer callback, find where `is_correct` is determined (where the correct answer is checked). Before the XP block, add:

```python
                    # Халява ulta override
                    if getattr(player, 'pet_ulta_trivia_pending', False):
                        is_correct = True
                        player.pet_ulta_trivia_pending = False
```

Make sure `is_correct` is a local variable set before this check — trace the existing logic to find the right insertion point. The flag is cleared before save.

**Step 3: Commit**

```bash
git add src/handlers/pet_handlers.py src/handlers/trivia_handlers.py
git commit -m "feat: implement Халява ulta (legendary stage) — auto-correct trivia"
```

---

### Task 15: Pet Badge in Game Results

**Files:**
- Modify: `src/handlers/trivia_handlers.py`
- Modify: `src/handlers/game_handlers.py`

**Step 1: Add `_get_pet_badge` helper to TriviaHandlers**

```python
    def _get_pet_badge(self, player) -> str:
        if not player.pet or not player.pet.get('is_alive') or not player.pet.get('is_locked'):
            return ''
        emojis = {'egg': '🥚', 'baby': '🐣', 'adult': '🐤', 'legendary': '🦅'}
        badge = emojis.get(player.pet.get('stage', ''), '')
        if self.pet_service.is_ulta_available(player):
            badge += '⚡'
        return f' {badge}' if badge else ''
```

**Step 2: Append badge to trivia correct-answer result message**

In `trivia_handlers.py`, find where the correct-answer message is sent to the group and append `self._get_pet_badge(player)` to the player mention/name display.

**Step 3: Append badge to pisunchik result in game_handlers.py**

In `game_handlers.py` in `pisunchik_command`, build `pet_badge` and insert in `reply_message`:

```python
            # Pet badge
            from services.pet_service import PetService as _PS
            _pet_badge = ''
            if player.pet and player.pet.get('is_alive') and player.pet.get('is_locked'):
                _stage_emojis = {'egg': '🥚', 'baby': '🐣', 'adult': '🐤', 'legendary': '🦅'}
                _pet_badge = ' ' + _stage_emojis.get(player.pet.get('stage', ''), '')

            reply_message = (
                f"Ваш писюнчик{_pet_badge}: {result['new_size']} см\n"
                f"Изменения: {result['size_change']} см\n"
                f"Также вы получили: {result['coins_change']} BTC"
            )
```

**Step 4: Commit**

```bash
git add src/handlers/trivia_handlers.py src/handlers/game_handlers.py
git commit -m "feat: add pet stage badge to trivia and pisunchik results"
```

---

### Task 16: Evolution Announcements to Group Chat

**Files:**
- Modify: `src/handlers/trivia_handlers.py`

**Step 1: Add `_announce_evolution` to TriviaHandlers**

```python
    def _announce_evolution(self, chat_id: int, player, old_stage: str):
        stage_names = {'egg': 'Яйцо', 'baby': 'Малыш', 'adult': 'Взрослый', 'legendary': 'Легендарный'}
        stage_emojis = {'egg': '🥚', 'baby': '🐣', 'adult': '🐤', 'legendary': '🦅'}
        new_stage = player.pet.get('stage', '')
        pet_name = escape_html(player.pet.get('name', 'питомец'))
        mention = f'<a href="tg://user?id={player.player_id}">{escape_html(player.player_name)}</a>'
        text = (
            f"🎉 Питомец «{pet_name}» игрока {mention} эволюционировал!\n"
            f"{stage_emojis.get(old_stage, '')} {stage_names.get(old_stage, old_stage)} → "
            f"{stage_emojis.get(new_stage, '')} {stage_names.get(new_stage, new_stage)}"
        )
        try:
            self.bot.send_message(chat_id, text, parse_mode='HTML')
        except Exception as e:
            logger.error(f"Failed to send evolution announcement: {e}")
```

**Step 2: Verify the `if evolved:` call added in Task 4 calls this method**

In `trivia_handlers.py` (Task 4 Step 2), confirm this line is present:

```python
                            if evolved:
                                self._announce_evolution(chat_id, player, old_stage)
```

And that `old_stage = player.pet.get('stage')` is captured BEFORE calling `add_xp`.

**Step 3: Commit**

```bash
git add src/handlers/trivia_handlers.py
git commit -m "feat: announce pet evolution to group chat"
```

---

## Final Verification

```bash
cd src && python -m pytest ../tests/test_pet_enhancement.py -v
```

All tests should pass. Manually test the flow:
1. `/pet` shows hunger/happiness bars
2. Correct trivia → pet gets XP (with multiplier), food drop appears in items
3. `/pet` → Покормить → basic/deluxe food works
4. `/pet` → ulta button appears after 24h
5. Each stage ulta: Казино+ gives extra spins, Халявный ролл makes next roll free, Оракул shows preview, Халява auto-corrects next trivia
6. Evolving shows group announcement
7. Trivia/pisunchik results show stage badge
