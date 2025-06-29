import os
import json
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    """
    Configuration class for the bot.
    Loads settings from environment variables.
    """
    
    def __init__(self):
        # --- Critical Configurations ---
        self.BOT_TOKEN = os.getenv("BOT_TOKEN")
        if not self.BOT_TOKEN:
            raise ValueError("Error: BOT_TOKEN environment variable not set.")

        self.GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
        if not self.GEMINI_API_KEY:
            raise ValueError("Error: GEMINI_API_KEY environment variable not set.")

        # --- Database Configuration ---
        db_conn_string = os.getenv("DB_CONN_STRING")
        if db_conn_string:
            # Use the provided PostgreSQL connection string
            self.DATABASE_URL = db_conn_string
        else:
            # Build from individual components or use default
            db_host = os.getenv('DB_HOST', 'localhost')
            db_name = os.getenv('DB_NAME', 'server-tg-pisunchik')
            db_user = os.getenv('DB_USER', 'postgres')
            db_password = os.getenv('DB_PASSWORD')
            
            if db_password:
                self.DATABASE_URL = f"dbname='{db_name}' user='{db_user}' password='{db_password}' host='{db_host}'"
            else:
                # Default to SQLite if no PostgreSQL credentials
                self.DATABASE_URL = "sqlite:///bot.db"

        # --- Telethon Configuration (for online monitoring) ---
        self.API_ID = os.getenv("API_ID")
        self.API_HASH = os.getenv("API_HASH")
        if not self.API_ID or not self.API_HASH:
            print("Warning: API_ID and/or API_HASH are not set. Online monitoring will be disabled.")

        # --- Bot Administration ---
        try:
            admin_ids_str = os.getenv("ADMIN_IDS", "[]")
            self.ADMIN_IDS = json.loads(admin_ids_str)
        except json.JSONDecodeError:
            # Fallback for comma-separated list
            self.ADMIN_IDS = [int(x.strip()) for x in admin_ids_str.split(',') if x.strip()]
        
        main_chat_id_str = os.getenv("MAIN_CHAT_ID")
        self.MAIN_CHAT_ID = int(main_chat_id_str) if main_chat_id_str else None

