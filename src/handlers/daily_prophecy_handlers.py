import json
import logging
import os
import random
from zoneinfo import ZoneInfo

import httpx
import google.generativeai as genai
from aiogram import Router

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config.settings import Settings
from services.circuit_breaker import ollama_breaker
from handlers.moltbot_handlers import CHAT_LORE_PATH

logger = logging.getLogger(__name__)

# The `messages.name` column stores whatever Telegram display name was captured at
# the time — "Spatifilum" is a username-style handle, not his real first name, so
# swap it for consistency with how the other two show up (real first names already).
NAME_OVERRIDES = {"Spatifilum": "Юра"}

# chat-lore.md's one entry is about "Эдик Коваленко" / его "торсионные генераторы" /
# "Геническ" — used to detect if it showed up recently so we can cool it down
# (see _lore_used_recently). Matches substrings, so "Генический"/"Геническа" etc. all hit.
LORE_COOLDOWN_KEYWORDS = ("Коваленко", "торсион", "Генич")

# Rotated daily so the delivery voice can't calcify into one predictable template —
# but the CONTENT rule (concrete absurd mini-story with a twist, see EXAMPLE_PROPHECIES)
# is the same regardless of voice.
PROPHET_STYLES = [
    {
        "key": "tarot",
        "voice": (
            "Ты — шарлатан-таролог с рынка, вещающий с театральной самоуверенностью, "
            "постоянно ссылаешься на несуществующие карты и знаки."
        ),
    },
    {
        "key": "data_astrologer",
        "voice": (
            "Ты — псевдонаучный дата-астролог, обожаешь придуманные проценты, графики "
            "и «алгоритмы», говоришь как капризный аналитик."
        ),
    },
    {
        "key": "doom_prophet",
        "voice": (
            "Ты — кладбищенский пророк конца света, мрачный и театрально-библейский, "
            "но с чёрным юмором."
        ),
    },
    {
        "key": "drunk_babka",
        "voice": (
            "Ты — пьяная бабка-гадалка на кухне, путаешься в словах, но метко подкалываешь."
        ),
    },
]

# Rotated independently of PROPHET_STYLES (mix-and-match = way more combinations
# than either list alone) so the same voice doesn't always read the same way.
FORMAT_FLAVORS = [
    {"key": "plain", "instruction": "Обычным текстом, как очень короткий мини-рассказ."},
    {
        "key": "rpg",
        "instruction": (
            "В стиле короткого лога квеста/RPG: можно использовать «Событие», «Дебафф» или "
            "«Опыт», но максимум ОДНУ такую метку на человека."
        ),
    },
    {
        "key": "horoscope",
        "instruction": (
            "В стиле язвительной рубрики гороскопа: по одному новому нелепому знаку на человека, "
            "без реальных знаков зодиака."
        ),
    },
    {
        "key": "rating",
        "instruction": (
            "В стиле короткого рейтинга с разными номинациями, но без одинаковых мест и без "
            "обязательного победителя."
        ),
    },
    {"key": "news", "instruction": "Как три лаконичные срочные новости с сухим издевательским заголовком."},
    {
        "key": "fortune_cookie",
        "instruction": "Как испорченные печенья с предсказаниями: афористично, конкретно и едко.",
    },
    {
        "key": "police_report",
        "instruction": "Как сухая полицейская сводка о нелепом происшествии, с одной убийственной деталью.",
    },
    {
        "key": "weather",
        "instruction": "Как персональный прогноз погоды, где осадки и давление — метафоры конкретного фиаско.",
    },
    {
        "key": "sports",
        "instruction": "Как энергичный спортивный комментарий одного бытового эпизода с итоговым счётом.",
    },
    {
        "key": "tech_support",
        "instruction": "Как лаконичный ответ техподдержки: симптом, причина и бесполезная рекомендация.",
    },
    {
        "key": "classifieds",
        "instruction": "Как абсурдное объявление с рубрикой «отдам», «ищу» или «обменяю», привязанное к событию дня.",
    },
    {
        "key": "court_verdict",
        "instruction": "Как короткий судебный приговор судьбы: обвинение, улика и смешное наказание.",
    },
    {
        "key": "product_review",
        "instruction": "Как едкий отзыв с оценкой от одной до пяти звёзд о предстоящем эпизоде дня.",
    },
    {
        "key": "museum_label",
        "instruction": "Как музейная табличка к будущему позору: название экспоната, материал и краткая история.",
    },
]

