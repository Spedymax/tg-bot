import random

import requests
import html
from telebot import types
import json
from datetime import datetime, timezone

from BotFunctions.cryptography import clientGoogle

DIFFICULTY = 'medium'
# CATEGORIES = [
#     'Шуточные темы',
#     'Шутки 18+',
#     'Иностранные языки',
#     'Dota 2',
#     'Технологии и IT',
#     'История',
#     'География',
#     'Фильмы и сериалы',
#     'Новости',
#     'Компьютерные игры',
#     'Политика',
#     'Европа'
#     'Мемы',
#     'Социальные сети'
# ]
TODAY = datetime.now(timezone.utc).strftime('%Y-%m-%d')


# Player IDs
PLAYER_IDS = {
    'YURA': 742272644,
    'MAX': 741542965,
    'BODYA': 855951767
}

question_messages = {}
original_questions = {}


def is_question_in_database(question, cursor):
    cursor.execute("SELECT 1 FROM questions WHERE question = %s", (question,))
    return cursor.fetchone() is not None


headers2 = {
    "X-Api-Key": "moGKfa1h6H4f95COwnuELg==peeKU76sjBgNFpRu"
}


def get_question_from_gemini():
    try:
        prompt = f"""Ты - эксперт по созданию вопросов для викторины. Создай интересный вопрос на любую тему.

Структура вопроса:
1. Формат:
   - Вопрос должен быть кратким (не более 2 строк)
   - Используй разговорный стиль, но без упрощения содержания
   - Избегай сложных терминов без необходимости
   - Вопрос должен быть однозначным и не допускать двойных толкований

2. Сложность:
   - Средний уровень (не очевидный, но и не экспертный)
   - Должен заставлять задуматься
   - Может содержать элементы юмора или неожиданные факты
   - Должен быть актуальным и основанным на реальных фактах

3. Ответы:
   - Правильный ответ должен быть однозначным и логически связан с вопросом
   - Неправильные ответы должны быть правдоподобными
   - Все ответы должны быть на одном языке
   - Каждый ответ не более 50 байт
   - Начинай каждый ответ с большой буквы
   - Без подсказок в формулировках

4. Проверка качества:
   - Вопрос и ответ должны соответствовать историческим/фактическим данным
   - Нет противоречий между условием и ответом
   - Все ответы логически связаны с темой вопроса
   - Вопрос должен быть интересным и познавательным

Обязательный формат ответа, придерживайся только его, не используй никакую другую формулировку:
ВОПРОС: [сам вопрос]
ПРАВИЛЬНЫЙ ОТВЕТ: [правильный ответ]
ОБЪЯСНЕНИЕ: [1-2 интересных факта, объясняющих правильный ответ]
НЕПРАВИЛЬНЫЕ ОТВЕТЫ: [ответ1], [ответ2], [ответ3]

Помни:
- Это дружеская викторина, но с образовательным элементом
- Вопросы должны быть интересными и запоминающимися
- Избегай тривиальных или слишком сложных вопросов
- Проверь финальный результат на логичность и соответствие фактам"""

        response = clientGoogle.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        
        response_text = response.text
        
        # Парсим ответ
        question = response_text.split('ВОПРОС: ')[1].split('ПРАВИЛЬНЫЙ ОТВЕТ:')[0].strip()
        print(question)
        correct_answer = response_text.split('ПРАВИЛЬНЫЙ ОТВЕТ: ')[1].split('ОБЪЯСНЕНИЕ:')[0].strip()
        print(correct_answer)
        explanation = response_text.split('ОБЪЯСНЕНИЕ: ')[1].split('НЕПРАВИЛЬНЫЕ ОТВЕТЫ:')[0].strip()
        print(explanation)
        wrong_answers = response_text.split('НЕПРАВИЛЬНЫЕ ОТВЕТЫ: ')[1].strip().split(',')
        print(wrong_answers)
        wrong_answers = [ans.strip() for ans in wrong_answers]

        return {
            "question": question,
            "answer": correct_answer,
            "explanation": explanation,
            "wrong_answers": wrong_answers
        }
    except Exception as e:
        print(f"Error generating question: {e}")
        return None


