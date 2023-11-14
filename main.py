import telebot.apihelper
import random
from datetime import datetime, timedelta, timezone
from telebot import types
import time
import os
import psycopg2
import requests
from bs4 import BeautifulSoup
import threading
import json
from openai import OpenAI
import Crypto
from openpyxl import load_workbook

encrypted_file = 'encrypted.xlsx'  # Replace with path for the encrypted file
decrypted_file = 'decrypted.xlsx'  # Replace with path for the decrypted file

Crypto.decrypt_file(encrypted_file, decrypted_file)

workbook = load_workbook(filename='decrypted.xlsx')
sheet = workbook.active  # Assumes you want the active sheet

# Read the value from cell A1
a1_value = sheet['A1'].value

client = OpenAI(
    api_key=f'{a1_value}'
)
client.models.list()

headers = {
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {client.api_key}',
}

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
            elif column_name == 'characteristics':
                # Convert the characteristics dictionary to a JSON string.
                characteristics = json.dumps(column_value)

                # Load the characteristics JSON string into a Python dictionary.
                player_dict['characteristics'] = json.loads(characteristics) if characteristics is not None else {}
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
VIKA_ID = 1561630034
# List of admin user IDs
admin_ids = [741542965]
# Dictionary to keep track of admin actions
admin_actions = {}

xarakteristiks = ['Gold', 'Glowing', 'Titan', 'Invisible', 'Big Black', 'Hot']

xarakteristiks_desc = {
    'Gold': 'Ахуеть, у вас теперь золотой член! Ежедневно приносит по 1 BTC. Можно улучшить чтобы увеличить количество ежедневной прибыли на 3 BTC',
    'Glowing': 'У вас член излучает свет!! Пока другие участники ослеплены вы можете каждую неделю незаметно красть у другого участника 2 см и прибавлять их себе. Можно улучшить чтобы красть на 2 см больше.',
    'Titan': 'Теперь ваш член титановый, и пиздец тяжёлый :( Вы угрожаете админу, благодаря этому кулдаун /pisunchik уменьшен только для вас на 3%. Можно улучшить чтобы добавить уменьшение кулдауна на 3%',
    'Invisible': 'Ваш член пропал!!! Вернее он теперь просто невидимый. Балгодаря этой уловке вы можете использовать комманду /roll абсолютно бесплатно с 3% шансом. Никто и не заметит :). Можно улучшить чтобы повысить шанс бесплатного прокрута на 3%',
    'Big Black': 'Теперь ваш член просто огроменный чёрный хуй. Ваш член не может стать меньше чем 0 см. Можно улучшить чтобы увеличить порог минимального размера писюнчика на 3 см',
    'Hot': 'У вас просто расскалённая лава между ног. Вы перегреваете магазинный апарат когда подходите к нему, так что теперь всё для вас на 5% дешевле. Можно улучшить чтобы получть дополнительные 3% скидки.'
}

statuetki_prices = {
    'Pudginio': 50,
    'Ryadovoi Rudgers': 100,
    'Polkovnik Buchantos': 150,
    'General Chin-Choppa': 200
}

statuetki_desc = {
    'Pudginio': 'Вы чувстуете огромную силу, которая переполняет ваше тело',
    'Ryadovoi Rudgers': 'Вы чувстуете невероятную ловкость, в ваших руках',
    'Polkovnik Buchantos': 'Вы чувстуете потрясающий интелект в вашей голове',
    'General Chin-Choppa': 'Самая обычная статуэтка :)'
}

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
    'shaurma': 150,

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


@bot.message_handler(commands=['giveChar'])
def add_characteristic(message):
    player_id = str(message.from_user.id)
    characteristic = random.choice(list(xarakteristiks))

    if player_id in pisunchik:
        existing_characteristic = pisunchik[player_id]['characteristics']
        n = 0
        if existing_characteristic is not None:
            while True:
                # Check if the characteristic is already in the player's characteristics
                characteristic_name = characteristic.split(":")[0]
                if any(char.startswith(characteristic_name + ":") for char in existing_characteristic):
                    characteristic = random.choice(list(xarakteristiks))
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


