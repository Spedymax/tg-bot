# Pet System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement a pet system where players grow pets by participating in trivia, with evolution stages, titles, and revival mechanics.

**Architecture:** New PetService handles pet logic, PetHandlers manages `/pet` command with inline buttons. Trivia integration adds XP on answers. QuizScheduler gets daily pet death check at midnight.

**Tech Stack:** Python, pyTelegramBotAPI, PostgreSQL, existing Player model pattern

---

## Task 1: Add Pet Fields to Player Model

**Files:**
- Modify: `src/models/player.py:6-35`

**Step 1: Add pet fields to Player dataclass**

Add these fields after line 30 (after `miniapp_total_winnings`):

```python
    # Pet system fields
    pet: Optional[Dict[str, Any]] = field(default_factory=lambda: None)
    pet_titles: List[str] = field(default_factory=list)
    pet_active_title: Optional[str] = None
    pet_revives_used: int = 0
    pet_revives_reset_date: Optional[datetime] = None
    trivia_streak: int = 0
    last_trivia_date: Optional[datetime] = None
```

**Step 2: Update JSON field handling in `from_db_row`**

Add `'pet'` and `'pet_titles'` to the JSON fields list at line 43:

```python
        for field_name in ['items', 'characteristics', 'player_stocks', 'statuetki',
                          'chat_id', 'correct_answers', 'nnn_checkins', 'pet', 'pet_titles']:
```

**Step 3: Update `to_db_dict` method**

Add `'pet'` and `'pet_titles'` to the list at line 66:

```python
        for field_name in ['items', 'characteristics', 'player_stocks', 'statuetki',
                          'chat_id', 'correct_answers', 'nnn_checkins', 'pet', 'pet_titles']:
```

**Step 4: Commit**

```bash
git add src/models/player.py
git commit -m "feat(pet): add pet system fields to Player model"
```

---

## Task 2: Update Database Schema

**Files:**
- Modify: `src/database/player_service.py:11-16, 84-106, 109-125`

**Step 1: Add pet fields to ALLOWED_PLAYER_FIELDS**

Update the whitelist at line 11:

```python
ALLOWED_PLAYER_FIELDS = {
    'player_name', 'pisunchik_size', 'coins', 'items', 'characteristics',
    'player_stocks', 'statuetki', 'chat_id', 'correct_answers', 'nnn_checkins',
    'last_used', 'last_vor', 'last_prezervativ', 'last_joke', 'casino_last_used',
    'casino_usage_count', 'ballzzz_number', 'notified',
    'pet', 'pet_titles', 'pet_active_title', 'pet_revives_used',
    'pet_revives_reset_date', 'trivia_streak', 'last_trivia_date'
}
```

**Step 2: Update save_player UPDATE query**

Add pet fields to the UPDATE query (after line 92):

```python
                    update_query = """
                        UPDATE pisunchik_data SET
                            player_name = %s, pisunchik_size = %s, coins = %s,
                            items = %s, characteristics = %s, player_stocks = %s,
                            statuetki = %s, chat_id = %s, correct_answers = %s,
                            nnn_checkins = %s, last_used = %s, last_vor = %s,
                            last_prezervativ = %s, last_joke = %s, casino_last_used = %s,
                            casino_usage_count = %s, ballzzz_number = %s, notified = %s,
                            miniapp_daily_spins = %s, miniapp_last_spin_date = %s, miniapp_total_winnings = %s,
                            pet = %s, pet_titles = %s, pet_active_title = %s,
                            pet_revives_used = %s, pet_revives_reset_date = %s,
                            trivia_streak = %s, last_trivia_date = %s
                        WHERE player_id = %s
                    """
```

**Step 3: Update execute parameters**

Add the new fields to cursor.execute parameters:

```python
                    cursor.execute(update_query, (
                        player.player_name, player.pisunchik_size, player.coins,
                        json.dumps(player.items) if isinstance(player.items, list) else player.items,
                        json.dumps(player.characteristics) if isinstance(player.characteristics, list) else player.characteristics,
                        json.dumps(player.player_stocks) if isinstance(player.player_stocks, list) else player.player_stocks,
                        json.dumps(player.statuetki) if isinstance(player.statuetki, list) else player.statuetki,
                        json.dumps(player.chat_id) if isinstance(player.chat_id, list) else player.chat_id,
                        json.dumps(player.correct_answers) if isinstance(player.correct_answers, list) else player.correct_answers,
                        json.dumps(player.nnn_checkins) if isinstance(player.nnn_checkins, list) else player.nnn_checkins,
                        player.last_used, player.last_vor,
                        player.last_prezervativ, player.last_joke, player.casino_last_used,
                        player.casino_usage_count, player.ballzzz_number, player.notified,
                        getattr(player, 'miniapp_daily_spins', 0),
                        getattr(player, 'miniapp_last_spin_date', datetime.min.replace(tzinfo=timezone.utc)),
                        getattr(player, 'miniapp_total_winnings', 0.0),
                        json.dumps(getattr(player, 'pet', None)),
                        json.dumps(getattr(player, 'pet_titles', [])),
                        getattr(player, 'pet_active_title', None),
                        getattr(player, 'pet_revives_used', 0),
                        getattr(player, 'pet_revives_reset_date', None),
                        getattr(player, 'trivia_streak', 0),
                        getattr(player, 'last_trivia_date', None),
                        player.player_id
                    ))
```

