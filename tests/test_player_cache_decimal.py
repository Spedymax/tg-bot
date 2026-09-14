"""NUMERIC columns arrive as Decimal; the Redis player cache must survive them.

Before the fix `_serialize_player` raised "Object of type Decimal is not JSON
serializable" for every player who had ever spun the mini-app wheel, so nothing
was ever cached and every read went to Postgres.
"""
import sys, os, json, types
from datetime import datetime, timezone
from decimal import Decimal

_src = os.path.join(os.path.dirname(__file__), '..', 'src')
sys.path.insert(0, _src)
for _mod_name in ('psycopg', 'psycopg_pool', 'psycopg.rows'):
    sys.modules.setdefault(_mod_name, types.ModuleType(_mod_name))
# db_manager only needs the names to exist at import time
sys.modules['psycopg_pool'].AsyncConnectionPool = object
sys.modules['psycopg'].AsyncConnection = object

from models.player import Player
from database.player_service import PlayerService


def _row(**overrides):
    data = {
        'player_id': 1, 'player_name': 'Макс',
        'pisunchik_size': 10, 'coins': 100,
        'miniapp_total_winnings': Decimal('123.45'),
        'miniapp_daily_spins': 2,
    }
    data.update(overrides)
    return tuple(data.values()), list(data.keys())


class TestFromDbRow:
    def test_decimal_becomes_float(self):
        row, cols = _row()
        player = Player.from_db_row(row, cols)
        assert isinstance(player.miniapp_total_winnings, float)
        assert player.miniapp_total_winnings == 123.45

    def test_other_fields_untouched(self):
        row, cols = _row()
        player = Player.from_db_row(row, cols)
        assert player.player_name == 'Макс' and player.pisunchik_size == 10


class TestSerializePlayer:
    def test_player_with_decimal_serializes(self):
        """Defensive: a Decimal set by hand (not via from_db_row) must not blow up."""
        player = Player(player_id=1, player_name='Макс')
        player.miniapp_total_winnings = Decimal('50.5')
        data = json.loads(PlayerService._serialize_player(player))
        assert data['miniapp_total_winnings'] == 50.5

    def test_decimal_nested_in_json_field(self):
        player = Player(player_id=1, player_name='Макс')
        player.pet = {'name': 'Шарик', 'level': Decimal('3')}
        data = json.loads(PlayerService._serialize_player(player))
        assert data['pet']['level'] == 3.0

    def test_round_trip_through_cache(self):
        row, cols = _row()
        player = Player.from_db_row(row, cols)
        player.last_used = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
        restored = PlayerService._deserialize_player(PlayerService._serialize_player(player))
        assert restored.miniapp_total_winnings == 123.45
        assert restored.last_used == player.last_used
        assert restored.player_name == player.player_name
