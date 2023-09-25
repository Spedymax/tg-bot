import telebot.apihelper
import random
from datetime import datetime, timedelta, timezone
from telebot import types
import time
import os
import psycopg2
import requests
from bs4 import BeautifulSoup
import subprocess

# Specify the path to the love.py script
# love_script_path = "love.py"

# Use subprocess to start the love.py script
# love_process = subprocess.Popen(["python3", love_script_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

# Get the database URL from environment variables
database_url = os.environ.get('DATABASE_URL')

# Establish a database connection
conn = psycopg2.connect(
    database="d8otdn21efhdgi",
    user="mbcexgnddtvzwu",
    host="ec2-99-80-246-170.eu-west-1.compute.amazonaws.com",
    password="ee48e2314e60e9610de0ac20be76ea1be559261e30ac0990f8267aeac1215a26",
    sslmode='require'
)

# Create a cursor for executing SQL queries
cursor = conn.cursor()


def load_data():
    cursor.execute(
        "SELECT player_id, pisunchik_size, coins, items, last_used, last_prezervativ, ballzzz_number, casino_last_used, casino_usage_count FROM pisunchik_data")
    data = cursor.fetchall()
    player_data = {}

    for player_id, pisunchik_size, coins, items_list, last_used, last_prezervativ, ballzzz_number, casino_last_used, casino_usage_count in data:
        # Check if 'items_list' is None or an empty list, and provide a default value
        if items_list is None or not items_list:
            items = []  # Default to an empty list
        else:
            items = items_list  # No need for conversion, it's already a list

        # Ensure 'last_used' is offset-aware with a default value
        if last_used is None:
            last_used = datetime.min.replace(tzinfo=timezone.utc)

        player_data[str(player_id)] = {
            'pisunchik_size': pisunchik_size,
            'coins': coins,
            'items': items,
            'last_used': last_used,
            'last_prezervativ': last_prezervativ,
            'ballzzz_number': ballzzz_number,
            'casino_last_used': casino_last_used,
            'casino_usage_count': casino_usage_count
        }

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
VIKA_ID = 1561630034
# List of admin user IDs
admin_ids = [741542965]
# Dictionary to keep track of admin actions
admin_actions = {}

shop_prices = {
    'kolczo_na_chlen': 75,
    'bdsm_kostumchik': 85,

    'kubik_seksa': 30,
    'prezervativ': 120,

    'krystalnie_ballzzz': 10,
    'smazka': 100,

    'zelie_pisunchika': 20,
    'masturbator': 20,

    'pisunchik_potion_small': 10,
    'pisunchik_potion_medium': 15,
    'pisunchik_potion_large': 20,
    'shaurma': 150
    # 'Statuetki': " ",
    # 'Pudginio': 100,
    # 'Ryadovoi Rudgers': 200,
    # 'Polkovnik Buchantos': 250,
    # 'General Chin-Choppa': 450

}

item_desc = {
    'kolczo_na_chlen': '{Пассивка} 20% шанс того что при использовании /pisunchik количество подученного BTC будет удвоено.',
    'bdsm_kostumchik': '{Пассивка} 10% шанс того что при использовании /pisunchik вы получите +5 см к писюнчику',

    'kubik_seksa': '{Пассивка} "При использовании /roll, стоимость броска на 50 процентов дешевле',
    'prezervativ': '{Пассивка} Если при использовании /pisunchik выпало отрицалеьное число то писюнчик не уменьшается. КД - 4 дня',

    'krystalnie_ballzzz': '{Активное} Показывает сколько выпадет при использовании /pisunchik в следующий раз\nИспользование: /krystalnie_ballzzz',
    'smazka': '{Аксивное} Можно использовать /pisunchik еще раз, раз в неделю\nИспользование: /smazka',
    'poroshochek': '/poroshochek ???',
    'shaurma': 'Ну молодец купил шаурму и чё дальше? Схавать /shaurma',
    'diarea': 'Теперь вы не можете кидать гифки смайлика в очках :)))))',

    'zelie_pisunchika': '{Съедобное} Моментально увеличивает писюнчик на 20 или -20 см. Шанс 50 на 50\nИспользование: /zelie_pisunchika',
    'masturbator': '{Съедобное} Позволяет с честью пожертвовать размером своего писюнчика ради получения BTC. Чем большим размером пожертвовано, тем больше монет выиграно. 1 см = 4 BTC + 5 BTC за каждые 5 см.\nИспользование: /masturbator',
    'pisunchik_potion_small': '{Съедобное} Моментально увеличивает писюнчик на 3 см\nИспользование: /pisunchik_potion_small',
    'pisunchik_potion_medium': '{Съедобное} Моментально увеличивает писюнчик на 5 см\nИспользование: /pisunchik_potion_medium',
    'pisunchik_potion_large': '{Съедобное} Моментально увеличивает писюнчик на 10 см\nИспользование: /pisunchik_potion_large'

}

