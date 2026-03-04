# Court Game Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement a 3-player Telegram courtroom party game where an AI judge (OpenClaw) runs the trial, players receive hidden evidence cards via DM, and a dramatic multi-message verdict is delivered after 4 rounds.

**Architecture:** Two new files (`court_service.py` for game logic + AI prompts, `court_handlers.py` for Telegram interactions) backed by two PostgreSQL tables (`court_games`, `court_messages`). Follows the existing `game_service.py + game_handlers.py` pattern. Game state lives in DB; ephemeral wait-states (e.g. "waiting for crime text") live in an in-memory dict on the handler.

**Tech Stack:** pyTelegramBotAPI (telebot), psycopg2, httpx, OpenClaw at `Settings.JARVIS_URL` (OpenAI-compatible API)

---

## Reference: Key existing patterns

**DB query:**
```python
self.db.execute_query("SELECT ...", (param,))
```

**OpenClaw call** (from `moltbot_handlers.py:276`):
```python
import httpx
r = httpx.Client().post(
    Settings.JARVIS_URL,
    headers={"Authorization": f"Bearer {Settings.JARVIS_TOKEN}"},
    json={"model": "openclaw:main", "user": user_key, "messages": [{"role": "user", "content": prompt}]},
    timeout=90,
)
text = r.json()["choices"][0]["message"]["content"]
```

**Handler registration** (from `main.py:55`):
```python
self.court_handlers = CourtHandlers(self.bot, self.db_manager)
# then in setup_handlers():
self.court_handlers.setup_handlers()
```

---

## Task 1: Create DB tables

**Files:**
- Create: `src/database/court_schema.sql`
- Run on server via SSH

**Step 1: Write the SQL**

Create `src/database/court_schema.sql`:
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

**Step 2: Apply schema on the server**

```bash
ssh -i ~/.ssh/mac-max spedymax@192.168.1.35 \
  "psql -U postgres -d server-tg-pisunchik < /home/spedymax/tg-bot/src/database/court_schema.sql"
```

Expected output: `CREATE TABLE` twice, no errors.

**Step 3: Verify tables exist**

```bash
ssh -i ~/.ssh/mac-max spedymax@192.168.1.35 \
  "psql -U postgres -d server-tg-pisunchik -c '\dt court*'"
```

Expected: `court_games` and `court_messages` listed.

**Step 4: Commit**

```bash
git add src/database/court_schema.sql
git commit -m "feat: add court game DB schema"
```

---

## Task 2: court_service.py — skeleton + DB helpers

**Files:**
- Create: `src/services/court_service.py`

**Step 1: Write failing test**

Create `tests/test_court_service.py`:
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

**Step 2: Run to verify it fails**

```bash
cd /home/spedymax/tg-bot
source /home/spedymax/venv/bin/activate
python -m pytest tests/test_court_service.py -v
```

Expected: `ImportError` or `ModuleNotFoundError` — file doesn't exist yet.

**Step 3: Write minimal implementation**

Create `src/services/court_service.py`:
```python
import json
import logging
import httpx
from config.settings import Settings

logger = logging.getLogger(__name__)


class CourtService:
    def __init__(self, db):
        self.db = db

    # ── DB helpers ─────────────────────────────────────────────────────────

    def create_game(self, chat_id: int, defendant: str, crime: str) -> int:
        """Create a new court game row, return its id."""
        rows = self.db.execute_query(
            "INSERT INTO court_games (chat_id, defendant, crime) VALUES (%s, %s, %s) RETURNING id",
            (chat_id, defendant, crime),
        )
        return rows[0][0] if rows else None

    def get_active_game(self, chat_id: int) -> dict | None:
        """Return the active game dict for a chat, or None."""
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
        """Set prosecutor_id / lawyer_id / witness_id."""
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
        """Append played card to played_cards array and decrement cards_left."""
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

**Step 4: Run tests**

```bash
python -m pytest tests/test_court_service.py -v
```

Expected: both tests PASS.

**Step 5: Commit**

```bash
git add src/services/court_service.py tests/test_court_service.py
git commit -m "feat: add CourtService with DB helpers"
```

---

## Task 3: AI prompts in court_service.py

**Files:**
- Modify: `src/services/court_service.py` (add 4 AI methods)

**Step 1: Write failing tests**

Add to `tests/test_court_service.py`:
```python
def test_generate_cards_returns_three_lists():
    svc = make_service()
    # Patch _call_openclaw
    svc._call_openclaw = MagicMock(return_value="""
ПРОКУРОР:
1. Знайдено крихти чіпсів на місці злочину
2. Підозрюваний відмовився від поліграфу
3. Бачили його біля холодильника о 3 ночі
4. На руках виявлено сліди сметани
5. Показання сусідської кішки суперечать алібі
6. Загублений чек з магазину
7. Камера зафіксувала підозрілу ходу
8. Відбитки лап на упаковці
АДВОКАТ:
1. Клієнт страждає на сомнамбулізм
2. Чіпси вже були відкриті
3. У нього алергія на той сорт
4. Свідки не можуть точно визначити час
СВІДОК:
1. Бачив його в іншому місці
2. Холодильник зламаний вже тиждень
3. Інший кіт теж мав мотив
4. Запах не відповідає марці чіпсів
""")
    prosecutor, lawyer, witness = svc.generate_cards(defendant="Кіт", crime="украв чіпси")
    assert len(prosecutor) == 8
    assert len(lawyer) == 4
    assert len(witness) == 4

