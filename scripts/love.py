import telebot
from telebot import types
import datetime
import random
import os
import time
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv('/home/spedymax/tg-bot/.env')

bot = telebot.TeleBot(os.getenv('LOVE_BOT_TOKEN'))

# Replace these with the actual chat IDs
MAX_ID = 741542965      # Your chat ID
MUSHROOM_ID = 475552394  # Your girlfriend's chat ID

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
        "question": "Где Максим учится сейчас?",
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
        "question": "Как Маша подписана у Макса в тг?",
        "options": ["Котик", "Сладкая попка", "Маша", "Машрумчик"],
        "answer": "Машрумчик"
    },
    {
        "question": "Любимая еда Макса?",
        "options": ["Суши", "Мороженое", "Рисовые чипсы", "Пицца", "Шашлык", "Конфеты"],
        "answer": "Рисовые чипсы"
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
        "options": ["185", "170", "172", "215"],
        "answer": "172"
    },
    {
        "question": "Когда мы начали встречаться?",
        "options": ["28 августа", "25 августа", "в 1945 году", "Летом 2021"],
        "answer": "28 августа"
    }
]

# Create a dictionary to keep track of the user's progress
user_progress = {}

# Set the start date to a past date for testing
start_date = datetime.date(2023, 6, 1)

# Load list of reasons from love.txt
with open('/home/spedymax/tg-bot/assets/data/love.txt', 'r', encoding='utf-8') as file:
    reasons = file.read().splitlines()


@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(
        message.chat.id,
        "Здравствуйте, Мария!\nМеня создал Максим, чтобы рассказать вам, как он вас любит!\nКаждый день вам будут открываться новые команды, которые вы сможете использовать!\nЧерез 4 дня все команды будут открыты для вас, и вы даже сможете сделать небольшой подарок Максу!\nНапишите /commands, чтобы узнать, какие команды уже доступны!"
    )
    # Debug message to you
    if message.from_user.id == MUSHROOM_ID:
        bot.send_message(MAX_ID, f"Она использовала /start")


@bot.message_handler(commands=['commands'])
def get_commands(message):
    current_date = datetime.date.today()
    startuem = False
    commands = ""
    # Adjusted dates for testing
    if current_date >= start_date:
        commands += '/count - узнать сколько дней вы вместе\n'
    if current_date >= start_date + datetime.timedelta(days=1):
        commands += '/100reasons - узнать 100 причин\n'
    if current_date >= start_date + datetime.timedelta(days=2):
        commands += '/trivia - викторина\n/answers - ответы на викторину\n'
    if current_date >= start_date + datetime.timedelta(days=3):
        commands += '/invite - пригласи Максима на свидание!\n'
    if current_date == start_date + datetime.timedelta(days=3):
        startuem = True
    bot.send_message(message.chat.id, f"Вам доступны команды:\n{commands}")
    if startuem:
        bot.send_message(
            message.chat.id,
            "Ого! Уже завтра вы будете отмечать 100 дней вместе!\nМои поздравления!❤️\nКак насчёт свидания?)\nНапиши /invite, чтобы узнать, как это сделать!"
        )
    # Debug message to you
    if message.from_user.id == MUSHROOM_ID:
        bot.send_message(MAX_ID, f"Она использовала /commands")


@bot.message_handler(commands=['count'])
def count(message):
    current_date = datetime.date.today()
    days_count = (current_date - start_date).days
    bot.send_message(message.chat.id, f"Вы на {days_count} дне отношений! 💑")
    if current_date == start_date + datetime.timedelta(days=100):
        bot.send_message(
            message.chat.id,
            "Поздравляю, вы встречаетесь уже 100 дней! 🥳 Пора устроить романтическую встречу!"
        )
    # Debug message to you
    if message.from_user.id == MUSHROOM_ID:
        bot.send_message(MAX_ID, f"Она использовала /count")


@bot.message_handler(commands=['invite'])
def send_invitation(message):
    # Send the invitation message to you
    bot.send_message(
        MAX_ID,
        "Пригласи Максима на свидание!\nПерейдите по ссылке чтобы это сделать: http://spedymax.sytes.net:200"
    )
    # Debug message to you
    if message.from_user.id == MUSHROOM_ID:
        bot.send_message(MAX_ID, f"Она использовала /invite")