# Define game states
START, IN_DUNGEON, FOUND_EXIT = range(3)

player_gold = 0
mob_hp = 10

# Initialize the game state
current_state = START

# Define dungeon rooms
dungeon_rooms = [
    "Вы просыпаетесь в темной подземной камере. Тут мокро и сыро, не очень хочеться тут оставаться. Ничего не видно но вы нащупываете две двери перед вами. Выберите одну, чтобы продолжить",
    "Вы попадаете в загадочную комнату с магическим алтарем. Жертвенный камень манит вас но вы сопротивляетесь изо всех сил. Куда вы пойдете дальше?",
    "Справа вы встречаете мост через бездонную пропасть. Решите, перейти ли вам на другую сторону или пойти налево?",
    "Вы попадаете в мрачное и опасное место. Оно заполнено пауками всех размеров, от крошечных паучков до огромных пауков-людоедов. Они могут быстро перемещаться и стрелять паутиной. Игрок должен быть осторожным, чтобы не попасть в паутину.",
    "Вы доходите до тупика. Вам придется вернуться назад. Вы разворачиваетесь, куда же вы пойдете?",
    "Вы видите сундук неподалёку. Вы открываете сундук и находите 40 BTC! Продолжайте путешевствие.",
    "Вы входите в забытый город который был построен в древние времена, но теперь он заброшен и забыт. Город состоит из огромных каменных зданий, украшенных резьбой и скульптурами. В центре города находится огромный храм, в котором вы видите огромный алтарь. Вы опять видите две двери. Куда вы пойдете?",
    "Вы попадаете в заброшенную шахту которая находится глубоко под землей. Она была построена много лет назад, но теперь она заброшена. Шахта состоит из узких проходов, глубоких колодцев и опасных ловушек. В шахте можно найти полезные ресурсы, такие как руда, золото и драгоценные камни. Вы прячите один из драгоценных камней себе в карман. Куда отправимся дальше?",
    "Перед вами огромный ледник который находится в глубине гор. Он состоит из огромного слоя льда, который образовался много лет назад. Ледник покрыт ледяными статуями, замерзшими водопадами и другими удивительными природными явлениями. Однако ледник также опасен. В нем может быть скользко, а холодный воздух может привести к обморожению. Вы видите две двери. Куда вы пойдете?",
    "Вы видите сундук неподалёку. Вы открываете сундук и находите 60 BTC! Юху!",
    "Вы рядом с подземным озером которое находится в глубине горы. Оно питается подземными источниками. Озеро окружено высокими скалами и зарослями деревьев. В озере можно найти рыбу, водоросли и другие обитателей подводного мира. Но в нем могут быть водовороты, ямы и другие опасности, лучше уйти отсюда поскорее.",
    "Вы забираетесь на остров который находится в центре озера. Он окружен высокими скалами. На острове есть деревья, цветы и другие растения. Но тут очень холодно. Уходите.",
]
dungeon_room = 0


# Keyboard markup for game options
def get_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    if current_state == IN_DUNGEON:
        keyboard.add(types.InlineKeyboardButton("Налево", callback_data='turn_left'),
                     types.InlineKeyboardButton("Направо", callback_data='turn_right'))
    return keyboard


# Start the game
@bot.message_handler(commands=['poroshochek'])
def start_game(message):
    player_id = str(message.from_user.id)
    if 'poroshochek' in pisunchik[player_id]['items']:
        global current_state
        current_state = IN_DUNGEON
        bot.send_message(message.chat.id, f"Вы достаете из кармана мешочек с порошком и вдыхаете его.")
        time.sleep(3)
        bot.send_message(message.chat.id, f"\nПеред вами появляется маленький человечек, возможно колдун!")
        time.sleep(3)
        bot.send_message(message.chat.id, f"Он что-то бормочет себе под нос и вдруг исчезает.")
        time.sleep(3)
        bot.send_message(message.chat.id,
                         f"Вы чувствуете как ваши яйца увеличиваются в размере.\nСейчас что-то произойдет!")
        time.sleep(3)
        bot.send_message(message.chat.id, f"Внезапно в глазах темнеет, и вы падаете на пол....")
        time.sleep(3)
        bot.send_message(message.chat.id, dungeon_rooms[0], reply_markup=get_keyboard())


