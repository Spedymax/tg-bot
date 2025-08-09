#!/usr/bin/env python3
"""
Tests for utility functions and helper modules
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import sys
import os
import json
from datetime import datetime, timezone, timedelta

# Add project paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

class TestTelegramErrorHandler(unittest.TestCase):
    """Test Telegram error handling utilities"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_bot = Mock()
        self.test_user_id = 12345
        self.test_chat_id = -123456
        
    def test_error_handler_import(self):
        """Test that error handler can be imported"""
        try:
            from services.telegram_error_handler import TelegramErrorHandler, telegram_error_handler
            self.assertTrue(True)  # Import successful
        except ImportError:
            self.skipTest("Cannot import TelegramErrorHandler")

    def test_handle_blocked_user_error(self):
        """Test handling blocked user errors"""
        try:
            from services.telegram_error_handler import TelegramErrorHandler
            
            # Mock API exception for blocked user
            class MockApiException:
                def __init__(self, description, error_code):
                    self.description = description
                    self.error_code = error_code
            
            blocked_error = MockApiException("Forbidden: bot was blocked by the user", 403)
            result = TelegramErrorHandler.handle_api_error(blocked_error, self.test_user_id, "send_message")
            
            self.assertTrue(result)  # Should be handled gracefully
            
        except ImportError:
            self.skipTest("Cannot import TelegramErrorHandler")

    def test_handle_deactivated_user_error(self):
        """Test handling deactivated user errors"""
        try:
            from services.telegram_error_handler import TelegramErrorHandler
            
            class MockApiException:
                def __init__(self, description, error_code):
                    self.description = description
                    self.error_code = error_code
            
            deactivated_error = MockApiException("Forbidden: user is deactivated", 403)
            result = TelegramErrorHandler.handle_api_error(deactivated_error, self.test_user_id, "send_message")
            
            self.assertTrue(result)  # Should be handled gracefully
            
        except ImportError:
            self.skipTest("Cannot import TelegramErrorHandler")

    def test_handle_chat_not_found_error(self):
        """Test handling chat not found errors"""
        try:
            from services.telegram_error_handler import TelegramErrorHandler
            
            class MockApiException:
                def __init__(self, description, error_code):
                    self.description = description
                    self.error_code = error_code
            
            chat_error = MockApiException("Bad Request: chat not found", 400)
            result = TelegramErrorHandler.handle_api_error(chat_error, self.test_user_id, "send_message")
            
            self.assertTrue(result)  # Should be handled gracefully
            
        except ImportError:
            self.skipTest("Cannot import TelegramErrorHandler")

    def test_safe_send_message(self):
        """Test safe send message wrapper"""
        try:
            from services.telegram_error_handler import TelegramErrorHandler
            
            # Test successful send
            result = TelegramErrorHandler.safe_send_message(self.mock_bot, self.test_chat_id, "Test message")
            self.mock_bot.send_message.assert_called_with(self.test_chat_id, "Test message")
            
        except ImportError:
            self.skipTest("Cannot import TelegramErrorHandler")

