"""Database manager wrapper for backwards compatibility"""
import psycopg2
import logging

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Wrapper for database operations compatible with songs.py"""

    def __init__(self, conn_string: str):
        self.conn_string = conn_string
        logger.info(f"DatabaseManager initialized with connection string")

    def get_connection(self):
        """Get a new database connection."""
        try:
            conn = psycopg2.connect(self.conn_string)
            return conn
        except Exception as e:
            logger.error(f"Error connecting to database: {e}")
            raise

    def init_db(self):
        """Initialize database tables if they don't exist."""
        try:
            conn = self.get_connection()
            cur = conn.cursor()

            # Create matchups table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS matchups (
                    id SERIAL PRIMARY KEY,
                    round_number INTEGER,
                    matchup_number INTEGER,
                    track1_uri TEXT,
                    track2_uri TEXT,
                    track1_friend TEXT,
                    track2_friend TEXT,
                    winner_track_uri TEXT,
                    processed BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create votes table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS votes (
                    id SERIAL PRIMARY KEY,
                    matchup_id INTEGER REFERENCES matchups(id),
                    user_id BIGINT,
                    track_uri TEXT,
                    voted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(matchup_id, user_id)
                )
            """)

            conn.commit()
            cur.close()
            conn.close()
            logger.info("Database tables initialized")
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            raise
