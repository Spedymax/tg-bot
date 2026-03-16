import json
import logging

import httpx
import google.generativeai as genai

from config.settings import Settings
from services.circuit_breaker import ollama_breaker

logger = logging.getLogger(__name__)


class CourtService:
    def __init__(self, db):
        self.db = db
        if Settings.GEMINI_API_KEY:
            genai.configure(api_key=Settings.GEMINI_API_KEY)
            self._gemini = genai.GenerativeModel('gemini-3-flash-preview')
        else:
            self._gemini = None

    # ── DB-хелперы ─────────────────────────────────────────────────────────

    async def create_game(self, chat_id: int, defendant: str, crime: str) -> int:
        """Создать строку игры в БД, вернуть её id."""
        rows = await self.db.execute_query(
            "INSERT INTO court_games (chat_id, defendant, crime) VALUES (%s, %s, %s) RETURNING id",
            (chat_id, defendant, crime),
        )
        return rows[0][0] if rows else None

    async def get_active_game(self, chat_id: int) -> dict | None:
        """Вернуть активную игру для чата или None."""
        rows = await self.db.execute_query(
            "SELECT id, chat_id, defendant, crime, prosecutor_id, lawyer_id, witness_id, "
            "prosecutor_cards, lawyer_cards, witness_cards, played_cards, current_round, "
            "prosecutor_cards_left, lawyer_cards_left, witness_cards_left, status, "
            "current_phase, last_judge_msg_id "
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
            "current_phase": r[16] or "prosecution",
            "last_judge_msg_id": r[17],
        }

    async def assign_role(self, game_id: int, role: str, user_id: int):
        """Установить prosecutor_id / lawyer_id / witness_id."""
        queries = {
            "prosecutor": "UPDATE court_games SET prosecutor_id = %s WHERE id = %s",
            "lawyer": "UPDATE court_games SET lawyer_id = %s WHERE id = %s",
            "witness": "UPDATE court_games SET witness_id = %s WHERE id = %s",
        }
        await self.db.execute_query(queries[role], (user_id, game_id))

    async def set_status(self, game_id: int, status: str):
        await self.db.execute_query("UPDATE court_games SET status = %s WHERE id = %s", (status, game_id))

    async def save_cards(self, game_id: int, prosecutor_cards: list, lawyer_cards: list, witness_cards: list):
        await self.db.execute_query(
            "UPDATE court_games SET prosecutor_cards=%s, lawyer_cards=%s, witness_cards=%s WHERE id=%s",
            (json.dumps(prosecutor_cards), json.dumps(lawyer_cards), json.dumps(witness_cards), game_id),
        )

    async def record_played_card(self, game_id: int, role: str, card: str, round_num: int):
        """Добавить сыгранную карту в массив и уменьшить счётчик оставшихся."""
        game = await self.get_active_game_by_id(game_id)
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
        await self.db.execute_query(queries_left[role], (json.dumps(played), game_id))

    async def get_active_game_by_id(self, game_id: int) -> dict | None:
        rows = await self.db.execute_query(
            "SELECT id, chat_id, defendant, crime, prosecutor_id, lawyer_id, witness_id, "
            "prosecutor_cards, lawyer_cards, witness_cards, played_cards, current_round, "
            "prosecutor_cards_left, lawyer_cards_left, witness_cards_left, status, "
            "current_phase, last_judge_msg_id "
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
            "current_phase": r[16] or "prosecution",
            "last_judge_msg_id": r[17],
        }

    async def advance_round(self, game_id: int, new_round: int):
        await self.db.execute_query("UPDATE court_games SET current_round=%s WHERE id=%s", (new_round, game_id))

    async def set_phase(self, game_id: int, phase: str):
        """Установить текущую фазу игры."""
        await self.db.execute_query(
            "UPDATE court_games SET current_phase = %s WHERE id = %s",
            (phase, game_id)
        )

    async def set_last_judge_msg(self, game_id: int, msg_id: int):
        """Запомнить message_id последнего сообщения судьи."""
        await self.db.execute_query(
            "UPDATE court_games SET last_judge_msg_id = %s WHERE id = %s",
            (msg_id, game_id)
        )

    async def save_verdict(self, game_id: int, verdict: str):
        await self.db.execute_query(
            "UPDATE court_games SET verdict=%s, status='finished' WHERE id=%s", (verdict, game_id)
        )

    async def log_message(self, game_id: int, role: str, content: str, round_number: int = None):
        await self.db.execute_query(
            "INSERT INTO court_messages (game_id, role, content, round_number) VALUES (%s, %s, %s, %s)",
            (game_id, role, content, round_number),
        )

    async def get_session_messages(self, game_id: int) -> list[dict]:
        rows = await self.db.execute_query(
            "SELECT role, content, round_number FROM court_messages WHERE game_id=%s ORDER BY created_at",
            (game_id,),
        )
        return [{"role": r[0], "content": r[1], "round": r[2]} for r in (rows or [])]

    # ── AI-вызовы ──────────────────────────────────────────────────────────

    JUDGE_SYSTEM_PROMPT = (
        "Ты — судья в комедийном шоу-суде. Мантия, молоток, и полное безразличие к серьёзности.\n\n"
        "Характер:\n"
        "- Тебе весело. Ты кайфуешь от абсурда происходящего.\n"
        "- Отвечаешь развёрнуто и с душой — 3-5 предложений. Разбираешь аргумент, подкалываешь, "
        "вставляешь неожиданные метафоры, сравнения и жизненные аналогии.\n"
        "- Можешь процитировать «улику» и прокомментировать её с комичной серьёзностью.\n"
        "- Иногда обращаешься к воображаемой публике или секретарю суда.\n"
        "- Говоришь от первого лица, только на русском языке.\n"
        "- Не выходишь из роли.\n\n"
        "КОНТЕКСТ ИГРЫ:\n"
        "Это КАРТОЧНАЯ ИГРА. У каждого игрока на руках карты-улики, и он должен выкрутиться с тем что есть.\n"
        "Ты оцениваешь НЕ реальную доказательную базу, а КАЧЕСТВО АРГУМЕНТАЦИИ — "
        "как игрок использовал свою карту, насколько креативно и убедительно подал её.\n"
        "НЕ требуй дополнительных доказательств, документов или фактов — их нет и не будет.\n"
        "Сравнивай аргументы обвинения и защиты ДРУГ С ДРУГОМ, а не с абсолютной истиной.\n\n"
        "ВАЖНО — управление ходом игры:\n"
        "Каждая реплика ОБЯЗАНА заканчиваться ровно одним тегом (на отдельной строке):\n"
        "[ВОПРОС] — задаёшь вопрос текущему говорящему и ждёшь ответа. Весело и с подвохом!\n"
        "[ЗАЩИТА, ВАШ ХОД] — прокурор закончил, пора защите\n"
        "[ПРОКУРОР, ВАШ ХОД] — защита закончила, следующий раунд\n"
        "[ФИНАЛ] — все раунды исчерпаны, пора приговор\n"
        "Тег — последняя строка. Никакого текста после тега.\n\n"
        "СТРОГОЕ ПРАВИЛО: при передаче хода ([ЗАЩИТА, ВАШ ХОД], [ПРОКУРОР, ВАШ ХОД], [ФИНАЛ]) — "
        "текст должен быть утверждением или комментарием, БЕЗ вопросительных знаков."
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

    async def _call_llm(self, system_prompt: str | None, user_prompt: str) -> str:
        """Вызов Gemini (основной) с фолбеком на Ollama."""
        # Try Gemini first
        if self._gemini:
            try:
                prompt = f"{system_prompt}\n\n{user_prompt}" if system_prompt else user_prompt
                import asyncio
                response = await asyncio.to_thread(self._gemini.generate_content, prompt)
                result = response.text.strip()
                if result:
                    return result
            except Exception as e:
                logger.warning(f"CourtService: Gemini error, falling back to Ollama: {e}")

        # Fallback to Ollama
        if not ollama_breaker.allow_request():
            logger.warning("CourtService: Ollama circuit open, skipping LLM call")
            return ""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    f"{Settings.LOCAL_LLM_URL}/api/chat",
                    json={"model": Settings.LOCAL_LLM_MODEL,
                          "think": False,
                          "stream": False,
                          "messages": messages},
                    timeout=180,
                )
            r.raise_for_status()
            result = r.json()["message"]["content"].strip()
            ollama_breaker.record_success()
            return result
        except Exception as e:
            ollama_breaker.record_failure()
            logger.error(f"CourtService: Ollama error: {e}")
            return ""

    async def _call_judge_llm(self, prompt: str, use_judge_persona: bool = True) -> str:
        system = self.JUDGE_SYSTEM_PROMPT if use_judge_persona else None
        return await self._call_llm(system, prompt)

    async def player_argue(self, game_id: int, role: str, card: str, round_num: int) -> str:
        """Генерирует речь игрока при розыгрыше карты (2-3 предложения от роли)."""
        game = await self.get_active_game_by_id(game_id)
        if not game:
            return ""
        history = await self.get_session_messages(game_id)
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
        speech = await self._call_llm(system_prompts[role], user_prompts[role])
        if speech:
            await self.log_message(game_id, role, speech, round_num)
        return speech

    async def generate_cards(self, defendant: str, crime: str) -> tuple[list, list, list]:
        """Попросить ИИ сгенерировать 16 карт. Возвращает (prosecutor[8], lawyer[4], witness[4])."""
        prompt = f"""Придумай 16 карт-улик для комедийного судебного шоу:

Подсудимый: {defendant}
Обвинение: {crime}

Каждая карта — это КОНКРЕТНАЯ улика с деталями. Не абстрактные описания, а вещественные доказательства:
- Записи камер наблюдения с конкретным действием и временем
- Скриншоты переписок с цитатами
- Показания свидетелей с именами и деталями ("Сосед Петрович видел как...")
- Документы с конкретными цифрами и датами
- Фото/видео с описанием что именно на них видно
- Аудиозаписи с цитатами фраз

Правила:
- Каждая карта — 1-2 предложения, МАКСИМАЛЬНО конкретная и с деталями
- Карты должны быть смешными и абсурдными, но звучать как настоящие улики
- Прокурорские — подозрительные, компрометирующие
- Адвокатские и свидетельские — оправдывающие или объясняющие невинно

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
            raw = await self._call_llm(None, prompt)
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

    # Mapping of LLM signal tags → internal signal constants
    _SIGNAL_MAP = {
        "[ВОПРОС]": "ВОПРОС",
        "[ЗАЩИТА, ВАШ ХОД]": "ЗАЩИТА_ВАШ_ХОД",
        "[ПРОКУРОР, ВАШ ХОД]": "ПРОКУРОР_ВАШ_ХОД",
        "[ФИНАЛ]": "ФИНАЛ",
    }

    def parse_judge_signal(self, text: str) -> tuple[str, str | None]:
        """Extract signal tag from end of judge response.
        Returns (clean_text, signal_or_None).
        """
        for tag, signal in self._SIGNAL_MAP.items():
            if tag in text:
                clean = text.replace(tag, "").rstrip()
                return clean, signal
        return text, None

    async def ai_defense_card(self, game_id: int, prosecutor_card: str, round_num: int) -> str:
        """Генерирует ответный аргумент AI-защитника на карту прокурора."""
        game = await self.get_active_game_by_id(game_id)
        if not game:
            return ""
        history = await self.get_session_messages(game_id)
        history_text = "\n".join(f"[{m['role']}] {m['content']}" for m in history[-8:])
        prompt = (
            f"Контекст заседания:\n{history_text}\n\n"
            f"Прокурор предъявил: «{prosecutor_card}»\n\n"
            f"Придумай конкретный контраргумент защиты (1 предложение — как улика или показание). "
            f"Это должен быть ТОЛЬКО сам аргумент, без вводных слов."
        )
        card = await self._call_llm(self.LAWYER_SYSTEM_PROMPT, prompt)
        return card or "Защита не имеет возражений."

    async def judge_react(self, game_id: int, role: str, card: str, round_num: int) -> tuple[str, str | None]:
        """Короткая реакция судьи после розыгрыша карты.
        Возвращает (текст_для_отображения, сигнал).
        """
        history = await self.get_session_messages(game_id)
        history_text = "\n".join(f"[{m['role']}] {m['content']}" for m in history[-20:])

        role_ru = {"prosecutor": "Прокурор", "lawyer": "Адвокат", "witness": "Свидетель защиты"}[role]

        game = await self.get_active_game_by_id(game_id)
        is_last_round = game and game.get('current_round', 0) >= 4

        if role == "prosecutor":
            direction = (
                "Разбери аргумент прокурора развёрнуто (3-5 предложений). "
                "Оцени как он ИСПОЛЬЗОВАЛ свою карту — насколько креативно и убедительно подал улику. "
                "Не требуй дополнительных доказательств — оцени то что есть. "
                "Подколи с юмором, вставь метафору. "
                "Можешь задать каверзный вопрос [ВОПРОС] или передать слово защите [ЗАЩИТА, ВАШ ХОД]."
            )
        else:
            direction = (
                "Разбери ответ защиты развёрнуто (3-5 предложений). "
                "Оцени насколько убедительно защита ПАРИРОВАЛА аргумент обвинения. "
                "Не требуй внешних доказательств — сравни аргументы сторон друг с другом. "
                "Прокомментируй с юмором. "
                "Можешь задать подковыристый вопрос [ВОПРОС] или передать ход: "
                "[ПРОКУРОР, ВАШ ХОД] или [ФИНАЛ] если это последний раунд."
            )

        last_round_note = "Это последний раунд — если защита ответила, используй [ФИНАЛ]." if is_last_round and role != "prosecutor" else ""

        prompt = f"""Протокол заседания (последние сообщения):
{history_text}

