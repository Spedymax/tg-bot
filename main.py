import telebot.apihelper
import random
from datetime import datetime, timedelta
from telebot import types
import time

last_used = {}  # player_id -> datetime

bot_token = "1469789335:AAHtRcVSuRvphCppLp57jD14kUY-uUhG99o"
bot = telebot.TeleBot(bot_token)

# Player IDs
YURA_ID = 742272644
MAX_ID = 741542965
BODYA_ID = 855951767

# Load the pisunchik values from file
try:
    with open("pisunchik.txt", "r") as f:
        pisunchik = {line.split()[0]: int(line.split()[1]) for line in f}
except FileNotFoundError:
    pisunchik = {
        str(YURA_ID): 0,
        str(MAX_ID): 0,
        str(BODYA_ID): 0
    }


@bot.message_handler(commands=['start'])
def start_game(message):
    player_id = str(message.from_user.id)
    pisunchik_value = pisunchik.get(player_id, 0)

    bot.reply_to(message, f"Your pisunchik: {pisunchik_value} cm")

@bot.message_handler(commands=['leaderboard'])
def show_leaderboard(message):
    sorted_pisunchik = sorted(pisunchik.items(), key=lambda x: x[1], reverse=True)

    leaderboard = "🏆 Большой член, большие яйца 🏆\n\n"
    for i, (player_id, value) in enumerate(sorted_pisunchik[:5]):
        name = bot.get_chat(int(player_id)).first_name
        leaderboard += f"{i + 1}. {name}: {value} см\n"

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
        pisunchik[player_id] += number
        bot.reply_to(message, f"Ваш писюнчик: {pisunchik[player_id]} см\nИзменения: {number} см")
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
            pisunchik[player_id] -= 5
        if (number > 3):
            pisunchik[player_id] += 5
        bot.reply_to(message, f"Ваш писюнчик: {pisunchik[player_id]} см\n")
    else:
        bot.reply_to(message, "Вы не зарегистрированы как игрок")

    save_data()


@bot.message_handler(commands=['otsos'])
def otsos(message):
    player_id = str(message.from_user.id)

    if player_id == "742272644":
        markup = types.InlineKeyboardMarkup()
        max_button = types.InlineKeyboardButton(text="Макс", callback_data="otsos_max")
        bogdan_button = types.InlineKeyboardButton(text="Богдан", callback_data="otsos_bogdan")
        markup.add(max_button, bogdan_button)
        bot.send_message(message.chat.id, f"<a href='tg://user?id={message.from_user.id}'>@{message.from_user.username}</a>, кому отсасываем?", reply_markup=markup, parse_mode='html')

    elif player_id == "741542965":
        markup = types.InlineKeyboardMarkup()
        yura_button = types.InlineKeyboardButton(text="Юра", callback_data="otsos_yura")
        bogdan_button = types.InlineKeyboardButton(text="Богдан", callback_data="otsos_bogdan")
        markup.add(yura_button, bogdan_button)
        bot.send_message(message.chat.id, f"<a href='tg://user?id={message.from_user.id}'>@{message.from_user.username}</a>, кому отсасываем?", reply_markup=markup, parse_mode='html')

    elif player_id == "855951767":
        markup = types.InlineKeyboardMarkup()
        max_button = types.InlineKeyboardButton(text="Макс", callback_data="otsos_max")
        yura_button = types.InlineKeyboardButton(text="Юра", callback_data="otsos_yura")
        markup.add(max_button, yura_button)
        bot.send_message(message.chat.id, f"<a href='tg://user?id={message.from_user.id}'>@{message.from_user.username}</a>, кому отсасываем?", reply_markup=markup, parse_mode='html')

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

def save_data():
    with open("pisunchik.txt", "w") as f:
        for player_id, value in pisunchik.items():
            f.write(f"{player_id} {value}\n")
    # Save last_used times
    with open("last_used.txt", "w") as f:
        for player_id, time in last_used.items():
            time_str = time.isoformat()
            f.write(f"{player_id} {time_str}\n")
# Load last_used times on startup
try:
    with open("last_used.txt") as f:
        for line in f:
            player_id, time_str = line.split()
            last_used[player_id] = datetime.fromisoformat(time_str)
except FileNotFoundError:
    pass

bot.polling()