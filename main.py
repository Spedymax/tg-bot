import telebot.apihelper
import random
from datetime import datetime, timedelta, timezone
from telebot import types
import time
import os
import psycopg2
import requests
from bs4 import BeautifulSoup

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
    cursor.execute("SELECT player_id, pisunchik_size, coins, items FROM pisunchik_data")
    data = cursor.fetchall()
    player_data = {}

    for player_id, pisunchik_size, coins, items_list in data:
        # Check if 'items_list' is None or an empty list, and provide a default value
        if items_list is None or not items_list:
            items = []  # Default to an empty list
        else:
            items = items_list  # No need for conversion, it's already a list

        player_data[str(player_id)] = {
            'pisunchik_size': pisunchik_size,
            'coins': coins,
            'items': items,
        }

    return player_data


# Function to load player data from the database
def load_lastUsed_data():
    cursor.execute("SELECT player_id, last_used FROM last_used_data")
    data = cursor.fetchall()
    return {str(player_id): last_used for player_id, last_used in data}


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

shop_prices = {
    'kolczo_na_chlen': 90,
    'bdsm_kostumchik': 100,

    'kubik_seksa': 40,
    'prezervativ': 150,

    'krystalnie_ballzzz': 10,
    'smazka': 140,

    'zelie_pisunchika': 45,
    'Masturbator(Юра)': 130,

    'pisunchik_potion_small': 30,
    'pisunchik_potion_medium': 40,
    'pisunchik_potion_large': 50

}

item_desc = {
    'kolczo_na_chlen': '{Пассивка} 20% шанс того что при использовании /pisunchik количество подученного BTC будет удвоено.',
    'bdsm_kostumchik': '{Пассивка} 10% шанс того что при использовании /pisunchik вы получите +5 см к писюнчику',

    'kubik_seksa': '{Пассивка} "При использовании /roll, стоимость броска на 50 процентов дешевле',
    'prezervativ': '{Пассивка} Если при использовании /pisunchik выпало отрицалеьное число то писюнчик не уменьшается. КД - 4 дня',

    'krystalnie_ballzzz': '{Активное} Показывает сколько выпадет при использовании /pisunchik в следующий раз',
    'smazka': '{Аксивное} Можно использовать /pisunchik еще раз, раз в неделю',

    'zelie_pisunchika': '{Съедобное} Моментально увеличивает писюнчик на 20 или -20 см. Шанс 50 на 50',
    'Masturbator(Юра)': '{Съедобное} Позволяет с честью пожертвовать размером своего писюнчика ради получения монет. Чем большим размером пожертвовано, тем больше монет выиграно. 1 см = 1 монета + 1 монета за каждые 5 см.',
    'pisunchik_potion_small': '{Съедобное} Моментально увеличивает писюнчик на 3 см',
    'pisunchik_potion_medium': '{Съедобное} Моментально увеличивает писюнчик на 5 см',
    'pisunchik_potion_large': '{Съедобное} Моментально увеличивает писюнчик на 10 см'

}


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


@bot.message_handler(commands=['smazka'])
def reset_pisunchik_cooldown(message):
    player_id = str(message.from_user.id)
    if 'smazka' in pisunchik[player_id]['items']:
        reset_timestamp = datetime(2000, 1, 1, tzinfo=timezone.utc)

        # Update the last_used column in the last_used_data table for the specific player
        cursor.execute("UPDATE last_used_data SET last_used = %s WHERE player_id = %s", (reset_timestamp, player_id))
        conn.commit()
        conn.close()

        # Provide a response to the user
        bot.reply_to(message, "Кулдаун для команды /pisunchik сброшен. Теперь вы можете использовать её снова.")
    else:
        bot.reply_to(message, "У вас нет предмета 'smazka'(")

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
        number2 = random.randint(5, 15)
        # Check if the player has 'kolczo_na_chlen' in their inventory and apply its effect
        if 'kolczo_na_chlen' in pisunchik[player_id]['inventory'] and random.random() <= 0.2:
            number2 *= 2  # Double the amount of BTC

        # Check if the player has 'bdsm_kostumchik' in their inventory and apply its effect
        if 'bdsm_kostumchik' in pisunchik[player_id]['inventory'] and random.random() <= 0.1:
            number += 5  # Add +5 cm to the pisunchik size

        # Check if the player has 'prezervativ' in their inventory and apply its effect
        if 'prezervativ' in pisunchik[player_id]['inventory'] and number < 0:
            # Check if enough time has passed since the last 'prezervativ' usage
            if datetime.now() - last_used[player_id]['last_prezervativ'] >= timedelta(days=4):
                number = 0
                pisunchik[player_id]['pisunchik_size'] += number
                pisunchik[player_id]['last_prezervativ'] = datetime.now()
            else:
                bot.reply_to(message, "'prezervativ' еще на кулдауне.")
                return

        pisunchik[player_id]['pisunchik_size'] += number
        pisunchik[player_id]['coins'] = pisunchik[player_id]['coins'] + number2

        # Construct the reply message based on the effects of the items
        reply_message = f"Ваш писюнчик: {pisunchik[player_id]['pisunchik_size']} см\nИзменения: {number} см\nТакже вы получили: {number2} BTC"

        if 'kolczo_na_chlen' in pisunchik[player_id]['inventory'] and random.random() <= 0.2:
            reply_message += "\nЭффект от 'kolczo_na_chlen': количество подученного BTC УДВОЕНО!."

        if 'bdsm_kostumchik' in pisunchik[player_id]['inventory'] and random.random() <= 0.1:
            reply_message += "\nЭффект от 'bdsm_kostumchik': +5 см к писюнчику получено."

        if 'prezervativ' in pisunchik[player_id]['inventory'] and number < 0:
            reply_message += "\nЭффект от 'prezervativ': писюнчик не уменьшился."

        bot.reply_to(message, reply_message)

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


