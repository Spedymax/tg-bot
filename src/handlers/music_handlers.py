import logging
import os
import asyncio
import psycopg
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from config.settings import Settings
from database.db_manager import DatabaseManager
from services.spotify_service import SpotifyService
from services.tournament_service import TournamentService

logger = logging.getLogger(__name__)


class MusicHandlers:
    """Handlers for music tournament commands and callbacks."""

    def __init__(self, bot: Bot):
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

        self.router = Router()
        self._register()

    def _register(self):
        """Register all music-related handlers."""

        @self.router.callback_query(F.data.startswith("bracket_vote|"))
        async def handle_bracket_vote(call: CallbackQuery):
            """Handle vote callback from inline keyboard."""
            parts = call.data.split("|")
            if len(parts) != 2:
                await call.answer("Invalid vote format.")
                return

            vote_value = parts[1]
            message, success = await self.tournament_service.handle_vote(call.from_user.id, vote_value)
            await call.answer(message)

        @self.router.message(Command('vote_for'))
        async def vote_for_player(message: Message):
            """Admin command to vote on behalf of a user."""
            if message.from_user.id not in ADMIN_IDS:
                await message.reply("❌ This command is only available to administrators.")
                return

            try:
                # Format: /vote_for user_id song_number
                parts = message.text.split()
                if len(parts) != 3:
                    await message.reply("❌ Usage: /vote_for user_id song_number")
                    return

                voter_id = parts[1]
                vote_value = parts[2]

                response_message, success = await self.tournament_service.handle_admin_vote(voter_id, vote_value)
                await message.reply(response_message)
            except Exception as e:
                await message.reply(f"❌ Error: {str(e)}")

        @self.router.message(Command('bracket'))
        async def show_bracket(message: Message):
            """Display the current tournament bracket."""
            bracket_visual = self.tournament_service.visualize_bracket()
            await message.reply(f"Current tournament bracket:\n\n{bracket_visual}")

        @self.router.message(Command('start_tournament'))
        async def cmd_start_tournament(message: Message):
            """Start or continue a tournament."""
            if os.path.exists(STATE_FILE):
                self.tournament_service.load_tournament_state()
                await self.bot.send_message(MAX_ID, "Continuing existing tournament!")
                await self.tournament_service.post_daily_matchup()
            else:
                self.tournament_service.initialize_tournament(self.song_pools)
                await self.bot.send_message(MAX_ID, 'Music bot started! New tournament created')

        @self.router.message(Command('new_tournament'))
        async def cmd_new_tournament(message: Message):
            """Force start a new tournament."""
            if message.from_user.id not in ADMIN_IDS:
                await message.reply("❌ This command is only available to administrators.")
                return

            self.tournament_service.initialize_tournament(self.song_pools)
            await message.reply("New tournament started!")

        @self.router.message(Command('manual_matchup'))
        async def manual_matchup(message: Message):
            """Manually trigger the next matchup."""
            if message.from_user.id not in ADMIN_IDS:
                await message.reply("❌ This command is only available to administrators.")
                return

            await self.tournament_service.post_daily_matchup()
            await message.reply("Manual matchup activated!")

        @self.router.message(Command('leaderboard'))
        async def show_leaderboard(message: Message):
            """Show song leaderboard."""
            leaderboard = await self.tournament_service.get_leaderboard()
            await message.reply(leaderboard)

        @self.router.message(Command('playlist_stats'))
        async def show_playlist_stats(message: Message):
            """Show statistics for each playlist."""
            stats = await self.tournament_service.get_friend_stats()
            await message.reply(stats)

        @self.router.message(Command('winners_playlist'))
        async def create_winners_playlist(message: Message):
            """Generate a playlist of tournament winners."""
            try:
                # Get winners from completed matchups
                query = """
                    SELECT DISTINCT winner_track_uri, created_at
                    FROM matchups
                    WHERE processed = TRUE
                    ORDER BY created_at DESC
                    LIMIT 20;
                """

                async with await psycopg.AsyncConnection.connect(self.db_manager.conn_string, autocommit=True) as conn:
                    cursor = await conn.execute(query)
                    winner_uris = [row[0] for row in await cursor.fetchall()]

                if not winner_uris:
                    await message.reply("No winners found yet!")
                    return

                # Generate playlist text
                playlist_text = await asyncio.to_thread(
                    self.spotify_service.create_playlist_from_tracks, winner_uris, "Tournament Winners"
                )
                await message.reply(playlist_text)

            except Exception as e:
                logger.error(f"Error creating winners playlist: {str(e)}")
                await message.reply("Error creating playlist")

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
                import asyncio as _asyncio
                _asyncio.create_task(self.bot.send_message(MAX_ID, 'Music bot started! Existing tournament loaded'))
            else:
                self.tournament_service.initialize_tournament(self.song_pools)
                import asyncio as _asyncio
                _asyncio.create_task(self.bot.send_message(MAX_ID, 'Music bot started! New tournament created'))

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


def register_music_handlers(bot: Bot) -> MusicHandlers:
    """Register music handlers with the bot and return the handler instance."""
    return MusicHandlers(bot)
