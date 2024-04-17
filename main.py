import json
import os
import random
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from subprocess import Popen, PIPE
from telebot.types import LabeledPrice

import psycopg2
import requests
import telebot.apihelper

from telebot import types

import BotFunctions.BotAnswer as botAnswer
import BotFunctions.Rofl as rofl
import BotFunctions.main_functions as main
import BotFunctions.trivia as trivia
from BotFunctions.cryptography import client

with open('data/statuetki.json', 'r', encoding='utf-8') as f:
    statuetki = json.load(f)
with open('data/shop.json', 'r', encoding='utf-8') as f:
    shop = json.load(f)
with open('data/char.json', 'r', encoding='utf-8') as f:
    char = json.load(f)
with open('data/plot.json', 'r', encoding='utf-8') as f:
    plot = json.load(f)

# Global variable to keep track of the subprocess
script_process = None

client.models.list()

headers = {
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {client.api_key}',
}
# Establish a database connection
conn = psycopg2.connect(
    database="d7c917hcd5cueq",
    user="lytcmoizjbmkyz",
    host="ec2-79-125-89-233.eu-west-1.compute.amazonaws.com",
    password="c641a9c8d30124f658cf93dc6fb98cf59ea6b9158591f4353684ee3bf91fadb1",
    sslmode='require'
)

# Create a cursor for executing SQL queries
cursor = conn.cursor()


def load_data():
    cursor.execute("SELECT * FROM pisunchik_data")  # Select all columns
    data = cursor.fetchall()
    player_data = {}

    column_names = [desc[0] for desc in cursor.description]

    for row in data:
        player_dict = {}
        for i, column_value in enumerate(row):
            column_name = column_names[i]

            if column_name == 'items':
                if column_value is None or not column_value:
                    items = []  # Default to an empty list
                else:
                    items = column_value  # No need for conversion, it's already a list
                player_dict['items'] = items
            elif column_name == 'last_used':
                if column_value is None:
                    last_used = datetime.min.replace(tzinfo=timezone.utc)
                else:
                    last_used = column_value
                player_dict['last_used'] = last_used
            elif column_name == 'last_vor':
                if column_value is None:
                    last_used = datetime.min.replace(tzinfo=timezone.utc)
                else:
                    last_used = column_value
                player_dict['last_vor'] = last_used
            elif column_name == 'characteristics':
                # Convert the characteristics dictionary to a JSON string.
                characteristics = json.dumps(column_value)

                # Load the characteristics JSON string into a Python dictionary.
                player_dict['characteristics'] = json.loads(characteristics) if characteristics is not None else {}
            elif column_name == 'player_stocks':
                # Convert the characteristics dictionary to a JSON string.
                player_stocks = json.dumps(column_value)

                # Load the characteristics JSON string into a Python dictionary.
                player_dict['player_stocks'] = json.loads(player_stocks) if player_stocks is not None else {}
            else:
                player_dict[column_name] = column_value

        player_data[str(row[0])] = player_dict

    return player_data


# Initialize pisunchik data
pisunchik = load_data()

bot_token = "1469789335:AAHtRcVSuRvphCppLp57jD14kUY-uUhG99o"
bot = telebot.TeleBot(bot_token)
print("Bot started")

# Player IDs
YURA_ID = 742272644
MAX_ID = 741542965
BODYA_ID = 855951767
NIKA_ID = 1085180226
VIKA_ID = 1561630034
# List of admin user IDs
admin_ids = [MAX_ID]
# Dictionary to keep track of admin actions
admin_actions = {}

xarakteristiks_desc = char['description']

statuetki_prices = statuetki['prices']

statuetki_desc = statuetki['description']

shop_prices = shop['prices']

item_desc = shop['description']


@bot.message_handler(commands=['giveChar'])
def add_characteristic(message):
    player_id = str(message.from_user.id)
    characteristic = random.choice(list(xarakteristiks_desc.items()))[0]

    if player_id in pisunchik:
        existing_characteristic = pisunchik[player_id]['characteristics']
        n = 0
        if existing_characteristic is not None:
            while True:
                # Check if the characteristic is already in the player's characteristics
                characteristic_name = characteristic.split(":")[0]
                if any(char.startswith(characteristic_name + ":") for char in existing_characteristic):
                    characteristic = random.choice(list(xarakteristiks_desc.items()))[0]
                    n += 1
                else:
                    # Append the characteristic to the player's characteristics with a random level
                    level = 1
                    characteristic = f"{characteristic_name}:{level}"
                    existing_characteristic.append(characteristic)
                    save_data()
                    break

                if n > 6:
                    break
        else:
            # If the player doesn't have any characteristics, add the new one with a random level
            level = 1  # You can adjust the range of levels as needed
            characteristic = f"{characteristic}:{level}"
            pisunchik[player_id]['characteristics'] = [characteristic]
            save_data()
    else:
        print(f"Player with ID {player_id} not found")
    save_data()


global_message = ''


@bot.message_handler(commands=['pay'])
def pay(message):
    global global_message
    prices = [LabeledPrice("Test", amount=100)]
    bot.send_invoice(message.chat.id, '2$', 'Купите 2$ всего за 1$!!! Невероятная акция!', 'two_dollars',
                     '284685063:TEST:MmNmYjMzMTFmMGMw', 'usd', prices, need_name=True,
                     need_email=True, )
    bot.send_invoice(message.chat.id, 'Kradoklad nudes', 'ОЧЕНЬ ГОРЯЧИЕ ФОТОЧКИ БОТА!', 'hot_bot',
                     '284685063:TEST:MmNmYjMzMTFmMGMw', 'usd', prices, need_name=True,
                     need_email=True, photo_url='https://i.imgur.com/4WvR9nP.png', photo_height=512,
                     # !=0/None or picture won't be shown
                     photo_width=512,
                     photo_size=512, )
    bot.send_invoice(message.chat.id, 'BrawlStart Megabox', 'Ты еблан? Мегабоксов уже как год нету в бравлике',
                     'megabox',
                     '284685063:TEST:MmNmYjMzMTFmMGMw', 'usd', prices, need_name=True,
                     need_email=True, )
    bot.send_invoice(message.chat.id, 'Shaurma Vkusnaya',
                     'Шаурма с сулугуні у шаурмиста на космонавтов! Вкуснее и дешевле не бывает', 'shaurma',
                     '284685063:TEST:MmNmYjMzMTFmMGMw', 'usd', prices, need_name=True,
                     need_email=True, )
    bot.send_invoice(message.chat.id, 'Trent Taunt',
                     'Насмешка на трента', 'trent',
                     '284685063:TEST:MmNmYjMzMTFmMGMw', 'usd', prices, need_name=True,
                     need_email=True, photo_url='https://i.imgur.com/MNONNqQ.jpeg', photo_height=512,
                     # !=0/None or picture won't be shown
                     photo_width=512,
                     photo_size=512, )
    bot.send_invoice(message.chat.id, 'Naked BULL Photos UNCENSORED',
                     'CLICK NOW! WATCH NOW!', 'hot_bull',
                     '284685063:TEST:MmNmYjMzMTFmMGMw', 'usd', prices, need_name=True,
                     need_email=True, photo_url='https://i.imgur.com/RHJczWI.png', photo_height=512,
                     # !=0/None or picture won't be shown
                     photo_width=512,
                     photo_size=512, )
    global_message = message


@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True,
                                  error_message="Что-то пошло не так:( Попробуйте ещё раз")


@bot.message_handler(content_types=['successful_payment'])
def got_payment(message):
    global global_message
    player_id = str(message.from_user.id)
    payload = message.successful_payment.invoice_payload
    if payload == 'two_dollars':
        pisunchik[player_id]['coins'] += 2
        bot.send_message(global_message.chat.id,
                         'Ураааааа! Спасибо за оплату! 2 доллара, что равно 0.0000061 BTC уже на вашем балансе:)',
                         parse_mode='Markdown')
    elif payload == 'hot_bot':
        bot.send_message(global_message.chat.id,
                         'Ураааааа! Спасибо за оплату! А вот и фоточки:)',
                         parse_mode='Markdown')
        bot.send_photo(message.chat.id, 'https://i.imgur.com/3HKy3PM.png', has_spoiler=True)
    elif payload == 'megabox':
        bot.send_message(global_message.chat.id,
                         'Ураааааа! Спасибо за оплату! Ваш мегабокс уже ждёт вас! Проверяйте!',
                         parse_mode='Markdown')
    elif payload == 'shaurma':
        bot.send_message(global_message.chat.id,
                         'Ураааааа! Спасибо за оплату! Ваша шаурма уже в пути, ожидайте ёё в 2034 году :)',
                         parse_mode='Markdown')
    elif payload == 'trent':
        bot.send_message(global_message.chat.id,
                         'Ураааааа! Спасибо за оплату! Нашмешка на трента только что была добавлена в ваш инвентарь! Проверяйте!',
                         parse_mode='Markdown')
    elif payload == 'hot_bull':
        bot.send_message(global_message.chat.id,
                         'Больной ублюдок',
                         parse_mode='Markdown')
        bot.send_photo(message.chat.id, 'https://i.ibb.co/ZgPCLCj/thumbnail-2fb6d148b5a978d62e3a937fae0319af.jpg',
                       has_spoiler=True)
    save_data()


@bot.message_handler(commands=['upgrade_char'])
def upgrade_characteristic(message):
    player_id = str(message.from_user.id)
    if player_id in pisunchik:
        existing_characteristic = pisunchik[player_id]['characteristics']

        if existing_characteristic is not None:
            characteristic_buttons = []
            for characteristic in existing_characteristic:
                characteristic_name, _ = characteristic.split(":")
                button_text = f"{characteristic_name}"
                callback_data = f"select_{characteristic}"
                characteristic_buttons.append(types.InlineKeyboardButton(text=button_text, callback_data=callback_data))

            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(*characteristic_buttons)

            bot.send_message(message.chat.id, "Выберите характеристику для улучшения:", reply_markup=keyboard)
        else:
            bot.send_message(message.chat.id, "У вас нет характеристик для улучшения.")
    else:
        bot.send_message(message.chat.id, "Вы не зарегистрированы как игрок, используйте /start")
    save_data()


