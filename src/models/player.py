from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import json

@dataclass
class Player:
    player_id: int
    player_name: str
    pisunchik_size: int = 0
    coins: float = 0.0
    items: List[str] = field(default_factory=list)
    characteristics: List[str] = field(default_factory=list)
    player_stocks: List[str] = field(default_factory=list)
    statuetki: List[str] = field(default_factory=list)
    chat_id: List[int] = field(default_factory=list)
    correct_answers: List[str] = field(default_factory=list)
    nnn_checkins: List[str] = field(default_factory=list)
    
    # Timestamp fields
    last_used: datetime = field(default_factory=lambda: datetime.min.replace(tzinfo=timezone.utc))
    last_vor: datetime = field(default_factory=lambda: datetime.min.replace(tzinfo=timezone.utc))
    last_prezervativ: datetime = field(default_factory=lambda: datetime.min.replace(tzinfo=timezone.utc))
    last_joke: Optional[datetime] = field(default_factory=lambda: datetime.min.replace(tzinfo=timezone.utc))
    casino_last_used: datetime = field(default_factory=lambda: datetime.min.replace(tzinfo=timezone.utc))
    
    # Game state fields
    casino_usage_count: int = 0
    ballzzz_number: Optional[int] = None
    notified: bool = False
    
    # Mini-app casino fields
    miniapp_daily_spins: int = 0
    miniapp_last_spin_date: Optional[datetime] = field(default_factory=lambda: datetime.min.replace(tzinfo=timezone.utc))
    miniapp_total_winnings: float = 0.0

    # Pet system fields
    pet: Optional[Dict[str, Any]] = field(default_factory=lambda: None)
    pet_titles: List[str] = field(default_factory=list)
    pet_active_title: Optional[str] = None
    pet_revives_used: int = 0
    pet_revives_reset_date: Optional[datetime] = None
    trivia_streak: int = 0
    last_trivia_date: Optional[datetime] = None

    @classmethod
    def from_db_row(cls, row: tuple, column_names: List[str]) -> 'Player':
        """Create a Player instance from a database row"""
        data = dict(zip(column_names, row))
        
        # Handle JSON fields
        for field_name in ['items', 'characteristics', 'player_stocks', 'statuetki',
                          'chat_id', 'correct_answers', 'nnn_checkins', 'pet', 'pet_titles']:
            if field_name in data and data[field_name]:
                if isinstance(data[field_name], str):
                    try:
                        data[field_name] = json.loads(data[field_name])
                    except (json.JSONDecodeError, TypeError):
                        # pet should be None on parse failure, lists should be empty
                        data[field_name] = None if field_name == 'pet' else []
                elif data[field_name] is None:
                    data[field_name] = []
        
        # Handle datetime fields
        for field_name in ['last_used', 'last_vor', 'last_prezervativ', 'last_joke', 'casino_last_used']:
            if field_name in data and data[field_name] is None:
                data[field_name] = datetime.min.replace(tzinfo=timezone.utc)
        
        return cls(**data)

    def to_db_dict(self) -> Dict[str, Any]:
        """Convert Player instance to a dictionary for database storage"""
        data = self.__dict__.copy()
        
        # Convert lists/dicts to JSON strings for database storage
        for field_name in ['items', 'characteristics', 'player_stocks', 'statuetki',
                          'chat_id', 'correct_answers', 'nnn_checkins', 'pet', 'pet_titles']:
            if isinstance(data[field_name], (list, dict)):
                data[field_name] = json.dumps(data[field_name])
        
        return data

    def has_item(self, item_name: str) -> bool:
        """Check if player has a specific item"""
        return item_name in self.items

    def add_item(self, item_name: str):
        """Add an item to player's inventory"""
        if item_name not in self.items:
            self.items.append(item_name)

    def remove_item(self, item_name: str) -> bool:
        """Remove an item from player's inventory. Returns True if removed, False if not found"""
        try:
            self.items.remove(item_name)
            return True
        except ValueError:
            return False

    def has_characteristic(self, characteristic_name: str) -> bool:
        """Check if player has a specific characteristic"""
        return any(char.startswith(f"{characteristic_name}:") for char in self.characteristics)

    def get_characteristic_level(self, characteristic_name: str) -> int:
        """Get the level of a specific characteristic"""
        for char in self.characteristics:
            if char.startswith(f"{characteristic_name}:"):
                parts = char.split(":")
                if len(parts) >= 2:
                    try:
                        return int(parts[1])
                    except ValueError:
                        return 0
        return 0

    def update_characteristic_level(self, characteristic_name: str, level: int):
        """Update or add a characteristic with a specific level"""
        # Remove existing characteristic if it exists
        self.characteristics = [char for char in self.characteristics 
                             if not char.startswith(f"{characteristic_name}:")]
        # Add new characteristic with level
        self.characteristics.append(f"{characteristic_name}:{level}")

    def add_coins(self, amount: float):
        """Add coins to player's balance"""
        self.coins += amount

    def spend_coins(self, amount: float) -> bool:
        """Spend coins if player has enough. Returns True if successful, False if insufficient funds"""
        if self.coins >= amount:
            self.coins -= amount
            return True
        return False

    def get_quiz_score(self, chat_id: int) -> int:
        """Get quiz score for a specific chat"""
        for entry in self.correct_answers:
            if entry.startswith(f"{chat_id}:"):
                parts = entry.split(":")
                if len(parts) >= 2:
                    try:
                        return int(parts[1])
                    except ValueError:
                        return 0
        return 0

    def update_quiz_score(self, chat_id: int, score: int):
        """Update quiz score for a specific chat"""
        # Remove existing score for this chat
        self.correct_answers = [entry for entry in self.correct_answers 
                              if not entry.startswith(f"{chat_id}:")]
        # Add new score
        self.correct_answers.append(f"{chat_id}:{score}")

    def add_chat_id(self, chat_id: int):
        """Add a chat ID to player's chat list if not already present"""
        if chat_id not in self.chat_id:
            self.chat_id.append(chat_id)
