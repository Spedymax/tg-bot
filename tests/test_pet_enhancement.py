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