def test_generate_cards_handles_parse_error():
    svc = make_service()
    svc._call_openclaw = MagicMock(return_value="broken response")
    prosecutor, lawyer, witness = svc.generate_cards(defendant="Кіт", crime="украв чіпси")
    # Should return empty lists on parse error, not raise
    assert isinstance(prosecutor, list)
```

**Step 2: Run to see failures**

```bash
python -m pytest tests/test_court_service.py::test_generate_cards_returns_three_lists -v
```

Expected: `AttributeError` — method doesn't exist.

**Step 3: Add AI methods to court_service.py**

Add at the bottom of the `CourtService` class in `src/services/court_service.py`:

```python
    # ── AI calls ───────────────────────────────────────────────────────────

    def _call_openclaw(self, prompt: str, user_key: str = "court-game") -> str:
        """Call OpenClaw. Returns response text or empty string on error."""
        try:
            with httpx.Client() as client:
                r = client.post(
                    Settings.JARVIS_URL,
                    headers={"Authorization": f"Bearer {Settings.JARVIS_TOKEN}"},
                    json={
                        "model": "openclaw:main",
                        "user": user_key,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                    timeout=90,
                )
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"CourtService: OpenClaw error: {e}")
            return ""

    def generate_cards(self, defendant: str, crime: str) -> tuple[list, list, list]:
        """Ask AI to generate 16 cards. Returns (prosecutor[8], lawyer[4], witness[4])."""
        prompt = f"""Ти — помічник судді. Тебе просять придумати докази/аргументи для судового засідання.

Підсудний: {defendant}
Злочин: {crime}

Придумай 16 карт у такому форматі. Карти мають бути смішними й абсурдними, але реалістичними — такими, з яких можна скласти зв'язну історію. Уникай магії, машин часу та повної нісенітниці. Краще — побутовий гумор.

Відповідай ТІЛЬКИ у такому форматі, без зайвого тексту:

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
СВІДОК:
1. [карта]
2. [карта]
3. [карта]
4. [карта]"""

        raw = self._call_openclaw(prompt, user_key="court-card-gen")
        return self._parse_cards(raw)

    def _parse_cards(self, raw: str) -> tuple[list, list, list]:
        """Parse the structured card response into three lists."""
        try:
            sections = {"ПРОКУРОР": [], "АДВОКАТ": [], "СВІДОК": []}
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
            return sections["ПРОКУРОР"][:8], sections["АДВОКАТ"][:4], sections["СВІДОК"][:4]
        except Exception as e:
            logger.error(f"CourtService: card parse error: {e}\nRaw: {raw}")
            return [], [], []

    def judge_react(self, game_id: int, role: str, card: str, round_num: int) -> str:
        """Short judge reaction after a card is played. Also asks follow-up if weak."""
        history = self.get_session_messages(game_id)
        history_text = "\n".join(f"[{m['role']}] {m['content']}" for m in history[-20:])

        role_ua = {"prosecutor": "Прокурор", "lawyer": "Адвокат", "witness": "Свідок захисту"}[role]
        prompt = f"""Ти — суворий, але театральний суддя на судовому засіданні. Ти не даєш себе маніпулювати і фіксуєш всі суперечності.

Протокол засідання (останні повідомлення):
{history_text}

Зараз {role_ua} зіграв карту: «{card}»

Дай коротку реакцію судді (1-3 речення). Якщо аргумент слабкий або суперечить попередньому — вкажи на це або постав уточнювальне запитання. Якщо сильний — визнай, але стримано. Говори від першої особи як суддя. Відповідай тільки українською."""

        reaction = self._call_openclaw(prompt, user_key=f"court-judge-{game_id}")
        self.log_message(game_id, "judge", reaction, round_num)
        return reaction

    def generate_verdict(self, game_id: int) -> list[str]:
        """Generate the dramatic multi-message verdict. Returns list of 4 message strings."""
        game = self.get_active_game_by_id(game_id)
        messages = self.get_session_messages(game_id)

        played = game["played_cards"]
        prosecution_plays = [p["card"] for p in played if p["role"] == "prosecutor"]
        defense_plays = [p["card"] for p in played if p["role"] in ("lawyer", "witness")]
        protocol = "\n".join(f"[{m['role']}] {m['content']}" for m in messages)

        prompt = f"""Ти — суворий суддя. Засідання завершено. Підсудний: {game['defendant']}. Злочин: {game['crime']}.

Протокол засідання:
{protocol}

Аргументи обвинувачення: {'; '.join(prosecution_plays)}
Аргументи захисту: {'; '.join(defense_plays)}

Винеси вирок у 4 окремих блоках, розділених рядком "---":

Блок 1: Резюме позиції обвинувачення (2-3 речення, посилаючись на конкретні аргументи)
---
Блок 2: Резюме позиції захисту (2-3 речення)
---
Блок 3: Ключові суперечності та спостереження суду (2-3 речення, що вирішили справу)
---
Блок 4: ВИРОК — "ВИНЕН" або "НЕ ВИНЕН" + покарання або виправдання (драматично, 2-4 речення)

Говори від першої особи як суддя. Тільки українська. Будь суворим — один слабкий аргумент не перекреслює сильний."""

        raw = self._call_openclaw(prompt, user_key=f"court-verdict-{game_id}")
        parts = [p.strip() for p in raw.split("---") if p.strip()]
        if len(parts) < 4:
            parts = [raw] + [""] * (4 - len(parts))
        return parts[:4]
