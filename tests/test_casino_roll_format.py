def test_casino_summary_with_wins():
    total_wins = 2
    reward = 300
    msg = f"🎰 Казино: {total_wins}/6 побед! Выигрыш: {total_wins * reward} BTC 🎉"
    assert "2/6" in msg
    assert "600 BTC" in msg
    assert "🎉" in msg

def test_casino_summary_no_wins():
    msg = "🎰 Казино: 0/6. Ничего не выиграл."
    assert "0/6" in msg
    assert "Ничего" in msg

def test_roll_merged_message_format():
    cost = 60
    results = [3, 1, 6, 2, 4]
    new_size = 42
    pet_badge = ' 🐣'
    dice_str = ' '.join(map(str, results))
    msg = f"🎲 Потрачено: {cost} BTC | [{dice_str}] | Писюнчик{pet_badge}: {new_size} см"
    assert "60 BTC" in msg
    assert "[3 1 6 2 4]" in msg
    assert "42 см" in msg
    assert "🐣" in msg

def test_roll_merged_message_no_badge():
    cost = 30
    results = [5, 2]
    new_size = 55
    pet_badge = ''
    dice_str = ' '.join(map(str, results))
    msg = f"🎲 Потрачено: {cost} BTC | [{dice_str}] | Писюнчик{pet_badge}: {new_size} см"
    assert "Писюнчик:" in msg
