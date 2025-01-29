import random

import requests
import html
from telebot import types
import json
from datetime import datetime, timezone

DIFFICULTY = 'medium'
CATEGORIES = 'general,entertainment,geography,sciencenature,fooddrink,peopleplaces'
TODAY = datetime.now(timezone.utc).strftime('%Y-%m-%d')

# Player IDs
PLAYER_IDS = {
    'YURA': 742272644,
    'MAX': 741542965,
    'BODYA': 855951767
}

question_messages = {}
original_questions = {}


def fetch_trivia_questions(categories, cursor, headers):
    for i in range(50):
        API_URL = 'https://api.api-ninjas.com/v1/trivia'
        try:
            response = requests.get(API_URL, headers=headers)
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
    "X-Api-Key": "moGKfa1h6H4f95COwnuELg==peeKU76sjBgNFpRu"
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
        print(correct_answer)

        funny_answer = get_funny_answer(question_text, correct_answer, headers)
        split_answers = funny_answer.split(",")
        answer_options = [correct_answer, split_answers[0], split_answers[1], split_answers[2]]
        # Shuffle the answer options
        random.shuffle(answer_options)
        send_question_with_options(chat_id, bot, question_text, answer_options, cursor)

        save_question_to_database(question_text, correct_answer, answer_options, cursor, conn)
    except Exception:
        bot.send_message(chat_id, 'Error while fetching trivia.')


def get_funny_answer(question, answer_options, headers):
    try:
        data = {"model": "gpt-4o", "messages": [{
            "role": "system",
            "content": "You're tasked with generating a wrong responses only to the question provided above, "
                       "considering the given answer. Your goal is to come up with 3 wrong answers."
                       "Please separate your response answers with comma. Be aware with the capital letters, "
                       "if the correct answer starts from big letter you must write other answers starting from big "
                       "letter too. Your answer must look like this:"
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


def send_question_with_options(chat_id, bot, question, answer_options, cursor):
    markup = types.InlineKeyboardMarkup()
    for answer in answer_options:
        button = types.InlineKeyboardButton(text=answer, callback_data=f"answer_{answer}")
        markup.add(button)

    bot.send_message(chat_id, "Внимание вопрос!", parse_mode='html')
    question_msg = bot.send_message(chat_id, question, reply_markup=markup, parse_mode='html', protect_content=True)

    # Сохранение оригинального вопроса и пустых ответов в базу данных
    question_messages[question_msg.message_id] = {"text": question, "players_responses": {}}
    save_question_state(question_msg.message_id, question, {}, cursor)


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


def save_question_state(message_id, question, players_responses, cursor):
    cursor.execute("""
        INSERT INTO question_state (message_id, original_question, players_responses)
        VALUES (%s, %s, %s)
        ON CONFLICT (message_id) DO UPDATE 
        SET players_responses = EXCLUDED.players_responses
    """, (message_id, question, json.dumps(players_responses)))  # Здесь мы сохраняем players_responses как JSON строку
    cursor.connection.commit()


def load_question_state(cursor):
    cursor.execute("SELECT message_id, original_question, players_responses FROM question_state")
    question_states = cursor.fetchall()
    # Мы предполагаем, что players_responses в базе данных хранится как строка, поэтому применяем json.loads()
    return {row[0]: {"text": row[1], "players_responses": json.loads(row[2])} for row in question_states if
            isinstance(row[2], str)}


def get_correct_answers(bot, pisunchik, cursor, chat_id):
    trivia = load_trivia_data(cursor)
    send_correct_answers_header(bot, chat_id)
    display_answers(bot, chat_id, trivia, cursor, pisunchik)
    display_player_scores(bot, chat_id, pisunchik)

def get_correct_answers2(bot, pisunchik, cursor, message):
    trivia = load_trivia_data(cursor)
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
        # Iterate through the correct_answers list
        for correct_answer in stats["correct_answers"]:
            # Assuming the format is '{chat_id:correct_answers_number}', split it by ':'
            stored_chat_id, correct_answers = correct_answer.strip('{}').split(':')

            # Convert stored_chat_id to integer for comparison
            if int(stored_chat_id) == chat_id:
                bot.send_message(chat_id, f'{stats["player_name"]} : {correct_answers}')


def has_answered_question(user_id, question, cursor):
    cursor.execute("SELECT 1 FROM answered_questions WHERE user_id = %s AND question = %s AND date_added = %s",
                   (user_id, question, TODAY))
    return cursor.fetchone() is not None


def answer_callback(call, bot, player_stats, cursor):
    user_id = str(call.from_user.id)
    player_name = player_stats[user_id]["player_name"]
    answer = call.data.split('_')[1]
    question_id = call.message.message_id
    chat_id = call.message.chat.id

    cursor.execute("SELECT original_question, players_responses FROM question_state WHERE message_id = %s",
                   (question_id,))
    result = cursor.fetchone()

    if not result:
        bot.send_message(call.message.chat.id, "Error: Original question not found.")
        return

    original_question, players_responses = result[0], result[1]

    if isinstance(players_responses, str):
        players_responses = json.loads(players_responses)

    cursor.execute("SELECT correct_answer FROM questions WHERE question = %s", (original_question,))
    result = cursor.fetchone()

    if not result:
        bot.send_message(call.message.chat.id, "Error: Question not found in the database.")
        return

    if has_answered_question(user_id, original_question, cursor):
        bot.send_message(call.message.chat.id, "Ты уже ответил.")
        return

    correct_answer = result[0]

    # Check if the answer is correct
    if answer == correct_answer:
        emoji = "✅"

        # Retrieve the current stats or initialize if not present
        if isinstance(player_stats[user_id]["correct_answers"], list):
            # Convert the list to a dictionary
            chat_stats = {item.split(":")[0]: int(item.split(":")[1]) for item in
                          player_stats[user_id]["correct_answers"]}
        else:
            chat_stats = {}

        # Initialize or update the count for the current chat
        chat_id_str = str(chat_id)
        if chat_id_str in chat_stats:
            chat_stats[chat_id_str] += 1
        else:
            chat_stats[chat_id_str] = 1

        # Convert back to list format
        player_stats[user_id]["correct_answers"] = [f"{k}:{v}" for k, v in chat_stats.items()]

    else:
        emoji = "❌"

    players_responses[player_name] = emoji

    updated_text = original_question + "\n\n" + \
                   "\n".join([f"{player} {response}" for player, response in players_responses.items()])
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=question_id, text=updated_text,
                          reply_markup=call.message.reply_markup, parse_mode='html')

    save_question_state(question_id, original_question, players_responses, cursor)

    cursor.execute("INSERT INTO answered_questions (user_id, question, date_added) VALUES (%s, %s, %s)",
                   (user_id, original_question, TODAY))
    cursor.connection.commit()
    save_player_stats(cursor, player_stats)



def load_all_questions_state(cursor):
    global question_messages
    question_messages = load_question_state(cursor)


def save_player_stats(cursor, player_stats):
    for player_id, stats in player_stats.items():
        correct_answers = stats["correct_answers"]
        cursor.execute("""
            INSERT INTO pisunchik_data (player_id, player_name, correct_answers)
            VALUES (%s, %s, %s::text[])
            ON CONFLICT (player_id) DO UPDATE 
            SET correct_answers = EXCLUDED.correct_answers
        """, (player_id, stats['player_name'], correct_answers))
    cursor.connection.commit()
