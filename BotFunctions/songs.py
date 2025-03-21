# DB_CONN_STRING = "dbname='server-tg-pisunchik' user='postgres' password='123' host='192.168.8.2'"

# YOUR_CHAT_ID = 741542965  # Замените на свой Telegram chat id

import os
import subprocess
import json

import psycopg2
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
import telebot
from telebot import types
import logging
import re

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

# ============================
# Spotify Аутентификация
# ============================
client_id = "9bf48d25628445f4a046b633498a0933"
client_secret = "db437688f371473b92a2e54c8e8199b5"
MAX_ID = 741542965

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
DB_CONN_STRING = "dbname='server-tg-pisunchik' user='admin' password='Sokoez32' host='localhost'"
DOWNLOAD_DIR = "../downloads"
YOUR_CHAT_ID = -1001294162183  # Замените на свой Telegram chat id

# Расписание матчей: 2 голосования в день (например, в 12:00 и 18:00)
MATCHUP_TIMES = ["12:00", "18:00"]

# Плейлисты Spotify для каждого участника (примерно по 12 треков в каждом)
PLAYLISTS = {
    "Max": "https://open.spotify.com/playlist/6GWIvmFtFQ9ZM7K5rkW3D6?si=fdefb484eaa54b41",
    "Yura": "https://open.spotify.com/playlist/1dAbSSXLOQtchgDEk9fT8n?si=duZs2KIATI6P5y0rR8u1Dw&pi=ovW_dnvHSui0Z",
    "Bogdan": "https://open.spotify.com/playlist/2lG3kJGp3TKf8L2fb85tIi?si=fcX3CtcpQs6jSDv8RxlEDg"
}

song_pools = {}
for friend, playlist_url in PLAYLISTS.items():
    try:
        song_pools[friend] = get_tracks_from_playlist(playlist_url)
    except Exception as e:
        print(f"Ошибка при получении плейлиста для {friend}: {e}")

# ============================
# Функция формирования пар с ограничением по friend
# ============================
def create_pairs(songs):
    """
    Формирует пары так, чтобы песни от разных участников парились максимально равномерно.
    """
    import random

    # Группировка песен по участнику
    groups = {}
    for song in songs:
        groups.setdefault(song["friend"], []).append(song)

    pairs = []
    remaining_songs = songs.copy()  # Создаем копию списка всех песен

    while len(remaining_songs) > 1:
        song1 = random.choice(remaining_songs)
        remaining_songs.remove(song1)
        
        # Ищем песню другого участника
        other_songs = [s for s in remaining_songs if s["friend"] != song1["friend"]]
        
        if other_songs:  # Если есть песни других участников
            song2 = random.choice(other_songs)
        else:  # Если остались только песни того же участника
            song2 = random.choice(remaining_songs)
            
        remaining_songs.remove(song2)
        pairs.append((song1, song2))

    # Если осталась одна песня, даём ей "бай"
    if remaining_songs:
        pairs.append((remaining_songs[0], None))

    return pairs


# ============================
# Переменные турнира (Bracket)
# ============================
# Каждый раунд – список матчей, где матч = (song1, song2).
# Если матч сыгран, для хранения результата он преобразуется в список:
# [song1, song2, {"winner": winner_song, "vote1": X, "vote2": Y}]
bracket = []           # Список раундов
current_round_index = 0  # Индекс текущего раунда
current_matchup_index = 0  # Индекс текущего матча в раунде
active_matchup = None  # Текущий активный матч

STATE_FILE = "tournament_bracket_state.json"

def save_tournament_state():
    state = {
        "bracket": bracket,
        "current_round_index": current_round_index,
        "current_matchup_index": current_matchup_index
    }
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    logging.info("Состояние турнира сохранено.")

def load_tournament_state():
    global bracket, current_round_index, current_matchup_index
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)
    bracket = state.get("bracket", [])
    current_round_index = state.get("current_round_index", 0)
    current_matchup_index = state.get("current_matchup_index", 0)
    logging.info("Состояние турнира загружено: Раунд %d, матч %d", current_round_index+1, current_matchup_index+1)

