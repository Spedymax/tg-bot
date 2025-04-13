import os
import logging
import telebot
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from telebot import types

# Import configuration and managers
from config import (
    SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, TELEGRAM_BOT_TOKEN,
    YOUR_CHAT_ID, MAX_ID, ADMIN_IDS, DB_CONN_STRING, DOWNLOAD_DIR,
    STATE_FILE, MATCHUP_TIMES, PLAYLISTS, PARTICIPANTS,
    MIN_VOTES_TO_FINALIZE, REMINDER_MINUTES_BEFORE
)
from db_manager import DatabaseManager
from spotify_client import SpotifyClient
from tournament_manager import TournamentManager

# ============================
# Logging configuration
# ============================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================
# Initialize components
# ============================
# Initialize Telegram bot
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# Initialize database manager
db_manager = DatabaseManager(DB_CONN_STRING)

# Initialize Spotify client
spotify_client = SpotifyClient(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, DOWNLOAD_DIR)

# Load song pools from playlists
song_pools = {}
for friend, playlist_url in PLAYLISTS.items():
    try:
        song_pools[friend] = spotify_client.get_tracks_from_playlist(playlist_url)
        logger.info(f"Loaded {len(song_pools[friend])} tracks for {friend}")
    except Exception as e:
        logger.error(f"Error loading playlist for {friend}: {str(e)}")

# Initialize tournament manager
tournament_manager = TournamentManager(STATE_FILE, bot, YOUR_CHAT_ID, db_manager, spotify_client)

# ============================
# Bot command handlers
# ============================
@bot.callback_query_handler(func=lambda call: call.data.startswith("bracket_vote|"))
def handle_bracket_vote(call):
    """Handle vote callback from inline keyboard."""
    parts = call.data.split("|")
    if len(parts) != 2:
        bot.answer_callback_query(call.id, "Invalid vote format.")
        return

    vote_value = parts[1]
    message, success = tournament_manager.handle_vote(call.from_user.id, vote_value)
    bot.answer_callback_query(call.id, message)

@bot.message_handler(commands=['vote_for'])
def vote_for_player(message):
    """Admin command to vote on behalf of a user."""
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "❌ This command is only available to administrators.")
        return
        
    try:
        # Format: /vote_for user_id song_number
        parts = message.text.split()
        if len(parts) != 3:
            bot.reply_to(message, "❌ Usage: /vote_for user_id song_number")
            return
            
        voter_id = parts[1]
        vote_value = parts[2]
        
        message, success = tournament_manager.handle_admin_vote(voter_id, vote_value)
        bot.reply_to(message, message)
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.message_handler(commands=['bracket'])
def show_bracket(message):
    """Display the current tournament bracket."""
    bracket_visual = tournament_manager.visualize_bracket()
    bot.reply_to(message, f"Current tournament bracket:\n\n{bracket_visual}")

@bot.message_handler(commands=['start_tournament'])
def cmd_start_tournament(message):
    """Start or continue a tournament."""
    if os.path.exists(STATE_FILE):
        tournament_manager.load_tournament_state()
        bot.send_message(MAX_ID, "Continuing existing tournament!")
        tournament_manager.post_daily_matchup()
    else:
        tournament_manager.initialize_tournament(song_pools)
        bot.send_message(MAX_ID, 'Music bot started! New tournament created')

@bot.message_handler(commands=['new_tournament'])
def cmd_new_tournament(message):
    """Force start a new tournament."""
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "❌ This command is only available to administrators.")
        return

    tournament_manager.initialize_tournament(song_pools)
    bot.reply_to(message, "New tournament started!")

@bot.message_handler(commands=['manual_matchup'])
def manual_matchup(message):
    """Manually trigger the next matchup."""
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "❌ This command is only available to administrators.")
        return

    tournament_manager.post_daily_matchup()
    bot.reply_to(message, "Manual matchup activated!")

@bot.message_handler(commands=['leaderboard'])
def show_leaderboard(message):
    """Show song leaderboard."""
    leaderboard = tournament_manager.get_leaderboard()
    bot.reply_to(message, leaderboard)

@bot.message_handler(commands=['playlist_stats'])
def show_playlist_stats(message):
    """Show statistics for each playlist."""
    stats = tournament_manager.get_friend_stats()
    bot.reply_to(message, stats)

@bot.message_handler(commands=['winners_playlist'])
def create_winners_playlist(message):
    """Generate a playlist of tournament winners."""
    # Get winning songs from database
    try:
        conn = db_manager.get_connection()
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
            bot.reply_to(message, "No winners found yet!")
            return

        # Generate playlist text
        playlist_text = spotify_client.create_playlist_from_tracks(winner_uris, "Tournament Winners")
        bot.reply_to(message, playlist_text)

    except Exception as e:
        logger.error(f"Error creating winners playlist: {str(e)}")
        bot.reply_to(message, f"Error creating playlist")

# ============================
# Scheduler functions
# ============================
def notify_non_voters():
    """Send notification to users who haven't voted."""
    tournament_manager.notify_non_voters(PARTICIPANTS)

def schedule_daily_matchups():
    """Schedule daily matchups at specified times."""
    scheduler = BackgroundScheduler()
    now = datetime.now()

    for t in MATCHUP_TIMES:
        target_time = datetime.strptime(t, "%H:%M").replace(year=now.year, month=now.month, day=now.day)
        if now > target_time:
            target_time += timedelta(days=1)

        scheduler.add_job(
            tournament_manager.post_daily_matchup,
            'interval',
            days=1,
            next_run_time=target_time
        )

        logger.info(f"Matchup scheduled at {t} (in {int((target_time - now).total_seconds())} seconds)")

        # Schedule reminder before matchup
        reminder_time = target_time - timedelta(minutes=REMINDER_MINUTES_BEFORE)
        if now > reminder_time:
            reminder_time += timedelta(days=1)

        scheduler.add_job(
            notify_non_voters,
            'interval',
            days=1,
            next_run_time=reminder_time,
            id=f'reminder_{t}',
            replace_existing=True
        )

        logger.info(f"Reminder scheduled at {reminder_time.strftime('%H:%M')} (in {int((reminder_time - now).total_seconds())} seconds)")

    return scheduler

# ============================
# Main execution
# ============================
def run_songs_bot():
    """Main function to run the bot."""
    # Ensure download directory exists
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)

    # Initialize database
    db_manager.init_db()

    # Load or create tournament
    if os.path.exists(STATE_FILE):
        tournament_manager.load_tournament_state()
        bot.send_message(MAX_ID, 'Music bot started! Existing tournament loaded')
    else:
        tournament_manager.initialize_tournament(song_pools)
        bot.send_message(MAX_ID, 'Music bot started! New tournament created')

    # Start scheduler
    scheduler = schedule_daily_matchups()
    scheduler.start()

    # Start bot
    logger.info("Bot started, polling for messages...")
    bot.infinity_polling()

if __name__ == "__main__":
    run_songs_bot()
    