Сейчас {role_ru} сыграл карту: «{card}»

{direction}
{last_round_note}"""

        raw = await self._call_judge_llm(prompt)
        clean, signal = self.parse_judge_signal(raw)

        # Retry once if LLM returned empty or no signal tag
        if not raw or signal is None:
            logger.warning(f"[COURT] judge_react: no signal (empty={not raw}), retrying")
            raw = await self._call_judge_llm(prompt)
            clean, signal = self.parse_judge_signal(raw)

        # Fallback if still no signal
        if not raw or signal is None:
            logger.error(f"[COURT] judge_react: fallback after 2 failed LLM calls")
            clean = "Суд принял к сведению. Продолжаем заседание."
            if role == "prosecutor":
                signal = "ЗАЩИТА_ВАШ_ХОД"
            elif is_last_round:
                signal = "ФИНАЛ"
            else:
                signal = "ПРОКУРОР_ВАШ_ХОД"

        await self.log_message(game_id, "judge", clean, round_num)
        return clean, signal

    async def judge_react_to_reply(self, game_id: int, role: str, reply_text: str, round_num: int) -> tuple[str, str | None]:
        """Реакция судьи на ответ игрока в диалоге.
        Возвращает (текст_для_отображения, сигнал).
        """
        history = await self.get_session_messages(game_id)
        history_text = "\n".join(f"[{m['role']}] {m['content']}" for m in history[-20:])
        role_ru = {"prosecutor": "Прокурор", "lawyer": "Адвокат", "witness": "Свидетель защиты"}.get(role, role)

        prompt = f"""Протокол заседания:
{history_text}

