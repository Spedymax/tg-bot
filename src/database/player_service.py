import json
from typing import Dict, Optional, List
from datetime import datetime, timezone
from models.player import Player
from database.db_manager import DatabaseManager

class PlayerService:
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        self._cache: Dict[int, Player] = {}
        self._cache_expiry = 300  # 5 minutes cache expiry

    def get_player(self, player_id: int) -> Optional[Player]:
        """Get a player by ID, first checking cache, then database"""
        if player_id in self._cache:
            return self._cache[player_id]
        
        connection = self.db.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM pisunchik_data WHERE player_id = %s", (player_id,))
                row = cursor.fetchone()
                
                if row:
                    # Get column names
                    column_names = [desc[0] for desc in cursor.description]
                    player = Player.from_db_row(row, column_names)
                    self._cache[player_id] = player
                    return player
                return None
        except Exception as e:
            print(f"Error getting player {player_id}: {e}")
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
                            miniapp_daily_spins = %s, miniapp_last_spin_date = %s, miniapp_total_winnings = %s
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
                            casino_usage_count, ballzzz_number, notified
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """
                    cursor.execute(insert_query, (
                        player.player_id, player.player_name, player.pisunchik_size, player.coins,
                        player.items, player.characteristics, player.player_stocks,
                        player.statuetki, player.chat_id, player.correct_answers,
                        player.nnn_checkins, player.last_used, player.last_vor,
                        player.last_prezervativ, player.last_joke, player.casino_last_used,
                        player.casino_usage_count, player.ballzzz_number, player.notified
                    ))
                
                connection.commit()
                self._cache[player.player_id] = player
                return True
                
        except Exception as e:
            print(f"Error saving player {player.player_id}: {e}")
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
            print(f"Error checking if player exists {player_id}: {e}")
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
                    self._cache[player.player_id] = player
                
                return players
        except Exception as e:
            print(f"Error getting all players: {e}")
            return {}
        finally:
            self.db.release_connection(connection)

    def update_player_field(self, player_id: int, field_name: str, value) -> bool:
        """Update a specific field for a player"""
        connection = self.db.get_connection()
        try:
            with connection.cursor() as cursor:
                query = f"UPDATE pisunchik_data SET {field_name} = %s WHERE player_id = %s"
                cursor.execute(query, (value, player_id))
                connection.commit()
                
                # Update cache if player is cached
                if player_id in self._cache:
                    setattr(self._cache[player_id], field_name, value)
                
                return True
        except Exception as e:
            print(f"Error updating player field {field_name} for player {player_id}: {e}")
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
            print(f"Error getting leaderboard: {e}")
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
