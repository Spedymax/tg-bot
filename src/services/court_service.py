import json
import logging

import google.generativeai as genai

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
        queries = {
            "prosecutor": "UPDATE court_games SET prosecutor_id = %s WHERE id = %s",
            "lawyer": "UPDATE court_games SET lawyer_id = %s WHERE id = %s",
            "witness": "UPDATE court_games SET witness_id = %s WHERE id = %s",
        }
        self.db.execute_query(queries[role], (user_id, game_id))

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
        if not game:
            logger.warning(f"Game {game_id} not found in record_played_card")
            return
        played = game.get("played_cards", [])
        if not isinstance(played, list):
            played = []
        played.append({"round": round_num, "role": role, "card": card})
        queries_left = {
            "prosecutor": "UPDATE court_games SET played_cards=%s, prosecutor_cards_left=prosecutor_cards_left-1 WHERE id=%s",
            "lawyer": "UPDATE court_games SET played_cards=%s, lawyer_cards_left=lawyer_cards_left-1 WHERE id=%s",
            "witness": "UPDATE court_games SET played_cards=%s, witness_cards_left=witness_cards_left-1 WHERE id=%s",
        }
        self.db.execute_query(queries_left[role], (json.dumps(played), game_id))

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

    PROSECUTOR_SYSTEM_PROMPT = (
        "Ты — прокурор на судебном заседании. Твоя задача — обвинять.\n"
        "Характер: уверенный, слегка пафосный, иногда преувеличиваешь значимость улик. "
        "Говоришь от первого лица, только на русском. Не выходишь из роли."
    )
    LAWYER_SYSTEM_PROMPT = (
        "Ты — адвокат защиты на судебном заседании. Твоя задача — защищать подсудимого.\n"
        "Характер: дипломатичный, находчивый, всегда найдёшь объяснение даже абсурдной улике. "
        "Говоришь от первого лица, только на русском. Не выходишь из роли."
    )
    WITNESS_SYSTEM_PROMPT = (
        "Ты — свидетель защиты на судебном заседании.\n"
        "Характер: немного нервничаешь, путаешься в деталях, но в целом поддерживаешь защиту. "
        "Говоришь от первого лица, только на русском. Не выходишь из роли."
    )

    def _call_llm(self, system_prompt: str | None, user_prompt: str) -> str:
        """Вызов Gemini с опциональным системным промптом."""
        try:
            genai.configure(api_key=Settings.GEMINI_API_KEY)
            model = genai.GenerativeModel(
                'gemini-2.5-flash-lite',
                system_instruction=system_prompt if system_prompt else None,
            )
            response = model.generate_content(user_prompt)
            return response.text.strip()
        except Exception as e:
            logger.error(f"CourtService: Gemini error: {e}")
            return ""

    def _call_judge_llm(self, prompt: str, use_judge_persona: bool = True) -> str:
        system = self.JUDGE_SYSTEM_PROMPT if use_judge_persona else None
        return self._call_llm(system, prompt)

    def player_argue(self, game_id: int, role: str, card: str, round_num: int) -> str:
        """Генерирует речь игрока при розыгрыше карты (2-3 предложения от роли)."""
        game = self.get_active_game_by_id(game_id)
        if not game:
            return ""
        history = self.get_session_messages(game_id)
        history_text = "\n".join(f"[{m['role']}] {m['content']}" for m in history[-8:])
        defendant = game["defendant"]
        crime = game["crime"]

        system_prompts = {
            "prosecutor": self.PROSECUTOR_SYSTEM_PROMPT,
            "lawyer": self.LAWYER_SYSTEM_PROMPT,
            "witness": self.WITNESS_SYSTEM_PROMPT,
        }
        user_prompts = {
            "prosecutor": (
                f"Контекст заседания:\n{history_text}\n\n"
                f"Ты представляешь улику: «{card}»\n"
                f"Объясни в 2-3 предложениях как эта улика доказывает вину «{defendant}» "
                f"в «{crime}». Будь убедителен и слегка театрален."
            ),
            "lawyer": (
                f"Контекст заседания:\n{history_text}\n\n"
                f"Ты представляешь аргумент защиты: «{card}»\n"
                f"Объясни в 2-3 предложениях как это доказывает невиновность «{defendant}» "
                f"в «{crime}». Будь находчив, даже если связь кажется натянутой."
            ),
            "witness": (
                f"Контекст заседания:\n{history_text}\n\n"
                f"Ты даёшь показания: «{card}»\n"
                f"Расскажи в 2-3 предложениях что именно ты видел или знаешь, "
                f"и почему это говорит в пользу «{defendant}». Можешь немного путаться в деталях."
            ),
        }
        speech = self._call_llm(system_prompts[role], user_prompts[role])
        if speech:
            self.log_message(game_id, role, speech, round_num)
        return speech

    def generate_cards(self, defendant: str, crime: str) -> tuple[list, list, list]:
        """Попросить ИИ сгенерировать 16 карт. Возвращает (prosecutor[8], lawyer[4], witness[4])."""
        prompt = f"""Ты — помощник судьи. Придумай 16 карт для судебной игры.

ВАЖНО: карты НЕ должны напрямую упоминать подсудимого или преступление. Это намеренно — игроки сами будут изобретательно связывать карты с делом, в этом весь прикол.

Карты — это бытовые детали, улики, показания, справки, случайные факты из жизни. Они должны быть:
- Конкретными и правдоподобными ("был замечен в 3 ночи у холодильника соседа", "на телефоне найдены поиски 'как избавиться от запаха'")
- Достаточно универсальными, чтобы их можно было прикрутить к любому делу
- Смешными, но не абсурдными (без машин времени, магии, инопланетян)
- Прокурорские карты — слегка компрометирующие
- Адвокатские и свидетельские — слегка оправдывающие или двусмысленные

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

        for attempt in range(3):
            raw = self._call_llm(None, prompt)
            if not raw:
                logger.warning(f"CourtService: пустой ответ от LLM при генерации карт (попытка {attempt + 1}/3)")
                continue
            p, l, w = self._parse_cards(raw)
            if p and l and w:
                return p, l, w
            logger.warning(f"CourtService: неполный парсинг карт (попытка {attempt + 1}/3), raw: {raw[:200]}")
        logger.error("CourtService: не удалось сгенерировать карты за 3 попытки")
        return [], [], []

    def _parse_cards(self, raw: str) -> tuple[list, list, list]:
        """Парсинг структурированного ответа с картами в три списка."""
        try:
            sections: dict[str, list] = {"ПРОКУРОР": [], "АДВОКАТ": [], "СВИДЕТЕЛЬ": []}
            current = None
            for line in raw.splitlines():
                line = line.strip()
                for key in sections:
                    if line.startswith(key):
                        current = key
                        break
                else:
                    if current and line and line[0].isdigit() and ". " in line:
                        parts = line.split(". ", 1)
                        if len(parts) == 2 and parts[1]:
                            sections[current].append(parts[1])
            return sections["ПРОКУРОР"][:8], sections["АДВОКАТ"][:4], sections["СВИДЕТЕЛЬ"][:4]
        except Exception as e:
            logger.error(f"CourtService: ошибка парсинга карт: {e}\nRaw: {raw}")
            return [], [], []

    def ai_defense_card(self, game_id: int, prosecutor_card: str, round_num: int) -> str:
        """Генерирует ответный аргумент AI-защитника на карту прокурора."""
        game = self.get_active_game_by_id(game_id)
        if not game:
            return ""
        history = self.get_session_messages(game_id)
        history_text = "\n".join(f"[{m['role']}] {m['content']}" for m in history[-8:])
        prompt = (
            f"Контекст заседания:\n{history_text}\n\n"
            f"Прокурор предъявил: «{prosecutor_card}»\n\n"
            f"Придумай конкретный контраргумент защиты (1 предложение — как улика или показание). "
            f"Это должен быть ТОЛЬКО сам аргумент, без вводных слов."
        )
        card = self._call_llm(self.LAWYER_SYSTEM_PROMPT, prompt)
        return card or "Защита не имеет возражений."

    def judge_react(self, game_id: int, role: str, card: str, round_num: int) -> str:
        """Короткая реакция судьи после розыгрыша карты."""
        history = self.get_session_messages(game_id)
        history_text = "\n".join(f"[{m['role']}] {m['content']}" for m in history[-20:])

        role_ru = {"prosecutor": "Прокурор", "lawyer": "Адвокат", "witness": "Свидетель защиты"}[role]

        if role == "prosecutor":
            direction = (
                "Дай реакцию (1-2 предложения), затем ПРЯМО обратись к стороне защиты — "
                "потребуй опровержения, объяснения или конкретного контраргумента."
            )
        else:
            direction = (
                "Дай реакцию (1-2 предложения). Сравни аргумент с позицией обвинения — "
                "есть ли противоречие? Подтверди принятие к сведению или задай уточняющий вопрос."
            )

        prompt = f"""Протокол заседания (последние сообщения):
{history_text}