# Сфера сюжета НАЗНАЧАЕТСЯ каждому человеку заранее, а не выбирается моделью. Раньше
# whitelist жил одной строкой внутри COMMON_VOICE_RULES ("сон, еда, телефон, погода...") —
# модель стабильно брала оттуда два самых киногеничных пункта: за неделю 20 из 24 пророчеств
# были про выпавший/самоотправивший-что-то телефон, почти все с жирной едой в маршрутке.
# Позитивная инструкция ("твоя сфера — вот эта") держит разнообразие надёжнее любого запрета.
LIFE_DOMAINS = [
    "сон, будильник и утренний подъём",
    "работа/учёба: созвон, дедлайн, начальник, коллеги",
    "поход в аптеку, поликлинику или к врачу",
    "спортзал, бег, попытка заняться собой",
    "подъезд, лифт, домофон, соседи по этажу",
    "курьер и доставка заказа",
    "интернет, wi-fi, роутер, отключение света",
    "деньги: банковское приложение, счёт, подписка, которую забыли отменить",
    "бюрократия: документы, справки, очередь в госучреждении",
    "парикмахерская или барбершоп",
    "уборка, стирка, посуда, ремонт бытовой техники",
    "магазин одежды и примерочная",
    "погода: дождь, ветер, гололёд, жара",
    "домашние животные — свои или чужие",
    "родственники и семейный чат",
    "дота/игры и стримы",
    "случайная встреча со знакомым, которого не хотел видеть",
    "свидание или попытка познакомиться",
    "поездка: такси, поезд, аэропорт, отель",
    "стройка, ремонт в квартире, мастер, который не пришёл",
    "кафе, бар и попытка заказать что-то нормальное",
    "мусор, консьерж, парковка, двор",
    "школьные/студенческие воспоминания, всплывшие некстати",
    "музыка в наушниках и уличные музыканты",
    "спорт по телевизору, ставки, болельщики",
    "попытка починить что-то своими руками",
]

STORY_MODES = [
    {
        "key": "independent",
        "shared_domain": False,
        "instruction": (
            "Три истории СТРОГО НЕЗАВИСИМЫ: не упоминай других участников в чужой строке, "
            "не связывай события причинно и не делай общего победителя."
        ),
    },
    {
        "key": "domino",
        "shared_domain": True,
        "instruction": (
            "Три строки образуют короткую цепочку-домино. Порядок участников указан ниже и "
            "уже перемешан; не превращай последнего в постоянного победителя."
        ),
    },
    {
        "key": "day_parts",
        "shared_domain": False,
        "instruction": (
            "Это три независимых снимка одного дня: первому достаётся утро, второму день, "
            "третьему вечер. Не упоминай участников друг у друга."
        ),
    },
    {
        "key": "shared_place",
        "shared_domain": True,
        "instruction": (
            "Все оказываются в одном месте, но переживают три РАЗНЫХ, не связанных причинно "
            "эпизода. Никто не получает выгоду из чужой неудачи."
        ),
    },
    {
        "key": "expectation_reality",
        "shared_domain": False,
        "instruction": (
            "Каждая строка строится как «ожидание против реальности»: человек планирует одно, "
            "а получает короткий противоположный результат. Истории независимы."
        ),
    },
    {
        "key": "three_times",
        "shared_domain": False,
        "instruction": (
            "Назначь участникам три разные точные отметки времени и покажи по одному независимому "
            "событию в этот момент. Не связывай их между собой."
        ),
    },
    {
        "key": "same_problem",
        "shared_domain": True,
        "instruction": (
            "Все сталкиваются с одной бытовой проблемой, но решают её тремя совершенно разными "
            "способами и получают разные исходы. Между строками нет причинной цепочки."
        ),
    },
    {
        "key": "rumor",
        "shared_domain": True,
        "instruction": (
            "Один безобидный слух проходит через троих и в каждой строке нелепо меняется. "
            "Перемешанный порядок ниже — порядок передачи слуха; финал не обязан быть победой."
        ),
    },
    {
        "key": "object_relay",
        "shared_domain": True,
        "instruction": (
            "Один обычный предмет случайно переходит от первого участника ко второму и третьему, "
            "каждому создавая новый короткий эпизод. Не делай последнего счастливчиком по умолчанию."
        ),
    },
    {
        "key": "parallel_choices",
        "shared_domain": True,
        "instruction": (
            "В одной исходной ситуации каждый выбирает свой вариант действий; покажи три параллельных "
            "альтернативы без встреч и влияния участников друг на друга."
        ),
    },
    {
        "key": "callback",
        "shared_domain": False,
        "instruction": (
            "Каждому возвращается мелкая вещь или поступок из собственного вчерашнего дня, но с "
            "ироничным последствием. Не переносись в далёкое прошлое и не связывай участников."
        ),
    },
    {
        "key": "false_alarm",
        "shared_domain": False,
        "instruction": (
            "Каждый пугается якобы большой проблемы, которая оказывается пустяком; настоящий короткий "
            "подвох приходит сразу после облегчения. Все три истории независимы."
        ),
    },
]

