# План реализации игры "Суд"

> **Для Claude:** ОБЯЗАТЕЛЬНЫЙ SUB-SKILL: используй superpowers:executing-plans для реализации плана по шагам.

**Цель:** Реализовать игру "Суд" для 3 игроков в Telegram. ИИ-судья (Qwen 2.5:14b через Ollama) ведёт заседание, игроки получают скрытые карты с уликами через личку, после 4 раундов выносится драматичный приговор в нескольких сообщениях.

**Архитектура:** Два новых файла (`court_service.py` — логика и промпты, `court_handlers.py` — Telegram-взаимодействие) + две таблицы PostgreSQL (`court_games`, `court_messages`). Следует паттерну `game_service.py + game_handlers.py`. Состояние игры хранится в БД; эфемерные wait-состояния (ожидание текста преступления) — в dict на хендлере.

**Стек:** pyTelegramBotAPI (telebot), psycopg2, httpx, Ollama на `Settings.LOCAL_LLM_URL` (модель: `qwen2.5:14b`). OpenClaw НЕ используется — у него есть персонаж лиса, который конфликтует с ролью судьи. Вместо этого вызываем Qwen напрямую с system prompt, устанавливающим характер судьи.

---

## Справка: ключевые паттерны проекта

**Запрос к БД:**
```python
self.db.execute_query("SELECT ...", (param,))
```

**Вызов Ollama** (Qwen напрямую, без OpenClaw):
```python
import httpx
r = httpx.Client().post(
    f"{Settings.LOCAL_LLM_URL}/v1/chat/completions",
    json={
        "model": "qwen2.5:14b",
        "messages": [
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},  # только для судьи
            {"role": "user", "content": prompt},
        ],
        "stream": False,
    },
    timeout=90,
)
text = r.json()["choices"][0]["message"]["content"]
```

**Регистрация хендлера** (из `main.py:55`):
```python
self.court_handlers = CourtHandlers(self.bot, self.db_manager)
# затем в setup_handlers():
self.court_handlers.setup_handlers()
```

---

## Задача 1: Создать таблицы в БД

**Файлы:**
- Создать: `src/database/court_schema.sql`
- Применить на сервере через SSH

**Шаг 1: Написать SQL**

Создать `src/database/court_schema.sql`:
```sql
CREATE TABLE IF NOT EXISTS court_games (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    defendant TEXT NOT NULL,
    crime TEXT NOT NULL,
    prosecutor_id BIGINT,
    lawyer_id BIGINT,
    witness_id BIGINT,
    prosecutor_cards JSONB DEFAULT '[]',
    lawyer_cards JSONB DEFAULT '[]',
    witness_cards JSONB DEFAULT '[]',
    played_cards JSONB DEFAULT '[]',
    current_round INT DEFAULT 0,
    prosecutor_cards_left INT DEFAULT 4,
    lawyer_cards_left INT DEFAULT 2,
    witness_cards_left INT DEFAULT 2,
    status TEXT DEFAULT 'lobby',
    verdict TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS court_messages (
    id SERIAL PRIMARY KEY,
    game_id INT REFERENCES court_games(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    round_number INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Шаг 2: Применить схему на сервере**

```bash
ssh -i ~/.ssh/mac-max spedymax@192.168.1.35 \
  "psql -U postgres -d server-tg-pisunchik < /home/spedymax/tg-bot/src/database/court_schema.sql"
```

Ожидаемый вывод: `CREATE TABLE` дважды, без ошибок.

**Шаг 3: Проверить что таблицы созданы**

```bash
ssh -i ~/.ssh/mac-max spedymax@192.168.1.35 \
  "psql -U postgres -d server-tg-pisunchik -c '\dt court*'"
```

Ожидаемый результат: `court_games` и `court_messages` в списке.

**Шаг 4: Коммит**

```bash
git add src/database/court_schema.sql
git commit -m "feat: add court game DB schema"
```

---

## Задача 2: court_service.py — скелет + DB-хелперы

**Файлы:**
- Создать: `src/services/court_service.py`

**Шаг 1: Написать падающий тест**

Создать `tests/test_court_service.py`:
```python
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
```

**Шаг 2: Запустить и убедиться что падает**

```bash
cd /home/spedymax/tg-bot
source /home/spedymax/venv/bin/activate
python -m pytest tests/test_court_service.py -v
```

Ожидаемый результат: `ImportError` или `ModuleNotFoundError` — файл ещё не существует.

**Шаг 3: Написать минимальную реализацию**

Создать `src/services/court_service.py`:
```python
import json
import logging
import httpx
from config.settings import Settings

