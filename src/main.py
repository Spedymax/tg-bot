#!/usr/bin/env python3
"""
Telegram Bot — aiogram v3 async entry point
"""
import asyncio
import logging
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand
from redis.asyncio import Redis

from config.settings import Settings
from database.db_manager import DatabaseManager
from database.player_service import PlayerService
from services.game_service import GameService
from services.quiz_scheduler import QuizScheduler
from services.ollama_wake_manager import OllamaWakeManager

from handlers.game_handlers import GameHandlers
from handlers.admin_handlers import AdminHandlers
from handlers.shop_handlers import ShopHandlers
from handlers.entertainment_handlers import EntertainmentHandlers
from handlers.trivia_handlers import TriviaHandlers
from handlers.miniapp_handlers import MiniAppHandlers
from handlers.health_alert_handlers import HealthAlertHandlers
from handlers.moltbot_handlers import MoltbotHandlers
from handlers.pet_handlers import PetHandlers
from handlers.court_handlers import CourtHandlers

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler('bot.log', maxBytes=10 * 1024 * 1024, backupCount=3),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)


async def main():
    # ── Core services (unchanged from old architecture) ──────────────────────
    db_manager = DatabaseManager()
    player_service = PlayerService(db_manager)
    game_service = GameService(player_service)

    # ── aiogram v3 Bot + Dispatcher with Redis FSM storage ───────────────────
    bot = Bot(
        token=Settings.TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    redis = Redis.from_url(Settings.REDIS_URL)
    storage = RedisStorage(redis=redis)
    dp = Dispatcher(storage=storage)

    # ── Handler instances (each exposes .router) ─────────────────────────────
    game_h = GameHandlers(bot, player_service, game_service)
    admin_h = AdminHandlers(bot, player_service, game_service)
    shop_h = ShopHandlers(bot, player_service, game_service)
    entertainment_h = EntertainmentHandlers(bot, player_service, game_service)
    trivia_h = TriviaHandlers(bot, player_service, game_service, db_manager)
    miniapp_h = MiniAppHandlers(bot, player_service, game_service)
    health_h = HealthAlertHandlers(bot)
    moltbot_h = MoltbotHandlers(bot, db_manager)
    pet_h = PetHandlers(bot, player_service, game_service)
    court_h = CourtHandlers(bot, db_manager)

    # ── Cross-handler wiring ──────────────────────────────────────────────────
    quiz_scheduler = QuizScheduler(bot, db_manager, trivia_h.trivia_service)
    admin_h.set_quiz_scheduler(quiz_scheduler)
    trivia_h.set_quiz_scheduler(quiz_scheduler)

    # ── Register routers ─────────────────────────────────────────────────────
    # State-based handlers (court, shop) are inherently priority-correct via FSM.
    # StateFilter(None) catch-alls in moltbot/admin sit at the bottom naturally.
    dp.include_router(court_h.router)
    dp.include_router(shop_h.router)
    dp.include_router(moltbot_h.router)
    dp.include_router(game_h.router)
    dp.include_router(admin_h.router)
    dp.include_router(entertainment_h.router)
    dp.include_router(trivia_h.router)
    dp.include_router(miniapp_h.router)
    dp.include_router(health_h.router)
    dp.include_router(pet_h.router)

    # ── Global error handler ──────────────────────────────────────────────────
    @dp.error()
    async def on_error(event, exception: Exception):
        logger.error(f"Unhandled exception in update: {exception}", exc_info=True)

    # ── Background services ───────────────────────────────────────────────────
    quiz_scheduler.start(bot)
    OllamaWakeManager().start(bot)

    # ── Proactive MoltBot scheduler ───────────────────────────────────────────
    moltbot_h.start_proactive_scheduler(Settings.CHAT_IDS['main'])

    # ── Register Telegram command menu ───────────────────────────────────────
    await bot.set_my_commands([
        BotCommand(command="start",           description="Профиль / начать игру"),
        BotCommand(command="pisunchik",       description="Прокачать писунчик"),
        BotCommand(command="leaderboard",     description="Таблица лидеров"),
        BotCommand(command="shop",            description="Магазин предметов"),
        BotCommand(command="items",           description="Мой инвентарь"),
        BotCommand(command="kazik",           description="Казино"),
        BotCommand(command="roll",            description="Бросить кубик"),
        BotCommand(command="trivia",          description="Запустить викторину"),
        BotCommand(command="pet",             description="Мой питомец"),
        BotCommand(command="danetka",         description="Загадать данетку"),
        BotCommand(command="sdayus",          description="Сдаться в данетке"),
        BotCommand(command="anekdot",         description="Случайный анекдот"),
        BotCommand(command="mut_reset",       description="Сбросить контекст бота"),
        BotCommand(command="sho_tam_novogo",  description="Что нового в чате (адм)"),
        BotCommand(command="analitika",       description="Аналитика за неделю (адм)"),
    ])
    logger.info("Bot commands registered")

    await bot.send_message(Settings.ADMIN_IDS[0], 'Bot restarted (aiogram v3)!')
    logger.info("Starting polling...")

    try:
        await dp.start_polling(bot)
    finally:
        await redis.aclose()
        db_manager.close_all_connections()
        logger.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