**Step 4: Create database migration script**

Create file `src/database/migrations/add_pet_fields.sql`:

```sql
-- Add pet system fields to pisunchik_data table
ALTER TABLE pisunchik_data
ADD COLUMN IF NOT EXISTS pet JSONB DEFAULT NULL,
ADD COLUMN IF NOT EXISTS pet_titles JSONB DEFAULT '[]',
ADD COLUMN IF NOT EXISTS pet_active_title VARCHAR(100) DEFAULT NULL,
ADD COLUMN IF NOT EXISTS pet_revives_used INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS pet_revives_reset_date TIMESTAMP WITH TIME ZONE DEFAULT NULL,
ADD COLUMN IF NOT EXISTS trivia_streak INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS last_trivia_date TIMESTAMP WITH TIME ZONE DEFAULT NULL;
```

**Step 5: Commit**

```bash
git add src/database/player_service.py src/database/migrations/add_pet_fields.sql
git commit -m "feat(pet): update database schema for pet system"
```

---

## Task 3: Create Pet Titles Configuration

**Files:**
- Create: `assets/data/pet_titles.json`

**Step 1: Create the titles JSON file**

```json
{
    "titles": [
        "Мудрець",
        "Воїн",
        "Легенда",
        "Хитрун",
        "Щасливчик",
        "Геній",
        "Везунчик",
        "Чемпіон",
        "Знавець",
        "Майстер",
        "Гуру",
        "Експерт",
        "Профі",
        "Ас",
        "Титан",
        "Мозок",
        "Розумник",
        "Всезнайка",
        "Ерудит",
        "Інтелектуал"
    ],
    "xp_thresholds": {
        "egg_to_baby": 50,
        "baby_to_adult": 150,
        "adult_to_legendary": 350,
        "max_xp": 700
    },
    "level_ranges": {
        "egg": [1, 10],
        "baby": [11, 25],
        "adult": [26, 50],
        "legendary": [51, 100]
    },
    "streak_for_title": 3,
    "max_revives_per_month": 5
}
```

**Step 2: Commit**

```bash
git add assets/data/pet_titles.json
git commit -m "feat(pet): add pet titles configuration"
```

---

## Task 4: Create Pet Service

**Files:**
- Create: `src/services/pet_service.py`

**Step 1: Create the PetService class**