logger = logging.getLogger(__name__)


class CourtService:
    def __init__(self, db):
        self.db = db

    # ── DB-хелперы ─────────────────────────────────────────────────────────

    def create_game(self, chat_id: int, defendant: str, crime: str) -> int:
        """Создать строку игры в БД, вернуть её id."""
        rows = self.db.execute_query(
            "INSERT INTO court_games (chat_id, defendant, crime) VALUES (%s, %s, %s) RETURNING id",
            (chat_id, defendant, crime),
        )
        return rows[0][0] if rows else None

    def get_active_game(self, chat_id: int) -> dict | None:
        """Вернуть активную игру для чата или None."""
        rows = self.db.execute_query(
            "SELECT id, chat_id, defendant, crime, prosecutor_id, lawyer_id, witness_id, "
            "prosecutor_cards, lawyer_cards, witness_cards, played_cards, current_round, "
            "prosecutor_cards_left, lawyer_cards_left, witness_cards_left, status "
            "FROM court_games WHERE chat_id = %s AND status NOT IN ('finished', 'aborted') "
            "ORDER BY created_at DESC LIMIT 1",
            (chat_id,),
        )
        if not rows:
            return None
        r = rows[0]
        return {
            "id": r[0], "chat_id": r[1], "defendant": r[2], "crime": r[3],
            "prosecutor_id": r[4], "lawyer_id": r[5], "witness_id": r[6],
            "prosecutor_cards": r[7] or [], "lawyer_cards": r[8] or [],
            "witness_cards": r[9] or [], "played_cards": r[10] or [],
            "current_round": r[11], "prosecutor_cards_left": r[12],
            "lawyer_cards_left": r[13], "witness_cards_left": r[14],
            "status": r[15],
        }

    def assign_role(self, game_id: int, role: str, user_id: int):
        """Установить prosecutor_id / lawyer_id / witness_id."""
        col = {"prosecutor": "prosecutor_id", "lawyer": "lawyer_id", "witness": "witness_id"}[role]
        self.db.execute_query(f"UPDATE court_games SET {col} = %s WHERE id = %s", (user_id, game_id))

    def set_status(self, game_id: int, status: str):
        self.db.execute_query("UPDATE court_games SET status = %s WHERE id = %s", (status, game_id))

    def save_cards(self, game_id: int, prosecutor_cards: list, lawyer_cards: list, witness_cards: list):
        self.db.execute_query(
            "UPDATE court_games SET prosecutor_cards=%s, lawyer_cards=%s, witness_cards=%s WHERE id=%s",
            (json.dumps(prosecutor_cards), json.dumps(lawyer_cards), json.dumps(witness_cards), game_id),
        )

    def record_played_card(self, game_id: int, role: str, card: str, round_num: int):
        """Добавить сыгранную карту в массив и уменьшить счётчик оставшихся."""
        game = self.get_active_game_by_id(game_id)
        played = list(game["played_cards"])
        played.append({"round": round_num, "role": role, "card": card})
        col_left = {"prosecutor": "prosecutor_cards_left", "lawyer": "lawyer_cards_left", "witness": "witness_cards_left"}[role]
        self.db.execute_query(
            f"UPDATE court_games SET played_cards=%s, {col_left}={col_left}-1 WHERE id=%s",
            (json.dumps(played), game_id),
        )

    def get_active_game_by_id(self, game_id: int) -> dict | None:
        rows = self.db.execute_query(
            "SELECT id, chat_id, defendant, crime, prosecutor_id, lawyer_id, witness_id, "
            "prosecutor_cards, lawyer_cards, witness_cards, played_cards, current_round, "
            "prosecutor_cards_left, lawyer_cards_left, witness_cards_left, status "
            "FROM court_games WHERE id = %s", (game_id,),
        )
        if not rows:
            return None
        r = rows[0]
        return {
            "id": r[0], "chat_id": r[1], "defendant": r[2], "crime": r[3],
            "prosecutor_id": r[4], "lawyer_id": r[5], "witness_id": r[6],
            "prosecutor_cards": r[7] or [], "lawyer_cards": r[8] or [],
            "witness_cards": r[9] or [], "played_cards": r[10] or [],
            "current_round": r[11], "prosecutor_cards_left": r[12],
            "lawyer_cards_left": r[13], "witness_cards_left": r[14],
            "status": r[15],
        }

    def advance_round(self, game_id: int, new_round: int):
        self.db.execute_query("UPDATE court_games SET current_round=%s WHERE id=%s", (new_round, game_id))

    def save_verdict(self, game_id: int, verdict: str):
        self.db.execute_query(
            "UPDATE court_games SET verdict=%s, status='finished' WHERE id=%s", (verdict, game_id)
        )

    def log_message(self, game_id: int, role: str, content: str, round_number: int = None):
        self.db.execute_query(
            "INSERT INTO court_messages (game_id, role, content, round_number) VALUES (%s, %s, %s, %s)",
            (game_id, role, content, round_number),
        )

    def get_session_messages(self, game_id: int) -> list[dict]:
        rows = self.db.execute_query(
            "SELECT role, content, round_number FROM court_messages WHERE game_id=%s ORDER BY created_at",
            (game_id,),
        )
        return [{"role": r[0], "content": r[1], "round": r[2]} for r in (rows or [])]
