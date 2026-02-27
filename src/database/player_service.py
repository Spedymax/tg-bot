import json
import logging
from typing import Dict, Optional, List
from datetime import datetime, timezone
from models.player import Player
from database.db_manager import DatabaseManager

logger = logging.getLogger(__name__)

# Whitelist of allowed field names to prevent SQL injection
ALLOWED_PLAYER_FIELDS = {
    'player_name', 'pisunchik_size', 'coins', 'items', 'characteristics',
    'player_stocks', 'statuetki', 'chat_id', 'correct_answers', 'nnn_checkins',
    'last_used', 'last_vor', 'last_prezervativ', 'last_joke', 'casino_last_used',
    'casino_usage_count', 'ballzzz_number', 'notified',
    'pet', 'pet_titles', 'pet_active_title', 'pet_revives_used',
    'pet_revives_reset_date', 'trivia_streak', 'last_trivia_date',
    # Pet hunger/happiness/ulta fields
    'pet_hunger', 'pet_happiness', 'pet_hunger_last_decay', 'pet_happiness_last_activity',
    'pet_ulta_used_date', 'pet_ulta_free_roll_pending', 'pet_ulta_oracle_pending',
    'pet_ulta_trivia_pending', 'pet_casino_extra_spins', 'pet_ulta_oracle_preview',
}