```

**Step 4: Run tests**

```bash
python -m pytest tests/test_court_service.py -v
```

Expected: all 4 tests PASS.

**Step 5: Commit**

```bash
git add src/services/court_service.py tests/test_court_service.py
git commit -m "feat: add AI card generation, judge reactions, and verdict to CourtService"
```

---

## Task 4: court_handlers.py — /суд command and game setup

**Files:**
- Create: `src/handlers/court_handlers.py`

**Step 1: Write the handler file**

Create `src/handlers/court_handlers.py`:

```python
import logging
import threading
from telebot import types
from services.court_service import CourtService

logger = logging.getLogger(__name__)

ROLE_NAMES = {
    "prosecutor": "⚔️ Прокурор",
    "lawyer": "🛡️ Адвокат",
    "witness": "👁️ Свідетель захисту",
}

RULES_TEXT = """⚖️ <b>СУДОВЕ ЗАСІДАННЯ ВІДКРИВАЄТЬСЯ</b>

Суд ознайомлює сторони з правилами процесу:

<b>Ролі:</b>
• ⚔️ <b>Прокурор</b> — отримує 8 карт, грає 4. Обвинувачує підсудного.
• 🛡️ <b>Адвокат</b> — отримує 4 карти, грає 2. Захищає підсудного. Бачить карти Свідка.
• 👁️ <b>Свідетель захисту</b> — отримує 4 карти, грає 2. Підтримує захист. Бачить карти Адвоката.

<b>Хід гри:</b>
1. Кожен отримує карти в особисті повідомлення від бота
2. 4 раунди: Прокурор грає карту → захист відповідає
3. Після 4 раундів суддя виносить вирок

<b>Важливо:</b>
— Захист координує стратегію між собою (бачать руки одне одного)
— Суддя фіксує всі суперечності. "Я не так сказав" — не аргумент.
— Підсудним може бути будь-хто: реальна людина, персонаж, кіт Леопольд.

Щоб грати — кожен учасник має написати боту в особисті повідомлення хоча б раз."""


