import random

import requests
import html
from telebot import types
import json
from datetime import datetime, timezone

API_URL = "https://api.api-ninjas.com/v1/trivia"
DIFFICULTY = 'medium'
CATEGORIES = 'general,entertainment,geography,mathematics,language'
TODAY = datetime.now(timezone.utc).strftime('%Y-%m-%d')

# Player IDs
PLAYER_IDS = {
    'YURA': 742272644,
    'MAX': 741542965,
    'BODYA': 855951767
}


def fetch_trivia_questions(categories, cursor, headers):
    while True:
        params = {"category": categories}
        try:
            response = requests.get(API_URL, params=params, headers=headers)
            response.raise_for_status()
            question_data = response.json()[0]

            if not is_question_in_database(question_data['question'], cursor):
                return question_data
        except requests.exceptions.RequestException as e:
            print(f"Error fetching trivia questions: {e}")
            return None


def is_question_in_database(question, cursor):
    cursor.execute("SELECT 1 FROM questions WHERE question = %s", (question,))
    return cursor.fetchone() is not None


headers2 = {
    "X-Api-Key": "hjvcRr/5dpubsuksJXy8jA==qMIPk0DacEoy2XjI"
}


def send_trivia_questions(chat_id, bot, cursor, conn, headers):
    try:
        category = random.choice(CATEGORIES.split(','))
        question_data = fetch_trivia_questions(category, cursor, headers2)
        if question_data is None:
            bot.send_message(chat_id, "Sorry, there was an error fetching trivia questions.")
            return

        question_text = html.unescape(question_data["question"])
        correct_answer = html.unescape(question_data["answer"])

        funny_answer = get_funny_answer(question_text, correct_answer, headers)
        split_answers = funny_answer.split(",")
        answer_options = [correct_answer, split_answers[0], split_answers[1], split_answers[2]]
        # Shuffle the answer options
        random.shuffle(answer_options)
        send_question_with_options(chat_id, bot, question_text, answer_options)

        save_question_to_database(question_text, correct_answer, answer_options, cursor, conn)
    except Exception:
        bot.send_message(-1001294162183, 'Error while fetching trivia.')



def get_funny_answer(question, answer_options, headers):
    try:
        data = {"model": "gpt-3.5-turbo", "messages": [{
            "role": "system",
            "content": "You're tasked with generating a wrong responses only to the question provided above, "
                       "considering the given answer. Your goal is to come up with 3 wrong answers."
                       "Please separate your response answers with comma. Your answer must look like this: "
                       "wrong_answer,wrong_answer,wrong_answer"
        },
            {"role": "user", "content": f"{question} \n{answer_options}"}],
                "temperature": 0.7}
        response = requests.post('https://api.openai.com/v1/chat/completions', headers=headers, data=json.dumps(data))
        response_data = response.json()
        return response_data['choices'][0]['message']['content']
    except Exception:
        return "No funny answer available."


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
    bot.send_message(chat_id, "Внимание вопрос!", parse_mode='html')
    bot.send_message(chat_id, question, reply_markup=markup, parse_mode='html')


def clear_trivia_data(cursor):
    cursor.execute("DELETE FROM answered_questions")
    cursor.connection.commit()


def load_trivia_data(cursor):
    cursor.execute("SELECT * FROM questions ORDER BY date_added DESC")
    return [{
        'question': row[0],
        'correct_answer': row[1],
        'date_added': row[3].strftime('%d-%m-%Y %H:%M')
    } for row in cursor.fetchall()]


def get_correct_answers(bot, pisunchik, cursor, message=False, ):
    trivia = load_trivia_data(cursor)
    if message is False:
        chat_id = -1001294162183
    else:
        chat_id = message.chat.id
    send_correct_answers_header(bot, chat_id)
    display_answers(bot, chat_id, trivia, cursor, pisunchik)
    display_player_scores(bot, chat_id, pisunchik)


def send_correct_answers_header(bot, chat_id):
    bot.send_message(chat_id, f'Here are the correct answers for {TODAY}:')


def display_answers(bot, chat_id, trivia, cursor, pisunchik):
    for trivia_entry in reversed(trivia):  # iterate backwards to show newest first
        question, answer, date = trivia_entry['question'], trivia_entry['correct_answer'], trivia_entry['date_added']
        if any(has_answered_question(int(player_id), question, cursor) for player_id in pisunchik):
            bot.send_message(chat_id, f'Question: {question} \nAnswer: {answer}\nDate: {date}')


def display_player_scores(bot, chat_id, pisunchik):
    bot.send_message(chat_id, 'Total correct answers:')
    for player_id, stats in pisunchik.items():
        bot.send_message(chat_id, f'{stats["player_name"]} : {stats["correct_answers"]}')


def has_answered_question(user_id, question, cursor):
    cursor.execute("SELECT 1 FROM answered_questions WHERE user_id = %s AND question = %s AND date_added = %s",
                   (user_id, question, TODAY))
    return cursor.fetchone() is not None


def answer_callback(call, bot, player_stats, cursor):
    user_id = str(call.from_user.id)
    answer = call.data.split('_')[1]
    cursor.execute("SELECT correct_answer FROM questions WHERE question = %s", (call.message.text,))
    result = cursor.fetchone()
    if not result:
        bot.send_message(call.message.chat.id, "Error: Question not found in the database.")
        return
    if has_answered_question(user_id, call.message.text, cursor):
        bot.send_message(call.message.chat.id, "Ты уже ответил.")
        return
    if answer == result[0]:
        player_stats[user_id]["correct_answers"] += 1
        bot.send_message(call.message.chat.id, f'{player_stats[user_id]["player_name"]} угадал(лаки)')
    else:
        bot.send_message(call.message.chat.id, f'{player_stats[user_id]["player_name"]} ошибся(анлак)')
    cursor.execute("INSERT INTO answered_questions (user_id, question, date_added) VALUES (%s, %s, %s)",
                   (user_id, call.message.text, TODAY))
    cursor.connection.commit()
    save_player_stats(cursor, player_stats)


def save_player_stats(cursor, player_stats):
    cursor.execute("DELETE FROM pisunchik_data")
    for player_id, stats in player_stats.items():
        data = {'player_id': player_id, **stats}
        columns = ', '.join(data.keys())
        placeholders = ', '.join(['%s'] * len(data))
        cursor.execute(f"INSERT INTO pisunchik_data ({columns}) VALUES ({placeholders})", list(data.values()))
    cursor.connection.commit()
