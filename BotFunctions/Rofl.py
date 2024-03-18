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


def get_furry_images():
    # Get the URL of the furry image website.
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

def send_furry_pics(message, random, bot):
    random_selection = random.sample(image_urls2, 5)
    for url in random_selection:
        if url.endswith(('.jpg', '.jpeg', '.png')):
            bot.send_photo(chat_id=message.chat.id, photo=url)
        elif url.endswith(('.gif', '.gifv')):
            bot.send_animation(chat_id=message.chat.id, animation=url)

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