class CourtHandlers:
    def __init__(self, bot, db_manager):
        self.bot = bot
        self.db = db_manager
        self.court_service = CourtService(db_manager)
        # In-memory wait states per chat: chat_id → {'state': str, 'game_id': int, ...}
        self._wait: dict[int, dict] = {}

    def setup_handlers(self):

        @self.bot.message_handler(commands=['суд', 'sud', 'court'])
        def cmd_court(message):
            if message.chat.type == 'private':
                self.bot.reply_to(message, "Ця команда працює тільки в груповому чаті.")
                return
            chat_id = message.chat.id
            existing = self.court_service.get_active_game(chat_id)
            if existing:
                self.bot.reply_to(message, "⚖️ Засідання вже йде! Використай /суд_стоп щоб завершити.")
                return

            self.bot.send_message(chat_id, RULES_TEXT, parse_mode='HTML')
            self.bot.send_message(chat_id, "👤 Кого обвинувачуємо? Напишіть ім'я або опис підсудного (наприклад: «Кіт Леопольд», «Юра з 3-го поверху»):")
            self._wait[chat_id] = {'state': 'waiting_defendant', 'initiator': message.from_user.id}

        @self.bot.message_handler(commands=['суд_стоп', 'sud_stop', 'court_stop'])
        def cmd_court_stop(message):
            chat_id = message.chat.id
            game = self.court_service.get_active_game(chat_id)
            if not game:
                self.bot.reply_to(message, "Активного засідання немає.")
                return
            self.court_service.set_status(game['id'], 'aborted')
            self._wait.pop(chat_id, None)
            self.bot.send_message(chat_id, "⚖️ Засідання достроково припинено.")

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
                    self.bot.reply_to(message, "Введіть ім'я підсудного (до 200 символів).")
                    return
                state_data['defendant'] = defendant
                state_data['state'] = 'waiting_crime'
                self.bot.send_message(chat_id, f"📋 Підсудний: <b>{defendant}</b>\n\nТепер опишіть злочин:", parse_mode='HTML')

            elif state == 'waiting_crime':
                crime = message.text.strip()
                if not crime or len(crime) > 500:
                    self.bot.reply_to(message, "Опишіть злочин (до 500 символів).")
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
        markup.row(types.InlineKeyboardButton("👁️ Свідетель захисту", callback_data=f"court_role:witness:{game_id}"))
        self.bot.send_message(
            chat_id,
            "⚖️ Оберіть роль для участі в засіданні:",
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

            # Check if role already taken
            if role in roles_taken:
                self.bot.answer_callback_query(call.id, "Ця роль вже зайнята!", show_alert=True)
                return
            # Check if user already has a role
            if user_id in roles_taken.values():
                self.bot.answer_callback_query(call.id, "Ти вже обрав роль!", show_alert=True)
                return

            roles_taken[role] = user_id
            state_data['roles_taken'] = roles_taken
            self.court_service.assign_role(game_id, role, user_id)

            # Edit the keyboard to remove taken button
            remaining_roles = [r for r in ("prosecutor", "lawyer", "witness") if r not in roles_taken]
            if remaining_roles:
                markup = types.InlineKeyboardMarkup()
                for r in remaining_roles:
                    markup.row(types.InlineKeyboardButton(ROLE_NAMES[r], callback_data=f"court_role:{r}:{game_id}"))
                self.bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=markup)
            else:
                self.bot.delete_message(chat_id, call.message.message_id)

            role_ua = ROLE_NAMES[role]
            self.bot.send_message(chat_id, f"✅ <b>{user_name}</b> бере роль {role_ua}", parse_mode='HTML')
            self.bot.answer_callback_query(call.id, f"Ти {role_ua}!")

            # All roles filled → start game
            if len(roles_taken) == 3:
                self._wait.pop(chat_id, None)
                threading.Thread(target=self._start_game, args=(chat_id, game_id, roles_taken), daemon=True).start()

        @self.bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("court_play:"))
        def handle_play_card(call):
            # Format: court_play:{game_id}:{role}:{card_index}
            parts = call.data.split(":", 3)
            game_id, role, card_index = int(parts[1]), parts[2], int(parts[3])
            user_id = call.from_user.id

            game = self.court_service.get_active_game_by_id(game_id)
            if not game:
                self.bot.answer_callback_query(call.id, "Гра не знайдена.", show_alert=True)
                return

            # Validate it's this player's turn
            expected_role_id = game[f"{role}_id"]
            if user_id != expected_role_id:
                self.bot.answer_callback_query(call.id, "Зараз не твій хід!", show_alert=True)
                return

            cards_left_key = f"{role}_cards_left"
            if game[cards_left_key] <= 0:
                self.bot.answer_callback_query(call.id, "Ти вже зіграв усі свої карти!", show_alert=True)
                return

            cards_key = f"{role}_cards"
            card_text = game[cards_key][card_index]

            self.bot.answer_callback_query(call.id, "Карту зіграно!")
            # Remove the played card button from DM
            self.bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)

            threading.Thread(
                target=self._process_played_card,
                args=(game_id, game['chat_id'], role, card_text, game['current_round']),
                daemon=True
            ).start()

    def _start_game(self, chat_id: int, game_id: int, roles_taken: dict):
        """Generate cards, send to DMs, start round 1."""
        game = self.court_service.get_active_game_by_id(game_id)
        defendant = game['defendant']
        crime = game['crime']

        self.bot.send_message(chat_id, "⚖️ <b>Склад суду сформовано. Генерую матеріали справи...</b>", parse_mode='HTML')

        prosecutor_cards, lawyer_cards, witness_cards = self.court_service.generate_cards(defendant, crime)

        if not prosecutor_cards:
            self.bot.send_message(chat_id, "❌ Помилка генерації карт. Спробуйте /суд ще раз.")
            self.court_service.set_status(game_id, 'aborted')
            return

        self.court_service.save_cards(game_id, prosecutor_cards, lawyer_cards, witness_cards)
        self.court_service.set_status(game_id, 'in_progress')
        self.court_service.advance_round(game_id, 1)
        self.court_service.log_message(game_id, 'system', f'Справа: {defendant} обвинувачується у «{crime}»')

        # Send cards via DM
        self._send_cards_dm(roles_taken['prosecutor'], game_id, 'prosecutor', prosecutor_cards)
        self._send_cards_dm(roles_taken['lawyer'], game_id, 'lawyer', lawyer_cards, partner_cards=witness_cards, partner_role='witness')
        self._send_cards_dm(roles_taken['witness'], game_id, 'witness', witness_cards, partner_cards=lawyer_cards, partner_role='lawyer')

        self.bot.send_message(
            chat_id,
            f"📬 <b>Карти надіслані в особисті повідомлення.</b>\n\n"
            f"⚖️ <b>Раунд 1 з 4</b>\n"
            f"Слово надається ⚔️ Прокурору. Зіграйте карту у своєму особистому чаті з ботом.",
            parse_mode='HTML'
        )

    def _send_cards_dm(self, user_id: int, game_id: int, role: str, cards: list,
                       partner_cards: list = None, partner_role: str = None):
        """Send player their hand as DM with inline buttons."""
        role_ua = ROLE_NAMES[role]
        text = f"⚖️ <b>Твоя роль: {role_ua}</b>\n\n<b>Твої карти ({len(cards)} шт, граєш {2 if role != 'prosecutor' else 4}):</b>\n"
        for i, card in enumerate(cards, 1):
            text += f"{i}. {card}\n"

        if partner_cards and partner_role:
            partner_ua = ROLE_NAMES[partner_role]
            text += f"\n<b>Карти {partner_ua} (для координації):</b>\n"
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
            logger.error(f"CourtHandlers: failed to send DM to {user_id}: {e}")
            # Notify in group that player needs to start bot in private
            game = self.court_service.get_active_game_by_id(game_id)
            self.bot.send_message(
                game['chat_id'],
                f"⚠️ Не вдалося надіслати карти гравцю. "
                f"Будь ласка, напишіть боту в особисті (@{self._get_bot_username()}) і повторіть /суд."
            )

    def _process_played_card(self, game_id: int, chat_id: int, role: str, card: str, round_num: int):
        """Called after a card is played: announce, log, judge reacts, advance state."""
        role_ua = ROLE_NAMES[role]
        self.bot.send_message(chat_id, f"🃏 <b>{role_ua}</b> грає карту:\n\n«{card}»", parse_mode='HTML')

        self.court_service.record_played_card(game_id, role, card, round_num)
        self.court_service.log_message(game_id, role, card, round_num)

        # Judge reacts
        reaction = self.court_service.judge_react(game_id, role, card, round_num)
        if reaction:
            self.bot.send_message(chat_id, f"⚖️ <i>{reaction}</i>", parse_mode='HTML')

        game = self.court_service.get_active_game_by_id(game_id)

        # Determine next action
        if role == 'prosecutor':
            # Prompt defense to respond
            self.bot.send_message(
                chat_id,
                f"🛡️ <b>Захист може відповісти.</b> Адвокат або Свідетель — зіграйте карту в особистих повідомленнях.\n"
                f"(Адвокат залишилось: {game['lawyer_cards_left']}, Свідетель: {game['witness_cards_left']})",
                parse_mode='HTML'
            )
        else:
            # Defense played — if both prosecutor's card and at least one defense card played this round, advance
            played_this_round = [p for p in game['played_cards'] if p['round'] == round_num]
            has_prosecution = any(p['role'] == 'prosecutor' for p in played_this_round)
            has_defense = any(p['role'] in ('lawyer', 'witness') for p in played_this_round)

            if has_prosecution and has_defense:
                next_round = round_num + 1
                if next_round > 4:
                    # Game over — generate verdict
                    self.bot.send_message(chat_id, "⚖️ <b>Всі раунди завершено. Суд видаляється на нараду...</b>", parse_mode='HTML')
                    self._deliver_verdict(game_id, chat_id)
                else:
                    self.court_service.advance_round(game_id, next_round)
                    self.bot.send_message(
                        chat_id,
                        f"⚖️ <b>Раунд {next_round} з 4</b>\nСлово надається ⚔️ Прокурору.",
                        parse_mode='HTML'
                    )

    def _deliver_verdict(self, game_id: int, chat_id: int):
        """Deliver dramatic multi-message verdict."""
        import time
        parts = self.court_service.generate_verdict(game_id)
        self.court_service.set_status(game_id, 'finished')

        prefixes = [
            "⚖️ <b>Позиція обвинувачення:</b>",
            "🛡️ <b>Позиція захисту:</b>",
            "🔍 <b>Висновки суду:</b>",
            "🔨 <b>ВИРОК:</b>",
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

**Step 2: Commit**

```bash
git add src/handlers/court_handlers.py
git commit -m "feat: add CourtHandlers with full game flow"
```

---

## Task 5: Wire up in main.py

**Files:**
- Modify: `src/main.py`

**Step 1: Add import and initialization**

In `src/main.py`, after the existing handler imports (around line 31):

```python
from handlers.court_handlers import CourtHandlers
```

In `TelegramBot.__init__`, after the `pet_handlers` initialization (around line 73):

```python
self.court_handlers = CourtHandlers(self.bot, self.db_manager)
```

**Step 2: Register handlers**

Find `setup_handlers()` method in `main.py` and add:

```python
self.court_handlers.setup_handlers()
self.court_handlers.setup_callback_handlers()
```

**Step 3: Deploy to server**

```bash
# Push to git
git add src/main.py
git commit -m "feat: register CourtHandlers in main bot"
git push

# Pull and restart on server
ssh -i ~/.ssh/mac-max spedymax@192.168.1.35 \
  "cd /home/spedymax/tg-bot && git pull && echo '123' | sudo -S systemctl restart bot-manager.service"

# Apply DB schema
ssh -i ~/.ssh/mac-max spedymax@192.168.1.35 \
  "psql -U postgres -d server-tg-pisunchik < /home/spedymax/tg-bot/src/database/court_schema.sql"
```

**Step 4: Smoke test**

1. Start a private chat with the bot (to enable DMs)
2. In the group, run `/суд`
3. Bot should reply with rules + ask for defendant
4. Type a defendant name
5. Type a crime
6. See role selection keyboard
7. All 3 players pick roles
8. Each player should receive DM with cards

---

## Known constraints

- Each player must have started a private chat with the bot before playing (Telegram limitation)
- OpenClaw card generation takes ~30s — the "Генерую матеріали справи..." message covers this wait
- Round advancement is simple: prosecutor plays → any defense plays → round ends. If defense has 0 cards left, round auto-advances after prosecutor plays.
- The `court_play` callback validates user_id against the role, so other players can't play each other's cards