# Handle button callbacks
@bot.callback_query_handler(func=lambda call: call.data.startswith("turn"))
def handle_callback(call):
    global current_state, player_gold, dungeon_room
    player_id = str(call.from_user.id)
    if current_state == IN_DUNGEON:
        if call.data == 'turn_left':
            dungeon_room += 1
        elif call.data == 'turn_right':
            dungeon_room += 1

        elif dungeon_room == 5:
            player_gold += 50
        elif dungeon_room == 9:
            player_gold += 50

        if dungeon_room == 12 or dungeon_room == 13 or dungeon_room == 14:
            current_state = FOUND_EXIT
            dungeon_room = 11
            bot.edit_message_text(f"Вы достигли выхода из подземелья! Поздравляю!", call.message.chat.id,
                                  call.message.message_id,
                                  reply_markup=None)
        else:
            bot.edit_message_text(dungeon_rooms[dungeon_room], call.message.chat.id, call.message.message_id,
                                  reply_markup=get_keyboard())

        if current_state == FOUND_EXIT:
            bot.send_message(call.message.chat.id, f"Вы достигли выхода из подземелья! Поздравляем!\n")
            time.sleep(3)
            bot.send_message(call.message.chat.id,
                             f"Вы осматриваетесь по сторонам и видите колдуна которого вы встретили ранее\n")
            time.sleep(3)
            bot.send_message(call.message.chat.id, f"Он опять что-то бормочет себе под нос и изчезает!\n")
            time.sleep(3)
            bot.send_message(call.message.chat.id, f"Вы понимаете что у вас пропал мешочек с порошком :(\n")
            pisunchik[player_id]['items'].remove('poroshochek')
            time.sleep(3)
            bot.send_message(call.message.chat.id,
                             f"Вы снимаете с себя трусы и понимаете что ваш писюнчик увеличился на 20 см!\n")
            time.sleep(3)
            bot.send_message(call.message.chat.id, f"А еще вы получили 100 BTC\n")
            pisunchik[player_id]['pisunchik_size'] += 20
            pisunchik[player_id]['coins'] += 100
            bot.send_message(call.message.chat.id, "Спасибо за игру!")
            save_data()


# Command to initiate sending a message to the group
@bot.message_handler(commands=['misha'])
def misha(message):
    bot.send_message(message.chat.id, 'Миша!')
    time.sleep(3)
    bot.send_message(message.chat.id, 'Миша привет!')
    time.sleep(3)
    bot.send_message(message.chat.id,
                     'Мммииишааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааа')


@bot.message_handler(commands=['start'])
def start_game(message):
    player_id = str(message.from_user.id)
    pisunchik_size = pisunchik[player_id]['pisunchik_size']
    coins = pisunchik[player_id]['coins']

    bot.reply_to(message, f"Your pisunchik: {pisunchik_size} cm\nYou have {coins} coins!")