```python
import json
import random
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger(__name__)


class PetService:
    """Service for managing pet system logic."""

    def __init__(self, config_path: str = '/home/spedymax/tg-bot/assets/data/pet_titles.json'):
        self.config = self._load_config(config_path)
        self.titles = self.config.get('titles', [])
        self.xp_thresholds = self.config.get('xp_thresholds', {})
        self.level_ranges = self.config.get('level_ranges', {})
        self.streak_for_title = self.config.get('streak_for_title', 3)
        self.max_revives = self.config.get('max_revives_per_month', 5)

    def _load_config(self, path: str) -> dict:
        """Load pet configuration from JSON file."""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading pet config: {e}")
            return {}

    def create_pet(self, name: str, image_file_id: Optional[str] = None) -> Dict[str, Any]:
        """Create a new pet with initial values."""
        return {
            "name": name,
            "image_file_id": image_file_id,
            "level": 1,
            "xp": 0,
            "stage": "egg",
            "is_alive": True,
            "is_locked": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        }

    def calculate_level(self, xp: int) -> int:
        """Calculate level from XP."""
        max_xp = self.xp_thresholds.get('max_xp', 700)
        # Linear progression: level 1 at 0 XP, level 100 at max_xp
        level = int((xp / max_xp) * 99) + 1
        return min(100, max(1, level))

    def get_stage(self, level: int) -> str:
        """Get evolution stage from level."""
        for stage, (min_lvl, max_lvl) in self.level_ranges.items():
            if min_lvl <= level <= max_lvl:
                return stage
        return "legendary"

    def get_xp_for_next_evolution(self, current_stage: str) -> Optional[int]:
        """Get XP needed for next evolution."""
        stage_thresholds = {
            "egg": self.xp_thresholds.get('egg_to_baby', 50),
            "baby": self.xp_thresholds.get('baby_to_adult', 150),
            "adult": self.xp_thresholds.get('adult_to_legendary', 350),
            "legendary": None
        }
        return stage_thresholds.get(current_stage)

    def add_xp(self, pet: Dict[str, Any], xp_amount: int) -> Tuple[Dict[str, Any], bool, bool]:
        """
        Add XP to pet and check for level up / evolution.
        Returns: (updated_pet, leveled_up, evolved)
        """
        if not pet or not pet.get('is_alive') or not pet.get('is_locked'):
            return pet, False, False

        old_level = pet['level']
        old_stage = pet['stage']

        pet['xp'] = pet.get('xp', 0) + xp_amount
        pet['level'] = self.calculate_level(pet['xp'])
        pet['stage'] = self.get_stage(pet['level'])

        leveled_up = pet['level'] > old_level
        evolved = pet['stage'] != old_stage

        # Unlock customization on evolution
        if evolved:
            pet['is_locked'] = False

        return pet, leveled_up, evolved

    def kill_pet(self, pet: Dict[str, Any]) -> Dict[str, Any]:
        """Mark pet as dead."""
        if pet:
            pet['is_alive'] = False
        return pet

    def revive_pet(self, pet: Dict[str, Any], revives_used: int, reset_date: Optional[datetime]) -> Tuple[Dict[str, Any], int, datetime, bool]:
        """
        Attempt to revive pet.
        Returns: (updated_pet, new_revives_used, new_reset_date, success)
        """
        now = datetime.now(timezone.utc)

        # Check if we need to reset monthly counter
        if reset_date is None or reset_date.month != now.month or reset_date.year != now.year:
            revives_used = 0
            reset_date = now

        # Check if revives available
        if revives_used >= self.max_revives:
            return pet, revives_used, reset_date, False

        # Revive the pet
        if pet:
            pet['is_alive'] = True
            revives_used += 1

        return pet, revives_used, reset_date, True

    def get_random_title(self, owned_titles: List[str]) -> Optional[str]:
        """Get a random title that player doesn't own yet."""
        available = [t for t in self.titles if t not in owned_titles]
        if available:
            return random.choice(available)
        # If all titles owned, return random anyway (won't be added)
        return None

    def check_streak_reward(self, streak: int, owned_titles: List[str]) -> Optional[str]:
        """Check if streak earns a new title. Returns new title or None."""
        if streak > 0 and streak % self.streak_for_title == 0:
            return self.get_random_title(owned_titles)
        return None

    def get_stage_emoji(self, stage: str) -> str:
        """Get emoji for evolution stage."""
        return {
            "egg": "🥚",
            "baby": "🐣",
            "adult": "🐤",
            "legendary": "🦅"
        }.get(stage, "🐾")

    def get_stage_name(self, stage: str) -> str:
        """Get Ukrainian name for evolution stage."""
        return {
            "egg": "Яйце",
            "baby": "Малюк",
            "adult": "Дорослий",
            "legendary": "Легендарний"
        }.get(stage, stage)

    def format_pet_display(self, pet: Dict[str, Any], active_title: Optional[str],
                           revives_used: int, streak: int) -> str:
        """Format pet info for display."""
        if not pet:
            return "У тебе ще немає улюбленця!"

        stage_emoji = self.get_stage_emoji(pet['stage'])
        stage_name = self.get_stage_name(pet['stage'])

        name_display = pet['name']
        if active_title:
            name_display = f"{pet['name']} the {active_title}"

        status = "Живий ✅" if pet['is_alive'] else "Мертвий 💀"

        # Calculate XP for next level/evolution
        next_evo_xp = self.get_xp_for_next_evolution(pet['stage'])
        xp_display = f"{pet['xp']}"
        if next_evo_xp:
            xp_display = f"{pet['xp']}/{next_evo_xp}"

        text = f"{stage_emoji} {name_display}\n"
        text += f"Рівень: {pet['level']} ({stage_name})\n"
        text += f"XP: {xp_display}\n"
        text += f"Статус: {status}\n"

        if pet['is_alive'] and streak > 0:
            text += f"Серія правильних: {streak} 🔥\n"

        if not pet['is_alive']:
            remaining = self.max_revives - revives_used
            text += f"Відродження: {remaining}/{self.max_revives} залишилось\n"

        if not pet.get('is_locked'):
            text += "\n⚙️ Статус: Налаштування..."

        return text
```

**Step 2: Commit**

```bash
git add src/services/pet_service.py
git commit -m "feat(pet): create PetService with core pet logic"
```

---

## Task 5: Create Pet Handlers

**Files:**
- Create: `src/handlers/pet_handlers.py`

**Step 1: Create the PetHandlers class**

