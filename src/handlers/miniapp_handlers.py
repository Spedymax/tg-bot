#!/usr/bin/env python3
"""
Handlers for mini-app integration
"""

import logging
import json
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

logger = logging.getLogger(__name__)

class MiniAppHandlers:
    def __init__(self, bot, player_service, game_service):
        self.bot = bot
        self.player_service = player_service
        self.game_service = game_service

        self.router = Router()
        self._register()

    def _register(self):
        """Setup all mini-app related handlers"""

        @self.router.message(Command('casino_app'))
        async def casino_app(message: Message):
            """Handle /casino_app command to launch mini-app"""
            player_id = message.from_user.id
            player = await self.player_service.get_player(player_id)

            if not player:
                await message.reply("Вы не зарегистрированы как игрок, используйте /start")
                return

            # Replace with your actual mini-app URL
            web_app_url = "https://your-domain.com/casino"  # Change this to your actual URL

            markup = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="🎰 Открыть Казино",
                    web_app=WebAppInfo(url=web_app_url)
                )
            ]])

            casino_message = f"🎰 **Добро пожаловать в Казино!** 🎰\\n\\n"
            casino_message += f"💰 Ваш баланс: {player.coins} BTC\\n"
            casino_message += f"🎯 Доступно 6 спинов колеса в день\\n\\n"
            casino_message += f"🎲 Возможные выигрыши:\\n"
            casino_message += f"• 5-50 BTC\\n"
            casino_message += f"• Удвоение монет\\n"
            casino_message += f"• Бонусные призы\\n\\n"
            casino_message += f"Нажмите кнопку ниже, чтобы начать игру!"

            await self.bot.send_message(
                message.chat.id,
                casino_message,
                reply_markup=markup,
                parse_mode='Markdown'
            )

        @self.router.message(Command('casino_status'))
        async def casino_status(message: Message):
            """Handle /casino_status command to check daily limits"""
            player_id = message.from_user.id
            player = await self.player_service.get_player(player_id)

            if not player:
                await message.reply("Вы не зарегистрированы как игрок, используйте /start")
                return

            # Get daily spins info (this would need to be implemented in your player model)
            daily_spins = getattr(player, 'daily_spins', 0)
            max_daily_spins = 6
            spins_left = max(0, max_daily_spins - daily_spins)

            status_message = f"🎰 **Статус Казино** 🎰\\n\\n"
            status_message += f"💰 Баланс: {player.coins} BTC\\n"
            status_message += f"🎯 Спинов использовано сегодня: {daily_spins}/{max_daily_spins}\\n"
            status_message += f"🎲 Спинов осталось: {spins_left}\\n\\n"

            if spins_left > 0:
                status_message += f"✅ Вы можете играть! Используйте /casino_app"
            else:
                status_message += f"❌ Лимит спинов исчерпан на сегодня\\n"
                status_message += f"🕐 Обновление в 00:00 UTC"

            await self.bot.send_message(
                message.chat.id,
                status_message,
                parse_mode='Markdown'
            )

        @self.router.message(F.web_app_data)
        async def handle_web_app_data(message: Message):
            """Handle data received from web app"""
            try:
                # Parse the data received from the web app
                web_app_data = json.loads(message.web_app_data.data)
                player_id = message.from_user.id

                logger.info(f"Received web app data from {player_id}: {web_app_data}")

                # Process the data based on the type
                if web_app_data.get('type') == 'casino_result':
                    await self._handle_casino_result(message, web_app_data)
                elif web_app_data.get('type') == 'casino_session_end':
                    await self._handle_casino_session_end(message, web_app_data)
                else:
                    logger.warning(f"Unknown web app data type: {web_app_data.get('type')}")

            except Exception as e:
                logger.error(f"Error handling web app data: {e}")
                await message.reply("Произошла ошибка при обработке данных из мини-приложения.")

    async def _handle_casino_result(self, message: Message, data):
        """Handle casino game result"""
        try:
            player_id = message.from_user.id
            player = await self.player_service.get_player(player_id)

            if not player:
                await message.reply("Игрок не найден")
                return

            # Update player's coins and spins
            new_coins = data.get('coins', player.coins)
            spins_used = data.get('spins_used', 0)
            prize_text = data.get('prize_text', 'Неизвестный результат')

            # Update player data
            player.coins = new_coins
            if not hasattr(player, 'daily_spins'):
                player.daily_spins = 0
            player.daily_spins = spins_used

            # Save the updated player
            await self.player_service.save_player(player)

            # Send confirmation message
            result_message = f"🎰 **Результат игры в казино** 🎰\\n\\n"
            result_message += f"🎲 Результат: {prize_text}\\n"
            result_message += f"💰 Ваш баланс: {new_coins} BTC\\n"
            result_message += f"🎯 Спинов использовано: {spins_used}/6\\n"

            await self.bot.send_message(
                message.chat.id,
                result_message,
                parse_mode='Markdown'
            )

        except Exception as e:
            logger.error(f"Error handling casino result: {e}")
            await message.reply("Ошибка при обработке результата игры.")

    async def _handle_casino_session_end(self, message: Message, data):
        """Handle end of casino session"""
        try:
            player_id = message.from_user.id
            player = await self.player_service.get_player(player_id)

            if not player:
                return

            # Update final player state
            final_coins = data.get('coins', player.coins)
            total_spins = data.get('total_spins', 0)
            total_winnings = data.get('total_winnings', 0)

            player.coins = final_coins
            if not hasattr(player, 'daily_spins'):
                player.daily_spins = 0
            player.daily_spins = total_spins

            await self.player_service.save_player(player)

            # Send session summary
            summary_message = f"🎰 **Итоги сессии в казино** 🎰\\n\\n"
            summary_message += f"💰 Финальный баланс: {final_coins} BTC\\n"
            summary_message += f"🎯 Спинов сыграно: {total_spins}\\n"
            summary_message += f"🏆 Общий выигрыш: {total_winnings} BTC\\n\\n"

            if total_spins >= 6:
                summary_message += f"✅ Вы использовали все спины на сегодня!\\n"
                summary_message += f"🕐 Новые спины будут доступны завтра"
            else:
                remaining_spins = 6 - total_spins
                summary_message += f"🎲 Осталось спинов: {remaining_spins}\\n"
                summary_message += f"Используйте /casino_app чтобы продолжить"

            await self.bot.send_message(
                message.chat.id,
                summary_message,
                parse_mode='Markdown'
            )

        except Exception as e:
            logger.error(f"Error handling casino session end: {e}")
            await message.reply("Ошибка при завершении сессии.")

    def get_casino_web_app_url(self):
        """Get the URL for the casino web app"""
        # This should be configured based on your deployment
        return "https://your-domain.com/casino"  # Replace with your actual URL