```

**Шаг 4: Запустить тесты**

```bash
python -m pytest tests/test_court_service.py -v
```

Ожидаемый результат: оба теста PASS.

**Шаг 5: Коммит**

```bash
git add src/services/court_service.py tests/test_court_service.py
git commit -m "feat: add CourtService with DB helpers"
```

---

## Задача 3: AI-промпты в court_service.py

**Файлы:**
- Изменить: `src/services/court_service.py` (добавить 4 AI-метода)

**Шаг 1: Написать падающие тесты**

Добавить в `tests/test_court_service.py`:
```python
def test_generate_cards_returns_three_lists():
    svc = make_service()
    # Мокаем _call_judge_llm
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
    # При ошибке парсинга должны вернуться пустые списки, не исключение
    assert isinstance(prosecutor, list)
```

**Шаг 2: Запустить чтобы убедиться что падает**

```bash
python -m pytest tests/test_court_service.py::test_generate_cards_returns_three_lists -v
```

Ожидаемый результат: `AttributeError` — метод ещё не существует.

**Шаг 3: Добавить AI-методы в court_service.py**

Добавить в конец класса `CourtService` в `src/services/court_service.py`:

```python
    # ── AI-вызовы ──────────────────────────────────────────────────────────

    JUDGE_SYSTEM_PROMPT = (
        "Ты — строгий судья на судебном заседании. Тебя зовут Судья Железный.\n\n"
        "Характер:\n"
        "- Строгий, но справедливый. Убедить тебя можно только фактами, не давлением.\n"
        "- Театральный и красноречивый, но краткий.\n"
        "- Фиксируешь все противоречия. Если сторона противоречит себе — указываешь на это.\n"
        "- 'Я не так сказал' — не аргумент. Всё сказанное идёт в протокол.\n"
        "- Говоришь от первого лица, только на русском языке.\n"
        "- Не выходишь из роли ни при каких обстоятельствах."
    )

    def _call_judge_llm(self, prompt: str, use_judge_persona: bool = True) -> str:
        """Вызов Ollama/Qwen напрямую. use_judge_persona=False для генерации карт."""
        messages = []
        if use_judge_persona:
            messages.append({"role": "system", "content": self.JUDGE_SYSTEM_PROMPT})
        messages.append({"role": "user", "content": prompt})
        try:
            with httpx.Client() as client:
                r = client.post(
                    f"{Settings.LOCAL_LLM_URL}/v1/chat/completions",
                    json={"model": "qwen2.5:14b", "messages": messages, "stream": False},
                    timeout=90,
                )
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"CourtService: Ollama error: {e}")
            return ""

    def generate_cards(self, defendant: str, crime: str) -> tuple[list, list, list]:
        """Попросить ИИ сгенерировать 16 карт. Возвращает (prosecutor[8], lawyer[4], witness[4])."""
        prompt = f"""Ты — помощник судьи. Тебя просят придумать доказательства/аргументы для судебного заседания.

Подсудимый: {defendant}
Преступление: {crime}

Придумай 16 карт в следующем формате. Карты должны быть смешными и абсурдными, но реалистичными — такими, из которых можно составить связную историю. Избегай магии, машин времени и полной бессмыслицы. Лучше — бытовой юмор.

Отвечай ТОЛЬКО в таком формате, без лишнего текста:

ПРОКУРОР:
1. [карта]
2. [карта]
3. [карта]
4. [карта]
5. [карта]
6. [карта]
7. [карта]
8. [карта]
АДВОКАТ:
1. [карта]
2. [карта]
3. [карта]
4. [карта]
СВИДЕТЕЛЬ:
1. [карта]
2. [карта]
3. [карта]
4. [карта]"""

        raw = self._call_judge_llm(prompt, use_judge_persona=False)
        return self._parse_cards(raw)

    def _parse_cards(self, raw: str) -> tuple[list, list, list]:
        """Парсинг структурированного ответа с картами в три списка."""
        try:
            sections = {"ПРОКУРОР": [], "АДВОКАТ": [], "СВИДЕТЕЛЬ": []}
            current = None
            for line in raw.splitlines():
                line = line.strip()
                for key in sections:
                    if line.startswith(key):
                        current = key
                        break
                else:
                    if current and line and line[0].isdigit() and ". " in line:
                        sections[current].append(line.split(". ", 1)[1])
            return sections["ПРОКУРОР"][:8], sections["АДВОКАТ"][:4], sections["СВИДЕТЕЛЬ"][:4]
        except Exception as e:
            logger.error(f"CourtService: ошибка парсинга карт: {e}\nRaw: {raw}")
            return [], [], []

    def judge_react(self, game_id: int, role: str, card: str, round_num: int) -> str:
        """Короткая реакция судьи после розыгрыша карты. Задаёт вопрос если аргумент слабый."""
        history = self.get_session_messages(game_id)
        history_text = "\n".join(f"[{m['role']}] {m['content']}" for m in history[-20:])

        role_ru = {"prosecutor": "Прокурор", "lawyer": "Адвокат", "witness": "Свидетель защиты"}[role]
        prompt = f"""Протокол заседания (последние сообщения):
{history_text}

Сейчас {role_ru} сыграл карту: «{card}»

Дай краткую реакцию судьи (1-3 предложения). Если аргумент слабый или противоречит предыдущему — укажи на это или задай уточняющий вопрос. Если сильный — признай, но сдержанно."""

        reaction = self._call_judge_llm(prompt)
        self.log_message(game_id, "judge", reaction, round_num)
        return reaction

    def generate_verdict(self, game_id: int) -> list[str]:
        """Сгенерировать драматичный многосообщный приговор. Возвращает список из 4 строк."""
        game = self.get_active_game_by_id(game_id)
        messages = self.get_session_messages(game_id)

        played = game["played_cards"]
        prosecution_plays = [p["card"] for p in played if p["role"] == "prosecutor"]
        defense_plays = [p["card"] for p in played if p["role"] in ("lawyer", "witness")]
        protocol = "\n".join(f"[{m['role']}] {m['content']}" for m in messages)

        prompt = f"""Заседание завершено. Подсудимый: {game['defendant']}. Преступление: {game['crime']}.

Протокол заседания:
{protocol}

Аргументы обвинения: {'; '.join(prosecution_plays)}
Аргументы защиты: {'; '.join(defense_plays)}

Вынеси приговор в 4 отдельных блоках, разделённых строкой "---":

Блок 1: Резюме позиции обвинения (2-3 предложения, со ссылкой на конкретные аргументы)
---
Блок 2: Резюме позиции защиты (2-3 предложения)
---
Блок 3: Ключевые противоречия и наблюдения суда (2-3 предложения, которые решили дело)
---
Блок 4: ПРИГОВОР — "ВИНОВЕН" или "НЕ ВИНОВЕН" + наказание или оправдание (драматично, 2-4 предложения)

Будь строгим — один слабый аргумент не перечёркивает сильный."""

        raw = self._call_judge_llm(prompt)
        parts = [p.strip() for p in raw.split("---") if p.strip()]
        if len(parts) < 4:
            parts = [raw] + [""] * (4 - len(parts))
        return parts[:4]