```python
import logging
from telebot import types
from datetime import datetime, timezone
from typing import Optional
from services.pet_service import PetService
from utils.helpers import escape_html

logger = logging.getLogger(__name__)


class PetHandlers:
    """Handlers for pet system commands and callbacks."""

    def __init__(self, bot, player_service, game_service):
        self.bot = bot
        self.player_service = player_service
        self.game_service = game_service
        self.pet_service = PetService()

        # Temp storage for waiting user input
        self.waiting_for_name = {}  # {user_id: message_id}
        self.waiting_for_image = {}  # {user_id: message_id}

    def setup_handlers(self):
        """Setup all pet-related command handlers."""

        @self.bot.message_handler(commands=['pet'])
        def pet_command(message):
            """Handle /pet command - main pet interface."""
            self.show_pet_menu(message.chat.id, message.from_user.id)

        # Callback handlers
        @self.bot.callback_query_handler(func=lambda call: call.data.startswith('pet_'))
        def pet_callback(call):
            """Handle all pet-related callbacks."""
            self.handle_pet_callback(call)

        # Text input handlers
        @self.bot.message_handler(func=lambda m: m.from_user.id in self.waiting_for_name)
        def handle_name_input(message):
            """Handle pet name input."""
            self.process_name_input(message)

        # Photo input handlers
        @self.bot.message_handler(content_types=['photo'],
                                   func=lambda m: m.from_user.id in self.waiting_for_image)
        def handle_image_input(message):
            """Handle pet image upload."""
            self.process_image_input(message)

    def show_pet_menu(self, chat_id: int, user_id: int, message_id: int = None):
        """Show the main pet menu with inline buttons."""
        player = self.player_service.get_player(user_id)

        if not player:
            self.bot.send_message(chat_id, "Ви не зареєстровані як гравець.")
            return

        pet = getattr(player, 'pet', None)

        if not pet:
            # No pet - show create button
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🥚 Створити улюбленця", callback_data="pet_create"))

            text = "У тебе ще немає улюбленця!"

            if message_id:
                self.bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)
            else:
                self.bot.send_message(chat_id, text, reply_markup=markup)
            return

        # Has pet - show pet info with appropriate buttons
        active_title = getattr(player, 'pet_active_title', None)
        revives_used = getattr(player, 'pet_revives_used', 0)
        streak = getattr(player, 'trivia_streak', 0)

        text = self.pet_service.format_pet_display(pet, active_title, revives_used, streak)
        markup = self._get_pet_buttons(pet, player)

        # Send with image if available
        if pet.get('image_file_id') and not message_id:
            try:
                self.bot.send_photo(chat_id, pet['image_file_id'], caption=text,
                                    reply_markup=markup, parse_mode='HTML')
                return
            except Exception as e:
                logger.error(f"Error sending pet image: {e}")

        if message_id:
            self.bot.edit_message_text(text, chat_id, message_id, reply_markup=markup, parse_mode='HTML')
        else:
            self.bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')

    def _get_pet_buttons(self, pet: dict, player) -> types.InlineKeyboardMarkup:
        """Get appropriate buttons based on pet state."""
        markup = types.InlineKeyboardMarkup()

        if not pet.get('is_alive'):
            # Dead pet buttons
            markup.add(types.InlineKeyboardButton("❤️ Відродити", callback_data="pet_revive"))
            markup.add(types.InlineKeyboardButton("🗑 Видалити назавжди", callback_data="pet_delete_confirm"))
        elif not pet.get('is_locked'):
            # Unlocked pet (customization mode)
            markup.row(
                types.InlineKeyboardButton("✏️ Змінити ім'я", callback_data="pet_name"),
                types.InlineKeyboardButton("🖼 Змінити фото", callback_data="pet_image")
            )
            markup.add(types.InlineKeyboardButton("✅ Підтвердити", callback_data="pet_confirm"))
        else:
            # Alive and locked pet
            pet_titles = getattr(player, 'pet_titles', [])
            if pet_titles:
                markup.add(types.InlineKeyboardButton("🏷 Титули", callback_data="pet_titles"))
            markup.add(types.InlineKeyboardButton("💀 Вбити", callback_data="pet_kill_confirm"))

        return markup

    def handle_pet_callback(self, call):
        """Route pet callbacks to appropriate handlers."""
        user_id = call.from_user.id
        chat_id = call.message.chat.id
        message_id = call.message.message_id
        action = call.data.replace('pet_', '')

        handlers = {
            'create': lambda: self.create_pet(call),
            'name': lambda: self.request_name(call),
            'image': lambda: self.request_image(call),
            'confirm': lambda: self.confirm_pet(call),
            'revive': lambda: self.revive_pet(call),
            'kill_confirm': lambda: self.show_kill_confirm(call),
            'kill_yes': lambda: self.kill_pet(call),
            'kill_no': lambda: self.show_pet_menu(chat_id, user_id, message_id),
            'delete_confirm': lambda: self.show_delete_confirm(call),
            'delete_yes': lambda: self.delete_pet(call),
            'delete_no': lambda: self.show_pet_menu(chat_id, user_id, message_id),
            'titles': lambda: self.show_titles(call),
            'titles_back': lambda: self.show_pet_menu(chat_id, user_id, message_id),
        }

        # Handle title selection (pet_title_TitleName)
        if action.startswith('title_') and action != 'titles' and action != 'titles_back':
            self.select_title(call, action.replace('title_', ''))
            return

        handler = handlers.get(action)
        if handler:
            handler()
        else:
            self.bot.answer_callback_query(call.id, "Невідома дія")

    def create_pet(self, call):
        """Start pet creation process."""
        user_id = call.from_user.id
        player = self.player_service.get_player(user_id)

        if not player:
            self.bot.answer_callback_query(call.id, "Гравець не знайдений")
            return

        # Create pet with default name
        pet = self.pet_service.create_pet("Новий улюбленець")
        player.pet = pet
        self.player_service.save_player(player)

        self.bot.answer_callback_query(call.id, "Улюбленця створено!")
        self.show_pet_menu(call.message.chat.id, user_id, call.message.message_id)

    def request_name(self, call):
        """Request new pet name from user."""
        user_id = call.from_user.id
        chat_id = call.message.chat.id

        self.waiting_for_name[user_id] = call.message.message_id

        self.bot.answer_callback_query(call.id)
        self.bot.send_message(chat_id, "Напиши нове ім'я для улюбленця:")

    def process_name_input(self, message):
        """Process pet name input."""
        user_id = message.from_user.id
        chat_id = message.chat.id
        new_name = message.text.strip()[:50]  # Limit name length

        if user_id not in self.waiting_for_name:
            return

        del self.waiting_for_name[user_id]

        player = self.player_service.get_player(user_id)
        if player and player.pet and not player.pet.get('is_locked'):
            player.pet['name'] = escape_html(new_name)
            self.player_service.save_player(player)
            self.bot.send_message(chat_id, f"Ім'я змінено на: {new_name}")

        self.show_pet_menu(chat_id, user_id)

    def request_image(self, call):
        """Request new pet image from user."""
        user_id = call.from_user.id
        chat_id = call.message.chat.id

        self.waiting_for_image[user_id] = call.message.message_id

        self.bot.answer_callback_query(call.id)
        self.bot.send_message(chat_id, "Надішли нове фото для улюбленця:")

    def process_image_input(self, message):
        """Process pet image upload."""
        user_id = message.from_user.id
        chat_id = message.chat.id

        if user_id not in self.waiting_for_image:
            return

        del self.waiting_for_image[user_id]

        # Get the largest photo
        photo = message.photo[-1]
        file_id = photo.file_id

        player = self.player_service.get_player(user_id)
        if player and player.pet and not player.pet.get('is_locked'):
            player.pet['image_file_id'] = file_id
            self.player_service.save_player(player)
            self.bot.send_message(chat_id, "Фото оновлено!")

        self.show_pet_menu(chat_id, user_id)

    def confirm_pet(self, call):
        """Lock pet customization."""
        user_id = call.from_user.id
        player = self.player_service.get_player(user_id)

        if player and player.pet:
            player.pet['is_locked'] = True
            self.player_service.save_player(player)
            self.bot.answer_callback_query(call.id, "Улюбленця підтверджено! Тепер він буде рости.")

        self.show_pet_menu(call.message.chat.id, user_id, call.message.message_id)

    def revive_pet(self, call):
        """Attempt to revive dead pet."""
        user_id = call.from_user.id
        player = self.player_service.get_player(user_id)

        if not player or not player.pet:
            self.bot.answer_callback_query(call.id, "Улюбленця не знайдено")
            return

        revives_used = getattr(player, 'pet_revives_used', 0)
        reset_date = getattr(player, 'pet_revives_reset_date', None)

        pet, new_revives, new_reset, success = self.pet_service.revive_pet(
            player.pet, revives_used, reset_date
        )

        if success:
            player.pet = pet
            player.pet_revives_used = new_revives
            player.pet_revives_reset_date = new_reset
            self.player_service.save_player(player)
            self.bot.answer_callback_query(call.id, "Улюбленця відроджено!")
        else:
            self.bot.answer_callback_query(call.id, "Немає відроджень на цей місяць!")

        self.show_pet_menu(call.message.chat.id, user_id, call.message.message_id)

    def show_kill_confirm(self, call):
        """Show kill confirmation."""
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("❌ Ні, залишити", callback_data="pet_kill_no"),
            types.InlineKeyboardButton("✅ Так, вбити", callback_data="pet_kill_yes")
        )

        self.bot.edit_message_text(
            "⚠️ Ти впевнений? Улюбленець помре і потребуватиме відродження!",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )

    def kill_pet(self, call):
        """Kill pet (make it dormant)."""
        user_id = call.from_user.id
        player = self.player_service.get_player(user_id)

        if player and player.pet:
            player.pet = self.pet_service.kill_pet(player.pet)
            self.player_service.save_player(player)
            self.bot.answer_callback_query(call.id, "Улюбленець помер 💀")

        self.show_pet_menu(call.message.chat.id, user_id, call.message.message_id)

    def show_delete_confirm(self, call):
        """Show delete confirmation."""
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("❌ Ні, залишити", callback_data="pet_delete_no"),
            types.InlineKeyboardButton("✅ Так, видалити", callback_data="pet_delete_yes")
        )

        self.bot.edit_message_text(
            "⚠️ Ти впевнений? Улюбленця буде видалено НАЗАВЖДИ! Весь прогрес буде втрачено!",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )

    def delete_pet(self, call):
        """Permanently delete pet."""
        user_id = call.from_user.id
        player = self.player_service.get_player(user_id)

        if player:
            player.pet = None
            # Keep titles - they're permanent
            self.player_service.save_player(player)
            self.bot.answer_callback_query(call.id, "Улюбленця видалено")

        self.show_pet_menu(call.message.chat.id, user_id, call.message.message_id)

    def show_titles(self, call):
        """Show titles selection screen."""
        user_id = call.from_user.id
        player = self.player_service.get_player(user_id)

        if not player:
            return

        titles = getattr(player, 'pet_titles', [])
        active_title = getattr(player, 'pet_active_title', None)

        if not titles:
            self.bot.answer_callback_query(call.id, "У тебе ще немає титулів!")
            return

        text = "🏷 Твої титули:\n\n"
        for title in titles:
            marker = " ✅ (активний)" if title == active_title else ""
            text += f"• {title}{marker}\n"

        markup = types.InlineKeyboardMarkup(row_width=2)
        buttons = [types.InlineKeyboardButton(t, callback_data=f"pet_title_{t}") for t in titles]
        markup.add(*buttons)
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="pet_titles_back"))

        self.bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )

    def select_title(self, call, title: str):
        """Select active title."""
        user_id = call.from_user.id
        player = self.player_service.get_player(user_id)

        if player and title in getattr(player, 'pet_titles', []):
            player.pet_active_title = title
            self.player_service.save_player(player)
            self.bot.answer_callback_query(call.id, f"Титул '{title}' активовано!")

        self.show_titles(call)

    def get_player_mention(self, user_id: int, player_name: str, username: Optional[str] = None) -> str:
        """Get mention string for player."""
        if username:
            return f"@{username}"
        return f'<a href="tg://user?id={user_id}">{escape_html(player_name)}</a>'
```

