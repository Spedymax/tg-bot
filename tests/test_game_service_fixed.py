#!/usr/bin/env python3
"""
Fixed Game Service tests with comprehensive mocking
"""

import sys
import os
import unittest
import pytest
from unittest.mock import Mock, patch, MagicMock, AsyncMock
import types
from datetime import datetime, timezone, timedelta

# Add project paths FIRST
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Create comprehensive mock modules
def create_mock_module(name):
    mock_module = types.ModuleType(name)
    mock_module.__dict__.update({
        '__all__': [],
        '__file__': f'/mock/{name}.py',
        '__package__': name.split('.')[0] if '.' in name else None
    })

    # Add all possible attributes
    for attr_name in ['connect', 'pool', 'ThreadedConnectionPool', 'RealDictCursor',
                      'extensions', 'connection', 'load_dotenv', 'configure',
                      'GenerativeModel', 'Spotify', 'SpotifyException',
                      'SpotifyClientCredentials']:
        setattr(mock_module, attr_name, Mock())

    if name == 'psycopg2':
        extensions_mock = Mock()
        extensions_mock.connection = Mock()
        mock_module.extensions = extensions_mock

    if name == 'spotipy':
        mock_module.Spotify = Mock()
        mock_module.SpotifyException = Exception
        mock_module.SpotifyClientCredentials = Mock()

    return mock_module

# Install mocks
mock_modules = {
    'psycopg2': create_mock_module('psycopg2'),
    'psycopg2.pool': create_mock_module('psycopg2.pool'),
    'psycopg2.extras': create_mock_module('psycopg2.extras'),
    'psycopg2.extensions': create_mock_module('psycopg2.extensions'),
    'dotenv': create_mock_module('dotenv'),
    'spotipy': create_mock_module('spotipy'),
    'google.generativeai': create_mock_module('google.generativeai'),
}

for name, module in mock_modules.items():
    sys.modules[name] = module

# Mock dotenv.load_dotenv
sys.modules['dotenv'].load_dotenv = Mock()


class TestGameServiceFixed(unittest.TestCase):
    """Fixed Game Service tests"""

    def setUp(self):
        """Set up test fixtures"""
        self.mock_player_service = Mock()
        self.mock_player_service.save_player = AsyncMock(return_value=True)
        self.test_player_data = {
            'player_id': 12345,
            'player_name': 'TestPlayer',
            'pisunchik_size': 10,
            'coins': 100.0,
            'items': [],
            'characteristics': [],
            'last_used': datetime.min.replace(tzinfo=timezone.utc),
            'casino_last_used': datetime.min.replace(tzinfo=timezone.utc),
            'casino_usage_count': 0
        }

    def test_game_service_initialization(self):
        """Test GameService initialization"""
        from services.game_service import GameService

        service = GameService(self.mock_player_service)
        self.assertEqual(service.player_service, self.mock_player_service)

    def test_pisunchik_cooldown_calculation(self):
        """Test pisunchik cooldown calculation"""
        from services.game_service import GameService
        from models.player import Player
        from config.game_config import GameConfig

        service = GameService(self.mock_player_service)

        # Test normal player (no characteristics)
        player = Player(**self.test_player_data)
        cooldown = service.calculate_pisunchik_cooldown(player)
        self.assertEqual(cooldown, GameConfig.PISUNCHIK_COOLDOWN_HOURS)

    def test_can_use_pisunchik_ready(self):
        """Test pisunchik command availability when ready"""
        from services.game_service import GameService
        from models.player import Player

        service = GameService(self.mock_player_service)

        # Player who hasn't used pisunchik recently
        old_time = datetime.now(timezone.utc) - timedelta(hours=25)
        player_data = {**self.test_player_data, 'last_used': old_time}
        player = Player(**player_data)

        can_use, time_left = service.can_use_pisunchik(player)

        self.assertTrue(can_use)
        self.assertIsNone(time_left)

    def test_can_use_pisunchik_cooldown(self):
        """Test pisunchik command cooldown"""
        from services.game_service import GameService
        from models.player import Player

        service = GameService(self.mock_player_service)

        # Player who used pisunchik recently
        recent_time = datetime.now(timezone.utc) - timedelta(hours=1)
        player_data = {**self.test_player_data, 'last_used': recent_time}
        player = Player(**player_data)

        can_use, time_left = service.can_use_pisunchik(player)

        self.assertFalse(can_use)
        self.assertIsInstance(time_left, timedelta)
        self.assertGreater(time_left.total_seconds(), 0)

    def test_item_effects_functionality(self):
        """Test item effects application"""
        from services.game_service import GameService
        from models.player import Player

        service = GameService(self.mock_player_service)

        # Player without items
        player = Player(**self.test_player_data)

        size_change, coins_change, effects = service.apply_item_effects(player, 5, 10)

        # Without items, should return original values
        self.assertEqual(size_change, 5)
        self.assertEqual(coins_change, 10)
        self.assertEqual(len(effects), 0)

    # theft test moved to async standalone test: test_theft_execution_cooldown_async