@bot.message_handler(commands=['characteristics'])
def show_characteristics(message):
    player_id = str(message.from_user.id)
    if player_id in pisunchik:
        characteristics_text = "Ваши характеристики:\n"
        existing_characteristic = pisunchik[player_id]['characteristics']
        for characteristic in existing_characteristic:
            characteristic_name, current_level = characteristic.split(":")
            if characteristic_name in xarakteristiks_desc:
                current_level = int(current_level)
                characteristics_text += f"{characteristic_name}(Level {current_level}): {xarakteristiks_desc[characteristic_name]}\n"
        bot.reply_to(message, characteristics_text)
    else:
        bot.reply_to(message, "You are not registered as a player.")


@bot.message_handler(commands=['upgrade_char'])
def upgrade_characteristic(message):
    player_id = str(message.from_user.id)
    if player_id in pisunchik:
        existing_characteristic = pisunchik[player_id]['characteristics']

        # Check if the player has any characteristics to upgrade
        if existing_characteristic is not None:
            # Send a message asking the user to select a characteristic to upgrade

            # Create a list of inline keyboard buttons for each characteristic
            characteristic_buttons = []
            for characteristic in existing_characteristic:
                characteristic_name, current_level = characteristic.split(":")
                button_text = f"{characteristic_name} (Level {current_level})"
                characteristic_buttons.append(
                    types.InlineKeyboardButton(text=button_text, callback_data=f"upgrade_{characteristic}"))

            # Create an inline keyboard with the characteristic buttons
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(*characteristic_buttons)

            # Send the keyboard to the user
            bot.send_message(message.chat.id, "Выберите характеристику для улучшения:", reply_markup=keyboard)
        else:
            bot.send_message(message.chat.id, "У вас нету характристик для улучшения.")
    else:
        bot.send_message(message.chat.id, "You are not registered as a player.")


@bot.callback_query_handler(func=lambda call: call.data.startswith("upgrade"))
def handle_characteristic_upgrade(call):
    chat_id = call.message.chat.id
    player_id = str(call.from_user.id)
    call2 = call
    call = call.data.split("_", 1)  # Split the callback data into action and player
    selected_characteristic = call[1]

    # Get the player's ID

    # Check if the player has enough coins to perform the upgrade (assuming a cost of 10 coins per upgrade)

    if pisunchik[player_id]['coins'] >= 100:
        # Deduct 100 coins from the player's balance
        pisunchik[player_id]['coins'] -= 100

        # Extract the characteristic name and current level
        characteristic_name, current_level = selected_characteristic.split(":")
        current_level = int(current_level)
        if current_level >= 15:
            bot.send_message(call2.message.chat.id, "Вы уже достигли максимального уровня этой характеристики :)")
            return

        # Increase the level of the characteristic by 1
        new_level = current_level + 1
        updated_characteristic = f"{characteristic_name}:{new_level}"
        n = 0
        for characteristic in pisunchik[player_id]['characteristics']:
            if selected_characteristic == characteristic:
                pisunchik[player_id]['characteristics'][n] = updated_characteristic
                save_data()
            n += 1
        save_data()

        # Send a message to confirm the upgrade
        bot.send_message(chat_id, f"Вы улучшили {characteristic_name} до лвла {new_level}!")
    else:
        # Send a message if the player doesn't have enough coins
        bot.send_message(chat_id, "У вас недостаточно денег для улучшения (Надо 100)")


strochki = [
    'Вы видите вдалеке Торговца с караваном.',
    'Подходя ближе, вы замечаете, что это статный мужчина в белом пальто с черными, как бездна очками.',
    'Он подносит руку к голове, снимая огромную шляпу, и делает маленький поклон в вашу сторону:',
    '"Здравствуйте, путники, приятно видеть живых людей на этом бескрайнем клочке земли"',
    '"Я побуду здесь некоторое время, переведу дух, а вы пока можете изучить мой товар" *подмигивает*',
    '"Прошу, не стейсняйтесь" /statuetkiShop',
]


@bot.message_handler(commands=['torgovec'])
def torgovec(message):
    for line in strochki:
        bot.send_message(message.chat.id, line)
        time.sleep(5)


@bot.message_handler(commands=['misha'])
def misha(message):
    bot.send_message(message.chat.id, 'Миша!')
    time.sleep(3)
    bot.send_message(message.chat.id, 'Миша привет!')
    time.sleep(3)
    bot.send_message(message.chat.id,
                     'Мммииишааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааа')