**Step 2: Commit**

```bash
git add src/handlers/pet_handlers.py
git commit -m "feat(pet): create PetHandlers with inline button UI"
```

---

## Task 6: Integrate Pet with Trivia System

**Files:**
- Modify: `src/handlers/trivia_handlers.py:12-28, 261-268`

**Step 1: Add pet service import and initialization**

At the top of the file, add import:

```python
from services.pet_service import PetService
```

In `__init__` method, add:

```python
        self.pet_service = PetService()
```

**Step 2: Create method for pet XP and streak handling**

Add new method after `handle_answer_callback`:

```python
    def _update_pet_on_trivia(self, player, is_correct: bool, chat_id: int) -> list:
        """
        Update pet XP and streak after trivia answer.
        Returns list of notification messages to send.
        """
        notifications = []

        pet = getattr(player, 'pet', None)
        if not pet or not pet.get('is_alive') or not pet.get('is_locked'):
            return notifications

        # Update last trivia date
        player.last_trivia_date = datetime.now(timezone.utc)

        # Add XP: 1 for participation, +3 bonus for correct
        xp_gain = 1
        if is_correct:
            xp_gain += 3
            # Update streak
            player.trivia_streak = getattr(player, 'trivia_streak', 0) + 1

            # Check for title reward
            new_title = self.pet_service.check_streak_reward(
                player.trivia_streak,
                getattr(player, 'pet_titles', [])
            )
            if new_title:
                if not hasattr(player, 'pet_titles') or player.pet_titles is None:
                    player.pet_titles = []
                player.pet_titles.append(new_title)
                notifications.append(('title', new_title))
        else:
            # Reset streak on wrong answer
            player.trivia_streak = 0

        # Add XP and check for level up / evolution
        old_level = pet['level']
        old_stage = pet['stage']

        pet, leveled_up, evolved = self.pet_service.add_xp(pet, xp_gain)
        player.pet = pet

        if leveled_up and not evolved:
            notifications.append(('level', pet['level']))

        if evolved:
            notifications.append(('evolution', pet['stage']))

        return notifications
```