@bot.callback_query_handler(func=lambda call: call.data.startswith("select"))
def select_characteristic_for_upgrade(call):
    chat_id = call.message.chat.id
    selected_characteristic = call.data.split("_")[1]

    level_buttons = []
    for i in range(1, 15):  # Предположим, что можно повысить максимум на 3 уровня
        button_text = f"Повысить на {i} уровень(ей)"
        callback_data = f"upgrade_{selected_characteristic}_{i}"
        level_buttons.append(types.InlineKeyboardButton(text=button_text, callback_data=callback_data))

    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(*level_buttons)

    bot.send_message(chat_id, "Выберите количество уровней для улучшения:", reply_markup=keyboard)
    save_data()


@bot.callback_query_handler(func=lambda call: call.data.startswith("upgrade"))
def handle_characteristic_upgrade(call):
    chat_id = call.message.chat.id
    player_id = str(call.from_user.id)
    call_data = call.data.split("_")
    selected_characteristic, levels_to_upgrade = call_data[1], int(call_data[2])

    characteristic_name, current_level = selected_characteristic.split(":")
    current_level = int(current_level)

    upgrade_cost = 100 * levels_to_upgrade  # Каждый уровень стоит 100 монет

    if pisunchik[player_id]['coins'] >= upgrade_cost and current_level + levels_to_upgrade <= 15:  # Проверка на
        # максимальный уровень и достаточно средств
        pisunchik[player_id]['coins'] -= upgrade_cost
        new_level = current_level + levels_to_upgrade
        updated_characteristic = f"{characteristic_name}:{new_level}"

        for n, characteristic in enumerate(pisunchik[player_id]['characteristics']):
            if selected_characteristic == characteristic:
                pisunchik[player_id]['characteristics'][n] = updated_characteristic

        save_data()
        bot.send_message(chat_id, f"Вы улучшили {characteristic_name} до уровня {new_level}!")
    else:
        bot.send_message(chat_id, "Недостаточно денег для улучшения или превышен максимальный уровень.")
    save_data()


@bot.message_handler(commands=['torgovec'])
def torgovec(message):
    for line in plot['strochki']:
        bot.send_message(message.chat.id, line)
        time.sleep(5)


@bot.message_handler(commands=['misha'])
def misha_wrapper(message):
    rofl.misha(message, bot, time)


@bot.message_handler(commands=['sho_tam_novogo'])
def get_recent_messages(message):
    bot.send_message(message.chat.id, "Ожидайте, анализирую сообщения...")
    cursor.execute("SELECT name, message_text FROM messages")
    converted_string = '\n'.join(f'{name}: {phrase}' for name, phrase in cursor.fetchall())
    data = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {"role": "system",
             "content": "Ты бот анализатор. Тебе будут давать сообщения от пользователей, твоё задание сделать "
                        "сводку того о чем была речь в этих сообщениях. Ты должен разделять каждую отдельную тему на "
                        "абзацы. Начинай своё сообщение с: За последние 12 часов речь шла о том что: *и потом "
                        "перечень того о чём шла речь*"},
            {"role": "user", "content": f"{converted_string}"},
        ],
        "temperature": 0.7
    }
    response = requests.post('https://api.openai.com/v1/chat/completions', headers=headers, data=json.dumps(data))
    response_data = response.json()
    bot.send_message(message.chat.id, f"{response_data['choices'][0]['message']['content']}")


@bot.message_handler(commands=['imagine'])
def imagine(message):
    try:
        prompt = message.text.split("/imagine", 1)[1].strip()
        if prompt:
            bot.send_message(message.chat.id, "Подождите, обрабатываю запрос...")
            response = client.images.generate(
                model="dall-e-2",
                prompt=f"{prompt}",
                size="1024x1024",
                quality="standard",
                n=1,
            )
            image_url = response.data[0].url
            bot.send_photo(message.chat.id, image_url)
    except:
        bot.send_message(message.chat.id, "Нормальное что-то попроси :(")


@bot.message_handler(commands=['start'])
def start_game(message):
    player_id = str(message.from_user.id)
    if player_id in pisunchik:
        # Existing player: display current pisunchik and coins
        pisunchik_size = pisunchik[player_id]['pisunchik_size']
        coins = pisunchik[player_id]['coins']
        bot.reply_to(message, f"Your pisunchik: {pisunchik_size} cm\nYou have {coins} coins!")
    else:
        # New player: ask for name and add to database
        bot.reply_to(message, "Добро пожаловать! Напишите ваше имя:")
        bot.register_next_step_handler(message, ask_where_found)


new_name = ''
new_user_id = ''


def ask_where_found(message):
    global new_name
    global new_user_id
    new_name = message.text.strip()
    new_user_id = message.from_user.id
    bot.send_message(message.chat.id, "Расскажите как вы нашли этого бота?")
    bot.register_next_step_handler(message, process_approval_step)


def process_approval_step(message):
    how_found = message.text.strip()
    global new_name
    bot.send_message(message.chat.id,
                     "Ваш запрос на регистрацию отправлен на рассмотрение. Пожалуйста, подождите одобрения.")
    bot.send_message(MAX_ID, f"Новый игрок {new_name}, она нашёл бота так: {how_found}")
    approval_markup = types.InlineKeyboardMarkup()
    approve_button = types.InlineKeyboardButton(text="Одобрить", callback_data="registration_approve")
    reject_button = types.InlineKeyboardButton(text="Отклонить", callback_data="registration_reject")
    approval_markup.row(approve_button, reject_button)
    bot.send_message(MAX_ID, f"Одобрить его регистрацию?",
                     reply_markup=approval_markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("registration"))
def registration_callback(call):
    global new_user_id
    call1 = call.data.split("_", 1)  # Split the callback data into action and player
    call2 = call1[1]
    global new_name
    if call2 == "approve":
        approve_registration(call.message)
    elif call2 == "reject":
        bot.send_message(call.message.chat.id, f"Регистрация пользователя {new_name} отклонена.")
        bot.send_message(new_user_id, f"Регистрация пользователя {new_name} отклонена.")
        new_name = ''  # Reset new_name variable


def approve_registration(message):
    global new_user_id
    player_id = str(message.from_user.id)

    # Add new player to database and initialize data
    pisunchik[player_id] = {
        'player_name': new_name,
        'pisunchik_size': 0,
        'coins': 0,
        'correct_answers': 0,
        'items': [],
        'characteristics': [],
        'player_stocks': [],
        'statuetki': [],
        'last_used': datetime.min.replace(tzinfo=timezone.utc),
        'last_vor': datetime.min.replace(tzinfo=timezone.utc),
        'last_prezervativ': datetime.min.replace(tzinfo=timezone.utc),
        'casino_last_used': datetime.min.replace(tzinfo=timezone.utc),
        'casino_usage_count': 0,
        'ballzzz_number': None,
        'notified': False,
    }
    # Insert new player into the database
    cursor.execute(
        "INSERT INTO pisunchik_data (player_id, player_name, pisunchik_size, coins, items, characteristics, "
        "statuetki, last_used, last_vor, last_prezervativ, casino_last_used, casino_usage_count, ballzzz_number, notified, "
        "player_stocks, correct_answers) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (int(player_id), new_name, 0, 0, '{}', '{}', '{}', datetime.min, datetime.min, datetime.min, datetime.min, 0,
         None,
         False, '{}',
         0))
    conn.commit()

    bot.send_message(new_user_id, f"Приятной игры, {new_name}! Вы зарегистрированы как новый игрок!")
    save_data()


is_echoing = False


@bot.message_handler(commands=['povtor'])
def start_echoing(message):
    global is_echoing
    is_echoing = True
    bot.reply_to(message, "Чё надо?")


@bot.message_handler(commands=['start_love'])
def start_script(message):
    global script_process
    if script_process is None or script_process.poll() is not None:
        # Start the script
        script_process = Popen(['python', 'love.py'], stdout=PIPE, stderr=PIPE)
        bot.reply_to(message, "Script started.")
    else:
        bot.reply_to(message, "Script is already running.")


@bot.message_handler(commands=['global_leaderboard'])
def show_leaderboard(message):
    # Sort pisunchik by pisunchik_size in descending order
    sorted_players = sorted(pisunchik.items(), key=lambda x: x[1]['pisunchik_size'], reverse=True)

    leaderboard = "🏆 Большой член, большие яйца 🏆\n\n"
    for i, (player_id, data) in enumerate(sorted_players[:5]):
        name = bot.get_chat(int(player_id)).first_name
        pisunchik_size = data['pisunchik_size']
        coins = data['coins']
        leaderboard += f"{i + 1}. {name}: {pisunchik_size} sm🌭 и {int(coins)} BTC💰\n"

    bot.reply_to(message, leaderboard)


@bot.message_handler(commands=['leaderboard'])
def show_local_leaderboard(message):
    # Get the current chat id
    current_chat_id = message.chat.id

    # Filter pisunchik to include only users in the current chat
    local_players = {player_id: data for player_id, data in pisunchik.items() if
                     bot.get_chat_member(current_chat_id, int(player_id)).status != 'left'}

    # Sort local_players by pisunchik_size in descending order
    sorted_local_players = sorted(local_players.items(), key=lambda x: x[1]['pisunchik_size'], reverse=True)

    leaderboard = "🏆 Local Leaderboard 🏆\n\n"
    for i, (player_id, data) in enumerate(sorted_local_players[:5]):
        try:
            name = bot.get_chat(int(player_id)).first_name
            pisunchik_size = data['pisunchik_size']
            coins = data['coins']
            leaderboard += f"{i + 1}. {name}: {pisunchik_size} sm🌭 и {int(coins)} BTC💰\n"
        except Exception as e:
            continue  # Skip if the user is not found or any other exception occurs

    bot.reply_to(message, leaderboard)


@bot.message_handler(commands=['smazka'])
def reset_pisunchik_cooldown(message):
    player_id = str(message.from_user.id)
    if 'smazka' in pisunchik[player_id]['items']:
        reset_timestamp = datetime(2000, 1, 1, tzinfo=timezone.utc)

        pisunchik[player_id]['last_used'] = reset_timestamp
        pisunchik[player_id]['items'].remove('smazka')
        save_data()
        # Provide a response to the user
        bot.reply_to(message, "Кулдаун для команды /pisunchik сброшен. Теперь вы можете использовать её снова.")
    else:
        bot.reply_to(message, "У вас нет предмета 'smazka'(")


