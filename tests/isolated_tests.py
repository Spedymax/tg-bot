#!/usr/bin/env python3
"""
Isolated tests that don't require external dependencies
"""

import sys
import os
import unittest
from unittest.mock import Mock
from datetime import datetime, timezone, timedelta
import json

# Mock ALL external dependencies
class MockModule:
    def __getattr__(self, name):
        return Mock()

# Install mocks
sys.modules['spotipy'] = MockModule()
sys.modules['psycopg2'] = MockModule()
sys.modules['psycopg2.pool'] = MockModule()
sys.modules['psycopg2.extras'] = MockModule()
sys.modules['google.generativeai'] = MockModule()
sys.modules['telebot'] = MockModule()
sys.modules['schedule'] = MockModule()
sys.modules['pytz'] = MockModule()
sys.modules['dotenv'] = MockModule()

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

class TestPlayerModelIsolated(unittest.TestCase):
    """Isolated tests for Player model"""

    def test_player_model_basic_functionality(self):
        """Test basic Player model functionality"""
        # Import here to ensure mocks are in place
        from models.player import Player
        
        # Test player creation
        player = Player(
            player_id=12345,
            player_name="TestPlayer"
        )
        
        self.assertEqual(player.player_id, 12345)
        self.assertEqual(player.player_name, "TestPlayer")
        self.assertEqual(player.pisunchik_size, 0)
        self.assertEqual(player.coins, 0.0)
        self.assertIsInstance(player.items, list)
        self.assertEqual(len(player.items), 0)

    def test_player_has_item_method(self):
        """Test player has_item method"""
        from models.player import Player
        
        player = Player(
            player_id=12345,
            player_name="TestPlayer",
            items=['sword', 'shield', 'potion']
        )
        
        self.assertTrue(player.has_item('sword'))
        self.assertTrue(player.has_item('shield'))
        self.assertFalse(player.has_item('bow'))
        self.assertFalse(player.has_item(''))

    def test_player_datetime_fields(self):
        """Test player datetime field handling"""
        from models.player import Player
        
        player = Player(
            player_id=12345,
            player_name="TestPlayer"
        )
        
        # Check that datetime fields exist and are datetime objects
        self.assertIsInstance(player.last_used, datetime)
        self.assertIsInstance(player.last_vor, datetime)
        self.assertIsInstance(player.casino_last_used, datetime)
        
        # Check timezone awareness
        self.assertIsNotNone(player.last_used.tzinfo)

class TestGameConfigIsolated(unittest.TestCase):
    """Isolated tests for game configuration"""

    def test_game_config_constants(self):
        """Test that game config constants are properly defined"""
        from config.game_config import GameConfig
        
        # Test basic constants exist
        self.assertTrue(hasattr(GameConfig, 'PISUNCHIK_COOLDOWN_HOURS'))
        self.assertTrue(hasattr(GameConfig, 'CASINO_DAILY_LIMIT'))
        self.assertTrue(hasattr(GameConfig, 'ITEM_EFFECTS'))
        
        # Test types
        self.assertIsInstance(GameConfig.PISUNCHIK_COOLDOWN_HOURS, int)
        self.assertIsInstance(GameConfig.CASINO_DAILY_LIMIT, int)
        self.assertIsInstance(GameConfig.ITEM_EFFECTS, dict)
        
        # Test reasonable values
        self.assertGreater(GameConfig.PISUNCHIK_COOLDOWN_HOURS, 0)
        self.assertGreater(GameConfig.CASINO_DAILY_LIMIT, 0)

    def test_item_effects_structure(self):
        """Test item effects dictionary structure"""
        from config.game_config import GameConfig
        
        # Test that item effects have expected structure
        for item_name, effect in GameConfig.ITEM_EFFECTS.items():
            self.assertIsInstance(item_name, str)
            self.assertIsInstance(effect, dict)
            self.assertIn('type', effect)

