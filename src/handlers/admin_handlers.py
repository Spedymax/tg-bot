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
                        "model": "ollama/qwen3.5:9b",
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
        
    def setup_priority_handlers(self):
        """Register high-priority handlers that must fire before moltbot text handlers."""

        @self.bot.message_handler(commands=['cancel'])
        def cancel_admin_action(message):
            """Cancel current pending admin action"""
            if message.from_user.id in self.admin_actions:
                del self.admin_actions[message.from_user.id]
                self.bot.reply_to(message, "❌ Действие отменено.")

        @self.bot.message_handler(func=lambda message: message.from_user.id in self.admin_actions)
        def handle_admin_text_input(message):
            """Handle text input for admin actions"""
            if message.from_user.id not in Settings.ADMIN_IDS:
                return

            user_action = self.admin_actions.get(message.from_user.id)
            if not user_action:
                return

            text = message.text.strip()
            action = user_action["action"]
            step = user_action.get("step", "")

            # --- Broadcast (single-step) ---
            if action == "broadcast":
                success_count = 0
                fail_count = 0
                all_players = self.player_service.get_all_players()
                for player_id, player in all_players.items():
                    try:
                        if player.chat_id:
                            for chat in player.chat_id:
                                self.bot.send_message(chat, f"📢 Объявление:\n\n{text}")
                                success_count += 1
                    except Exception as e:
                        fail_count += 1
                        logger.error(f"Failed to send broadcast to {player_id}: {e}")
                self.bot.reply_to(
                    message,
                    f"📢 Рассылка завершена\n✅ Успешно: {success_count}\n❌ Неудачно: {fail_count}"
                )
                del self.admin_actions[message.from_user.id]
                return

            # --- Step 1: get numeric amount ---
            if step == "waiting_amount":
                try:
                    amount = float(text.lstrip("+"))
                except ValueError:
                    self.bot.reply_to(message, "❌ Введите число.\n\n/cancel — отмена")
                    return

                player = self.player_service.get_player(user_action["player_id"])
                if not player:
                    self.bot.reply_to(message, "❌ Игрок не найден.")
                    del self.admin_actions[message.from_user.id]
                    return

                if action == "increasePisunchik":
                    player.pisunchik_size += int(amount)
                    ok = self.player_service.save_player(player)
                    self.bot.reply_to(message, f"✅ Писюнчик {player.player_name}: +{int(amount)} см → {player.pisunchik_size} см" if ok else "❌ Ошибка при сохранении.")

                elif action == "decreasePisunchik":
                    player.pisunchik_size -= int(amount)
                    ok = self.player_service.save_player(player)
                    self.bot.reply_to(message, f"✅ Писюнчик {player.player_name}: -{int(amount)} см → {player.pisunchik_size} см" if ok else "❌ Ошибка при сохранении.")

                elif action == "increaseBtc":
                    player.add_coins(amount)
                    ok = self.player_service.save_player(player)
                    self.bot.reply_to(message, f"✅ +{amount:.4f} BTC → {player.player_name} имеет {player.coins:.4f} BTC" if ok else "❌ Ошибка при сохранении.")

                elif action == "decreaseBtc":
                    player.coins = max(0.0, player.coins - amount)
                    ok = self.player_service.save_player(player)
                    self.bot.reply_to(message, f"✅ -{amount:.4f} BTC → {player.player_name} имеет {player.coins:.4f} BTC" if ok else "❌ Ошибка при сохранении.")

                elif action == "quizPoints":
                    delta = int(amount)
                    quiz_chat = user_action.get("quiz_chat_id", message.chat.id)
                    current = player.get_quiz_score(quiz_chat)
                    new_score = max(0, current + delta)
                    player.update_quiz_score(quiz_chat, new_score)
                    ok = self.player_service.save_player(player)
                    sign = "+" if delta >= 0 else ""
                    self.bot.reply_to(message, f"✅ Квиз {player.player_name}: {current} → {new_score} ({sign}{delta})" if ok else "❌ Ошибка при сохранении.")

                del self.admin_actions[message.from_user.id]

            # --- Step 2: get quantity for item actions ---
            elif step == "waiting_quantity":
                try:
                    quantity = int(text)
                    if quantity < 1:
                        raise ValueError
                except ValueError:
                    self.bot.reply_to(message, "❌ Введите целое число больше 0.\n\n/cancel — отмена")
                    return

                item_name = user_action.get("item_name", "")
                player = self.player_service.get_player(user_action["player_id"])
                if not player:
                    self.bot.reply_to(message, "❌ Игрок не найден.")
                    del self.admin_actions[message.from_user.id]
                    return

                if action == "addItem":
                    for _ in range(quantity):
                        player.add_item(item_name)
                    ok = self.player_service.save_player(player)
                    self.bot.reply_to(message, f"✅ Добавлено {quantity}x {item_name} игроку {player.player_name}" if ok else "❌ Ошибка при сохранении.")

                elif action == "removeItem":
                    removed = sum(1 for _ in range(quantity) if player.remove_item(item_name))
                    if removed == 0:
                        self.bot.reply_to(message, f"❌ Предмет '{item_name}' не найден у {player.player_name}")
                    else:
                        ok = self.player_service.save_player(player)
                        self.bot.reply_to(message, f"✅ Удалено {removed}x {item_name} у {player.player_name}" if ok else "❌ Ошибка при сохранении.")

                elif action == "addStatue":
                    for _ in range(quantity):
                        player.statuetki.append(item_name)
                    ok = self.player_service.save_player(player)
                    self.bot.reply_to(message, f"✅ Добавлено {quantity}x '{item_name}' игроку {player.player_name}" if ok else "❌ Ошибка при сохранении.")

                del self.admin_actions[message.from_user.id]

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
        
        @self.bot.callback_query_handler(func=lambda call: (
            call.data.startswith("admin_")
            and not call.data.startswith("admin_selectPlayer_")
            and not call.data.startswith("admin_item::")
        ))
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
                        types.InlineKeyboardButton("😴 Выключить ПК", callback_data="action_sleepPc"),
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
                        from src.services.ollama_wake_manager import OllamaWakeManager
                        wake_manager = OllamaWakeManager()
                        wake_manager.trigger_wake()
                        self.bot.edit_message_text(
                            "✅ WoL пакет отправлен, ПК просыпается (~1–3 мин).",
                            call.message.chat.id,
                            call.message.message_id
                        )
                    except Exception as e:
                        self.bot.edit_message_text(
                            f"❌ Ошибка: {str(e)}",
                            call.message.chat.id,
                            call.message.message_id
                        )

                elif action == "sleepPc":
                    try:
                        from src.services.ollama_wake_manager import OllamaWakeManager
                        wake_manager = OllamaWakeManager()
                        self.bot.edit_message_text(
                            "😴 Отправляю команду сна...",
                            call.message.chat.id,
                            call.message.message_id
                        )
                        wake_manager.sleep_pc()
                        self.bot.edit_message_text(
                            "😴 Команда отправлена, ПК засыпает.",
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

                elif action == "restartBot":
                    import os, sys
                    self.bot.edit_message_text(
                        "🔄 Перезапускаю бота...",
                        call.message.chat.id,
                        call.message.message_id
                    )
                    os.execv(sys.executable, [sys.executable] + sys.argv)

                elif action in ("increasePisunchik", "decreasePisunchik", "resetCooldown",
                                "playerStats", "quizPoints", "increaseBtc", "decreaseBtc",
                                "addItem", "removeItem", "addStatue"):
                    action_labels = {
                        "increasePisunchik": "Увеличить писюнчик",
                        "decreasePisunchik": "Уменьшить писюнчик",
                        "resetCooldown": "Сбросить кулдаун",
                        "playerStats": "Статистика игрока",
                        "quizPoints": "Изменить очки квиза",
                        "increaseBtc": "Добавить BTC",
                        "decreaseBtc": "Убрать BTC",
                        "addItem": "Добавить предмет",
                        "removeItem": "Убрать предмет",
                        "addStatue": "Добавить статуэтку",
                    }
                    all_players = self.player_service.get_all_players()
                    markup = types.InlineKeyboardMarkup()
                    for pid, p in all_players.items():
                        markup.add(types.InlineKeyboardButton(
                            p.player_name,
                            callback_data=f"admin_selectPlayer_{action}_{pid}"
                        ))
                    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data="admin_back"))
                    self.bot.edit_message_text(
                        f"🎯 {action_labels.get(action, action)}\n\nВыберите игрока:",
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup
                    )

        @self.bot.callback_query_handler(func=lambda call: call.data.startswith("admin_selectPlayer_"))
        def handle_player_selection(call):
            """Handle player selection from inline keyboard for admin actions"""
            if call.from_user.id not in Settings.ADMIN_IDS:
                self.bot.answer_callback_query(call.id, "Нет доступа.")
                return
            # Format: admin_selectPlayer_{action}_{player_id}
            remainder = call.data[len("admin_selectPlayer_"):]
            action, player_id_str = remainder.rsplit("_", 1)
            player_id = int(player_id_str)
            player = self.player_service.get_player(player_id)
            if not player:
                self.bot.answer_callback_query(call.id, "Игрок не найден.")
                return

            if action == "playerStats":
                items_str = ", ".join(player.items) if player.items else "нет"
                stats = (
                    f"📊 Статистика: {player.player_name}\n"
                    f"🆔 ID: {player.player_id}\n"
                    f"📏 Писюнчик: {player.pisunchik_size} см\n"
                    f"💰 BTC: {player.coins:.4f}\n"
                    f"🎁 Предметы: {items_str}\n"
                    f"🏆 Статуэтки: {len(player.statuetki)}\n"
                    f"🎰 Казино: {player.casino_usage_count} раз"
                )
                self.bot.edit_message_text(stats, call.message.chat.id, call.message.message_id)

            elif action == "resetCooldown":
                from datetime import datetime, timezone
                player.last_used = datetime.min.replace(tzinfo=timezone.utc)
                ok = self.player_service.save_player(player)
                self.bot.edit_message_text(
                    f"✅ Кулдаун {player.player_name} сброшен." if ok else "❌ Ошибка при сохранении.",
                    call.message.chat.id, call.message.message_id
                )

            elif action in ("increasePisunchik", "decreasePisunchik"):
                self.admin_actions[call.from_user.id] = {
                    "action": action, "player_id": player_id, "step": "waiting_amount"
                }
                self.bot.edit_message_text(
                    f"✅ {player.player_name} (сейчас {player.pisunchik_size} см)\n\nВведите количество см:\n\n/cancel — отмена",
                    call.message.chat.id, call.message.message_id
                )

            elif action in ("increaseBtc", "decreaseBtc"):
                self.admin_actions[call.from_user.id] = {
                    "action": action, "player_id": player_id, "step": "waiting_amount"
                }
                self.bot.edit_message_text(
                    f"✅ {player.player_name} (сейчас {player.coins:.4f} BTC)\n\nВведите количество BTC:\n\n/cancel — отмена",
                    call.message.chat.id, call.message.message_id
                )

            elif action == "quizPoints":
                current_score = player.get_quiz_score(call.message.chat.id)
                self.admin_actions[call.from_user.id] = {
                    "action": action, "player_id": player_id, "step": "waiting_amount",
                    "quiz_chat_id": call.message.chat.id
                }
                self.bot.edit_message_text(
                    f"✅ {player.player_name} (сейчас {current_score} очков)\n\nВведите изменение (например: 5 или -3):\n\n/cancel — отмена",
                    call.message.chat.id, call.message.message_id
                )

            elif action == "addItem":
                try:
                    with open('/home/spedymax/tg-bot/assets/data/shop.json', 'r', encoding='utf-8') as f:
                        shop_data = json.load(f)
                    item_names = shop_data.get("names", {})
                except Exception:
                    item_names = {}
                markup = types.InlineKeyboardMarkup()
                for item_key, item_label in item_names.items():
                    markup.add(types.InlineKeyboardButton(item_label, callback_data=f"admin_item::{item_key}"))
                markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data="admin_back"))
                self.admin_actions[call.from_user.id] = {
                    "action": action, "player_id": player_id, "step": "waiting_item_selection"
                }
                self.bot.edit_message_text(
                    f"✅ {player.player_name}\n\nВыберите предмет:",
                    call.message.chat.id, call.message.message_id, reply_markup=markup
                )

            elif action == "removeItem":
                unique_items = list(dict.fromkeys(player.items))
                if not unique_items:
                    self.bot.answer_callback_query(call.id, "У игрока нет предметов.")
                    return
                try:
                    with open('/home/spedymax/tg-bot/assets/data/shop.json', 'r', encoding='utf-8') as f:
                        shop_data = json.load(f)
                    item_names = shop_data.get("names", {})
                except Exception:
                    item_names = {}
                markup = types.InlineKeyboardMarkup()
                for item_key in unique_items:
                    label = item_names.get(item_key, item_key)
                    markup.add(types.InlineKeyboardButton(label, callback_data=f"admin_item::{item_key}"))
                markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data="admin_back"))
                self.admin_actions[call.from_user.id] = {
                    "action": action, "player_id": player_id, "step": "waiting_item_selection"
                }
                self.bot.edit_message_text(
                    f"✅ {player.player_name}\n\nВыберите предмет для удаления:",
                    call.message.chat.id, call.message.message_id, reply_markup=markup
                )

            elif action == "addStatue":
                try:
                    with open('/home/spedymax/tg-bot/assets/data/statuetki.json', 'r', encoding='utf-8') as f:
                        stat_data = json.load(f)
                    statue_names = list(stat_data.get("prices", {}).keys())
                except Exception:
                    statue_names = []
                markup = types.InlineKeyboardMarkup()
                for name in statue_names:
                    markup.add(types.InlineKeyboardButton(name, callback_data=f"admin_item::{name}"))
                markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data="admin_back"))
                self.admin_actions[call.from_user.id] = {
                    "action": action, "player_id": player_id, "step": "waiting_item_selection"
                }
                self.bot.edit_message_text(
                    f"✅ {player.player_name}\n\nВыберите статуэтку:",
                    call.message.chat.id, call.message.message_id, reply_markup=markup
                )

        @self.bot.callback_query_handler(func=lambda call: call.data.startswith("admin_item::"))
        def handle_item_selection(call):
            """Handle item selection from inline keyboard"""
            if call.from_user.id not in Settings.ADMIN_IDS:
                self.bot.answer_callback_query(call.id, "Нет доступа.")
                return
            user_action = self.admin_actions.get(call.from_user.id)
            if not user_action or user_action.get("step") != "waiting_item_selection":
                self.bot.answer_callback_query(call.id, "Нет активного действия.")
                return
            item_name = call.data[len("admin_item::"):]
            user_action["item_name"] = item_name
            user_action["step"] = "waiting_quantity"
            self.bot.edit_message_text(
                f"✅ Выбрано: {item_name}\n\nВведите количество (число):\n\n/cancel — отмена",
                call.message.chat.id, call.message.message_id
            )

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