@bot.message_handler(commands=['krystalnie_ballzzz'])
def use_krystalnie_ballzzz(message):
    player_id = str(message.from_user.id)

    if player_id not in pisunchik:
        bot.reply_to(message, "Вы не зарегистрированы как игрок.")
        return

    if 'krystalnie_ballzzz' not in pisunchik[player_id]['items']:
        bot.reply_to(message, "У вас нету предмета 'krystalnie_ballzzz'.")
        return

    if pisunchik[player_id]['ballzzz_number'] is None:
        next_effect = random.randint(-10, 17)

        effect_message = f"Следующее изменение писюнчика будет: {next_effect} см."
        pisunchik[player_id]['ballzzz_number'] = next_effect
    else:
        next_effect = pisunchik[player_id]['ballzzz_number']
        effect_message = f"Следующее изменение писюнчика будет: {next_effect} см."

    bot.reply_to(message, effect_message)
    save_data()


# Command to access the admin panel
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id in admin_ids:
        # Create an inline keyboard for the admin panel
        markup = types.InlineKeyboardMarkup()

        # Options for managing pisunchik' pisunchik and BTC amount
        increase_pisunchik_button = types.InlineKeyboardButton("Increase Pisunchik",
                                                               callback_data="admin_increase_pisunchik")
        decrease_pisunchik_button = types.InlineKeyboardButton("Decrease Pisunchik",
                                                               callback_data="admin_decrease_pisunchik")
        increase_btc_button = types.InlineKeyboardButton("Increase BTC", callback_data="admin_increase_btc")
        decrease_btc_button = types.InlineKeyboardButton("Decrease BTC", callback_data="admin_decrease_btc")

        # Options for adding/removing items from pisunchik
        add_item_button = types.InlineKeyboardButton("Add Item to Player", callback_data="admin_add_item")
        remove_item_button = types.InlineKeyboardButton("Remove Item from Player", callback_data="admin_remove_item")

        markup.add(
            increase_pisunchik_button, decrease_pisunchik_button,
            increase_btc_button, decrease_btc_button,
            add_item_button, remove_item_button
        )

        # Send the admin panel
        bot.send_message(message.chat.id, "Admin Panel:", reply_markup=markup)
    else:
        bot.reply_to(message, "You are not authorized to access the admin panel.")


player_name2 = ""


def get_player_name(player):
    global player_name2
    if player == '741542965':
        player_name2 = "Максим"
    elif player == '742272644':
        player_name2 = "Юра"
    elif player == '855951767':
        player_name2 = "Богдан"
    return player_name2


# Handle admin panel callbacks
@bot.callback_query_handler(func=lambda call: call.data.startswith("admin"))
def handle_callback(call):
    if call.from_user.id in admin_ids:
        admin_chat_id = call.message.chat.id
        call = call.data.split("_", 1)  # Split the callback data into action and player
        call = call[1]
        if call == "increase_pisunchik":
            # Prompt the admin to select a player
            markup = types.InlineKeyboardMarkup()
            for player in pisunchik:
                player_name2 = get_player_name(player)
                markup.add(
                    types.InlineKeyboardButton(player_name2,
                                               callback_data=f"select_player_increase_pisunchik_{player}"))
            bot.send_message(admin_chat_id, "Select a player to increase Pisunchik:", reply_markup=markup)

        elif call == "decrease_pisunchik":
            # Prompt the admin to select a player
            markup = types.InlineKeyboardMarkup()
            for player in pisunchik:
                player_name2 = get_player_name(player)
                markup.add(
                    types.InlineKeyboardButton(player_name2,
                                               callback_data=f"select_player_decrease_pisunchik_{player}"))
            bot.send_message(admin_chat_id, "Select a player to decrease Pisunchik:", reply_markup=markup)

        elif call == "increase_btc":
            # Prompt the admin to select a player
            markup = types.InlineKeyboardMarkup()
            for player in pisunchik:
                player_name2 = get_player_name(player)
                markup.add(
                    types.InlineKeyboardButton(player_name2, callback_data=f"select_player_increase_btc_{player}"))
            bot.send_message(admin_chat_id, "Select a player to increase BTC:", reply_markup=markup)

        elif call == "decrease_btc":
            # Prompt the admin to select a player
            markup = types.InlineKeyboardMarkup()
            for player in pisunchik:
                player_name2 = get_player_name(player)
                markup.add(
                    types.InlineKeyboardButton(player_name2, callback_data=f"select_player_decrease_btc_{player}"))
            bot.send_message(admin_chat_id, "Select a player to decrease BTC:", reply_markup=markup)

        elif call == "add_item":
            # Prompt the admin to select a player
            markup = types.InlineKeyboardMarkup()
            for player in pisunchik:
                player_name2 = get_player_name(player)
                markup.add(types.InlineKeyboardButton(player_name2, callback_data=f"select_player_add_item_{player}"))
            bot.send_message(admin_chat_id, "Select a player to add an item:", reply_markup=markup)

        elif call == "remove_item":
            # Prompt the admin to select a player
            markup = types.InlineKeyboardMarkup()
            for player in pisunchik:
                player_name2 = get_player_name(player)
                markup.add(
                    types.InlineKeyboardButton(player_name2, callback_data=f"select_player_remove_item_{player}"))
            bot.send_message(admin_chat_id, "Select a player to remove an item:", reply_markup=markup)

    else:
        bot.answer_callback_query(call.id, "You are not authorized to perform this action.")


# Handle player selection callbacks
@bot.callback_query_handler(func=lambda call: call.data.startswith("select_player"))
def handle_select_player(call):
    if call.from_user.id in admin_ids:
        admin_chat_id = call.message.chat.id
        action_data = call.data.split("_")
        if len(action_data) == 5:
            action = action_data[2] + "_" + action_data[3]  # pisunchik or btc or item
            player = action_data[4]

            player_name2 = get_player_name(player)

            # Store the selected player in the admin actions
            admin_actions[admin_chat_id] = {"action": action, "player": player}

            # Prompt the admin to enter the value or item name
            if action == "increase_pisunchik":
                bot.send_message(admin_chat_id, f"Enter the value to increase Pisunchik for Player {player_name2}:")
            elif action == "decrease_pisunchik":
                bot.send_message(admin_chat_id, f"Enter the value to decrease Pisunchik for Player {player_name2}:")
            elif action == "increase_btc":
                bot.send_message(admin_chat_id, f"Enter the value to increase BTC for Player {player_name2}:")
            elif action == "decrease_btc":
                bot.send_message(admin_chat_id, f"Enter the value to increase BTC for Player {player_name2}:")
            elif action == "add_item":
                bot.send_message(admin_chat_id, f"Enter the name of the item to add for Player {player_name2}:")
            elif action == "remove_item":
                bot.send_message(admin_chat_id, f"Enter the name of the item to remove for Player {player_name2}:")
    else:
        bot.answer_callback_query(call.id, "You are not authorized to perform this action.")


# Handle user messages for admin actions
@bot.message_handler(func=lambda message: message.chat.id in admin_actions)
def handle_admin_actions(message):
    if message.from_user.id in admin_ids:
        admin_chat_id = message.chat.id
        admin_action_data = admin_actions.get(admin_chat_id)

        if admin_action_data:
            action = admin_action_data.get("action")
            player = admin_action_data.get("player")
            player_name2 = get_player_name(player)

            if action == "increase_pisunchik":
                try:
                    value = int(message.text)
                    if player in pisunchik:
                        pisunchik[player]["pisunchik_size"] += value
                        bot.send_message(admin_chat_id, f"Pisunchik increased for Player {player_name2}.")
                    else:
                        bot.send_message(admin_chat_id, "Player not found.")
                except ValueError:
                    bot.send_message(admin_chat_id, "Please enter a valid numeric value.")

            elif action == "decrease_pisunchik":
                try:
                    value = int(message.text)
                    if player in pisunchik:
                        pisunchik[player]["pisunchik_size"] -= value
                        bot.send_message(admin_chat_id, f"Pisunchik decreased for Player {player_name2}.")
                    else:
                        bot.send_message(admin_chat_id, "Player not found.")
                except ValueError:
                    bot.send_message(admin_chat_id, "Please enter a valid numeric value.")

            elif action == "increase_btc":
                try:
                    value = int(message.text)
                    if player in pisunchik:
                        pisunchik[player]["coins"] += value
                        bot.send_message(admin_chat_id, f"BTC increased for Player {player_name2}.")
                    else:
                        bot.send_message(admin_chat_id, "Player not found.")
                except ValueError:
                    bot.send_message(admin_chat_id, "Please enter a valid numeric value.")
            elif action == "decrease_btc":
                try:
                    value = int(message.text)
                    if player in pisunchik:
                        pisunchik[player]["coins"] -= value
                        bot.send_message(admin_chat_id, f"BTC decreased for Player {player_name2}.")
                    else:
                        bot.send_message(admin_chat_id, "Player not found.")
                except ValueError:
                    bot.send_message(admin_chat_id, "Please enter a valid numeric value.")

            elif action == "add_item":
                item_name = message.text
                if player in pisunchik:
                    if item_name in item_desc:
                        pisunchik[player]["items"].append(item_name)
                        bot.send_message(admin_chat_id, f"Item '{item_name}' added to Player {player_name2}.")
                    else:
                        bot.send_message(admin_chat_id, "Item not found.")
                else:
                    bot.send_message(admin_chat_id, "Player not found.")
            elif action == "remove_item":
                item_name = message.text
                if player in pisunchik:
                    if item_name in pisunchik[player]["items"]:
                        pisunchik[player]["items"].remove(item_name)
                        bot.send_message(admin_chat_id, f"Item '{item_name}' removed from Player {player_name2}.")
                    else:
                        bot.send_message(admin_chat_id,
                                         f"Item '{item_name}' not found in Player {player_name2}'s inventory.")
                else:
                    bot.send_message(admin_chat_id, "Player not found.")

            del admin_actions[admin_chat_id]
        else:
            bot.send_message(admin_chat_id, "Invalid admin action.")
    else:
        bot.answer_callback_query(message.id, "You are not authorized to perform this action.")
    save_data()


