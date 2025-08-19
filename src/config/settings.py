import os
from dotenv import load_dotenv

# Load environment variables from a .env file
load_dotenv()

class Settings:
    DB_CONFIG = {
        'dbname': os.getenv('DB_NAME', 'server-tg-pisunchik'),
        'user': os.getenv('DB_USER', 'postgres'),
        'host': os.getenv('DB_HOST', 'localhost'),
        'password': os.getenv('DB_PASSWORD', ''),
        'port': os.getenv('DB_PORT', 5432),
    }

    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    ADMIN_IDS = [741542965]  # Add more admin IDs if necessary
    CHAT_IDS = {
        'main': -1001294162183,
        'secondary': -1002491624152
    }
    
    # AI configuration
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    
    # Spotify configuration
    SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
    SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')
    
    # Music bot configuration
    SONGS_BOT_TOKEN = os.getenv('SONGS_BOT_TOKEN')
    YOUR_CHAT_ID = os.getenv('YOUR_CHAT_ID', -1001294162183)  # Default to main chat
    MAX_ID = int(os.getenv('MAX_ID', 741542965))  # Default to admin ID
    
    # Database connection string
    DB_CONN_STRING = os.getenv('DB_CONN_STRING', f"postgresql://{os.getenv('DB_USER', 'postgres')}:{os.getenv('DB_PASSWORD', '')}@{os.getenv('DB_HOST', 'localhost')}:{os.getenv('DB_PORT', 5432)}/{os.getenv('DB_NAME', 'server-tg-pisunchik')}")
    
    # File paths
    DOWNLOAD_DIR = os.getenv('DOWNLOAD_DIR', './downloads')
    STATE_FILE = os.getenv('STATE_FILE', './tournament_state.json')
    
    # Tournament configuration
    MATCHUP_TIMES = os.getenv('MATCHUP_TIMES', '12:00,18:00').split(',')
    MIN_VOTES_TO_FINALIZE = int(os.getenv('MIN_VOTES_TO_FINALIZE', 3))
    REMINDER_MINUTES_BEFORE = int(os.getenv('REMINDER_MINUTES_BEFORE', 30))
    
    # Playlists and participants (these should be configured in environment or separate config)
    PLAYLISTS = {
        # Add your playlist configurations here
        # Example: 'friend_name': 'spotify_playlist_url'
    }
    
    PARTICIPANTS = [
        # Add participant user IDs here
        # Example: 123456789, 987654321
    ]
