import requests
import html
from telebot import types
import json
import random
from datetime import datetime, timedelta, timezone

API_URL = "https://the-trivia-api.com/v2/questions"
DIFFICULTY = 'medium'
CATEGORIES = 'general_knowledge, history, geography'

today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

# Define player IDs
YURA_ID = 742272644
MAX_ID = 741542965
BODYA_ID = 855951767
NIKA_ID = 1085180226
VIKA_ID = 1561630034
# Define API headers
HEADERS = {
    "Content-Type": "application/json",
    "Authorization": "Bearer YOUR_API_KEY"  # Replace with your actual API key
}


# Function to fetch trivia questions from the API
def fetch_trivia_questions(difficulty, categories):
    params = {
        "limit": 1,
        "difficulties": difficulty,
        "categories": categories
    }

    try:
        response = requests.get(API_URL, params=params)
        response.raise_for_status()  # Raise an exception for error status codes
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching trivia questions: {e}")
        return None


# Function to send trivia questions to a chat
def send_trivia_questions(chat_id, bot, cursor, conn, headers):
    questions_data = fetch_trivia_questions(DIFFICULTY, CATEGORIES)
    if not questions_data:
        bot.send_message(chat_id, "Sorry, there was an error fetching trivia questions.")
        return

    for question_data in questions_data:
        question_text = html.unescape(question_data["question"]["text"])
        correct_answer = html.unescape(question_data["correctAnswer"])
        answer_options = [correct_answer] + question_data["incorrectAnswers"]

        # Get funny answer
        funny_answer = get_funny_answer(question_text, answer_options, headers)

        answer_options.append(funny_answer)

        # Generate and send message with question and options
        send_question_with_options(chat_id, bot, question_text, answer_options)

        # Save question to database
        save_question_to_database(question_text, correct_answer, answer_options, cursor, conn)


def get_funny_answer(question, answer_options, headers):
    try:
        data = {
            "model": "gpt-3.5-turbo",
            "messages": [
                {
                    "role": "system",
                    "content": "You're tasked with generating a funny response to the question provided above, considering the given answers. Your goal is to come up with a witty and humorous response that would make someone chuckle. You must use black and sexist and unethical humor. Remember, your response should stand out and be entertaining. Don't use already existing answers. You must return the funny answer ONLY. Your answer must be one or two or three words long. You mustn't answer given question, just think of funny response to it."
                },
                {
                    "role": "user",
                    "content": f"{question} \n{answer_options}"
                }
            ],
            "temperature": 0.7
        }

        response = requests.post('https://api.openai.com/v1/chat/completions', headers=headers, data=json.dumps(data))
        response_data = response.json()
        funny_answer = response_data['choices'][0]['message']['content']
    except:
        funny_answer = "Funny moment не будет(("
    return funny_answer


def save_question_to_database(question, correct_answer, answer_options, cursor, conn):
    answer_options_str = json.dumps(answer_options)
    current_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    cursor.execute(
        "INSERT INTO questions (question, correct_answer, answer_options, date_added) VALUES (%s, %s, %s, %s)",
        (question, correct_answer, answer_options_str, current_date))
    conn.commit()


def send_question_with_options(chat_id, bot, question, answer_options):
    markup = types.InlineKeyboardMarkup()
    for answer in answer_options:
        button = types.InlineKeyboardButton(text=answer, callback_data=f"answer_{answer}")
        markup.add(button)

    bot.send_message(chat_id, "Внимание вопрос!")
    bot.send_message(chat_id, question, reply_markup=markup, parse_mode='html')


def clear_trivia_data(cursor, conn):
    cursor.execute("DELETE FROM answered_questions")
    conn.commit()


def load_trivia_data(cursor):
    cursor.execute("SELECT * FROM questions ORDER BY date_added")  # Получаем все записи из таблицы
    data = cursor.fetchall()
    trivia = []

    for row in data:
        question, corr_answer, answer_options, date_added = row
        date_added2 = f'{date_added.day}-{date_added.month}-{date_added.year} {date_added.hour}:{date_added.minute}'
        trivia.append({'question': question, 'correct_answer': corr_answer, 'date_added': date_added2})

    return trivia

