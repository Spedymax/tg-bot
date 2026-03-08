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
    'pet_death_pending_notify',
}

# All datetime fields on the Player model (for serialization)
_DATETIME_FIELDS = {
    'last_used', 'last_vor', 'last_prezervativ', 'last_joke',
    'casino_last_used', 'miniapp_last_spin_date',
    'pet_revives_reset_date', 'last_trivia_date',
    'pet_hunger_last_decay', 'pet_happiness_last_activity',
    'pet_ulta_used_date',
}

# Fields stored as JSON (lists/dicts) in the database
_JSON_FIELDS = {
    'items', 'characteristics', 'player_stocks', 'statuetki',
    'chat_id', 'correct_answers', 'nnn_checkins',
    'pet', 'pet_titles', 'pet_ulta_oracle_preview',
}

_REDIS_KEY_PREFIX = "player:"


class PlayerService:
    def __init__(self, db_manager: DatabaseManager, redis=None):
        self.db = db_manager
        self._redis = redis
        self._cache_expiry_seconds = 300  # 5 minutes

    # ── Redis serialization helpers ────────────────────────────────────────

    @staticmethod
    def _serialize_player(player: Player) -> str:
        """Serialize a Player to a JSON string for Redis storage."""
        data = {}
        for attr_name in player.__dataclass_fields__:
            val = getattr(player, attr_name)
            if isinstance(val, datetime):
                data[attr_name] = val.isoformat()
            else:
                # lists, dicts, ints, floats, bools, None — all JSON-native
                data[attr_name] = val
        return json.dumps(data, ensure_ascii=False)

    @staticmethod
    def _deserialize_player(raw: str) -> Player:
        """Deserialize a JSON string from Redis back into a Player."""
        data: dict = json.loads(raw)
        for field_name in _DATETIME_FIELDS:
            val = data.get(field_name)
            if val is not None and isinstance(val, str):
                try:
                    data[field_name] = datetime.fromisoformat(val)
                except (ValueError, TypeError):
                    data[field_name] = None
        return Player(**data)

    # ── Cache operations (async, Redis-backed) ─────────────────────────────

    async def _cache_player(self, player: Player):
        """Cache a player in Redis with TTL."""
        if self._redis is None:
            return
        try:
            key = f"{_REDIS_KEY_PREFIX}{player.player_id}"
            await self._redis.set(key, self._serialize_player(player), ex=self._cache_expiry_seconds)
        except Exception as e:
            logger.warning(f"Redis cache SET failed for player {player.player_id}: {e}")

    async def _get_cached_player(self, player_id: int) -> Optional[Player]:
        """Get player from Redis cache (returns None on miss or error)."""
        if self._redis is None:
            return None
        try:
            key = f"{_REDIS_KEY_PREFIX}{player_id}"
            raw = await self._redis.get(key)
            if raw is None:
                return None
            return self._deserialize_player(raw)
        except Exception as e:
            logger.warning(f"Redis cache GET failed for player {player_id}: {e}")
            return None

    async def remove_from_cache(self, player_id: int):
        """Remove a specific player from Redis cache."""
        if self._redis is None:
            return
        try:
            key = f"{_REDIS_KEY_PREFIX}{player_id}"
            await self._redis.delete(key)
        except Exception as e:
            logger.warning(f"Redis cache DEL failed for player {player_id}: {e}")

    async def clear_cache(self):
        """Delete all player cache keys from Redis."""
        if self._redis is None:
            return
        try:
            cursor = 0
            while True:
                cursor, keys = await self._redis.scan(cursor, match=f"{_REDIS_KEY_PREFIX}*", count=100)
                if keys:
                    await self._redis.delete(*keys)
                if cursor == 0:
                    break
        except Exception as e:
            logger.warning(f"Redis cache CLEAR failed: {e}")

    # ── Data access methods ────────────────────────────────────────────────

    async def get_player(self, player_id: int) -> Optional[Player]:
        """Get a player by ID, first checking cache, then database"""
        cached_player = await self._get_cached_player(player_id)
        if cached_player:
            return cached_player

        try:
            async with self.db.connection() as conn:
                cursor = await conn.execute(
                    "SELECT * FROM pisunchik_data WHERE player_id = %s", (player_id,)
                )
                row = await cursor.fetchone()

                if row:
                    column_names = [desc[0] for desc in cursor.description]
                    player = Player.from_db_row(row, column_names)
                    await self._cache_player(player)
                    return player
                return None
        except Exception as e:
            logger.error(f"Error getting player {player_id}: {e}")
            return None

    async def save_player(self, player: Player) -> bool:
        """Save a player to the database and update cache"""
        try:
            async with self.db.connection() as conn:
                # Use a transaction for atomicity (SELECT + INSERT/UPDATE)
                async with conn.transaction():
                    cursor = await conn.execute(
                        "SELECT player_id FROM pisunchik_data WHERE player_id = %s",
                        (player.player_id,),
                    )
                    exists = await cursor.fetchone() is not None

                    if exists:
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
                                pet_casino_extra_spins = %s, pet_ulta_oracle_preview = %s,
                                pet_death_pending_notify = %s
                            WHERE player_id = %s
                        """
                        await conn.execute(update_query, (
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
                            getattr(player, 'pet_death_pending_notify', False),
                            player.player_id
                        ))
                    else:
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
                                pet_ulta_trivia_pending, pet_casino_extra_spins, pet_ulta_oracle_preview,
                                pet_death_pending_notify
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """
                        await conn.execute(insert_query, (
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
                            getattr(player, 'pet_death_pending_notify', False),
                        ))

                await self._cache_player(player)
                return True

        except Exception as e:
            logger.error(f"Error saving player {player.player_id}: {e}")
            return False

    async def create_player(self, player_id: int, player_name: str) -> Player:
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

        if await self.save_player(player):
            return player
        else:
            raise Exception(f"Failed to create player {player_id}")

    async def player_exists(self, player_id: int) -> bool:
        """Check if a player exists in the database"""
        try:
            async with self.db.connection() as conn:
                cursor = await conn.execute(
                    "SELECT 1 FROM pisunchik_data WHERE player_id = %s", (player_id,)
                )
                return await cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Error checking if player exists {player_id}: {e}")
            return False

    async def get_all_players(self) -> Dict[int, Player]:
        """Get all players from the database (use carefully, can be memory intensive)"""
        try:
            async with self.db.connection() as conn:
                cursor = await conn.execute("SELECT * FROM pisunchik_data")
                rows = await cursor.fetchall()
                column_names = [desc[0] for desc in cursor.description]

                players = {}
                for row in rows:
                    player = Player.from_db_row(row, column_names)
                    players[player.player_id] = player
                    await self._cache_player(player)

                return players
        except Exception as e:
            logger.error(f"Error getting all players: {e}")
            return {}

    async def update_player_field(self, player_id: int, field_name: str, value) -> bool:
        """Update a specific field for a player"""
        # Validate field_name against whitelist to prevent SQL injection
        if field_name not in ALLOWED_PLAYER_FIELDS:
            logger.error(f"Invalid field name: {field_name}")
            return False

        try:
            async with self.db.connection() as conn:
                # Safe because field_name is validated against whitelist
                query = f"UPDATE pisunchik_data SET {field_name} = %s WHERE player_id = %s"
                await conn.execute(query, (value, player_id))

                # Invalidate cache to force reload on next access
                await self.remove_from_cache(player_id)

                return True
        except Exception as e:
            logger.error(f"Error updating player field {field_name} for player {player_id}: {e}")
            return False

    async def get_leaderboard(self, limit: int = 10) -> List[Player]:
        """Get top players by pisunchik size"""
        try:
            async with self.db.connection() as conn:
                cursor = await conn.execute("""
                    SELECT * FROM pisunchik_data
                    ORDER BY pisunchik_size DESC
                    LIMIT %s
                """, (limit,))
                rows = await cursor.fetchall()
                column_names = [desc[0] for desc in cursor.description]

                return [Player.from_db_row(row, column_names) for row in rows]
        except Exception as e:
            logger.error(f"Error getting leaderboard: {e}")
            return []
