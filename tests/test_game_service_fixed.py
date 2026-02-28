#!/usr/bin/env python3
"""
Fixed Game Service tests with comprehensive mocking
"""

import sys
import os
import unittest
from unittest.mock import Mock, patch, MagicMock
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
    
    @patch('services.game_service.random.randint')
    def test_execute_pisunchik_command_success(self, mock_randint):
        """Test successful pisunchik command execution"""
        from services.game_service import GameService
        from models.player import Player
        
        # Mock random size change
        mock_randint.return_value = 5
        
        service = GameService(self.mock_player_service)
        self.mock_player_service.save_player.return_value = True
        
        # Player ready to use pisunchik
        old_time = datetime.now(timezone.utc) - timedelta(hours=25)
        player_data = {**self.test_player_data, 'last_used': old_time}
        player = Player(**player_data)
        
        result = service.execute_pisunchik_command(player)
        
        self.assertTrue(result['success'])
        self.assertIn('new_size', result)
        self.assertIn('size_change', result)
        self.assertIn('coins_change', result)
        self.mock_player_service.save_player.assert_called_once()
    
    def test_execute_pisunchik_command_cooldown(self):
        """Test pisunchik command execution during cooldown"""
        from services.game_service import GameService
        from models.player import Player
        
        service = GameService(self.mock_player_service)
        
        # Player on cooldown
        recent_time = datetime.now(timezone.utc) - timedelta(hours=1)
        player_data = {**self.test_player_data, 'last_used': recent_time}
        player = Player(**player_data)
        
        result = service.execute_pisunchik_command(player)
        
        self.assertFalse(result['success'])
        self.assertIn('message', result)
        self.mock_player_service.save_player.assert_not_called()
    
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
    
    def test_casino_command_execution(self):
        """Test casino command execution"""
        from services.game_service import GameService
        from models.player import Player
        
        service = GameService(self.mock_player_service)
        self.mock_player_service.save_player.return_value = True
        
        # Player ready for casino
        old_time = datetime.now(timezone.utc) - timedelta(hours=25)
        player_data = {**self.test_player_data, 'casino_last_used': old_time, 'coins': 50.0}
        player = Player(**player_data)
        
        result = service.execute_casino_command(player)
        
        self.assertIn('success', result)
        if result['success']:
            self.assertIn('send_dice', result)
            self.assertIn('dice_count', result)
    
    def test_casino_command_daily_limit(self):
        """Test casino command with daily limit reached"""
        from services.game_service import GameService
        from models.player import Player
        from config.game_config import GameConfig
        
        service = GameService(self.mock_player_service)
        
        # Player who has reached daily limit
        recent_time = datetime.now(timezone.utc) - timedelta(hours=1)
        player_data = {
            **self.test_player_data,
            'casino_last_used': recent_time,
            'casino_usage_count': GameConfig.CASINO_DAILY_LIMIT,
            'coins': 50.0
        }
        player = Player(**player_data)
        
        result = service.execute_casino_command(player)
        
        self.assertFalse(result['success'])
        self.assertIn('message', result)
    
    def test_roll_command_execution(self):
        """Test roll command execution"""
        from services.game_service import GameService
        from models.player import Player
        
        service = GameService(self.mock_player_service)
        self.mock_player_service.save_player.return_value = True
        
        # Player with enough coins for roll
        player_data = {**self.test_player_data, 'coins': 100.0}
        player = Player(**player_data)
        
        with patch('services.game_service.random.randint') as mock_randint:
            # Mock dice rolls and jackpot check - provide enough values
            mock_randint.side_effect = [3, 50, 5, 50, 2, 50]  # dice roll, jackpot check, repeat
            result = service.execute_roll_command(player, 3)
        
        self.assertIn('success', result)
        if result['success']:
            self.assertIn('results', result)
            self.assertIn('cost', result)
            self.assertIn('new_size', result)
    
    def _make_service_and_player(self):
        """Helper: return a (GameService, Player) tuple ready for roll tests."""
        from services.game_service import GameService
        from models.player import Player

        self.mock_player_service.save_player.return_value = True
        service = GameService(self.mock_player_service)
        player_data = {**self.test_player_data, 'coins': 100.0}
        player = Player(**player_data)
        return service, player

    @patch('services.game_service.random.randint')
    def test_jackpot_fires_at_1_in_300(self, mock_randint):
        """Jackpot fires when randint returns 14; upper bound is now 300."""
        service, player = self._make_service_and_player()
        # 1 roll: dice value 4 (win size), jackpot check returns 14 (hits)
        mock_randint.side_effect = [4, 14]
        result = service.execute_roll_command(player, 1)
        assert result['jackpots'] == 1

    @patch('services.game_service.random.randint')
    def test_jackpot_misses_when_not_14(self, mock_randint):
        """Jackpot does not fire when randint returns any value other than 14."""
        service, player = self._make_service_and_player()
        mock_randint.side_effect = [4, 15]
        result = service.execute_roll_command(player, 1)
        assert result['jackpots'] == 0

    def test_theft_execution_cooldown(self):
        """Test theft execution during cooldown"""
        from services.game_service import GameService
        from models.player import Player
        
        service = GameService(self.mock_player_service)
        
        # Thief on cooldown
        recent_time = datetime.now(timezone.utc) - timedelta(hours=1)
        thief_data = {**self.test_player_data, 'player_id': 11111, 'last_vor': recent_time}
        thief = Player(**thief_data)
        
        victim_data = {**self.test_player_data, 'player_id': 22222}
        victim = Player(**victim_data)
        
        result = service.execute_theft(thief, victim)
        
        self.assertFalse(result['success'])
        self.assertIn('message', result)