Сейчас {role_ru} сыграл карту: «{card}»

{direction}"""

        reaction = self._call_judge_llm(prompt)
        self.log_message(game_id, "judge", reaction, round_num)
        return reaction

    def generate_verdict(self, game_id: int, final_statements: dict = None) -> list[str]:
        """Сгенерировать драматичный многосообщный приговор. Возвращает список из 4 строк."""
        game = self.get_active_game_by_id(game_id)
        if not game:
            return ["Игра не найдена."] + [""] * 3
        messages = self.get_session_messages(game_id)

        played = game["played_cards"]
        prosecution_plays = [p["card"] for p in played if p["role"] == "prosecutor"]
        defense_plays = [p["card"] for p in played if p["role"] in ("lawyer", "witness")]
        protocol = "\n".join(f"[{m['role']}] {m['content']}" for m in messages)

        final_section = ""
        if final_statements:
            lines = []
            for role, text in final_statements.items():
                role_ru = {"prosecutor": "Прокурор", "lawyer": "Адвокат", "witness": "Свидетель"}.get(role, role)
                if text:
                    lines.append(f"{role_ru}: «{text}»")
            if lines:
                final_section = "\n\nФинальные слова сторон:\n" + "\n".join(lines)

        prompt = f"""Заседание завершено. Подсудимый: {game['defendant']}. Преступление: {game['crime']}.

Протокол заседания:
{protocol}

Аргументы обвинения: {'; '.join(prosecution_plays)}
Аргументы защиты: {'; '.join(defense_plays)}{final_section}

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
            parts = parts + [""] * (4 - len(parts))
        return parts[:4]
