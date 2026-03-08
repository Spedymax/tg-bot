import logging
import psycopg
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class DatabaseService:
    """Service for managing database interactions and data persistence."""

    def __init__(self, connection_string: str):
        self.conn_string = connection_string

        # Check if SQLite is being used (not supported by this service)
        if connection_string.startswith('sqlite://'):
            raise ValueError(
                "SQLite is not supported by DatabaseService. "
                "Please configure PostgreSQL connection using DB_CONN_STRING, "
                "or individual DB_HOST, DB_NAME, DB_USER, DB_PASSWORD variables."
            )

    async def init_db(self):
        """Initialize database tables if they do not exist."""
        try:
            async with await psycopg.AsyncConnection.connect(self.conn_string, autocommit=True) as conn:
                # Create matchups table
                await conn.execute("""
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

                # Create votes table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS votes (
                        id SERIAL PRIMARY KEY,
                        matchup_id INTEGER REFERENCES matchups(id),
                        voter_id TEXT,
                        vote INTEGER,
                        vote_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Create analytics table for song statistics
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS song_stats (
                        track_uri TEXT PRIMARY KEY,
                        friend TEXT,
                        total_votes INTEGER DEFAULT 0,
                        wins INTEGER DEFAULT 0,
                        losses INTEGER DEFAULT 0,
                        last_played TIMESTAMP
                    )
                """)

                # Create trivia questions table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS questions (
                        id SERIAL PRIMARY KEY,
                        question TEXT NOT NULL,
                        correct_answer TEXT NOT NULL,
                        answer_options TEXT,
                        explanation TEXT,
                        date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Migration: add id column to questions if it was created without one
                await conn.execute("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'questions' AND column_name = 'id'
                        ) THEN
                            ALTER TABLE questions ADD COLUMN id SERIAL PRIMARY KEY;
                        END IF;
                    END $$;
                """)

                # Create answered questions table (to prevent duplicate answers)
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS answered_questions (
                        id SERIAL PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        question TEXT NOT NULL,
                        date_added DATE DEFAULT CURRENT_DATE
                    )
                """)

                # Create question state table (for active questions)
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS question_state (
                        message_id INTEGER PRIMARY KEY,
                        original_question TEXT NOT NULL,
                        players_responses TEXT
                    )
                """)

                # Create user activity table (for tracking active users)
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS user_activity (
                        id SERIAL PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        chat_id INTEGER NOT NULL,
                        last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Track which questions were sent to which chat (prevents repeats)
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS chat_question_history (
                        id          SERIAL PRIMARY KEY,
                        chat_id     BIGINT NOT NULL,
                        question_id INTEGER NOT NULL REFERENCES questions(id),
                        sent_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_cqh_lookup
                        ON chat_question_history (chat_id, question_id)
                """)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_cqh_sent_at
                        ON chat_question_history (chat_id, sent_at)
                """)

            logger.info("Database initialized successfully")
        except Exception as e:
            logger.error(f"Database initialization error: {str(e)}")
            raise

    async def insert_matchup(self, matchup_data: Dict[str, Dict[str, str]], round_number: int) -> Optional[int]:
        """Insert a new matchup into the database."""
        try:
            query = """
                INSERT INTO matchups (round, matchup_date, song1_track_uri, song1_friend, song2_track_uri, song2_friend)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING id;
            """

            matchup_date = datetime.now()
            async with await psycopg.AsyncConnection.connect(self.conn_string, autocommit=True) as conn:
                cursor = await conn.execute(query, (
                    round_number,
                    matchup_date,
                    matchup_data["song1"]["track_uri"],
                    matchup_data["song1"]["friend"],
                    matchup_data["song2"]["track_uri"],
                    matchup_data["song2"]["friend"]
                ))
                row = await cursor.fetchone()
                matchup_id = row[0]

            logger.info(f"Matchup recorded in DB with ID {matchup_id}")
            return matchup_id
        except Exception as e:
            logger.error(f"Error recording matchup in DB: {str(e)}")
            return None

    async def insert_vote(self, matchup_id: int, voter_id: str, vote_value: int) -> bool:
        """Insert a vote for a matchup."""
        try:
            query = """
                INSERT INTO votes (matchup_id, voter_id, vote)
                VALUES (%s, %s, %s);
            """

            async with await psycopg.AsyncConnection.connect(self.conn_string, autocommit=True) as conn:
                await conn.execute(query, (matchup_id, voter_id, vote_value))

            logger.info(f"Vote recorded for matchup {matchup_id}")
            return True
        except Exception as e:
            logger.error(f"Error recording vote in DB: {str(e)}")
            return False

    async def finalize_matchup(self, matchup_id: int, vote1: int, vote2: int, winner_song: Dict[str, str]) -> bool:
        """Finalize a matchup with vote counts and winner."""
        try:
            query = """
                UPDATE matchups
                SET song1_votes = %s,
                    song2_votes = %s,
                    winner_track_uri = %s,
                    winner_friend = %s,
                    processed = TRUE
                WHERE id = %s;
            """

            async with await psycopg.AsyncConnection.connect(self.conn_string) as conn:
                async with conn.transaction():
                    await conn.execute(query, (
                        vote1,
                        vote2,
                        winner_song["track_uri"],
                        winner_song["friend"],
                        matchup_id
                    ))
                    await self._update_song_stats(conn, matchup_id)

            logger.info(f"Matchup {matchup_id} finalized in DB")
            return True
        except Exception as e:
            logger.error(f"Error finalizing matchup in DB: {str(e)}")
            return False

    async def _update_song_stats(self, conn, matchup_id: int):
        """Update statistics for songs in a matchup."""
        try:
            cursor = await conn.execute("""
                SELECT song1_track_uri, song1_friend, song2_track_uri, song2_friend,
                       winner_track_uri
                FROM matchups
                WHERE id = %s
            """, (matchup_id,))

            result = await cursor.fetchone()
            if not result:
                return

            song1_uri, song1_friend, song2_uri, song2_friend, winner_uri = result

            # Update winner stats
            if winner_uri == song1_uri:
                # Song 1 won
                await self._upsert_song_stats(conn, song1_uri, song1_friend, True)
                await self._upsert_song_stats(conn, song2_uri, song2_friend, False)
            else:
                # Song 2 won
                await self._upsert_song_stats(conn, song2_uri, song2_friend, True)
                await self._upsert_song_stats(conn, song1_uri, song1_friend, False)

        except Exception as e:
            logging.error(f"Error updating song stats: {str(e)}")

    async def _upsert_song_stats(self, conn, track_uri: str, friend: str, is_winner: bool):
        """Insert or update song statistics."""
        try:
            cursor = await conn.execute("""
                SELECT track_uri FROM song_stats WHERE track_uri = %s
            """, (track_uri,))

            if await cursor.fetchone():
                # Update existing record
                if is_winner:
                    await conn.execute("""
                        UPDATE song_stats
                        SET total_votes = total_votes + 1,
                            wins = wins + 1,
                            last_played = CURRENT_TIMESTAMP
                        WHERE track_uri = %s
                    """, (track_uri,))
                else:
                    await conn.execute("""
                        UPDATE song_stats
                        SET total_votes = total_votes + 1,
                            losses = losses + 1,
                            last_played = CURRENT_TIMESTAMP
                        WHERE track_uri = %s
                    """, (track_uri,))
            else:
                # Insert new record
                wins = 1 if is_winner else 0
                losses = 0 if is_winner else 1

                await conn.execute("""
                    INSERT INTO song_stats (track_uri, friend, total_votes, wins, losses, last_played)
                    VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                """, (track_uri, friend, 1, wins, losses))

        except Exception as e:
            logging.error(f"Error upserting song stats: {str(e)}")

    async def get_existing_votes(self, matchup_id: int) -> Dict[str, set]:
        """Get existing votes for a matchup."""
        try:
            query = """
                SELECT voter_id, vote
                FROM votes
                WHERE matchup_id = %s;
            """

            async with await psycopg.AsyncConnection.connect(self.conn_string, autocommit=True) as conn:
                cursor = await conn.execute(query, (matchup_id,))

                votes = {"1": set(), "2": set()}
                for row in await cursor.fetchall():
                    voter_id, vote = row
                    votes[str(vote)].add(str(voter_id))

            return votes
        except Exception as e:
            logger.error(f"Error getting votes from DB: {str(e)}")
            return {"1": set(), "2": set()}

    async def get_song_info(self, track_uri: str) -> Optional[Dict[str, any]]:
        """Get cached song information."""
        try:
            query = """
                SELECT track_uri, friend, total_votes, wins, losses
                FROM song_stats
                WHERE track_uri = %s;
            """

            async with await psycopg.AsyncConnection.connect(self.conn_string, autocommit=True) as conn:
                cursor = await conn.execute(query, (track_uri,))
                result = await cursor.fetchone()

            if result:
                return {
                    "track_uri": result[0],
                    "friend": result[1],
                    "total_votes": result[2],
                    "wins": result[3],
                    "losses": result[4],
                    "win_rate": round(result[3] / (result[3] + result[4]) * 100, 1) if (result[3] + result[4]) > 0 else 0
                }
            return None
        except Exception as e:
            logger.error(f"Error getting song info: {str(e)}")
            return None

    async def get_leaderboard(self, limit: int = 10) -> List[Dict[str, any]]:
        """Get top songs by win rate."""
        try:
            query = """
                SELECT track_uri, friend, wins, losses,
                       CASE WHEN (wins + losses) > 0
                            THEN (wins::float / (wins + losses)::float) * 100
                            ELSE 0
                       END as win_rate
                FROM song_stats
                WHERE (wins + losses) >= 3
                ORDER BY win_rate DESC, wins DESC
                LIMIT %s;
            """

            async with await psycopg.AsyncConnection.connect(self.conn_string, autocommit=True) as conn:
                cursor = await conn.execute(query, (limit,))
                leaderboard = []

                for row in await cursor.fetchall():
                    leaderboard.append({
                        "track_uri": row[0],
                        "friend": row[1],
                        "wins": row[2],
                        "losses": row[3],
                        "win_rate": round(row[4], 1)
                    })

            return leaderboard
        except Exception as e:
            logger.error(f"Error getting leaderboard: {str(e)}")
            return []

    async def get_friend_stats(self) -> List[Dict[str, any]]:
        """Get statistics grouped by friend."""
        try:
            query = """
                SELECT friend,
                       COUNT(*) as songs,
                       SUM(wins) as total_wins,
                       SUM(losses) as total_losses,
                       CASE WHEN SUM(wins + losses) > 0
                            THEN (SUM(wins)::float / SUM(wins + losses)::float) * 100
                            ELSE 0
                       END as win_rate
                FROM song_stats
                GROUP BY friend
                ORDER BY win_rate DESC;
            """

            async with await psycopg.AsyncConnection.connect(self.conn_string, autocommit=True) as conn:
                cursor = await conn.execute(query)
                stats = []

                for row in await cursor.fetchall():
                    stats.append({
                        "friend": row[0],
                        "songs": row[1],
                        "total_wins": row[2],
                        "total_losses": row[3],
                        "win_rate": round(row[4], 1)
                    })

            return stats
        except Exception as e:
            logger.error(f"Error getting friend stats: {str(e)}")
            return []

    async def check_existing_matchup(self, song1_uri: str, song2_uri: str, round_number: int) -> Optional[int]:
        """Check if matchup already exists in database."""
        try:
            query = """
                SELECT id
                FROM matchups
                WHERE song1_track_uri = %s
                  AND song2_track_uri = %s
                  AND round = %s
                  AND processed = FALSE
                ORDER BY created_at DESC LIMIT 1;
            """

            async with await psycopg.AsyncConnection.connect(self.conn_string, autocommit=True) as conn:
                cursor = await conn.execute(query, (song1_uri, song2_uri, round_number))
                result = await cursor.fetchone()

            return result[0] if result else None
        except Exception as e:
            logger.error(f"Error checking existing matchup: {str(e)}")
            return None
