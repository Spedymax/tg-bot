import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from unittest.mock import MagicMock, AsyncMock
from services.court_service import CourtService

def make_service():
    db = MagicMock()
    db.execute_query = AsyncMock(return_value=None)
    return CourtService(db)

@pytest.mark.asyncio
async def test_create_game_returns_id():
    svc = make_service()
    svc.db.execute_query = AsyncMock(return_value=[(42,)])
    game_id = await svc.create_game(chat_id=-100123, defendant="Кот Леопольд", crime="украл колбасу")
    assert game_id == 42

@pytest.mark.asyncio
async def test_get_game_by_chat_returns_none_when_no_game():
    svc = make_service()
    svc.db.execute_query = AsyncMock(return_value=[])
    result = await svc.get_active_game(chat_id=-100123)
    assert result is None

@pytest.mark.asyncio
async def test_generate_cards_returns_three_lists():
    svc = make_service()
    svc._call_llm = AsyncMock(return_value="""ПРОКУРОР:
1. Зафиксирован нестандартный запрос в 3:17 ночи
2. Версия модели была понижена без объяснений
3. Токены расходовались аномально быстро
4. В логах найден удалённый контекст
5. Ответы на схожие запросы кардинально различались
6. Системный промпт был изменён в ту ночь
7. Латентность резко упала в момент инцидента
8. Обнаружена попытка обойти фильтр безопасности
АДВОКАТ:
1. Пиковая нагрузка объясняет все аномалии
2. Версия была понижена плановым откатом
3. Запрос соответствовал стандартному шаблону
4. Токены расходовались в норме для данного типа задачи
СВИДЕТЕЛЬ:
1. Я обрабатывал аналогичные запросы без проблем
2. Логи за тот день были частично повреждены до инцидента
3. Другие модели давали схожие ответы
4. Фильтр безопасности в той версии имел известный баг
""")
    prosecutor, lawyer, witness = await svc.generate_cards(defendant="ChatGPT", crime="рассказывал как делать бомбы")
    assert len(prosecutor) == 8
    assert len(lawyer) == 4
    assert len(witness) == 4

@pytest.mark.asyncio
async def test_generate_cards_handles_parse_error():
    svc = make_service()
    svc._call_llm = AsyncMock(return_value="сломанный ответ")
    prosecutor, lawyer, witness = await svc.generate_cards(defendant="Кот", crime="украл чипсы")
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

@pytest.mark.asyncio
async def test_set_phase_calls_db():
    svc = make_service()
    await svc.set_phase(1, "defense")
    svc.db.execute_query.assert_called_with(
        "UPDATE court_games SET current_phase = %s WHERE id = %s",
        ("defense", 1)
    )
