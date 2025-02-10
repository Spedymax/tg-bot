import os
import random
import subprocess
import json
from time import sleep
import psycopg2
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
import telebot
from telebot import types
import logging

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import re

# ============================
# Spotify аутентификация
# ============================
client_id = "9bf48d25628445f4a046b633498a0933"
client_secret = "db437688f371473b92a2e54c8e8199b5"

sp = spotipy.Spotify(
    client_credentials_manager=SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
)


def extract_playlist_id(playlist_url):
    match = re.search(r'playlist/([a-zA-Z0-9]+)', playlist_url)
    if not match:
        raise ValueError("Неверный формат URL плейлиста")
    return match.group(1)


def get_tracks_from_playlist(playlist_url):
    playlist_id = extract_playlist_id(playlist_url)
    track_uris = []
    results = sp.playlist_items(playlist_id)
    track_items = results['items']
    while results['next']:
        results = sp.next(results)
        track_items.extend(results['items'])
    # Собираем список URL треков
    for item in track_items:
        track = item.get('track')
        if track:
            track_uris.append(track['external_urls']['spotify'])
    return track_uris


# ============================
# Конфигурация и константы
# ============================
logging.basicConfig(level=logging.INFO)

TELEGRAM_BOT_TOKEN = "7815692651:AAGBWOiEBMbulQOC_-6uvvBl9oF08pn3cJ0"
# DB_CONN_STRING = "dbname='server-tg-pisunchik' user='postgres' password='123' host='192.168.8.2'"
DB_CONN_STRING = "dbname='server-tg-pisunchik' user='admin' password='Sokoez32' host='localhost'"
DOWNLOAD_DIR = "../downloads"
# YOUR_CHAT_ID = 741542965  # Замените на свой Telegram chat id
YOUR_CHAT_ID = -1001294162183  # Замените на свой Telegram chat id

MATCHUP_TIME = "12:00"  # Формат ЧЧ:ММ

# Плейлисты Spotify для каждого друга
PLAYLISTS = {
    "Max": "https://open.spotify.com/playlist/0gwy0oCdOogcb37FWQunFm?si=d97101113244400f",
    "Yura": "https://open.spotify.com/playlist/0MeiPQyQh3Nd3mDr5JleQM?si=2e5924faaaa345aa",
    "Bogdan": "https://open.spotify.com/playlist/4xGkrno4vquibfnoherdvO?si=a7d23312d4184714"
}

song_pools = {}
for friend, playlist_url in PLAYLISTS.items():
    try:
        song_pools[friend] = get_tracks_from_playlist(playlist_url)
    except Exception as e:
        print(f"Ошибка при получении плейлиста для {friend}: {e}")

# Переменные турнира
current_tournament_round = []  # список песен, каждая – dict с "track_uri" и "friend"
current_matchup = None
current_round_number = 1
current_round_size = 0

# Файл для сохранения состояния турнира
STATE_FILE = "tournament_state.json"
pending_tournament_choice = False


def save_tournament_state():
    state = {
        "current_tournament_round": current_tournament_round,
        "current_round_number": current_round_number,
        "current_round_size": current_round_size
    }
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    logging.info("Текущее состояние турнира сохранено.")


def load_tournament_state():
    global current_tournament_round, current_round_number, current_round_size
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)
    current_tournament_round = state.get("current_tournament_round", [])
    current_round_number = state.get("current_round_number", 1)
    current_round_size = state.get("current_round_size", len(current_tournament_round))
    logging.info("Состояние турнира загружено: Раунд %d, песен в игре: %d", current_round_number, current_round_size)