class PlayerService:
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        self._cache: Dict[int, dict] = {}  # {player_id: {"player": Player, "cached_at": datetime}}
        self._cache_expiry_seconds = 300  # 5 minutes cache expiry

    def _is_cache_valid(self, player_id: int) -> bool:
        """Check if cache entry is still valid."""
        if player_id not in self._cache:
            return False
        cached_at = self._cache[player_id].get("cached_at")
        if not cached_at:
            return False
        age = (datetime.now(timezone.utc) - cached_at).total_seconds()
        return age < self._cache_expiry_seconds

    def _cache_player(self, player: Player):
        """Cache a player with timestamp."""
        self._cache[player.player_id] = {
            "player": player,
            "cached_at": datetime.now(timezone.utc)
        }

    def _get_cached_player(self, player_id: int) -> Optional[Player]:
        """Get player from cache if valid."""
        if self._is_cache_valid(player_id):
            return self._cache[player_id]["player"]
        return None

    def get_player(self, player_id: int) -> Optional[Player]:
        """Get a player by ID, first checking cache, then database"""
        # Check cache first
        cached_player = self._get_cached_player(player_id)
        if cached_player:
            return cached_player

        connection = self.db.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM pisunchik_data WHERE player_id = %s", (player_id,))
                row = cursor.fetchone()

                if row:
                    # Get column names
                    column_names = [desc[0] for desc in cursor.description]
                    player = Player.from_db_row(row, column_names)
                    self._cache_player(player)
                    return player
                return None
        except Exception as e:
            logger.error(f"Error getting player {player_id}: {e}")
            return None
        finally:
            self.db.release_connection(connection)

    def save_player(self, player: Player) -> bool:
        """Save a player to the database and update cache"""
        connection = self.db.get_connection()
        try:
            with connection.cursor() as cursor:
                # Check if player exists
                cursor.execute("SELECT player_id FROM pisunchik_data WHERE player_id = %s", (player.player_id,))
                exists = cursor.fetchone() is not None
                
                if exists:
                    # Update existing player
                    update_query = """
                        UPDATE pisunchik_data SET
                            player_name = %s, pisunchik_size = %s, coins = %s,
                            items = %s, characteristics = %s, player_stocks = %s,
                            statuetki = %s, chat_id = %s, correct_answers = %s,
                            nnn_checkins = %s, last_used = %s, last_vor = %s,
                            last_prezervativ = %s, last_joke = %s, casino_last_used = %s,
                            casino_usage_count = %s, ballzzz_number = %s, notified = %s,
                            miniapp_daily_spins = %s, miniapp_last_spin_date = %s, miniapp_total_winnings = %s,
                            pet = %s, pet_titles = %s, pet_active_title = %s, pet_revives_used = %s,
                            pet_revives_reset_date = %s, trivia_streak = %s, last_trivia_date = %s,
                            pet_hunger = %s, pet_happiness = %s,
                            pet_hunger_last_decay = %s, pet_happiness_last_activity = %s,
                            pet_ulta_used_date = %s, pet_ulta_free_roll_pending = %s,
                            pet_ulta_oracle_pending = %s, pet_ulta_trivia_pending = %s,
                            pet_casino_extra_spins = %s, pet_ulta_oracle_preview = %s
                        WHERE player_id = %s
                    """
                    cursor.execute(update_query, (
                        player.player_name, player.pisunchik_size, player.coins,
                        player.items, player.characteristics, player.player_stocks,
                        player.statuetki, player.chat_id, player.correct_answers,
                        player.nnn_checkins, player.last_used, player.last_vor,
                        player.last_prezervativ, player.last_joke, player.casino_last_used,
                        player.casino_usage_count, player.ballzzz_number, player.notified,
                        getattr(player, 'miniapp_daily_spins', 0),
                        getattr(player, 'miniapp_last_spin_date', datetime.min.replace(tzinfo=timezone.utc)),
                        getattr(player, 'miniapp_total_winnings', 0.0),
                        json.dumps(getattr(player, 'pet', None)) if getattr(player, 'pet', None) else None,
                        json.dumps(getattr(player, 'pet_titles', [])),
                        getattr(player, 'pet_active_title', None),
                        getattr(player, 'pet_revives_used', 0),
                        getattr(player, 'pet_revives_reset_date', None),
                        getattr(player, 'trivia_streak', 0),
                        getattr(player, 'last_trivia_date', None),
                        getattr(player, 'pet_hunger', 100),
                        getattr(player, 'pet_happiness', 50),
                        getattr(player, 'pet_hunger_last_decay', None),
                        getattr(player, 'pet_happiness_last_activity', None),
                        getattr(player, 'pet_ulta_used_date', None),
                        getattr(player, 'pet_ulta_free_roll_pending', False),
                        getattr(player, 'pet_ulta_oracle_pending', False),
                        getattr(player, 'pet_ulta_trivia_pending', False),
                        getattr(player, 'pet_casino_extra_spins', 0),
                        json.dumps(getattr(player, 'pet_ulta_oracle_preview', None)) if getattr(player, 'pet_ulta_oracle_preview', None) else None,
                        player.player_id
                    ))
                else:
                    # Insert new player
                    insert_query = """
                        INSERT INTO pisunchik_data (
                            player_id, player_name, pisunchik_size, coins,
                            items, characteristics, player_stocks, statuetki,
                            chat_id, correct_answers, nnn_checkins, last_used,
                            last_vor, last_prezervativ, last_joke, casino_last_used,
                            casino_usage_count, ballzzz_number, notified,
                            pet, pet_titles, pet_active_title, pet_revives_used,
                            pet_revives_reset_date, trivia_streak, last_trivia_date,
                            pet_hunger, pet_happiness, pet_hunger_last_decay,
                            pet_happiness_last_activity, pet_ulta_used_date,
                            pet_ulta_free_roll_pending, pet_ulta_oracle_pending,
                            pet_ulta_trivia_pending, pet_casino_extra_spins, pet_ulta_oracle_preview
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """
                    cursor.execute(insert_query, (
                        player.player_id, player.player_name, player.pisunchik_size, player.coins,
                        player.items, player.characteristics, player.player_stocks,
                        player.statuetki, player.chat_id, player.correct_answers,
                        player.nnn_checkins, player.last_used, player.last_vor,
                        player.last_prezervativ, player.last_joke, player.casino_last_used,
                        player.casino_usage_count, player.ballzzz_number, player.notified,
                        json.dumps(getattr(player, 'pet', None)) if getattr(player, 'pet', None) else None,
                        json.dumps(getattr(player, 'pet_titles', [])),
                        getattr(player, 'pet_active_title', None),
                        getattr(player, 'pet_revives_used', 0),
                        getattr(player, 'pet_revives_reset_date', None),
                        getattr(player, 'trivia_streak', 0),
                        getattr(player, 'last_trivia_date', None),
                        getattr(player, 'pet_hunger', 100),
                        getattr(player, 'pet_happiness', 50),
                        getattr(player, 'pet_hunger_last_decay', None),
                        getattr(player, 'pet_happiness_last_activity', None),
                        getattr(player, 'pet_ulta_used_date', None),
                        getattr(player, 'pet_ulta_free_roll_pending', False),
                        getattr(player, 'pet_ulta_oracle_pending', False),
                        getattr(player, 'pet_ulta_trivia_pending', False),
                        getattr(player, 'pet_casino_extra_spins', 0),
                        json.dumps(getattr(player, 'pet_ulta_oracle_preview', None)) if getattr(player, 'pet_ulta_oracle_preview', None) else None,
                    ))
                
                connection.commit()
                self._cache_player(player)
                return True
                
        except Exception as e:
            logger.error(f"Error saving player {player.player_id}: {e}")
            connection.rollback()
            return False
        finally:
            self.db.release_connection(connection)

    def create_player(self, player_id: int, player_name: str) -> Player:
        """Create a new player with default values"""
        player = Player(
            player_id=player_id,
            player_name=player_name,
            pisunchik_size=0,
            coins=0.0,
            last_used=datetime.min.replace(tzinfo=timezone.utc),
            last_vor=datetime.min.replace(tzinfo=timezone.utc),
            last_prezervativ=datetime.min.replace(tzinfo=timezone.utc),
            last_joke=datetime.min.replace(tzinfo=timezone.utc),
            casino_last_used=datetime.min.replace(tzinfo=timezone.utc),
            casino_usage_count=0,
            ballzzz_number=None,
            notified=False
        )
        
        if self.save_player(player):
            return player
        else:
            raise Exception(f"Failed to create player {player_id}")

    def player_exists(self, player_id: int) -> bool:
        """Check if a player exists in the database"""
        connection = self.db.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM pisunchik_data WHERE player_id = %s", (player_id,))
                return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Error checking if player exists {player_id}: {e}")
            return False
        finally:
            self.db.release_connection(connection)

    def get_all_players(self) -> Dict[int, Player]:
        """Get all players from the database (use carefully, can be memory intensive)"""
        connection = self.db.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM pisunchik_data")
                rows = cursor.fetchall()
                column_names = [desc[0] for desc in cursor.description]
                
                players = {}
                for row in rows:
                    player = Player.from_db_row(row, column_names)
                    players[player.player_id] = player
                    self._cache_player(player)

                return players
        except Exception as e:
            logger.error(f"Error getting all players: {e}")
            return {}
        finally:
            self.db.release_connection(connection)

    def update_player_field(self, player_id: int, field_name: str, value) -> bool:
        """Update a specific field for a player"""
        # Validate field_name against whitelist to prevent SQL injection
        if field_name not in ALLOWED_PLAYER_FIELDS:
            logger.error(f"Invalid field name: {field_name}")
            return False

        connection = self.db.get_connection()
        try:
            with connection.cursor() as cursor:
                # Safe because field_name is validated against whitelist
                query = f"UPDATE pisunchik_data SET {field_name} = %s WHERE player_id = %s"
                cursor.execute(query, (value, player_id))
                connection.commit()

                # Invalidate cache to force reload on next access
                self.remove_from_cache(player_id)

                return True
        except Exception as e:
            logger.error(f"Error updating player field {field_name} for player {player_id}: {e}")
            connection.rollback()
            return False
        finally:
            self.db.release_connection(connection)

    def get_leaderboard(self, limit: int = 10) -> List[Player]:
        """Get top players by pisunchik size"""
        connection = self.db.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM pisunchik_data 
                    ORDER BY pisunchik_size DESC 
                    LIMIT %s
                """, (limit,))
                rows = cursor.fetchall()
                column_names = [desc[0] for desc in cursor.description]
                
                return [Player.from_db_row(row, column_names) for row in rows]
        except Exception as e:
            logger.error(f"Error getting leaderboard: {e}")
            return []
        finally:
            self.db.release_connection(connection)

    def clear_cache(self):
        """Clear the player cache"""
        self._cache.clear()

    def remove_from_cache(self, player_id: int):
        """Remove a specific player from cache"""
        if player_id in self._cache:
            del self._cache[player_id]