@bot.message_handler(commands=['items'])
def show_items(message):
    player_id = str(message.from_user.id)

    if player_id in pisunchik:
        user_items = pisunchik[player_id]['items']

        if not user_items:
            bot.reply_to(message, "You don't have any items.")
            return

        item_descriptions = []
        for item in user_items:
            if item in item_desc:
                item_descriptions.append(f"{item}: {item_desc[item]}")

        if item_descriptions:
            items_text = "\n".join(item_descriptions)
            bot.reply_to(message, f"Your items:\n{items_text}")
        else:
            bot.reply_to(message, "No item descriptions available.")
    else:
        bot.reply_to(message, "You are not registered as a player.")

# Function to display available items in the shop
def display_shop_items():
    shop_items = "\n".join([f"{item}: {price} coins" for item, price in shop_prices.items()])
    return f"Available items in the shop:\n{shop_items}"


@bot.message_handler(commands=['shop'])
def show_shop(message):
    player_id = str(message.from_user.id)
    user_balance = pisunchik[player_id]['coins']

    # Display available items and prices
    shop_message = display_shop_items()
    shop_message += f"\n\nYour current balance: {user_balance} coins"

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
            confirm_button = types.InlineKeyboardButton("Yes", callback_data=f"buy_confirm_{item_name}")
            cancel_button = types.InlineKeyboardButton("No", callback_data="buy_cancel")
            markup.add(confirm_button, cancel_button)

            # Ask for confirmation
            confirmation_message = f"Do you want to buy {item_name} for {item_price} coins?"
            bot.send_message(message.chat.id, confirmation_message, reply_markup=markup)
        else:
            bot.reply_to(message, "You don't have enough coins to buy this item.")
    else:
        bot.reply_to(message, "Item not found in the shop.")


@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_confirm_"))
def confirm_purchase(call):
    bot.edit_message_reply_markup(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=None
    )
    player_id = str(call.from_user.id)
    item_name = call.data.split("_")[2]  # Extract item name from the callback data
    item_price = shop_prices.get(item_name, 0)

    user_balance = pisunchik[player_id]['coins']

    if user_balance >= item_price:
        # Deduct the item price from the user's balance
        pisunchik[player_id]['coins'] -= item_price
        # Add the item to the user's inventory
        pisunchik[player_id]['items'].append(item_name)

        # Update the 'items' field in the database with the new item list
        update_items(player_id, pisunchik[player_id]['items'], pisunchik[player_id]['coins'])

        bot.send_message(call.message.chat.id, f"You bought {item_name} for {item_price} coins.")
    else:
        bot.send_message(call.message.chat.id, "You don't have enough coins to buy this item.")


@bot.callback_query_handler(func=lambda call: call.data == "buy_cancel")
def cancel_purchase(call):
    bot.edit_message_reply_markup(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=None
    )
    bot.send_message(call.message.chat.id, "Purchase canceled.")


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


@bot.message_handler(commands=['furrypics'])
def send_furry_pics(message):
    random_selection = random.sample(image_urls2, 5)
    for url in random_selection:
        if url.endswith(('.jpg', '.jpeg', '.png')):
            bot.send_photo(chat_id=message.chat.id, photo=url)
        elif url.endswith(('.gif', '.gifv')):
            bot.send_animation(chat_id=message.chat.id, animation=url)


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
        items = data['items']
        cursor.execute("INSERT INTO pisunchik_data (player_id, pisunchik_size, coins, items) VALUES (%s, %s, %s, %s)",
                       (player_id, pisunchik_size, coins, items))
    cursor.execute("DELETE FROM last_used_data")
    for player_id, last_used_time in last_used.items():
        cursor.execute("INSERT INTO last_used (player_id, last_used_time) VALUES (%s, %s)",
                       (player_id, last_used))
    conn.commit()


bot.polling()