OUTCOME_PATTERNS = ["one_lucky", "everyone_bites", "two_lucky", "ambiguous"]

MAX_PROPHECY_WORDS = 40
MAX_SCENE_WORDS = 25

EXAMPLE_PROPHECIES = (
    "Сегодня ты не сдашь тест и умрёшь в нищете.\n"
    "Сегодня твой босс подойдёт и наступит тебе на ногу, а в качестве извинения повысит "
    "зарплату на 50%.\n"
    "Сегодня в кафе к тебе подойдёт альтушка 10/10, но она разговаривает только на сербском.\n"
    "Сегодня коллеги наконец узнают, почему от тебя вечно пахнет вчерашним, и молча "
    "поставят освежитель воздуха тебе на стол — без единого слова, зато с осуждением во взгляде.\n"
    "Сегодня в парикмахерской тебя пострижут ровно так, как ты просил, — первый раз за пять "
    "лет, и ты полдня будешь ловить своё отражение в каждой витрине.\n"
    "Сегодня ты наконец выспишься по-настоящему, и день покажется процентов на тридцать "
    "менее отвратительным, чем обычно."
)

SCENE_EXAMPLE = (
    "Вы втроём забрели в старый дом в лесу, где в центре комнаты растёт красный гриб — "
    "и явно видно, что кто-то его надкусил, а в углу на табурете сидит древний дед."
)

PROPHECY_HEADER = "ПРОРОООЧЕЕЕЕСТВАААА"

COMMON_VOICE_RULES = (
    " Отвечаешь только на русском, коротко, без вступлений и оправданий. "
    "Это чат друзей с чёрным, токсичным юмором и дружеским подстёбом — не смягчай и не "
    "цензурируй себя, резкая/подколистая шутка почти всегда лучше вежливой. "
    "Каждое пророчество — КОНКРЕТНАЯ мини-история про сегодня из ПРИЗЕМЛЁННОЙ повседневной "
    "жизни, в сфере, назначенной этому человеку ниже. "
    "СТРОГО ЗАПРЕЩЕНО: магия, сверхъестественные существа, инопланетяне, порталы, "
    "говорящие животные, воскрешение мёртвых, конец света в буквальном смысле — никакой "
    "фантастики, только то, что реально могло бы произойти с обычным человеком за день. "
    "Каждое пророчество ОБЯЗАНО иметь острый комедийный поворот, подкол или чёрный юмор — "
    "избегай мягких «и тут случится что-то милое» историй без шипов, это скучно и не смешно. "
    "Баланс удачи и неудачи назначается отдельно ниже — соблюдай его буквально и не сваливайся "
    "по привычке в схему «двое страдают, последний выигрывает». НЕ общие "
    "фразы про судьбу и перемены типа «тебя ждут перемены» — это скучно и запрещено. "
    "НЕ придумывай про человека конкретные факты жизни, которых ты не знаешь и не видишь "
    "в его сообщениях (машина, ипотека, конкретная работа/должность, дети, семейное "
    "положение) — держись универсальных ситуаций, которые подходят почти кому угодно, "
    "внутри той сферы жизни, которая назначена этому человеку ниже. Сюжет ОБЯЗАН "
    "происходить в назначенной сфере, не уводи его в другую. "
    "СТРОГО ЗАПРЕЩЕНЫ (заезжено до состояния мема чата, ищи что угодно другое): касса/"
    "терминал/оплата картой/мелочь на кассе; телефон как главный объект сюжета — выпал, "
    "утонул, сам отправил сообщение/стикер/лайк, разбился экран; жирная еда, которая "
    "пачкает одежду или в которую что-то падает (беляши, творог, бульон, рыба, чебуреки); "
    "маршрутка/автобус как место действия. "
    f"Примеры нужного уровня конкретики, остроты и приземлённости, разного настроения "
    f"(не копируй буквально, придумывай новое):\n{EXAMPLE_PROPHECIES}"
)