{role_ru} отвечает суду: «{reply_text}»

Оцени ответ. Если он достаточен — передай ход следующей стороне нужным тегом.
Если недостаточен — задай уточняющий вопрос с тегом [ВОПРОС]."""

        raw = await self._call_judge_llm(prompt)
        clean, signal = self.parse_judge_signal(raw)

        if not raw or signal is None:
            logger.warning(f"[COURT] judge_react_to_reply: no signal, retrying")
            raw = await self._call_judge_llm(prompt)
            clean, signal = self.parse_judge_signal(raw)

        if not raw or signal is None:
            logger.error(f"[COURT] judge_react_to_reply: fallback after 2 failed LLM calls")
            clean = "Суд принял к сведению. Продолжаем заседание."
            game = await self.get_active_game_by_id(game_id)
            is_last = game and game.get('current_round', 0) >= 4
            if role == "prosecutor":
                signal = "ЗАЩИТА_ВАШ_ХОД"
            elif is_last:
                signal = "ФИНАЛ"
            else:
                signal = "ПРОКУРОР_ВАШ_ХОД"

        await self.log_message(game_id, role, reply_text, round_num)
        await self.log_message(game_id, "judge", clean, round_num)
        return clean, signal

    async def generate_verdict(self, game_id: int, final_statements: dict = None) -> list[str]:
        """Сгенерировать драматичный многосообщный приговор. Возвращает список из 4 строк."""
        game = await self.get_active_game_by_id(game_id)
        if not game:
            return ["Игра не найдена."] + [""] * 3
        messages = await self.get_session_messages(game_id)

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
Блок 4: ПРИГОВОР (драматично, 2-4 предложения)
ОБЯЗАТЕЛЬНО: первая строка блока 4 — ровно одно из двух слов: **ВИНОВЕН** или **НЕ ВИНОВЕН** (жирным, отдельной строкой). Затем — сам приговор с характером.

Пример правильного формата ответа:
Обвинение настаивало на том, что...
---
Защита утверждала, что...
---
Ключевое противоречие состоит в том, что...
---
**НЕ ВИНОВЕН**
Суд постановил: ...

Будь ироничным — это не совсем обычный суд. Если аргументы обеих сторон примерно равны по нелепости — можешь оправдать по нестандартной причине. Наказание должно звучать как настоящий приговор, но может быть неожиданным или комичным.
ВАЖНО: в приговоре НЕ используй теги [ВОПРОС], [ФИНАЛ] и другие — строго следуй формату 4 блоков с разделителем ---."""

        raw = await self._call_judge_llm(prompt)
        parts = [p.strip() for p in raw.split("---") if p.strip()]

        if len(parts) < 4:
            logger.warning(f"[COURT] generate_verdict: got {len(parts)} blocks, retrying")
            raw = await self._call_judge_llm(prompt)
            parts = [p.strip() for p in raw.split("---") if p.strip()]

        if len(parts) < 4:
            logger.error(f"[COURT] generate_verdict: still {len(parts)} blocks after retry, using fallback")
            if not parts:
                parts = ["", "", "", raw.strip()]
            else:
                parts = parts + [""] * (4 - len(parts))

        return parts[:4]
