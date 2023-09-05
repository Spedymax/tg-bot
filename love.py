import telebot
from telebot import types
import datetime
import random

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
        "options": ["Житомир", "Ровно", "Киев", "Львов"],
        "answer": "Киев"
    },
    {
        "question": "Где Максим окончил первые 6 классов?",
        "options": ["Житомир", "Ровно", "Киев", "Львов"],
        "answer": "Киев"
    },
    {
        "question": "Где Максим окончил 7-11 класы?",
        "options": ["Житомир", "Ровно", "Киев", "Львов"],
        "answer": "Киев"
    },
    {
        "question": "Где максим учится сейчас?",
        "options": ["Житомир", "Ровно", "Киев", "Львов"],
        "answer": "Киев"
    },
    {
        "question": "Название компании где работает Максим?",
        "options": ["Житомир", "Ровно", "Киев", "Львов"],
        "answer": "Киев"
    },
    {
        "question": "Как Макс называет своего кота?",
        "options": ["Житомир", "Ровно", "Киев", "Львов"],
        "answer": "Киев"
    },
    {
        "question": "Как Вика подписана у Макса?",
        "options": ["Житомир", "Ровно", "Киев", "Львов"],
        "answer": "Киев"
    },
    {
        "question": "С",
        "options": ["Житомир", "Ровно", "Киев", "Львов"],
        "answer": "Киев"
    },
    {
        "question": "Где родился Максим?",
        "options": ["Житомир", "Ровно", "Киев", "Львов"],
        "answer": "Киев"
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
                     "Здравствуйте, Вика!\nМеня создал Максим чтобы рассказать вам как он вас любит!\nКаждый день вам будут открываться новые команды которые вы сможете использовать!\nНапишите /commands чтобы узнать какие команды уже доступны!")


@bot.message_handler(commands=['commands'])
def get_commands(message):
    current_date = datetime.date.today()
    commands = ""
    if current_date >= datetime.date(2023, 9, 4):
        commands += '/count- узнать сколько дней вы вместе\n'
    if current_date >= datetime.date(2023, 9, 5):
        commands += '/100reasons- узнать 100 причин\n'
    # if current_date >= datetime.date(2023, 9, 7):
    #
    # if current_date >= datetime.date(2023, 9, 8):
    #
    # if current_date >= datetime.date(2023, 9, 9):
    #
    # if current_date >= datetime.date(2023, 9, 10):

    bot.send_message(message.chat.id, f"Вам доступны команды:\n {commands}")


@bot.message_handler(commands=['count'])
def count(message):
    current_date = datetime.date.today()
    days_count = (current_date - start_date).days
    bot.send_message(message.chat.id, f"Вы на {days_count} дне отношений! 💑")
    if current_date == datetime.date(2023, 9, 10):
        bot.send_message(message.chat.id,
                         "Поздравляю с 100 днями отношений! 🥳 Пора устроить романтический завтрак и создать пригласительную открытку.")


@bot.message_handler(commands=['invite'])
def invite(message):
    # Здесь вы можете добавить код для отправки пригласительной открытки на завтрак
    bot.send_message(message.chat.id, "Пригласительная открытка на завтрак будет отправлена вам в ближайшее время!")


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
                         f"Викторина окончена! Ты правильно ответила на {correct_answers} из {len(trivia_questions)} вопросов верно. Молодец!❤️")
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


bot.polling()
