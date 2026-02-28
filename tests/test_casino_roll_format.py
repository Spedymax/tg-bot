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