# Async tests using pytest
@pytest.mark.asyncio
@patch('services.game_service.random.randint')
async def test_execute_pisunchik_command_success(mock_randint):
    """Test successful pisunchik command execution"""
    from services.game_service import GameService
    from models.player import Player

    mock_randint.return_value = 5
    mock_player_service = Mock()
    mock_player_service.save_player = AsyncMock(return_value=True)

    service = GameService(mock_player_service)

    test_player_data = {
        'player_id': 12345,
        'player_name': 'TestPlayer',
        'pisunchik_size': 10,
        'coins': 100.0,
        'items': [],
        'characteristics': [],
        'last_used': datetime.now(timezone.utc) - timedelta(hours=25),
        'casino_last_used': datetime.min.replace(tzinfo=timezone.utc),
        'casino_usage_count': 0
    }
    player = Player(**test_player_data)

    result = await service.execute_pisunchik_command(player)

    assert result['success']
    assert 'new_size' in result
    assert 'size_change' in result
    assert 'coins_change' in result
    mock_player_service.save_player.assert_called_once()


@pytest.mark.asyncio
async def test_execute_pisunchik_command_cooldown():
    """Test pisunchik command execution during cooldown"""
    from services.game_service import GameService
    from models.player import Player

    mock_player_service = Mock()
    mock_player_service.save_player = AsyncMock()
    service = GameService(mock_player_service)

    recent_time = datetime.now(timezone.utc) - timedelta(hours=1)
    test_player_data = {
        'player_id': 12345,
        'player_name': 'TestPlayer',
        'pisunchik_size': 10,
        'coins': 100.0,
        'items': [],
        'characteristics': [],
        'last_used': recent_time,
        'casino_last_used': datetime.min.replace(tzinfo=timezone.utc),
        'casino_usage_count': 0
    }
    player = Player(**test_player_data)

    result = await service.execute_pisunchik_command(player)

    assert not result['success']
    assert 'message' in result
    mock_player_service.save_player.assert_not_called()


@pytest.mark.asyncio
async def test_casino_command_execution():
    """Test casino command execution"""
    from services.game_service import GameService
    from models.player import Player

    mock_player_service = Mock()
    mock_player_service.save_player = AsyncMock(return_value=True)
    service = GameService(mock_player_service)

    old_time = datetime.now(timezone.utc) - timedelta(hours=25)
    test_player_data = {
        'player_id': 12345,
        'player_name': 'TestPlayer',
        'pisunchik_size': 10,
        'coins': 50.0,
        'casino_last_used': old_time,
        'casino_usage_count': 0
    }
    player = Player(**test_player_data)

    result = await service.execute_casino_command(player)

    assert 'success' in result
    if result['success']:
        assert 'send_dice' in result
        assert 'dice_count' in result


@pytest.mark.asyncio
async def test_casino_command_daily_limit():
    """Test casino command with daily limit reached"""
    from services.game_service import GameService
    from models.player import Player
    from config.game_config import GameConfig

    mock_player_service = Mock()
    mock_player_service.save_player = AsyncMock()
    service = GameService(mock_player_service)

    recent_time = datetime.now(timezone.utc) - timedelta(hours=1)
    test_player_data = {
        'player_id': 12345,
        'player_name': 'TestPlayer',
        'pisunchik_size': 10,
        'coins': 50.0,
        'casino_last_used': recent_time,
        'casino_usage_count': GameConfig.CASINO_DAILY_LIMIT,
    }
    player = Player(**test_player_data)

    result = await service.execute_casino_command(player)

    assert not result['success']
    assert 'message' in result


@pytest.mark.asyncio
async def test_roll_command_execution():
    """Test roll command execution"""
    from services.game_service import GameService
    from models.player import Player

    mock_player_service = Mock()
    mock_player_service.save_player = AsyncMock(return_value=True)
    service = GameService(mock_player_service)

    test_player_data = {
        'player_id': 12345,
        'player_name': 'TestPlayer',
        'pisunchik_size': 10,
        'coins': 100.0,
    }
    player = Player(**test_player_data)

    with patch('services.game_service.random.randint') as mock_randint:
        mock_randint.side_effect = [3, 50, 5, 50, 2, 50]
        result = await service.execute_roll_command(player, 3)

    assert 'success' in result
    if result['success']:
        assert 'results' in result
        assert 'cost' in result
        assert 'new_size' in result


