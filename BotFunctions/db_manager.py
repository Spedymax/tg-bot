import logging
import psycopg2
from datetime import datetime

class DatabaseManager:
    def __init__(self, connection_string):
        self.conn_string = connection_string
        self.init_db()
        
    def get_connection(self):
        """Create and return a database connection."""
        try:
            return psycopg2.connect(self.conn_string)
        except Exception as e:
            logging.error(f"Database connection error: {str(e)}")
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
            cur.execute("""
                CREATE TABLE IF NOT EXISTS votes (
                    id SERIAL PRIMARY KEY,
                    matchup_id INTEGER REFERENCES matchups(id),
                    voter_id TEXT,
                    vote INTEGER,
                    vote_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create analytics table for song statistics
            cur.execute("""
                CREATE TABLE IF NOT EXISTS song_stats (
                    track_uri TEXT PRIMARY KEY,
                    friend TEXT,
                    total_votes INTEGER DEFAULT 0,
                    wins INTEGER DEFAULT 0,
                    losses INTEGER DEFAULT 0,
                    last_played TIMESTAMP
                )
            """)
            
            conn.commit()
            cur.close()
            conn.close()
            logging.info("Database initialized successfully")
        except Exception as e:
            logging.error(f"Database initialization error: {str(e)}")
            raise

    def insert_matchup(self, matchup_data, round_number):
        """Insert a new matchup into the database."""
        try:
            conn = self.get_connection()
            cur = conn.cursor()
            
            query = """
                INSERT INTO matchups (round, matchup_date, song1_track_uri, song1_friend, song2_track_uri, song2_friend)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING id;
            """
            
            matchup_date = datetime.now()
            cur.execute(query, (
                round_number, 
                matchup_date,
                matchup_data["song1"]["track_uri"],
                matchup_data["song1"]["friend"],
                matchup_data["song2"]["track_uri"],
                matchup_data["song2"]["friend"]
            ))
            
            matchup_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            conn.close()
            
            logging.info(f"Matchup recorded in DB with ID {matchup_id}")
            return matchup_id
        except Exception as e:
            logging.error(f"Error recording matchup in DB: {str(e)}")
            return None

    def insert_vote(self, matchup_id, voter_id, vote_value):
        """Insert a vote for a matchup."""
        try:
            conn = self.get_connection()
            cur = conn.cursor()
            
            query = """
                INSERT INTO votes (matchup_id, voter_id, vote)
                VALUES (%s, %s, %s);
            """
            
            cur.execute(query, (matchup_id, voter_id, int(vote_value)))
            conn.commit()
            cur.close()
            conn.close()
            
            logging.info(f"Vote recorded for matchup {matchup_id}")
            return True
        except Exception as e:
            logging.error(f"Error recording vote in DB: {str(e)}")
            return False

    def finalize_matchup(self, matchup_id, vote1, vote2, winner_song):
        """Finalize a matchup with vote counts and winner."""
        try:
            conn = self.get_connection()
            cur = conn.cursor()
            
            # Update the matchup record
            query = """
                UPDATE matchups
                SET song1_votes = %s,
                    song2_votes = %s,
                    winner_track_uri = %s,
                    winner_friend = %s,
                    processed = TRUE
                WHERE id = %s;
            """
            
            cur.execute(query, (
                vote1, 
                vote2, 
                winner_song["track_uri"], 
                winner_song["friend"], 
                matchup_id
            ))
            
            # Update song stats for both songs
            self._update_song_stats(cur, matchup_id)
            
            conn.commit()
            cur.close()
            conn.close()
            
            logging.info(f"Matchup {matchup_id} finalized in DB")
            return True
        except Exception as e:
            logging.error(f"Error finalizing matchup in DB: {str(e)}")
            return False

    def _update_song_stats(self, cursor, matchup_id):
        """Update statistics for songs in a matchup."""
        try:
            # Get matchup details
            cursor.execute("""
                SELECT song1_track_uri, song1_friend, song2_track_uri, song2_friend, 
                       winner_track_uri
                FROM matchups
                WHERE id = %s
            """, (matchup_id,))
            
            result = cursor.fetchone()
            if not result:
                return
                
            song1_uri, song1_friend, song2_uri, song2_friend, winner_uri = result
            
            # Update winner stats
            if winner_uri == song1_uri:
                # Song 1 won
                self._upsert_song_stats(cursor, song1_uri, song1_friend, True)
                self._upsert_song_stats(cursor, song2_uri, song2_friend, False)
            else:
                # Song 2 won
                self._upsert_song_stats(cursor, song2_uri, song2_friend, True)
                self._upsert_song_stats(cursor, song1_uri, song1_friend, False)
                
        except Exception as e:
            logging.error(f"Error updating song stats: {str(e)}")

    def _upsert_song_stats(self, cursor, track_uri, friend, is_winner):
        """Insert or update song statistics."""
        try:
            # Check if song exists
            cursor.execute("""
                SELECT track_uri FROM song_stats WHERE track_uri = %s
            """, (track_uri,))
            
            if cursor.fetchone():
                # Update existing record
                if is_winner:
                    cursor.execute("""
                        UPDATE song_stats
                        SET total_votes = total_votes + 1,
                            wins = wins + 1,
                            last_played = CURRENT_TIMESTAMP
                        WHERE track_uri = %s
                    """, (track_uri,))
                else:
                    cursor.execute("""
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
                
                cursor.execute("""
                    INSERT INTO song_stats (track_uri, friend, total_votes, wins, losses, last_played)
                    VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                """, (track_uri, friend, 1, wins, losses))
                
        except Exception as e:
            logging.error(f"Error upserting song stats: {str(e)}")

    def get_existing_votes(self, matchup_id):
        """Get existing votes for a matchup."""
        try:
            conn = self.get_connection()
            cur = conn.cursor()
            
            query = """
                SELECT voter_id, vote
                FROM votes
                WHERE matchup_id = %s;
            """
            
            cur.execute(query, (matchup_id,))
            
            votes = {"1": set(), "2": set()}
            for row in cur.fetchall():
                voter_id, vote = row
                votes[str(vote)].add(str(voter_id))
                
            cur.close()
            conn.close()
            
            return votes
        except Exception as e:
            logging.error(f"Error getting votes from DB: {str(e)}")
            return {"1": set(), "2": set()}

    def get_song_info(self, track_uri):
        """Get cached song information."""
        try:
            conn = self.get_connection()
            cur = conn.cursor()
            
            query = """
                SELECT track_uri, friend, total_votes, wins, losses
                FROM song_stats
                WHERE track_uri = %s;
            """
            
            cur.execute(query, (track_uri,))
            result = cur.fetchone()
            
            cur.close()
            conn.close()
            
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
            logging.error(f"Error getting song info: {str(e)}")
            return None

    def get_leaderboard(self, limit=10):
        """Get top songs by win rate."""
        try:
            conn = self.get_connection()
            cur = conn.cursor()
            
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
            
            cur.execute(query, (limit,))
            leaderboard = []
            
            for row in cur.fetchall():
                leaderboard.append({
                    "track_uri": row[0],
                    "friend": row[1],
                    "wins": row[2],
                    "losses": row[3],
                    "win_rate": round(row[4], 1)
                })
                
            cur.close()
            conn.close()
            
            return leaderboard
        except Exception as e:
            logging.error(f"Error getting leaderboard: {str(e)}")
            return []

    def get_friend_stats(self):
        """Get statistics grouped by friend."""
        try:
            conn = self.get_connection()
            cur = conn.cursor()
            
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
            
            cur.execute(query)
            stats = []
            
            for row in cur.fetchall():
                stats.append({
                    "friend": row[0],
                    "songs": row[1],
                    "total_wins": row[2],
                    "total_losses": row[3],
                    "win_rate": round(row[4], 1)
                })
                
            cur.close()
            conn.close()
            
            return stats
        except Exception as e:
            logging.error(f"Error getting friend stats: {str(e)}")
            return []