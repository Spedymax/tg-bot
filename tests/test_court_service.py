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

def test_generate_cards_returns_three_lists():
    svc = make_service()
    svc._call_judge_llm = MagicMock(return_value="""
ПРОКУРОР:
1. Найдены крошки чипсов на месте преступления
2. Подозреваемый отказался от полиграфа
3. Его видели у холодильника в 3 ночи
4. На руках обнаружены следы сметаны
5. Показания соседской кошки противоречат алиби
6. Потерян чек из магазина
7. Камера зафиксировала подозрительную походку
8. Отпечатки лап на упаковке
АДВОКАТ:
1. Клиент страдает лунатизмом
2. Чипсы уже были открыты
3. У него аллергия на этот сорт
4. Свидетели не могут точно установить время
СВИДЕТЕЛЬ:
1. Видел его в другом месте
2. Холодильник сломан уже неделю
3. Другой кот тоже имел мотив
4. Запах не соответствует марке чипсов
""")
    prosecutor, lawyer, witness = svc.generate_cards(defendant="Кот", crime="украл чипсы")
    assert len(prosecutor) == 8
    assert len(lawyer) == 4
    assert len(witness) == 4

def test_generate_cards_handles_parse_error():
    svc = make_service()
    svc._call_judge_llm = MagicMock(return_value="сломанный ответ")
    prosecutor, lawyer, witness = svc.generate_cards(defendant="Кот", crime="украл чипсы")
    assert isinstance(prosecutor, list)
    assert isinstance(lawyer, list)
    assert isinstance(witness, list)

def test_parse_judge_signal_extracts_defense_tag():
    svc = make_service()
    text = "Суд принял к сведению. Весьма любопытно.\n[ЗАЩИТА, ВАШ ХОД]"
    clean, signal = svc.parse_judge_signal(text)
    assert signal == "ЗАЩИТА_ВАШ_ХОД"
    assert "[ЗАЩИТА, ВАШ ХОД]" not in clean
    assert "Суд принял" in clean

def test_parse_judge_signal_question():
    svc = make_service()
    text = "Чем докажете это заявление?\n[ВОПРОС]"
    clean, signal = svc.parse_judge_signal(text)
    assert signal == "ВОПРОС"
    assert "[ВОПРОС]" not in clean

def test_parse_judge_signal_no_tag():
    svc = make_service()
    text = "Суд принял к сведению."
    clean, signal = svc.parse_judge_signal(text)
    assert signal is None
    assert clean == text

def test_parse_judge_signal_final():
    svc = make_service()
    text = "Все аргументы заслушаны.\n[ФИНАЛ]"
    clean, signal = svc.parse_judge_signal(text)
    assert signal == "ФИНАЛ"
    assert "[ФИНАЛ]" not in clean

def test_set_phase_calls_db():
    svc = make_service()
    svc.set_phase(1, "defense")
    svc.db.execute_query.assert_called_with(
        "UPDATE court_games SET current_phase = %s WHERE id = %s",
        ("defense", 1)
    )
