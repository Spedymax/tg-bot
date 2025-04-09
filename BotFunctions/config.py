import os
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()

# Spotify credentials
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "9bf48d25628445f4a046b633498a0933")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "db437688f371473b92a2e54c8e8199b5")

# Telegram config
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7815692651:AAGBWOiEBMbulQOC_-6uvvBl9oF08pn3cJ0")
# YOUR_CHAT_ID = int(os.getenv("YOUR_CHAT_ID", "-1001294162183"))
YOUR_CHAT_ID = int(os.getenv("YOUR_CHAT_ID", "741542965"))
MAX_ID = int(os.getenv("MAX_ID", "741542965"))
ADMIN_IDS = [int(id) for id in os.getenv("ADMIN_IDS", "741542965").split(",")]

# Database config
# DB_CONN_STRING = os.getenv("DB_CONN_STRING", "dbname='server-tg-pisunchik' user='admin' password='Sokoez32' host='localhost'")
DB_CONN_STRING = os.getenv("DB_CONN_STRING", "dbname='server-tg-pisunchik' user='postgres' password='123' host='192.168.8.2'")

# Paths
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "../downloads")
STATE_FILE = os.getenv("STATE_FILE", "tournament_bracket_state.json")

# Tournament config
MATCHUP_TIMES = os.getenv("MATCHUP_TIMES", "12:00,18:00").split(",")
MIN_VOTES_TO_FINALIZE = int(os.getenv("MIN_VOTES_TO_FINALIZE", "3"))
REMINDER_MINUTES_BEFORE = int(os.getenv("REMINDER_MINUTES_BEFORE", "30"))

# Playlists
PLAYLISTS = {
    "Max": os.getenv("MAX_PLAYLIST", "https://open.spotify.com/playlist/6GWIvmFtFQ9ZM7K5rkW3D6?si=fdefb484eaa54b41"),
    "Yura": os.getenv("YURA_PLAYLIST", "https://open.spotify.com/playlist/1dAbSSXLOQtchgDEk9fT8n?si=duZs2KIATI6P5y0rR8u1Dw&pi=ovW_dnvHSui0Z"),
    "Bogdan": os.getenv("BOGDAN_PLAYLIST", "https://open.spotify.com/playlist/2lG3kJGp3TKf8L2fb85tIi?si=fcX3CtcpQs6jSDv8RxlEDg")
}

# User mapping for notifications
PARTICIPANTS = {
    742272644: {"username": "spedymax", "display_name": "Макс"},
    741542965: {"username": "Spatifilum", "display_name": "Юра"},
    855951767: {"username": "lofiSnitch", "display_name": "Богдан"}
}