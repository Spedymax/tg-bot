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
    cursor.execute(
        "SELECT player_id, pisunchik_size, coins, items, last_used, last_prezervativ, ballzzz_number FROM pisunchik_data")
    data = cursor.fetchall()
    player_data = {}

    for player_id, pisunchik_size, coins, items_list, last_used, last_prezervativ, ballzzz_number in data:
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
            'ballzzz_number': ballzzz_number
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

shop_prices = {
    'kolczo_na_chlen': 90,
    'bdsm_kostumchik': 100,

    'kubik_seksa': 40,
    'prezervativ': 150,

    'krystalnie_ballzzz': 10,
    'smazka': 140,

    'zelie_pisunchika': 45,
    'masturbator': 50,

    'pisunchik_potion_small': 30,
    'pisunchik_potion_medium': 40,
    'pisunchik_potion_large': 50

}

item_desc = {
    'kolczo_na_chlen': '{Пассивка} 20% шанс того что при использовании /pisunchik количество подученного BTC будет удвоено.',
    'bdsm_kostumchik': '{Пассивка} 10% шанс того что при использовании /pisunchik вы получите +5 см к писюнчику',

    'kubik_seksa': '{Пассивка} "При использовании /roll, стоимость броска на 50 процентов дешевле',
    'prezervativ': '{Пассивка} Если при использовании /pisunchik выпало отрицалеьное число то писюнчик не уменьшается. КД - 4 дня',

    'krystalnie_ballzzz': '{Активное} Показывает сколько выпадет при использовании /pisunchik в следующий раз\nИспользование: /krystalnie_ballzzz',
    'smazka': '{Аксивное} Можно использовать /pisunchik еще раз, раз в неделю\nИспользование: /smazka',

    'zelie_pisunchika': '{Съедобное} Моментально увеличивает писюнчик на 20 или -20 см. Шанс 50 на 50\nИспользование: /zelie_pisunchika',
    'masturbator': '{Съедобное} Позволяет с честью пожертвовать размером своего писюнчика ради получения монет. Чем большим размером пожертвовано, тем больше монет выиграно. 1 см = 1 монета + 1 монета за каждые 5 см.\nИспользование: /masturbator',
    'pisunchik_potion_small': '{Съедобное} Моментально увеличивает писюнчик на 3 см\nИспользование: /pisunchik_potion_small',
    'pisunchik_potion_medium': '{Съедобное} Моментально увеличивает писюнчик на 5 см\nИспользование: /pisunchik_potion_medium',
    'pisunchik_potion_large': '{Съедобное} Моментально увеличивает писюнчик на 10 см\nИспользование: /pisunchik_potion_large'

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

    if pisunchik[player_id]['last_used'].replace(tzinfo=None) >= datetime.now() and pisunchik[player_id]['last_used'] is not None:
        # Generate a random number to determine the next effect (for demonstration purposes)
        next_effect = random.randint(-10, 10)

        effect_message = f"Следующее изменение писюнчика будет: {next_effect} см."
        pisunchik[player_id]['ballzzz_number'] = next_effect

    elif pisunchik[player_id]['ballzzz_number'] is None:
        next_effect = random.randint(-10, 10)

        effect_message = f"Следующее изменение писюнчика будет: {next_effect} см."
        pisunchik[player_id]['ballzzz_number'] = next_effect
    else:
        next_effect = pisunchik[player_id]['ballzzz_number']
        effect_message = f"Следующее изменение писюнчика будет: {next_effect} см."

    bot.reply_to(message, effect_message)


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
        number = random.randint(-10, 10)
        number2 = random.randint(5, 15)
        kolzo_random = random.random()
        bdsm_random = random.random()
        ne_umenshilsya = False
        cooldown = False
        # Check if the player has 'kolczo_na_chlen' in their inventory and apply its effect
        if 'kolczo_na_chlen' in pisunchik[player_id]['items'] and kolzo_random <= 0.2:
            print(number2)
            number2 *= 2  # Double the amount of BTC
            print(number2)

        # Check if the player has 'prezervativ' in their inventory and apply its effect
        if 'prezervativ' in pisunchik[player_id]['items']:
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

        if 'krystalnie_ballzzz' in pisunchik[player_id]['items'] and pisunchik[player_id]['ballzzz_number'] is not None:
            number = pisunchik[player_id]['ballzzz_number']
            pisunchik[player_id]['ballzzz_number'] = None

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

        bot.reply_to(message, reply_message)

    save_data()


@bot.message_handler(commands=['roll'])
def update_pisunchik(message):
    player_id = str(message.from_user.id)
    if 'kubik_seksa' in pisunchik[player_id]['items']:
        pisunchik[player_id]['coins'] = pisunchik[player_id]['coins'] - 5
        bot.send_message(message.chat.id,
                         f"Вы потратили 10 BTC\nСработал kubik_seksa - Стоимость броска уменьшена на 50%")

    else:
        pisunchik[player_id]['coins'] = pisunchik[player_id]['coins'] - 10
        bot.send_message(message.chat.id, f"Вы потратили 10 BTC")

    if player_id in pisunchik:
        number = random.randint(1, 6)
        bot.reply_to(message, f"Выпало: {number}")
        if number <= 3:
            pisunchik[player_id]['pisunchik_size'] -= 5
        if number > 3:
            pisunchik[player_id]['pisunchik_size'] += 5
        bot.reply_to(message, f"Ваш писюнчик: {pisunchik[player_id]['pisunchik_size']} см\n")
    else:
        bot.reply_to(message, "Вы не зарегистрированы как игрок")

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
        "Вы можете пожертвовать часть своего писюнчика ради получения ВТС. Чем больше размер пожертвован, тем больше монет выиграно. 1 см = 1 ВТС + 1 ВТС за каждые 5 см.\n\n"
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
    coins_awarded = donation_amount + (donation_amount // 5)

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
        last_used = data['last_used']
        last_prezervativ = data['last_prezervativ']
        ballzzz_number = data['ballzzz_number']
        cursor.execute(
            "INSERT INTO pisunchik_data (player_id, pisunchik_size, coins, items, last_used, last_prezervativ, ballzzz_number) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (player_id, pisunchik_size, coins, items, last_used, last_prezervativ, ballzzz_number))

    conn.commit()


bot.polling()
