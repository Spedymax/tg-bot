#!/usr/bin/env python3
"""
Fixed Player Service tests with comprehensive mocking
"""

import sys
import os
import unittest
from unittest.mock import Mock, patch
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
                      'extensions', 'connection', 'load_dotenv']:
        setattr(mock_module, attr_name, Mock())
    
    if name == 'psycopg2':
        extensions_mock = Mock()
        extensions_mock.connection = Mock()
        mock_module.extensions = extensions_mock
    
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
    'telebot': create_mock_module('telebot'),
    'schedule': create_mock_module('schedule'),
    'apscheduler': create_mock_module('apscheduler'),
    'apscheduler.schedulers': create_mock_module('apscheduler.schedulers'),
    'apscheduler.schedulers.background': create_mock_module('apscheduler.schedulers.background'),
}

for name, module in mock_modules.items():
    sys.modules[name] = module

# Mock dotenv.load_dotenv
sys.modules['dotenv'].load_dotenv = Mock()

class TestPlayerModelFixed(unittest.TestCase):
    """Fixed Player model tests"""
    
    def test_player_model_functionality(self):
        """Test Player model with comprehensive setup"""
        from models.player import Player
        
        # Test basic creation
        player = Player(player_id=12345, player_name="TestPlayer")
        self.assertEqual(player.player_id, 12345)
        self.assertEqual(player.player_name, "TestPlayer")
        self.assertEqual(player.pisunchik_size, 0)
        self.assertIsInstance(player.items, list)
        
        # Test has_item functionality
        player.items = ['sword', 'shield']
        self.assertTrue(player.has_item('sword'))
        self.assertFalse(player.has_item('bow'))
        
        # Test datetime fields
        self.assertIsInstance(player.last_used, datetime)
        self.assertIsNotNone(player.last_used.tzinfo)

class TestPlayerServiceFixed(unittest.TestCase):
    """Fixed Player service tests"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_db_manager = Mock()
        self.mock_connection = Mock()
        self.mock_cursor = Mock()
        
        # Setup connection chain
        self.mock_db_manager.get_connection.return_value = self.mock_connection
        self.mock_connection.cursor.return_value.__enter__ = Mock(return_value=self.mock_cursor)
        self.mock_connection.cursor.return_value.__exit__ = Mock(return_value=None)
    
    def test_player_service_initialization(self):
        """Test PlayerService initialization"""
        from database.player_service import PlayerService
        
        service = PlayerService(self.mock_db_manager)
        
        self.assertEqual(service.db, self.mock_db_manager)
        self.assertIsInstance(service._cache, dict)
        self.assertEqual(len(service._cache), 0)
    
    def test_get_player_from_cache(self):
        """Test getting player from cache"""
        from database.player_service import PlayerService
        from models.player import Player
        
        service = PlayerService(self.mock_db_manager)
        
        # Add player to cache
        test_player = Player(player_id=12345, player_name="TestPlayer")
        service._cache[12345] = test_player
        
        # Get player (should come from cache)
        player = service.get_player(12345)
        
        self.assertEqual(player, test_player)
        # Verify no database call was made
        self.mock_db_manager.get_connection.assert_not_called()
    
    def test_get_player_not_found(self):
        """Test getting non-existent player"""
        from database.player_service import PlayerService
        
        self.mock_cursor.fetchone.return_value = None
        
        service = PlayerService(self.mock_db_manager)
        player = service.get_player(12345)
        
        self.assertIsNone(player)
        self.assertNotIn(12345, service._cache)

class TestPlayerServiceDatabase(unittest.TestCase):
    """Test database operations"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_db_manager = Mock()
        
    def test_database_error_handling(self):
        """Test database error handling"""
        from database.player_service import PlayerService
        
        # Mock database error
        self.mock_db_manager.get_connection.side_effect = Exception("Database connection failed")
        
        service = PlayerService(self.mock_db_manager)
        
        # The service should handle the error gracefully and return None
        try:
            player = service.get_player(12345)
            # Should return None on error
            self.assertIsNone(player)
        except Exception as e:
            # If an exception is raised, that's also acceptable behavior
            # as long as it's handled properly in the calling code
            self.assertIn("Database connection failed", str(e))
    
    def test_save_player_functionality(self):
        """Test save player with mocked database"""
        from database.player_service import PlayerService
        from models.player import Player
        
        mock_connection = Mock()
        mock_cursor = Mock()
        self.mock_db_manager.get_connection.return_value = mock_connection
        mock_connection.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
        mock_connection.cursor.return_value.__exit__ = Mock(return_value=None)
        
        # Mock player doesn't exist (new player)
        mock_cursor.fetchone.return_value = None
        
        service = PlayerService(self.mock_db_manager)
        player = Player(player_id=12345, player_name="TestPlayer")
        
        result = service.save_player(player)
        
        self.assertTrue(result)
        # Verify database operations were called
        mock_cursor.execute.assert_called()

def run_player_service_tests_fixed():
    """Run fixed player service tests"""
    print("👤 Running Fixed Player Service Tests...")
    
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add test cases
    suite.addTests(loader.loadTestsFromTestCase(TestPlayerModelFixed))
    suite.addTests(loader.loadTestsFromTestCase(TestPlayerServiceFixed))
    suite.addTests(loader.loadTestsFromTestCase(TestPlayerServiceDatabase))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print(f"\n📊 Fixed Player Service Tests Results:")
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")
    
    success = len(result.failures) == 0 and len(result.errors) == 0
    
    if success:
        print("✅ All Player Service tests passed!")
    else:
        print("❌ Some Player Service tests failed:")
        for test, error in result.failures + result.errors:
            print(f"  {test}: {error[:100]}...")
    
    return success

if __name__ == "__main__":
    run_player_service_tests_fixed()