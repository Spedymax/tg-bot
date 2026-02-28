from models.player import Player

def test_player_has_death_pending_notify_field():
    p = Player(player_id=1, player_name='Test')
    assert hasattr(p, 'pet_death_pending_notify')
    assert p.pet_death_pending_notify is False