@bot.message_handler(commands=['leaderboard'])
def show_leaderboard(message):
    if message.chat.id == -1001294162183:
        # Sort pisunchik by pisunchik_size in descending order
        sorted_players = sorted(pisunchik.items(), key=lambda x: x[1]['pisunchik_size'], reverse=True)

        # Suppose you want to remove the player with a specific player_id
        player_id_to_remove = '1561630034'

        # Use a list comprehension to filter out the player with the specified player_id
        sorted_players = [player for player in sorted_players if player[0] != player_id_to_remove]

        leaderboard = "🏆 Большой член, большие яйца 🏆\n\n"
        for i, (player_id, data) in enumerate(sorted_players[:5]):
            name = bot.get_chat(int(player_id)).first_name
            pisunchik_size = data['pisunchik_size']
            coins = data['coins']
            leaderboard += f"{i + 1}. {name}: {pisunchik_size} sm🌭 и {coins} BTC💰\n"

        bot.reply_to(message, leaderboard)
    elif message.chat.id == -1001932619845:
        # Sort pisunchik by pisunchik_size in descending order
        sorted_players = sorted(pisunchik.items(), key=lambda x: x[1]['pisunchik_size'], reverse=True)

        # Suppose you want to remove the player with a specific player_id
        player_id_to_remove = '742272644'

        # Use a list comprehension to filter out the player with the specified player_id
        sorted_players = [player for player in sorted_players if player[0] != player_id_to_remove]

        # Suppose you want to remove the player with a specific player_id
        player_id_to_remove = '855951767'

        # Use a list comprehension to filter out the player with the specified player_id
        sorted_players = [player for player in sorted_players if player[0] != player_id_to_remove]

        leaderboard = "🏆 Большой член, большие яйца 🏆\n\n"
        for i, (player_id, data) in enumerate(sorted_players[:5]):
            name = bot.get_chat(int(player_id)).first_name
            pisunchik_size = data['pisunchik_size']
            coins = data['coins']
            leaderboard += f"{i + 1}. {name}: {pisunchik_size} sm🌭 и {coins} BTC💰\n"

        bot.reply_to(message, leaderboard)
    else:
        # Sort pisunchik by pisunchik_size in descending order
        sorted_players = sorted(pisunchik.items(), key=lambda x: x[1]['pisunchik_size'], reverse=True)

        leaderboard = "🏆 Большой член, большие яйца 🏆\n\n"
        for i, (player_id, data) in enumerate(sorted_players[:5]):
            name = bot.get_chat(int(player_id)).first_name
            pisunchik_size = data['pisunchik_size']
            coins = data['coins']
            leaderboard += f"{i + 1}. {name}: {pisunchik_size} sm🌭 и {coins} BTC💰\n"

        bot.reply_to(message, leaderboard)


@bot.message_handler(commands=['smazka'])
def reset_pisunchik_cooldown(message):
    player_id = str(message.from_user.id)
    if 'smazka' in pisunchik[player_id]['items']:
        reset_timestamp = datetime(2000, 1, 1, tzinfo=timezone.utc)

        # Update the last_used column in the last_used_data table for the specific player
        cursor.execute("UPDATE pisunchik_data SET last_used = %s WHERE player_id = %s", (reset_timestamp, player_id))
        conn.commit()
        conn.close()

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


player_name = ""


