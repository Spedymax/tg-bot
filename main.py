import telebot.apihelper
import random
from datetime import datetime, timedelta
from telebot import types
import time
import os
import psycopg2

# Get the database URL from environment variables
database_url = os.environ.get('DATABASE_URL')

# Establish a database connection
conn = psycopg2.connect(
    database="d10jl00d7m0v3k",
    user="swwnmrmvibkaln",
    host="ec2-54-73-22-169.eu-west-1.compute.amazonaws.com",
    password="9f127f6402cc566666445efbca44e4bbc8c4f48cf0ab3a1a8d27261bd874fac3",
    sslmode='require'
)

# Create a cursor for executing SQL queries
cursor = conn.cursor()


# Function to load player data from the database
def load_data():
    cursor.execute("SELECT player_id, pisunchik_size, coins FROM pisunchik_data")
    data = cursor.fetchall()
    return {str(player_id): {'pisunchik_size': pisunchik_size, 'coins': coins} for player_id, pisunchik_size, coins in data}


# Function to load player data from the database
def load_lastUsed_data():
    cursor.execute("SELECT player_id, last_used_time FROM last_used_data")
    data = cursor.fetchall()
    return {str(player_id): last_used_time for player_id, last_used_time in data}


# Initialize pisunchik data
pisunchik = load_data()
last_used = load_lastUsed_data()

bot_token = "1469789335:AAHtRcVSuRvphCppLp57jD14kUY-uUhG99o"
bot = telebot.TeleBot(bot_token)
print("Bot started")

# Player IDs
YURA_ID = 742272644
MAX_ID = 741542965
BODYA_ID = 855951767


@bot.message_handler(commands=['start'])
def start_game(message):
    player_id = str(message.from_user.id)
    pisunchik_size = pisunchik[player_id]['pisunchik_size']
    coins = pisunchik[player_id]['coins']

    bot.reply_to(message, f"Your pisunchik: {pisunchik_size} cm\nYou have {coins} coins!")


@bot.message_handler(commands=['leaderboard'])
def show_leaderboard(message):
    # Sort players by pisunchik_size in descending order
    sorted_players = sorted(pisunchik.items(), key=lambda x: x[1]['pisunchik_size'], reverse=True)

    leaderboard = "🏆 Большой член, большие яйца 🏆\n\n"
    for i, (player_id, data) in enumerate(sorted_players[:5]):
        name = bot.get_chat(int(player_id)).first_name
        pisunchik_size = data['pisunchik_size']
        coins = data['coins']
        leaderboard += f"{i + 1}. {name}: {pisunchik_size} sm🌭 и {coins} BTC💰\n"

    bot.reply_to(message, leaderboard)



@bot.message_handler(commands=['pisunchik'])
def update_pisunchik(message):
    player_id = str(message.from_user.id)

    if player_id not in last_used:
        last_used[player_id] = datetime.min

    if datetime.now() - last_used[player_id] < timedelta(hours=24):
        time_diff = timedelta(hours=24) - (datetime.now() - last_used[player_id])
        time_left = time_diff - timedelta(microseconds=time_diff.microseconds)
        bot.reply_to(message, f"Вы можете использовать эту команду только раз в день \nОсталось времени: {time_left}")
        return

    if player_id in pisunchik:
        last_used[player_id] = datetime.now()
        number = random.randint(-10, 10)
        pisunchik[player_id]['pisunchik_size'] += number
        number = random.randint(5, 15)
        pisunchik[player_id]['coins'] = pisunchik[player_id]['coins'] + number
        bot.reply_to(message, f"Ваш писюнчик: {pisunchik[player_id]['pisunchik_size']} см\nИзменения: {number} см\nТакже вы получили: {number} BTC")

    else:
        bot.reply_to(message, "Вы не зарегистрированы как игрок")

    save_data()


@bot.message_handler(commands=['roll'])
def update_pisunchik(message):
    player_id = str(message.from_user.id)

    if player_id in pisunchik:
        number = random.randint(1, 6)
        bot.reply_to(message, f"Выпало: {number}")
        if (number <= 3):
            pisunchik[player_id]['pisunchik_size'] -= 5
        if (number > 3):
            pisunchik[player_id]['pisunchik_size'] += 5
        bot.reply_to(message, f"Ваш писюнчик: {pisunchik[player_id]['pisunchik_size']} см\n")
    else:
        bot.reply_to(message, "Вы не зарегистрированы как игрок")
    pisunchik[player_id]['coins'] = pisunchik[player_id]['coins'] - 10

    save_data()


