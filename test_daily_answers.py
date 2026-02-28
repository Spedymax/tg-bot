#!/usr/bin/env python3
"""Test script to manually trigger the daily answers broadcast."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from config.settings import Settings
from database.db_manager import DatabaseManager
from services.trivia_service import TriviaService
from services.quiz_scheduler import QuizScheduler
import telebot

def main():
    print("Testing daily answers broadcast...")
    print(f"Target chat: {Settings.CHAT_IDS['main']}")
    print(f"Timezone: {Settings.ANSWERS_BROADCAST_TIMEZONE}")
    print(f"Local time: {Settings.ANSWERS_BROADCAST_TIME_LOCAL}")
    print()

    # Initialize bot
    bot = telebot.TeleBot(Settings.TELEGRAM_BOT_TOKEN)

    # Initialize database manager
    db_manager = DatabaseManager()

    # Initialize trivia service
    trivia_service = TriviaService(Settings.GEMINI_API_KEY, db_manager)

    # Initialize quiz scheduler
    scheduler = QuizScheduler(bot, db_manager, trivia_service)

    print("Triggering daily answers broadcast...")
    try:
        scheduler.send_daily_answers()
        print("✅ Broadcast sent successfully!")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