def get_player_name(player):
    global player_name
    if player == '741542965':
        player_name = "Максим"
    elif player == '742272644':
        player_name = "Юра"
    elif player == '855951767':
        player_name = "Богдан"
    return player_name


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
                player_name = get_player_name(player)
                markup.add(
                    types.InlineKeyboardButton(player_name, callback_data=f"select_player_increase_pisunchik_{player}"))
            bot.send_message(admin_chat_id, "Select a player to increase Pisunchik:", reply_markup=markup)

        elif call == "decrease_pisunchik":
            # Prompt the admin to select a player
            markup = types.InlineKeyboardMarkup()
            for player in pisunchik:
                player_name = get_player_name(player)
                markup.add(
                    types.InlineKeyboardButton(player_name, callback_data=f"select_player_decrease_pisunchik_{player}"))
            bot.send_message(admin_chat_id, "Select a player to decrease Pisunchik:", reply_markup=markup)

        elif call == "increase_btc":
            # Prompt the admin to select a player
            markup = types.InlineKeyboardMarkup()
            for player in pisunchik:
                player_name = get_player_name(player)
                markup.add(
                    types.InlineKeyboardButton(player_name, callback_data=f"select_player_increase_btc_{player}"))
            bot.send_message(admin_chat_id, "Select a player to increase BTC:", reply_markup=markup)

        elif call == "decrease_btc":
            # Prompt the admin to select a player
            markup = types.InlineKeyboardMarkup()
            for player in pisunchik:
                player_name = get_player_name(player)
                markup.add(
                    types.InlineKeyboardButton(player_name, callback_data=f"select_player_decrease_btc_{player}"))
            bot.send_message(admin_chat_id, "Select a player to decrease BTC:", reply_markup=markup)

        elif call == "add_item":
            # Prompt the admin to select a player
            markup = types.InlineKeyboardMarkup()
            for player in pisunchik:
                player_name = get_player_name(player)
                markup.add(types.InlineKeyboardButton(player_name, callback_data=f"select_player_add_item_{player}"))
            bot.send_message(admin_chat_id, "Select a player to add an item:", reply_markup=markup)

        elif call == "remove_item":
            # Prompt the admin to select a player
            markup = types.InlineKeyboardMarkup()
            for player in pisunchik:
                player_name = get_player_name(player)
                markup.add(types.InlineKeyboardButton(player_name, callback_data=f"select_player_remove_item_{player}"))
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
            player_name = get_player_name(player)

            if action == "increase_pisunchik":
                try:
                    value = int(message.text)
                    if player in pisunchik:
                        pisunchik[player]["pisunchik_size"] += value
                        bot.send_message(admin_chat_id, f"Pisunchik increased for Player {player_name}.")
                    else:
                        bot.send_message(admin_chat_id, "Player not found.")
                except ValueError:
                    bot.send_message(admin_chat_id, "Please enter a valid numeric value.")

            elif action == "decrease_pisunchik":
                try:
                    value = int(message.text)
                    if player in pisunchik:
                        pisunchik[player]["pisunchik_size"] -= value
                        bot.send_message(admin_chat_id, f"Pisunchik decreased for Player {player_name}.")
                    else:
                        bot.send_message(admin_chat_id, "Player not found.")
                except ValueError:
                    bot.send_message(admin_chat_id, "Please enter a valid numeric value.")

            elif action == "increase_btc":
                try:
                    value = int(message.text)
                    if player in pisunchik:
                        pisunchik[player]["coins"] += value
                        bot.send_message(admin_chat_id, f"BTC increased for Player {player_name}.")
                    else:
                        bot.send_message(admin_chat_id, "Player not found.")
                except ValueError:
                    bot.send_message(admin_chat_id, "Please enter a valid numeric value.")
            elif action == "decrease_btc":
                try:
                    value = int(message.text)
                    if player in pisunchik:
                        pisunchik[player]["coins"] -= value
                        bot.send_message(admin_chat_id, f"BTC decreased for Player {player_name}.")
                    else:
                        bot.send_message(admin_chat_id, "Player not found.")
                except ValueError:
                    bot.send_message(admin_chat_id, "Please enter a valid numeric value.")

            elif action == "add_item":
                item_name = message.text
                if player in pisunchik:
                    if item_name in item_desc:
                        pisunchik[player]["items"].append(item_name)
                        bot.send_message(admin_chat_id, f"Item '{item_name}' added to Player {player_name}.")
                    else:
                        bot.send_message(admin_chat_id, "Item not found.")
                else:
                    bot.send_message(admin_chat_id, "Player not found.")
            elif action == "remove_item":
                item_name = message.text
                if player in pisunchik:
                    if item_name in pisunchik[player]["items"]:
                        pisunchik[player]["items"].remove(item_name)
                        bot.send_message(admin_chat_id, f"Item '{item_name}' removed from Player {player_name}.")
                    else:
                        bot.send_message(admin_chat_id,
                                         f"Item '{item_name}' not found in Player {player_name}'s inventory.")
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

    if datetime.now() - pisunchik[player_id]['last_used'].replace(tzinfo=None) < timedelta(hours=24):
        time_diff = timedelta(hours=24) - (datetime.now() - pisunchik[player_id]['last_used'].replace(tzinfo=None))
        time_left = time_diff - timedelta(microseconds=time_diff.microseconds)
        bot.reply_to(message, f"Вы можете использовать эту команду только раз в день \nОсталось времени: {time_left}")
        return

    if player_id in pisunchik:
        pisunchik[player_id]['last_used'] = datetime.now()
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
            print(number2)
            number2 *= 2  # Double the amount of BTC
            print(number2)

        # Check if the player has 'prezervativ' in their inventory and apply its effect
        if 'prezervativ' in pisunchik[player_id]['items'] and number < 0:
            current_time = datetime.now(
                timezone.utc)  # Use datetime.now(timezone.utc) to create an offset-aware datetime
            if current_time - pisunchik[player_id]['last_prezervativ'] >= timedelta(days=4):
                number = 0
                ne_umenshilsya = True
                pisunchik[player_id]['pisunchik_size'] += number
                pisunchik[player_id]['last_prezervativ'] = current_time  # Update to use the current time
            else:
                cooldown = True

        # Check if the player has 'bdsm_kostumchik' in their inventory and apply its effect
        if 'bdsm_kostumchik' in pisunchik[player_id]['items'] and bdsm_random <= 0.1:
            print(number)
            number += 5  # Add +5 cm to the pisunchik size
            print(number)

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

    jackpot_message = f"🆘🤑БОГ ТЫ МОЙ! ТЫ ВЫИГРАЛ ДЖЕКПОТ! 300 BTC ТЕБЕ НА СЧЕТ!🤑🆘\n"

    if user_id in pisunchik:
        neededCoins = option * 6
        if 'kubik_seksa' in pisunchik[user_id]['items']:
            neededCoins = option * 3

        if pisunchik[user_id]['coins'] >= neededCoins:
            if 'kubik_seksa' in pisunchik[user_id]['items']:
                pisunchik[user_id]['coins'] -= neededCoins
            else:
                pisunchik[user_id]['coins'] -= neededCoins

            roll_results = []
            jackpot = 0
            for _ in range(option):
                number = random.randint(1, 6)
                roll_results.append(number)
                for number in roll_results:
                    if number <= 3:
                        pisunchik[user_id]['pisunchik_size'] -= 5
                    if number > 3:
                        pisunchik[user_id]['pisunchik_size'] += 5
                number2 = random.randint(1, 40)
                if number2 == 14:
                    jackpot += 1

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
                    pisunchik[user_id]['coins'] += 300
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


