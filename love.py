import telebot
from telebot import types
import datetime, time
import random
import os
from PIL import Image, ImageDraw, ImageFont
import schedule

bot = telebot.TeleBot('6608486511:AAF_Ro0BOUXhfwBME5DM5NU_n2N7ut_PZ_U')

# Define trivia questions and answers
trivia_questions = [
    {
        "question": "Любимый цвет Максима",
        "options": ["Красный", "Синий", "Белый", "Зеленый", "Желтый"],
        "answer": "Белый"
    },
    {
        "question": "Где родился Максим?",
        "options": ["Житомир", "Ровно", "Киев", "Львов", "Одесса"],
        "answer": "Киев"
    },
    {
        "question": "Где Максим окончил первые 6 классов?",
        "options": ["лицей №142", "лицей №144", "гимназия Академия", "Лесная сказка", "Школа 5"],
        "answer": "Лесная сказка"
    },
    {
        "question": "Где Максим окончил 7-11 класы?",
        "options": ["лицей Тараса Шевч.", "гим-ия Академия", "лицей №142", "лицей 153", "гимназия №5"],
        "answer": "лицей №142"
    },
    {
        "question": "Где максим учится сейчас?",
        "options": ["Бурса", "уник им.Тар.Шевч.", "КПИ", "Не учится(работает)"],
        "answer": "КПИ"
    },
    {
        "question": "Название компании где работает Максим?",
        "options": ["Tech Industries", "McDonalds", "Google", "Anthill Agency", "Agnitio Agency"],
        "answer": "Anthill Agency"
    },
    {
        "question": "Как Макс называет своего кота?",
        "options": ["Кекс", "Скотик", "Кот", "Котик"],
        "answer": "Скотик"
    },
    {
        "question": "Как Вика подписана у Макса в тг?",
        "options": ["Котик", "Сладкая попка", "Вика", "Конкретная Вика"],
        "answer": "Котик"
    },
    {
        "question": "Любимая еда Макса?",
        "options": ["Суши", "Мороженое", "Рисовые чипсы", "Пицца", "Шашлык", "Конфеты"],
        "answer": "Пицца"
    },
    {
        "question": "Как зовут сестру Макса?",
        "options": ["Милена", "Милина", "Милана", "Малина"],
        "answer": "Милана"
    },
    {
        "question": "Какой у Макса любимый фильм?",
        "options": ["Геошторм", "Начало", "Волк с Уолл стрит", "Интерстеллар"],
        "answer": "Интерстеллар"
    },
    {
        "question": "Какой у Макса настоящий рост?(185)",
        "options": ["185", "170", "173", "215"],
        "answer": "170"
    },
    {
        "question": "Когда мы начали встречаться?",
        "options": ["2 июня", "3 июня", "в 1945 году", "Летом 2021"],
        "answer": "2 июня"
    },
    {
        "question": "Когда Макс думает мы начали встречаться?(Мяу😋)",
        "options": ["9 января", "Зимой", "Когда признался", "2 июня"],
        "answer": "2 июня"
    },
    {
        "question": "За что Макс любит Вику больше всего?",
        "options": ["За глаза", "За то что ты есть у него❤️", "За ум", "За ножки и попку"],
        "answer": "За то что ты есть у него❤️"
    },

]

# Create a dictionary to keep track of the user's progress
user_progress = {}

start_date = datetime.date(2023, 6, 2)  # Пример: 2 июня 2023 года

# Загрузите список причин из файла love.txt
with open('love.txt', 'r', encoding='utf-8') as file:
    reasons = file.read().splitlines()


@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id,
                     "Здравствуйте, Вика!\nМеня создал Максим чтобы рассказать вам как он вас любит!\nКаждый день вам будут открываться новые команды которые вы сможете использовать!\nЧерез 4 дня все команды будут открыты для вас, и вы даже сможете сделать небольшой подарок Максу!\nНапишите /commands чтобы узнать какие команды уже доступны!")