@bot.message_handler(commands=['100reasons'])
def show_reasons(message):
    # Create Inline Keyboard
    keyboard = types.InlineKeyboardMarkup()
    random_reasons_button = types.InlineKeyboardButton("10 причин (так веселее)", callback_data="reas_random_10")
    all_reasons_button = types.InlineKeyboardButton("Все сразу", callback_data="reas_all")
    keyboard.add(random_reasons_button, all_reasons_button)

    bot.send_message(message.chat.id, "Выберите, сколько причин вы хотите увидеть:", reply_markup=keyboard)
    # Debug message to you
    if message.from_user.id == MUSHROOM_ID:
        bot.send_message(MAX_ID, f"Она использовала /100reasons")


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
        # Debug message to you
        if call.from_user.id == MUSHROOM_ID:
            bot.send_message(MAX_ID, "Она выбрала 10 причин")
    elif call.data == "reas_all":
        # Send all reasons in smaller chunks
        chunk_size = 50  # Adjust the chunk size as needed
        for i in range(0, len(reasons), chunk_size):
            chunk = reasons[i:i + chunk_size]
            reasons_text = "\n".join(chunk)
            bot.send_message(call.message.chat.id, reasons_text)
        bot.send_message(call.message.chat.id, "Спасибо за то, что ты есть у меня!❤️")
        # Debug message to you
        if call.from_user.id == MUSHROOM_ID:
            bot.send_message(MAX_ID, "Она выбрала все причины")


@bot.message_handler(commands=['trivia'])
def start_trivia(message):
    chat_id = message.chat.id

    # Initialize or reset the user's progress
    user_progress[chat_id] = {
        "current_question_index": 0,
        "correct_answers": 0
    }
    bot.send_message(chat_id, "Добро пожаловать в викторину!\nСейчас мы узнаем, насколько хорошо вы знаете Макса!")

    send_next_question(chat_id)
    # Debug message to you
    if message.from_user.id == MUSHROOM_ID:
        bot.send_message(MAX_ID, "Она начала викторину")


def send_next_question(chat_id):
    current_question_index = user_progress[chat_id]["current_question_index"]

    # Check if all questions have been answered
    if current_question_index >= len(trivia_questions):
        correct_answers = user_progress[chat_id]["correct_answers"]
        bot.send_message(
            chat_id,
            f"Викторина окончена! Ты правильно ответила на {correct_answers} из {len(trivia_questions)} вопросов. Умничка!❤️"
        )
        # Debug message to you
        if chat_id == MUSHROOM_ID:
            bot.send_message(MAX_ID, f"Она завершила викторину с результатом {correct_answers}/{len(trivia_questions)}")
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
    # Debug message to you
    if chat_id == MUSHROOM_ID:
        bot.send_message(MAX_ID, f"Она отвечает на вопрос: {question_text}")


@bot.callback_query_handler(func=lambda call: call.data.startswith("answer_"))
def handle_trivia_answer(call):
    chat_id = call.message.chat.id
    user_answer = call.data.split("_", 1)[1]

    current_question_index = user_progress[chat_id]["current_question_index"]
    correct_answer = trivia_questions[current_question_index]["answer"]

    # Check if the user's answer is correct
    if user_answer == correct_answer:
        user_progress[chat_id]["correct_answers"] += 1
        is_correct = True
    else:
        is_correct = False

    # Move to the next question
    user_progress[chat_id]["current_question_index"] += 1

    # Remove the inline keyboard
    bot.edit_message_reply_markup(chat_id, call.message.message_id)

    # Debug message to you
    if call.from_user.id == MUSHROOM_ID:
        bot.send_message(MAX_ID, f"Она ответила: '{user_answer}' - {'Правильно' if is_correct else 'Неправильно'}")

    # Send the next question or end the quiz
    send_next_question(chat_id)


@bot.message_handler(commands=['answers'])
def answers(message):
    # Send a message with the correct answers
    response = "Правильные ответы:"
    for item in trivia_questions:
        response += f"\n{item['question']}: {item['answer']}"

    bot.send_message(message.chat.id, response)
    # Debug message to you
    if message.from_user.id == MUSHROOM_ID:
        bot.send_message(MAX_ID, f"Она запросила ответы на викторину")

# Polling with retry logic for network errors
def start_polling_with_retry(max_retries=5):
    """Start bot polling with exponential backoff retry on network errors"""
    retry_delay = 5  # Initial retry delay in seconds

    for attempt in range(max_retries):
        try:
            print(f"Starting love bot polling (attempt {attempt + 1}/{max_retries})...")
            bot.polling(none_stop=True, timeout=60)
            break  # If polling starts successfully, exit retry loop
        except Exception as e:
            error_msg = str(e)
            if "NameResolutionError" in error_msg or "ConnectionError" in error_msg:
                if attempt < max_retries - 1:
                    print(f"Network error on attempt {attempt + 1}: {error_msg}")
                    print(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    print(f"Failed to start after {max_retries} attempts. Giving up.")
                    raise
            else:
                # Re-raise non-network errors immediately
                raise

start_polling_with_retry()

#741542965
#475552394
