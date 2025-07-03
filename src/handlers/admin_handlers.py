from telebot import types
from config.settings import Settings
import json
from datetime import datetime
import socket
from struct import pack

class AdminHandlers:
    def __init__(self, bot, player_service, game_service):
        self.bot = bot
        self.player_service = player_service
        self.game_service = game_service
        self.admin_actions = {}
        
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
                        types.InlineKeyboardButton("⬅️ Назад", callback_data="admin_back")
                    ]
                    markup.add(*buttons)
                    self.bot.edit_message_text("⚙️ Системные функции\nВыберите действие:",
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

                if action == "backupData":
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
