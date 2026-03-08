#!/usr/bin/env python3
"""
Fixed Player Service tests with comprehensive mocking
"""

import sys
import os
import unittest
import pytest
from unittest.mock import Mock, patch, AsyncMock
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
                      'extensions', 'connection', 'load_dotenv',
                      'AsyncConnectionPool', 'ConnectionPool']:
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
    'psycopg_pool': create_mock_module('psycopg_pool'),
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
        self.mock_db_manager.execute_query = AsyncMock()
        self.mock_db_manager.connection = Mock()

    def test_player_service_initialization(self):
        """Test PlayerService initialization"""
        from database.player_service import PlayerService

        service = PlayerService(self.mock_db_manager, redis=None)

        self.assertEqual(service.db, self.mock_db_manager)
        # Redis-backed cache: _redis should be None when no redis provided
        self.assertIsNone(service._redis)


@pytest.mark.asyncio
async def test_get_player_from_cache():
    """Test getting player from cache (Redis-backed)"""
    from database.player_service import PlayerService
    from models.player import Player

    mock_db_manager = Mock()
    mock_db_manager.execute_query = AsyncMock()
    mock_db_manager.connection = Mock()

    # Create a mock Redis that returns a cached player
    test_player = Player(player_id=12345, player_name="TestPlayer")
    serialized = PlayerService._serialize_player(test_player)

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=serialized)

    service = PlayerService(mock_db_manager, redis=mock_redis)

    # Get player (should come from Redis cache)
    player = await service.get_player(12345)

    assert player is not None
    assert player.player_id == 12345
    assert player.player_name == "TestPlayer"


@pytest.mark.asyncio
async def test_get_player_not_found():
    """Test getting non-existent player"""
    from database.player_service import PlayerService

    mock_db_manager = Mock()

    # Mock the async context manager for db connection
    mock_cursor = AsyncMock()
    mock_cursor.fetchone = AsyncMock(return_value=None)
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=mock_cursor)
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_db_manager.connection = Mock(return_value=mock_ctx)

    service = PlayerService(mock_db_manager, redis=None)
    player = await service.get_player(12345)

    assert player is None


@pytest.mark.asyncio
async def test_save_player_functionality():
    """Test save player with mocked database"""
    from database.player_service import PlayerService
    from models.player import Player

    mock_db_manager = Mock()

    # Mock the async context manager for db connection with transaction
    mock_cursor_select = AsyncMock()
    mock_cursor_select.fetchone = AsyncMock(return_value=None)  # player doesn't exist yet

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=mock_cursor_select)

    mock_transaction = AsyncMock()
    mock_transaction.__aenter__ = AsyncMock()
    mock_transaction.__aexit__ = AsyncMock(return_value=False)
    mock_conn.transaction = Mock(return_value=mock_transaction)

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_db_manager.connection = Mock(return_value=mock_ctx)

    service = PlayerService(mock_db_manager, redis=None)
    player = Player(player_id=12345, player_name="TestPlayer")

    result = await service.save_player(player)

    assert result is True
    mock_conn.execute.assert_called()


@pytest.mark.asyncio
async def test_database_error_handling():
    """Test database error handling"""
    from database.player_service import PlayerService

    mock_db_manager = Mock()

    # Make connection() raise an exception via the context manager
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(side_effect=Exception("Database connection failed"))
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_db_manager.connection = Mock(return_value=mock_ctx)

    service = PlayerService(mock_db_manager, redis=None)

    # The service should handle the error gracefully and return None
    player = await service.get_player(12345)
    assert player is None


def run_player_service_tests_fixed():
    """Run fixed player service tests"""
    print("Running Fixed Player Service Tests...")

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add test cases
    suite.addTests(loader.loadTestsFromTestCase(TestPlayerModelFixed))
    suite.addTests(loader.loadTestsFromTestCase(TestPlayerServiceFixed))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print(f"\nFixed Player Service Tests Results:")
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")

    success = len(result.failures) == 0 and len(result.errors) == 0

    if success:
        print("All Player Service tests passed!")
    else:
        print("Some Player Service tests failed:")
        for test, error in result.failures + result.errors:
            print(f"  {test}: {error[:100]}...")

    return success

if __name__ == "__main__":
    run_player_service_tests_fixed()
