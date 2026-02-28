import random
import time
from telebot import types
from config.game_config import GameConfig
from config.settings import Settings
from utils.helpers import safe_split_callback, safe_int, escape_html, safe_username

class GameHandlers:
    def __init__(self, bot, player_service, game_service):
        self.bot = bot
        self.player_service = player_service
        self.game_service = game_service
        
    def setup_handlers(self):
        """Setup all game-related command handlers"""
        
        @self.bot.message_handler(commands=['pisunchik'])
        def pisunchik_command(message):
            """Handle /pisunchik command"""
            player_id = message.from_user.id
            player = self.player_service.get_player(player_id)
            
            if not player:
                self.bot.reply_to(message, "Вы не зарегистрированы как игрок, используйте /start")
                return
            
            result = self.game_service.execute_pisunchik_command(player)

            if not result['success']:
                self.bot.reply_to(message, result['message'])
                return

            # Reload player since execute_pisunchik_command saves internally
            player = self.player_service.get_player(player_id)

            # Pet activity tracking + food drop
            import random as _rand
            from datetime import datetime, timezone
            from services.pet_service import PetService as _PetSvc
            _pet_svc = _PetSvc()
            _pet_svc.record_game_activity(player, 'pisunchik', datetime.now(timezone.utc))
            if player.pet and player.pet.get('is_alive') and _rand.random() < 0.20:
                player.add_item('pet_food_basic')
            self.player_service.save_player(player)

            pet_badge = _pet_svc.get_pet_badge(player)

            reply_message = (
                f"Ваш писюнчик{pet_badge}: {result['new_size']} см\n"
                f"Изменения: {result['size_change']} см\n"
                f"Также вы получили: {result['coins_change']} BTC"
            )
            
            for effect in result['effects']:
                reply_message += f"\n{effect}"
            
            self.bot.reply_to(message, reply_message)
        
        @self.bot.message_handler(commands=['kazik'])
        def casino_command(message):
            """Handle /kazik command"""
            player_id = message.from_user.id
            player = self.player_service.get_player(player_id)
            
            if not player:
                self.bot.reply_to(message, "Вы не зарегистрированы как игрок")
                return
            
            result = self.game_service.execute_casino_command(player)
            
            if not result['success']:
                self.bot.reply_to(message, result['message'])
                return
            
            if result.get('send_dice'):
                # Send 6 casino dice one by one
                dice_results = []
                total_wins = 0
                
                for i in range(6):
                    dice_msg = self.bot.send_dice(message.chat.id, emoji='🎰')
                    dice_value = dice_msg.dice.value
                    dice_results.append(dice_value)

                    # Check if this dice is a winning value
                    if dice_value in GameConfig.CASINO_JACKPOT_VALUES:
                        total_wins += 1
                        player.add_coins(GameConfig.CASINO_JACKPOT_REWARD)
                        time.sleep(GameConfig.CASINO_JACKPOT_DELAY)
                        self.bot.send_message(message.chat.id, f"🎰 ДЖЕКПОТ ЕБАТЬ! Вы получаете {GameConfig.CASINO_JACKPOT_REWARD} BTC!")

                    if i < 5:  # Don't sleep after the last dice
                        time.sleep(GameConfig.CASINO_DICE_DELAY)
                
                # Save player with updated coins
                import random as _rand
                from datetime import datetime, timezone
                from services.pet_service import PetService as _PetSvc
                _pet_svc = _PetSvc()
                _pet_svc.record_game_activity(player, 'casino', datetime.now(timezone.utc))
                if total_wins > 0 and player.pet and player.pet.get('is_alive') and _rand.random() < 0.15:
                    player.add_item('pet_food_basic')

                self.player_service.save_player(player)
                self.bot.send_message(message.chat.id, f"🎉 Всего выигрышей: {total_wins}! Общий выигрыш: {total_wins * GameConfig.CASINO_JACKPOT_REWARD} BTC!")

        
        @self.bot.message_handler(commands=['roll'])
        def roll_command(message):
            """Handle /roll command with inline keyboard"""
            keyboard = self.create_roll_keyboard()
            self.bot.send_message(message.chat.id, "Выберите, сколько раз вы хотите бросить кубик:", reply_markup=keyboard)
        
        @self.bot.callback_query_handler(func=lambda call: call.data.startswith('roll_'))
        def handle_roll_callback(call):
            """Handle roll option selection"""
            parts = safe_split_callback(call.data, "_", 2)
            if not parts:
                self.bot.send_message(call.message.chat.id, "Неверный формат данных")
                return

            rolls = safe_int(parts[1], 0)
            if rolls <= 0:
                self.bot.send_message(call.message.chat.id, "Неверное количество бросков")
                return

            player_id = call.from_user.id
            player = self.player_service.get_player(player_id)

            if not player:
                self.bot.send_message(call.message.chat.id, "Вы не зарегистрированы как игрок")
                return
            
            result = self.game_service.execute_roll_command(player, rolls)
            
            if not result['success']:
                self.bot.send_message(call.message.chat.id, result['message'])
                return
            
            self.bot.send_message(call.message.chat.id, f"Всего потрачено: {result['cost']} BTC")
            self.bot.send_message(call.message.chat.id, f"Результаты бросков: {' '.join(map(str, result['results']))}")
            self.bot.send_message(call.message.chat.id, f"Ваш писюнчик: {result['new_size']} см")
            
            if result['jackpots'] > 0:
                for i in range(result['jackpots']):
                    time.sleep(GameConfig.ROLL_JACKPOT_DELAY)
                    if i >= 1:
                        self.bot.send_message(call.message.chat.id, "ЧТО? ЕЩЕ ОДИН?")
                        time.sleep(GameConfig.ROLL_JACKPOT_DELAY)
                    self.bot.send_message(call.message.chat.id, "🆘🤑БОГ ТЫ МОЙ! ТЫ ВЫИГРАЛ ДЖЕКПОТ! 400 BTC ТЕБЕ НА СЧЕТ!🤑🆘")
        
        @self.bot.message_handler(commands=['vor'])
        def theft_command(message):
            """Handle /vor command"""
            player_id = message.from_user.id
            player = self.player_service.get_player(player_id)
            
            if not player:
                self.bot.reply_to(message, "Вы не зарегистрированы как игрок")
                return
            
            can_steal, error_message = self.game_service.can_steal(player)
            if not can_steal:
                self.bot.reply_to(message, error_message)
                return
            
            # Create theft target selection based on player ID
            markup = types.InlineKeyboardMarkup()

            # Use Settings.PLAYER_IDS for target selection
            player_ids = Settings.PLAYER_IDS
            if player_id == player_ids['YURA']:
                markup.add(types.InlineKeyboardButton("Макс", callback_data="vor_max"))
                markup.add(types.InlineKeyboardButton("Богдан", callback_data="vor_bogdan"))
            elif player_id == player_ids['MAX']:
                markup.add(types.InlineKeyboardButton("Юра", callback_data="vor_yura"))
                markup.add(types.InlineKeyboardButton("Богдан", callback_data="vor_bogdan"))
            elif player_id == player_ids['BODYA']:
                markup.add(types.InlineKeyboardButton("Макс", callback_data="vor_max"))
                markup.add(types.InlineKeyboardButton("Юра", callback_data="vor_yura"))
            
            # Escape username to prevent XSS
            username = safe_username(message.from_user.username, player_id)
            self.bot.send_message(
                message.chat.id,
                f"<a href='tg://user?id={player_id}'>@{username}</a>, у кого крадём член?",
                reply_markup=markup,
                parse_mode='html'
            )

        @self.bot.callback_query_handler(func=lambda call: call.data.startswith("vor_"))
        def handle_theft_callback(call):
            """Handle theft target selection"""
            parts = safe_split_callback(call.data, "_", 2)
            if not parts:
                self.bot.send_message(call.message.chat.id, "Неверный формат данных")
                return

            target = parts[1]
            player_id = call.from_user.id

            # Map targets to player IDs from Settings
            target_ids = {
                "yura": Settings.PLAYER_IDS['YURA'],
                "max": Settings.PLAYER_IDS['MAX'],
                "bogdan": Settings.PLAYER_IDS['BODYA']
            }
            
            if target not in target_ids:
                self.bot.send_message(call.message.chat.id, "Неверная цель для кражи")
                return
            
            thief = self.player_service.get_player(player_id)
            victim = self.player_service.get_player(target_ids[target])
            
            if not thief or not victim:
                self.bot.send_message(call.message.chat.id, "Ошибка: игрок не найден")
                return
            
            result = self.game_service.execute_theft(thief, victim)
            
            if not result['success']:
                self.bot.send_message(call.message.chat.id, result['message'])
                return
            
            self.bot.send_message(call.message.chat.id, f"Вы украли {result['amount']} см у {result['victim_name']}...")
        
        @self.bot.message_handler(commands=['smazka'])
        def reset_cooldown_command(message):
            """Handle /smazka command to reset pisunchik cooldown"""
            player_id = message.from_user.id
            player = self.player_service.get_player(player_id)
            
            if not player:
                self.bot.reply_to(message, "Вы не зарегистрированы как игрок")
                return
            
            if not player.has_item('smazka'):
                self.bot.reply_to(message, "У вас нет предмета 'smazka'(")
                return
            
            from datetime import datetime, timezone
            player.last_used = datetime(2000, 1, 1, tzinfo=timezone.utc)
            player.remove_item('smazka')
            
            self.player_service.save_player(player)
            self.bot.reply_to(message, "Кулдаун для команды /pisunchik сброшен. Теперь вы можете использовать её снова.")
        
        @self.bot.message_handler(commands=['krystalnie_ballzzz'])
        def crystal_balls_command(message):
            """Handle /krystalnie_ballzzz command"""
            player_id = message.from_user.id
            player = self.player_service.get_player(player_id)
            
            if not player:
                self.bot.reply_to(message, "Вы не зарегистрированы как игрок.")
                return
            
            if not player.has_item('krystalnie_ballzzz'):
                self.bot.reply_to(message, "У вас нету предмета 'krystalnie_ballzzz'.")
                return
            
            if player.ballzzz_number is None:
                next_effect = random.randint(GameConfig.PISUNCHIK_MIN_CHANGE, GameConfig.PISUNCHIK_MAX_CHANGE)
                player.ballzzz_number = next_effect
                self.player_service.save_player(player)
            
            self.bot.reply_to(message, f"Следующее изменение писюнчика будет: {player.ballzzz_number} см.")
        
        @self.bot.message_handler(commands=['masturbator'])
        def masturbator_command(message):
            """Handle /masturbator command"""
            player_id = message.from_user.id
            player = self.player_service.get_player(player_id)
            
            if not player:
                self.bot.reply_to(message, "Вы не зарегистрированы как игрок")
                return
            
            if not player.has_item('masturbator'):
                self.bot.reply_to(message, "У вас нету предмета 'masturbator'")
                return
            
            self.bot.send_message(
                message.chat.id,
                "Вы можете пожертвовать часть своего писюнчика ради получения БТС. "
                "Чем больше размер пожертвован, тем больше BTC выиграно. "
                "1 см = 4 БТС + 5 БТС за каждые 5 см.\n\nВведите количество см для пожертвования:"
            )
            # Pass player_id instead of player object to avoid stale data
            self.bot.register_next_step_handler(message, lambda msg: self.handle_masturbator_input(msg, player_id))
        
        @self.bot.message_handler(commands=['zelie_pisunchika'])
        def potion_command(message):
            """Handle /zelie_pisunchika command"""
            player_id = message.from_user.id
            player = self.player_service.get_player(player_id)

            if not player:
                self.bot.reply_to(message, "Вы не зарегистрированы как игрок.")
                return

            if not player.has_item('zelie_pisunchika'):
                self.bot.reply_to(message, "У вас нету предмета 'zelie_pisunchika'.")
                return

            # 50% chance to increase or decrease
            is_increase = random.choice([True, False])
            amount = 20

            if is_increase:
                player.pisunchik_size += amount
                effect_message = f"Ваш писюнчик увеличился на {amount} см."
            else:
                player.pisunchik_size -= amount
                effect_message = f"Ваш писюнчик уменьшился на {amount} см."

            player.remove_item('zelie_pisunchika')
            self.player_service.save_player(player)

            self.bot.reply_to(message, effect_message)

        # Potion commands
        @self.bot.message_handler(commands=['pisunchik_potion_small'])
        def small_potion_command(message):
            self.handle_potion_command(message, 'small', 3)

        @self.bot.message_handler(commands=['pisunchik_potion_medium'])
        def medium_potion_command(message):
            self.handle_potion_command(message, 'medium', 5)

        @self.bot.message_handler(commands=['pisunchik_potion_large'])
        def large_potion_command(message):
            self.handle_potion_command(message, 'large', 10)
        
    def handle_masturbator_input(self, message, player_id: int):
        """Handle masturbator donation amount input"""
        try:
            # Fetch fresh player data to avoid stale state
            player = self.player_service.get_player(player_id)
            if not player:
                self.bot.reply_to(message, "Игрок не найден")
                return

            donation_amount = int(message.text)
            result = self.game_service.use_masturbator(player, donation_amount)

            if not result['success']:
                self.bot.reply_to(message, result['message'])
                return

            self.bot.reply_to(
                message,
                f"Вы задонатили {result['donated']} см вашего писюнчика и получили {result['coins_received']} БТС взамен"
            )
        except ValueError:
            self.bot.reply_to(message, "Пожалуйста, введите корректное число.")
    
    def handle_potion_command(self, message, size, increase_amount):
        """Handle potion commands"""
        player_id = message.from_user.id
        player = self.player_service.get_player(player_id)
        
        if not player:
            self.bot.reply_to(message, "Вы не зарегистрированы как игрок.")
            return
        
        potion_name = f'pisunchik_potion_{size}'
        if not player.has_item(potion_name):
            self.bot.reply_to(message, f"У вас нету предмета '{potion_name}'.")
            return
        
        player.pisunchik_size += increase_amount
        player.remove_item(potion_name)
        
        self.player_service.save_player(player)
        self.bot.reply_to(message, f"Your pisunchik size increased by {increase_amount} cm.")
    
    def create_roll_keyboard(self):
        """Create inline keyboard for roll command"""
        keyboard = types.InlineKeyboardMarkup()
        keyboard.row(
            types.InlineKeyboardButton(text='1', callback_data='roll_1'),
            types.InlineKeyboardButton(text='3', callback_data='roll_3')
        )
        keyboard.row(
            types.InlineKeyboardButton(text='5', callback_data='roll_5'),
            types.InlineKeyboardButton(text='10', callback_data='roll_10')
        )
        keyboard.row(
            types.InlineKeyboardButton(text='20', callback_data='roll_20'),
            types.InlineKeyboardButton(text='50', callback_data='roll_50')
        )
        keyboard.row(
            types.InlineKeyboardButton(text='100', callback_data='roll_100')
        )
        return keyboard
