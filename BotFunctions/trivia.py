import requests
import html
from telebot import types
import json

correct_answer = ''
api_requests = ['general_knowledge', 'history', 'geography']
YURA_ID = 742272644
MAX_ID = 741542965
BODYA_ID = 855951767
NIKA_ID = 1085180226
VIKA_ID = 1561630034


def send_trivia_questions(message, random, bot, cursor, conn, headers):
    chat_id = message.chat.id
    global correct_answer
    number = random.randint(0, len(api_requests) - 1)
    while True:
        try:
            response = requests.get(
                f'https://the-trivia-api.com/v2/questions?limit=1&categories={api_requests[number]}&difficulties=easy,medium')
            response_data = response.json()
            break
        except:
            pass
    question = response_data[0]['question']['text']
    bot.send_message(MAX_ID, response_data[0]['correctAnswer'])
    answer_options = response_data[0]['incorrectAnswers'] + [response_data[0]['correctAnswer']]
    question = html.unescape(question)

    # Get a funny answer based on the question
    funny_answer = get_funny_answer(question, answer_options, headers)

    # Replace one of the answer options with the funny answer
    index_to_replace = random.randint(0, len(answer_options) - 1)
    answer_options[index_to_replace] = funny_answer

    # Update the correct answer if it was replaced with a funny one
    if index_to_replace == len(answer_options) - 1:
        correct_answer = funny_answer
    else:
        correct_answer = response_data[0]['correctAnswer']

    # Shuffle the answer options
    random.shuffle(answer_options)

    # Unescape HTML entities in answer options
    answer_options = [html.unescape(item) for item in answer_options]

    # Unescape HTML entities in correct answer
    correct_answer = html.unescape(correct_answer)

    save_question(question, correct_answer, cursor, conn)  # Сохраняем вопрос и ответ в базу данных

    markup = types.InlineKeyboardMarkup()
    for answer in answer_options:
        button = types.InlineKeyboardButton(text=f"{answer}", callback_data=f"answer_{answer}")
        markup.add(button)
    reset_answered_questions()
    bot.send_message(chat_id, "Внимание вопрос!")
    bot.send_message(chat_id, question, reply_markup=markup, parse_mode='html')


def send_trivia_questions2(random, bot, cursor, conn, headers):
    global correct_answer
    chat_id = [-1001294162183, -4087198265]
    number = random.randint(0, len(api_requests) - 1)
    while True:
        try:
            response = requests.get(
                f'https://the-trivia-api.com/v2/questions?limit=1&categories={api_requests[number]}&difficulties=easy,medium')
            response_data = response.json()
            break
        except:
            pass
    question = response_data[0]['question']['text']
    answer_options = response_data[0]['incorrectAnswers'] + [response_data[0]['correctAnswer']]
    question = html.unescape(question)

    # Get a funny answer based on the question
    funny_answer = get_funny_answer(question, answer_options, headers)

    # Replace one of the answer options with the funny answer
    index_to_replace = random.randint(0, len(answer_options) - 1)
    answer_options[index_to_replace] = funny_answer

    # Update the correct answer if it was replaced with a funny one
    if index_to_replace == len(answer_options) - 1:
        correct_answer = funny_answer
    else:
        correct_answer = response_data[0]['correctAnswer']

    # Shuffle the answer options
    random.shuffle(answer_options)

    # Unescape HTML entities in answer options
    answer_options = [html.unescape(item) for item in answer_options]

    # Unescape HTML entities in correct answer
    correct_answer = html.unescape(correct_answer)

    save_question(question, correct_answer, cursor, conn)  # Сохраняем вопрос и ответ в базу данных

    markup = types.InlineKeyboardMarkup()
    for answer in answer_options:
        button = types.InlineKeyboardButton(text=f"{answer}", callback_data=f"answer_{answer}")
        markup.add(button)
    reset_answered_questions()
    for chat in chat_id:
        bot.send_message(chat,
                         "Внимание вопрос!")
        bot.send_message(chat,
                         question,
                         reply_markup=markup, parse_mode='html')