@bot.message_handler(commands=['sho_tam_novogo'])
def get_recent_messages(message):
    bot.send_message(message.chat.id, "Ожидайте, анализирую сообщения...")
    cursor.execute("SELECT name, message_text FROM messages")
    converted_string = '\n'.join(f'{name}: {phrase}' for name, phrase in cursor.fetchall())
    data = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {"role": "system",
             "content": "Ты бот анализатор. Тебе будут давать сообщения от пользователей, твоё задание сделать краткую сводку того о чем была речь в этих сообщениях. Разделяй каждую отдельную тему на абзацы"},
            {"role": "system",
             "content": "Начинай своё сообщение с: За последние 12 часов речь шла о том что: *и потом перечень того о чём шла речь*"},
            {"role": "user", "content": f"{converted_string}"},
        ],
        "temperature": 0.7
    }
    response = requests.post('https://api.openai.com/v1/chat/completions', headers=headers, data=json.dumps(data))
    response_data = response.json()
    bot.send_message(message.chat.id, f"{response_data['choices'][0]['message']['content']}")


# Function to send prompt to OpenAI and get a response
def ask_openai(prompt):
    data = {
        "model": "gpt-3.5-turbo",  # or another model you prefer
        "messages": [
            {
                "role": "user",
                "content": f"{prompt}"}
        ],
        "temperature": 0.7
    }

    response = requests.post('https://api.openai.com/v1/chat/completions', headers=headers, data=json.dumps(data))
    response_data = response.json()
    return response_data['choices'][0]['message']['content']


# Handler for messages mentioning the bot
@bot.message_handler(func=lambda message: f"@GgAllMute" in message.text)
def handle_mention(message):
    # Extract text following the bot's username
    prompt = message.text.split("@GgAllMute_bot", 1)[1].strip()
    if prompt:
        bot.send_message(message.chat.id, "Подождите, обрабатываю запрос...")
        response_text = ask_openai(prompt)
        bot.reply_to(message, response_text)


