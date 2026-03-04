import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from unittest.mock import MagicMock
from services.court_service import CourtService

def make_service():
    db = MagicMock()
    db.execute_query.return_value = None
    return CourtService(db)

def test_create_game_returns_id():
    svc = make_service()
    svc.db.execute_query.return_value = [(42,)]
    game_id = svc.create_game(chat_id=-100123, defendant="Кот Леопольд", crime="украл колбасу")
    assert game_id == 42

def test_get_game_by_chat_returns_none_when_no_game():
    svc = make_service()
    svc.db.execute_query.return_value = []
    result = svc.get_active_game(chat_id=-100123)
    assert result is None
