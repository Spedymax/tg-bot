import time

import telebot.apihelper
import random
from BotFunctions.BotAnswer import send_furry_pics
from BotFunctions.Rofl import get_furry_images

bot_token = "1469789335:AAHtRcVSuRvphCppLp57jD14kUY-uUhG99o"
bot = telebot.TeleBot(bot_token)
print("Bot started")

image_urls2 = get_furry_images()
print(f'Наказание отправлено :))))')
for i in range(1, 15):
    send_furry_pics(random, bot, image_urls2, 855951767)
    time.sleep(3)