@bot.message_handler(commands=['imagine'])
def imagine(message):
    prompt = message.text.split("/imagine", 1)[1].strip()
    if prompt:
        bot.send_message(message.chat.id, "Подождите, обрабатываю запрос...")
        response = client.images.generate(
            model="dall-e-3",
            prompt=f"{prompt}",
            size="1024x1024",
            quality="standard",
            n=1,
        )
        image_url = response.data[0].url
        print(image_url)
        bot.send_photo(message.chat.id, image_url)


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
            strochki2 = [
                'Вы замечаете что на вас пристально смотрит торговец',
                '"О, я вижу вы собрали все 4 статуэтки"',
                '"Насколько я знаю мне нужно сделать вот это", сказал загадочный торговец, копошась в своём рюкзаке',
                'Он достал из неё маленький флакончик с фиолетовым содержимым.',
                '"Пожулуйста, покажите ваши статуэтки"',
                'Вы вынимаете их и раскаладываете на стол.',
                'Торговец капает фиолетовую жидкость на каждую из статуэток',
                '"Смотрите внимательнее, сейчас произойдёт нечто", произносит он и отходит на 3 метра назад.',
                '...',
                '.....',
                '"*Ничего не происходит*(кроме того что юра так и не поменял обосранные штаны после шаурмы)"',
                '"Хммм, что же могло пойти не так, я всё делал по инструкции"',
                'Вы подходите к стутэткам и осматриваете их со всех сторон, но ничего необычного не замечаете. Только надписи - Капрал, Генерал, которые вы уже видели',
                'Попробовав расставить их в порядке возрастания ранга, вы замечаете что первая статуэтка начинает мерцать',
                'Вскоре уже все статуэтки синхронно излучают свет с одинаковой частотой, всё ускоряясь и ускоряясь.',
                'Вас ослепляет яркий свет и вы лишь краем глаза успеваете заметить как статуэтки сливаються в одну большую золотую статуэтку',
                'И надпись на небе "ПУДЖИНИО-ФАМОЗА"',
                'Статуэтка стремительно летит к вам, но под странным углом, как будто-бы она хочет...',
                'ОНА ОТКУСИЛА ВАМ ЧЛЕН!!!!',
                'А...',
                'Совсем не больно...',
                'Золотая фигура взлетает в небо и начинает вертеться с огромной скоростью',
                'Опять яркая вспышка!',
                'Статуэтка пропадает, а ваш член снова на месте.',
                '*Поздравляю вы разблокировали новую характеристику для вашего члена*',
                '*Посмотреть какую характеристику вы получили можно испозовав команду /characteristics*',
            ]

            for line in strochki2:
                time.sleep(5)
                bot.send_message(message.chat.id, line)

            add_characteristic(message)

    else:
        bot.reply_to(message, "Вы не зарегистрированы как игрок")


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
def display_shop_items(player):
    existing_characteristic = pisunchik[player]['characteristics']
    # Check if the characteristic is already in the player's characteristics
    player_name = get_player_name(player)
    characteristic_name = "Hot"
    shop_items = " "
    global discount
    if existing_characteristic is not None:
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
    shop_message = display_shop_items(player_id)
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
        url = "https://www.deviantart.com/tag/furries" + str(x)
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
    for i in range(1, 4):
        player_id = str(message.from_user.id)

        # Check if the user has exceeded the usage limit for today
        if player_id in pisunchik:
            last_usage_time = pisunchik[player_id]['casino_last_used']
            current_time = datetime.now(timezone.utc)

            # Calculate the time elapsed since the last usage
            time_elapsed = current_time - last_usage_time

            # If less than 24 hours have passed, and the usage limit is reached, deny access
            if time_elapsed < timedelta(hours=24) and pisunchik[player_id]['casino_usage_count'] >= max_usage_per_day:
                bot.send_message(message.chat.id,
                                 f"Вы достигли лимита использования команды на сегодня.\n Времени осталось: {timedelta(days=1) - time_elapsed}")
                return
            elif time_elapsed >= timedelta(hours=24):
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
        if result.dice.value in {64}:
            time.sleep(4)
            bot.send_message(message.chat.id, "ДЕКПОТ! Вы получаете 300 BTC!")
            pisunchik[player_id]['coins'] += 300
        elif result.dice.value in {1, 22, 43}:
            time.sleep(4)
            bot.send_message(message.chat.id, "Сори, джекпот только для трёх семёрок((")

    save_data()


@bot.message_handler(commands=['prosipaisya'])
def prosipaisya(message):
    for i in range(1, 5):
        bot.send_message(message.chat.id,
                         f"<a href='tg://user?id={BODYA_ID}'>@lofiSnitch</a>",
                         parse_mode='html')


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


@bot.callback_query_handler(func=lambda call: call.data.startswith('otsos'))
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


@bot.message_handler(commands=['vor'])
def otsos(message):
    player_id = str(message.from_user.id)

    existing_characteristic = pisunchik[player_id]['characteristics']
    # Check if the characteristic is already in the player's characteristics
    player_name = get_player_name(player_id)
    characteristic_name = "Glowing"
    if existing_characteristic is not None:
        for char_info in existing_characteristic:
            if char_info.startswith(characteristic_name):
                char_name, char_level = char_info.split(":")
                int_level = int(char_level)

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
    else:
        bot.send_message(message.chat.id, "У вас нету нужной характеристики для писюничка :(")


@bot.callback_query_handler(func=lambda call: call.data.startswith("vor"))
def otsos_callback(call):
    bot.edit_message_reply_markup(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=None
    )
    player_id = call.from_user.id
    existing_characteristic = pisunchik[player_id]['characteristics']
    characteristic_name = "Glowing"
    vor_number = 0
    for char_info in existing_characteristic:
        if char_info.startswith(characteristic_name):
            char_name, char_level = char_info.split(":")
            int_level = int(char_level)
            vor_number = 2 + ((int_level - 1) * 2)

    if call.data == "otsos_yura":
        pisunchik[str(YURA_ID)]['pisunchik_size'] -= vor_number
        pisunchik[player_id]['pisunchik_size'] += vor_number
        bot.send_message(call.message.chat.id, f"Вы украли {vor_number} см у Юры...")
        time.sleep(3)
    elif call.data == "otsos_max":
        pisunchik[str(MAX_ID)]['pisunchik_size'] -= vor_number
        pisunchik[player_id]['pisunchik_size'] += vor_number
        bot.send_message(call.message.chat.id, f"Вы украли {vor_number} см у Макса...")

    elif call.data == "otsos_bogdan":
        pisunchik[str(BODYA_ID)]['pisunchik_size'] -= vor_number
        pisunchik[player_id]['pisunchik_size'] += vor_number
        bot.send_message(call.message.chat.id, f"Вы украли {vor_number} см у Богдана...")