def initialize_bracket_tournament():
    global bracket, current_round_index, current_matchup_index
    all_songs = []
    for friend, songs in song_pools.items():
        for track_uri in songs:
            all_songs.append({"track_uri": track_uri, "friend": friend})
    # Используем функцию create_pairs для формирования первого раунда
    first_round = create_pairs(all_songs)
    bracket = [first_round]
    current_round_index = 0
    current_matchup_index = 0
    save_tournament_state()
    bot.send_message(YOUR_CHAT_ID, f"🎉 Новый турнир запущен! Раунд 1, пар: {len(first_round)}.")

# ============================
# Работа с БД
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
    conn.commit()
    cur.close()
    conn.close()

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
        if os.path.exists(file_path):
            os.remove(file_path)
        else:
            logging.warning("Файл %s не существует и не может быть удалён.", file_path)
    except Exception as e:
        logging.error("Не удалось удалить файл %s: %s", file_path, str(e))

# ============================
# Telegram Bot Setup
# ============================
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# ============================
# Публикация матча (Bracket)
# ============================
def post_daily_matchup_bracket():
    global current_matchup_index, active_matchup, bracket, current_round_index

    # Если текущий раунд закончен, переходим к следующему
    if current_matchup_index >= len(bracket[current_round_index]):
        bot.send_message(YOUR_CHAT_ID, f"Раунд {current_round_index+1} завершён. Подготовка следующего раунда...")
        build_next_round()
        return

    matchup = bracket[current_round_index][current_matchup_index]
    # Если второй участник отсутствует – бай
    if matchup[1] is None:
        bot.send_message(YOUR_CHAT_ID, f"Песня от {matchup[0]['friend']} ({matchup[0]['track_uri']}) получает бай и проходит в следующий раунд!")
        record_matchup_result(matchup, winner=matchup[0], vote1=0, vote2=0)
        current_matchup_index += 1
        save_tournament_state()
        post_daily_matchup_bracket()
        return

    # Скачиваем аудио для обоих участников
    file1 = download_song(matchup[0]["track_uri"])
    file2 = download_song(matchup[1]["track_uri"])
    if file1 is None:
        bot.send_message(YOUR_CHAT_ID, f"Не удалось скачать песню от {matchup[0]['friend']}")
        return
    if file2 is None:
        bot.send_message(YOUR_CHAT_ID, f"Не удалось скачать песню от {matchup[1]['friend']}")
        delete_file(file1)
        return

    try:
        bot.send_audio(YOUR_CHAT_ID, audio=open(file1, 'rb'))
    except Exception as e:
        bot.send_message(YOUR_CHAT_ID, f"Ошибка отправки аудио первой песни: {str(e)}")
        delete_file(file1)
        return
    try:
        bot.send_audio(YOUR_CHAT_ID, audio=open(file2, 'rb'))
    except Exception as e:
        bot.send_message(YOUR_CHAT_ID, f"Ошибка отправки аудио второй песни: {str(e)}")
        delete_file(file2)
        return

    delete_file(file1)
    delete_file(file2)

    # Клавиатура для голосования
    markup = types.InlineKeyboardMarkup()
    btn1 = types.InlineKeyboardButton("Голосовать за Песню 1", callback_data="bracket_vote|1")
    btn2 = types.InlineKeyboardButton("Голосовать за Песню 2", callback_data="bracket_vote|2")
    markup.row(btn1, btn2)

    msg = bot.send_message(YOUR_CHAT_ID,
                           "🎶 Выберите победителя матча:",
                           reply_markup=markup)
    active_matchup = {
        "round": current_round_index + 1,
        "match_index": current_matchup_index,
        "song1": matchup[0],
        "song2": matchup[1],
        "votes": {"1": set(), "2": set()},
        "trivia_msg_id": msg.message_id,
        "chat_id": YOUR_CHAT_ID,
        "reply_markup": markup,
        "matchup_id": insert_matchup_into_db({
            "song1": matchup[0],
            "song2": matchup[1]
        }, current_round_index+1)
    }
    logging.info("Матч опубликован: %s vs %s", matchup[0]["track_uri"], matchup[1]["track_uri"])

