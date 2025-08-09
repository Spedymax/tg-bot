import time
from telebot import types
from config.game_config import GameConfig
from services.stock_service import StockService

class ShopHandlers:
    def __init__(self, bot, player_service, game_service):
        self.bot = bot
        self.player_service = player_service
        self.game_service = game_service
        self.stock_service = StockService()
        self.shop_data = {}
        self.statuetki_data = {}
        self.temp_user_data = {}
        self.temp_user_sell_data = {}
        
    def load_shop_data(self, shop_data, statuetki_data):
        """Load shop and statuetki data"""
        self.shop_data = shop_data
        self.statuetki_data = statuetki_data
        
    def setup_handlers(self):
        """Setup all shop-related command handlers"""
        
        @self.bot.message_handler(commands=['shop'])
        def show_shop(message):
            """Handle /shop command with inline keyboard"""
            player_id = message.from_user.id
            player = self.player_service.get_player(player_id)
            
            if not player:
                self.bot.reply_to(message, "Вы не зарегистрированы как игрок")
                return
            
            # Create inline keyboard for shop items
            markup = types.InlineKeyboardMarkup(row_width=1)
            
            for item_name, base_price in self.shop_data['prices'].items():
                discounted_price = self.game_service.calculate_shop_discount(player, base_price)
                display_name = self.shop_data.get('names', {}).get(item_name, item_name)
                button_text = f"{display_name} - {discounted_price} BTC"
                callback_data = f"shop_buy_{item_name}"
                markup.add(types.InlineKeyboardButton(button_text, callback_data=callback_data))
            
            shop_message = f"🛍️ Добро пожаловать в магазин! 🛍️\n\n"
            shop_message += f"💰 У вас есть: {player.coins} BTC\n\n"
            shop_message += f"📦 Ваши предметы: /items\n\n"
            shop_message += f"Выберите предмет для покупки:"
            
            self.bot.send_message(message.chat.id, shop_message, reply_markup=markup)
        
        @self.bot.message_handler(commands=['items'])
        def show_items(message):
            """Handle /items command"""
            player_id = message.from_user.id
            player = self.player_service.get_player(player_id)
            
            if not player:
                self.bot.reply_to(message, "Вы не зарегистрированы как игрок")
                return
            
            if not player.items:
                self.bot.reply_to(message, "У вас нету предметов(")
                return
            
            item_descriptions = []
            for item in player.items:
                if item in self.shop_data['description']:
                    display_name = self.shop_data.get('names', {}).get(item, item)
                    item_descriptions.append(f"{display_name}: {self.shop_data['description'][item]}")
            
            if item_descriptions:
                items_text = "\n\n".join(item_descriptions)
                self.bot.reply_to(message, f"Ваши предметы:\n\n{items_text}")
            else:
                self.bot.reply_to(message, "Нету описания предметов (Странно)")
        
        @self.bot.message_handler(commands=['statuetki'])
        def show_statuetki(message):
            """Handle /statuetki command"""
            player_id = message.from_user.id
            player = self.player_service.get_player(player_id)
            
            if not player:
                self.bot.reply_to(message, "Вы не зарегистрированы как игрок")
                return
            
            if not player.statuetki:
                self.bot.reply_to(message, "У вас нету статуэток:(")
                return
            
            item_images = {
                'Pudginio': '/home/spedymax/tg-bot/assets/images/statuetki/pudginio.jpg',
                'Ryadovoi Rudgers': '/home/spedymax/tg-bot/assets/images/statuetki/ryadovoi_rudgers.jpg',
                'Polkovnik Buchantos': '/home/spedymax/tg-bot/assets/images/statuetki/polkovnik_buchantos.jpg',
                'General Chin-Choppa': '/home/spedymax/tg-bot/assets/images/statuetki/general_chin_choppa.png'
            }
            # item_images = {
            #     'Pudginio': '../assets/images/statuetki/pudginio.jpg',
            #     'Ryadovoi Rudgers': '../assets/images/statuetki/ryadovoi_rudgers.jpg',
            #     'Polkovnik Buchantos': '../assets/images/statuetki/polkovnik_buchantos.jpg',
            #     'General Chin-Choppa': '../assets/images/statuetki/general_chin_choppa.png'
            # }
            
            statuetki_descriptions = []
            for statuetka in player.statuetki:
                if statuetka in self.statuetki_data['description']:
                    description = f"{statuetka}: {self.statuetki_data['description'][statuetka]}"
                    statuetki_descriptions.append(description)
            
            if statuetki_descriptions:
                self.bot.reply_to(message, f"Ваши статуэтки:\n")
                time.sleep(1)  # Sleep for 1 second before sending images
                
                for statuetka in player.statuetki:
                    description = self.statuetki_data['description'].get(statuetka, 'No description available')
                    item_image_filename = item_images.get(statuetka, '/home/spedymax/tg-bot/assets/images/statuetki/pudginio.jpg')
                    try:
                        with open(item_image_filename, 'rb') as photo:
                            time.sleep(1)
                            self.bot.send_photo(message.chat.id, photo, caption=f"{statuetka} - {description}")
                    except FileNotFoundError:
                        self.bot.send_message(message.chat.id, f"{statuetka} - {description}")
                
                n = len(player.statuetki)
                self.bot.send_message(message.chat.id, f"Количество статуэток у вас: {n} из 4")
                
                # Check if player has all 4 statuetki for special event
                if len(player.statuetki) == 4:
                    self._handle_all_statuetki_collected(player, message)
            else:
                self.bot.reply_to(message, "Нету описания предметов (Странно)")
        
        @self.bot.message_handler(commands=['statuetki_shop'])
        def show_statuetki_shop(message):
            """Handle /statuetki_shop command with inline keyboard"""
            player_id = message.from_user.id
            player = self.player_service.get_player(player_id)
            
            if not player:
                self.bot.reply_to(message, "Вы не зарегистрированы как игрок")
                return
            
            # Create inline keyboard for statuetki
            markup = types.InlineKeyboardMarkup(row_width=1)
            
            available_items = []
            for item_name, item_price in self.statuetki_data['prices'].items():
                # Only show items player doesn't own yet
                if item_name not in player.statuetki:
                    button_text = f"{item_name} - {item_price} BTC"
                    callback_data = f"statuetki_buy_{item_name}"
                    markup.add(types.InlineKeyboardButton(button_text, callback_data=callback_data))
                    available_items.append(item_name)
            
            # If player has all statuetki, show a message
            if not available_items:
                self.bot.send_message(message.chat.id, "🎉 Поздравляем! Вы собрали все статуэтки!\n\n🏆 Используйте /statuetki чтобы активировать особое событие!")
                return
            
            shop_message = f"🏰 Магазин статуэток 🏰\n\n"
            shop_message += f"💰 У вас есть: {player.coins} BTC\n\n"
            shop_message += f"🗿 Ваши статуэтки: /statuetki ({len(player.statuetki)}/4)\n\n"
            shop_message += f"Выберите статуэтку для покупки:"
            
            self.bot.send_message(message.chat.id, shop_message, reply_markup=markup)
        
        @self.bot.message_handler(commands=['characteristics'])
        def show_characteristics(message):
            """Handle /characteristics command"""
            player_id = message.from_user.id
            player = self.player_service.get_player(player_id)
            
            if not player:
                self.bot.reply_to(message, "Вы не зарегистрированы как игрок, используйте /start")
                return
            
            if not player.characteristics:
                self.bot.reply_to(message, "Ой, у вас нету характеристик :( \nСначала купите все статуэтки используя /statuetki_shop")
                return
            
            try:
                # Load characteristics descriptions
                import json
                with open('/home/spedymax/tg-bot/assets/data/char.json', 'r', encoding='utf-8') as f:
                    char_data = json.load(f)
                
                characteristics_text = "🎯 Ваши характеристики:\n\n"
                for characteristic in player.characteristics:
                    characteristic_name, current_level = characteristic.split(":")
                    description = char_data['description'].get(characteristic_name, "Описание не найдено")
                    characteristics_text += f"⚡ **{characteristic_name}** (Уровень {current_level})\n"
                    characteristics_text += f"📝 {description}\n\n"
                
                characteristics_text += "🔧 Используйте /upgrade_char для улучшения характеристик!"
                
                self.bot.reply_to(message, characteristics_text, parse_mode='Markdown')
                
            except FileNotFoundError:
                # Fallback to basic display if file not found
                characteristics_text = "Ваши характеристики:\n"
                for characteristic in player.characteristics:
                    characteristic_name, current_level = characteristic.split(":")
                    characteristics_text += f"{characteristic_name} (Уровень {current_level})\n"
                
                self.bot.reply_to(message, characteristics_text)
            except Exception as e:
                self.bot.reply_to(message, f"Произошла ошибка при загрузке характеристик: {str(e)}")
        
        @self.bot.message_handler(commands=['upgrade_char'])
        def upgrade_characteristic(message):
            """Handle /upgrade_char command"""
            player_id = message.from_user.id
            player = self.player_service.get_player(player_id)
            
            if not player:
                self.bot.reply_to(message, "Вы не зарегистрированы как игрок, используйте /start")
                return
            
            if not player.characteristics:
                self.bot.reply_to(message, "У вас нет характеристик для улучшения.")
                return
            
            characteristic_buttons = []
            for characteristic in player.characteristics:
                characteristic_name, _ = characteristic.split(":")
                button_text = f"{characteristic_name}"
                callback_data = f"selectchar_{characteristic}"
                characteristic_buttons.append(types.InlineKeyboardButton(text=button_text, callback_data=callback_data))
            
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(*characteristic_buttons)
            
            self.bot.send_message(message.chat.id, "Выберите характеристику для улучшения:", reply_markup=keyboard)
        
        # Old handlers removed - now using inline keyboard
        
        # Shop confirmation callbacks
        @self.bot.callback_query_handler(func=lambda call: call.data.startswith("buy_confirm_"))
        def confirm_shop_purchase(call):
            """Handle shop purchase confirmation"""
            self.bot.edit_message_reply_markup(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=None
            )
            
            player_id = call.from_user.id
            player = self.player_service.get_player(player_id)
            item_name = call.data.split("_", 2)[2]
            base_price = self.shop_data['prices'].get(item_name, 0)
            
            if player and base_price > 0:
                discounted_price = self.game_service.calculate_shop_discount(player, base_price)
                
                if player.spend_coins(discounted_price):
                    player.add_item(item_name)
                    self.player_service.save_player(player)
                    display_name = self.shop_data.get('names', {}).get(item_name, item_name)
                    self.bot.send_message(call.message.chat.id, f"Вы купили {display_name} за {discounted_price} BTC.")
                else:
                    self.bot.send_message(call.message.chat.id, "Недостаточно денег((")
        
        @self.bot.callback_query_handler(func=lambda call: call.data.startswith("statuetka_confirm_"))
        def confirm_statuetka_purchase(call):
            """Handle statuetka purchase confirmation"""
            self.bot.edit_message_reply_markup(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=None
            )
            
            player_id = call.from_user.id
            player = self.player_service.get_player(player_id)
            item_name = call.data.split("_", 2)[2]
            item_price = self.statuetki_data['prices'].get(item_name, 0)
            
            if player and item_price > 0:
                if player.spend_coins(item_price):
                    player.statuetki.append(item_name)
                    self.player_service.save_player(player)
                    self.bot.send_message(call.message.chat.id, f"Вы купили {item_name} за {item_price} BTC.")
                else:
                    self.bot.send_message(call.message.chat.id, "Недостаточно денег((")
        
        @self.bot.callback_query_handler(func=lambda call: call.data.startswith("statuetki_buy_"))
        def handle_statuetki_purchase(call):
            """Handle statuetki purchase from inline keyboard"""
            player_id = call.from_user.id
            player = self.player_service.get_player(player_id)
            
            if not player:
                self.bot.answer_callback_query(call.id, "Вы не зарегистрированы как игрок")
                return
            
            item_name = call.data.split("_", 2)[2]  # Extract item name from callback data
            item_price = self.statuetki_data['prices'].get(item_name, 0)
            
            if item_price <= 0:
                self.bot.answer_callback_query(call.id, "Предмет не найден")
                return
            
            # Check if player already owns this statuetka
            if item_name in player.statuetki:
                self.bot.answer_callback_query(call.id, f"У вас уже есть эта статуэтка!")
                return
            
            if player.coins < item_price:
                self.bot.answer_callback_query(call.id, f"Недостаточно денег. Нужно {item_price} BTC")
                return
            
            # Create confirmation keyboard
            markup = types.InlineKeyboardMarkup()
            confirm_button = types.InlineKeyboardButton("✅ Купить", callback_data=f"statuetka_confirm_{item_name}")
            cancel_button = types.InlineKeyboardButton("❌ Отмена", callback_data="statuetka_cancel")
            markup.add(confirm_button, cancel_button)
            
            description = self.statuetki_data.get('description', {}).get(item_name, 'Описание не найдено')
            
            confirmation_message = f"🏰 Подтверждение покупки\n\n"
            confirmation_message += f"🗿 Статуэтка: {item_name}\n"
            confirmation_message += f"💰 Цена: {item_price} BTC\n\n"
            confirmation_message += f"📜 Описание: {description}\n\n"
            confirmation_message += f"Вы уверены, что хотите купить эту статуэтку?"
            
            self.bot.edit_message_text(
                text=confirmation_message,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=markup
            )
        
        @self.bot.callback_query_handler(func=lambda call: call.data.startswith("shop_buy_"))
        def handle_shop_purchase(call):
            """Handle shop purchase from inline keyboard"""
            player_id = call.from_user.id
            player = self.player_service.get_player(player_id)
            
            if not player:
                self.bot.answer_callback_query(call.id, "Вы не зарегистрированы как игрок")
                return
            
            item_name = call.data.split("_", 2)[2]  # Extract item name from callback data
            base_price = self.shop_data['prices'].get(item_name, 0)
            
            if base_price <= 0:
                self.bot.answer_callback_query(call.id, "Предмет не найден")
                return
            
            discounted_price = self.game_service.calculate_shop_discount(player, base_price)
            
            if player.coins < discounted_price:
                self.bot.answer_callback_query(call.id, f"Недостаточно денег. Нужно {discounted_price} BTC")
                return
            
            # Create confirmation keyboard
            markup = types.InlineKeyboardMarkup()
            confirm_button = types.InlineKeyboardButton("✅ Купить", callback_data=f"buy_confirm_{item_name}")
            cancel_button = types.InlineKeyboardButton("❌ Отмена", callback_data="buy_cancel")
            markup.add(confirm_button, cancel_button)
            
            display_name = self.shop_data.get('names', {}).get(item_name, item_name)
            description = self.shop_data.get('description', {}).get(item_name, 'Описание не найдено')
            
            confirmation_message = f"🛍️ Подтверждение покупки\n\n"
            confirmation_message += f"🏷️ Предмет: {display_name}\n"
            confirmation_message += f"💰 Цена: {discounted_price} BTC\n\n"
            confirmation_message += f"📜 Описание: {description}\n\n"
            confirmation_message += f"Вы уверены, что хотите купить этот предмет?"
            
            self.bot.edit_message_text(
                text=confirmation_message,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=markup
            )
        
        @self.bot.callback_query_handler(func=lambda call: call.data in ["buy_cancel", "statuetka_cancel"])
        def cancel_purchase(call):
            """Handle purchase cancellation"""
            self.bot.edit_message_reply_markup(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=None
            )
            self.bot.answer_callback_query(call.id, "Покупка отменена")
            self.bot.edit_message_text(
                text="❌ Покупка отменена",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id
            )
        
        # Characteristic upgrade callbacks
        @self.bot.callback_query_handler(func=lambda call: call.data.startswith("selectchar"))
        def select_characteristic_for_upgrade(call):
            """Handle characteristic selection for upgrade"""
            chat_id = call.message.chat.id
            selected_characteristic = call.data.split("_")[1]
            
            level_buttons = []
            for i in range(1, 15):
                button_text = f"Повысить на {i} уровень(ей)"
                callback_data = f"upgrade_{selected_characteristic}_{i}"
                level_buttons.append(types.InlineKeyboardButton(text=button_text, callback_data=callback_data))
            
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(*level_buttons)
            
            self.bot.send_message(chat_id, "Выберите количество уровней для улучшения:", reply_markup=keyboard)
        
        @self.bot.callback_query_handler(func=lambda call: call.data.startswith("upgrade"))
        def handle_characteristic_upgrade(call):
            """Handle characteristic upgrade"""
            chat_id = call.message.chat.id
            player_id = call.from_user.id
            player = self.player_service.get_player(player_id)
            
            if not player:
                self.bot.send_message(chat_id, "Игрок не найден")
                return
            
            call_data = call.data.split("_")
            selected_characteristic, levels_to_upgrade = call_data[1], int(call_data[2])
            
            result = self.game_service.upgrade_characteristic(player, selected_characteristic.split(":")[0], levels_to_upgrade)
            
            if result['success']:
                self.bot.send_message(chat_id, f"Вы улучшили {result['characteristic']} до уровня {result['new_level']}!")
            else:
                self.bot.send_message(chat_id, result['message'])
    
    def _handle_all_statuetki_collected(self, player, message):
        """Handle special event when player collects all statuetki"""
        import json
        import random
        import time
        
        try:
            # Load plot data for the special story
            with open('/home/spedymax/tg-bot/assets/data/plot.json', 'r', encoding='utf-8') as f:
                plot_data = json.load(f)

            # Load characteristics data
            with open('/home/spedymax/tg-bot/assets/data/char.json', 'r', encoding='utf-8') as f:
                char_data = json.load(f)

            # # Load plot data for the special story
            # with open('../assets/data/plot.json', 'r', encoding='utf-8') as f:
            #     plot_data = json.load(f)
            #
            # # Load characteristics data
            # with open('../assets/data/char.json', 'r', encoding='utf-8') as f:
            #     char_data = json.load(f)
            
            # Get the special story lines
            story_lines = plot_data.get('strochki2', [])
            
            # Send the story line by line with dramatic pauses
            for i, line in enumerate(story_lines):
                self.bot.send_message(message.chat.id, line)
                # Add dramatic pauses, longer for key moments
                if "яркая вспышка" in line.lower() or "ослепляет" in line.lower():
                    time.sleep(3)
                elif "..." in line or "...." in line:
                    time.sleep(2)
                elif i < len(story_lines) - 2:  # Don't pause after the last two messages
                    time.sleep(1.5)
            
            # Remove all statuetki after the story
            player.statuetki.clear()
            
            # Add a random characteristic
            available_characteristics = list(char_data['description'].keys())
            
            # Initialize characteristics list if it doesn't exist
            if not hasattr(player, 'characteristics') or player.characteristics is None:
                player.characteristics = []
            
            # Get characteristics player already has
            existing_characteristics = [char.split(':')[0] for char in player.characteristics]
            
            # Filter out already owned characteristics
            available_characteristics = [char for char in available_characteristics if char not in existing_characteristics]
            
            # If player has all characteristics, give them a random one anyway but level it up
            if not available_characteristics:
                selected_characteristic = random.choice(list(char_data['description'].keys()))
                # Find existing characteristic and level it up
                for i, char in enumerate(player.characteristics):
                    char_name, level = char.split(':')
                    if char_name == selected_characteristic:
                        player.characteristics[i] = f"{char_name}:{int(level) + 1}"
                        break
            else:
                # Add new characteristic with level 1
                selected_characteristic = random.choice(available_characteristics)
                new_characteristic = f"{selected_characteristic}:1"
                player.characteristics.append(new_characteristic)
            
            # Save the player
            self.player_service.save_player(player)
            
            # Send final message about the new characteristic
            characteristic_description = char_data['description'][selected_characteristic]
            final_message = f"🎉 Поздравляем! Вы получили новую характеристику: **{selected_characteristic}**\n\n"
            final_message += f"📝 Описание: {characteristic_description}\n\n"
            final_message += "✨ Используйте /characteristics чтобы посмотреть все ваши характеристики!"
            
            self.bot.send_message(message.chat.id, final_message, parse_mode='Markdown')
            
        except FileNotFoundError as e:
            self.bot.send_message(message.chat.id, f"Ошибка: не удалось найти файл данных - {str(e)}")
        except Exception as e:
            self.bot.send_message(message.chat.id, f"Произошла ошибка во время особого события: {str(e)}")
            # Still clear statuetki and save player even if story fails
            player.statuetki.clear()
            self.player_service.save_player(player)
        
        # Stock-related handlers
        @self.bot.message_handler(commands=['stocks_update'])
        def stocks_update(message):
            """Handle /stocks_update command (admin only)"""
            from config.settings import ADMIN_IDS
            if message.from_user.id in ADMIN_IDS:
                try:
                    conn = self.player_service.get_connection()
                    cursor = conn.cursor()
                    
                    # Get old prices for comparison
                    old_stock_data = self.stock_service.get_stock_data(cursor)
                    
                    # Update stock prices
                    self.stock_service.update_stock_prices(cursor)
                    conn.commit()
                    
                    # Get new prices for comparison
                    new_stock_data = self.stock_service.get_stock_data(cursor)
                    
                    # Format the message
                    stock_message = "Акции компаний на данный момент:\n\n"
                    for company, new_price in new_stock_data.items():
                        old_price = old_stock_data.get(company, new_price)
                        change, arrow = self.stock_service.calculate_price_change(old_price, new_price)
                        stock_message += f"{company}: {new_price} BTC ({abs(change):.2f}% {arrow})\n"
                    
                    cursor.close()
                    conn.close()
                    
                    # Send the message
                    self.bot.send_message(message.chat.id, stock_message)
                    self.bot.send_message(message.chat.id,
                                         "Чтобы купить акции используйте /buy_stocks \nЧтобы посмотреть свои акции используйте /my_stocks. \nЧтобы посмотреть стоимость акций на данный момент используйте /current_stocks")
                except Exception as e:
                    self.bot.send_message(message.chat.id, f"Ошибка обновления акций: {str(e)}")
            else:
                self.bot.send_message(message.chat.id, "Вы не админ((((((((((((")
        
        @self.bot.message_handler(commands=['current_stocks'])
        def current_stocks(message):
            """Handle /current_stocks command"""
            try:
                conn = self.player_service.get_connection()
                cursor = conn.cursor()
                
                stock_data = self.stock_service.get_stock_data(cursor)
                stock_message = "Акции компаний на данный момент:\n\n"
                for company, price in stock_data.items():
                    stock_message += f"{company}: {price} BTC\n"
                
                cursor.close()
                conn.close()
                
                self.bot.reply_to(message, stock_message)
            except Exception as e:
                self.bot.reply_to(message, f"Ошибка получения данных об акциях: {str(e)}")
        
        @self.bot.message_handler(commands=['my_stocks'])
        def my_stocks(message):
            """Handle /my_stocks command"""
            player_id = message.from_user.id
            player = self.player_service.get_player(player_id)
            
            if not player:
                self.bot.reply_to(message, "Вы не зарегистрированы как игрок, используйте /start")
                return
            
            if not hasattr(player, 'player_stocks') or not player.player_stocks:
                self.bot.reply_to(message, "У вас нет акций")
                return
            
            try:
                conn = self.player_service.get_connection()
                cursor = conn.cursor()
                
                stocks_text = "Ваши акции:\n"
                for stock in player.player_stocks:
                    company_name, quantity = stock.split(":")
                    cursor.execute("SELECT price FROM stocks WHERE company_name = %s", (company_name,))
                    result = cursor.fetchone()
                    
                    if result:
                        quantity = int(quantity)
                        stock_price = result[0]
                        total_cost = stock_price * quantity
                        stocks_text += f"Компания {company_name}, кол-во акций: {quantity}\nЦена ваших активов компании {company_name}: {total_cost}\n\n"
                    else:
                        stocks_text += f"Компания {company_name} не найдена\n"
                
                cursor.close()
                conn.close()
                
                self.bot.reply_to(message, stocks_text)
            except Exception as e:
                self.bot.reply_to(message, f"Ошибка получения ваших акций: {str(e)}")
        
        @self.bot.message_handler(commands=['buy_stocks'])
        def buy_stocks(message):
            """Handle /buy_stocks command"""
            markup = types.InlineKeyboardMarkup()
            companies = ['ATB', 'Rockstar', 'Google', 'Apple', 'Valve', 'Obuhov toilet paper']
            for company in companies:
                markup.add(types.InlineKeyboardButton(company, callback_data=f"buy_stocks_{company}"))
            self.bot.send_message(message.chat.id, "Выберите компанию акции которой хотите купить:", reply_markup=markup)
        
        @self.bot.message_handler(commands=['sell_stocks'])
        def sell_stocks(message):
            """Handle /sell_stocks command"""
            player_id = message.from_user.id
            player = self.player_service.get_player(player_id)
            
            if not player or not hasattr(player, 'player_stocks') or not player.player_stocks:
                self.bot.send_message(message.chat.id, "Ты бомж, у тебя вообще нету акций.")
                return
            
            markup = types.InlineKeyboardMarkup()
            owned_stocks = set(stock.split(':')[0] for stock in player.player_stocks)
            for company in owned_stocks:
                markup.add(types.InlineKeyboardButton(company, callback_data=f"sell_stocks_{company}"))
            self.bot.send_message(message.chat.id, "Выберите свою компанию:", reply_markup=markup)
        
        # Stock purchase callbacks
        @self.bot.callback_query_handler(func=lambda call: call.data.startswith("buy_stocks_"))
        def handle_company_selection(call):
            """Handle company selection for stock purchase"""
            company = call.data.split('_')[2]
            self.temp_user_data[call.from_user.id] = {'company': company}
            msg = f"Сколько акций компании {company} вы хотите купить?"
            self.bot.send_message(call.message.chat.id, msg)
        
        @self.bot.callback_query_handler(func=lambda call: call.data.startswith("sell_stocks_"))
        def handle_sell_company_selection(call):
            """Handle company selection for stock sale"""
            company = call.data.split('_')[2]
            self.temp_user_sell_data[call.from_user.id] = {'company_to_sell': company}
            msg = f"Сколько акций компании {company} вы хотите продать?"
            self.bot.send_message(call.message.chat.id, msg)
        
        # Stock quantity input handlers
        @self.bot.message_handler(func=lambda message: message.from_user.id in self.temp_user_data and message.text.isdigit())
        def handle_quantity_selection(message):
            """Handle stock purchase quantity input"""
            try:
                quantity = int(message.text)
                user_id = message.from_user.id
                company = self.temp_user_data[user_id]['company']
                
                player = self.player_service.get_player(user_id)
                if not player:
                    self.bot.reply_to(message, "Игрок не найден")
                    return
                
                conn = self.player_service.get_connection()
                cursor = conn.cursor()
                
                # Get stock price
                cursor.execute("SELECT price FROM stocks WHERE company_name = %s", (company,))
                result = cursor.fetchone()
                if not result:
                    self.bot.reply_to(message, f"Company {company} not found.")
                    return
                
                stock_price = result[0]
                total_cost = stock_price * quantity
                
                # Check if user has enough coins
                if player.coins < total_cost:
                    self.bot.reply_to(message, f"Недостаточно BTC для покупки. Надо {total_cost} BTC")
                    return
                
                # Process transaction
                if not hasattr(player, 'player_stocks'):
                    player.player_stocks = []
                
                player_stocks_set = set(player.player_stocks)
                updated_stocks, cost = self.stock_service.process_stock_transaction(
                    player_stocks_set, company, quantity, stock_price, True
                )
                
                # Update player data
                player.spend_coins(int(cost))
                player.player_stocks = list(updated_stocks)
                self.player_service.save_player(player)
                
                cursor.close()
                conn.close()
                
                self.bot.reply_to(message, f"Мои поздравления! Вы купили {quantity} акций компании {company}.")
                
            except Exception as e:
                self.bot.reply_to(message, f"An error occurred: {str(e)}")
            finally:
                if message.from_user.id in self.temp_user_data:
                    del self.temp_user_data[message.from_user.id]
        
        @self.bot.message_handler(func=lambda message: message.from_user.id in self.temp_user_sell_data and message.text.isdigit())
        def handle_sell_quantity_selection(message):
            """Handle stock sale quantity input"""
            try:
                quantity = int(message.text)
                user_id = message.from_user.id
                company = self.temp_user_sell_data[user_id]['company_to_sell']
                
                player = self.player_service.get_player(user_id)
                if not player:
                    self.bot.reply_to(message, "Игрок не найден")
                    return
                
                # Check if user has enough stocks
                user_stock = next((stock for stock in player.player_stocks if stock.startswith(company)), None)
                if not user_stock:
                    self.bot.reply_to(message, f"У вас нет акций компании {company}")
                    return
                
                current_quantity = int(user_stock.split(':')[1])
                if quantity > current_quantity:
                    self.bot.reply_to(message, f"У вас нет столько акций. У вас {current_quantity} акций.")
                    return
                
                conn = self.player_service.get_connection()
                cursor = conn.cursor()
                
                # Get current stock price
                cursor.execute("SELECT price FROM stocks WHERE company_name = %s", (company,))
                result = cursor.fetchone()
                if not result:
                    self.bot.reply_to(message, f"Company {company} not found.")
                    return
                
                current_price = result[0]
                
                # Process transaction
                player_stocks_set = set(player.player_stocks)
                updated_stocks, earnings = self.stock_service.process_stock_transaction(
                    player_stocks_set, company, quantity, current_price, False
                )
                
                # Update player data
                player.add_coins(int(abs(earnings)))
                player.player_stocks = list(updated_stocks)
                self.player_service.save_player(player)
                
                cursor.close()
                conn.close()
                
                self.bot.reply_to(message, f"Вы успешно продали {quantity} акций компании {company}.\nИ вы заработали: {abs(earnings)}")
                
            except Exception as e:
                self.bot.reply_to(message, f"An error occurred: {str(e)}")
            finally:
                if message.from_user.id in self.temp_user_sell_data:
                    del self.temp_user_sell_data[message.from_user.id]