def save_data():
    cursor.execute("DELETE FROM pisunchik_data")

    for player_id, data in pisunchik.items():
        columns = ', '.join(data.keys())
        placeholders = ', '.join(['%s'] * len(data))
        values = tuple(data.values())

        # Build the INSERT query dynamically.
        query = f"INSERT INTO pisunchik_data ({columns}) VALUES ({placeholders})"

        cursor.execute(query, values)

    conn.commit()


# Function to check if a user can use the /pisunchik command
def can_use_pisunchik():
    while True:
        for player in pisunchik:
            current_time = datetime.now(timezone.utc)
            last_used_time = pisunchik[player]['last_used']

            # Calculate the time difference
            time_difference = current_time - last_used_time

            # Check if the cooldown period (4 hours) has passed
            if time_difference >= timedelta(hours=24):
                # Update the last_used timestamp in the database
                if not pisunchik[player]['notified']:
                    if player != '1561630034':
                        player_name2 = get_player_name(player)
                        bot.send_message(-1001294162183,
                                         f"<a href='tg://user?id={player}'>@{player_name2}</a>, вы можете использовать /pisunchik",
                                         parse_mode='html')
                        pisunchik[player]['notified'] = True
                        save_data()
        curr_time = datetime.now(timezone.utc)
        if curr_time.hour == 12 and curr_time.minute == 0:
            for player in pisunchik:
                existing_characteristic = pisunchik[player]['characteristics']
                # Check if the characteristic is already in the player's characteristics
                player_name = get_player_name(player)
                characteristic_name = "Gold"
                n = 0
                if existing_characteristic is not None:
                    for char_info in existing_characteristic:
                        if char_info.startswith(characteristic_name):
                            char_name, char_level = char_info.split(":")
                            int_level = int(char_level)
                            income = 1 + ((int_level - 1) * 3)
                            pisunchik[player]['coins'] += income
                            bot.send_message(-1001294162183,
                                             f"{player_name}, ваш золотой член принёс сегодня прибыль в размере {income} BTC")

        if curr_time.hour == 6 and curr_time.minute == 0:
            for i in range(1, 5):
                bot.send_message(-1001294162183,
                                 f"<a href='tg://user?id={BODYA_ID}'>@lofiSnitch</a>",
                                 parse_mode='html')
            with open('Napominalka.wav', 'rb') as audio_file:
                bot.send_audio(-1001294162183, audio_file)
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

        time.sleep(60)  # Sleep for 1 minute (adjust as needed)


# Define a function to start the cooldown checking thread
def start_cooldown_check_thread():
    cooldown_check_thread = threading.Thread(target=can_use_pisunchik)
    cooldown_check_thread.daemon = True
    cooldown_check_thread.start()


start_cooldown_check_thread()


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

    # If message count is greater than 199, delete the oldest ones
    if message_count > 150:
        # Find out how many messages to delete to get back to 199
        delete_count = message_count - 150
        cursor.execute("""
                DELETE FROM messages 
                WHERE id IN (
                    SELECT id FROM messages 
                    ORDER BY timestamp ASC 
                    LIMIT %s
                )
            """, (delete_count,))
        conn.commit()


@bot.message_handler(content_types=['animation'])
def handle_message(message):
    if message.from_user.id == 742272644:
        if message.content_type == 'animation':
            time.sleep(2)
            bot.send_message(message.chat.id, "Ойой, ты добаловался, наказан на 5 минут)")
            time.sleep(2)
            bot.send_message(message.chat.id, "Пока-пока 🤓")
            time.sleep(2)
            bot.restrict_chat_member(message.chat.id, message.from_user.id,
                                     until_date=datetime.now() + timedelta(minutes=5), permissions=None)


bot.polling()
# 741542965
