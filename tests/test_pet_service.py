import pytest
from unittest.mock import MagicMock
from services.pet_service import PetService

@pytest.fixture
def svc():
    s = PetService.__new__(PetService)
    s.titles = []
    s.xp_thresholds = {'egg_to_baby': 50, 'baby_to_adult': 150, 'adult_to_legendary': 350, 'max_xp': 700}
    s.level_ranges = {}
    s.streak_for_title = 3
    s.max_revives = 5
    return s

def make_player(hunger=100, happiness=50, stage='baby', alive=True, locked=True):
    p = MagicMock()
    p.pet = {'is_alive': alive, 'is_locked': locked, 'stage': stage}
    p.pet_hunger = hunger
    p.pet_happiness = happiness
    return p

def test_badge_no_pet(svc):
    p = MagicMock()
    p.pet = None
    assert svc.get_pet_badge(p) == ''

def test_badge_dead_pet(svc):
    p = make_player(alive=False)
    assert svc.get_pet_badge(p) == ''

def test_badge_unlocked_pet(svc):
    p = make_player(locked=False)
    assert svc.get_pet_badge(p) == ''

def test_badge_healthy_no_label(svc):
    p = make_player(hunger=80, happiness=50)
    assert svc.get_pet_badge(p) == ' 🐣'

def test_badge_hungry(svc):
    p = make_player(hunger=45, happiness=50)
    assert svc.get_pet_badge(p) == ' 🐣 [Голоден 😟]'

def test_badge_very_hungry(svc):
    p = make_player(hunger=20, happiness=50)
    assert svc.get_pet_badge(p) == ' 🐣 [Очень голоден 😫]'

def test_badge_dying(svc):
    p = make_player(hunger=5, happiness=50)
    assert svc.get_pet_badge(p) == ' 🐣 [Умирает! 💀]'

def test_badge_happy(svc):
    p = make_player(hunger=90, happiness=85)
    assert svc.get_pet_badge(p) == ' 🐣 [Счастлив 😊]'

def test_badge_depressed_with_hunger(svc):
    p = make_player(hunger=40, happiness=10)
    badge = svc.get_pet_badge(p)
    assert '[Голоден 😟]' in badge
    assert '[Подавлен]' in badge

def test_badge_egg_stage(svc):
    p = make_player(hunger=80, happiness=50, stage='egg')
    assert svc.get_pet_badge(p) == ' 🥚'

def test_badge_legendary_stage(svc):
    p = make_player(hunger=80, happiness=50, stage='legendary')
    assert svc.get_pet_badge(p) == ' 🦅'

def test_badge_depressed_only_no_hunger(svc):
    """Depressed pet with healthy hunger — only [Подавлен] label."""
    p = make_player(hunger=80, happiness=10)
    badge = svc.get_pet_badge(p)
    assert '[Подавлен]' in badge
    assert '[Голоден' not in badge
