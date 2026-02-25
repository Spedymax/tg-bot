import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from models.player import Player

def test_player_has_pet_hunger_default():
    p = Player(player_id=1, player_name="Test")
    assert p.pet_hunger == 100
    assert p.pet_happiness == 50
    assert p.pet_ulta_free_roll_pending == False
    assert p.pet_ulta_oracle_pending == False
    assert p.pet_ulta_trivia_pending == False
    assert p.pet_casino_extra_spins == 0
    assert p.pet_ulta_oracle_preview is None

from datetime import datetime, timezone, timedelta
from services.pet_service import PetService

def make_player_with_live_pet():
    from models.player import Player
    p = Player(player_id=1, player_name="Test")
    p.pet = {'name': 'X', 'level': 1, 'xp': 0, 'stage': 'egg',
             'is_alive': True, 'is_locked': True,
             'created_at': datetime.now(timezone.utc).isoformat()}
    return p

def test_get_xp_multiplier_normal():
    svc = PetService()
    p = make_player_with_live_pet()
    p.pet_hunger = 70
    p.pet_happiness = 60
    assert svc.get_xp_multiplier(p) == 1.0

def test_get_xp_multiplier_happy_bonus():
    svc = PetService()
    p = make_player_with_live_pet()
    p.pet_hunger = 70
    p.pet_happiness = 85
    assert abs(svc.get_xp_multiplier(p) - 1.2) < 0.001

def test_get_xp_multiplier_hungry_halved():
    svc = PetService()
    p = make_player_with_live_pet()
    p.pet_hunger = 45
    p.pet_happiness = 60
    assert svc.get_xp_multiplier(p) == 0.5

def test_get_xp_multiplier_very_hungry_stopped():
    svc = PetService()
    p = make_player_with_live_pet()
    p.pet_hunger = 20
    p.pet_happiness = 60
    assert svc.get_xp_multiplier(p) == 0.0

def test_hunger_decay_applies_ticks():
    svc = PetService()
    p = make_player_with_live_pet()
    p.pet_hunger = 100
    now = datetime.now(timezone.utc)
    p.pet_hunger_last_decay = now - timedelta(hours=25)  # 2 ticks of 12h
    died = svc.apply_hunger_decay(p, now)
    assert p.pet_hunger == 80
    assert died == False

def test_hunger_decay_kills_pet():
    svc = PetService()
    p = make_player_with_live_pet()
    p.pet_hunger = 5
    now = datetime.now(timezone.utc)
    p.pet_hunger_last_decay = now - timedelta(hours=12)
    died = svc.apply_hunger_decay(p, now)
    assert p.pet_hunger == 0
    assert died == True
    assert p.pet['is_alive'] == False

def test_happiness_decay_applies():
    svc = PetService()
    p = make_player_with_live_pet()
    p.pet_happiness = 70
    now = datetime.now(timezone.utc)
    p.pet_happiness_last_activity = now - timedelta(hours=48)
    svc.apply_happiness_decay(p, now)
    assert p.pet_happiness == 50

def test_record_game_activity_increases_happiness():
    svc = PetService()
    p = make_player_with_live_pet()
    p.pet_happiness = 50
    now = datetime.now(timezone.utc)
    svc.record_game_activity(p, 'trivia', now)
    assert p.pet_happiness == 55