@bot.message_handler(commands=['pisunchik'])
def update_pisunchik(message):
    player_id = str(message.from_user.id)

    if player_id not in pisunchik:
        pisunchik[player_id]['last_used'] = datetime.min
    existing_characteristic = pisunchik[player_id]['characteristics']
    # Check if the characteristic is already in the player's characteristics
    characteristic_name = "Titan"
    cooldown = 24
    if existing_characteristic is not None:
        for char_info in existing_characteristic:
            if char_info.startswith(characteristic_name):
                char_name, char_level = char_info.split(":")
                int_level = int(char_level)
                cooldown = int((24 * (100 - int_level * 3)) / 100)

    if datetime.now() - pisunchik[player_id]['last_used'].replace(tzinfo=None) < timedelta(hours=cooldown):
        time_diff = timedelta(hours=cooldown) - (
                datetime.now() - pisunchik[player_id]['last_used'].replace(tzinfo=None))
        time_left = time_diff - timedelta(microseconds=time_diff.microseconds)
        bot.reply_to(message, f"Вы можете использовать эту команду только раз в день \nОсталось времени: {time_left}")
        return

    if player_id in pisunchik:
        pisunchik[player_id]['last_used'] = datetime.now(timezone.utc)
        number = random.randint(-10, 17)
        number2 = random.randint(5, 15)
        kolzo_random = random.random()
        bdsm_random = random.random()
        ne_umenshilsya = False
        cooldown = False

        if 'krystalnie_ballzzz' in pisunchik[player_id]['items'] and pisunchik[player_id]['ballzzz_number'] is not None:
            number = pisunchik[player_id]['ballzzz_number']
            pisunchik[player_id]['ballzzz_number'] = None

        # Check if the player has 'kolczo_na_chlen' in their inventory and apply its effect
        if 'kolczo_na_chlen' in pisunchik[player_id]['items'] and kolzo_random <= 0.2:
            number2 *= 2  # Double the amount of BTC

        # Check if the player has 'prezervativ' in their inventory and apply its effect
        if 'prezervativ' in pisunchik[player_id]['items'] and number < 0:
            current_time = datetime.now(
                timezone.utc)  # Use datetime.now(timezone.utc)  to create an offset-aware datetime
            if current_time - pisunchik[player_id]['last_prezervativ'] >= timedelta(days=4):
                number = 0
                ne_umenshilsya = True
                pisunchik[player_id]['pisunchik_size'] += number
                pisunchik[player_id]['last_prezervativ'] = current_time  # Update to use the current time
            else:
                cooldown = True

        # Check if the player has 'bdsm_kostumchik' in their inventory and apply its effect
        if 'bdsm_kostumchik' in pisunchik[player_id]['items'] and bdsm_random <= 0.1:
            number += 5  # Add +5 cm to the pisunchik size

        pisunchik[player_id]['pisunchik_size'] += number
        pisunchik[player_id]['coins'] = pisunchik[player_id]['coins'] + number2

        # Construct the reply message based on the effects of the items
        reply_message = f"Ваш писюнчик: {pisunchik[player_id]['pisunchik_size']} см\nИзменения: {number} см\nТакже вы получили: {number2} BTC"

        if 'kolczo_na_chlen' in pisunchik[player_id]['items'] and kolzo_random <= 0.2:
            reply_message += "\nЭффект от 'kolczo_na_chlen': количество подученного BTC УДВОЕНО!"

        if 'bdsm_kostumchik' in pisunchik[player_id]['items'] and bdsm_random <= 0.1:
            reply_message += "\nЭффект от 'bdsm_kostumchik': +5 см к писюнчику получено."

        if ne_umenshilsya:
            reply_message += "\nЭффект от 'prezervativ': писюнчик не уменьшился."
        if cooldown:
            reply_message += "\nprezervativ' еще на кулдауне."
        # Generate a random number to determine the next effect (for demonstration purposes)
        next_effect = random.randint(-10, 17)
        pisunchik[player_id]['ballzzz_number'] = next_effect
        bot.reply_to(message, reply_message)
        pisunchik[player_id]['notified'] = False

    save_data()


# Create an inline keyboard with options
def create_roll_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(
        types.InlineKeyboardButton(text='1', callback_data='roll_1'),
        types.InlineKeyboardButton(text='3', callback_data='roll_3')
    )
    keyboard.row(
        types.InlineKeyboardButton(text='5', callback_data='roll_5'),
        types.InlineKeyboardButton(text='10', callback_data='roll_10')
    )
    keyboard.row(
        types.InlineKeyboardButton(text='20', callback_data='roll_20'),
        types.InlineKeyboardButton(text='50', callback_data='roll_50')
    )
    keyboard.row(
        types.InlineKeyboardButton(text='100', callback_data='roll_100')
    )
    return keyboard


@bot.message_handler(commands=['roll'])
def update_pisunchik(message):
    # Create and send the inline keyboard
    keyboard = create_roll_keyboard()
    bot.send_message(message.chat.id, "Выберите, сколько раз вы хотите бросить кубик:", reply_markup=keyboard)


@bot.callback_query_handler(func=lambda call: call.data.startswith('roll_'))
def handle_roll_option(call):
    option = int(call.data.split('_')[1])
    user_id = str(call.from_user.id)

    jackpot_message = f"🆘🤑БОГ ТЫ МОЙ! ТЫ ВЫИГРАЛ ДЖЕКПОТ! 400 BTC ТЕБЕ НА СЧЕТ!🤑🆘\n"

    if user_id in pisunchik:

        existing_characteristic = pisunchik[user_id]['characteristics']
        # Check if the characteristic is already in the player's characteristics
        player_name = get_player_name(user_id)
        characteristic_name = "Invisible"
        notNeededCoins = 0
        for i in range(0, option):
            if existing_characteristic is not None:
                for char_info in existing_characteristic:

                    if char_info.startswith(characteristic_name):
                        char_name, char_level = char_info.split(":")
                        int_level = int(char_level)
                        probability = 0.03 + ((int_level - 1) * 0.03)

                        # Generate a random number between 0 and 1
                        random_number = random.random()

                        # Check if the random number is less than or equal to the probability
                        if random_number <= probability:
                            notNeededCoins += 1
                        break
        if notNeededCoins >= 0:
            bot.send_message(call.message.chat.id,
                             f"Поздравляю, вот столько роллов для вас бесплатны: {notNeededCoins}")

        neededCoins = option * 6 - notNeededCoins * 6
        if 'kubik_seksa' in pisunchik[user_id]['items']:
            neededCoins = option * 3 - notNeededCoins * 3

        if pisunchik[user_id]['coins'] >= neededCoins:
            if 'kubik_seksa' in pisunchik[user_id]['items']:
                pisunchik[user_id]['coins'] -= neededCoins
            else:
                pisunchik[user_id]['coins'] -= neededCoins

            bot.send_message(call.message.chat.id, f"Всего потрачено: {neededCoins} BTC")

            roll_results = []
            jackpot = 0
            for _ in range(option):
                number = random.randint(1, 6)
                roll_results.append(number)
                number2 = random.randint(1, 101)
                if number2 == 14:
                    jackpot += 1
            for number in roll_results:
                if number <= 3:
                    pisunchik[user_id]['pisunchik_size'] -= 5
                elif number > 3:
                    pisunchik[user_id]['pisunchik_size'] += 5
            # Display the roll results in one message
            roll_message = f"Результаты бросков: {' '.join(map(str, roll_results))}\n"
            bot.send_message(call.message.chat.id, roll_message)
            # Display the updated pizunchik size
            bot.send_message(call.message.chat.id, f"Ваш писюнчик: {pisunchik[user_id]['pisunchik_size']} см")

            if jackpot != 0:
                time.sleep(2)
                bot.send_message(call.message.chat.id, "Cтоп что?")
                time.sleep(2)
                bot.send_message(call.message.chat.id, "...")
                time.sleep(2)
                bot.send_message(call.message.chat.id, "Да ладно...")
                for i in range(jackpot):
                    time.sleep(2)
                    if i >= 1:
                        bot.send_message(call.message.chat.id, "ЧТО? ЕЩЕ ОДИН?")
                        time.sleep(2)
                    pisunchik[user_id]['coins'] += 400
                    bot.send_message(call.message.chat.id, jackpot_message)
        else:
            bot.send_message(call.message.chat.id, f"Недостаточно BTC. Нужно {neededCoins} BTC")
    else:
        bot.send_message(call.message.chat.id, "Вы не зарегистрированы как игрок")

    save_data()


@bot.message_handler(commands=['items'])
def show_items(message):
    player_id = str(message.from_user.id)

    if player_id in pisunchik:
        user_items = pisunchik[player_id]['items']

        if not user_items:
            bot.reply_to(message, "У вас нету предметов(")
            return

        item_descriptions = []
        for item in user_items:
            if item in item_desc:
                item_descriptions.append(f"{item}: {item_desc[item]}")

        if item_descriptions:
            items_text = "\n".join(item_descriptions)
            bot.reply_to(message, f"Ваши предметы:\n{items_text}")
        else:
            bot.reply_to(message, "Нету описания предметов (Странно)")
    else:
        bot.reply_to(message, "Вы не зарегистрированы как игрок")


@bot.message_handler(commands=['statuetki'])
def show_items(message):
    player_id = str(message.from_user.id)
    item_images = {
        'Pudginio': 'statuetkiImages/pudginio.jpg',
        'Ryadovoi Rudgers': 'statuetkiImages/ryadovoi_rudgers.jpg',
        'Polkovnik Buchantos': 'statuetkiImages/polkovnik_buchantos.jpg',
        'General Chin-Choppa': 'statuetkiImages/general_chin_choppa.png'
    }

    if player_id in pisunchik:
        user_statuetki = pisunchik[player_id]['statuetki']

        if not user_statuetki:
            bot.reply_to(message, "У вас нету статуэток:(")
            return

        statuetki_descriptions = []
        for statuetka in user_statuetki:
            if statuetka in statuetki_desc:
                description = f"{statuetka}: {statuetki_desc[statuetka]}"
                statuetki_descriptions.append(description)

        if statuetki_descriptions:
            bot.reply_to(message, f"Ваши предметы:\n")
            time.sleep(1)  # Sleep for 1 second before sending images

            for statuetka in user_statuetki:
                description = statuetki_desc.get(statuetka, 'No description available')
                item_image_filename = item_images.get(statuetka, 'statuetkiImages/pudginio.jpg')
                with open(item_image_filename, 'rb') as photo:
                    time.sleep(1)
                    bot.send_photo(message.chat.id, photo, caption=f"{statuetka} - {description}")
            n = len(user_statuetki)
            bot.send_message(message.chat.id, f"Количество статуэток у вас: {n} из 4")

        else:
            bot.reply_to(message, "Нету описания предметов (Странно)")

        if len(user_statuetki) == 4:
            pisunchik[player_id]['statuetki'].remove('Pudginio')
            pisunchik[player_id]['statuetki'].remove('Ryadovoi Rudgers')
            pisunchik[player_id]['statuetki'].remove('Polkovnik Buchantos')
            pisunchik[player_id]['statuetki'].remove('General Chin-Choppa')

            for line in plot['strochki2']:
                time.sleep(5)
                bot.send_message(message.chat.id, line)

            add_characteristic(message)

    else:
        bot.reply_to(message, "Вы не зарегистрированы как игрок")