class DailyProphecyHandlers:
    def __init__(self, bot, db_manager):
        self.bot = bot
        self.db = db_manager
        if Settings.GEMINI_API_KEY:
            genai.configure(api_key=Settings.GEMINI_API_KEY)
            self._gemini = genai.GenerativeModel('gemini-3-flash-preview')
        else:
            self._gemini = None
        self.router = Router()  # unused for now — reserved for future betting buttons

    # ── LLM ─────────────────────────────────────────────────────────────────

    async def _call_llm(self, system_prompt: str | None, user_prompt: str) -> str:
        """Gemini first, Ollama fallback — same shape as CourtService._call_llm."""
        import asyncio
        if self._gemini:
            try:
                prompt = f"{system_prompt}\n\n{user_prompt}" if system_prompt else user_prompt
                response = await asyncio.to_thread(self._gemini.generate_content, prompt)
                result = response.text.strip()
                if result:
                    return result
            except Exception as e:
                logger.warning(f"DailyProphecy: Gemini error, falling back to Ollama: {e}")

        if not ollama_breaker.allow_request():
            logger.warning("DailyProphecy: Ollama circuit open, skipping LLM call")
            return ""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    f"{Settings.LOCAL_LLM_URL}/api/chat",
                    json={"model": Settings.LOCAL_LLM_MODEL, "think": False, "stream": False, "messages": messages},
                    timeout=180,
                )
            r.raise_for_status()
            result = r.json()["message"]["content"].strip()
            ollama_breaker.record_success()
            return result
        except Exception as e:
            ollama_breaker.record_failure()
            logger.error(f"DailyProphecy: Ollama error: {e}")
            return ""

    @staticmethod
    def _match_name_prefix(clean_line: str, name: str) -> str | None:
        """Returns the text after 'Name:' if clean_line starts with it, or None.
        Some real display names carry trailing punctuation (e.g. "Богдан." from
        their Telegram first name) that the LLM naturally drops when addressing
        them — so also try the prefix with trailing punctuation stripped."""
        candidates = {name, name.rstrip('.,!?').strip()}
        low = clean_line.lower()
        for candidate in candidates:
            prefix = f"{candidate}:".lower()
            if low.startswith(prefix):
                return clean_line[len(prefix):].strip()
        return None

    @classmethod
    def _parse_named_lines(cls, raw: str, names: list[str]) -> dict[str, str]:
        """Defensive line parser: match each line against known roster names rather
        than a generic regex, so odd LLM formatting (bold markers, dashes) doesn't break it."""
        result = {}
        for line in raw.splitlines():
            clean = line.strip().lstrip('-•*0123456789. ').replace('**', '').strip()
            for name in names:
                matched = cls._match_name_prefix(clean, name)
                if matched is not None:
                    result[name] = matched
                    break
        return result

    @classmethod
    def _parse_scene_and_lines(cls, raw: str, names: list[str]) -> tuple[str, dict[str, str]]:
        """Everything before the first recognized 'Name:' line is the intro scene;
        the rest is parsed the same defensive way as _parse_named_lines."""
        lines = raw.splitlines()
        first_name_idx = None
        for i, line in enumerate(lines):
            clean = line.strip().lstrip('-•*0123456789. ').replace('**', '').strip()
            if any(cls._match_name_prefix(clean, name) is not None for name in names):
                first_name_idx = i
                break
        if first_name_idx is None:
            return "", {}
        scene = "\n".join(lines[:first_name_idx]).strip()
        prophecies = cls._parse_named_lines("\n".join(lines[first_name_idx:]), names)
        return scene, prophecies

    # ── DB ──────────────────────────────────────────────────────────────────

    async def _ensure_table(self):
        try:
            await self.db.execute_query(
                "CREATE TABLE IF NOT EXISTS daily_prophecies ("
                "id SERIAL PRIMARY KEY, "
                "chat_id BIGINT NOT NULL, "
                "style TEXT NOT NULL, "
                "prophecies JSONB NOT NULL, "
                "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
                (),
            )
            await self.db.execute_query(
                "ALTER TABLE daily_prophecies "
                "ADD COLUMN IF NOT EXISTS format_key TEXT, "
                "ADD COLUMN IF NOT EXISTS story_mode TEXT, "
                "ADD COLUMN IF NOT EXISTS outcome_key TEXT, "
                "ADD COLUMN IF NOT EXISTS lucky_user_id BIGINT",
                (),
            )
        except Exception as e:
            logger.error(f"DailyProphecy: failed to create table: {e}")

    async def _get_roster(self, chat_id: int) -> list[tuple[int, str]]:
        rows = await self.db.execute_query(
            "SELECT DISTINCT ON (user_id) user_id, name FROM messages "
            "WHERE chat_id = %s AND timestamp > NOW() - INTERVAL '14 days' AND user_id != 0 "
            "ORDER BY user_id, timestamp DESC",
            (chat_id,),
        )
        return [(r[0], NAME_OVERRIDES.get(r[1], r[1] or "Аноним")) for r in (rows or [])]

    async def _get_yesterday_text(self, chat_id: int, user_id: int) -> str:
        """Rolling last-24h window, same simplicity as _send_weekly_analytics's
        rolling 7-day window — avoids calendar-day/timezone boundary edge cases."""
        rows = await self.db.execute_query(
            "SELECT message_text FROM messages WHERE chat_id = %s AND user_id = %s "
            "AND timestamp > NOW() - INTERVAL '1 day' ORDER BY timestamp",
            (chat_id, user_id),
        )
        texts = [r[0] for r in (rows or []) if r[0]]
        return " / ".join(texts) if texts else ""

    def _load_lore(self, chat_id: int) -> str:
        try:
            path = CHAT_LORE_PATH
            if chat_id != Settings.CHAT_IDS['main']:
                stem, ext = os.path.splitext(path)
                path = f"{stem}-{chat_id}{ext}"
            with open(path, encoding="utf-8") as f:
                return f.read().strip()[:2000]
        except Exception:
            return ""

    async def _lore_used_recently(self, chat_id: int, days: int = 5) -> bool:
        """A flat per-day probability can still cluster by bad luck (it hit 3 of the
        last 4 real days and people noticed — "Эдик не отпускает"). This hard-blocks
        lore for a few days after it last actually appeared, on top of the roll."""
        recent = await self._get_recent_prophecy_texts(chat_id, days=days, limit=100)
        return any(kw in t for t in recent for kw in LORE_COOLDOWN_KEYWORDS)

    async def _get_last_style(self, chat_id: int) -> str:
        """doom_prophet came up 6 days out of 8 on a plain random.choice — with only four
        voices that's enough repetition to read as "the bot has one mode"."""
        rows = await self.db.execute_query(
            "SELECT style FROM daily_prophecies WHERE chat_id = %s ORDER BY created_at DESC LIMIT 1",
            (chat_id,),
        )
        return rows[0][0] if rows else ""

    async def _get_recent_generation_meta(self, chat_id: int, limit: int = 5) -> list[dict]:
        rows = await self.db.execute_query(
            "SELECT format_key, story_mode, outcome_key, lucky_user_id, prophecies "
            "FROM daily_prophecies WHERE chat_id = %s ORDER BY created_at DESC LIMIT %s",
            (chat_id, limit),
        )
        result = []
        for format_key, story_mode, outcome_key, lucky_user_id, prophecies in (rows or []):
            # Old rows predate metadata. Their recurring pattern made the last roster
            # member the winner, so use that as a one-time bootstrap hint.
            if lucky_user_id is None and prophecies:
                lucky_user_id = prophecies[-1].get("user_id")
            result.append({
                "format_key": format_key,
                "story_mode": story_mode,
                "outcome_key": outcome_key,
                "lucky_user_id": lucky_user_id,
            })
        return result

    async def _get_recent_prophecy_texts(self, chat_id: int, days: int = 14, limit: int = 45) -> list[str]:
        """Flat list of individual past prophecy lines (not full rows) from the last
        N days, newest first, capped — fed back to the LLM so it stops repeating itself.
        `days` is a trusted internal value (never user input), so it's safe to interpolate
        directly — psycopg's %s placeholder can't sit inside the quoted INTERVAL literal."""
        rows = await self.db.execute_query(
            f"SELECT prophecies FROM daily_prophecies WHERE chat_id = %s "
            f"AND created_at > NOW() - INTERVAL '{int(days)} days' ORDER BY created_at DESC",
            (chat_id,),
        )
        texts = []
        for (prophecies,) in (rows or []):
            for p in prophecies:
                if p.get("text"):
                    texts.append(p["text"])
        return texts[:limit]

    # ── Formatting ──────────────────────────────────────────────────────────

    @staticmethod
    def _build_message(scene: str, prophecies: list[dict]) -> str:
        parts = [f"🕯 <b>{PROPHECY_HEADER}</b> 🕯"]
        if scene:
            parts.append(f"\n<i>{scene}</i>")
        parts.append("\n⋆ ｉ ˚ ✦ ˚ ｉ ⋆")
        for p in prophecies:
            parts.append(f"\n🔮 <b>{p['name']}</b> — {p['text']}")
        return "\n".join(parts)

    @staticmethod
    def _choose_fresh(items: list, recent_keys: list[str], key=lambda item: item):
        """Prefer values absent from the recent window, then at least avoid yesterday's."""
        fresh = [item for item in items if key(item) not in recent_keys]
        if not fresh and recent_keys:
            fresh = [item for item in items if key(item) != recent_keys[0]]
        return random.choice(fresh or items)

    @staticmethod
    def _shorten_text(text: str, max_words: int) -> str:
        words = text.split()
        if len(words) <= max_words:
            return text.strip()
        return " ".join(words[:max_words]).rstrip(" ,;:-") + "…"

    @classmethod
    def _shorten_prophecy(cls, text: str) -> str:
        return cls._shorten_text(text, MAX_PROPHECY_WORDS)

    # ── Generation ────────────────────────────────────────────────────────────

    async def _generate_prophecies(
        self, per_person: list[tuple[int, str, str]], lore: str, recent_texts: list[str] | None = None,
        exclude_style: str = "", generation_history: list[dict] | None = None,
    ) -> tuple[dict, str, list[dict], dict]:
        """Pure LLM-generation step, separated from the DB fetch so tests can feed
        synthetic (user_id, name, yesterday_text) rows without touching real chat history.
        Returns (style, scene_text, prophecies, generation metadata)."""
        pool = [s for s in PROPHET_STYLES if s["key"] != exclude_style] or PROPHET_STYLES
        style = random.choice(pool)
        history = generation_history or []
        format_flavor = self._choose_fresh(
            FORMAT_FLAVORS, [m.get("format_key") for m in history[:5]], key=lambda item: item["key"]
        )
        story_mode = self._choose_fresh(
            STORY_MODES, [m.get("story_mode") for m in history[:4]], key=lambda item: item["key"]
        )
        outcome_key = self._choose_fresh(
            OUTCOME_PATTERNS, [m.get("outcome_key") for m in history[:2]]
        )

        # Shuffle the causal and display order so one roster position does not become
        # the permanent victim, middleman, or winner.
        ordered_people = list(per_person)
        random.shuffle(ordered_people)
        names = [name for _, name, _ in ordered_people]
        if story_mode["shared_domain"]:
            domain_block = (
                f"Сфера жизни — общая для сегодняшних событий: "
                f"{random.choice(LIFE_DOMAINS)}\n\n"
            )
        else:
            domains = (random.sample(LIFE_DOMAINS, len(names)) if len(names) <= len(LIFE_DOMAINS)
                       else random.choices(LIFE_DOMAINS, k=len(names)))
            domain_block = (
                "Сфера жизни на сегодня для каждого — сюжет ОБЯЗАН развернуться именно в ней:\n"
                + "\n".join(f"- {n}: {d}" for n, d in zip(names, domains)) + "\n\n"
            )

        block = "\n".join(
            f"{name}: {text or '(гробовое молчание, вчера не написал ни слова)'}"
            for _, name, text in ordered_people
        )
        history_block = ""
        if recent_texts:
            history_block = (
                "Вот пророчества за последние дни. ВАЖНО: избегай не только точного повтора "
                "текста, но и повтора той же СИТУАЦИИ/СФЕРЫ ЖИЗНИ другими словами — если недавно "
                "уже был, например, сюжет про очередь, про сломанную технику или про случайную "
                "встречу, не делай ещё один такой же под другим соусом, возьми принципиально "
                "другую область жизни:\n" + "\n".join(f"- {t}" for t in recent_texts) + "\n\n"
            )
        recent_lucky_ids = [m.get("lucky_user_id") for m in history if m.get("lucky_user_id")]
        lucky_candidates = [p for p in ordered_people if p[0] not in recent_lucky_ids[:2]] or ordered_people
        lucky_people = []
        if outcome_key == "one_lucky":
            lucky_people = random.sample(lucky_candidates, 1)
            outcome_instruction = (
                f"Распределение исходов: только {lucky_people[0][1]} получает удачный, но смешной исход; "
                "остальные получают разные мелкие неприятности."
            )
        elif outcome_key == "two_lucky":
            first = random.choice(lucky_candidates)
            rest = [p for p in ordered_people if p[0] != first[0]]
            lucky_people = [first, random.choice(rest)]
            outcome_instruction = (
                f"Распределение исходов: у {lucky_people[0][1]} и {lucky_people[1][1]} всё неожиданно "
                "складывается неплохо, но с комедийной ценой; третий получает лёгкую неприятность."
            )
        elif outcome_key == "everyone_bites":
            outcome_instruction = "Распределение исходов: сегодня не везёт всем троим, но каждому совершенно по-разному."
        else:
            outcome_instruction = (
                "Распределение исходов: у всех неоднозначный обмен — что-то приобрёл, что-то потерял; "
                "явного победителя и проигравшего нет."
            )

        lucky_user_id = lucky_people[0][0] if lucky_people else None
        generation_meta = {
            "format_key": format_flavor["key"],
            "story_mode": story_mode["key"],
            "outcome_key": outcome_key,
            "lucky_user_id": lucky_user_id,
        }

        user_prompt = (
            (f"Инсайды и внутренние шутки этого чата (необязательно использовать):\n{lore}\n\n" if lore else "")
            + f"Вот что вчера писал каждый (необязательный контекст для лёгкой персонализации, "
            + f"не обязан быть буквально связан с пророчеством):\n{block}\n\n"
            + history_block
            + domain_block
            + f"Структура выпуска: {story_mode['instruction']}\n"
            + f"{outcome_instruction}\n\n"
            + f"Сначала опиши ОДНИМ предложением до {MAX_SCENE_WORDS} слов загадочную сцену — как вы (трое друзей, "
            + "от второго лица «вы») наткнулись именно сегодня на этого пророка, в обстановке, "
            + "подходящей твоему образу (старый дом в лесу, склеп, кухня, серверная — что угодно "
            + "атмосферное и странное). Вот пример нужного уровня жути и конкретики (не копируй "
            + f"буквально, придумывай новую сцену):\n{SCENE_EXAMPLE}\n\n"
            + f"Потом, после сцены, дай ровно по одному пророчеству на сегодня для каждого из "
            + f"{len(per_person)} человек — конкретный абсурдный сюжет с поворотом, как в примерах "
            + f"выше. Стиль подачи текста пророчеств сегодня: {format_flavor['instruction']}\n\n"
            + f"КРИТИЧЕСКИ ВАЖНО: каждое пророчество — максимум {MAX_PROPHECY_WORDS} слов и максимум "
            + "два коротких предложения. Никаких длинных пояснений, второго поворота или эпилога.\n\n"
            + "Формат ответа СТРОГО такой — сначала сцена (1-2 предложения), потом пустая строка, "
            + "потом построчно пророчества, без другого текста:\n\n<сцена>\n\nИмя: пророчество"
        )

        style_dict, scene, parsed = style, "", {}
        for attempt in range(2):
            raw = await self._call_llm(style["voice"] + COMMON_VOICE_RULES, user_prompt)
            scene, parsed = self._parse_scene_and_lines(raw, names)
            scene = self._shorten_text(scene, MAX_SCENE_WORDS)
            if len(parsed) == len(names):
                break
            logger.warning(f"DailyProphecy: attempt {attempt + 1} parsed {len(parsed)}/{len(names)}, raw={raw[:200]!r}")

        prophecies = [
            {"user_id": uid, "name": name, "text": self._shorten_prophecy(parsed.get(name, ""))}
            for uid, name, _ in ordered_people if name in parsed
        ]
        return style_dict, scene, prophecies, generation_meta

    async def post_daily_prophecy(self, chat_id: int):
        await self._ensure_table()
        try:
            roster = await self._get_roster(chat_id)
            if not roster:
                logger.info("DailyProphecy: empty roster, skipping")
                return

            per_person = []
            any_activity = False
            for user_id, name in roster:
                text = await self._get_yesterday_text(chat_id, user_id)
                if text:
                    any_activity = True
                per_person.append((user_id, name, text))

            if not any_activity:
                logger.info(f"DailyProphecy: nobody said anything yesterday, skipping chat={chat_id}")
                return

            # chat-lore.md currently holds a single running gag ("Эдик Коваленко") —
            # feeding it in on every single run makes the model lean on the one
            # available callback constantly. Offer it rarely, AND only if it hasn't
            # shown up in the last few days — a flat per-day roll alone can still
            # cluster by bad luck (it hit 3 of 4 real days and people noticed).
            lore = ""
            if random.random() < 0.2 and not await self._lore_used_recently(chat_id):
                lore = self._load_lore(chat_id)
            recent_texts = await self._get_recent_prophecy_texts(chat_id)
            generation_history = await self._get_recent_generation_meta(chat_id)
            last_style = await self._get_last_style(chat_id)
            style, scene, prophecies, generation_meta = await self._generate_prophecies(
                per_person, lore, recent_texts, exclude_style=last_style,
                generation_history=generation_history,
            )

            if not prophecies:
                logger.error("DailyProphecy: could not parse any prophecy, skipping post")
                return

            await self.bot.send_message(
                chat_id, self._build_message(scene, prophecies), parse_mode='HTML', disable_notification=True,
            )

            await self.db.execute_query(
                "INSERT INTO daily_prophecies "
                "(chat_id, style, prophecies, format_key, story_mode, outcome_key, lucky_user_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    chat_id, style["key"], json.dumps(prophecies), generation_meta["format_key"],
                    generation_meta["story_mode"], generation_meta["outcome_key"],
                    generation_meta["lucky_user_id"],
                ),
            )
            logger.info(f"DailyProphecy: posted chat={chat_id} style={style['key']} count={len(prophecies)}")
        except Exception as e:
            logger.error(f"DailyProphecy: post_daily_prophecy failed: {e}", exc_info=True)

    # ── Scheduler ───────────────────────────────────────────────────────────

    def start_scheduler(self, chat_id: int):
        tz = ZoneInfo("Europe/Kyiv")
        self._scheduler = AsyncIOScheduler(timezone=tz)
        self._scheduler.add_job(
            self.post_daily_prophecy, CronTrigger(hour=9, minute=30, timezone=tz), args=[chat_id],
        )
        self._scheduler.start()
        logger.info(f"DailyProphecy: scheduler started for chat {chat_id} (post 09:30 Europe/Kyiv, morning-only)")
