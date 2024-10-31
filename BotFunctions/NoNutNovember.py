# BotFunctions/NoNutNovember.py

import threading
import time
from datetime import datetime, timedelta
from telebot import types
import random
import json

# Load motivational messages and memes
def load_motivations():
    with open('data/motivational_messages.json', 'r', encoding='utf-8') as f:
        motivational_messages = json.load(f)
    return motivational_messages

def load_memes():
    with open('data/memes.json', 'r', encoding='utf-8') as f:
        memes = json.load(f)
    return memes

motivational_messages = load_motivations()
memes = load_memes()

# Dictionary to track user check-ins
user_checkins = {}

def send_daily_checkin(bot, chat_id):
    # Create an inline keyboard with "Check In" button
    keyboard = types.InlineKeyboardMarkup()
    checkin_button = types.InlineKeyboardButton("Check In ✅", callback_data='nnn_checkin')
    keyboard.add(checkin_button)

    bot.send_message(
        chat_id=chat_id,
        text="🕛 БОЙЦЫ! Проверка на сперму в яйцах!",
        reply_markup=keyboard
    )

def schedule_daily_checkin(bot, chat_id):
    def run():
        while True:
            now = datetime.now()
            next_run = now.replace(hour=14, minute=50, second=0, microsecond=0)
            if now >= next_run:
                next_run += timedelta(days=1)
            time_to_wait = (next_run - now).total_seconds()
            time.sleep(time_to_wait)
            send_daily_checkin(bot, chat_id)
    threading.Thread(target=run).start()

def handle_checkin_callback(call, bot, pisunchik, save_data):
    user_id = str(call.from_user.id)
    username = call.from_user.username or call.from_user.first_name

    today = datetime.now().strftime('%Y-%m-%d')

    # Initialize user data if not present
    if user_id not in pisunchik:
        pisunchik[user_id] = {
            'player_name': username,
            'nnn_checkins': []
        }

    if 'nnn_checkins' not in pisunchik[user_id] or pisunchik[user_id]['nnn_checkins'] is None:
        pisunchik[user_id]['nnn_checkins'] = []

    # Record the check-in
    if today not in pisunchik[user_id]['nnn_checkins']:
        pisunchik[user_id]['nnn_checkins'].append(today)
        save_data()

    # Send motivational message and meme
    message = random.choice(motivational_messages)
    meme = random.choice(memes)

    bot.send_message(call.message.chat.id, f"{message}")
    bot.send_photo(call.message.chat.id, meme)

    bot.answer_callback_query(call.id, "Check-in successful!")

def motivation_command(message, bot):
    # Send a motivational message and meme
    message_text = random.choice(motivational_messages)
    meme = random.choice(memes)

    bot.send_message(message.chat.id, f"{message_text}")
    bot.send_photo(message.chat.id, meme)

def get_leaderboard(message, bot, pisunchik):
    leaderboard_text = "🏆 *NNN Leaderboard:*\n"
    for user_id, data in pisunchik.items():
        if 'nnn_checkins' in data and data['nnn_checkins']:
            checkin_count = len(data['nnn_checkins'])
            username = data.get('player_name') or 'User'
            leaderboard_text += f"- {username}: {checkin_count} check-ins\n"
    bot.send_message(message.chat.id, leaderboard_text, parse_mode='Markdown')
