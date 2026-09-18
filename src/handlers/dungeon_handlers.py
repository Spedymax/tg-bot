"""
Daily dungeon — bot side. The game itself runs in the mini-app (miniapp/app.py +
dungeon.html); this only hands out the button and shows today's standings.
"""
import json
import logging
import os
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from config.settings import Settings
from services.dungeon_service import get_dungeon_service

logger = logging.getLogger(__name__)

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CONTENT_PATH = os.path.join(_BASE_DIR, 'assets', 'data', 'dungeon_content.json')


def load_dungeon_content() -> dict:
    try:
        with open(_CONTENT_PATH, encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Dungeon: failed to load content: {e}")
        return {}


class DungeonHandlers:
    def __init__(self, bot, db_manager):
        self.bot = bot
        self.db = db_manager
        self.svc = get_dungeon_service(db_manager, load_dungeon_content())
        self.router = Router()
        self._register()

    def _markup(self, private: bool) -> InlineKeyboardMarkup:
        if private:
            button = InlineKeyboardButton(text="⚔️ В данж", web_app=WebAppInfo(url=Settings.DUNGEON_WEB_APP_URL))
        else:
            # web_app buttons are private-chat only (BUTTON_TYPE_INVALID in groups) — deep-link instead
            button = InlineKeyboardButton(text="⚔️ В данж", url=f"https://t.me/{Settings.BOT_USERNAME}?start=dungeon")
        return InlineKeyboardMarkup(inline_keyboard=[[button]])

    def _register(self):
        @self.router.message(CommandStart(deep_link=True, magic=F.args == 'dungeon'))
        async def dungeon_deep_link(message: Message, command: CommandObject):
            await message.answer(
                "🏰 Десять комнат, в конце — Мини-Пуджик. Один заход в день. Комнаты и правило дня одинаковые для всех.",
                reply_markup=self._markup(private=True),
            )

        @self.router.message(Command('dungeon', 'данж'))
        async def dungeon_status(message: Message):
            private = message.chat.type == 'private'
            try:
                results = await self.svc.today_results()
            except Exception as e:
                logger.warning(f"Dungeon: status failed: {e}")
                results = []
            if results:
                lines = ["🏰 <b>Данж дня</b>"] + [escape(self.svc.result_line(*r)) for r in results]
            else:
                lines = ["🏰 <b>Данж дня</b>", "Сегодня ещё никто не спускался."]
            await message.reply("\n".join(lines), parse_mode='HTML', reply_markup=self._markup(private=private))
