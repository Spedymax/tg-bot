import json
import logging
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

EXAMPLE_PROPHECIES = (
    "Сегодня ты не сдашь тест и умрёшь в нищете.\n"
    "Сегодня твой босс подойдёт и наступит тебе на ногу, а в качестве извинения повысит "
    "зарплату на 50%.\n"
    "Сегодня в кафе к тебе подойдёт альтушка 10/10, но она разговаривает только на сербском.\n"
    "Сегодня тебе наконец ответят на то сообщение, которое ты писал три дня назад — да ещё "
    "и с извинениями за молчание.\n"
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
    "Каждое пророчество — КОНКРЕТНАЯ мини-история про сегодня из ПРИЗЕМЛЁННОЙ повседневной "
    "жизни: работа, транспорт, кафе, семья, телефон, соседи, погода, очередь в магазине. "
    "СТРОГО ЗАПРЕЩЕНО: магия, сверхъестественные существа, инопланетяне, порталы, "
    "говорящие животные, воскрешение мёртвых, конец света в буквальном смысле — никакой "
    "фантастики, только то, что реально могло бы произойти с обычным человеком за день. "
    "Не каждое пророчество обязано быть ироничным или с подвохом — часть пусть будет "
    "просто хорошими новостями без иронии, для разнообразия (см. примеры 4-5). НЕ общие "
    "фразы про судьбу и перемены типа «тебя ждут перемены» — это скучно и запрещено. "
    "НЕ придумывай про человека конкретные факты жизни, которых ты не знаешь и не видишь "
    "в его сообщениях (машина, ипотека, конкретная работа/должность, дети, семейное "
    "положение) — используй только универсальные повседневные ситуации, которые подходят "
    "почти кому угодно: сон, еда, телефон/переписка, погода, настроение, случайные встречи, "
    "транспорт (метро/маршрутка/автобус, не личная машина), очереди, соседи. "
    f"Примеры нужного уровня конкретики и приземлённости, разного настроения "
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
        except Exception as e:
            logger.error(f"DailyProphecy: failed to create table: {e}")

    async def _get_roster(self) -> list[tuple[int, str]]:
        rows = await self.db.execute_query(
            "SELECT DISTINCT ON (user_id) user_id, name FROM messages "
            "WHERE timestamp > NOW() - INTERVAL '14 days' AND user_id != 0 "
            "ORDER BY user_id, timestamp DESC",
            (),
        )
        return [(r[0], NAME_OVERRIDES.get(r[1], r[1] or "Аноним")) for r in (rows or [])]

    async def _get_yesterday_text(self, user_id: int) -> str:
        """Rolling last-24h window, same simplicity as _send_weekly_analytics's
        rolling 7-day window — avoids calendar-day/timezone boundary edge cases."""
        rows = await self.db.execute_query(
            "SELECT message_text FROM messages WHERE user_id = %s "
            "AND timestamp > NOW() - INTERVAL '1 day' ORDER BY timestamp",
            (user_id,),
        )
        texts = [r[0] for r in (rows or []) if r[0]]
        return " / ".join(texts) if texts else ""

    def _load_lore(self) -> str:
        try:
            with open(CHAT_LORE_PATH, encoding="utf-8") as f:
                return f.read().strip()[:2000]
        except Exception:
            return ""

    async def _get_recent_prophecy_texts(self, chat_id: int, days: int = 14, limit: int = 20) -> list[str]:
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

    # ── Generation ────────────────────────────────────────────────────────────

    async def _generate_prophecies(
        self, per_person: list[tuple[int, str, str]], lore: str, recent_texts: list[str] | None = None,
    ) -> tuple[dict, str, list[dict]]:
        """Pure LLM-generation step, separated from the DB fetch so tests can feed
        synthetic (user_id, name, yesterday_text) rows without touching real chat history.
        Returns (style, scene_text, prophecies)."""
        style = random.choice(PROPHET_STYLES)
        names = [name for _, name, _ in per_person]

        block = "\n".join(
            f"{name}: {text or '(гробовое молчание, вчера не написал ни слова)'}"
            for _, name, text in per_person
        )
        history_block = ""
        if recent_texts:
            history_block = (
                "Вот пророчества за последние дни — НЕ повторяй эти сюжеты и близкие к ним идеи, "
                "придумай принципиально новые:\n" + "\n".join(f"- {t}" for t in recent_texts) + "\n\n"
            )
        user_prompt = (
            (f"Инсайды и внутренние шутки этого чата (необязательно использовать):\n{lore}\n\n" if lore else "")
            + f"Вот что вчера писал каждый (необязательный контекст для лёгкой персонализации, "
            + f"не обязан быть буквально связан с пророчеством):\n{block}\n\n"
            + history_block
            + "Сначала опиши в 1-2 предложениях загадочную сцену — как вы (трое друзей, "
            + "от второго лица «вы») наткнулись именно сегодня на этого пророка, в обстановке, "
            + "подходящей твоему образу (старый дом в лесу, склеп, кухня, серверная — что угодно "
            + "атмосферное и странное). Вот пример нужного уровня жути и конкретики (не копируй "
            + f"буквально, придумывай новую сцену):\n{SCENE_EXAMPLE}\n\n"
            + f"Потом, после сцены, дай ровно по одному пророчеству на сегодня для каждого из "
            + f"{len(per_person)} человек — конкретный абсурдный сюжет с поворотом, как в примерах "
            + f"выше.\n\n"
            + "Формат ответа СТРОГО такой — сначала сцена (1-2 предложения), потом пустая строка, "
            + "потом построчно пророчества, без другого текста:\n\n<сцена>\n\nИмя: пророчество"
        )

        style_dict, scene, parsed = style, "", {}
        for attempt in range(2):
            raw = await self._call_llm(style["voice"] + COMMON_VOICE_RULES, user_prompt)
            scene, parsed = self._parse_scene_and_lines(raw, names)
            if len(parsed) == len(names):
                break
            logger.warning(f"DailyProphecy: attempt {attempt + 1} parsed {len(parsed)}/{len(names)}, raw={raw[:200]!r}")

        prophecies = [
            {"user_id": uid, "name": name, "text": parsed.get(name, "")}
            for uid, name, _ in per_person if name in parsed
        ]
        return style_dict, scene, prophecies

    async def post_daily_prophecy(self, chat_id: int):
        await self._ensure_table()
        try:
            roster = await self._get_roster()
            if not roster:
                logger.info("DailyProphecy: empty roster, skipping")
                return

            per_person = []
            any_activity = False
            for user_id, name in roster:
                text = await self._get_yesterday_text(user_id)
                if text:
                    any_activity = True
                per_person.append((user_id, name, text))

            if not any_activity:
                logger.info(f"DailyProphecy: nobody said anything yesterday, skipping chat={chat_id}")
                return

            # chat-lore.md currently holds a single running gag ("Эдик Коваленко") —
            # feeding it in on every single run makes the model lean on the one
            # available callback constantly. Only offer it some of the time so it
            # stays a rare treat instead of a daily crutch.
            lore = self._load_lore() if random.random() < 0.3 else ""
            recent_texts = await self._get_recent_prophecy_texts(chat_id)
            style, scene, prophecies = await self._generate_prophecies(per_person, lore, recent_texts)

            if not prophecies:
                logger.error("DailyProphecy: could not parse any prophecy, skipping post")
                return

            await self.bot.send_message(chat_id, self._build_message(scene, prophecies), parse_mode='HTML')

            await self.db.execute_query(
                "INSERT INTO daily_prophecies (chat_id, style, prophecies) VALUES (%s, %s, %s)",
                (chat_id, style["key"], json.dumps(prophecies)),
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
