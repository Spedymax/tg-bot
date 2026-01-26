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