@bot.message_handler(commands=['characteristics'])
def show_characteristics(message):
    player_id = str(message.from_user.id)
    if player_id in pisunchik:
        characteristics_text = "Ваши характеристики:\n"
        existing_characteristic = pisunchik[player_id]['characteristics']
        if existing_characteristic:
            for characteristic in existing_characteristic:
                characteristic_name, current_level = characteristic.split(":")
                if characteristic_name in xarakteristiks_desc:
                    current_level = int(current_level)
                    characteristics_text += f"{characteristic_name}(Level {current_level}): {xarakteristiks_desc[characteristic_name]}\n"
            bot.reply_to(message, characteristics_text)
        else:
            bot.reply_to(message,
                         "Ой, у вас нету характеристик :( \n Сначала купите все статуэтки используя /statuetki_shop")
    else:
        bot.reply_to(message, "Вы не зарегистрированы как игрок, используйте /start")


@bot.message_handler(commands=['statuetki_shop'])
def show_statuetki_shop(message):
    chat_id = message.chat.id

    # Create a dictionary to map item names to image file names
    item_images = {
        'Pudginio': 'statuetkiImages/pudginio.jpg',
        'Ryadovoi Rudgers': 'statuetkiImages/ryadovoi_rudgers.jpg',
        'Polkovnik Buchantos': 'statuetkiImages/polkovnik_buchantos.jpg',
        'General Chin-Choppa': 'statuetkiImages/general_chin_choppa.png'
    }

    # Generate the shop message with images and prices
    shop_message = "🏛️ Добро пожаловать в мой магазин! 🏛️\n\n"
    bot.send_message(chat_id, shop_message)

    for item_name, item_price in statuetki_prices.items():
        # Get the image file name for the item
        item_image_filename = item_images.get(item_name, 'statuetkiImages/pudginio.jpg')

        # Send the image along with the item name and price
        with open(item_image_filename, 'rb') as photo:
            time.sleep(2)
            bot.send_photo(chat_id, photo, caption=f"{item_name} - {item_price} BTC")

    bot.send_message(chat_id, f'Посмотреть свои статуэтки можно использовав /statuetki')


@bot.message_handler(func=lambda message: message.text in statuetki_prices.keys())
def buy_item(message):
    player_id = str(message.from_user.id)
    statuetka_name = message.text
    statuetka_price = statuetki_prices.get(statuetka_name, 0)

    if statuetka_price > 0:
        user_balance = pisunchik[player_id]['coins']
        if user_balance >= statuetka_price:
            # Create an inline keyboard for confirmation
            markup = types.InlineKeyboardMarkup()
            confirm_button = types.InlineKeyboardButton("Да", callback_data=f"statuetka_confirm_{statuetka_name}")
            cancel_button = types.InlineKeyboardButton("Нет", callback_data="statuetka_cancel")
            markup.add(confirm_button, cancel_button)

            # Ask for confirmation
            confirmation_message = f"Вы хотите купить {statuetka_name} за {statuetka_price} ВТС?"
            bot.send_message(message.chat.id, confirmation_message, reply_markup=markup)
        else:
            bot.reply_to(message, "Недостаточно денег((")
    else:
        bot.reply_to(message, "Предмет не найден")


@bot.callback_query_handler(func=lambda call: call.data.startswith("statuetka_confirm_"))
def confirm_purchase(call):
    bot.edit_message_reply_markup(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=None
    )
    player_id = str(call.from_user.id)
    item_name = call.data.split("_", 2)[2]  # Extract item name from the callback data
    item_price = statuetki_prices.get(item_name, 0)

    user_balance = pisunchik[player_id]['coins']

    if user_balance >= item_price:
        # Deduct the item price from the user's balance
        pisunchik[player_id]['coins'] -= item_price
        # Add the item to the user's inventory
        pisunchik[player_id]['statuetki'].append(item_name)

        bot.send_message(call.message.chat.id, f"Вы купили {item_name} за {item_price} ВТС.")
    else:
        bot.send_message(call.message.chat.id, "Недостаточно денег((")

    save_data()


@bot.callback_query_handler(func=lambda call: call.data == "statuetka_cancel")
def cancel_purchase(call):
    bot.edit_message_reply_markup(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=None
    )
    bot.send_message(call.message.chat.id, "Покупка отменена")


discount = 0


# Function to display available items in the shop
def display_shop_items(message):
    player_id = str(message.from_user.id)
    existing_characteristic = pisunchik[player_id]['characteristics']
    # Check if the characteristic is already in the player's characteristics
    characteristic_name = "Hot"
    shop_items = " "
    global discount
    if existing_characteristic is not None and not '[]':
        for char_info in existing_characteristic:
            if char_info.startswith(characteristic_name):
                char_name, char_level = char_info.split(":")
                int_level = int(char_level)
                discount = 5 + ((int_level - 1) * 3)
                bot.send_message(-1001294162183, 'Магазинный автомат плавится...')
                time.sleep(3)
                shop_items = "\n".join(
                    [f"{item}: {int(price * (100 - discount) / 100)} coins" for item, price in shop_prices.items()])
            else:
                shop_items = "\n".join([f"{item}: {price} coins" for item, price in shop_prices.items()])
    else:
        shop_items = "\n".join([f"{item}: {price} coins" for item, price in shop_prices.items()])

    return f"Предметы в магазине: \n{shop_items}"


@bot.message_handler(commands=['shop'])
def show_shop(message):
    player_id = str(message.from_user.id)
    user_balance = pisunchik[player_id]['coins']

    # Display available items and prices
    shop_message = display_shop_items(message)
    shop_message += f"\n\nУ вас есть: {user_balance} BTC"
    shop_message += f"\n\nВаши предметы: /items"

    bot.reply_to(message, shop_message)


@bot.message_handler(func=lambda message: message.text in shop_prices.keys())
def buy_item(message):
    player_id = str(message.from_user.id)
    item_name = message.text
    item_price = shop_prices.get(item_name, 0)

    if item_price > 0:
        user_balance = pisunchik[player_id]['coins']
        if user_balance >= item_price:
            # Create an inline keyboard for confirmation
            markup = types.InlineKeyboardMarkup()
            confirm_button = types.InlineKeyboardButton("Да", callback_data=f"buy_confirm_{item_name}")
            cancel_button = types.InlineKeyboardButton("Нет", callback_data="buy_cancel")
            markup.add(confirm_button, cancel_button)

            # Ask for confirmation
            confirmation_message = f"Вы хотите купить {item_name} за {int(item_price * (100 - discount) / 100)} ВТС?"
            bot.send_message(message.chat.id, confirmation_message, reply_markup=markup)
        else:
            bot.reply_to(message, "Недостаточно денег((")
    else:
        bot.reply_to(message, "Предмет не найден")


@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_confirm_"))
def confirm_purchase(call):
    bot.edit_message_reply_markup(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=None
    )
    player_id = str(call.from_user.id)
    item_name = call.data.split("_", 2)[2]  # Extract item name from the callback data
    item_price = shop_prices.get(item_name, 0)

    user_balance = pisunchik[player_id]['coins']

    if user_balance >= item_price:
        # Deduct the item price from the user's balance
        pisunchik[player_id]['coins'] -= int(item_price * (100 - discount) / 100)
        # Add the item to the user's inventory
        pisunchik[player_id]['items'].append(item_name)
        # Update the 'items' field in the database with the new item list
        update_items(player_id, pisunchik[player_id]['items'], pisunchik[player_id]['coins'])

        bot.send_message(call.message.chat.id, f"Вы купили {item_name} за {item_price} ВТС.")
    else:
        bot.send_message(call.message.chat.id, "Недостаточно денег((")
    save_data()


@bot.callback_query_handler(func=lambda call: call.data == "buy_cancel")
def cancel_purchase(call):
    bot.edit_message_reply_markup(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=None
    )
    bot.send_message(call.message.chat.id, "Покупка отменена")


@bot.message_handler(commands=['zelie_pisunchika'])
def use_zelie_pisunchika(message):
    player_id = str(message.from_user.id)

    if player_id not in pisunchik:
        bot.reply_to(message, "Вы не зарегистрированы как игрок.")
        return

    if 'zelie_pisunchika' not in pisunchik[player_id]['items']:
        bot.reply_to(message, "У вас нету предмета 'zelie_pisunchika'.")
        return

    # Generate a random number to determine the effect (50% chance)
    is_increase = random.choice([True, False])
    amount = 20

    if is_increase:
        pisunchik[player_id]['pisunchik_size'] += amount
        effect_message = f"Ваш писюнчик увеличился на {amount} см."
    else:
        pisunchik[player_id]['pisunchik_size'] -= amount
        effect_message = f"Ваш писюнчик уменьшился на {amount} см."

    # Remove the 'zelie_pisunchika' item from the player's inventory
    pisunchik[player_id]['items'].remove('zelie_pisunchika')

    # Save the updated player data to the database
    save_data()

    bot.reply_to(message, effect_message)


@bot.message_handler(commands=['masturbator'])
def use_masturbator(message):
    player_id = str(message.from_user.id)

    if player_id not in pisunchik:
        bot.reply_to(message, "Вы не зарегистрированы как игрок")
        return

    if 'masturbator' not in pisunchik[player_id]['items']:
        bot.reply_to(message, "Y вас нету предмета 'masturbator'")
        return

    bot.send_message(
        message.chat.id,
        "Вы можете пожертвовать часть своего писюнчика ради получения ВТС. Чем больше размер пожертвован, тем больше BTC выиграно. 1 см = 4 ВТС + 5 ВТС за каждые 5 см.\n\n"
    )

    # Set the user's state to "waiting_for_donation" to handle the donation amount
    bot.register_next_step_handler(message, handle_donation_amount)