@pytest.mark.asyncio
@patch('services.game_service.random.randint')
async def test_jackpot_fires_at_1_in_300(mock_randint):
    """Jackpot fires when randint returns 14; upper bound is now 300."""
    from services.game_service import GameService
    from models.player import Player

    mock_player_service = Mock()
    mock_player_service.save_player = AsyncMock(return_value=True)
    service = GameService(mock_player_service)
    player = Player(player_id=12345, player_name='TestPlayer', coins=100.0)

    mock_randint.side_effect = [4, 14]
    result = await service.execute_roll_command(player, 1)
    assert result['jackpots'] == 1


@pytest.mark.asyncio
@patch('services.game_service.random.randint')
async def test_jackpot_misses_when_not_14(mock_randint):
    """Jackpot does not fire when randint returns any value other than 14."""
    from services.game_service import GameService
    from models.player import Player

    mock_player_service = Mock()
    mock_player_service.save_player = AsyncMock(return_value=True)
    service = GameService(mock_player_service)
    player = Player(player_id=12345, player_name='TestPlayer', coins=100.0)

    mock_randint.side_effect = [4, 15]
    result = await service.execute_roll_command(player, 1)
    assert result['jackpots'] == 0


@pytest.mark.asyncio
async def test_theft_execution_cooldown_async():
    """Test theft execution during cooldown"""
    from services.game_service import GameService
    from models.player import Player

    mock_player_service = Mock()
    mock_player_service.save_player = AsyncMock()
    service = GameService(mock_player_service)

    recent_time = datetime.now(timezone.utc) - timedelta(hours=1)
    thief = Player(player_id=11111, player_name='Thief', pisunchik_size=10, coins=100.0, last_vor=recent_time)
    victim = Player(player_id=22222, player_name='Victim', pisunchik_size=10, coins=100.0)

    result = await service.execute_theft(thief, victim)

    assert not result['success']
    assert 'message' in result


class TestGameServiceEdgeCasesFixed(unittest.TestCase):
    """Test game service edge cases - fixed version"""

    def setUp(self):
        """Set up test fixtures"""
        self.mock_player_service = Mock()
        self.mock_player_service.save_player = AsyncMock(return_value=True)


@pytest.mark.asyncio
async def test_negative_coins_handling():
    """Test handling of negative coin amounts"""
    from services.game_service import GameService
    from models.player import Player

    mock_player_service = Mock()
    mock_player_service.save_player = AsyncMock(return_value=True)
    service = GameService(mock_player_service)

    player = Player(
        player_id=123,
        player_name='TestPlayer',
        coins=-50.0,
        pisunchik_size=10,
        casino_last_used=datetime.min.replace(tzinfo=timezone.utc),
        casino_usage_count=0
    )

    result = await service.execute_casino_command(player)
    assert 'success' in result
    assert result['success']


@pytest.mark.asyncio
async def test_zero_size_handling():
    """Test handling of zero pisunchik size"""
    from services.game_service import GameService
    from models.player import Player

    mock_player_service = Mock()
    mock_player_service.save_player = AsyncMock(return_value=True)
    service = GameService(mock_player_service)

    old_time = datetime.now(timezone.utc) - timedelta(hours=25)
    player = Player(
        player_id=123,
        player_name='TestPlayer',
        pisunchik_size=0,
        coins=100.0,
        last_used=old_time,
        items=[],
        characteristics=[]
    )

    result = await service.execute_pisunchik_command(player)
    assert 'success' in result


def run_game_service_tests_fixed():
    """Run fixed game service tests"""
    print("Running Fixed Game Service Tests...")

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add test cases
    suite.addTests(loader.loadTestsFromTestCase(TestGameServiceFixed))
    suite.addTests(loader.loadTestsFromTestCase(TestGameServiceEdgeCasesFixed))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print(f"\nFixed Game Service Tests Results:")
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")

    success = len(result.failures) == 0 and len(result.errors) == 0

    if success:
        print("All Game Service tests passed!")
    else:
        print("Some Game Service tests failed:")
        for test, error in result.failures + result.errors:
            print(f"  {test}: {error[:100]}...")

    return success


if __name__ == "__main__":
    run_game_service_tests_fixed()
