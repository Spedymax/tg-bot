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
        "расскажи анекдот про маму Максима": "Шутка"
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
