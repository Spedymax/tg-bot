import requests
from bs4 import BeautifulSoup
import random


def bot_answer(message, bot, time, dad_jokes):
    # Словарь команд и их описаний
    commands = {
        "отшлёпай Юру": "Юра отшлёпан :)",
        "расскажи что ты можешь": "Отправляет список команд",
        "отшлёпай Макса": "Нельзя шлёпать Макса :(",
        "что-то жарко стало": "Включает вентилятор",
        "расскажи анекдот": "Рассказывает анекдот",
        "расскажи анекдот про маму Юры": "Рассказывает анекдот про маму Юры",
        "расскажи анекдот про маму Богдана": "Нет.",
        "расскажи анекдот про маму Максима": "Шутка",
        "накажи Богдана": "Наказание",
    }

    # Извлекаем текст после упоминания бота
    prompt = message.text.split("Бот,", 1)[1].strip()

    # Проверяем, если запрос на список команд
    if prompt == "расскажи что ты можешь" or prompt == "что ты можешь?":
        command_list = "\n".join(commands.keys())
        bot.send_message(message.chat.id, "Вот мои команды:\n" + command_list)
    # Проверяем остальные команды
    elif prompt in commands:
        if prompt == "расскажи анекдот":
            dad_jokes(message)
        elif prompt == "накажи Богдана":
            bot.send_message(message.chat.id, "Отсылаю 9999 каринок фурри в личку Богдану :)")
            for i in range(1, 15):
                send_furry_pics(random, bot)
        elif prompt == "расскажи анекдот про маму Юры":
            bot.send_message(message.chat.id, "Ну ладно")
            with open('bezobidno.jpg', 'rb') as photo:
                time.sleep(1)
                bot.send_photo(message.chat.id, photo)
        elif prompt == "что-то жарко стало":
            bot.send_message(message.chat.id, "Понял, включаю вентилятор 卐卐卐卐卐卐卐卐卐卐卐卐卐卐卐卐卐卐卐...")
            time.sleep(5)
            bot.send_message(message.chat.id, "Чёт вентилятор сломался 卐卐卐卐卐卐, из-за грозы наверное ᛋᛋ")
            time.sleep(5)
            bot.send_message(message.chat.id, "Достаём инструменты ☭☭☭☭☭, всё починил, можно и поспать ZzzZZzZzZZZ")
        elif prompt == "расскажи анекдот про маму Максима" or prompt == "расскажи анекдот про маму Макса" or prompt == "расскажи анекдот про маму максима" or prompt == "расскажи анекдот про маму макса":
            bot.send_message(message.chat.id, "С радостью :)")
            time.sleep(3)
            bot.send_message(message.chat.id,
                             "Мама Максима попросила его друга Юру помочь с ремонтом ванной. Юра согласился и начал "
                             "разбираться с трубами.\nВ какой-то момент он спрашивает: — Мама Максима, а у вас есть "
                             "гаечный ключ?\nНа что мама отвечает:— Нет, Юра, иди нахуй")
        else:
            bot.send_message(message.chat.id, commands[prompt])
    else:
        bot.send_message(message.chat.id, "?")

def get_furry_images():
    # Get the URL of the furry image website.
    image_urls = []
    for x in range(1, 18):
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
def send_furry_pics(random, bot):
    random_selection = random.sample(image_urls2, 5)
    for url in random_selection:
        if url.endswith(('.jpg', '.jpeg', '.png')):
            bot.send_photo(chat_id=855951767, photo=url)
        elif url.endswith(('.gif', '.gifv')):
            bot.send_animation(chat_id=855951767, animation=url)