# ============================
# Инициализация базы данных
# ============================
def init_db():
    conn = psycopg2.connect(DB_CONN_STRING)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS matchups (
        id SERIAL PRIMARY KEY,
        round INTEGER,
        matchup_date TIMESTAMP,
        song1_track_uri TEXT,
        song1_friend TEXT,
        song2_track_uri TEXT,
        song2_friend TEXT,
        song1_votes INTEGER DEFAULT 0,
        song2_votes INTEGER DEFAULT 0,
        winner_track_uri TEXT,
        winner_friend TEXT,
        processed BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS votes (
        id SERIAL PRIMARY KEY,
        matchup_id INTEGER REFERENCES matchups(id),
        voter_id TEXT,
        vote INTEGER,
        vote_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS tournament_rounds (
        id SERIAL PRIMARY KEY,
        round INTEGER,
        song_track_uri TEXT,
        song_friend TEXT,
        eliminated BOOLEAN DEFAULT FALSE,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    cur.close()
    conn.close()


# ============================
# Вспомогательные функции для БД
# ============================
def insert_matchup_into_db(matchup_data, round_number):
    try:
        conn = psycopg2.connect(DB_CONN_STRING)
        cur = conn.cursor()
        query = """
        INSERT INTO matchups (round, matchup_date, song1_track_uri, song1_friend, song2_track_uri, song2_friend)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id;
        """
        matchup_date = datetime.now()
        cur.execute(query, (round_number, matchup_date,
                            matchup_data["song1"]["track_uri"],
                            matchup_data["song1"]["friend"],
                            matchup_data["song2"]["track_uri"],
                            matchup_data["song2"]["friend"]))
        matchup_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        logging.info("Матч записан в БД с ID %s", matchup_id)
        return matchup_id
    except Exception as e:
        logging.error("Ошибка записи матча в БД: %s", str(e))
        return None


def insert_vote_into_db(matchup_id, voter_id, vote_value):
    try:
        conn = psycopg2.connect(DB_CONN_STRING)
        cur = conn.cursor()
        query = """
        INSERT INTO votes (matchup_id, voter_id, vote)
        VALUES (%s, %s, %s);
        """
        cur.execute(query, (matchup_id, voter_id, int(vote_value)))
        conn.commit()
        cur.close()
        conn.close()
        logging.info("Голос записан для матча %s", matchup_id)
    except Exception as e:
        logging.error("Ошибка записи голоса в БД: %s", str(e))


def finalize_matchup_in_db(matchup_id, vote1, vote2, winner_song):
    try:
        conn = psycopg2.connect(DB_CONN_STRING)
        cur = conn.cursor()
        query = """
        UPDATE matchups SET song1_votes = %s, song2_votes = %s, winner_track_uri = %s, winner_friend = %s, processed = TRUE
        WHERE id = %s;
        """
        cur.execute(query, (vote1, vote2, winner_song["track_uri"], winner_song["friend"], matchup_id))
        conn.commit()
        cur.close()
        conn.close()
        logging.info("Матч %s завершён в БД", matchup_id)
    except Exception as e:
        logging.error("Ошибка завершения матча в БД: %s", str(e))


def record_tournament_round(round_number, songs):
    try:
        conn = psycopg2.connect(DB_CONN_STRING)
        cur = conn.cursor()
        for song in songs:
            query = """
            INSERT INTO tournament_rounds (round, song_track_uri, song_friend, eliminated)
            VALUES (%s, %s, %s, %s)
            """
            cur.execute(query, (round_number, song["track_uri"], song["friend"], False))
        conn.commit()
        cur.close()
        conn.close()
        logging.info("Раунд %s записан в БД", round_number)
    except Exception as e:
        logging.error("Ошибка записи раунда в БД: %s", str(e))


# ============================
# Вспомогательные функции для турнира
# ============================
def get_round_threshold():
    global current_round_size
    if current_round_size % 2 == 0:
        return current_round_size // 2
    else:
        return (current_round_size // 2) + 1


def finalize_round():
    global current_round_number, current_round_size, current_tournament_round
    bot.send_message(YOUR_CHAT_ID, f"Раунд {current_round_number} завершён. Продолжаем бой!")
    record_tournament_round(current_round_number, current_tournament_round)
    current_round_number += 1
    current_round_size = len(current_tournament_round)
    save_tournament_state()
    bot.send_message(YOUR_CHAT_ID, f"Начинается раунд {current_round_number} с {current_round_size} песнями.")


def initialize_tournament():
    global current_tournament_round, current_round_number, current_round_size
    all_songs = []
    for friend, songs in song_pools.items():
        for track_uri in songs:
            all_songs.append({"track_uri": track_uri, "friend": friend})
    random.shuffle(all_songs)
    current_tournament_round = all_songs
    current_round_number = 1
    current_round_size = len(current_tournament_round)
    logging.info("Турнир инициализирован с %d песнями.", current_round_size)
    save_tournament_state()


# ============================
# Spotify Download Helper
# ============================
def download_song(track_uri):
    try:
        cmd = ["spotdl", "--output", DOWNLOAD_DIR, track_uri]
        logging.info("Скачиваем песню %s", track_uri)
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        if result.returncode != 0:
            logging.error("Не удалось скачать %s: %s", track_uri, result.stderr)
            return None
        files = os.listdir(DOWNLOAD_DIR)
        if not files:
            return None
        files.sort(key=lambda f: os.path.getctime(os.path.join(DOWNLOAD_DIR, f)), reverse=True)
        file_path = os.path.join(DOWNLOAD_DIR, files[0])
        return file_path
    except Exception as e:
        logging.exception("Исключение при скачивании %s: %s", track_uri, str(e))
        return None


def delete_file(file_path):
    try:
        os.remove(file_path)
    except Exception as e:
        logging.error("Не удалось удалить файл %s: %s", file_path, str(e))


# ============================
# Telegram Bot Setup
# ============================
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)


# ============================
# Обработка перезапуска турнира
# ============================
@bot.message_handler(func=lambda message: pending_tournament_choice and message.from_user.id == YOUR_CHAT_ID)
def handle_tournament_choice(message):
    global pending_tournament_choice
    text = message.text.strip().lower()
    if text == "новый":
        initialize_tournament()
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
        pending_tournament_choice = False
        bot.reply_to(message, "Новый турнир запущен! Пусть музыка зазвучит!")
    elif text == "продолжить":
        load_tournament_state()
        pending_tournament_choice = False
        bot.reply_to(message, "Продолжаем старый турнир. Удачи!")
    else:
        bot.reply_to(message, "Пожалуйста, отправьте 'новый' или 'продолжить'.")


# ============================
# Daily Matchup Posting
# ============================
def post_daily_matchup():
    global current_matchup, current_tournament_round

    if len(current_tournament_round) < 2:
        bot.send_message(YOUR_CHAT_ID, "Раунд окончен! Подведём итоги.")
        finalize_round()
        return

    # Если осталось ровно 3 песни – объявляем полуфинал
    if len(current_tournament_round) == 3:
        bot.send_message(YOUR_CHAT_ID, "🔥 Полуфинал! Осталось 3 песни. Готовьтесь к решающему бою!")
    # Если осталось ровно 2 песни – объявляем финал
    if len(current_tournament_round) == 2:
        bot.send_message(YOUR_CHAT_ID, "🏆 Финал! Остались последние 2 песни. Это битва за титул чемпиона!")
        idx1, idx2 = 0, 1
        song1 = current_tournament_round[idx1]
        song2 = current_tournament_round[idx2]
    else:
        possible_pairs = []
        for i in range(len(current_tournament_round)):
            for j in range(i + 1, len(current_tournament_round)):
                if current_tournament_round[i]["friend"] != current_tournament_round[j]["friend"]:
                    possible_pairs.append((i, j))
        if not possible_pairs and len(current_tournament_round) == 2:
            bot.send_message(YOUR_CHAT_ID, "🏆 Финал! Последние 2 песни готовы к битве!")
            idx1, idx2 = 0, 1
            song1 = current_tournament_round[idx1]
            song2 = current_tournament_round[idx2]
        elif not possible_pairs:
            bot.send_message(YOUR_CHAT_ID, "Упс! Недостаточно песен для матча. Попробуйте позже!")
            return
        else:
            idx1, idx2 = random.choice(possible_pairs)
            song1 = current_tournament_round[idx1]
            song2 = current_tournament_round[idx2]

    file1 = download_song(song1["track_uri"])
    file2 = download_song(song2["track_uri"])
    if file1 is None:
        bot.send_message(YOUR_CHAT_ID, f"😕 Не удалось скачать песню от {song1['friend']}: {song1['track_uri']}")
        return
    if file2 is None:
        bot.send_message(YOUR_CHAT_ID, f"😕 Не удалось скачать песню от {song2['friend']}: {song2['track_uri']}")
        delete_file(file1)
        return

    try:
        bot.send_audio(YOUR_CHAT_ID, audio=open(file1, 'rb'))
    except Exception as e:
        bot.send_message(YOUR_CHAT_ID, f"😬 Проблема с отправкой аудио первой песни: {str(e)}")
        delete_file(file1)
        delete_file(file2)
        return
    try:
        bot.send_audio(YOUR_CHAT_ID, audio=open(file2, 'rb'))
    except Exception as e:
        bot.send_message(YOUR_CHAT_ID, f"😬 Проблема с отправкой аудио второй песни: {str(e)}")
        delete_file(file1)
        delete_file(file2)
        return

    delete_file(file1)
    delete_file(file2)

    markup = types.InlineKeyboardMarkup()
    btn1 = types.InlineKeyboardButton("Голосовать за Песню 1", callback_data="vote|1")
    btn2 = types.InlineKeyboardButton("Голосовать за Песню 2", callback_data="vote|2")
    markup.row(btn1, btn2)

    trivia_msg = bot.send_message(
        YOUR_CHAT_ID,
        "🎶 Выберите победителя! Текущие голоса:\nПесня 1: 0\nПесня 2: 0",
        reply_markup=markup
    )

    matchup_data = {
        "song1": {"track_uri": song1["track_uri"], "friend": song1["friend"]},
        "song2": {"track_uri": song2["track_uri"], "friend": song2["friend"]}
    }
    matchup_id = insert_matchup_into_db(matchup_data, current_round_number)
    current_matchup = {
        "matchup_id": matchup_id,
        "song1": matchup_data["song1"],
        "song2": matchup_data["song2"],
        "votes": {"1": set(), "2": set()},
        "trivia_msg_id": trivia_msg.message_id,
        "chat_id": YOUR_CHAT_ID,
        "reply_markup": markup,
        "indices": (idx1, idx2)
    }
    logging.info("Матч опубликован между %s и %s", song1["track_uri"], song2["track_uri"])


# ============================
# Обработка голосования (Callback)
# ============================
@bot.callback_query_handler(func=lambda call: call.data.startswith("vote|"))
def handle_vote(call):
    global current_matchup
    if current_matchup is None:
        bot.answer_callback_query(call.id, "Ой, сейчас нет активного матча. Подождите, пожалуйста!")
        return
    parts = call.data.split("|")
    if len(parts) != 2:
        bot.answer_callback_query(call.id, "Неверный формат голосования. Попробуйте ещё раз!")
        return
    vote_value = parts[1]
    voter_id = str(call.from_user.id)
    if voter_id in current_matchup["votes"]["1"] or voter_id in current_matchup["votes"]["2"]:
        bot.answer_callback_query(call.id, "Вы уже отдали свой голос!")
        return
    current_matchup["votes"][vote_value].add(voter_id)
    if current_matchup["matchup_id"] is not None:
        insert_vote_into_db(current_matchup["matchup_id"], voter_id, vote_value)
    vote1_count = len(current_matchup["votes"]["1"])
    vote2_count = len(current_matchup["votes"]["2"])
    new_text = (
        "🎤 Текущие голоса:\n"
        f"Песня 1: {vote1_count} голосов\n"
        f"Песня 2: {vote2_count} голосов\n"
    )
    try:
        bot.edit_message_text(new_text,
                              chat_id=current_matchup["chat_id"],
                              message_id=current_matchup["trivia_msg_id"],
                              reply_markup=current_matchup["reply_markup"])
    except Exception as e:
        logging.error("Ошибка редактирования сообщения: %s", str(e))
    bot.answer_callback_query(call.id, "Спасибо за голос, рок-звезда!")
    total_votes = vote1_count + vote2_count
    if total_votes >= 2:
        finalize_matchup()


def finalize_matchup():
    global current_matchup, current_tournament_round, current_round_size
    if current_matchup is None:
        return
    vote1 = len(current_matchup["votes"]["1"])
    vote2 = len(current_matchup["votes"]["2"])
    if vote1 == vote2:
        bot.send_message(current_matchup["chat_id"], "Ничья! 🤝 Нет победителя в этом матче, попробуйте снова!")
        current_matchup = None
        return
    winner_vote = "1" if vote1 > vote2 else "2"
    loser_vote = "2" if winner_vote == "1" else "1"
    winner_song = current_matchup["song1"] if winner_vote == "1" else current_matchup["song2"]
    loser_song = current_matchup["song1"] if loser_vote == "1" else current_matchup["song2"]
    bot.send_message(current_matchup["chat_id"],
                     f"И победитель – песня от {winner_song['friend']}! ({vote1} против {vote2} голосов)")
    if current_matchup["matchup_id"] is not None:
        finalize_matchup_in_db(current_matchup["matchup_id"], vote1, vote2, winner_song)
    idx1, idx2 = current_matchup["indices"]
    if current_tournament_round[idx1]["track_uri"] == loser_song["track_uri"]:
        del current_tournament_round[idx1]
    elif current_tournament_round[idx2]["track_uri"] == loser_song["track_uri"]:
        del current_tournament_round[idx2]
    else:
        logging.error("Поражённая песня не найдена в текущем раунде.")
    current_matchup = None
    save_tournament_state()
    threshold = get_round_threshold()
    if len(current_tournament_round) == 1:
        winner = current_tournament_round[0]
        bot.send_message(YOUR_CHAT_ID,
                         f"🏆 Финальный победитель: Поздравляем песню от {winner['friend']}! Победа заслужена!")
        record_tournament_round(current_round_number, current_tournament_round)
        initialize_tournament()  # Запускаем новый турнир для следующей серии.
    elif len(current_tournament_round) <= threshold:
        finalize_round()


# ============================
# Команды для объявления турнира и информации
# ============================
@bot.message_handler(commands=['announce_tournament'])
def announce_tournament(message):
    rules = (
        "Привет, участники музыкального турнира!\n\n"
        "Правила турнира:\n"
        "1. Турнир состоит из дуэлей между песнями из плейлистов друзей.\n"
        "2. В каждом матче выбирается 2 песни, и вы голосуете за ту, которая вам нравится больше.\n"
        "3. Каждый участник может отдать только один голос за матч.\n"
        "4. Победители переходят в следующий раунд, а проигравшие – выбывают.\n"
        "5. Когда останется 3 песни, объявляем полуфинал, а при 2 – финал!\n\n"
        "Чтобы голосовать, нажимайте на кнопку под аудио. Удачи и пусть победит лучшая музыка! 🎶"
    )
    bot.reply_to(message, rules)


@bot.message_handler(commands=['tournament_info'])
def tournament_info(message):
    global current_round_size, current_tournament_round, current_round_number, current_matchup
    competing = len(current_tournament_round)
    eliminated = current_round_size - competing
    info_text = f"Раунд: {current_round_number}\n"
    info_text += f"Ещё в игре: {competing}\n"
    info_text += f"Вылетели: {eliminated}\n"
    bot.reply_to(message, info_text)


@bot.message_handler(commands=['manual_matchup'])
def manual_matchup(message):
    post_daily_matchup()
    bot.reply_to(message, "Ручной запуск матча активирован! Пусть начнётся музыкальная битва!")


@bot.message_handler(commands=['reset_tournament'])
def reset_tournament(message):
    initialize_tournament()
    bot.reply_to(message, f"🎉 Турнир сброшен! В игре {len(current_tournament_round)} песен.")


@bot.message_handler(commands=['debug_status'])
def debug_status(message):
    status = "🔍 Текущий раунд:\n"
    for i, song in enumerate(current_tournament_round):
        status += f"{i + 1}. Песня от {song['friend']} - {song['track_uri']}\n"
    if current_matchup:
        status += "\n🔥 Активный матч:\n"
        status += f"Песня 1: {current_matchup['song1']['track_uri']} от {current_matchup['song1']['friend']} (Голоса: {len(current_matchup['votes']['1'])})\n"
        status += f"Песня 2: {current_matchup['song2']['track_uri']} от {current_matchup['song2']['friend']} (Голоса: {len(current_matchup['votes']['2'])})\n"
    else:
        status += "\nМатч отсутствует. Всё спокойно!"
    bot.reply_to(message, status)


@bot.message_handler(commands=['simulate_vote'])
def simulate_vote(message):
    """
    Для отладки: симулировать голос.
    Использование: /simulate_vote 1 или /simulate_vote 2
    """
    global current_matchup
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "Использование: /simulate_vote <1 или 2>")
            return
        vote_value = parts[1]
        if vote_value not in ["1", "2"]:
            bot.reply_to(message, "Значение голоса должно быть 1 или 2.")
            return
        voter_id = str(message.from_user.id)
        if current_matchup is None:
            bot.reply_to(message, "Нет активного матча для голосования. Попробуйте позже!")
            return
        if voter_id in current_matchup["votes"]["1"] or voter_id in current_matchup["votes"]["2"]:
            bot.reply_to(message, "Вы уже отдали голос!")
            return
        current_matchup["votes"][vote_value].add(voter_id)
        if current_matchup["matchup_id"] is not None:
            insert_vote_into_db(current_matchup["matchup_id"], voter_id, vote_value)
        vote1_count = len(current_matchup["votes"]["1"])
        vote2_count = len(current_matchup["votes"]["2"])
        new_text = (
            "🎤 Текущие голоса:\n"
            f"Песня 1: {vote1_count} голосов\n"
            f"Песня 2: {vote2_count} голосов\n"
        )
        try:
            bot.edit_message_text(new_text,
                                  chat_id=current_matchup["chat_id"],
                                  message_id=current_matchup["trivia_msg_id"],
                                  reply_markup=current_matchup["reply_markup"])
        except Exception as e:
            logging.error("Ошибка редактирования сообщения: %s", str(e))
        total_votes = vote1_count + vote2_count
        bot.reply_to(message,
                     f"Симуляция голоса для варианта {vote_value} завершена. Всего голосов: {total_votes}. Продолжайте битву!")
        if total_votes >= 2:
            finalize_matchup()
    except Exception as e:
        bot.reply_to(message, f"Упс, ошибка при симуляции голосования: {str(e)}")


# ============================
# Планирование ежедневных матчей
# ============================
scheduler = BackgroundScheduler()


def schedule_daily_matchup():
    """
    Запланировать ежедневный матч на время MATCHUP_TIME.
    APScheduler будет вызывать post_daily_matchup() каждый день.
    """
    now = datetime.now()
    target_time = datetime.strptime(MATCHUP_TIME, "%H:%M").replace(year=now.year, month=now.month, day=now.day)
    if now > target_time:
        target_time += timedelta(days=1)
    delay_seconds = (target_time - now).total_seconds()
    scheduler.add_job(post_daily_matchup, 'interval', days=1, next_run_time=target_time)
    scheduler.start()
    logging.info("Ежедневный матч запланирован на %s (через %d секунд)", MATCHUP_TIME, int(delay_seconds))


# ============================
# Основное выполнение
# ============================
if __name__ == "__main__":
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)
    init_db()

    # При запуске бота проверяем, есть ли сохранённое состояние турнира.
    if os.path.exists(STATE_FILE):
        pending_tournament_choice = True
        bot.send_message(YOUR_CHAT_ID,
                         "Найден сохранённый турнир. Напишите 'новый', чтобы начать новый турнир, или 'продолжить', чтобы возобновить старый.")
    else:
        initialize_tournament()

    schedule_daily_matchup()
    bot.infinity_polling()