@bot.callback_query_handler(func=lambda call: call.data.startswith("bracket_vote|"))
def handle_bracket_vote(call):
    global active_matchup, current_matchup_index
    if active_matchup is None:
        bot.answer_callback_query(call.id, "Нет активного матча.")
        return
    parts = call.data.split("|")
    if len(parts) != 2:
        bot.answer_callback_query(call.id, "Неверный формат голосования.")
        return
    vote_value = parts[1]
    voter_id = str(call.from_user.id)
    if voter_id in active_matchup["votes"]["1"] or voter_id in active_matchup["votes"]["2"]:
        bot.answer_callback_query(call.id, "Вы уже голосовали!")
        return
    active_matchup["votes"][vote_value].add(voter_id)
    if active_matchup["matchup_id"]:
        insert_vote_into_db(active_matchup["matchup_id"], voter_id, vote_value)
    vote1_count = len(active_matchup["votes"]["1"])
    vote2_count = len(active_matchup["votes"]["2"])
    new_text = f"🎤 Текущие голоса:\nПесня 1: {vote1_count}\nПесня 2: {vote2_count}"
    try:
        bot.edit_message_text(new_text,
                              chat_id=active_matchup["chat_id"],
                              message_id=active_matchup["trivia_msg_id"],
                              reply_markup=active_matchup["reply_markup"])
    except Exception as e:
        logging.error("Ошибка редактирования сообщения: %s", str(e))
    bot.answer_callback_query(call.id, "Голос засчитан!")
    total_votes = vote1_count + vote2_count
    if total_votes >= 3:
        finalize_matchup_bracket()


ADMIN_IDS = [741542965]  # Добавьте сюда ID администраторов

@bot.message_handler(commands=['vote_for'])
def vote_for_player(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "❌ Эта команда доступна только администраторам.")
        return
        
    try:
        # Формат: /vote_for user_id song_number
        parts = message.text.split()
        if len(parts) != 3:
            bot.reply_to(message, "❌ Использование: /vote_for user_id song_number")
            return
            
        voter_id = parts[1]
        vote_value = parts[2]
        
        if active_matchup is None:
            bot.reply_to(message, "❌ Нет активного матча.")
            return
            
        if voter_id in active_matchup["votes"]["1"] or voter_id in active_matchup["votes"]["2"]:
            bot.reply_to(message, "❌ Этот пользователь уже голосовал!")
            return
            
        if vote_value not in ["1", "2"]:
            bot.reply_to(message, "❌ Номер песни должен быть 1 или 2")
            return
            
        active_matchup["votes"][vote_value].add(voter_id)
        if active_matchup["matchup_id"]:
            insert_vote_into_db(active_matchup["matchup_id"], voter_id, vote_value)
            
        vote1_count = len(active_matchup["votes"]["1"])
        vote2_count = len(active_matchup["votes"]["2"])
        
        new_text = f"🎤 Текущие голоса:\nПесня 1: {vote1_count}\nПесня 2: {vote2_count}"
        bot.edit_message_text(new_text,
                            chat_id=active_matchup["chat_id"],
                            message_id=active_matchup["trivia_msg_id"],
                            reply_markup=active_matchup["reply_markup"])
                            
        bot.reply_to(message, f"✅ Голос пользователя {voter_id} за песню {vote_value} засчитан!")
        
        total_votes = vote1_count + vote2_count
        if total_votes >= 3:
            finalize_matchup_bracket()
            
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {str(e)}")