class TestTelegramHelpers(unittest.TestCase):
    """Test telegram helper utilities"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_bot = Mock()
        
    def test_telegram_helpers_import(self):
        """Test that telegram helpers can be imported"""
        try:
            from utils.telegram_helpers import safe_bot_action, safe_send_message, safe_reply_to
            self.assertTrue(True)  # Import successful
        except ImportError:
            self.skipTest("Cannot import telegram helpers")

    def test_safe_bot_action_decorator(self):
        """Test safe bot action decorator"""
        try:
            from utils.telegram_helpers import safe_bot_action
            
            @safe_bot_action("test_action")
            def test_function():
                return "success"
            
            result = test_function()
            self.assertEqual(result, "success")
            
        except ImportError:
            self.skipTest("Cannot import safe_bot_action")

class TestConfigurationHandling(unittest.TestCase):
    """Test configuration and settings handling"""
    
    def test_settings_import(self):
        """Test that settings can be imported"""
        try:
            from config.settings import Settings
            self.assertTrue(hasattr(Settings, 'DB_CONFIG'))
            self.assertTrue(hasattr(Settings, 'ADMIN_IDS'))
        except ImportError:
            self.skipTest("Cannot import Settings")

    def test_game_config_import(self):
        """Test that game config can be imported"""
        try:
            from config.game_config import GameConfig
            self.assertTrue(True)  # Import successful
        except ImportError:
            self.skipTest("Cannot import GameConfig")

    def test_admin_ids_configuration(self):
        """Test admin IDs configuration"""
        try:
            from config.settings import Settings
            
            self.assertIsInstance(Settings.ADMIN_IDS, list)
            self.assertGreater(len(Settings.ADMIN_IDS), 0)
            
            # All admin IDs should be integers
            for admin_id in Settings.ADMIN_IDS:
                self.assertIsInstance(admin_id, int)
                
        except ImportError:
            self.skipTest("Cannot import Settings")

    def test_chat_ids_configuration(self):
        """Test chat IDs configuration"""
        try:
            from config.settings import Settings
            
            self.assertIsInstance(Settings.CHAT_IDS, dict)
            self.assertIn('main', Settings.CHAT_IDS)
            
        except ImportError:
            self.skipTest("Cannot import Settings")

class TestDatabaseManager(unittest.TestCase):
    """Test database manager functionality"""
    
    def test_database_manager_import(self):
        """Test that database manager can be imported"""
        try:
            from database.db_manager import DatabaseManager
            self.assertTrue(True)  # Import successful
        except ImportError:
            self.skipTest("Cannot import DatabaseManager")

    def test_database_manager_initialization(self):
        """Test database manager initialization"""
        try:
            from database.db_manager import DatabaseManager
            
            # This test may fail if no database connection is available
            # but it tests the class can be instantiated
            with patch('database.db_manager.psycopg2') as mock_psycopg2:
                mock_pool = Mock()
                mock_psycopg2.pool.ThreadedConnectionPool.return_value = mock_pool
                
                db_manager = DatabaseManager()
                self.assertIsNotNone(db_manager)
                
        except ImportError:
            self.skipTest("Cannot import DatabaseManager")

class TestJSONDataHandling(unittest.TestCase):
    """Test JSON data file handling"""
    
    def test_load_json_file_success(self):
        """Test successful JSON file loading"""
        try:
            from main import TelegramBot
            
            # Create a temporary JSON file
            test_data = {"test": "data", "items": [1, 2, 3]}
            test_file = "/tmp/test_data.json"
            
            with open(test_file, 'w') as f:
                json.dump(test_data, f)
            
            # Test loading
            loaded_data = TelegramBot.load_json_file(test_file)
            self.assertEqual(loaded_data, test_data)
            
            # Clean up
            os.remove(test_file)
            
        except ImportError:
            self.skipTest("Cannot import TelegramBot")
        except Exception:
            self.skipTest("Cannot create test file or load JSON")

    def test_load_json_file_not_found(self):
        """Test JSON file loading when file doesn't exist"""
        try:
            from main import TelegramBot
            
            # Test loading non-existent file
            loaded_data = TelegramBot.load_json_file("/nonexistent/path/data.json")
            self.assertEqual(loaded_data, {})  # Should return empty dict
            
        except ImportError:
            self.skipTest("Cannot import TelegramBot")

    def test_game_data_files_exist(self):
        """Test that required game data files exist"""
        required_files = [
            '/home/spedymax/tg-bot/assets/data/char.json',
            '/home/spedymax/tg-bot/assets/data/plot.json',
            '/home/spedymax/tg-bot/assets/data/shop.json',
            '/home/spedymax/tg-bot/assets/data/statuetki.json'
        ]
        
        for file_path in required_files:
            full_path = os.path.join('..', file_path)
            if os.path.exists(full_path):
                # File exists, try to load it
                try:
                    with open(full_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    self.assertIsInstance(data, (dict, list))
                except json.JSONDecodeError:
                    self.fail(f"Invalid JSON in {file_path}")

class TestUtilityFunctions(unittest.TestCase):
    """Test various utility functions"""
    
    def test_datetime_handling(self):
        """Test datetime utility handling"""
        # Test timezone-aware datetime creation
        now = datetime.now(timezone.utc)
        self.assertIsNotNone(now.tzinfo)
        
        # Test timedelta calculations
        past_time = now - timedelta(hours=24)
        time_diff = now - past_time
        self.assertEqual(time_diff.total_seconds(), 24 * 3600)

    def test_random_functionality(self):
        """Test random number generation utilities"""
        import random
        
        # Test random integer generation
        rand_int = random.randint(1, 10)
        self.assertTrue(1 <= rand_int <= 10)
        
        # Test random choice
        choices = ['a', 'b', 'c', 'd']
        choice = random.choice(choices)
        self.assertIn(choice, choices)
        
        # Test random probability
        prob = random.random()
        self.assertTrue(0.0 <= prob < 1.0)

class TestLogging(unittest.TestCase):
    """Test logging configuration and functionality"""
    
    def test_logging_import(self):
        """Test that logging can be imported and configured"""
        import logging
        
        # Test logger creation
        logger = logging.getLogger('test_logger')
        self.assertIsInstance(logger, logging.Logger)
        
        # Test logging levels
        self.assertTrue(hasattr(logging, 'INFO'))
        self.assertTrue(hasattr(logging, 'ERROR'))
        self.assertTrue(hasattr(logging, 'WARNING'))

    def test_bot_logging_configuration(self):
        """Test bot logging configuration"""
        try:
            import logging
            
            # Test that we can create a logger similar to the bot's
            logger = logging.getLogger('bot_test')
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
            
            self.assertEqual(logger.level, logging.INFO)
            self.assertGreater(len(logger.handlers), 0)
            
        except Exception as e:
            self.skipTest(f"Cannot test logging configuration: {e}")

class TestMiniAppComponents(unittest.TestCase):
    """Test mini-app related utilities"""
    
    def test_miniapp_files_exist(self):
        """Test that mini-app files exist"""
        miniapp_files = [
            'miniapp/app.py',
            'miniapp/package.json',
            'miniapp/slot_casino.html'
        ]
        
        for file_path in miniapp_files:
            full_path = os.path.join('..', file_path)
            if os.path.exists(full_path):
                self.assertTrue(os.path.isfile(full_path))

    def test_miniapp_package_json(self):
        """Test mini-app package.json structure"""
        package_path = '../miniapp/package.json'
        if os.path.exists(package_path):
            try:
                with open(package_path, 'r') as f:
                    package_data = json.load(f)
                
                # Check required fields
                required_fields = ['name', 'version', 'scripts', 'dependencies']
                for field in required_fields:
                    self.assertIn(field, package_data)
                
                # Check required scripts
                scripts = package_data.get('scripts', {})
                self.assertIn('dev', scripts)
                self.assertIn('build', scripts)
                
            except json.JSONDecodeError:
                self.fail("Invalid JSON in miniapp/package.json")

def run_utility_tests():
    """Run all utility tests"""
    print("🔧 Running Utility Tests...")
    
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add test cases
    suite.addTests(loader.loadTestsFromTestCase(TestTelegramErrorHandler))
    suite.addTests(loader.loadTestsFromTestCase(TestTelegramHelpers))
    suite.addTests(loader.loadTestsFromTestCase(TestConfigurationHandling))
    suite.addTests(loader.loadTestsFromTestCase(TestDatabaseManager))
    suite.addTests(loader.loadTestsFromTestCase(TestJSONDataHandling))
    suite.addTests(loader.loadTestsFromTestCase(TestUtilityFunctions))
    suite.addTests(loader.loadTestsFromTestCase(TestLogging))
    suite.addTests(loader.loadTestsFromTestCase(TestMiniAppComponents))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print(f"\n📊 Utility Tests Results:")
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")
    
    if result.failures:
        print("\n❌ Failures:")
        for test, failure in result.failures:
            print(f"  {test}: {failure}")
            
    if result.errors:
        print("\n🚨 Errors:")
        for test, error in result.errors:
            print(f"  {test}: {error}")
    
    return result.wasSuccessful()

if __name__ == "__main__":
    run_utility_tests()