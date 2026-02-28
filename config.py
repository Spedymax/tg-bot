"""Configuration wrapper for backwards compatibility with songs.py"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Spotify Config
SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')

# Telegram Config
SONGS_BOT_TOKEN = os.getenv('SONGS_BOT_TOKEN')
YOUR_CHAT_ID = int(os.getenv('YOUR_CHAT_ID', '-1001294162183'))
MAX_ID = int(os.getenv('MAX_ID', '741542965'))
ADMIN_IDS = [int(x.strip()) for x in os.getenv('ADMIN_IDS', '741542965').split(',')]

# Database Config
DB_CONN_STRING = os.getenv('DB_CONN_STRING', "dbname='server-tg-pisunchik' user='postgres' password='123' host='192.168.8.2'")

# Paths
DOWNLOAD_DIR = os.getenv('DOWNLOAD_DIR', '../downloads')
STATE_FILE = os.getenv('STATE_FILE', 'tournament_bracket_state.json')

# Tournament Config
MATCHUP_TIMES = os.getenv('MATCHUP_TIMES', '12:00,18:00').split(',')
MIN_VOTES_TO_FINALIZE = int(os.getenv('MIN_VOTES_TO_FINALIZE', '3'))
REMINDER_MINUTES_BEFORE = int(os.getenv('REMINDER_MINUTES_BEFORE', '30'))

# Playlists
PLAYLISTS = {
    'Max': os.getenv('MAX_PLAYLIST', 'https://open.spotify.com/playlist/6GWIvmFtFQ9ZM7K5rkW3D6?si=fdefb484eaa54b41'),
    'Yura': os.getenv('YURA_PLAYLIST', 'https://open.spotify.com/playlist/1dAbSSXLOQtchgDEk9fT8n?si=duZs2KIATI6P5y0rR8u1Dw&pi=ovW_dnvHSui0Z'),
    'Bogdan': os.getenv('BOGDAN_PLAYLIST', 'https://open.spotify.com/playlist/2lG3kJGp3TKf8L2fb85tIi?si=fcX3CtcpQs6jSDv8RxlEDg')
}

# Participants (admin IDs by default)
PARTICIPANTS = ADMIN_IDS
