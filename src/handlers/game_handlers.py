import asyncio
import logging
import random
import time
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)
from config.game_config import GameConfig
from config.settings import Settings
from utils.helpers import safe_split_callback, safe_int, escape_html, safe_username

class GameHandlers:
    def __init__(self, bot, player_service, game_service):
        self.bot = bot
        self.player_service = player_service
        self.game_service = game_service
        self.router = Router()
        self._register()

    async def _maybe_send_death_notice(self, chat_id: int, player) -> None:
        """Send one-shot death notification if pet just died from hunger."""
        if not getattr(player, 'pet_death_pending_notify', False):
            return
        player.pet_death_pending_notify = False
        pet = getattr(player, 'pet', None)
        pet_name = ''
        if pet:
            from utils.helpers import escape_html
            pet_name = escape_html(pet.get('name', ''))
        name_part = f' «{pet_name}»' if pet_name else ''
        await self.bot.send_message(
            chat_id,
            f"💀 Питомец{name_part} умер от голода! Используй /pet чтобы возродить.",
            parse_mode='HTML'
        )

    def _register(self):
        """Register all game-related command handlers"""

        @self.router.message(Command('pisunchik'))
        async def pisunchik_command(message: Message):
            """Handle /pisunchik command"""
            player_id = message.from_user.id
            player = await asyncio.to_thread(self.player_service.get_player, player_id)

            if not player:
                await message.reply("Вы не зарегистрированы как игрок, используйте /start")
                return

            result = await asyncio.to_thread(self.game_service.execute_pisunchik_command, player)

            if not result['success']:
                await message.reply(result['message'])
                return

            # Reload player since execute_pisunchik_command saves internally
            player = await asyncio.to_thread(self.player_service.get_player, player_id)

            # Pet activity tracking + food drop
            import random as _rand
            from datetime import datetime, timezone
            from services.pet_service import PetService as _PetSvc
            _pet_svc = _PetSvc()
            await asyncio.to_thread(_pet_svc.record_game_activity, player, 'pisunchik', datetime.now(timezone.utc))
            got_food = player.pet and player.pet.get('is_alive') and _rand.random() < 0.20
            if got_food:
                player.add_item('pet_food_basic')
            await self._maybe_send_death_notice(message.chat.id, player)
            await asyncio.to_thread(self.player_service.save_player, player)

            pet_badge = await asyncio.to_thread(_pet_svc.get_pet_badge, player)

            reply_message = (
                f"Ваш писюнчик{pet_badge}: {result['new_size']} см\n"
                f"Изменения: {result['size_change']} см\n"
                f"Также вы получили: {result['coins_change']} BTC"
            )
            if got_food:
                reply_message += "\n🍖 +1 корм для питомца!"

            for effect in result['effects']:
                reply_message += f"\n{effect}"

            await message.reply(reply_message)

        @self.router.message(Command('kazik'))
        async def casino_command(message: Message):
            """Handle /kazik command"""
            player_id = message.from_user.id
            player = await asyncio.to_thread(self.player_service.get_player, player_id)

            if not player:
                await message.reply("Вы не зарегистрированы как игрок")
                return

            result = await asyncio.to_thread(self.game_service.execute_casino_command, player)

            if not result['success']:
                await message.reply(result['message'])
                return

            if result.get('send_dice'):
                dice_msg_ids = []
                total_wins = 0

                try:
                    for i in range(6):
                        dice_msg = await self.bot.send_dice(
                            message.chat.id, emoji='🎰',
                            disable_notification=True
                        )
                        dice_msg_ids.append(dice_msg.message_id)
                        dice_value = dice_msg.dice.value

                        if dice_value in GameConfig.CASINO_JACKPOT_VALUES:
                            total_wins += 1
                            player.add_coins(GameConfig.CASINO_JACKPOT_REWARD)

                        if i < 5:
                            await asyncio.sleep(GameConfig.CASINO_DICE_DELAY)
                except Exception:
                    pass  # Partial result — still deliver summary below

                # Wait for last animation to finish, then delete all dice
                await asyncio.sleep(GameConfig.CASINO_ANIMATION_WAIT)
                for msg_id in dice_msg_ids:
                    try:
                        await self.bot.delete_message(message.chat.id, msg_id)
                    except Exception as e:
                        logger.warning(f"Casino: failed to delete dice msg {msg_id}: {e}")

                # Pet activity tracking + death notice
                import random as _rand
                from datetime import datetime, timezone
                from services.pet_service import PetService as _PetSvc
                _pet_svc = _PetSvc()
                await asyncio.to_thread(_pet_svc.record_game_activity, player, 'casino', datetime.now(timezone.utc))
                got_food = total_wins > 0 and player.pet and player.pet.get('is_alive') and _rand.random() < 0.15
                if got_food:
                    player.add_item('pet_food_basic')

                await self._maybe_send_death_notice(message.chat.id, player)
                await asyncio.to_thread(self.player_service.save_player, player)

                if total_wins > 0:
                    summary = f"🎰 Казино: {total_wins}/6 побед! Выигрыш: {total_wins * GameConfig.CASINO_JACKPOT_REWARD} BTC 🎉"
                else:
                    summary = "🎰 Казино: 0/6. Ничего не выиграл."
                if got_food:
                    summary += f"\n🍖 {player.player_name} получил +1 корм для питомца!"
                await self.bot.send_message(message.chat.id, summary, disable_notification=True)

        @self.router.message(Command('roll'))
        async def roll_command(message: Message):
            """Handle /roll command with inline keyboard"""
            keyboard = self.create_roll_keyboard()
            await self.bot.send_message(message.chat.id, "Выберите, сколько раз вы хотите бросить кубик:", reply_markup=keyboard)

        @self.router.callback_query(F.data.startswith('roll_'))
        async def handle_roll_callback(call: CallbackQuery):
            """Handle roll option selection"""
            parts = safe_split_callback(call.data, "_", 2)
            if not parts:
                await self.bot.send_message(call.message.chat.id, "Неверный формат данных")
                return

            rolls = safe_int(parts[1], 0)
            if rolls <= 0:
                await self.bot.send_message(call.message.chat.id, "Неверное количество бросков")
                return

            player_id = call.from_user.id
            player = await asyncio.to_thread(self.player_service.get_player, player_id)

            if not player:
                await self.bot.send_message(call.message.chat.id, "Вы не зарегистрированы как игрок")
                return

            result = await asyncio.to_thread(self.game_service.execute_roll_command, player, rolls)

            if not result['success']:
                await self.bot.send_message(call.message.chat.id, result['message'])
                return

            # Pet activity tracking + death notice
            from datetime import datetime, timezone
            from services.pet_service import PetService as _PetSvc
            _pet_svc = _PetSvc()
            player = await asyncio.to_thread(self.player_service.get_player, player_id)
            if player:
                await asyncio.to_thread(_pet_svc.record_game_activity, player, 'roll', datetime.now(timezone.utc))
                await self._maybe_send_death_notice(call.message.chat.id, player)
                await asyncio.to_thread(self.player_service.save_player, player)
                pet_badge = await asyncio.to_thread(_pet_svc.get_pet_badge, player)
            else:
                pet_badge = ''

            try:
                await self.bot.delete_message(call.message.chat.id, call.message.message_id)
            except Exception as e:
                logger.warning(f"Roll: failed to delete selection message: {e}")

            dice_str = ' '.join(map(str, result['results']))
            await self.bot.send_message(
                call.message.chat.id,
                f"🎲 Потрачено: {result['cost']} BTC | [{dice_str}] | Писюнчик{pet_badge}: {result['new_size']} см"
            )

            if result['jackpots'] > 0:
                for i in range(result['jackpots']):
                    await asyncio.sleep(GameConfig.ROLL_JACKPOT_DELAY)
                    if i >= 1:
                        await self.bot.send_message(call.message.chat.id, "ЧТО? ЕЩЕ ОДИН?")
                        await asyncio.sleep(GameConfig.ROLL_JACKPOT_DELAY)
                    await self.bot.send_message(call.message.chat.id, "🆘🤑БОГ ТЫ МОЙ! ТЫ ВЫИГРАЛ ДЖЕКПОТ! 400 BTC ТЕБЕ НА СЧЕТ!🤑🆘")

        @self.router.message(Command('vor'))
        async def theft_command(message: Message):
            """Handle /vor command"""
            player_id = message.from_user.id
            player = await asyncio.to_thread(self.player_service.get_player, player_id)

            if not player:
                await message.reply("Вы не зарегистрированы как игрок")
                return

            can_steal, error_message = await asyncio.to_thread(self.game_service.can_steal, player)
            if not can_steal:
                await message.reply(error_message)
                return

            # Create theft target selection based on player ID
            player_ids = Settings.PLAYER_IDS
            buttons = []
            if player_id == player_ids['YURA']:
                buttons = [
                    [InlineKeyboardButton(text="Макс", callback_data="vor_max")],
                    [InlineKeyboardButton(text="Богдан", callback_data="vor_bogdan")],
                ]
            elif player_id == player_ids['MAX']:
                buttons = [
                    [InlineKeyboardButton(text="Юра", callback_data="vor_yura")],
                    [InlineKeyboardButton(text="Богдан", callback_data="vor_bogdan")],
                ]
            elif player_id == player_ids['BODYA']:
                buttons = [
                    [InlineKeyboardButton(text="Макс", callback_data="vor_max")],
                    [InlineKeyboardButton(text="Юра", callback_data="vor_yura")],
                ]
            markup = InlineKeyboardMarkup(inline_keyboard=buttons)

            # Escape username to prevent XSS
            username = safe_username(message.from_user.username, player_id)
            await self.bot.send_message(
                message.chat.id,
                f"<a href='tg://user?id={player_id}'>@{username}</a>, у кого крадём член?",
                reply_markup=markup,
                parse_mode='HTML'
            )

        @self.router.callback_query(F.data.startswith("vor_"))
        async def handle_theft_callback(call: CallbackQuery):
            """Handle theft target selection"""
            parts = safe_split_callback(call.data, "_", 2)
            if not parts:
                await self.bot.send_message(call.message.chat.id, "Неверный формат данных")
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
                await self.bot.send_message(call.message.chat.id, "Неверная цель для кражи")
                return

            thief = await asyncio.to_thread(self.player_service.get_player, player_id)
            victim = await asyncio.to_thread(self.player_service.get_player, target_ids[target])

            if not thief or not victim:
                await self.bot.send_message(call.message.chat.id, "Ошибка: игрок не найден")
                return

            result = await asyncio.to_thread(self.game_service.execute_theft, thief, victim)

            if not result['success']:
                await self.bot.send_message(call.message.chat.id, result['message'])
                return

            await self.bot.send_message(call.message.chat.id, f"Вы украли {result['amount']} см у {result['victim_name']}...")

        @self.router.message(Command('smazka'))
        async def reset_cooldown_command(message: Message):
            """Handle /smazka command to reset pisunchik cooldown"""
            player_id = message.from_user.id
            player = await asyncio.to_thread(self.player_service.get_player, player_id)

            if not player:
                await message.reply("Вы не зарегистрированы как игрок")
                return

            if not player.has_item('smazka'):
                await message.reply("У вас нет предмета 'smazka'(")
                return

            from datetime import datetime, timezone
            player.last_used = datetime(2000, 1, 1, tzinfo=timezone.utc)
            player.remove_item('smazka')

            await asyncio.to_thread(self.player_service.save_player, player)
            await message.reply("Кулдаун для команды /pisunchik сброшен. Теперь вы можете использовать её снова.")

        @self.router.message(Command('krystalnie_ballzzz'))
        async def crystal_balls_command(message: Message):
            """Handle /krystalnie_ballzzz command"""
            player_id = message.from_user.id
            player = await asyncio.to_thread(self.player_service.get_player, player_id)

            if not player:
                await message.reply("Вы не зарегистрированы как игрок.")
                return

            if not player.has_item('krystalnie_ballzzz'):
                await message.reply("У вас нету предмета 'krystalnie_ballzzz'.")
                return

            if player.ballzzz_number is None:
                next_effect = random.randint(GameConfig.PISUNCHIK_MIN_CHANGE, GameConfig.PISUNCHIK_MAX_CHANGE)
                player.ballzzz_number = next_effect
                await asyncio.to_thread(self.player_service.save_player, player)

            await message.reply(f"Следующее изменение писюнчика будет: {player.ballzzz_number} см.")

        @self.router.message(Command('masturbator'))
        async def masturbator_command(message: Message):
            """Handle /masturbator command"""
            player_id = message.from_user.id
            player = await asyncio.to_thread(self.player_service.get_player, player_id)

            if not player:
                await message.reply("Вы не зарегистрированы как игрок")
                return

            if not player.has_item('masturbator'):
                await message.reply("У вас нету предмета 'masturbator'")
                return

            await self.bot.send_message(
                message.chat.id,
                "Вы можете пожертвовать часть своего писюнчика ради получения БТС. "
                "Чем больше размер пожертвован, тем больше BTC выиграно. "
                "1 см = 4 БТС + 5 БТС за каждые 5 см.\n\nВведите количество см для пожертвования:"
            )
            # Pass player_id instead of player object to avoid stale data
            self.bot.register_next_step_handler(message, lambda msg: asyncio.create_task(self.handle_masturbator_input(msg, player_id)))

        @self.router.message(Command('zelie_pisunchika'))
        async def potion_command(message: Message):
            """Handle /zelie_pisunchika command"""
            player_id = message.from_user.id
            player = await asyncio.to_thread(self.player_service.get_player, player_id)

            if not player:
                await message.reply("Вы не зарегистрированы как игрок.")
                return

            if not player.has_item('zelie_pisunchika'):
                await message.reply("У вас нету предмета 'zelie_pisunchika'.")
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
            await asyncio.to_thread(self.player_service.save_player, player)

            await message.reply(effect_message)

        # Potion commands
        @self.router.message(Command('pisunchik_potion_small'))
        async def small_potion_command(message: Message):
            await self.handle_potion_command(message, 'small', 3)

        @self.router.message(Command('pisunchik_potion_medium'))
        async def medium_potion_command(message: Message):
            await self.handle_potion_command(message, 'medium', 5)

        @self.router.message(Command('pisunchik_potion_large'))
        async def large_potion_command(message: Message):
            await self.handle_potion_command(message, 'large', 10)

    async def handle_masturbator_input(self, message: Message, player_id: int):
        """Handle masturbator donation amount input"""
        try:
            # Fetch fresh player data to avoid stale state
            player = await asyncio.to_thread(self.player_service.get_player, player_id)
            if not player:
                await message.reply("Игрок не найден")
                return

            donation_amount = int(message.text)
            result = await asyncio.to_thread(self.game_service.use_masturbator, player, donation_amount)

            if not result['success']:
                await message.reply(result['message'])
                return

            await message.reply(
                f"Вы задонатили {result['donated']} см вашего писюнчика и получили {result['coins_received']} БТС взамен"
            )
        except ValueError:
            await message.reply("Пожалуйста, введите корректное число.")

    async def handle_potion_command(self, message: Message, size, increase_amount):
        """Handle potion commands"""
        player_id = message.from_user.id
        player = await asyncio.to_thread(self.player_service.get_player, player_id)

        if not player:
            await message.reply("Вы не зарегистрированы как игрок.")
            return

        potion_name = f'pisunchik_potion_{size}'
        if not player.has_item(potion_name):
            await message.reply(f"У вас нету предмета '{potion_name}'.")
            return

        player.pisunchik_size += increase_amount
        player.remove_item(potion_name)

        await asyncio.to_thread(self.player_service.save_player, player)
        await message.reply(f"Your pisunchik size increased by {increase_amount} cm.")

    def create_roll_keyboard(self):
        """Create inline keyboard for roll command"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text='1', callback_data='roll_1'),
                InlineKeyboardButton(text='3', callback_data='roll_3'),
            ],
            [
                InlineKeyboardButton(text='5', callback_data='roll_5'),
                InlineKeyboardButton(text='10', callback_data='roll_10'),
            ],
            [
                InlineKeyboardButton(text='20', callback_data='roll_20'),
                InlineKeyboardButton(text='50', callback_data='roll_50'),
            ],
            [
                InlineKeyboardButton(text='100', callback_data='roll_100'),
            ],
        ])