# Function to display available items in the shop
def display_shop_items():
    shop_items = "\n".join([f"{item}: {price} coins" for item, price in shop_prices.items()])
    return f"Предметы в магазине: \n{shop_items}"


@bot.message_handler(commands=['shop'])
def show_shop(message):
    player_id = str(message.from_user.id)
    user_balance = pisunchik[player_id]['coins']

    # Display available items and prices
    shop_message = display_shop_items()
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
            confirmation_message = f"Вы хотите купить {item_name} за {item_price} ВТС?"
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
        pisunchik[player_id]['coins'] -= item_price
        # Add the item to the user's inventory
        pisunchik[player_id]['items'].append(item_name)

        # Update the 'items' field in the database with the new item list
        update_items(player_id, pisunchik[player_id]['items'], pisunchik[player_id]['coins'])

        bot.send_message(call.message.chat.id, f"Вы купили {item_name} за {item_price} ВТС.")
    else:
        bot.send_message(call.message.chat.id, "Недостаточно денег((")


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


def get_furry_images():
    # Get the URL of the furry images website.
    image_urls = []
    for x in range(1, 9):
        url = "https://imgbin.com/free-png/furry-art/" + str(x)
        # Make a request to the website.
        response = requests.get(url)

        # Parse the response.
        soup = BeautifulSoup(response.content, "html.parser")

        # Find all the image links.
        for x in range(1, 46):
            # Find the image link by id
            image_link = soup.find(id='listimg' + str(x))

            if image_link:
                # Extract the URL from the 'src' attribute of the 'img' tag

                if 'data-src' in image_link.attrs:
                    image_url = image_link['data-src']
                    image_urls.append(image_url)

    return image_urls


image_urls2 = get_furry_images()
print("Loaded")