def handle_donation_amount(message):
    player_id = str(message.from_user.id)
    donation_amount = message.text

    if not donation_amount.isdigit():
        bot.send_message(message.chat.id, "Пожалуйста, введите корректное число.")
        return

    donation_amount = int(donation_amount)

    if donation_amount <= 0:
        bot.send_message(message.chat.id, "Пожалуйста, введите позитивное число. (Не балуйся)")
        return

    current_pisunchik_size = pisunchik[player_id]['pisunchik_size']

    if donation_amount > current_pisunchik_size:
        bot.send_message(message.chat.id, "Вы не можете пожертвовать больше, чем у вас есть. Дурак совсем?")
        return

    # Calculate the number of coins to award based on the donation
    coins_awarded = donation_amount * 4 + (donation_amount // 5) * 5

    # Update the player's pisunchik size and coins
    pisunchik[player_id]['pisunchik_size'] -= donation_amount
    pisunchik[player_id]['coins'] += coins_awarded

    # Remove the 'Masturbator(Юра)' item from the player's inventory
    pisunchik[player_id]['items'].remove('masturbator')

    # Save the updated player data to the database
    save_data()

    bot.reply_to(
        message,
        f"Вы задонатили {donation_amount} см вашего писюнчика и получили {coins_awarded} ВТС взамен"
    )


@bot.message_handler(commands=['piratik'])
def pirate_song(message):
    songs_folder = 'piratSongs'
    song_files = [f for f in os.listdir(songs_folder) if f.endswith('.mp3')]

    if not song_files:
        bot.send_message(message.chat.id, "No MP3 songs found in the folder.")
        return

    # Select a random song from the list
    random_song = random.choice(song_files)

    # Send the selected song to the user
    with open(os.path.join(songs_folder, random_song), 'rb') as audio_file:
        bot.send_audio(message.chat.id, audio_file)


@bot.message_handler(commands=['shaurma'])
def shaurma(message):
    player_id = str(message.from_user.id)
    bot.send_message(message.chat.id, 'Ну допустим схавал ты шаурмую. И? Оно того стоило?')
    time.sleep(3)
    bot.send_message(message.chat.id, '*Нихуя не произошло*')
    time.sleep(3)
    bot.send_message(message.chat.id, 'А, не, что-то происходит...')
    time.sleep(3)
    bot.send_message(message.chat.id, 'Бляяя, у тебя порвало днище')
    time.sleep(3)
    bot.send_message(message.chat.id, 'Ты просто всё вокруг обосрал, это пиздец')
    time.sleep(3)
    bot.send_message(message.chat.id, '*Получен дебафф диарея /items*')
    pisunchik[player_id]['items'].append('diarea')
    pisunchik[player_id]['items'].remove('shaurma')


@bot.message_handler(commands=['pisunchik_potion_small'])
def use_pisunchik_potion_small(message):
    apply_pisunchik_potion_effect(message, 3, 'small')


@bot.message_handler(commands=['pisunchik_potion_medium'])
def use_pisunchik_potion_medium(message):
    apply_pisunchik_potion_effect(message, 5, 'medium')


@bot.message_handler(commands=['pisunchik_potion_large'])
def use_pisunchik_potion_large(message):
    apply_pisunchik_potion_effect(message, 10, 'large')


def apply_pisunchik_potion_effect(message, increase_amount, size):
    player_id = str(message.from_user.id)

    if player_id not in pisunchik:
        bot.reply_to(message, "Вы не зарегистрированы как игрок.")
        return

    if f'pisunchik_potion_{size}' not in pisunchik[player_id]['items']:
        bot.reply_to(message, f"У вас нету пердмета 'pisunchik_potion_{size}'.")
        return

    pisunchik[player_id]['pisunchik_size'] += increase_amount
    effect_message = f"Your pisunchik size increased by {increase_amount} cm."

    # Remove the used potion from the player's inventory
    potion_name = f'pisunchik_potion_{size}'
    pisunchik[player_id]['items'].remove(potion_name)

    # Save the updated player data to the database
    save_data()

    bot.reply_to(message, effect_message)


def update_items(player_id, items, coins):
    # Convert the items list to a string representation
    items_str = str(items)
    # Use the ARRAY constructor to create a valid array literal
    query = "UPDATE pisunchik_data SET items = %s WHERE player_id = %s"
    cursor.execute(query, ([item for item in items], player_id))
    query2 = "UPDATE pisunchik_data SET coins = %s WHERE player_id = %s"
    cursor.execute(query2, (coins, player_id))
    conn.commit()


@bot.message_handler(commands=['furrypics'])
def furry_wrapper(message):
    rofl.send_furry_pics(message, random, bot)


@bot.message_handler(commands=['kazik'])
def kazik_wrapper(message):
    main.kazik(message, pisunchik, bot)
    save_data()


@bot.message_handler(commands=['trivia'])
def trivia_wrapper(message):
    trivia.send_trivia_questions(message.chat.id, bot, cursor, conn, headers)


@bot.message_handler(commands=['correct_answers'])
def correct_answers_wrapper(message):
    trivia.get_correct_answers(message, bot, pisunchik, cursor)




@bot.message_handler(commands=['peremoga'])
def peremoga(message):
    i = 0
    while i != 5:
        bot.send_message(message.chat.id, 'ПЕРЕМОГА БУДЕ ЛЮЮЮЮЮЮЮДИИИИИИИИ!!!!!')
        i = i + 1

@bot.message_handler(commands=['zrada'])
def peremoga(message):
    i = 0
    while i != 5:
        bot.send_message(message.chat.id, 'ЗРАДАААА😭😭😭😭')
        i = i + 1


@bot.callback_query_handler(func=lambda call: call.data.startswith('answer'))
def callback_answer(call):
    trivia.answer_callback(call, bot, pisunchik, cursor, conn)


def update_stock_prices():
    # Fetch the stock data
    query = "SELECT company_name, price FROM stocks"
    cursor.execute(query)
    stock_data = cursor.fetchall()

    # Store old prices in a dictionary for comparison
    old_prices = {company: price for company, price in stock_data}

    for company, old_price in old_prices.items():
        if company == 'ATB':
            change_percent = random.uniform(-0.2, 0)
            new_price = round(old_price * (1 + change_percent), 2)

            # Update the new price in the database
            update_query = "UPDATE stocks SET price = %s WHERE company_name = %s"
            cursor.execute(update_query, (new_price, company))
        elif company == 'Valve':
            change_percent = random.uniform(0, 0.14)
            new_price = round(old_price * (1 + change_percent), 2)

            # Update the new price in the database
            update_query = "UPDATE stocks SET price = %s WHERE company_name = %s"
            cursor.execute(update_query, (new_price, company))
        else:
            # Randomly increase or decrease price by up to 10%
            change_percent = random.uniform(-0.2, 0.2)
            new_price = round(old_price * (1 + change_percent), 2)

            # Update the new price in the database
            update_query = "UPDATE stocks SET price = %s WHERE company_name = %s"
            cursor.execute(update_query, (new_price, company))

    # Fetch updated stock data
    cursor.execute(query)
    updated_stock_data = cursor.fetchall()

    # Format the message
    stock_message = "Акции компаний на данный момент:\n\n"
    for company, new_price in updated_stock_data:
        old_price = old_prices[company]
        change = ((new_price - old_price) / old_price) * 100
        arrow = '⬆️' if change > 0 else '⬇️'
        stock_message += f"{company}: {new_price} BTC ({abs(change):.2f}% {arrow})\n"

    # Send the message
    bot.send_message(-1001294162183, stock_message)
    bot.send_message(-1001294162183,
                     "Чтобы купить акции используйте /buy_stocks \nЧтобы посмотреть свои акции используйте /my_stocks. \nЧтобы посмотреть стоимость акций на данный момент используйте /current_stocks")


@bot.message_handler(commands=['stocks_update'])
def stocks_update(message):
    if message.from_user.id in admin_ids:
        update_stock_prices()
    else:
        bot.send_message(message.chat.id, "Вы не админ((((((((((((")


@bot.message_handler(commands=['current_stocks'])
def current_stocks(message):
    query = "SELECT * FROM stocks"
    cursor.execute(query)
    stock_data = cursor.fetchall()
    stock_message = "Акции компаний на данный момент:\n\n"
    for company, price in stock_data:
        stock_message += f"{company}: {price} BTC\n"

    # Send the message
    bot.reply_to(message, stock_message)


@bot.message_handler(commands=['my_stocks'])
def myStocks(message):
    player_id = str(message.from_user.id)
    if player_id in pisunchik:
        stocks_text = "Ваши акции:\n"
        existing_stoks = pisunchik[player_id]['player_stocks']
        for player_stocks in existing_stoks:
            company_name, quantity = player_stocks.split(":")
            cursor.execute("SELECT price FROM stocks WHERE company_name = %s", (company_name,))
            result = cursor.fetchone()
            if not result:
                bot.reply_to(message, f"Company {company_name} not found.")
                return
            quantity = int(quantity)
            stock_price = result[0]
            total_cost = stock_price * quantity
            stocks_text += f"Компания {company_name}, кол-во акций: {quantity}  \n Цена ваших активов компании {company_name}: {total_cost}\n"
        bot.reply_to(message, stocks_text)
    else:
        bot.reply_to(message, "Вы не зарегистрированы как игрок, используйте /start")


temp_user_data = {}
temp_user_sell_data = {}


@bot.message_handler(commands=['buy_stocks'])
def buy_stocks(message):
    markup = types.InlineKeyboardMarkup()
    # Assuming you have a list of companies
    companies = ['ATB', 'Rockstar', 'Google', 'Apple', 'Valve', 'Obuhov toilet paper']
    for company in companies:
        markup.add(types.InlineKeyboardButton(company, callback_data=f"buy_stocks_{company}"))
    bot.send_message(message.chat.id, "Выберите компанию акции которой хотите купить:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('buy_stocks_'))
def handle_company_selection(call):
    company = call.data.split('_')[2]
    temp_user_data[call.from_user.id] = {'company': company}
    msg = f"Сколько акций компании {company} вы хотите купить?"
    bot.send_message(call.message.chat.id, msg)


@bot.message_handler(func=lambda message: message.from_user.id in temp_user_data)
def handle_quantity_selection(message):
    global user_id
    try:
        quantity = message.text
        if not quantity.isdigit():
            bot.reply_to(message, "Введи норм число, клоун).")
            return

        quantity = int(quantity)
        user_id = message.from_user.id
        company = temp_user_data[user_id]['company']

        # Fetch stock price from the database
        cursor.execute("SELECT price FROM stocks WHERE company_name = %s", (company,))
        result = cursor.fetchone()
        if not result:
            bot.reply_to(message, f"Company {company} not found.")
            return

        stock_price = result[0]
        total_cost = stock_price * quantity
        player_id = str(user_id)
        # Check if the user has enough coins
        if pisunchik[player_id]['coins'] < total_cost:
            bot.reply_to(message, f"Недостаточно BTC для покупки. Надо {total_cost} BTC")
            return

        # Deduct the total cost from the user's coins
        pisunchik[player_id]['coins'] -= total_cost

        # Check if user already owns stocks of this company
        stock_found = False
        for i, stock in enumerate(pisunchik[player_id]['player_stocks']):
            if stock.startswith(company):
                current_quantity = int(stock.split(':')[1])
                new_quantity = current_quantity + quantity
                pisunchik[player_id]['player_stocks'][i] = f"{company}:{new_quantity}"
                stock_found = True
                break

        if not stock_found:
            # Add the new stocks to the player's holdings
            new_stock = f"{company}:{quantity}"
            pisunchik[player_id]['player_stocks'].append(new_stock)

        # Update the player's data in the database
        # Example: UPDATE players SET coins = coins - total_cost, player_stocks = new_stock WHERE player_id = user_id
        cursor.execute("UPDATE pisunchik_data SET coins = %s, player_stocks = %s WHERE player_id = %s",
                       (pisunchik[player_id]['coins'], pisunchik[player_id]['player_stocks'], user_id))
        conn.commit()

        # Inform the user
        bot.reply_to(message, f"Мои поздравления! Вы купили вот столько акций: {quantity}, компании {company}.")
        save_data()
    except Exception as e:
        bot.reply_to(message, f"An error occurred: {str(e)}")
    finally:
        # Clear the temporary data
        if user_id in temp_user_data:
            del temp_user_data[user_id]


@bot.message_handler(commands=['sell_stocks'])
def sell_stocks(message):
    markup = types.InlineKeyboardMarkup()
    player_id = str(message.from_user.id)

    if player_id not in pisunchik or not pisunchik[player_id]['player_stocks']:
        bot.send_message(message.chat.id, "Ты бомж, у тебя вообще нету акций.")
        return

    # List the companies the user has stocks in
    owned_stocks = set(stock.split(':')[0] for stock in pisunchik[player_id]['player_stocks'])
    for company in owned_stocks:
        markup.add(types.InlineKeyboardButton(company, callback_data=f"sell_stocks_{company}"))
    bot.send_message(message.chat.id, "Выберите свою компанию:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('sell_stocks_'))
def handle_sell_company_selection(call):
    company = call.data.split('_')[2]
    # Store the selected company in a temporary structure (or user session)
    temp_user_sell_data[call.from_user.id] = {'company_to_sell': company}
    msg = f"Сколько акций компании {company} вы хотите продать?"
    bot.send_message(call.message.chat.id, msg)
    # Next, the user will send a message with the quantity, which you'll handle in a different function


@bot.message_handler(func=lambda message: message.from_user.id in temp_user_sell_data)
def handle_sell_quantity_selection(message):
    global user_id
    try:
        quantity = message.text
        if not quantity.isdigit():
            bot.reply_to(message, "Введи просто число, клоун)")
            return

        quantity = int(quantity)
        user_id = message.from_user.id
        company = temp_user_sell_data[user_id]['company_to_sell']
        player_id = str(user_id)

        # Check if the user owns enough stocks of the company
        for i, stock in enumerate(pisunchik[player_id]['player_stocks']):
            if stock.startswith(company):
                current_quantity = int(stock.split(':')[1])
                if quantity > current_quantity:
                    bot.reply_to(message, f"У вас нет столько акций. У вас {current_quantity} акций.")
                    return

                # Update the quantity or remove the stock entry if quantity becomes zero
                if quantity < current_quantity:
                    new_quantity = current_quantity - quantity
                    pisunchik[player_id]['player_stocks'][i] = f"{company}:{new_quantity}"
                else:
                    pisunchik[player_id]['player_stocks'].pop(i)
                # Calculate the amount earned from selling the stocks
                # Fetch current stock price from the database
                cursor.execute("SELECT price FROM stocks WHERE company_name = %s", (company,))
                result = cursor.fetchone()
                if not result:
                    bot.reply_to(message, f"Company {company} not found.")
                    return
                current_price = result[0]
                total_earned = current_price * quantity

                # Update player's coins
                pisunchik[player_id]['coins'] += total_earned

                # Update the player's data in the database
                cursor.execute("UPDATE pisunchik_data SET coins = %s, player_stocks = %s WHERE player_id = %s",
                               (pisunchik[player_id]['coins'], pisunchik[player_id]['player_stocks'], user_id))
                conn.commit()

                bot.reply_to(message,
                             f"Вы успешно продали {quantity} акций компании {company}.\n И вы заработали: {total_earned}")
                save_data()

                break
        else:
            bot.reply_to(message, f"You do not own any stocks of {company}.")
    except Exception as e:
        bot.reply_to(message, f"An error occurred: {str(e)}")
    finally:
        # Clear the temporary data
        if user_id in temp_user_sell_data:
            del temp_user_sell_data[user_id]


@bot.message_handler(commands=['prosipaisya'])
def prosipaisya(message):
    for i in range(1, 5):
        bot.send_message(message.chat.id,
                         f"<a href='tg://user?id={BODYA_ID}'>@lofiSnitch</a>",
                         parse_mode='html')


@bot.message_handler(commands=['otsos'])
def otsos_wrapper(message):
    rofl.otsos(message, pisunchik, bot)


@bot.callback_query_handler(func=lambda call: call.data.startswith('otsos'))
def otsos_callback_wrapper(call):
    rofl.otsos_callback(call, bot, pisunchik)


@bot.message_handler(commands=['vor'])
def vor(message):
    player_id = str(message.from_user.id)

    existing_characteristic = pisunchik[player_id]['characteristics']
    # Check if the characteristic is already in the player's characteristics
    exist = False
    characteristic_name = "Glowing"
    if existing_characteristic is not None:
        for char_info in existing_characteristic:
            if char_info.startswith(characteristic_name):
                if player_id in pisunchik:
                    last_usage_time = pisunchik[player_id]['last_vor']
                    current_time = datetime.now(timezone.utc)

                    # Calculate the time elapsed since the last usage
                    time_elapsed = current_time - last_usage_time

                    # If less than 24 hours have passed, and the usage limit is reached, deny access
                    if time_elapsed < timedelta(days=7):
                        bot.send_message(message.chat.id,
                                         f"Вы достигли лимита использования команды на эту неделю.\n Времени осталось: {timedelta(days=7) - time_elapsed}")
                        return
                exist = True
                pisunchik[player_id]['last_vor'] = datetime.now(timezone.utc)

                if player_id == "742272644":
                    markup = types.InlineKeyboardMarkup()
                    max_button = types.InlineKeyboardButton(text="Макс", callback_data="vor_max")
                    bogdan_button = types.InlineKeyboardButton(text="Богдан", callback_data="vor_bogdan")
                    markup.add(max_button, bogdan_button)
                    bot.send_message(message.chat.id,
                                     f"<a href='tg://user?id={message.from_user.id}'>@{message.from_user.username}</a>, у кого крадём член?",
                                     reply_markup=markup, parse_mode='html')

                elif player_id == "741542965":
                    markup = types.InlineKeyboardMarkup()
                    yura_button = types.InlineKeyboardButton(text="Юра", callback_data="vor_yura")
                    bogdan_button = types.InlineKeyboardButton(text="Богдан", callback_data="vor_bogdan")
                    markup.add(yura_button, bogdan_button)
                    bot.send_message(message.chat.id,
                                     f"<a href='tg://user?id={message.from_user.id}'>@{message.from_user.username}</a>, у кого крадём член?",
                                     reply_markup=markup, parse_mode='html')

                elif player_id == "855951767":
                    markup = types.InlineKeyboardMarkup()
                    max_button = types.InlineKeyboardButton(text="Макс", callback_data="vor_max")
                    yura_button = types.InlineKeyboardButton(text="Юра", callback_data="vor_yura")
                    markup.add(max_button, yura_button)
                    bot.send_message(message.chat.id,
                                     f"<a href='tg://user?id={message.from_user.id}'>@{message.from_user.username}</a"
                                     f">, у кого крадём член?",
                                     reply_markup=markup, parse_mode='html')

                elif player_id == "1561630034":
                    markup = types.InlineKeyboardMarkup()
                    max_button = types.InlineKeyboardButton(text="Макс", callback_data="vor_max")
                    markup.add(max_button)
                    bot.send_message(message.chat.id,
                                     f"<a href='tg://user?id={message.from_user.id}'>@{message.from_user.username}</a>, у кого крадём член?",
                                     reply_markup=markup, parse_mode='html')

                break
        if not exist:
            bot.send_message(message.chat.id, "У вас нету нужной характеристики для писюничка :(")
        save_data()


@bot.callback_query_handler(func=lambda call: call.data.startswith("vor"))
def vor_callback(call):
    bot.edit_message_reply_markup(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=None
    )
    player_id = call.from_user.id
    player = str(player_id)
    existing_characteristic = pisunchik[player]['characteristics']
    characteristic_name = "Glowing"
    vor_number = 0
    for char_info in existing_characteristic:
        if char_info.startswith(characteristic_name):
            char_name, char_level = char_info.split(":")
            int_level = int(char_level)
            vor_number = 2 + ((int_level - 1) * 2)

    if call.data == "vor_yura":
        pisunchik[str(YURA_ID)]['pisunchik_size'] -= vor_number
        pisunchik[player]['pisunchik_size'] += vor_number
        bot.send_message(call.message.chat.id, f"Вы украли {vor_number} см у Юры...")
        time.sleep(3)
    elif call.data == "vor_max":
        pisunchik[str(MAX_ID)]['pisunchik_size'] -= vor_number
        pisunchik[player]['pisunchik_size'] += vor_number
        bot.send_message(call.message.chat.id, f"Вы украли {vor_number} см у Макса...")

    elif call.data == "vor_bogdan":
        pisunchik[str(BODYA_ID)]['pisunchik_size'] -= vor_number
        pisunchik[player]['pisunchik_size'] += vor_number
        bot.send_message(call.message.chat.id, f"Вы украли {vor_number} см у Богдана...")


punchline = ""


@bot.message_handler(commands=['anekdot'])
def dad_jokes(message):
    url = "https://dad-jokes.p.rapidapi.com/random/joke"

    headers = {
        "X-RapidAPI-Key": "b56bba012emshd183f9e61c8904bp160ae7jsn40271047c907",
        "X-RapidAPI-Host": "dad-jokes.p.rapidapi.com"
    }

    response = requests.get(url, headers=headers)
    response = response.json()

    global punchline
    punchline = response['body'][0]['punchline']
    setup = response['body'][0]['setup']

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('?', callback_data="punchline"))
    bot.send_message(message.chat.id, setup, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("punchline"))
def dad_jokes_handler(call):
    bot.send_message(call.message.chat.id, punchline)


def save_data():
    # First, clear all existing data from the table, consider if this is what you really want to do
    cursor.execute("DELETE FROM pisunchik_data")

    # Loop through each player in the pisunchik dictionary
    for player_id, data in pisunchik.items():
        # Ensure player_id is not None or empty
        if player_id:
            # Prepare the data for insertion
            # Add player_id to the data dictionary
            data_with_id = {'player_id': player_id, **data}

            columns = ', '.join(data_with_id.keys())
            placeholders = ', '.join(['%s'] * len(data_with_id))
            values = tuple(data_with_id.values())

            # Build and execute the INSERT query
            query = f"INSERT INTO pisunchik_data ({columns}) VALUES ({placeholders})"
            cursor.execute(query, values)

    # Commit changes to the database
    conn.commit()


# Function to check if a user can use the /pisunchik command
def can_use_pisunchik():
    while True:
        for player in pisunchik:
            existing_characteristic = pisunchik[player]['characteristics']
            # Check if the characteristic is already in the player's characteristics
            characteristic_name = "Titan"
            cooldown = 24
            if existing_characteristic is not None:
                for char_info in existing_characteristic:
                    if char_info.startswith(characteristic_name):
                        char_name, char_level = char_info.split(":")
                        int_level = int(char_level)
                        cooldown = int((24 * (100 - int_level * 3)) / 100)

            current_time = datetime.now(timezone.utc)
            last_used_time = pisunchik[player]['last_used']

            # Calculate the time difference
            time_difference = current_time - last_used_time

            # Check if the cooldown period (24 or 13 hours) has passed
            if time_difference >= timedelta(hours=cooldown):
                # Update the last_used timestamp in the database
                if not pisunchik[player]['notified']:
                    bot.send_message(-1001294162183,
                                     f"<a href='tg://user?id={player}'>@{pisunchik[player]['player_name']}</a>, вы можете использовать /pisunchik",
                                     parse_mode='html')
                    pisunchik[player]['notified'] = True
                    save_data()
        curr_time = datetime.now(timezone.utc)
        if curr_time.hour == 12 and curr_time.minute == 0:
            for player in pisunchik:
                existing_characteristic = pisunchik[player]['characteristics']
                # Check if the characteristic is already in the player's characteristics
                characteristic_name = "Gold"
                n = 0
                if existing_characteristic is not None:
                    for char_info in existing_characteristic:
                        if char_info.startswith(characteristic_name):
                            char_name, char_level = char_info.split(":")
                            int_level = int(char_level)
                            income = 2 + ((int_level - 1) * 1.5)
                            pisunchik[player]['coins'] += int(income)
                            bot.send_message(-1001294162183,
                                             f"{pisunchik[player]['player_name']}, ваш золотой член принёс сегодня прибыль в размере {int(income)} BTC")
        if curr_time.hour in [8, 13, 17] and curr_time.minute == 0:
            update_stock_prices()
        if curr_time.hour in [10, 15, 18] and curr_time.minute == 0:
            for chat_id in [-1001294162183]:  # Replace with your chat IDs
                trivia.send_trivia_questions(chat_id, bot, cursor, conn, headers)
        if curr_time.hour == 22 and curr_time.minute == 0:
            trivia.get_correct_answers2(bot, pisunchik, cursor, conn)
        # if curr_time.hour == 12 and curr_time.minute == 0:
        #     bot.send_message(-1001294162183,
        #                      "Юра, вам был отправлен подарок. Нажмите /podarok чтобы открыть его...")
        # if curr_time.hour == 6 and curr_time.minute == 0:
        #     for i in range(1, 5):
        #         bot.send_message(-1001294162183,
        #                          'Хохлик, просыпайся)')
        # with open('Napominalka.wav', 'rb') as audio_file:
        #     bot.send_audio(-1001294162183, audio_file)
        for player in pisunchik:
            existing_characteristic = pisunchik[player]['characteristics']
            # Check if the characteristic is already in the player's characteristics
            player_name = get_player_name(player)
            characteristic_name = "Big Black"
            n = 0
            if existing_characteristic is not None:
                for char_info in existing_characteristic:
                    if char_info.startswith(characteristic_name):
                        char_name, char_level = char_info.split(":")
                        int_level = int(char_level)
                        min_pisunchik = 0 + ((int_level - 1) * 3)
                        if pisunchik[player]['pisunchik_size'] < min_pisunchik:
                            pisunchik[player]['pisunchik_size'] = min_pisunchik
                            save_data()
                            bot.send_message(-1001294162183,
                                             f"{player_name}, ваш член менее {min_pisunchik} сантиметров :( Но, не переживайте благодаря вашей Big Black характеристике ваш член снова стал {min_pisunchik} см")

        time.sleep(59)  # Sleep for 1 minute (adjust as needed)


# Define a function to start the cooldown checking thread
def start_cooldown_check_thread():
    cooldown_check_thread = threading.Thread(target=can_use_pisunchik)
    cooldown_check_thread.daemon = True
    cooldown_check_thread.start()


start_cooldown_check_thread()


@bot.message_handler(commands=['send'])
def send_to_group_command(message):
    # Ask the user to send the message they want to forward
    bot.send_message(message.chat.id, "Please send the message you want to forward to the group chat.")


@bot.message_handler(commands=['send2'])
def send_to_group_command(message):
    # Ask the user to send the message they want to forward
    bot.send_message(message.chat.id, "Please send the message you want to forward to the second group chat.")


@bot.message_handler(func=lambda message: f"Бот," in message.text)
def bot_answer_wrapper(message):
    botAnswer.bot_answer(message, bot, time, dad_jokes)


# Handler for messages mentioning the bot
@bot.message_handler(func=lambda message: f"@GgAllMute" in message.text)
def handle_mention(message):
    # Extract text following the bot's username
    prompt = message.text.split("@GgAllMute_bot", 1)[1].strip()
    if prompt:
        bot.send_message(message.chat.id, "Подождите, обрабатываю запрос...")
        try:
            data = {
                "model": "gpt-3.5-turbo",
                "messages": [
                    {

                        "role": "user",
                        "content": f"{prompt}"
                    }
                ],
                "temperature": 0.7
            }

            response = requests.post('https://api.openai.com/v1/chat/completions', headers=headers,
                                     data=json.dumps(data))
            response_data = response.json()
            bot.reply_to(message, response_data['choices'][0]['message']['content'])
        except:
            bot.send_message(message.chat.id, "Нормальное что-то попроси :(")


# Regular expression pattern for emojis
emoji_pattern = re.compile("["
                           u"\U0001F600-\U0001F64F"  # emoticons
                           u"\U0001F300-\U0001F5FF"  # symbols & pictographs
                           u"\U0001F680-\U0001F6FF"  # transport & map symbols
                           u"\U0001F1E0-\U0001F1FF"  # flags (iOS)
                           u"\U00002702-\U000027B0"
                           u"\U000024C2-\U0001F251"
                           "]+", flags=re.UNICODE)


# Handle user messages for sending a message to the group
@bot.message_handler(func=lambda message: True, content_types=['text'])
def handle_send_to_group_message(message):
    global is_echoing
    # If the flag is True and the message is not 'stop', echo the message.
    if is_echoing:
        if message.text.strip().lower() == 'харе':
            is_echoing = False
            bot.send_message(message.chat.id, "Повтор выключен")
        elif message.text.strip().lower() == 'я гей':
            bot.send_message(message.chat.id, "ты гей")
        elif message.text.strip().lower() == 'я пидор':
            bot.send_message(message.chat.id, "ты пидор")
        else:
            bot.send_message(message.chat.id, message.text)
    # Check if the user's message is a reply to the "sendtogroup" command
    if message.reply_to_message and message.reply_to_message.text == ("Please send the message you want to forward to "
                                                                      "the group chat."):
        # Forward the user's message to the group chat
        bot.send_message(-1001294162183, message.text)
        bot.send_message(message.chat.id, "Your message has been sent to the group chat.")

    if message.reply_to_message and message.reply_to_message.text == ("Please send the message you want to forward to "
                                                                      "the second group chat."):
        # Forward the user's message to the group chat
        bot.send_message(-4087198265, message.text)
        bot.send_message(message.chat.id, "Your message has been sent to the second group chat.")
    # if message.from_user.id == 742272644:
    #     if emoji_pattern.search(message.text):
    #         bot.send_message(message.chat.id, "Ойой, ты добаловался, наказан на 15 минут)")
    #         bot.send_message(message.chat.id, "Пока-пока 🤓")
    #         time.sleep(2)
    #         bot.restrict_chat_member(message.chat.id, message.from_user.id,
    #                                  until_date=datetime.now() + timedelta(minutes=15), permissions=None)
    user_id = message.from_user.id
    message_text = message.text
    timestamp = datetime.fromtimestamp(message.date)
    name = get_player_name(str(user_id))

    # Insert message into the database
    cursor.execute("INSERT INTO messages (user_id, message_text, timestamp, name) VALUES (%s, %s, %s, %s)",
                   (user_id, message_text, timestamp, name))
    conn.commit()
    some_hours_ago = datetime.utcnow() - timedelta(hours=12)
    # Delete messages older than 12 hours
    cursor.execute("DELETE FROM messages WHERE timestamp < %s", (some_hours_ago,))
    conn.commit()
    # Check total count of messages
    cursor.execute("SELECT COUNT(*) FROM messages")
    message_count = cursor.fetchone()[0]

    # If message count is greater than 150, delete the oldest ones
    if message_count > 300:
        # Find out how many messages to delete to get back to 150
        delete_count = message_count - 300
        cursor.execute("""
                DELETE FROM messages 
                WHERE id IN (
                    SELECT id FROM messages 
                    ORDER BY timestamp ASC 
                    LIMIT %s
                )
            """, (delete_count,))
        conn.commit()


bot.polling()
# 741542965
# -1001294162183 Чатик с пацанами
# -1001857844029 joke chat