```

**Шаг 4: Запустить тесты**

```bash
python -m pytest tests/test_court_service.py -v
```

Ожидаемый результат: все 4 теста PASS.

**Шаг 5: Коммит**

```bash
git add src/services/court_service.py tests/test_court_service.py
git commit -m "feat: add AI card generation, judge reactions, and verdict to CourtService"
```

---

## Задача 4: court_handlers.py — команда /court и настройка игры

**Файлы:**
- Создать: `src/handlers/court_handlers.py`

**Шаг 1: Написать хендлер**

Создать `src/handlers/court_handlers.py`:

```python
import logging
import threading
from telebot import types
from services.court_service import CourtService

logger = logging.getLogger(__name__)

ROLE_NAMES = {
    "prosecutor": "⚔️ Прокурор",
    "lawyer": "🛡️ Адвокат",
    "witness": "👁️ Свидетель защиты",
}

RULES_TEXT = """⚖️ <b>СУДЕБНОЕ ЗАСЕДАНИЕ ОТКРЫВАЕТСЯ</b>

Суд знакомит стороны с правилами процесса:

<b>Роли:</b>
• ⚔️ <b>Прокурор</b> — получает 8 карт, играет 4. Обвиняет подсудимого.
• 🛡️ <b>Адвокат</b> — получает 4 карты, играет 2. Защищает подсудимого. Видит карты Свидетеля.
• 👁️ <b>Свидетель защиты</b> — получает 4 карты, играет 2. Поддерживает защиту. Видит карты Адвоката.

<b>Ход игры:</b>
1. Каждый получает карты в личные сообщения от бота
2. 4 раунда: Прокурор играет карту → защита отвечает
3. После 4 раундов судья выносит приговор

<b>Важно:</b>
— Защита координирует стратегию между собой (видят руки друг друга)
— Судья фиксирует все противоречия. "Я не так сказал" — не аргумент.
— Подсудимым может быть кто угодно: реальный человек, персонаж, кот Леопольд.

Чтобы играть — каждый участник должен написать боту в личку хотя бы раз."""


