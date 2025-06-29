import logging
import os
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from telebot import types
import telebot

from config.settings import Settings
from database.db_manager import DatabaseManager
from services.spotify_service import SpotifyService
from services.tournament_service import TournamentService

logger = logging.getLogger(__name__)


class MusicHandlers:
    """Handlers for music tournament commands and callbacks."""
    
    def __init__(self, bot: telebot.TeleBot):
        self.bot = bot
        self.db_manager = DatabaseManager(DB_CONN_STRING)
        self.spotify_service = SpotifyService(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, DOWNLOAD_DIR)
        self.tournament_service = TournamentService(
            STATE_FILE, bot, YOUR_CHAT_ID, self.db_manager, self.spotify_service
        )
        
        # Load song pools from playlists
        self.song_pools = {}
        for friend, playlist_url in PLAYLISTS.items():
            try:
                self.song_pools[friend] = self.spotify_service.get_tracks_from_playlist(playlist_url)
                logger.info(f"Loaded {len(self.song_pools[friend])} tracks for {friend}")
            except Exception as e:
                logger.error(f"Error loading playlist for {friend}: {str(e)}")
        
        self.scheduler = None
        self._register_handlers()

    def _register_handlers(self):
        """Register all music-related handlers."""
        
        # Callback handlers
        @self.bot.callback_query_handler(func=lambda call: call.data.startswith("bracket_vote|"))
        def handle_bracket_vote(call):
            """Handle vote callback from inline keyboard."""
            parts = call.data.split("|")
            if len(parts) != 2:
                self.bot.answer_callback_query(call.id, "Invalid vote format.")
                return

            vote_value = parts[1]
            message, success = self.tournament_service.handle_vote(call.from_user.id, vote_value)
            self.bot.answer_callback_query(call.id, message)

        # Command handlers
        @self.bot.message_handler(commands=['vote_for'])
        def vote_for_player(message):
            """Admin command to vote on behalf of a user."""
            if message.from_user.id not in ADMIN_IDS:
                self.bot.reply_to(message, "❌ This command is only available to administrators.")
                return
                
            try:
                # Format: /vote_for user_id song_number
                parts = message.text.split()
                if len(parts) != 3:
                    self.bot.reply_to(message, "❌ Usage: /vote_for user_id song_number")
                    return
                    
                voter_id = parts[1]
                vote_value = parts[2]
                
                response_message, success = self.tournament_service.handle_admin_vote(voter_id, vote_value)
                self.bot.reply_to(message, response_message)
            except Exception as e:
                self.bot.reply_to(message, f"❌ Error: {str(e)}")

        @self.bot.message_handler(commands=['bracket'])
        def show_bracket(message):
            """Display the current tournament bracket."""
            bracket_visual = self.tournament_service.visualize_bracket()
            self.bot.reply_to(message, f"Current tournament bracket:\n\n{bracket_visual}")

        @self.bot.message_handler(commands=['start_tournament'])
        def cmd_start_tournament(message):
            """Start or continue a tournament."""
            if os.path.exists(STATE_FILE):
                self.tournament_service.load_tournament_state()
                self.bot.send_message(MAX_ID, "Continuing existing tournament!")
                self.tournament_service.post_daily_matchup()
            else:
                self.tournament_service.initialize_tournament(self.song_pools)
                self.bot.send_message(MAX_ID, 'Music bot started! New tournament created')

        @self.bot.message_handler(commands=['new_tournament'])
        def cmd_new_tournament(message):
            """Force start a new tournament."""
            if message.from_user.id not in ADMIN_IDS:
                self.bot.reply_to(message, "❌ This command is only available to administrators.")
                return

            self.tournament_service.initialize_tournament(self.song_pools)
            self.bot.reply_to(message, "New tournament started!")

        @self.bot.message_handler(commands=['manual_matchup'])
        def manual_matchup(message):
            """Manually trigger the next matchup."""
            if message.from_user.id not in ADMIN_IDS:
                self.bot.reply_to(message, "❌ This command is only available to administrators.")
                return

            self.tournament_service.post_daily_matchup()
            self.bot.reply_to(message, "Manual matchup activated!")

        @self.bot.message_handler(commands=['leaderboard'])
        def show_leaderboard(message):
            """Show song leaderboard."""
            leaderboard = self.tournament_service.get_leaderboard()
            self.bot.reply_to(message, leaderboard)

        @self.bot.message_handler(commands=['playlist_stats'])
        def show_playlist_stats(message):
            """Show statistics for each playlist."""
            stats = self.tournament_service.get_friend_stats()
            self.bot.reply_to(message, stats)

        @self.bot.message_handler(commands=['winners_playlist'])
        def create_winners_playlist(message):
            """Generate a playlist of tournament winners."""
            try:
                # Get winning songs from database
                conn = self.db_manager.get_connection()
                cur = conn.cursor()

                # Get winners from completed matchups
                query = """
                    SELECT DISTINCT winner_track_uri, created_at
                    FROM matchups
                    WHERE processed = TRUE
                    ORDER BY created_at DESC
                    LIMIT 20;
                """

                cur.execute(query)
                winner_uris = [row[0] for row in cur.fetchall()]

                cur.close()
                conn.close()

                if not winner_uris:
                    self.bot.reply_to(message, "No winners found yet!")
                    return

                # Generate playlist text
                playlist_text = self.spotify_service.create_playlist_from_tracks(winner_uris, "Tournament Winners")
                self.bot.reply_to(message, playlist_text)

            except Exception as e:
                logger.error(f"Error creating winners playlist: {str(e)}")
                self.bot.reply_to(message, "Error creating playlist")

    def notify_non_voters(self):
        """Send notification to users who haven't voted."""
        self.tournament_service.notify_non_voters(PARTICIPANTS)

    def schedule_daily_matchups(self):
        """Schedule daily matchups at specified times."""
        self.scheduler = BackgroundScheduler()
        now = datetime.now()

        for t in MATCHUP_TIMES:
            target_time = datetime.strptime(t, "%H:%M").replace(year=now.year, month=now.month, day=now.day)
            if now > target_time:
                target_time += timedelta(days=1)

            self.scheduler.add_job(
                self.tournament_service.post_daily_matchup,
                'interval',
                days=1,
                next_run_time=target_time
            )

            logger.info(f"Matchup scheduled at {t} (in {int((target_time - now).total_seconds())} seconds)")

            # Schedule reminder before matchup
            reminder_time = target_time - timedelta(minutes=REMINDER_MINUTES_BEFORE)
            if now > reminder_time:
                reminder_time += timedelta(days=1)

            self.scheduler.add_job(
                self.notify_non_voters,
                'interval',
                days=1,
                next_run_time=reminder_time,
                id=f'reminder_{t}',
                replace_existing=True
            )

            logger.info(f"Reminder scheduled at {reminder_time.strftime('%H:%M')} (in {int((reminder_time - now).total_seconds())} seconds)")

        return self.scheduler

    def start_music_bot(self):
        """Initialize and start the music tournament bot functionality."""
        try:
            # Ensure download directory exists
            if not os.path.exists(DOWNLOAD_DIR):
                os.makedirs(DOWNLOAD_DIR)

            # Initialize database
            self.db_manager.init_db()

            # Load or create tournament
            if os.path.exists(STATE_FILE):
                self.tournament_service.load_tournament_state()
                self.bot.send_message(MAX_ID, 'Music bot started! Existing tournament loaded')
            else:
                self.tournament_service.initialize_tournament(self.song_pools)
                self.bot.send_message(MAX_ID, 'Music bot started! New tournament created')

            # Start scheduler
            self.scheduler = self.schedule_daily_matchups()
            self.scheduler.start()

            logger.info("Music bot functionality initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error starting music bot: {str(e)}")
            return False

    def stop_music_bot(self):
        """Stop the music bot scheduler."""
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Music bot scheduler stopped")


def register_music_handlers(bot: telebot.TeleBot) -> MusicHandlers:
    """Register music handlers with the bot and return the handler instance."""
    return MusicHandlers(bot)
