from telebot import types
from config.settings import Settings
import json
from datetime import datetime, timedelta
import socket
from struct import pack
import google.generativeai as genai
import httpx
import logging

logger = logging.getLogger(__name__)

class AdminHandlers:
    def __init__(self, bot, player_service, game_service):
        self.bot = bot
        self.player_service = player_service
        self.game_service = game_service
        self.admin_actions = {}
        self.quiz_scheduler = None  # Will be set by main.py

        # Initialize Gemini for message analysis
        if Settings.GEMINI_API_KEY:
            genai.configure(api_key=Settings.GEMINI_API_KEY)
            self.gemini_model = genai.GenerativeModel('gemini-2.5-flash-lite')
        else:
            self.gemini_model = None
            logger.warning("GEMINI_API_KEY not found, sho_tam_novogo feature will be disabled")

        # Create messages table if it doesn't exist
        self._create_messages_table()
        
    def set_quiz_scheduler(self, quiz_scheduler):
        """Set the quiz scheduler instance"""
        self.quiz_scheduler = quiz_scheduler

    def _create_messages_table(self):
        """Create messages table for storing chat messages (if not exists)"""
        try:
            # Using existing table structure: id, user_id, message_text, timestamp, name
            query = """
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER,
                    message_text TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    name TEXT,
                    message_id BIGINT
                )
            """
            self.player_service.db.execute_query(query)
            # Add message_id column if it doesn't exist yet (migration for existing installs)
            self.player_service.db.execute_query("""
                ALTER TABLE messages ADD COLUMN IF NOT EXISTS message_id BIGINT
            """)
            logger.info("Messages table created/verified successfully")
        except Exception as e:
            logger.error(f"Error creating messages table: {e}")

    def _store_message(self, message):
        """Store a message in the database"""
        try:
            # Don't store bot commands or messages from bots
            if message.text and not message.text.startswith('/') and not message.from_user.is_bot:
                # Use existing table structure: id, user_id, message_text, timestamp, name
                query = """
                    INSERT INTO messages (user_id, message_text, timestamp, name, message_id)
                    VALUES (%s, %s, CURRENT_TIMESTAMP, %s, %s)
                """
                # Combine first_name and username for the name field
                name = message.from_user.first_name or message.from_user.username or 'Аноним'
                params = (
                    message.from_user.id,
                    message.text,
                    name,
                    message.message_id,
                )
                self.player_service.db.execute_query(query, params)
        except Exception as e:
            logger.error(f"Error storing message: {e}")

    def _get_recent_messages(self, hours=12, limit=100):
        """Get recent messages from the database"""
        try:
            query = """
                SELECT name, message_text, timestamp
                FROM messages
                WHERE timestamp > NOW() - INTERVAL '%s hours'
                ORDER BY timestamp DESC
                LIMIT %s
            """
            params = (hours, limit)
            results = self.player_service.db.execute_query(query, params)

            if not results:
                return []

            # Format messages for AI analysis
            messages = []
            for row in results:
                name = row[0] or 'Аноним'
                text = row[1]
                messages.append(f"{name}: {text}")

            return messages
        except Exception as e:
            logger.error(f"Error getting recent messages: {e}")
            return []

    def _analyze_messages_with_gemini(self, messages):
        """Analyze messages using Gemini AI"""
        if not self.gemini_model:
            return "❌ Gemini API не настроен. Проверьте GEMINI_API_KEY в .env файле."

        if not messages:
            return "📭 За последние 12 часов не было сообщений для анализа."

        try:
            messages_text = "\n".join(messages)
            prompt = f"""Ты бот-анализатор чата. Тебе дан список сообщений от пользователей за последние 12 часов.

Твоя задача: сделать краткую сводку того, о чём была речь в этих сообщениях.

Требования:
1. Начни сообщение с: "За последние 12 часов речь шла о том что:"
2. Раздели темы на отдельные абзацы
3. Используй эмодзи для наглядности
4. Будь кратким и информативным
5. Если были какие-то забавные моменты - упомяни их
6. Пиши на русском языке

Сообщения:
{messages_text}
"""
            response = self.gemini_model.generate_content(prompt)
            return response.text

        except Exception as e:
            logger.error(f"Error analyzing messages with Gemini: {e}")
            return f"❌ Ошибка при анализе сообщений: {str(e)}"

    def _analyze_messages_with_qwen(self, messages):
        """Analyze messages using Qwen via OpenClaw."""
        if not messages:
            return "📭 За последние 12 часов не было сообщений для анализа."

        messages_text = "\n".join(messages)
        prompt = f"""Ты бот-анализатор чата. Тебе дан список сообщений от пользователей за последние 12 часов.

Твоя задача: сделать краткую сводку того, о чём была речь в этих сообщениях.

Требования:
1. Начни сообщение с: "За последние 12 часов речь шла о том что:"
2. Раздели темы на отдельные абзацы
3. Используй эмодзи для наглядности
4. Будь кратким и информативным
5. Если были какие-то забавные моменты — упомяни их
6. Пиши на русском языке

Сообщения:
{messages_text}
"""
        try:
            with httpx.Client() as client:
                r = client.post(
                    Settings.JARVIS_URL,
                    headers={"Authorization": f"Bearer {Settings.JARVIS_TOKEN}"},
                    json={
                        "model": "ollama/qwen2.5:14b",
                        "user": "sho-tam-novogo",
                        "messages": [{"role": "user", "content": prompt}],
                    },
                    timeout=90,
                )
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"Error analyzing messages with Qwen: {e}")
            return f"❌ Ошибка при анализе сообщений: {str(e)}"
        
    def wake_on_lan(self, mac_address, broadcast_ip='255.255.255.255'):
        """Send a Wake-on-LAN packet to wake up a computer"""
        try:
            # Remove separators from MAC address
            mac_address = mac_address.replace(':', '').replace('-', '')
            
            # Create WOL packet
            magic_packet = b'\xff' * 6 + bytes.fromhex(mac_address) * 16
            
            # Send a packet
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(magic_packet, (broadcast_ip, 9))
            sock.close()
            
            return True
        except Exception as e:
            print(f"Wake-on-LAN error: {e}")
            return False
        
    def setup_handlers(self):
        """Setup all admin command handlers"""
        
        @self.bot.message_handler(commands=['admin'])
        def admin_panel(message):
            """Handle admin panel command"""
            if message.from_user.id in Settings.ADMIN_IDS:
                # Create an inline keyboard for the admin panel with categories
                markup = types.InlineKeyboardMarkup(row_width=2)
                
                # Main categories
                player_management = types.InlineKeyboardButton("👤 Управление игроками", callback_data="admin_playerManagement")
                economy = types.InlineKeyboardButton("💰 Экономика", callback_data="admin_economy")
                items = types.InlineKeyboardButton("🎁 Предметы", callback_data="admin_items")
                system = types.InlineKeyboardButton("⚙️ Система", callback_data="admin_system")
                
                markup.add(player_management, economy, items, system)
                
                self.bot.send_message(message.chat.id, "🎮 Админ-панель\nВыберите категорию:", reply_markup=markup)
            else:
                self.bot.reply_to(message, "У вас нет доступа к админ-панели.")
        
        @self.bot.callback_query_handler(func=lambda call: call.data.startswith("admin_"))
        def handle_admin_categories(call):
            """Handle admin category selection"""
            if call.from_user.id in Settings.ADMIN_IDS:
                category = call.data.split("_")[1]
                markup = types.InlineKeyboardMarkup(row_width=2)
                
                if category == "playerManagement":
                    # Player management options
                    buttons = [
                        types.InlineKeyboardButton("➕ Увеличить писюнчик", callback_data="action_increasePisunchik"),
                        types.InlineKeyboardButton("➖ Уменьшить писюнчик", callback_data="action_decreasePisunchik"),
                        types.InlineKeyboardButton("🔄 Сбросить кулдаун", callback_data="action_resetCooldown"),
                        types.InlineKeyboardButton("📊 Статистика игрока", callback_data="action_playerStats"),
                        types.InlineKeyboardButton("🧠 Изменить очки квиза", callback_data="action_quizPoints"),
                        types.InlineKeyboardButton("⬅️ Назад", callback_data="admin_back")
                    ]
                    markup.add(*buttons)
                    
                    self.bot.edit_message_text(
                        "👤 Управление игроками\nВыберите действие:",
                        call.message.chat.id, 
                        call.message.message_id, 
                        reply_markup=markup
                    )
                    
                elif category == "economy":
                    # Economy management options
                    buttons = [
                        types.InlineKeyboardButton("➕ Добавить BTC", callback_data="action_increaseBtc"),
                        types.InlineKeyboardButton("➖ Убрать BTC", callback_data="action_decreaseBtc"),
                        types.InlineKeyboardButton("💱 Управление акциями", callback_data="action_manageStocks"),
                        types.InlineKeyboardButton("⬅️ Назад", callback_data="admin_back")
                    ]
                    markup.add(*buttons)
                    self.bot.edit_message_text("💰 Управление экономикой\nВыберите действие:",
                                            call.message.chat.id, 
                                            call.message.message_id, 
                                            reply_markup=markup)
                    
                elif category == "items":
                    # Item management options
                    buttons = [
                        types.InlineKeyboardButton("➕ Добавить предмет", callback_data="action_addItem"),
                        types.InlineKeyboardButton("➖ Убрать предмет", callback_data="action_removeItem"),
                        types.InlineKeyboardButton("🏆 Добавить статуэтку", callback_data="action_addStatue"),
                        types.InlineKeyboardButton("⬅️ Назад", callback_data="admin_back")
                    ]
                    markup.add(*buttons)
                    self.bot.edit_message_text("🎁 Управление предметами\nВыберите действие:",
                                            call.message.chat.id, 
                                            call.message.message_id, 
                                            reply_markup=markup)
                    
                elif category == "system":
                    # System management options
                    buttons = [
                        types.InlineKeyboardButton("🔄 Перезапуск бота", callback_data="action_restartBot"),
                        types.InlineKeyboardButton("💾 Бэкап данных", callback_data="action_backupData"),
                        types.InlineKeyboardButton("📢 Рассылка", callback_data="action_broadcast"),
                        types.InlineKeyboardButton("💻 Включить ПК", callback_data="action_wakePc"),
                        types.InlineKeyboardButton("🧠 Управление квизами", callback_data="admin_quizManagement"),
                        types.InlineKeyboardButton("⬅️ Назад", callback_data="admin_back")
                    ]
                    markup.add(*buttons)
                    self.bot.edit_message_text("⚙️ Системные функции\nВыберите действие:",
                                            call.message.chat.id, 
                                            call.message.message_id, 
                                            reply_markup=markup)
                    
                elif category == "quizManagement":
                    # Quiz management options
                    buttons = [
                        types.InlineKeyboardButton("▶️ Запустить планировщик", callback_data="action_startQuizScheduler"),
                        types.InlineKeyboardButton("⏹️ Остановить планировщик", callback_data="action_stopQuizScheduler"),
                        types.InlineKeyboardButton("📊 Статус планировщика", callback_data="action_quizSchedulerStatus"),
                        types.InlineKeyboardButton("🎯 Отправить квиз сейчас", callback_data="action_sendQuizNow"),
                        types.InlineKeyboardButton("🔄 Пополнить пул (5 вопросов)", callback_data="action_regenQuestions"),
                        types.InlineKeyboardButton("⬅️ Назад", callback_data="admin_system")
                    ]
                    markup.add(*buttons)
                    self.bot.edit_message_text("🧠 Управление квизами\nВыберите действие:",
                                            call.message.chat.id, 
                                            call.message.message_id, 
                                            reply_markup=markup)
                    
                elif category == "back":
                    # Return to main admin panel
                    markup = types.InlineKeyboardMarkup(row_width=2)
                    player_management = types.InlineKeyboardButton("👤 Управление игроками", callback_data="admin_playerManagement")
                    economy = types.InlineKeyboardButton("💰 Экономика", callback_data="admin_economy")
                    items = types.InlineKeyboardButton("🎁 Предметы", callback_data="admin_items")
                    system = types.InlineKeyboardButton("⚙️ Система", callback_data="admin_system")
                    markup.add(player_management, economy, items, system)
                    
                    self.bot.edit_message_text("🎮 Админ-панель\nВыберите категорию:",
                                            call.message.chat.id, 
                                            call.message.message_id, 
                                            reply_markup=markup)
            else:
                self.bot.answer_callback_query(call.id, "У вас нет доступа к админ-панели.")
        
        @self.bot.callback_query_handler(func=lambda call: call.data.startswith("action_"))
        def handle_admin_actions(call):
            """Handle admin action selection"""
            if call.from_user.id in Settings.ADMIN_IDS:
                action = call.data.split("_")[1]

                if action == "wakePc":
                    try:
                        self.bot.edit_message_text(
                            "Отправляю Wake-on-LAN пакет на ваш ПК...",
                            call.message.chat.id,
                            call.message.message_id
                        )
                        result = self.wake_on_lan('D8:43:AE:BD:2B:F1')
                        if result:
                            self.bot.edit_message_text(
                                "✅ Wake-on-LAN пакет успешно отправлен! Ваш ПК должен включиться.",
                                call.message.chat.id,
                                call.message.message_id
                            )
                        else:
                            self.bot.edit_message_text(
                                "❌ Не удалось отправить Wake-on-LAN пакет. Проверьте логи для деталей.",
                                call.message.chat.id,
                                call.message.message_id
                            )
                    except Exception as e:
                        self.bot.edit_message_text(
                            f"❌ Ошибка: {str(e)}",
                            call.message.chat.id,
                            call.message.message_id
                        )

                elif action == "startQuizScheduler":
                    # Start quiz scheduler
                    if self.quiz_scheduler:
                        try:
                            self.quiz_scheduler.start_scheduler()
                            self.bot.edit_message_text(
                                "✅ Планировщик квизов запущен! Квизы будут отправляться в 12:00, 16:00 и 20:00.",
                                call.message.chat.id,
                                call.message.message_id
                            )
                        except Exception as e:
                            self.bot.edit_message_text(
                                f"❌ Ошибка при запуске планировщика: {str(e)}",
                                call.message.chat.id,
                                call.message.message_id
                            )
                    else:
                        self.bot.edit_message_text(
                            "❌ Планировщик квизов не инициализирован.",
                            call.message.chat.id,
                            call.message.message_id
                        )
                        
                elif action == "stopQuizScheduler":
                    # Stop quiz scheduler
                    if self.quiz_scheduler:
                        try:
                            self.quiz_scheduler.stop_scheduler()
                            self.bot.edit_message_text(
                                "⏹️ Планировщик квизов остановлен.",
                                call.message.chat.id,
                                call.message.message_id
                            )
                        except Exception as e:
                            self.bot.edit_message_text(
                                f"❌ Ошибка при остановке планировщика: {str(e)}",
                                call.message.chat.id,
                                call.message.message_id
                            )
                    else:
                        self.bot.edit_message_text(
                            "❌ Планировщик квизов не инициализирован.",
                            call.message.chat.id,
                            call.message.message_id
                        )
                        
                elif action == "quizSchedulerStatus":
                    # Get quiz scheduler status
                    if self.quiz_scheduler:
                        try:
                            status = self.quiz_scheduler.get_schedule_info()
                            status_text = f"📊 Статус планировщика квизов:\n\n"
                            status_text += f"🔄 Работает: {'Да' if status['is_running'] else 'Нет'}\n"
                            status_text += f"⏰ Времена квизов: {', '.join(status['quiz_times'])}\n"
                            status_text += f"📱 Целевой чат: {status['target_chat_id']}\n"
                            status_text += f"⏳ Следующий квиз: {status['next_run']}"
                            
                            self.bot.edit_message_text(
                                status_text,
                                call.message.chat.id,
                                call.message.message_id
                            )
                        except Exception as e:
                            self.bot.edit_message_text(
                                f"❌ Ошибка при получении статуса: {str(e)}",
                                call.message.chat.id,
                                call.message.message_id
                            )
                    else:
                        self.bot.edit_message_text(
                            "❌ Планировщик квизов не инициализирован.",
                            call.message.chat.id,
                            call.message.message_id
                        )
                        
                elif action == "sendQuizNow":
                    # Send quiz now
                    if self.quiz_scheduler:
                        try:
                            result = self.quiz_scheduler.manual_quiz()
                            if result['success']:
                                self.bot.edit_message_text(
                                    "✅ Квиз отправлен в целевой чат!",
                                    call.message.chat.id,
                                    call.message.message_id
                                )
                            else:
                                self.bot.edit_message_text(
                                    f"❌ Ошибка при отправке квиза: {result['message']}",
                                    call.message.chat.id,
                                    call.message.message_id
                                )
                        except Exception as e:
                            self.bot.edit_message_text(
                                f"❌ Ошибка при отправке квиза: {str(e)}",
                                call.message.chat.id,
                                call.message.message_id
                            )
                    else:
                        self.bot.edit_message_text(
                            "❌ Планировщик квизов не инициализирован.",
                            call.message.chat.id,
                            call.message.message_id
                        )
                        
                elif action == "regenQuestions":
                    # Refill question pool with 5 AI-generated questions
                    if self.quiz_scheduler:
                        try:
                            self.bot.edit_message_text(
                                "🔄 Генерирую 5 вопросов для пула, подождите...",
                                call.message.chat.id,
                                call.message.message_id
                            )
                            result = self.quiz_scheduler.refill_question_pool(5)
                            self.bot.edit_message_text(
                                f"✅ Готово!\n\n"
                                f"Добавлено в пул: {result['added']}\n"
                                f"Пропущено (дубли/ошибки): {result['skipped']}",
                                call.message.chat.id,
                                call.message.message_id
                            )
                        except Exception as e:
                            self.bot.edit_message_text(
                                f"❌ Ошибка при генерации вопросов: {str(e)}",
                                call.message.chat.id,
                                call.message.message_id
                            )
                    else:
                        self.bot.edit_message_text(
                            "❌ Планировщик квизов не инициализирован.",
                            call.message.chat.id,
                            call.message.message_id
                        )

                elif action == "backupData":
                    # Create data backup
                    try:
                        all_players = self.player_service.get_all_players()
                        backup_time = datetime.now().strftime("%Y%m%d_%H%M%S")
                        backup_filename = f"backup_{backup_time}.json"

                        # Convert player objects to dictionaries for JSON serialization
                        backup_data = {}
                        for player_id, player in all_players.items():
                            backup_data[str(player_id)] = player.to_db_dict()

                        with open(backup_filename, 'w', encoding='utf-8') as f:
                            json.dump(backup_data, f, ensure_ascii=False, indent=4, default=str)

                        self.bot.edit_message_text(
                            f"✅ Бэкап успешно создан: {backup_filename}",
                            call.message.chat.id,
                            call.message.message_id
                        )
                    except Exception as e:
                        self.bot.edit_message_text(
                            f"❌ Ошибка при создании бэкапа: {str(e)}",
                            call.message.chat.id,
                            call.message.message_id
                        )

                elif action == "broadcast":
                    self.admin_actions[call.from_user.id] = {"action": "broadcast"}
                    self.bot.edit_message_text(
                        "Введите сообщение для рассылки всем игрокам:",
                        call.message.chat.id,
                        call.message.message_id
                    )
        
        @self.bot.message_handler(func=lambda message: message.from_user.id in self.admin_actions)
        def handle_admin_text_input(message):
            """Handle text input for admin actions"""
            if message.from_user.id in Settings.ADMIN_IDS:
                user_action = self.admin_actions.get(message.from_user.id)
                
                if user_action and user_action["action"] == "broadcast":
                    # Send broadcast message to all players
                    broadcast_message = message.text
                    success_count = 0
                    fail_count = 0
                    
                    all_players = self.player_service.get_all_players()
                    
                    for player_id, player in all_players.items():
                        try:
                            if player.chat_id:
                                for chat in player.chat_id:
                                    self.bot.send_message(chat, f"📢 Объявление:\n\n{broadcast_message}")
                                    success_count += 1
                        except Exception as e:
                            fail_count += 1
                            print(f"Failed to send broadcast to {player_id}: {e}")
                    
                    self.bot.reply_to(
                        message, 
                        f"📢 Рассылка завершена\n✅ Успешно: {success_count}\n❌ Неудачно: {fail_count}"
                    )
                    
                    # Clear the admin action
                    del self.admin_actions[message.from_user.id]
        
        @self.bot.message_handler(commands=['giveChar'])
        def add_characteristic_command(message):
            """Give random characteristic to player"""
            if message.from_user.id in Settings.ADMIN_IDS:
                player_id = message.from_user.id
                player = self.player_service.get_player(player_id)

                if player:
                    # Add random characteristic logic here
                    self.bot.reply_to(message, "Характеристика добавлена!")
                else:
                    self.bot.reply_to(message, f"Игрок с ID {player_id} не найден")
            else:
                self.bot.reply_to(message, "У вас нет доступа к этой команде.")

        @self.bot.message_handler(commands=['sho_tam_novogo'])
        def analyze_recent_messages_command(message):
            """Analyze recent chat messages with Gemini AI"""
            if message.from_user.id in Settings.ADMIN_IDS:
                try:
                    # Send waiting message
                    waiting_msg = self.bot.reply_to(message, "🔍 Анализирую сообщения за последние 12 часов...")

                    # Get recent messages
                    messages = self._get_recent_messages(hours=12, limit=100)

                    # Analyze with Qwen via OpenClaw
                    analysis = self._analyze_messages_with_qwen(messages)

                    # Send analysis result
                    self.bot.edit_message_text(
                        analysis,
                        waiting_msg.chat.id,
                        waiting_msg.message_id
                    )

                except Exception as e:
                    logger.error(f"Error in sho_tam_novogo command: {e}")
                    self.bot.reply_to(message, f"❌ Ошибка: {str(e)}")
            else:
                self.bot.reply_to(message, "У вас нет доступа к этой команде.")

        @self.bot.message_handler(func=lambda m: m.text and not m.text.startswith('/'), content_types=['text'])
        def store_message_handler(message):
            """Store all NON-COMMAND text messages in the database for later analysis"""
            # Store message asynchronously (non-blocking)
            try:
                self._store_message(message)
            except Exception as e:
                logger.error(f"Error storing message in handler: {e}")
