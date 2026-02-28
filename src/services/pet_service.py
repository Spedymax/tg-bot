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

    def get_stage_from_xp(self, xp: int) -> str:
        """Get evolution stage directly from XP (source of truth for evolution)."""
        if xp < self.xp_thresholds.get('egg_to_baby', 50):
            return 'egg'
        elif xp < self.xp_thresholds.get('baby_to_adult', 150):
            return 'baby'
        elif xp < self.xp_thresholds.get('adult_to_legendary', 350):
            return 'adult'
        return 'legendary'

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
        pet['stage'] = self.get_stage_from_xp(pet['xp'])

        leveled_up = pet['level'] > old_level
        evolved = pet['stage'] != old_stage

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
        """Get Russian name for evolution stage."""
        return {
            "egg": "Яйцо",
            "baby": "Малыш",
            "adult": "Взрослый",
            "legendary": "Легендарный"
        }.get(stage, stage)

    def format_pet_display(self, pet: Dict[str, Any], active_title: Optional[str],
                           revives_used: int, streak: int, player=None) -> str:
        """Format pet info for display."""
        if not pet:
            return "У тебя ещё нет питомца!"

        stage_emoji = self.get_stage_emoji(pet['stage'])
        stage_name = self.get_stage_name(pet['stage'])

        name_display = pet['name']
        if active_title:
            name_display = f"{pet['name']} — {active_title}"

        status = "Живой ✅" if pet['is_alive'] else "Мёртвый 💀"

        # Calculate XP for next level/evolution
        next_evo_xp = self.get_xp_for_next_evolution(pet['stage'])
        xp_display = f"{pet['xp']}"
        if next_evo_xp:
            xp_display = f"{pet['xp']}/{next_evo_xp}"

        text = f"{stage_emoji} {name_display}\n"
        text += f"Уровень: {pet['level']} ({stage_name})\n"
        text += f"XP: {xp_display}\n"
        text += f"Статус: {status}\n"

        if pet['is_alive'] and streak > 0:
            text += f"Серия правильных: {streak} 🔥\n"

        if not pet['is_alive']:
            remaining = self.max_revives - revives_used
            text += f"Возрождений: {remaining}/{self.max_revives} осталось\n"

        if not pet.get('is_locked'):
            text += "\n⚙️ Статус: Настройка..."

        # Show hunger/happiness bars if pet is alive and active
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

        return text

    # ─── Hunger / Happiness ───────────────────────────────────────

    def get_xp_multiplier(self, player) -> float:
        """Return XP multiplier based on hunger and happiness."""
        if not player.pet or not player.pet.get('is_alive'):
            return 0.0
        hunger = getattr(player, 'pet_hunger', 100)
        if hunger < 30:
            return 0.0
        multiplier = 0.5 if hunger < 60 else 1.0
        happiness = getattr(player, 'pet_happiness', 50)
        if happiness >= 80:
            multiplier *= 1.2
        return multiplier

    def apply_hunger_decay(self, player, now: datetime) -> bool:
        """Apply accumulated hunger decay ticks (every 12h = -10).
        Returns True if pet just died."""
        from datetime import timedelta
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
        from datetime import timedelta
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
        if hunger < 10:
            return False
        used = getattr(player, 'pet_ulta_used_date', None)
        if used is None:
            return True
        cooldown_h = 48 if happiness < 20 else 24
        return (datetime.now(timezone.utc) - used).total_seconds() >= cooldown_h * 3600

    def mark_ulta_used(self, player):
        """Record that ulta was used now."""
        player.pet_ulta_used_date = datetime.now(timezone.utc)

    def get_ulta_name(self, stage: str) -> str:
        """Get display name for ulta at given stage."""
        return self.ULTA_NAMES.get(stage, '⚡ Ульта')

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

        parts = []
        if hunger < 10:
            parts.append('[Умирает! 💀]')
        elif hunger < 30:
            parts.append('[Очень голоден 😫]')
        elif hunger < 60:
            parts.append('[Голоден 😟]')
        elif happiness >= 80:
            parts.append('[Счастлив 😊]')

        if happiness < 20 and parts:
            parts.append('[Подавлен]')
        elif happiness < 20:
            parts.append('[Подавлен]')

        badge = f' {stage_emoji}'
        if parts:
            badge += ' ' + ' '.join(parts)
        return badge