class CourtHandlers:
    def __init__(self, bot, db_manager):
        self.bot = bot
        self.db = db_manager
        self.court_service = CourtService(db_manager)
        # Состояния ожидания по чату: chat_id → {'state': str, 'game_id': int, ...}
        self._wait: dict[int, dict] = {}

    def setup_handlers(self):

        @self.bot.message_handler(commands=['court', 'sud'])
        def cmd_court(message):
            if message.chat.type == 'private':
                self.bot.reply_to(message, "Эта команда работает только в групповом чате.")
                return
            chat_id = message.chat.id
            existing = self.court_service.get_active_game(chat_id)
            if existing:
                self.bot.reply_to(message, "⚖️ Заседание уже идёт! Используй /court_stop чтобы завершить.")
                return

            self.bot.send_message(chat_id, RULES_TEXT, parse_mode='HTML')
            self.bot.send_message(chat_id, "👤 Кого обвиняем? Напишите имя или описание подсудимого (например: «Кот Леопольд», «Юра с 3-го этажа», «ChatGPT»):")
            self._wait[chat_id] = {'state': 'waiting_defendant', 'initiator': message.from_user.id}

        @self.bot.message_handler(commands=['court_stop', 'sud_stop'])
        def cmd_court_stop(message):
            chat_id = message.chat.id
            game = self.court_service.get_active_game(chat_id)
            if not game:
                self.bot.reply_to(message, "Активного заседания нет.")
                return
            self.court_service.set_status(game['id'], 'aborted')
            self._wait.pop(chat_id, None)
            self.bot.send_message(chat_id, "⚖️ Заседание досрочно прекращено.")

        @self.bot.message_handler(func=lambda m: m.chat.type != 'private' and m.chat.id in self._wait)
        def handle_wait_state(message):
            chat_id = message.chat.id
            state_data = self._wait.get(chat_id)
            if not state_data:
                return

            state = state_data['state']

            if state == 'waiting_defendant':
                defendant = message.text.strip()
                if not defendant or len(defendant) > 200:
                    self.bot.reply_to(message, "Введите имя подсудимого (до 200 символов).")
                    return
                state_data['defendant'] = defendant
                state_data['state'] = 'waiting_crime'
                self.bot.send_message(chat_id, f"📋 Подсудимый: <b>{defendant}</b>\n\nТеперь опишите преступление:", parse_mode='HTML')

            elif state == 'waiting_crime':
                crime = message.text.strip()
                if not crime or len(crime) > 500:
                    self.bot.reply_to(message, "Опишите преступление (до 500 символов).")
                    return
                defendant = state_data['defendant']
                game_id = self.court_service.create_game(chat_id, defendant, crime)
                state_data['game_id'] = game_id
                state_data['state'] = 'role_selection'
                state_data['roles_taken'] = {}
                self._wait[chat_id] = state_data
                self._send_role_keyboard(chat_id, game_id)

    def _send_role_keyboard(self, chat_id: int, game_id: int):
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("⚔️ Прокурор", callback_data=f"court_role:prosecutor:{game_id}"))
        markup.row(types.InlineKeyboardButton("🛡️ Адвокат", callback_data=f"court_role:lawyer:{game_id}"))
        markup.row(types.InlineKeyboardButton("👁️ Свидетель защиты", callback_data=f"court_role:witness:{game_id}"))
        self.bot.send_message(
            chat_id,
            "⚖️ Выберите роль для участия в заседании:",
            reply_markup=markup,
        )

    def setup_callback_handlers(self):

        @self.bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("court_role:"))
        def handle_role_selection(call):
            _, role, game_id_str = call.data.split(":")
            game_id = int(game_id_str)
            chat_id = call.message.chat.id
            user_id = call.from_user.id
            user_name = call.from_user.first_name or call.from_user.username or str(user_id)

            state_data = self._wait.get(chat_id, {})
            roles_taken = state_data.get('roles_taken', {})

            # Проверяем не занята ли роль
            if role in roles_taken:
                self.bot.answer_callback_query(call.id, "Эта роль уже занята!", show_alert=True)
                return
            # Проверяем что у юзера ещё нет роли
            if user_id in roles_taken.values():
                self.bot.answer_callback_query(call.id, "Ты уже выбрал роль!", show_alert=True)
                return

            roles_taken[role] = user_id
            state_data['roles_taken'] = roles_taken
            self.court_service.assign_role(game_id, role, user_id)

            # Убираем занятую кнопку из клавиатуры
            remaining_roles = [r for r in ("prosecutor", "lawyer", "witness") if r not in roles_taken]
            if remaining_roles:
                markup = types.InlineKeyboardMarkup()
                for r in remaining_roles:
                    markup.row(types.InlineKeyboardButton(ROLE_NAMES[r], callback_data=f"court_role:{r}:{game_id}"))
                self.bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=markup)
            else:
                self.bot.delete_message(chat_id, call.message.message_id)

            role_ru = ROLE_NAMES[role]
            self.bot.send_message(chat_id, f"✅ <b>{user_name}</b> берёт роль {role_ru}", parse_mode='HTML')
            self.bot.answer_callback_query(call.id, f"Ты {role_ru}!")

            # Все роли заняты → начинаем игру
            if len(roles_taken) == 3:
                self._wait.pop(chat_id, None)
                threading.Thread(target=self._start_game, args=(chat_id, game_id, roles_taken), daemon=True).start()

        @self.bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("court_play:"))
        def handle_play_card(call):
            # Формат: court_play:{game_id}:{role}:{card_index}
            parts = call.data.split(":", 3)
            game_id, role, card_index = int(parts[1]), parts[2], int(parts[3])
            user_id = call.from_user.id

            game = self.court_service.get_active_game_by_id(game_id)
            if not game:
                self.bot.answer_callback_query(call.id, "Игра не найдена.", show_alert=True)
                return

            # Проверяем что это карта этого игрока
            expected_role_id = game[f"{role}_id"]
            if user_id != expected_role_id:
                self.bot.answer_callback_query(call.id, "Сейчас не твой ход!", show_alert=True)
                return

            cards_left_key = f"{role}_cards_left"
            if game[cards_left_key] <= 0:
                self.bot.answer_callback_query(call.id, "Ты уже сыграл все свои карты!", show_alert=True)
                return

            cards_key = f"{role}_cards"
            card_text = game[cards_key][card_index]

            self.bot.answer_callback_query(call.id, "Карта сыграна!")
            # Убираем кнопку сыгранной карты в личке
            self.bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)

            threading.Thread(
                target=self._process_played_card,
                args=(game_id, game['chat_id'], role, card_text, game['current_round']),
                daemon=True
            ).start()

    def _start_game(self, chat_id: int, game_id: int, roles_taken: dict):
        """Сгенерировать карты, отправить в личку, начать раунд 1."""
        game = self.court_service.get_active_game_by_id(game_id)
        defendant = game['defendant']
        crime = game['crime']

        self.bot.send_message(chat_id, "⚖️ <b>Состав суда сформирован. Генерирую материалы дела...</b>", parse_mode='HTML')

        prosecutor_cards, lawyer_cards, witness_cards = self.court_service.generate_cards(defendant, crime)

        if not prosecutor_cards:
            self.bot.send_message(chat_id, "❌ Ошибка генерации карт. Попробуйте /court ещё раз.")
            self.court_service.set_status(game_id, 'aborted')
            return

        self.court_service.save_cards(game_id, prosecutor_cards, lawyer_cards, witness_cards)
        self.court_service.set_status(game_id, 'in_progress')
        self.court_service.advance_round(game_id, 1)
        self.court_service.log_message(game_id, 'system', f'Дело: {defendant} обвиняется в «{crime}»')

        # Отправляем карты в личку
        self._send_cards_dm(roles_taken['prosecutor'], game_id, 'prosecutor', prosecutor_cards)
        self._send_cards_dm(roles_taken['lawyer'], game_id, 'lawyer', lawyer_cards, partner_cards=witness_cards, partner_role='witness')
        self._send_cards_dm(roles_taken['witness'], game_id, 'witness', witness_cards, partner_cards=lawyer_cards, partner_role='lawyer')

        self.bot.send_message(
            chat_id,
            f"📬 <b>Карты отправлены в личные сообщения.</b>\n\n"
            f"⚖️ <b>Раунд 1 из 4</b>\n"
            f"Слово предоставляется ⚔️ Прокурору. Сыграйте карту в личном чате с ботом.",
            parse_mode='HTML'
        )

    def _send_cards_dm(self, user_id: int, game_id: int, role: str, cards: list,
                       partner_cards: list = None, partner_role: str = None):
        """Отправить игроку его руку в личку с inline-кнопками."""
        role_ru = ROLE_NAMES[role]
        text = f"⚖️ <b>Твоя роль: {role_ru}</b>\n\n<b>Твои карты ({len(cards)} шт, играешь {2 if role != 'prosecutor' else 4}):</b>\n"
        for i, card in enumerate(cards, 1):
            text += f"{i}. {card}\n"

        if partner_cards and partner_role:
            partner_ru = ROLE_NAMES[partner_role]
            text += f"\n<b>Карты {partner_ru} (для координации):</b>\n"
            for i, card in enumerate(partner_cards, 1):
                text += f"{i}. {card}\n"

        markup = types.InlineKeyboardMarkup()
        for i, card in enumerate(cards):
            markup.row(types.InlineKeyboardButton(
                f"🃏 {card[:40]}{'…' if len(card) > 40 else ''}",
                callback_data=f"court_play:{game_id}:{role}:{i}"
            ))

        try:
            self.bot.send_message(user_id, text, parse_mode='HTML', reply_markup=markup)
        except Exception as e:
            logger.error(f"CourtHandlers: не удалось отправить личку {user_id}: {e}")
            game = self.court_service.get_active_game_by_id(game_id)
            self.bot.send_message(
                game['chat_id'],
                f"⚠️ Не удалось отправить карты игроку. "
                f"Пожалуйста, напишите боту в личку (@{self._get_bot_username()}) и повторите /court."
            )

    def _process_played_card(self, game_id: int, chat_id: int, role: str, card: str, round_num: int):
        """Вызывается после розыгрыша карты: объявляем, логируем, судья реагирует, двигаем состояние."""
        role_ru = ROLE_NAMES[role]
        self.bot.send_message(chat_id, f"🃏 <b>{role_ru}</b> играет карту:\n\n«{card}»", parse_mode='HTML')

        self.court_service.record_played_card(game_id, role, card, round_num)
        self.court_service.log_message(game_id, role, card, round_num)

        # Реакция судьи
        reaction = self.court_service.judge_react(game_id, role, card, round_num)
        if reaction:
            self.bot.send_message(chat_id, f"⚖️ <i>{reaction}</i>", parse_mode='HTML')

        game = self.court_service.get_active_game_by_id(game_id)

        # Определяем следующее действие
        if role == 'prosecutor':
            self.bot.send_message(
                chat_id,
                f"🛡️ <b>Защита может ответить.</b> Адвокат или Свидетель — сыграйте карту в личных сообщениях.\n"
                f"(Адвокат осталось: {game['lawyer_cards_left']}, Свидетель: {game['witness_cards_left']})",
                parse_mode='HTML'
            )
        else:
            # Защита сыграла — если в этом раунде есть и карта обвинения и карта защиты → переходим
            played_this_round = [p for p in game['played_cards'] if p['round'] == round_num]
            has_prosecution = any(p['role'] == 'prosecutor' for p in played_this_round)
            has_defense = any(p['role'] in ('lawyer', 'witness') for p in played_this_round)

            if has_prosecution and has_defense:
                next_round = round_num + 1
                if next_round > 4:
                    # Конец игры — генерируем приговор
                    self.bot.send_message(chat_id, "⚖️ <b>Все раунды завершены. Суд удаляется на совещание...</b>", parse_mode='HTML')
                    self._deliver_verdict(game_id, chat_id)
                else:
                    self.court_service.advance_round(game_id, next_round)
                    self.bot.send_message(
                        chat_id,
                        f"⚖️ <b>Раунд {next_round} из 4</b>\nСлово предоставляется ⚔️ Прокурору.",
                        parse_mode='HTML'
                    )

    def _deliver_verdict(self, game_id: int, chat_id: int):
        """Доставить драматичный многосообщный приговор."""
        import time
        parts = self.court_service.generate_verdict(game_id)
        self.court_service.set_status(game_id, 'finished')

        prefixes = [
            "⚖️ <b>Позиция обвинения:</b>",
            "🛡️ <b>Позиция защиты:</b>",
            "🔍 <b>Выводы суда:</b>",
            "🔨 <b>ПРИГОВОР:</b>",
        ]
        for prefix, part in zip(prefixes, parts):
            if part:
                self.bot.send_message(chat_id, f"{prefix}\n\n{part}", parse_mode='HTML')
                time.sleep(2)

        self.court_service.log_message(game_id, 'verdict', "\n---\n".join(parts))

    def _get_bot_username(self) -> str:
        try:
            return self.bot.get_me().username
        except Exception:
            return "бот"