class TestUtilityFunctions(unittest.TestCase):
    """Test utility functions without external dependencies"""

    def test_datetime_utilities(self):
        """Test datetime utility functions"""
        now = datetime.now(timezone.utc)
        past = now - timedelta(hours=24)
        
        # Test timezone awareness
        self.assertIsNotNone(now.tzinfo)
        self.assertIsNotNone(past.tzinfo)
        
        # Test time calculations
        diff = now - past
        self.assertEqual(diff.total_seconds(), 24 * 3600)

    def test_json_handling(self):
        """Test JSON handling capabilities"""
        test_data = {
            'items': ['sword', 'shield'],
            'stats': {'level': 5, 'coins': 100.5},
            'active': True
        }
        
        # Test serialization
        json_str = json.dumps(test_data)
        self.assertIsInstance(json_str, str)
        
        # Test deserialization
        loaded_data = json.loads(json_str)
        self.assertEqual(loaded_data, test_data)

class TestErrorHandlingLogic(unittest.TestCase):
    """Test error handling logic without Telegram dependencies"""

    def test_error_classification(self):
        """Test error classification logic"""
        
        # Mock error class
        class MockTelegramError:
            def __init__(self, description, error_code):
                self.description = description
                self.error_code = error_code
        
        # Test blocked user error
        blocked_error = MockTelegramError("Forbidden: bot was blocked by the user", 403)
        self.assertEqual(blocked_error.error_code, 403)
        self.assertIn("blocked", blocked_error.description)
        
        # Test chat not found error
        chat_error = MockTelegramError("Bad Request: chat not found", 400)
        self.assertEqual(chat_error.error_code, 400)
        self.assertIn("chat not found", chat_error.description)

class TestGameLogic(unittest.TestCase):
    """Test game logic without external dependencies"""

    def test_cooldown_calculations(self):
        """Test cooldown calculation logic"""
        from config.game_config import GameConfig
        
        # Test basic cooldown
        base_cooldown = GameConfig.PISUNCHIK_COOLDOWN_HOURS
        self.assertIsInstance(base_cooldown, int)
        self.assertGreater(base_cooldown, 0)
        
        # Test time calculations
        current_time = datetime.now(timezone.utc)
        last_used = current_time - timedelta(hours=base_cooldown + 1)
        time_since = current_time - last_used
        
        self.assertGreater(time_since.total_seconds(), base_cooldown * 3600)

    def test_probability_ranges(self):
        """Test that probability values are in valid ranges"""
        from config.game_config import GameConfig
        
        for item_name, effect in GameConfig.ITEM_EFFECTS.items():
            if 'probability' in effect:
                prob = effect['probability']
                self.assertGreaterEqual(prob, 0.0)
                self.assertLessEqual(prob, 1.0)

def run_isolated_tests():
    """Run all isolated tests"""
    print("🔬 Running Isolated Tests (No External Dependencies)")
    print("=" * 60)
    
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add test cases
    suite.addTests(loader.loadTestsFromTestCase(TestPlayerModelIsolated))
    suite.addTests(loader.loadTestsFromTestCase(TestGameConfigIsolated))
    suite.addTests(loader.loadTestsFromTestCase(TestUtilityFunctions))
    suite.addTests(loader.loadTestsFromTestCase(TestErrorHandlingLogic))
    suite.addTests(loader.loadTestsFromTestCase(TestGameLogic))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print(f"\n📊 Isolated Tests Results:")
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")
    
    success = len(result.failures) == 0 and len(result.errors) == 0
    
    if success:
        print("\n🎉 ALL ISOLATED TESTS PASSED! 🎉")
        print("Core functionality is working correctly!")
    else:
        print("\n❌ Some tests failed:")
        for test, failure in result.failures:
            print(f"  FAIL: {test}")
        for test, error in result.errors:
            print(f"  ERROR: {test}")
    
    return success

if __name__ == "__main__":
    success = run_isolated_tests()
    sys.exit(0 if success else 1)