def send_trivia_questions(chat_id, bot, cursor, conn):
    try:
        question_data = get_question_from_gemini()
        
        if question_data is None:
            bot.send_message(chat_id, "Извините, произошла ошибка при создании вопроса.")
            return

        question_text = question_data["question"]
        correct_answer = question_data["answer"]
        wrong_answers = question_data["wrong_answers"]

        answer_options = [correct_answer] + wrong_answers[:3]
        random.shuffle(answer_options)
        
        send_question_with_options(chat_id, bot, question_text, answer_options, cursor)
        save_question_to_database(question_text, correct_answer, answer_options, cursor, conn, question_data["explanation"])
        
    except Exception as e:
        bot.send_message(chat_id, f'Ошибка при создании вопроса: {e}')


def save_question_to_database(question, correct_answer, answer_options, cursor, conn, explanation=""):
    answer_options_str = json.dumps(answer_options)
    current_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute(
        "INSERT INTO questions (question, correct_answer, answer_options, date_added, explanation) VALUES (%s, %s, %s, %s, %s)",
        (question, correct_answer, answer_options_str, current_date, explanation))
    conn.commit()


def send_question_with_options(chat_id, bot, question, answer_options, cursor):
    markup = types.InlineKeyboardMarkup()

    # Use indices instead of full answer text in callback_data
    for index, answer in enumerate(answer_options):
        button = types.InlineKeyboardButton(text=answer, callback_data=f"ans_{index}")
        markup.add(button)

    bot.send_message(chat_id, "Внимание вопрос!", parse_mode='html')
    question_msg = bot.send_message(chat_id, question, reply_markup=markup, parse_mode='html', protect_content=True)

    # Store the original question, options and empty responses
    question_data = {
        "text": question,
        "players_responses": {},
        "options": answer_options  # Store the answer options to reference by index later
    }

    question_messages[question_msg.message_id] = question_data
    save_question_state(question_msg.message_id, question, {}, cursor, answer_options)


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


# Update save_question_state to also store answer options
def save_question_state(message_id, question, players_responses, cursor, answer_options=None):
    data_to_save = {
        "players_responses": players_responses
    }

    # Add answer options to data if provided
    if answer_options:
        data_to_save["options"] = answer_options

    cursor.execute("""
                   INSERT INTO question_state (message_id, original_question, players_responses)
                   VALUES (%s, %s, %s) ON CONFLICT (message_id) DO
                   UPDATE
                       SET players_responses = EXCLUDED.players_responses
                   """, (message_id, question, json.dumps(data_to_save)))
    cursor.connection.commit()


# Update load_question_state to handle the new format
def load_question_state(cursor):
    cursor.execute("SELECT message_id, original_question, players_responses FROM question_state")
    question_states = cursor.fetchall()

    result = {}
    for row in question_states:
        message_id, original_question = row[0], row[1]

        try:
            data = json.loads(row[2]) if isinstance(row[2], str) else {}

            # Handle both old and new format
            if isinstance(data, dict) and "players_responses" in data:
                # New format
                result[message_id] = {
                    "text": original_question,
                    "players_responses": data.get("players_responses", {}),
                    "options": data.get("options", [])
                }
            else:
                # Old format
                result[message_id] = {
                    "text": original_question,
                    "players_responses": data,
                    "options": []
                }
        except (json.JSONDecodeError, TypeError):
            # Fallback for any parsing errors
            result[message_id] = {
                "text": original_question,
                "players_responses": {},
                "options": []
            }

    return result


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
    current_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    bot.send_message(chat_id, f'Here are the correct answers for {current_date}:')


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
    current_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    cursor.execute("SELECT 1 FROM answered_questions WHERE user_id = %s AND question = %s AND date_added = %s",
                   (user_id, question, current_date))
    return cursor.fetchone() is not None


