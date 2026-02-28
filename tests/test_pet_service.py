import pytest
from unittest.mock import MagicMock
from datetime import datetime, timezone, timedelta
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


def test_cooldown_none_when_never_used(svc):
    p = make_player()
    p.pet_ulta_used_date = None
    p.pet_happiness = 50
    assert svc.get_ulta_cooldown_remaining(p) is None


def test_cooldown_returns_timedelta_when_active(svc):
    p = make_player()
    p.pet_happiness = 50
    p.pet_ulta_used_date = datetime.now(timezone.utc) - timedelta(hours=10)
    remaining = svc.get_ulta_cooldown_remaining(p)
    assert remaining is not None
    assert 0 < remaining.total_seconds() < 14 * 3600


def test_cooldown_none_when_expired(svc):
    p = make_player()
    p.pet_happiness = 50
    p.pet_ulta_used_date = datetime.now(timezone.utc) - timedelta(hours=25)
    assert svc.get_ulta_cooldown_remaining(p) is None


def test_cooldown_48h_when_depressed(svc):
    p = make_player(happiness=10)
    p.pet_ulta_used_date = datetime.now(timezone.utc) - timedelta(hours=25)
    remaining = svc.get_ulta_cooldown_remaining(p)
    assert remaining is not None  # 48h cooldown, only 25h elapsed
    assert remaining.total_seconds() > 0


def test_death_sets_notify_flag(svc):
    p = make_player(hunger=10)
    p.pet_hunger = 10
    p.pet_death_pending_notify = False
    p.pet_hunger_last_decay = datetime.now(timezone.utc) - timedelta(hours=13)
    died = svc.apply_hunger_decay(p, datetime.now(timezone.utc))
    assert died is True
    assert p.pet['is_alive'] is False
    assert p.pet_death_pending_notify is True