**Step 3: Modify handle_answer_callback to call pet update**

In `handle_answer_callback`, after the player score update block (around line 268), add:

```python
            # Update pet system
            if player:
                pet_notifications = self._update_pet_on_trivia(player, is_correct, call.message.chat.id)
                self.player_service.save_player(player)

                # Send pet notifications
                self._send_pet_notifications(call.from_user, pet_notifications, player)
```

**Step 4: Add notification sending method**

```python
    def _send_pet_notifications(self, user, notifications: list, player):
        """Send pet-related notifications after trivia."""
        if not notifications:
            return

        username = user.username
        player_name = player.player_name or user.first_name
        pet_name = player.pet.get('name', 'Улюбленець') if player.pet else 'Улюбленець'

        # Build mention
        if username:
            mention = f"@{username}"
        else:
            mention = f'<a href="tg://user?id={user.id}">{escape_html(player_name)}</a>'

        for notif_type, value in notifications:
            if notif_type == 'title':
                msg = f"{mention}, 🏷 Ти отримав титул \"{value}\"! Серія правильних відповідей!"
            elif notif_type == 'level':
                msg = f"{mention}, 🎉 {pet_name} досяг рівня {value}!"
            elif notif_type == 'evolution':
                stage_name = self.pet_service.get_stage_name(value)
                msg = f"{mention}, ✨ {pet_name} еволюціонував у {stage_name}! Натисни /pet щоб налаштувати."
            else:
                continue

            try:
                # Send to the same chat where trivia was answered
                # Note: we need chat_id from the original message
                pass  # Will be sent from the caller
            except Exception as e:
                logger.error(f"Error sending pet notification: {e}")
```