# Function to reset answered questions after sending out questions for the day
def reset_answered_questions():
    global answered_questions
    answered_questions = {}


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

        response = requests.post('https://api.openai.com/v1/chat/completions', headers=headers,
                                 data=json.dumps(data))
        response_data = response.json()
        funny_answer = response_data['choices'][0]['message']['content']
    except:
        funny_answer = "Funny moment не будет(("
    return funny_answer


def save_question(question, correct_answer, cursor, conn):
    cursor.execute("INSERT INTO questions VALUES (%s, %s)", (question, correct_answer))
    conn.commit()


def get_correct_answers(message, bot, pisunchik, cursor):
    trivia = load_trivia_data(cursor)
    bot.send_message(message.chat.id, f'А вот и правильные ответы:')
    for i in range(0, len(trivia)):
        question = trivia[-1 - i]['question']
        answer = trivia[-1 - i]['correct_answer']
        bot.send_message(message.chat.id, f'Вопрос: {question} \nОтвет: {answer}')
    bot.send_message(message.chat.id, f'Итого у игроков правильных ответов:')
    bot.send_message(message.chat.id,
                     f'{pisunchik[str(MAX_ID)]["player_name"]} : {pisunchik[str(MAX_ID)]["correct_answers"]}')
    bot.send_message(message.chat.id,
                     f'{pisunchik[str(YURA_ID)]["player_name"]} : {pisunchik[str(YURA_ID)]["correct_answers"]}')
    bot.send_message(message.chat.id,
                     f'{pisunchik[str(BODYA_ID)]["player_name"]} : {pisunchik[str(BODYA_ID)]["correct_answers"]}')
    bot.send_message(message.chat.id,
                     f'{pisunchik[str(NIKA_ID)]["player_name"]} : {pisunchik[str(NIKA_ID)]["correct_answers"]}')


def get_correct_answers2(bot, pisunchik, cursor):
    chat_id = [-1001294162183, -4087198265]
    for chat in chat_id:
        trivia = load_trivia_data(cursor)
        bot.send_message(chat, f'А вот и правильные ответы:')
        for i in range(0, len(trivia)):
            if i >= 3:
                break
            question = trivia[-1 - i]['question']
            answer = trivia[-1 - i]['correct_answer']
            bot.send_message(chat, f'Вопрос: {question} \nОтвет: {answer}')
        bot.send_message(chat, f'Итого у игроков правильных ответов:')
        bot.send_message(chat,
                         f'{pisunchik[str(MAX_ID)]["player_name"]} : {pisunchik[str(MAX_ID)]["correct_answers"]}')
        bot.send_message(chat,
                         f'{pisunchik[str(YURA_ID)]["player_name"]} : {pisunchik[str(YURA_ID)]["correct_answers"]}')
        bot.send_message(chat,
                         f'{pisunchik[str(BODYA_ID)]["player_name"]} : {pisunchik[str(BODYA_ID)]["correct_answers"]}')
        bot.send_message(chat,
                         f'{pisunchik[str(NIKA_ID)]["player_name"]} : {pisunchik[str(NIKA_ID)]["correct_answers"]}')
        clear_trivia_data()


answered_questions = {}  # Keep track of which questions each user has answered


def clear_trivia_data(cursor, conn):
    cursor.execute("DELETE FROM questions")
    conn.commit()


def load_trivia_data(cursor):
    cursor.execute("SELECT * FROM questions")  # Получаем все записи из таблицы
    data = cursor.fetchall()
    trivia = []

    for row in data:
        question, corr_answer = row
        trivia.append({'question': question, 'correct_answer': corr_answer})

    return trivia


def answer_callback(call, bot, pisunchik, cursor, conn):
    global correct_answer
    user_id = str(call.from_user.id)
    answer = call.data.split('_')[1]

    # Check if the user has already answered a question today
    if user_id in answered_questions:
        bot.send_message(call.message.chat.id, "Вы уже ответили на вопрос сегодня.")
        return

    if answer == correct_answer:
        pisunchik[user_id]["correct_answers"] += 1

    # Update the answered questions dictionary
    answered_questions[user_id] = correct_answer

    bot.send_message(call.message.chat.id, f'Игрок {pisunchik[user_id]["player_name"]} сделал свой выбор...')
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