@bot.message_handler(commands=['otsos'])
def otsos(message):
    player_id = str(message.from_user.id)

    if player_id == "742272644":
        markup = types.InlineKeyboardMarkup()
        max_button = types.InlineKeyboardButton(text="Макс", callback_data="otsos_max")
        bogdan_button = types.InlineKeyboardButton(text="Богдан", callback_data="otsos_bogdan")
        markup.add(max_button, bogdan_button)
        bot.send_message(message.chat.id,
                         f"<a href='tg://user?id={message.from_user.id}'>@{message.from_user.username}</a>, кому отсасываем?",
                         reply_markup=markup, parse_mode='html')

    elif player_id == "741542965":
        markup = types.InlineKeyboardMarkup()
        yura_button = types.InlineKeyboardButton(text="Юра", callback_data="otsos_yura")
        bogdan_button = types.InlineKeyboardButton(text="Богдан", callback_data="otsos_bogdan")
        markup.add(yura_button, bogdan_button)
        bot.send_message(message.chat.id,
                         f"<a href='tg://user?id={message.from_user.id}'>@{message.from_user.username}</a>, кому отсасываем?",
                         reply_markup=markup, parse_mode='html')

    elif player_id == "855951767":
        markup = types.InlineKeyboardMarkup()
        max_button = types.InlineKeyboardButton(text="Макс", callback_data="otsos_max")
        yura_button = types.InlineKeyboardButton(text="Юра", callback_data="otsos_yura")
        markup.add(max_button, yura_button)
        bot.send_message(message.chat.id,
                         f"<a href='tg://user?id={message.from_user.id}'>@{message.from_user.username}</a>, кому отсасываем?",
                         reply_markup=markup, parse_mode='html')


@bot.callback_query_handler(func=lambda call: True)
def otsos_callback(call):
    bot.edit_message_reply_markup(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=None
    )
    if call.data == "otsos_yura":
        bot.send_message(call.message.chat.id, "Вы отсасываете Юре...")
        time.sleep(2)

        number = random.randint(1, 2)
        if number == 1:
            bot.send_message(call.message.chat.id, "Вы отсосали Юре. У него член: Встал :)")
        else:
            bot.send_message(call.message.chat.id, "Вы отсосали Юре. У него член: Не встал :(")

    elif call.data == "otsos_max":
        bot.send_message(call.message.chat.id, "Вы отсасываете Максу...")
        time.sleep(2)

        number = random.randint(1, 2)
        if number == 1:
            bot.send_message(call.message.chat.id, "Вы отсосали Максу. У него член: Встал :)")
        else:
            bot.send_message(call.message.chat.id, "Вы отсосали Максу. У него член: Не встал :(")

    elif call.data == "otsos_bogdan":
        bot.send_message(call.message.chat.id, "Вы отсасываете Богдану...")
        time.sleep(2)

        number = random.randint(1, 2)
        if number == 1:
            bot.send_message(call.message.chat.id, "Вы отсосали Богдану. У него член: Встал :)")
        else:
            bot.send_message(call.message.chat.id, "Вы отсосали Богдану. У него член: Не встал :(")


# Function to save player data to the database
def save_data():
    cursor.execute("DELETE FROM pisunchik_data")
    for player_id, data in pisunchik.items():
        pisunchik_size = data['pisunchik_size']
        coins = data['coins']
        cursor.execute("INSERT INTO pisunchik_data (player_id, pisunchik_size, coins) VALUES (%s, %s, %s)",
                       (player_id, pisunchik_size, coins))
    cursor.execute("DELETE FROM last_used_data")
    for player_id, last_used_time in last_used.items():
        cursor.execute("INSERT INTO last_used_data (player_id, last_used_time) VALUES (%s, %s)",
                       (player_id, last_used_time))
    conn.commit()


# Load last_used times on startup (if needed)
try:
    with open("last_used.txt") as f:
        for line in f:
            player_id, time_str = line.split()
            last_used[player_id] = datetime.fromisoformat(time_str)
except FileNotFoundError:
    pass

bot.polling()
