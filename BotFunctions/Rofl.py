import requests
from bs4 import BeautifulSoup
from telebot import types
import random
import time

def misha(message, bot, time):
    bot.send_message(message.chat.id, 'Миша!')
    time.sleep(3)
    bot.send_message(message.chat.id, 'Миша привет!')
    time.sleep(3)
    bot.send_message(message.chat.id,
                     'Мммииишааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааааа')


def zov(message, bot):
    bot.send_message(message.chat.id, 'ZOV Z Z Z ZA СВОих СВО ГОЙДА ГОЙДА Z Z ZZZ ZOV ZOV СВО')


def get_furry_images(category="cute", count=5):
    """
    Fetches a list of furry image URLs from Jay's Furry API.

    Parameters:
      category (str): API category to use; should be one of "cute", "meme", or "yiff".
      count (int): Number of images to fetch.

    Returns:
      list[str]: List of image URLs.
    """
    base_url = "https://193.161.193.99:63393"
    image_urls = []
    for _ in range(count):
        response = requests.get(f"{base_url}/{category}")
        if response.status_code == 200:
            # Assuming the API returns the image URL as plain text.
            image_url = response.text.strip()
            image_urls.append(image_url)
        else:
            print(f"Error fetching {category} image: {response.status_code}")
    return image_urls


image_urls2 = get_furry_images()
print("Loaded")


def send_furry_pics(message, bot, category="cute", count=5):
    """
    Selects a set of furry image URLs from Jay's Furry API and sends them via Telegram.

    Parameters:
      message: Telegram message object.
      bot: Telegram bot instance.
      category (str): Category of images to fetch ("cute", "meme", "yiff").
      count (int): Number of images to send.
    """
    image_urls = get_furry_images(category, count)
    # Alternatively, if you want a random selection from a larger pool, you can fetch more and then use sample()
    # image_urls = get_furry_images(category, count * 2)
    # image_urls = sample(image_urls, count)

    for url in image_urls:
        if url.endswith(('.jpg', '.jpeg', '.png')):
            bot.send_photo(chat_id=message.chat.id, photo=url)
        elif url.endswith(('.gif', '.gifv')):
            bot.send_animation(chat_id=message.chat.id, animation=url)
        else:
            # For other file types, you might want to send as a document or handle accordingly.
            bot.send_message(chat_id=message.chat.id, text=f"Image: {url}")

def otsos(message, pisunchik, bot):
    chat_id = message.chat.id
    user_id = str(message.from_user.id)

    # Filter pisunchik to include only users in the current chat and exclude the user who triggered the command
    local_players = {player_id: data for player_id, data in pisunchik.items() if
                     bot.get_chat_member(chat_id, int(player_id)).status != 'left' and player_id != user_id}

    markup = types.InlineKeyboardMarkup()
    for player_id, data in local_players.items():
        button = types.InlineKeyboardButton(text=f"{data['player_name']}", callback_data=f"otsos_{player_id}")
        markup.add(button)

    bot.send_message(chat_id,
                     "Кому отсасываем?",
                     reply_markup=markup, parse_mode='html')

def otsos_callback(call, bot, pisunchik):
    bot.edit_message_reply_markup(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=None
    )
    user_id = int(call.data.split('_')[1])  # Получаем ID пользователя из callback data
    user_name = pisunchik[str(user_id)]['player_name']
    bot.send_message(call.message.chat.id, f"Вы отсасываете пользователю {user_name}...")
    time.sleep(3)

    number = random.randint(1, 2)
    if number == 1:
        bot.send_message(call.message.chat.id, f"Вы отсосали пользователю {user_name}. У него член: Встал :)")
    else:
        bot.send_message(call.message.chat.id, f"Вы отсосали пользователю {user_name}. У него член: Не встал :(")