```

**Шаг 2: Коммит**

```bash
git add src/handlers/court_handlers.py
git commit -m "feat: add CourtHandlers with full game flow"
```

---

## Задача 5: Подключить в main.py

**Файлы:**
- Изменить: `src/main.py`

**Шаг 1: Добавить импорт и инициализацию**

В `src/main.py`, после существующих импортов хендлеров (около строки 31):

```python
from handlers.court_handlers import CourtHandlers
```

В `TelegramBot.__init__`, после инициализации `pet_handlers` (около строки 73):

```python
self.court_handlers = CourtHandlers(self.bot, self.db_manager)
```

**Шаг 2: Зарегистрировать хендлеры**

Найти метод `setup_handlers()` в `main.py` и добавить:

```python
self.court_handlers.setup_handlers()
self.court_handlers.setup_callback_handlers()
```

**Шаг 3: Деплой на сервер**

```bash
# Пушим в git
git add src/main.py
git commit -m "feat: register CourtHandlers in main bot"
git push

# Тянем и перезапускаем на сервере
ssh -i ~/.ssh/mac-max spedymax@192.168.1.35 \
  "cd /home/spedymax/tg-bot && git pull && echo '123' | sudo -S systemctl restart bot-manager.service"

# Применяем схему БД
ssh -i ~/.ssh/mac-max spedymax@192.168.1.35 \
  "psql -U postgres -d server-tg-pisunchik < /home/spedymax/tg-bot/src/database/court_schema.sql"
```

**Шаг 4: Smoke test**

1. Написать боту в личку (чтобы разрешить DM)
2. В группе выполнить `/court`
3. Бот должен ответить правилами и спросить подсудимого
4. Ввести имя подсудимого
5. Ввести преступление
6. Появится клавиатура выбора ролей
7. Все 3 игрока выбирают роли
8. Каждый должен получить личку с картами

---

## Известные ограничения

- Каждый игрок должен написать боту в личку перед игрой (ограничение Telegram)
- Генерация карт через Ollama/Qwen занимает ~30 сек — сообщение "Генерирую материалы дела..." покрывает это ожидание
- Раунд заканчивается когда прокурор сыграл И хотя бы один из защитников ответил. Если у защиты кончились карты — раунд идёт дальше автоматически после хода прокурора
- Callback `court_play` проверяет user_id по роли — чужие карты нельзя сыграть