**Step 5: Update the notification sending in handle_answer_callback**

Replace the notification section with direct sends:

```python
            # Update pet system
            if player:
                pet_notifications = self._update_pet_on_trivia(player, is_correct, call.message.chat.id)
                self.player_service.save_player(player)

                # Send pet notifications
                username = call.from_user.username
                player_name = player.player_name or call.from_user.first_name
                pet_name = player.pet.get('name', 'Улюбленець') if player.pet else 'Улюбленець'

                if username:
                    mention = f"@{username}"
                else:
                    mention = f'<a href="tg://user?id={call.from_user.id}">{escape_html(player_name)}</a>'

                for notif_type, value in pet_notifications:
                    try:
                        if notif_type == 'title':
                            msg = f"{mention}, 🏷 Ти отримав титул \"{value}\"! Серія правильних відповідей!"
                        elif notif_type == 'level':
                            msg = f"{mention}, 🎉 {pet_name} досяг рівня {value}!"
                        elif notif_type == 'evolution':
                            stage_name = self.pet_service.get_stage_name(value)
                            msg = f"{mention}, ✨ {pet_name} еволюціонував у {stage_name}! Натисни /pet щоб налаштувати."
                        else:
                            continue
                        self.bot.send_message(call.message.chat.id, msg, parse_mode='HTML')
                    except Exception as e:
                        logger.error(f"Error sending pet notification: {e}")
```

**Step 6: Commit**

```bash
git add src/handlers/trivia_handlers.py
git commit -m "feat(pet): integrate pet XP and titles with trivia system"
```

---

## Task 7: Add Daily Pet Death Check to Scheduler

**Files:**
- Modify: `src/services/quiz_scheduler.py:1-35, 36-43`

**Step 1: Add player_service parameter and pet checking**

Update `__init__` to accept player_service:

```python
    def __init__(self, bot, db_manager, trivia_service: TriviaService, player_service=None):
        self.bot = bot
        self.db_manager = db_manager
        self.trivia_service = trivia_service
        self.player_service = player_service
```

**Step 2: Add pet death check to schedule setup**

In `setup_schedule`, add midnight check:

```python
    def setup_schedule(self):
        """Настройка расписания для отправки квизов."""
        logger.info("Setting up quiz schedule...")

        for quiz_time in self.quiz_times:
            schedule.every().day.at(quiz_time).do(self.send_scheduled_quiz)
            logger.info(f"Quiz scheduled at {quiz_time}")

        # Add daily pet death check at midnight
        schedule.every().day.at("00:00").do(self.check_pet_deaths)
        logger.info("Pet death check scheduled at 00:00")
```

**Step 3: Add pet death check method**

