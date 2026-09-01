#!/usr/bin/env python3
"""
Daily Wordle-style game, posted once to the group chat and played in the mini-app.
Actual guessing happens server-side in the Flask mini-app (miniapp/app.py), which
uses the same services.wordle_logic helpers to score guesses and rebuild the shared
results message. This handler only owns the daily posting schedule and the
/wordle status command — it never scores a guess itself.
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config.settings import Settings
from services.wordle_logic import build_message_text, word_for_date

logger = logging.getLogger(__name__)


class WordleHandlers:
    def __init__(self, bot, db_manager):
        self.bot = bot
        self.db = db_manager
        self.router = Router()
        self._scheduler = None
        self._register()

    def _register(self):
        @self.router.message(CommandStart(deep_link=True))
        async def wordle_deep_link(message: Message, command: CommandObject):
            # web_app buttons only work in private chats, so the group post links here
            # instead (?start=wordle) — this handler fires once Telegram opens the
            # resulting private chat, where the real web_app button is valid.
            if command.args != 'wordle':
                return
            await message.answer(
                "🟩🟨⬜ Открывай и угадывай сегодняшнее слово!",
                reply_markup=self._build_markup(private=True),
            )

        @self.router.message(Command('wordle'))
        async def wordle_status(message: Message):
            tz = ZoneInfo("Europe/Kyiv")
            today = datetime.now(tz).date()
            row = await self.db.execute_query("SELECT word FROM wordle_daily WHERE date = %s", (today,))
            if not row:
                await message.reply("Вордль дня ещё не готов, загляни после 10:00 🌅")
                return
            private = message.chat.type == 'private'
            await message.reply("🟩🟨⬜ Сегодняшний Wordle уже в игре!", reply_markup=self._build_markup(private=private))

        @self.router.message(Command('wordle_test'))
        async def wordle_test(message: Message):
            if message.from_user.id not in Settings.ADMIN_IDS:
                return
            text = (
                "🧪 Тестовый Wordle — сегодняшнее слово, играется так же, как в группе "
                "(одна попытка в день, общая для группы и этой тестовой ссылки)."
            )
            try:
                await self.bot.send_message(message.from_user.id, text, reply_markup=self._build_markup(private=True))
                if message.chat.type != 'private':
                    await message.reply("Кинул в личку 🎮")
            except Exception as e:
                logger.warning(f"Wordle: failed to DM test link to {message.from_user.id}: {e}")
                await message.reply("Не получилось написать в личку — напиши боту первым (/start) и попробуй снова.")

    def _build_markup(self, private: bool) -> InlineKeyboardMarkup:
        if private:
            button = InlineKeyboardButton(text="🎮 Играть в Wordle", web_app=WebAppInfo(url=Settings.WORDLE_WEB_APP_URL))
        else:
            # Telegram rejects web_app buttons outside private chats (BUTTON_TYPE_INVALID) —
            # deep-link into a private /start instead, see wordle_deep_link above.
            button = InlineKeyboardButton(
                text="🎮 Играть в Wordle", url=f"https://t.me/{Settings.BOT_USERNAME}?start=wordle",
            )
        return InlineKeyboardMarkup(inline_keyboard=[[button]])

    async def _ensure_tables(self):
        try:
            await self.db.execute_query(
                "CREATE TABLE IF NOT EXISTS wordle_daily ("
                "id SERIAL PRIMARY KEY, "
                "date DATE UNIQUE NOT NULL, "
                "word TEXT NOT NULL, "
                "chat_id BIGINT NOT NULL, "
                "message_id BIGINT, "
                "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
                (),
            )
            await self.db.execute_query(
                "CREATE TABLE IF NOT EXISTS wordle_games ("
                "id SERIAL PRIMARY KEY, "
                "date DATE NOT NULL, "
                "player_id BIGINT NOT NULL, "
                "player_name TEXT, "
                "attempts INTEGER DEFAULT 0, "
                "guesses JSONB DEFAULT '[]', "
                "won BOOLEAN DEFAULT FALSE, "
                "finished BOOLEAN DEFAULT FALSE, "
                "finished_at TIMESTAMP, "
                "UNIQUE(date, player_id))",
                (),
            )
        except Exception as e:
            logger.error(f"Wordle: failed to create tables: {e}")

    async def post_daily_wordle(self, chat_id: int):
        await self._ensure_tables()
        try:
            tz = ZoneInfo("Europe/Kyiv")
            today = datetime.now(tz).date()

            existing = await self.db.execute_query("SELECT id FROM wordle_daily WHERE date = %s", (today,))
            if existing:
                logger.info(f"Wordle: daily puzzle for {today} already posted, skipping")
                return

            # Unpin the previous day's puzzle before pinning today's — keeps the
            # pinned-messages list from accumulating one Wordle post per day.
            previous = await self.db.execute_query(
                "SELECT message_id FROM wordle_daily WHERE chat_id = %s AND date < %s "
                "ORDER BY date DESC LIMIT 1",
                (chat_id, today),
            )
            if previous and previous[0][0]:
                try:
                    await self.bot.unpin_chat_message(chat_id, previous[0][0])
                except Exception as e:
                    logger.warning(f"Wordle: failed to unpin previous message: {e}")

            word = word_for_date(today)
            # Include games already finished for this date (normally none, but a
            # missed post day or legacy early-morning games would otherwise be
            # silently dropped from the fresh message).
            games = await self.db.execute_query(
                "SELECT player_name, attempts, won, guesses FROM wordle_games "
                "WHERE date = %s AND finished = TRUE ORDER BY finished_at ASC",
                (today,),
            )
            rows = [
                (name or 'Игрок', attempts, won, [g['marks'] for g in (guesses or [])])
                for name, attempts, won, guesses in (games or [])
            ]
            text = build_message_text(rows)
            sent = await self.bot.send_message(
                chat_id, text, reply_markup=self._build_markup(private=False), parse_mode='HTML',
            )
            await self.db.execute_query(
                "INSERT INTO wordle_daily (date, word, chat_id, message_id) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (date) DO NOTHING",
                (today, word, chat_id, sent.message_id),
            )
            try:
                await self.bot.pin_chat_message(chat_id, sent.message_id, disable_notification=True)
            except Exception as e:
                logger.warning(f"Wordle: failed to pin daily message: {e}")
            logger.info(f"Wordle: posted daily puzzle for {today} in chat {chat_id}")
        except Exception as e:
            logger.error(f"Wordle: post_daily_wordle failed: {e}", exc_info=True)

    def start_scheduler(self, chat_id: int):
        tz = ZoneInfo("Europe/Copenhagen")
        self._scheduler = AsyncIOScheduler(timezone=tz)
        self._scheduler.add_job(
            self.post_daily_wordle, CronTrigger(hour=10, minute=0, timezone=tz), args=[chat_id],
        )
        self._scheduler.start()
        logger.info(f"Wordle: scheduler started for chat {chat_id} (post 10:00 Europe/Copenhagen)")