@bot.message_handler(commands=['commands'])
def get_commands(message):
    current_date = datetime.date.today()
    startuem = False
    commands = ""
    if current_date >= datetime.date(2023, 9, 6):
        commands += '/count - узнать сколько дней вы вместе\n'
    if current_date >= datetime.date(2023, 9, 7):
        commands += '/100reasons - узнать 100 причин\n'
    if current_date >= datetime.date(2023, 9, 8):
        commands += '/trivia - викторина\n/answers - ответы на викторину\n'
    if current_date >= datetime.date(2023, 9, 9):
        commands += '/create - создайте открытку\n'
    if current_date == datetime.date(2023, 9, 9):
        startuem = True
    bot.send_message(message.chat.id, f"Вам доступны команды:\n {commands}")
    if startuem:
        bot.send_message(message.chat.id,
                         "Ого! Уже завтра вы будете отмечать 100 дней вместе!\nМои поздравления!❤️\nКак насчёт создать пригласительную открытку и отправить Максу?\nНапиши /create чтобы узнать как это сделать!")


def mi():
    # Get the current time in 24-hour format
    current_time = time.strftime('%H:%M')
    current_date = datetime.date.today()

    # Check if the current time is between 9:00 and 24:00
    while '09:00' <= current_time <= '24:00' and current_date == datetime.date(2023, 9, 10):
        # Get a list of image files in the specified folder
        image_files = [f for f in os.listdir('cats')]

        if image_files:
            # Choose and send a random image to the user
            image_file = os.path.join('cats', random.choice(image_files))
            with open(image_file, 'rb') as photo:
                bot.send_photo(1561630034, photo)
                bot.send_photo(741542965, photo)
                bot.send_message(1561630034, "Мы?🥺")
        else:
            bot.send_message(741542965, "No images available to send.")
        time.sleep(60 * 30)


# 741542965
# 1561630034
mi()


@bot.message_handler(commands=['count'])
def count(message):
    current_date = datetime.date.today()
    days_count = (current_date - start_date).days
    bot.send_message(message.chat.id, f"Вы на {days_count} дне отношений! 💑")
    if current_date == datetime.date(2023, 9, 10):
        bot.send_message(message.chat.id,
                         "Поздравляю с 100 днями отношений! 🥳 Пора устроить романтическую встречу!")


# Handle the /invite command
@bot.message_handler(commands=['invite'])
def send_invitation(message):
    # Send the invitation card to the known user
    with open("invitation_card.png", "rb") as photo:
        bot.send_photo(741542965, photo)
    bot.send_message(message.chat.id, "Пригласительная открытка уже отправлена Максу!")


@bot.message_handler(commands=['100reasons'])
def show_reasons(message):
    # Создаем Inline Keyboard
    keyboard = types.InlineKeyboardMarkup()
    random_reasons_button = types.InlineKeyboardButton("10 причин(так веселее)", callback_data="reas_random_10")
    all_reasons_button = types.InlineKeyboardButton("Все сразу", callback_data="reas_all")
    keyboard.add(random_reasons_button, all_reasons_button)

    bot.send_message(message.chat.id, "Выберите, сколько причин вы хотите увидеть:", reply_markup=keyboard)


@bot.callback_query_handler(func=lambda call: call.data.startswith("reas_"))
def handle_inline_keyboard(call):
    bot.edit_message_reply_markup(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=None
    )
    if call.data == "reas_random_10":
        # Send 10 random reasons at a time
        random_reasons = random.sample(reasons, 10)
        for reason in random_reasons:
            bot.send_message(call.message.chat.id, reason)
        bot.send_message(call.message.chat.id, "Спасибо за то, что ты есть у меня!❤️")
    elif call.data == "reas_all":
        # Send all reasons in smaller chunks
        chunk_size = 50  # Adjust the chunk size as needed
        for i in range(0, len(reasons), chunk_size):
            chunk = reasons[i:i + chunk_size]
            reasons_text = "\n".join(chunk)
            bot.send_message(call.message.chat.id, reasons_text)
        bot.send_message(call.message.chat.id, "Спасибо за то, что ты есть у меня!❤️")