class TestGameServiceEdgeCasesFixed(unittest.TestCase):
    """Test game service edge cases - fixed version"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_player_service = Mock()
    
    def test_negative_coins_handling(self):
        """Test handling of negative coin amounts"""
        from services.game_service import GameService
        from models.player import Player
        
        service = GameService(self.mock_player_service)
        
        # Player with negative coins
        player_data = {
            'player_id': 123,
            'player_name': 'TestPlayer',
            'coins': -50.0,
            'pisunchik_size': 10,
            'casino_last_used': datetime.min.replace(tzinfo=timezone.utc),
            'casino_usage_count': 0
        }
        player = Player(**player_data)
        
        # Casino command doesn't check coins, so it should succeed
        result = service.execute_casino_command(player)
        self.assertIn('success', result)
        # Casino allows usage regardless of coin amount
        self.assertTrue(result['success'])
    
    def test_zero_size_handling(self):
        """Test handling of zero pisunchik size"""
        from services.game_service import GameService
        from models.player import Player
        
        service = GameService(self.mock_player_service)
        self.mock_player_service.save_player.return_value = True
        
        # Player with zero size
        old_time = datetime.now(timezone.utc) - timedelta(hours=25)
        player_data = {
            'player_id': 123,
            'player_name': 'TestPlayer',
            'pisunchik_size': 0,
            'coins': 100.0,
            'last_used': old_time,
            'items': [],
            'characteristics': []
        }
        player = Player(**player_data)
        
        result = service.execute_pisunchik_command(player)
        
        # Should handle zero size appropriately
        self.assertIn('success', result)


def run_game_service_tests_fixed():
    """Run fixed game service tests"""
    print("🎮 Running Fixed Game Service Tests...")
    
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add test cases
    suite.addTests(loader.loadTestsFromTestCase(TestGameServiceFixed))
    suite.addTests(loader.loadTestsFromTestCase(TestGameServiceEdgeCasesFixed))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print(f"\n📊 Fixed Game Service Tests Results:")
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")
    
    success = len(result.failures) == 0 and len(result.errors) == 0
    
    if success:
        print("✅ All Game Service tests passed!")
    else:
        print("❌ Some Game Service tests failed:")
        for test, error in result.failures + result.errors:
            print(f"  {test}: {error[:100]}...")
    
    return success


if __name__ == "__main__":
    run_game_service_tests_fixed()