import os
import logging
from dotenv import load_dotenv

# Load environment variables from a .env file
load_dotenv()

logger = logging.getLogger(__name__)


def _safe_int(value: str, default: int, name: str = "value") -> int:
    """Safely convert string to int with logging on failure."""
    try:
        return int(value)
    except (ValueError, TypeError):
        logger.warning(f"Invalid integer for {name}: '{value}', using default: {default}")
        return default


def _parse_int_list(value: str, default_list: list, name: str = "list") -> list:
    """Parse comma-separated integers with error handling."""
    result = []
    for item in value.split(','):
        item = item.strip()
        if item:
            try:
                result.append(int(item))
            except ValueError:
                logger.warning(f"Invalid integer in {name}: '{item}', skipping")
    return result if result else default_list


class Settings:
    DB_CONFIG = {
        'dbname': os.getenv('DB_NAME', 'server-tg-pisunchik'),
        'user': os.getenv('DB_USER', 'postgres'),
        'host': os.getenv('DB_HOST', 'localhost'),
        'password': os.getenv('DB_PASSWORD', ''),
        'port': _safe_int(os.getenv('DB_PORT', '5432'), 5432, 'DB_PORT'),
    }

    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

    # Admin IDs from environment (comma-separated)
    _admin_ids_str = os.getenv('ADMIN_IDS', '741542965')
    ADMIN_IDS = _parse_int_list(_admin_ids_str, [741542965], 'ADMIN_IDS')

    # Chat IDs from environment
    CHAT_IDS = {
        'main': _safe_int(os.getenv('CHAT_ID_MAIN', '-1001294162183'), -1001294162183, 'CHAT_ID_MAIN'),
        'secondary': _safe_int(os.getenv('CHAT_ID_SECONDARY', '-1002491624152'), -1002491624152, 'CHAT_ID_SECONDARY')
    }

    # Wake-on-LAN configuration
    WOL_MAC_ADDRESS = os.getenv('WOL_MAC_ADDRESS', 'D8:43:AE:BD:2B:F1')
    
    # AI configuration
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
    
    # Spotify configuration
    SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
    SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')
    
    # Music bot configuration
    SONGS_BOT_TOKEN = os.getenv('SONGS_BOT_TOKEN')
    YOUR_CHAT_ID = _safe_int(os.getenv('YOUR_CHAT_ID', '-1001294162183'), -1001294162183, 'YOUR_CHAT_ID')
    MAX_ID = _safe_int(os.getenv('MAX_ID', '741542965'), 741542965, 'MAX_ID')
    
    # Database connection string
    DB_CONN_STRING = os.getenv('DB_CONN_STRING', f"postgresql://{os.getenv('DB_USER', 'postgres')}:{os.getenv('DB_PASSWORD', '')}@{os.getenv('DB_HOST', 'localhost')}:{os.getenv('DB_PORT', 5432)}/{os.getenv('DB_NAME', 'server-tg-pisunchik')}")
    
    # File paths
    DOWNLOAD_DIR = os.getenv('DOWNLOAD_DIR', './downloads')
    STATE_FILE = os.getenv('STATE_FILE', './tournament_state.json')
    
    # Tournament configuration
    MATCHUP_TIMES = os.getenv('MATCHUP_TIMES', '12:00,18:00').split(',')
    MIN_VOTES_TO_FINALIZE = _safe_int(os.getenv('MIN_VOTES_TO_FINALIZE', '3'), 3, 'MIN_VOTES_TO_FINALIZE')
    REMINDER_MINUTES_BEFORE = _safe_int(os.getenv('REMINDER_MINUTES_BEFORE', '30'), 30, 'REMINDER_MINUTES_BEFORE')
    
    # Playlists and participants (these should be configured in environment or separate config)
    PLAYLISTS = {
        # Add your playlist configurations here
        # Example: 'friend_name': 'spotify_playlist_url'
    }
    
    PARTICIPANTS = [
        # Add participant user IDs here
        # Example: 123456789, 987654321
    ]

    # Trivia configuration
    PLAYER_IDS = {
        'YURA': _safe_int(os.getenv('PLAYER_ID_YURA', '742272644'), 742272644, 'PLAYER_ID_YURA'),
        'MAX': _safe_int(os.getenv('PLAYER_ID_MAX', '741542965'), 741542965, 'PLAYER_ID_MAX'),
        'BODYA': _safe_int(os.getenv('PLAYER_ID_BODYA', '855951767'), 855951767, 'PLAYER_ID_BODYA')
    }

    TRIVIA_HOURS = os.getenv('TRIVIA_HOURS', '10:00,15:00,20:00').split(',')
