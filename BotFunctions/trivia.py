import random

import requests
import html
from telebot import types
import json
from datetime import datetime, timezone

from BotFunctions.cryptography import clientGoogle

DIFFICULTY = 'medium'
CATEGORIES = [
    'Шуточные темы',
    'Расистские шутки',
    'Шутки 18+',
    'Иностранные языки',
    'Dota 2',
    'Технологии и IT',
    'История',
    'География', 
    'Фильмы и сериалы',
    'Новости',
    'Компьютерные игры',
    'Политика',
    'Жизнь в Украине',
    'Жизнь в Германии',
    'Жизнь в Копенгагене',
    'Мемы',
    'Социальные сети'
]
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


def get_question_from_gemini(category):
    try:
        prompt = f"""Создай интересный вопрос для викторины на тему "{category}".

        Требования к вопросу:
        - Должен быть нестандартным и заставлять задуматься
        - Средняя сложность (не очевидный, но и не экспертный)
        - Можно с элементами юмора или неожиданными фактами
        - Краткость формулировки (не более 2 строк)
        - Вопрос должен быть актуальным и реальным, а не твоей галюцинацией
        - ВАЖНО: Вопрос и правильный ответ должны быть логически связаны и соответствовать историческим фактам
        - ВАЖНО: Не создавать вопросы, где правильный ответ противоречит условиям вопроса

        После генерации обязательно проверь:
        1. Соответствует ли правильный ответ условиям вопроса
        2. Нет ли исторических или фактических противоречий
        3. Если есть противоречия - переделай вопрос полностью

        Требования к ответам:
        - Правильный ответ должен быть однозначным
        - Неправильные ответы должны быть правдоподобными и логичными
        - Каждый ответ должен быть не более 60 байтов
        - Без подсказок в формулировках
        - Начинай с большой буквы
        - Все ответы должны быть на одном и том же языке

        После того как ты сгенерируешь вопрос и ответы, проверь имеют ли они вообще смыслб и переделай если нужно.

        Обязательный формат ответа:
        ВОПРОС: [сам вопрос]
        ПРАВИЛЬНЫЙ ОТВЕТ: [правильный ответ]
        ОБЪЯСНЕНИЕ: [1-2 интересных факта, объясняющих правильный ответ]
        НЕПРАВИЛЬНЫЕ ОТВЕТЫ: [ответ1], [ответ2], [ответ3]

        Помни, это дружеская викторина - используй разговорный стиль, но без упрощения содержания."""

        response = clientGoogle.models.generate_content(
            model="gemini-2.0-flash",
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
        category = random.choice(CATEGORIES)
        question_data = get_question_from_gemini(category)
        
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


def answer_callback(call, bot, player_stats, cursor):
    user_id = str(call.from_user.id)
    player_name = player_stats[user_id]["player_name"]
    answer = call.data.split('_')[1]
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

    original_question, players_responses = result[0], result[1]

    if isinstance(players_responses, str):
        players_responses = json.loads(players_responses)

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

    save_question_state(question_id, original_question, players_responses, cursor)
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