# Добавим функцию для уведомления неголосовавших
def notify_non_voters():
    if active_matchup is None:
        return
        
    # Словарь с ID пользователей и их именами в Telegram
    participants = {
        742272644: "spedymax",
        741542965: "Spatifilum",
        855951767: "lofiSnitch"
    }
    
    
    participants2 = {
        742272644: "Макс",
        741542965: "Юра",
        855951767: "Богдан"
    }

    # Проверяем, что active_matchup и его поля существуют
    if not isinstance(active_matchup, dict) or "votes" not in active_matchup:
        return
        
    voted_participants = set().union(
        active_matchup["votes"].get("1", set()),
        active_matchup["votes"].get("2", set())
    )
    non_voters = set(participants.keys()) - voted_participants
    disabled_link=types.LinkPreviewOptions(is_disabled=True)
    if non_voters:
        # Создаем упоминания с помощью HTML-разметки
        mention_text = " ".join([f"<a href='https://t.me/{participants[uid]}'>@{participants2[uid]}</a>" for uid in non_voters])
        bot.reply_to(active_matchup["trivia_msg_id"],
                        f"⚠️ Напоминание! {mention_text}\n"
                        f"У вас есть 30 минут, чтобы проголосовать в текущем матче!",
                        parse_mode='HTML', link_preview_options=disabled_link)


def finalize_matchup_bracket():
    global active_matchup, current_matchup_index
    if active_matchup is None:
        return
    vote1 = len(active_matchup["votes"]["1"])
    vote2 = len(active_matchup["votes"]["2"])
    if vote1 == vote2:
        bot.send_message(YOUR_CHAT_ID, "Ничья! Голосование повторяется.")
        active_matchup = None
        return
    winner_vote = "1" if vote1 > vote2 else "2"
    loser_vote = "2" if winner_vote == "1" else "1"
    winner_song = active_matchup["song1"] if winner_vote == "1" else active_matchup["song2"]
    loser_song = active_matchup["song1"] if loser_vote == "1" else active_matchup["song2"]
    
    # Отправка аудио и названия песни победителя
    file_path = download_song(winner_song["track_uri"])
    if file_path:
        try:
            bot.send_audio(YOUR_CHAT_ID, audio=open(file_path, 'rb'))
            bot.send_message(YOUR_CHAT_ID, f"Победитель матча – песня от {winner_song['friend']}!\nНазвание: {winner_song['track_uri']}")
        except Exception as e:
            bot.send_message(YOUR_CHAT_ID, f"Ошибка отправки аудио победителя: {str(e)}")
        finally:
            delete_file(file_path)
    else:
        bot.send_message(YOUR_CHAT_ID, f"Не удалось скачать песню победителя от {winner_song['friend']}")

    if active_matchup["matchup_id"]:
        finalize_matchup_in_db(active_matchup["matchup_id"], vote1, vote2, winner_song)
    record_matchup_result(bracket[current_round_index][current_matchup_index], winner_song, vote1, vote2)
    active_matchup = None
    current_matchup_index += 1
    save_tournament_state()

def record_matchup_result(matchup, winner, vote1=0, vote2=0):
    matchup_result = {"winner": winner, "vote1": vote1, "vote2": vote2}
    bracket[current_round_index][current_matchup_index] = [matchup[0], matchup[1], matchup_result]

def build_next_round():
    global bracket, current_round_index, current_matchup_index
    winners = []
    for match in bracket[current_round_index]:
        if isinstance(match, list) and len(match) == 3 and "winner" in match[2]:
            winners.append(match[2]["winner"])
    if not winners:
        bot.send_message(YOUR_CHAT_ID, "Ошибка: не найдено победителей текущего раунда.")
        return
    if len(winners) == 1:
        bot.send_message(YOUR_CHAT_ID, f"🏆 Чемпион турнира – песня от {winners[0]['friend']}!")
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
        initialize_bracket_tournament()
        return
    # Используем create_pairs для формирования нового раунда
    next_round = create_pairs(winners)
    bracket.append(next_round)
    current_round_index += 1
    current_matchup_index = 0
    save_tournament_state()
    bot.send_message(YOUR_CHAT_ID, f"Начинается раунд {current_round_index+1} с {len(next_round)} матчами.")
    post_daily_matchup_bracket()