```python
    def check_pet_deaths(self):
        """Check for pets that should die due to inactivity."""
        if not self.player_service:
            logger.warning("Player service not available for pet death check")
            return

        try:
            logger.info("Running daily pet death check...")
            now = datetime.now(timezone.utc)
            today = now.date()

            # Get all players
            players = self.player_service.get_all_players()
            deaths = []

            for player_id, player in players.items():
                pet = getattr(player, 'pet', None)
                if not pet or not pet.get('is_alive') or not pet.get('is_locked'):
                    continue

                # Check last trivia date
                last_trivia = getattr(player, 'last_trivia_date', None)
                if last_trivia is None:
                    # Pet was never fed, check creation date
                    created_str = pet.get('created_at')
                    if created_str:
                        try:
                            created = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
                            if created.date() < today:
                                # Pet created before today and never fed
                                deaths.append((player_id, player, pet.get('name', 'Улюбленець')))
                        except:
                            pass
                    continue

                # Check if last trivia was before today
                if last_trivia.date() < today:
                    deaths.append((player_id, player, pet.get('name', 'Улюбленець')))

            # Process deaths
            for player_id, player, pet_name in deaths:
                try:
                    player.pet['is_alive'] = False
                    self.player_service.save_player(player)

                    # Send death notification
                    username = None
                    try:
                        chat = self.bot.get_chat(player_id)
                        username = chat.username
                    except:
                        pass

                    if username:
                        mention = f"@{username}"
                    else:
                        mention = f'<a href="tg://user?id={player_id}">{player.player_name}</a>'

                    msg = f"{mention}, 💀 {pet_name} помер... Ти пропустив день. /pet щоб відродити."

                    # Send to main chat
                    self.bot.send_message(self.target_chat_id, msg, parse_mode='HTML')

                    logger.info(f"Pet died for player {player_id}")

                except Exception as e:
                    logger.error(f"Error processing pet death for {player_id}: {e}")

            logger.info(f"Pet death check complete. {len(deaths)} pets died.")

        except Exception as e:
            logger.error(f"Error in pet death check: {e}")
```

**Step 4: Commit**

```bash
git add src/services/quiz_scheduler.py
git commit -m "feat(pet): add daily pet death check to scheduler"
```

---

## Task 8: Register Pet Handlers in Main

**Files:**
- Modify: `src/main.py:21-29, 52-68`

**Step 1: Add import for PetHandlers**

After line 27, add:

```python
from handlers.pet_handlers import PetHandlers
```

**Step 2: Initialize PetHandlers in __init__**

After miniapp_handlers initialization (around line 62), add:

```python
        # Initialize pet handlers
        self.pet_handlers = PetHandlers(self.bot, self.player_service, self.game_service)
```

**Step 3: Update QuizScheduler initialization**

Update the quiz_scheduler line to pass player_service:

```python
        self.quiz_scheduler = QuizScheduler(self.bot, self.db_manager, self.trivia_handlers.trivia_service, self.player_service)
```

**Step 4: Setup pet handlers in setup_handlers**

After miniapp handlers setup (around line 134), add:

```python
        # Setup pet handlers
        self.pet_handlers.setup_handlers()
```

**Step 5: Commit**

```bash
git add src/main.py
git commit -m "feat(pet): register pet handlers in main bot"
```

---

## Task 9: Run Database Migration

**Step 1: Connect to database and run migration**

```bash
cd /Users/mso/PycharmProjects/tg-bot
psql -h localhost -U your_user -d your_database -f src/database/migrations/add_pet_fields.sql
```

Or run via Python:

```python
# Run this in Python shell or create a migration script
import psycopg2
from config.settings import Settings

conn = psycopg2.connect(Settings.DATABASE_URL)
cur = conn.cursor()
cur.execute(open('src/database/migrations/add_pet_fields.sql').read())
conn.commit()
cur.close()
conn.close()
```

**Step 2: Verify migration**

```bash
psql -h localhost -U your_user -d your_database -c "\d pisunchik_data"
```

---

## Task 10: Test the Pet System

**Step 1: Start the bot**

```bash
cd /Users/mso/PycharmProjects/tg-bot
python src/main.py
```

**Step 2: Test commands**

1. `/pet` - should show "create pet" button
2. Click create - should create pet
3. Change name and image
4. Click confirm - should lock pet
5. Answer trivia - should gain XP
6. Get 3 correct in a row - should earn title
7. `/pet` again - should show titles button
8. Kill pet - should show dead state
9. Revive pet - should work

**Step 3: Final commit**

```bash
git add -A
git commit -m "feat(pet): complete pet system implementation"
```

---

## Summary

**Files Created:**
- `assets/data/pet_titles.json` - Configuration
- `src/services/pet_service.py` - Business logic
- `src/handlers/pet_handlers.py` - Command handlers
- `src/database/migrations/add_pet_fields.sql` - Database migration

**Files Modified:**
- `src/models/player.py` - Added pet fields
- `src/database/player_service.py` - Updated save/load for pet fields
- `src/handlers/trivia_handlers.py` - Integrated XP/titles
- `src/services/quiz_scheduler.py` - Added death check
- `src/main.py` - Registered handlers