# Function to get the time remaining for the prezervativ cooldown
def get_prezervativ_cooldown_remaining(player_id):
    cursor.execute("SELECT last_prezervativ FROM pisunchik_data WHERE player_id = %s", (player_id,))
    last_used_time = cursor.fetchone()[0]

    if last_used_time is None:
        return 0  # If the command was never used, it's available immediately

    # Calculate the time remaining until the command becomes available
    current_time = datetime.now(timezone.utc)
    cooldown_end_time = last_used_time + timedelta(days=1)
    time_remaining = cooldown_end_time - current_time

    # Calculate hours, minutes, and seconds remaining
    hours, remainder = divmod(time_remaining.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    return hours, minutes, seconds


# Function to get the time remaining for the cooldown
def get_cooldown_remaining(player_id):
    cursor.execute("SELECT last_used FROM pisunchik_data WHERE player_id = %s", (player_id,))
    last_used_time = cursor.fetchone()[0]

    if last_used_time is None:
        return 0  # If the command was never used, it's available immediately

    # Calculate the time remaining until the command becomes available
    current_time = datetime.now(timezone.utc)
    cooldown_end_time = last_used_time + timedelta(hours=24)
    time_remaining = cooldown_end_time - current_time

    # Calculate hours, minutes, and seconds remaining
    hours, remainder = divmod(time_remaining.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    return hours, minutes, seconds


# Command to check the cooldown and display the countdown
@bot.message_handler(commands=['timer'])
def check_cooldown(message):
    player_id = str(message.from_user.id)
    player_name = get_player_name(player_id)
    response = f"Таймер для игрока {player_name}\n/pisunchik будет доступен через "

    hours, minutes, seconds = get_cooldown_remaining(player_id)
    prez_hours, prez_minutes, prez_seconds = get_prezervativ_cooldown_remaining(player_id)

    text_response = response

    if hours == 0 and minutes == 0 and seconds == 0:
        text_response = f"Таймер для игрока {player_name}\n/pisunchik Уже доступен!"
    else:
        if hours > 0:
            text_response += f"{hours} часов "
        if minutes > 0:
            text_response += f"{minutes} минут "
        if seconds > 0:
            text_response += f"{seconds} секунд "

    if 'prezervativ' in pisunchik[player_id]['items']:
        prez_response = "prezervativ будет доступен через "
        if prez_hours == 0 and prez_minutes == 0 and prez_seconds == 0:
            prez_response = "prezervativ уже доступен!"
        else:
            if prez_hours > 0:
                prez_response += f"{prez_hours} часов "
            if prez_minutes > 0:
                prez_response += f"{prez_minutes} минут "
            if prez_seconds > 0:
                prez_response += f"{prez_seconds} секунд "

        text_response += f"\n{prez_response}"

    # Send the initial message and save its message ID
    initial_message = bot.send_message(chat_id=message.chat.id, text=text_response)

    # Update the message every second by editing it
    while hours > 0 or minutes > 0 or seconds > 0 or prez_hours > 0 or prez_minutes > 0 or prez_seconds > 0:
        time.sleep(30)  # Wait for 5 second before updating the message
        hours, minutes, seconds = get_cooldown_remaining(player_id)
        prez_hours, prez_minutes, prez_seconds = get_prezervativ_cooldown_remaining(player_id)
        text_response = response

        if hours == 0 and minutes == 0 and seconds == 0:
            text_response = f"Таймер для игрока {player_name}\n/pisunchik Уже доступен!"
        else:
            if hours > 0:
                text_response += f"{hours} часов "
            if minutes > 0:
                text_response += f"{minutes} минут "
            if seconds > 0:
                text_response += f"{seconds} секунд "

        if 'prezervativ' in pisunchik[player_id]['items']:
            prez_response = "prezervativ будет доступен через "
            if prez_hours == 0 and prez_minutes == 0 and prez_seconds == 0:
                prez_response = "prezervativ уже доступен!"
            else:
                if prez_hours > 0:
                    prez_response += f"{prez_hours} часов "
                if prez_minutes > 0:
                    prez_response += f"{prez_minutes} минут "
                if prez_seconds > 0:
                    prez_response += f"{prez_seconds} секунд "

            text_response += f"\n{prez_response}"
        # Edit the initial message with updated cooldown information
        bot.edit_message_text(chat_id=message.chat.id, message_id=initial_message.message_id, text=text_response)


@bot.message_handler(commands=['furrypics'])
def send_furry_pics(message):
    random_selection = random.sample(image_urls2, 5)
    for url in random_selection:
        if url.endswith(('.jpg', '.jpeg', '.png')):
            bot.send_photo(chat_id=message.chat.id, photo=url)
        elif url.endswith(('.gif', '.gifv')):
            bot.send_animation(chat_id=message.chat.id, animation=url)


max_usage_per_day = 3

@bot.message_handler(commands=['kazik'])
def kazik(message):
    player_id = str(message.from_user.id)

    # Check if the user has exceeded the usage limit for today
    if player_id in pisunchik:
        last_usage_time = pisunchik[player_id]['casino_last_used']
        current_time = datetime.now(timezone.utc)

        # Calculate the time elapsed since the last usage
        time_elapsed = current_time - last_usage_time

        # If less than 24 hours have passed, and the usage limit is reached, deny access
        if time_elapsed < timedelta(days=1) and pisunchik[player_id]['casino_usage_count'] >= max_usage_per_day:
            bot.send_message(message.chat.id,
                             f"Вы достигли лимита использования команды на сегодня.\n Времени осталось: {timedelta(days=1) - time_elapsed}")
            return
        elif time_elapsed >= timedelta(days=1):
            # If 24 hours have passed since the last usage, reset the usage count
            pisunchik[player_id]['casino_usage_count'] = 0

    # Update the last usage time and count for the user
    if player_id not in pisunchik:
        bot.send_message(message.chat.id, 'Вы не зарегистрированы как игрок')
        return
    else:
        pisunchik[player_id]['casino_last_used'] = datetime.now(timezone.utc)
        pisunchik[player_id]['casino_usage_count'] += 1

    result = bot.send_dice(message.chat.id, emoji='🎰')
    if result.dice.value in {64, 1, 22, 43}:
        time.sleep(4)
        bot.send_message(message.chat.id, "ДЕКПОТ! Вы получаете 300 BTC!")
        pisunchik[player_id]['coins'] += 300

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

    elif player_id == "1561630034":
        markup = types.InlineKeyboardMarkup()
        max_button = types.InlineKeyboardButton(text="Макс", callback_data="otsos_max")
        markup.add(max_button)
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
        time.sleep(3)

        number = random.randint(1, 2)
        if number == 1:
            bot.send_message(call.message.chat.id, "Вы отсосали Юре. У него член: Встал :)")
        else:
            bot.send_message(call.message.chat.id, "Вы отсосали Юре. У него член: Не встал :(")

    elif call.data == "otsos_max":
        bot.send_message(call.message.chat.id, "Вы отсасываете Максу...")
        time.sleep(3)

        number = random.randint(1, 2)
        if number == 1:
            bot.send_message(call.message.chat.id, "Вы отсосали Максу. У него член: Встал :)")
        else:
            bot.send_message(call.message.chat.id, "Вы отсосали Максу. У него член: Не встал :(")

    elif call.data == "otsos_bogdan":
        bot.send_message(call.message.chat.id, "Вы отсасываете Богдану...")
        time.sleep(3)

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
        items = data['items']
        last_used = data['last_used']
        last_prezervativ = data['last_prezervativ']
        ballzzz_number = data['ballzzz_number']
        casino_last_used = data['casino_last_used'],
        casino_usage_count = data['casino_usage_count']
        cursor.execute(
            "INSERT INTO pisunchik_data (player_id, pisunchik_size, coins, items, last_used, last_prezervativ, ballzzz_number, casino_last_used, casino_usage_count) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (player_id, pisunchik_size, coins, items, last_used, last_prezervativ, ballzzz_number, casino_last_used,
             casino_usage_count))

    conn.commit()


@bot.message_handler(commands=['sendtogroup'])
def send_to_group_command(message):
    # Ask the user to send the message they want to forward
    bot.send_message(message.chat.id, "Please send the message you want to forward to the group chat.")


# Handle user messages for sending a message to the group
@bot.message_handler(func=lambda message: True, content_types=['text'])
def handle_send_to_group_message(message):
    # Check if the user's message is a reply to the "sendtogroup" command
    if message.reply_to_message and message.reply_to_message.text == "Please send the message you want to forward to the group chat.":
        # Forward the user's message to the group chat
        bot.send_message(-1001294162183, message.text)
        bot.send_message(message.chat.id, "Your message has been sent to the group chat.")
    if message.from_user.id == 742272644:
        if message.text == '🤓':
            bot.send_message(message.chat.id, "Ойой, ты добаловался, наказан на 10 минут)")
            bot.send_message(message.chat.id, "Пока-пока 🤓")
            time.sleep(2)
            bot.restrict_chat_member(message.chat.id, message.from_user.id,
                                     until_date=datetime.now() + timedelta(minutes=10), permissions=None)


# Define the GIF or emoji you want to detect
specified_gifs = ['AgAD0wIAAsz-DFM', 'AgADGAMAAlMkDVM', 'AgAD9QIAAnD8DVM', 'AgADQQMAAlJEBFM', 'AgAD9iUAAkE6yEo',
                  'AgADLwMAAkik1FI']


@bot.message_handler(content_types=['animation'])
def handle_message(message):
    if message.from_user.id == 742272644:
        if message.content_type == 'animation':
            # Check if the message is an animation (GIF)
            if message.animation.file_unique_id in specified_gifs:
                # User sent the specified GIF, take some action
                bot.send_message(message.chat.id, "Ойой, ты добаловался, наказан на 10 минут)")
                bot.send_message(message.chat.id, "Пока-пока 🤓")
                time.sleep(2)
                bot.restrict_chat_member(message.chat.id, message.from_user.id,
                                         until_date=datetime.now() + timedelta(minutes=10), permissions=None)


bot.polling()