# ============================
# Визуализация таблицы турнира (брекета)
# ============================
def visualize_bracket():
    visual = ""
    for r_idx, round_matches in enumerate(bracket):
        visual += f"Раунд {r_idx+1}:\n"
        for m_idx, match in enumerate(round_matches):
            if isinstance(match, list) and len(match) == 3 and "winner" in match[2]:
                song1 = match[0]
                song2 = match[1]
                winner = match[2]["winner"]
                # Проверяем оба участника на None
                if song1 is None and song2 is None:
                    visual += f"  Матч {m_idx+1}: Пустой матч\n"
                elif song1 is None:
                    visual += f"  Матч {m_idx+1}: БАЙ vs {song2['friend']} -> Победитель: {winner['friend']}\n"
                elif song2 is None:
                    visual += f"  Матч {m_idx+1}: {song1['friend']} (БАЙ) -> Победитель: {winner['friend']}\n"
                else:
                    visual += f"  Матч {m_idx+1}: {song1['friend']} vs {song2['friend']} -> Победитель: {winner['friend']}\n"
            else:
                song1 = match[0]
                song2 = match[1]
                # Проверяем оба участника на None для текущих матчей
                if song1 is None and song2 is None:
                    visual += f"  Матч {m_idx+1}: Пустой матч\n"
                elif song1 is None:
                    visual += f"  Матч {m_idx+1}: БАЙ vs {song2['friend']}\n"
                elif song2 is None:
                    visual += f"  Матч {m_idx+1}: {song1['friend']} -> БАЙ\n"
                else:
                    visual += f"  Матч {m_idx+1}: {song1['friend']} vs {song2['friend']} -> (ожидается голосование)\n"
        visual += "\n"
    return visual

@bot.message_handler(commands=['bracket'])
def show_bracket(message):
    bracket_visual = visualize_bracket()
    bot.reply_to(message, f"Текущая таблица турнира:\n\n{bracket_visual}")

# ============================
# Команды для управления турниром
# ============================
@bot.message_handler(commands=['start_tournament'])
def cmd_start_tournament(message):
    if os.path.exists(STATE_FILE):
        load_tournament_state()
        bot.send_message(MAX_ID, "Продолжаем существующий турнир!")
        post_daily_matchup_bracket()
    else:
        initialize_bracket_tournament()

@bot.message_handler(func=lambda message: message.text.lower() in ["новый", "продолжить"])
def handle_tournament_choice(message):
    if message.text.lower() == "новый":
        initialize_bracket_tournament()
        bot.reply_to(message, "Запущен новый турнир!")
    elif message.text.lower() == "продолжить":
        load_tournament_state()
        bot.reply_to(message, "Продолжаем старый турнир!")
        post_daily_matchup_bracket()

@bot.message_handler(commands=['manual_matchup'])
def manual_matchup(message):
    post_daily_matchup_bracket()
    bot.reply_to(message, "Ручной запуск матча активирован! ")

# ============================
# Планирование матчей – 2 в день
# ============================
scheduler = BackgroundScheduler()

def schedule_daily_matchups():
    now = datetime.now()
    for t in MATCHUP_TIMES:
        target_time = datetime.strptime(t, "%H:%M").replace(year=now.year, month=now.month, day=now.day)
        if now > target_time:
            target_time += timedelta(days=1)
        scheduler.add_job(post_daily_matchup_bracket, 'interval', days=1, next_run_time=target_time)
        logging.info("Матч запланирован на %s (через %d секунд)", t, int((target_time - now).total_seconds()))

def schedule_reminder_before_matchup():
    for t in MATCHUP_TIMES:
        reminder_time = datetime.strptime(t, "%H:%M") - timedelta(minutes=30)
        reminder_time = reminder_time.strftime("%H:%M")
        scheduler.add_job(notify_non_voters, 'cron', hour=reminder_time.split(":")[0], 
                        minute=reminder_time.split(":")[1])


# ============================
# Основное выполнение
# ============================

if __name__ == "__main__":
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)
    init_db()
    if os.path.exists(STATE_FILE):
        load_tournament_state()
        post_daily_matchup_bracket()
    else:
        initialize_bracket_tournament()
    
    # Убедитесь, что планирование задач выполняется только один раз
    if not scheduler.get_jobs():
        schedule_daily_matchups()
        schedule_reminder_before_matchup()
    
    scheduler.start()
    bot.infinity_polling()