@bot.message_handler(commands=['trivia'])
def start_trivia(message):
    chat_id = message.chat.id

    # Initialize or reset the user's progress
    user_progress[chat_id] = {
        "current_question_index": 0,
        "correct_answers": 0
    }
    bot.send_message(chat_id, "Добро пожаловать в викторину!\nСейчас мы узнаем насколько хорошо вы знаете Макса!")

    send_next_question(chat_id)


def send_next_question(chat_id):
    current_question_index = user_progress[chat_id]["current_question_index"]

    # Check if all questions have been answered
    if current_question_index >= len(trivia_questions):
        correct_answers = user_progress[chat_id]["correct_answers"]
        bot.send_message(chat_id,
                         f"Викторина окончена! Ты правильно ответила на {correct_answers} из {len(trivia_questions)} вопросов верно. Умничка!❤️")
        return

    question_data = trivia_questions[current_question_index]
    question_text = question_data["question"]
    options = question_data["options"]

    # Create inline keyboard with answer options
    keyboard = types.InlineKeyboardMarkup()
    for option in options:
        button = types.InlineKeyboardButton(option, callback_data=f"answer_{option}")
        keyboard.add(button)

    bot.send_message(chat_id, question_text, reply_markup=keyboard)


@bot.callback_query_handler(func=lambda call: call.data.startswith("answer_"))
def handle_trivia_answer(call):
    chat_id = call.message.chat.id
    user_answer = call.data.split("_")[1]

    current_question_index = user_progress[chat_id]["current_question_index"]
    correct_answer = trivia_questions[current_question_index]["answer"]

    # Check if the user's answer is correct
    if user_answer == correct_answer:
        user_progress[chat_id]["correct_answers"] += 1

    # Move to the next question
    user_progress[chat_id]["current_question_index"] += 1

    # Remove the inline keyboard
    bot.edit_message_reply_markup(chat_id, call.message.message_id)

    # Send the next question or end the quiz
    send_next_question(chat_id)


# Helper function to end the trivia game and show results
@bot.message_handler(commands=['answers'])
def answers(message):
    user_id = message.from_user.id

    # Send a message with the user's score and correct answers
    response = f"Правильные ответы:"
    for x in range(0, 15):
        response += f"\n{trivia_questions[x]['question']}: {trivia_questions[x]['answer']}"

    bot.send_message(user_id, response)


card_text = 'TEST'
text_color = 'black'
when = 'breakfast'


@bot.message_handler(commands=['create'])
def create_card(message):
    # Просим пользователя ввести текст для открытки
    bot.send_message(message.chat.id, "Привет!\nЯ помогу тебе создать пригласительную открытку для Макса!\n")
    bot.send_message(message.chat.id,
                     "Структура такая:\n                       1                                   2                                      3\n'[Приглашаю тебя...][*Выбор мероприятия*][*Выбор фона*]'\n(Чем хуже открытка тем лучше, зато своими руками🥰)")
    bot.send_message(message.chat.id, "Сначала введи текст для открытки:")
    bot.register_next_step_handler(message, select_text_color)


def select_text_color(msg):
    global card_text

    # Сохраняем текст открытки
    card_text = msg.text
    # Просим пользователя ввести текст для открытки
    bot.send_message(msg.chat.id, "Теперь выбери цвет текста(на англ):")
    bot.send_message(msg.chat.id, "Если в конце текст в открытке все равно черный, то такого цвета нету(")
    bot.register_next_step_handler(msg, select_invitation)


def select_invitation(msg2):
    # Сохраняем текст открытки
    global text_color

    # Сохраняем текст открытки
    text_color = msg2.text
    # Создаем клавиатуру с выбором приглашения
    markup = types.InlineKeyboardMarkup()
    breakfast_button = types.InlineKeyboardButton("Завтрак в 11:00", callback_data='breakfast')
    lunch_button = types.InlineKeyboardButton("Обед в 14:00", callback_data='lunch')
    dinner_button = types.InlineKeyboardButton("Ужин в 20:00", callback_data='dinner')
    markup.add(breakfast_button, lunch_button, dinner_button)

    # Отправляем сообщение с клавиатурой
    bot.send_message(msg2.chat.id, "Выберите приглашение:", reply_markup=markup)