def get_correct_answers(message, bot, pisunchik, cursor):
    trivia = load_trivia_data(cursor)
    bot.send_message(message.chat.id, f'А вот и правильные ответы за {today}:')
    for i in range(len(trivia) - 1, -1, -1):  # iterate backwards to show newest first
        question = trivia[i]['question']
        answer = trivia[i]['correct_answer']
        date = trivia[i]['date_added']
        if has_answered_question(str(MAX_ID), question, cursor):  # Check for MAX_ID (replace with actual user ID)
            bot.send_message(message.chat.id, f'Вопрос: {question} \nОтвет: {answer}\nДата: {date}')
    bot.send_message(message.chat.id, f'Итого у игроков правильных ответов:')
    bot.send_message(message.chat.id,
                     f'{pisunchik[str(MAX_ID)]["player_name"]} : {pisunchik[str(MAX_ID)]["correct_answers"]}')
    bot.send_message(message.chat.id,
                     f'{pisunchik[str(YURA_ID)]["player_name"]} : {pisunchik[str(YURA_ID)]["correct_answers"]}')
    bot.send_message(message.chat.id,
                     f'{pisunchik[str(BODYA_ID)]["player_name"]} : {pisunchik[str(BODYA_ID)]["correct_answers"]}')


def get_correct_answers2(bot, pisunchik, cursor, conn):
    chat_id = [-1001294162183]
    for chat in chat_id:
        trivia = load_trivia_data(cursor)
        bot.send_message(chat, f'А вот и правильные ответы за {today}:')
        for i in range(len(trivia) - 1, -1, -1):  # iterate backwards to show newest first
            question = trivia[i]['question']
            answer = trivia[i]['correct_answer']
            date = trivia[i]['date_added']
            if has_answered_question(str(MAX_ID), question, cursor):  # Check for MAX_ID (replace with actual user ID)
                bot.send_message(chat, f'Вопрос: {question} \nОтвет: {answer}\nДата: {date}')
        bot.send_message(chat, f'Итого у игроков правильных ответов:')
        bot.send_message(chat,
                         f'{pisunchik[str(MAX_ID)]["player_name"]} : {pisunchik[str(MAX_ID)]["correct_answers"]}')
        bot.send_message(chat,
                         f'{pisunchik[str(YURA_ID)]["player_name"]} : {pisunchik[str(YURA_ID)]["correct_answers"]}')
        bot.send_message(chat,
                         f'{pisunchik[str(BODYA_ID)]["player_name"]} : {pisunchik[str(BODYA_ID)]["correct_answers"]}')
        clear_trivia_data(cursor, conn)

answered_questions = {}  # Keep track of which questions each user has answered

def has_answered_question(user_id, question, cursor):
    cursor.execute("SELECT * FROM answered_questions WHERE user_id = %s AND question = %s AND date_added = %s", (user_id, question, today))
    return cursor.fetchone() is not None



def answer_callback(call, bot, pisunchik, cursor, conn):
    user_id = str(call.from_user.id)
    answer = call.data.split('_')[1]
    question = call.message.text

    cursor.execute("SELECT correct_answer FROM questions WHERE question = %s", (question,))
    result = cursor.fetchone()
    if result:
        correct_answer = result[0]  # Extract the correct answer from the result tuple
    else:
        bot.send_message(call.message.chat.id, "Error: Question not found in the database.")
        return

    if has_answered_question(user_id, question, cursor):
        bot.send_message(call.message.chat.id, "Вы уже ответили на этот вопрос.")
        return

    if answer == correct_answer:
        pisunchik[user_id]["correct_answers"] += 1

    # Update the answered questions dictionary
    answered_questions[user_id] = correct_answer

    bot.send_message(call.message.chat.id, f'Игрок {pisunchik[user_id]["player_name"]} сделал свой выбор...')
    cursor.execute("INSERT INTO answered_questions (user_id, question) VALUES (%s, %s)", (user_id, question))
    conn.commit()
    save_data(cursor, pisunchik, conn)


def save_data(cursor, pisunchik, conn):
    # First, clear all existing data from the table, consider if this is what you really want to do
    cursor.execute("DELETE FROM pisunchik_data")

    # Loop through each player in the pisunchik dictionary
    for player_id, data in pisunchik.items():
        # Ensure player_id is not None or empty
        if player_id:
            # Prepare the data for insertion
            # Add player_id to the data dictionary
            data_with_id = {'player_id': player_id, **data}

            columns = ', '.join(data_with_id.keys())
            placeholders = ', '.join(['%s'] * len(data_with_id))
            values = tuple(data_with_id.values())

            # Build and execute the INSERT query
            query = f"INSERT INTO pisunchik_data ({columns}) VALUES ({placeholders})"
            cursor.execute(query, values)

    # Commit changes to the database
    conn.commit()
