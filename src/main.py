#!/usr/bin/env python3
"""
Refactored Telegram Bot with improved database management and configuration
"""

import json
import logging
import random
import telebot
from datetime import datetime, timezone, timedelta

# Import new configuration and database modules
from config.settings import Settings
from config.game_config import GameConfig
from database.db_manager import DatabaseManager
from database.player_service import PlayerService
from models.player import Player
from services.game_service import GameService
from handlers.game_handlers import GameHandlers
from handlers.admin_handlers import AdminHandlers
from handlers.shop_handlers import ShopHandlers

# Import newly created handlers
from handlers.entertainment_handlers import EntertainmentHandlers
from handlers.trivia_handlers import TriviaHandlers
from handlers.miniapp_handlers import MiniAppHandlers
from services.quiz_scheduler import QuizScheduler
from services.telegram_error_handler import TelegramErrorHandler, telegram_error_handler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class TelegramBot:
    def __init__(self):
        """Initialize the Telegram bot with new architecture"""
        self.bot = telebot.TeleBot(Settings.TELEGRAM_BOT_TOKEN)
        self.db_manager = DatabaseManager()
        self.player_service = PlayerService(self.db_manager)
        self.game_service = GameService(self.player_service)
        
        # Initialize all handlers
        self.game_handlers = GameHandlers(self.bot, self.player_service, self.game_service)
        self.admin_handlers = AdminHandlers(self.bot, self.player_service, self.game_service)
        self.shop_handlers = ShopHandlers(self.bot, self.player_service, self.game_service)
        
        # Initialize entertainment and trivia handlers
        self.entertainment_handlers = EntertainmentHandlers(self.bot, self.player_service, self.game_service)
        self.trivia_handlers = TriviaHandlers(self.bot, self.player_service, self.game_service, self.db_manager)
        
        # Initialize mini-app handlers
        self.miniapp_handlers = MiniAppHandlers(self.bot, self.player_service, self.game_service)
        
        # Initialize quiz scheduler
        self.quiz_scheduler = QuizScheduler(self.bot, self.db_manager, self.trivia_handlers.trivia_service)
        
        # Set quiz scheduler reference in admin handlers
        self.admin_handlers.set_quiz_scheduler(self.quiz_scheduler)

        # Load game data
        self.char = self.load_json_file('assets/data/char.json')
        self.plot = self.load_json_file('assets/data/plot.json')
        self.shop = self.load_json_file('assets/data/shop.json')
        self.statuetki = self.load_json_file('assets/data/statuetki.json')

        # Load game data
        # self.char = self.load_json_file('../assets/data/char.json')
        # self.plot = self.load_json_file('../assets/data/plot.json')
        # self.shop = self.load_json_file('../assets/data/shop.json')
        # self.statuetki = self.load_json_file('../assets/data/statuetki.json')

        # Global state (to be refactored later)
        self.admin_actions = {}
        self.temp_user_data = {}
        self.temp_user_sell_data = {}
        
        logger.info("Bot initialized successfully")

    @staticmethod
    def load_json_file(file_path: str) -> dict:
        """Load JSON file with error handling"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error(f"JSON file not found: {file_path}")
            return {}
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in file: {file_path}")
            return {}

    def setup_handlers(self):
        """Set up all bot command handlers"""
        
        # Setup game handlers first
        self.game_handlers.setup_handlers()
        
        # Setup admin handlers
        self.admin_handlers.setup_handlers()
        
        # Setup shop handlers and load data
        self.shop_handlers.load_shop_data(self.shop, self.statuetki)
        self.shop_handlers.setup_handlers()
        
        # Setup entertainment handlers
        self.entertainment_handlers.setup_handlers()

        # Setup trivia handlers
        self.trivia_handlers.setup_handlers()
        
        # Setup mini-app handlers
        self.miniapp_handlers.setup_handlers()

        @self.bot.message_handler(commands=['start'])
        @telegram_error_handler("start_command")
        def start_game(message):
            """Handle the /start command with new player service"""
            player_id = message.from_user.id
            
            try:
                player = self.player_service.get_player(player_id)
                
                if player:
                    # Existing player
                    TelegramErrorHandler.safe_reply_to(
                        self.bot,
                        message,
                        f"Your pisunchik: {player.pisunchik_size} cm\n"
                        f"You have {player.coins} coins!\n"
                        f"Use /pisunchik to gain cm"
                    )
                else:
                    # New player registration
                    if TelegramErrorHandler.safe_reply_to(self.bot, message, "Добро пожаловать! Напишите ваше имя:"):
                        self.bot.register_next_step_handler(message, self.ask_where_found)
                    
            except Exception as e:
                logger.error(f"Error in start command for user {player_id}: {e}")
                TelegramErrorHandler.safe_reply_to(self.bot, message, "Произошла ошибка. Попробуйте позже.")

        # Registration approval callbacks
        @self.bot.callback_query_handler(func=lambda call: call.data.startswith("registration"))
        def registration_callback(call):
            """Handle registration approval/rejection callbacks"""
            try:
                if call.from_user.id not in Settings.ADMIN_IDS:
                    self.bot.answer_callback_query(call.id, "У вас нет доступа.")
                    return
                
                action = call.data.split("_")[1]
                
                if action == "approve" and hasattr(self, 'pending_registration'):
                    player_data = self.pending_registration
                    
                    # Create new player
                    player = self.player_service.create_player(
                        player_data['player_id'], 
                        player_data['name']
                    )
                    
                    self.bot.send_message(
                        player_data['player_id'], 
                        f"Приятной игры, {player_data['name']}! Вы зарегистрированы как новый игрок!"
                    )
                    self.bot.send_message(call.message.chat.id, f"Регистрация пользователя {player_data['name']} одобрена.")
                    
                elif action == "reject" and hasattr(self, 'pending_registration'):
                    player_data = self.pending_registration
                    self.bot.send_message(call.message.chat.id, f"Регистрация пользователя {player_data['name']} отклонена.")
                    self.bot.send_message(player_data['player_id'], "Ваша регистрация была отклонена.")
                
                # Clear pending registration
                if hasattr(self, 'pending_registration'):
                    delattr(self, 'pending_registration')
                    
            except Exception as e:
                logger.error(f"Error in registration callback: {e}")
                self.bot.answer_callback_query(call.id, "Произошла ошибка.")

        @self.bot.message_handler(commands=['leaderboard'])
        @telegram_error_handler("leaderboard_command")
        def show_leaderboard(message):
            """Show leaderboard using new player service"""
            try:
                top_players = self.player_service.get_leaderboard(limit=5)
                
                leaderboard = "🏆 Большой член, большие яйца 🏆\n\n"
                for i, player in enumerate(top_players):
                    try:
                        name = self.bot.get_chat(player.player_id).first_name
                        leaderboard += f"{i + 1}. {name}: {player.pisunchik_size} sm🌭 и {int(player.coins)} BTC💰\n"
                    except Exception as e:
                        logger.warning(f"Could not get name for player {player.player_id}: {e}")
                        leaderboard += f"{i + 1}. {player.player_name}: {player.pisunchik_size} sm🌭 и {int(player.coins)} BTC💰\n"
                
                TelegramErrorHandler.safe_reply_to(self.bot, message, leaderboard)
                
            except Exception as e:
                logger.error(f"Error in leaderboard command: {e}")
                TelegramErrorHandler.safe_reply_to(self.bot, message, "Ошибка при получении таблицы лидеров.")

    def apply_item_effects(self, player: Player, size_change: int, coins_change: int) -> tuple:
        """Apply item effects to size and coins changes"""
        try:
            # Crystal balls effect
            if player.has_item('krystalnie_ballzzz') and player.ballzzz_number is not None:
                size_change = player.ballzzz_number
                player.ballzzz_number = None
            
            # Ring effect
            if player.has_item('kolczo_na_chlen') and random.random() <= 0.2:
                coins_change *= 2
            
            # Condom protection
            if player.has_item('prezervativ') and size_change < 0:
                current_time = datetime.now(timezone.utc)
                if current_time - player.last_prezervativ >= timedelta(days=4):
                    size_change = 0
                    player.last_prezervativ = current_time
            
            # BDSM costume effect
            if player.has_item('bdsm_kostumchik') and random.random() <= 0.1:
                size_change += 5
            
            return size_change, coins_change
            
        except Exception as e:
            logger.error(f"Error applying item effects: {e}")
            return size_change, coins_change

    def ask_where_found(self, message):
        """Ask new player how they found the bot"""
        self.new_name = message.text.strip()
        self.bot.send_message(message.chat.id, "Расскажите как вы нашли этого бота?")
        self.bot.register_next_step_handler(message, self.process_approval_step)

    def process_approval_step(self, message):
        """Process new player approval"""
        try:
            how_found = message.text.strip()
            self.bot.send_message(
                message.chat.id,
                "Ваш запрос на регистрацию отправлен на рассмотрение. Пожалуйста, подождите одобрения."
            )
            
            # Send approval request to admin
            approval_markup = telebot.types.InlineKeyboardMarkup()
            approve_button = telebot.types.InlineKeyboardButton("Одобрить", callback_data="registration_approve")
            reject_button = telebot.types.InlineKeyboardButton("Отклонить", callback_data="registration_reject")
            approval_markup.row(approve_button, reject_button)
            
            admin_id = Settings.ADMIN_IDS[0]  # First admin
            self.bot.send_message(admin_id, f"Новый игрок {self.new_name}, он нашёл бота так: {how_found}")
            self.bot.send_message(admin_id, "Одобрить его регистрацию?", reply_markup=approval_markup)
            
            # Store registration data temporarily
            self.pending_registration = {
                'player_id': message.from_user.id,
                'name': self.new_name,
                'message': message
            }
            
        except Exception as e:
            logger.error(f"Error in approval process: {e}")
            self.bot.reply_to(message, "Произошла ошибка при обработке регистрации.")

    def run(self):
        """Start the bot"""
        try:
            logger.info("Setting up handlers...")
            self.setup_handlers()
            
            # Start the quiz scheduler
            logger.info("Starting quiz scheduler...")
            self.quiz_scheduler.start_scheduler()
            
            logger.info("Starting bot polling...")
            self.bot.send_message(Settings.ADMIN_IDS[0], 'Bot restarted with new architecture!')
            
            while True:
                try:
                    self.bot.polling(none_stop=True)
                except Exception as e:
                    logger.error(f"Polling error: {e}")
                    import time
                    time.sleep(15)
                    
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
        except Exception as e:
            logger.error(f"Critical error: {e}")
        finally:
            # Stop the quiz scheduler
            logger.info("Stopping quiz scheduler...")
            self.quiz_scheduler.stop_scheduler()
            
            self.db_manager.close_all_connections()
            logger.info("Database connections closed")

def main():
    """Main entry point"""
    try:
        bot = TelegramBot()
        bot.run()
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")

if __name__ == "__main__":
    main()