def select_background(call):
    # Получаем выбранное приглашение
    selected_invitation = call.data
    bot.send_photo(chat_id=call.message.chat.id, photo=open('backgrounds/img1.png', 'rb'))
    bot.send_photo(chat_id=call.message.chat.id, photo=open('backgrounds/img2.png', 'rb'))
    bot.send_photo(chat_id=call.message.chat.id, photo=open('backgrounds/img3.png', 'rb'))
    # Создаем клавиатуру с выбором фона
    markup = types.InlineKeyboardMarkup()
    background1_button = types.InlineKeyboardButton("Фон 1", callback_data='backgrounds/img1.png')
    background2_button = types.InlineKeyboardButton("Фон 2", callback_data='backgrounds/img2.png')
    background3_button = types.InlineKeyboardButton("Фон 3", callback_data='backgrounds/img3.png')
    markup.add(background1_button, background2_button, background3_button)

    # Сохраняем выбранное приглашение в контексте пользователя
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=call.message.text)
    bot.send_message(call.message.chat.id, "Выберите фон для открытки:", reply_markup=markup)


# Обработчики нажатия кнопок
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    if call.data in ['breakfast', 'lunch', 'dinner']:
        global when
        # Сохраняем текст открытки
        when = call.data
        select_background(call)
    elif call.data in ['backgrounds/img1.png', 'backgrounds/img2.png', 'backgrounds/img3.png']:
        create_invitation_card(call.message, call.data)


def create_invitation_card(message, background):
    background_img = Image.open(background)

    # Измените размер фона, чтобы он соответствовал размеру открытки
    background_img2 = background_img.resize((1280, 720))

    # Load the background image
    card = Image.new('RGB', (1280, 720), color='white')

    # Create a drawing context
    draw = ImageDraw.Draw(card)

    # Define the font and size for the text
    font = ImageFont.truetype("arial.ttf", 64)

    # Calculate the text size for the user text
    text_width, text_height = draw.textsize(card_text, font)
    card_width, card_height = card.size

    card.paste(background_img2, (0, 0))

    # Calculate the position for the user text to be centered
    text_x = (card_width - text_width) // 2
    text_y = 20
    try:
        # Draw the user text in the center
        draw.text((text_x, text_y), card_text, fill=text_color, font=font)
    except:
        # Draw the user text in the center
        draw.text((text_x, text_y), card_text, fill='black', font=font)

    # Define the font and size for the date and event text
    date_font = ImageFont.truetype("arial.ttf", 52)
    event_font = ImageFont.truetype("arial.ttf", 64)

    # Define the date text
    date_text = "10/09/2023"

    # Calculate the position for the date text at the bottom left corner
    date_x = card_width - 300
    date_y = card_height - 100  # Adjust the position as needed

    # Calculate the position for the event text in the center
    event_x = (card_width - text_width) // 2
    event_y = (card_height - text_height) // 2  # Adjust the position as needed

    # Define the event text based on the user's choice
    if when == "breakfast":
        event_text = "Завтрак в 11:00"
    elif when == "lunch":
        event_text = "Обед в 14:00"
    elif when == "dinner":
        event_text = "Ужин в 20:00"
    else:
        event_text = "Event"

    try:
        # Draw the date text at the bottom left corner
        draw.text((date_x, date_y), date_text, fill=text_color, font=date_font)
        # Draw the event text in the center
        draw.text((event_x, event_y), event_text, fill=text_color, font=event_font)
    except:
        # Draw the date text at the bottom left corner
        draw.text((date_x, date_y), date_text, fill='black', font=date_font)
        # Draw the event text in the center
        draw.text((event_x, event_y), event_text, fill='black', font=event_font)

    # Save the resulting image
    card.save("invitation_card.png")

    # Send the image to the user
    bot.send_photo(message.chat.id, open("invitation_card.png", "rb"))

    # Завершите интеракцию с пользователем
    bot.send_message(message.chat.id,
                     "Открытка создана!\n/create - чтобы создать снова\nНапишите /invite чтобы отправить её Максу!")


while True:
    schedule.run_pending()
    time.sleep(1)
    bot.polling()