# Update answer_callback to work with the new approach
def answer_callback(call, bot, player_stats, cursor):
    user_id = str(call.from_user.id)
    player_name = player_stats[user_id]["player_name"]
    callback_data = call.data.split('_')

    # Extract the index from callback data
    if len(callback_data) != 2 or not callback_data[1].isdigit():
        bot.answer_callback_query(call.id, "Invalid callback data")
        return

    answer_index = int(callback_data[1])
    question_id = call.message.message_id
    chat_id = call.message.chat.id

    # Проверяем, является ли чат личным
    is_private_chat = call.message.chat.type == "private"

    cursor.execute("SELECT original_question, players_responses FROM question_state WHERE message_id = %s",
                   (question_id,))
    result = cursor.fetchone()

    if not result:
        bot.send_message(chat_id, "Error: Original question not found.")
        return

    original_question, stored_data = result[0], result[1]

    # Parse the stored data
    if isinstance(stored_data, str):
        try:
            stored_data = json.loads(stored_data)
        except json.JSONDecodeError:
            stored_data = {"players_responses": {}, "options": []}

    # Handle both old and new formats
    if isinstance(stored_data, dict) and "players_responses" in stored_data:
        players_responses = stored_data.get("players_responses", {})
        answer_options = stored_data.get("options", [])
    else:
        players_responses = stored_data
        answer_options = []

    # Make sure we have valid answer options
    if not answer_options or answer_index >= len(answer_options):
        bot.answer_callback_query(call.id, "Answer option not found")
        return

    # Get the actual answer text from the index
    answer = answer_options[answer_index]

    cursor.execute("SELECT correct_answer, explanation FROM questions WHERE question = %s", (original_question,))
    result = cursor.fetchone()

    if not result:
        bot.send_message(chat_id, "Error: Question not found in the database.")
        return

    correct_answer, explanation = result[0], result[1]

    if has_answered_question(user_id, original_question, cursor):
        bot.send_message(chat_id, "Ты уже ответил.")
        return

    # Проверяем правильность ответа и обновляем статистику
    is_correct = answer == correct_answer
    emoji = "✅" if is_correct else "❌"
    players_responses[player_name] = emoji

    # Обновляем статистику игрока
    if is_correct:
        # Находим текущий счет для этого чата
        current_score = 0
        for score_entry in player_stats[user_id]["correct_answers"]:
            if f"{chat_id}:" in score_entry:
                current_score = int(score_entry.split(":")[1])
                break

        # Обновляем или добавляем новый счет
        new_score = current_score + 1
        new_score_entry = f"{chat_id}:{new_score}"

        # Удаляем старый счет и добавляем новый
        player_stats[user_id]["correct_answers"] = [
            entry for entry in player_stats[user_id]["correct_answers"]
            if not entry.startswith(f"{chat_id}:")
        ]
        player_stats[user_id]["correct_answers"].append(new_score_entry)

    # Обновляем сообщение с вопросом
    updated_text = original_question + "\n\n" + \
                   "\n".join([f"{player} {response}" for player, response in players_responses.items()])

    # Если это личный чат, сразу показываем результат
    if is_private_chat:
        result_text = f"{'Правильно!' if is_correct else 'Неправильно!'}\nПравильный ответ: {correct_answer}\n\nОбъяснение: {explanation}"
        bot.send_message(chat_id, result_text)
    else:
        # Получаем количество активных участников в группе
        cursor.execute("SELECT COUNT(DISTINCT user_id) FROM user_activity WHERE chat_id = %s", (chat_id,))
        active_users_count = cursor.fetchone()[0]

        # Если все активные участники ответили, показываем объяснение
        if len(players_responses) >= active_users_count:
            updated_text += f"\n\nПравильный ответ: {correct_answer}\nОбъяснение: {explanation}"

    bot.edit_message_text(chat_id=chat_id, message_id=question_id, text=updated_text,
                          reply_markup=call.message.reply_markup, parse_mode='html')

    # Store the updated data
    data_to_save = {
        "players_responses": players_responses,
        "options": answer_options
    }

    cursor.execute("""
                   UPDATE question_state
                   SET players_responses = %s
                   WHERE message_id = %s
                   """, (json.dumps(data_to_save), question_id))

    current_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    cursor.execute("INSERT INTO answered_questions (user_id, question, date_added) VALUES (%s, %s, %s)",
                   (user_id, original_question, current_date))
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
