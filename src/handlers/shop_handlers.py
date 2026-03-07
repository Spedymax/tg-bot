import asyncio
import json
import logging
import random
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from services.stock_service import StockService
from states.shop import ShopStates
from utils.helpers import safe_split_callback, safe_int

logger = logging.getLogger(__name__)

class ShopHandlers:
    def __init__(self, bot, player_service, game_service):
        self.bot = bot
        self.player_service = player_service
        self.game_service = game_service
        self.stock_service = StockService()
        self.shop_data = {}
        self.statuetki_data = {}
        self.router = Router()
        self._register()

    def load_shop_data(self, shop_data, statuetki_data):
        """Load shop and statuetki data"""
        self.shop_data = shop_data
        self.statuetki_data = statuetki_data

    def _register(self):
        """Setup all shop-related command handlers"""

        @self.router.message(Command('shop'))
        async def show_shop(message: Message):
            """Handle /shop command with inline keyboard"""
            player_id = message.from_user.id
            player = await asyncio.to_thread(self.player_service.get_player, player_id)

            if not player:
                await message.reply("Вы не зарегистрированы как игрок")
                return

            buttons = []
            for item_name, base_price in self.shop_data['prices'].items():
                discounted_price = self.game_service.calculate_shop_discount(player, base_price)
                display_name = self.shop_data.get('names', {}).get(item_name, item_name)
                button_text = f"{display_name} - {discounted_price} BTC"
                buttons.append([InlineKeyboardButton(text=button_text, callback_data=f"shop_buy_{item_name}")])

            markup = InlineKeyboardMarkup(inline_keyboard=buttons)

            shop_message = "🛍️ Добро пожаловать в магазин! 🛍️\n\n"
            shop_message += f"💰 У вас есть: {player.coins} BTC\n\n"
            shop_message += "📦 Ваши предметы: /items\n\n"
            shop_message += "Выберите предмет для покупки:"

            await self.bot.send_message(message.chat.id, shop_message, reply_markup=markup)

        @self.router.message(Command('items'))
        async def show_items(message: Message):
            """Handle /items command"""
            player_id = message.from_user.id
            player = await asyncio.to_thread(self.player_service.get_player, player_id)

            if not player:
                await message.reply("Вы не зарегистрированы как игрок")
                return

            if not player.items:
                await message.reply("У вас нету предметов(")
                return

            item_descriptions = []
            for item in player.items:
                if item in self.shop_data['description']:
                    display_name = self.shop_data.get('names', {}).get(item, item)
                    item_descriptions.append(f"{display_name}: {self.shop_data['description'][item]}")

            if item_descriptions:
                items_text = "\n\n".join(item_descriptions)
                await message.reply(f"Ваши предметы:\n\n{items_text}")
            else:
                await message.reply("Нету описания предметов (Странно)")

        @self.router.message(Command('statuetki'))
        async def show_statuetki(message: Message):
            """Handle /statuetki command"""
            player_id = message.from_user.id
            player = await asyncio.to_thread(self.player_service.get_player, player_id)

            if not player:
                await message.reply("Вы не зарегистрированы как игрок")
                return

            if not player.statuetki:
                await message.reply("У вас нету статуэток:(")
                return

            item_images = {
                'Pudginio': '/home/spedymax/tg-bot/assets/images/statuetki/pudginio.jpg',
                'Ryadovoi Rudgers': '/home/spedymax/tg-bot/assets/images/statuetki/ryadovoi_rudgers.jpg',
                'Polkovnik Buchantos': '/home/spedymax/tg-bot/assets/images/statuetki/polkovnik_buchantos.jpg',
                'General Chin-Choppa': '/home/spedymax/tg-bot/assets/images/statuetki/general_chin_choppa.png'
            }

            statuetki_descriptions = []
            for statuetka in player.statuetki:
                if statuetka in self.statuetki_data['description']:
                    description = f"{statuetka}: {self.statuetki_data['description'][statuetka]}"
                    statuetki_descriptions.append(description)

            if statuetki_descriptions:
                await message.reply("Ваши статуэтки:\n")
                await asyncio.sleep(1)

                for statuetka in player.statuetki:
                    description = self.statuetki_data['description'].get(statuetka, 'No description available')
                    item_image_filename = item_images.get(statuetka, '/home/spedymax/tg-bot/assets/images/statuetki/pudginio.jpg')
                    try:
                        with open(item_image_filename, 'rb') as photo:
                            await asyncio.sleep(1)
                            await self.bot.send_photo(message.chat.id, photo, caption=f"{statuetka} - {description}")
                    except FileNotFoundError:
                        await self.bot.send_message(message.chat.id, f"{statuetka} - {description}")

                n = len(player.statuetki)
                await self.bot.send_message(message.chat.id, f"Количество статуэток у вас: {n} из 4")

                # Check if player has all 4 statuetki for special event
                if len(player.statuetki) == 4:
                    await self._handle_all_statuetki_collected(player, message)
            else:
                await message.reply("Нету описания предметов (Странно)")

        @self.router.message(Command('statuetki_shop'))
        async def show_statuetki_shop(message: Message):
            """Handle /statuetki_shop command with inline keyboard"""
            player_id = message.from_user.id
            player = await asyncio.to_thread(self.player_service.get_player, player_id)

            if not player:
                await message.reply("Вы не зарегистрированы как игрок")
                return

            buttons = []
            available_items = []
            for item_name, item_price in self.statuetki_data['prices'].items():
                # Only show items player doesn't own yet
                if item_name not in player.statuetki:
                    button_text = f"{item_name} - {item_price} BTC"
                    buttons.append([InlineKeyboardButton(text=button_text, callback_data=f"statuetki_buy_{item_name}")])
                    available_items.append(item_name)

            # If player has all statuetki, show a message
            if not available_items:
                await self.bot.send_message(message.chat.id, "🎉 Поздравляем! Вы собрали все статуэтки!\n\n🏆 Используйте /statuetki чтобы активировать особое событие!")
                return

            markup = InlineKeyboardMarkup(inline_keyboard=buttons)

            shop_message = "🏰 Магазин статуэток 🏰\n\n"
            shop_message += f"💰 У вас есть: {player.coins} BTC\n\n"
            shop_message += f"🗿 Ваши статуэтки: /statuetki ({len(player.statuetki)}/4)\n\n"
            shop_message += "Выберите статуэтку для покупки:"

            await self.bot.send_message(message.chat.id, shop_message, reply_markup=markup)

        @self.router.message(Command('characteristics'))
        async def show_characteristics(message: Message):
            """Handle /characteristics command"""
            player_id = message.from_user.id
            player = await asyncio.to_thread(self.player_service.get_player, player_id)

            if not player:
                await message.reply("Вы не зарегистрированы как игрок, используйте /start")
                return

            if not player.characteristics:
                await message.reply("Ой, у вас нету характеристик :( \nСначала купите все статуэтки используя /statuetki_shop")
                return

            try:
                with open('/home/spedymax/tg-bot/assets/data/char.json', 'r', encoding='utf-8') as f:
                    char_data = json.load(f)

                characteristics_text = "🎯 Ваши характеристики:\n\n"
                for characteristic in player.characteristics:
                    characteristic_name, current_level = characteristic.split(":")
                    description = char_data['description'].get(characteristic_name, "Описание не найдено")
                    characteristics_text += f"⚡ **{characteristic_name}** (Уровень {current_level})\n"
                    characteristics_text += f"📝 {description}\n\n"

                characteristics_text += "🔧 Используйте /upgrade_char для улучшения характеристик!"

                await message.reply(characteristics_text, parse_mode='Markdown')

            except FileNotFoundError:
                characteristics_text = "Ваши характеристики:\n"
                for characteristic in player.characteristics:
                    characteristic_name, current_level = characteristic.split(":")
                    characteristics_text += f"{characteristic_name} (Уровень {current_level})\n"

                await message.reply(characteristics_text)
            except Exception as e:
                await message.reply(f"Произошла ошибка при загрузке характеристик: {str(e)}")

        @self.router.message(Command('upgrade_char'))
        async def upgrade_characteristic(message: Message):
            """Handle /upgrade_char command"""
            player_id = message.from_user.id
            player = await asyncio.to_thread(self.player_service.get_player, player_id)

            if not player:
                await message.reply("Вы не зарегистрированы как игрок, используйте /start")
                return

            if not player.characteristics:
                await message.reply("У вас нет характеристик для улучшения.")
                return

            buttons = []
            for characteristic in player.characteristics:
                characteristic_name, _ = characteristic.split(":")
                buttons.append([InlineKeyboardButton(text=characteristic_name, callback_data=f"selectchar_{characteristic}")])

            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

            await self.bot.send_message(message.chat.id, "Выберите характеристику для улучшения:", reply_markup=keyboard)

        # Shop confirmation callbacks
        @self.router.callback_query(F.data.startswith("buy_confirm_"))
        async def confirm_shop_purchase(call: CallbackQuery):
            """Handle shop purchase confirmation"""
            await call.answer()
            await call.message.edit_reply_markup(reply_markup=None)

            player_id = call.from_user.id
            player = await asyncio.to_thread(self.player_service.get_player, player_id)
            item_name = call.data.split("_", 2)[2]
            base_price = self.shop_data['prices'].get(item_name, 0)

            if player and base_price > 0:
                discounted_price = self.game_service.calculate_shop_discount(player, base_price)

                if player.spend_coins(discounted_price):
                    player.add_item(item_name)
                    await asyncio.to_thread(self.player_service.save_player, player)
                    display_name = self.shop_data.get('names', {}).get(item_name, item_name)
                    await self.bot.send_message(call.message.chat.id, f"Вы купили {display_name} за {discounted_price} BTC.")
                else:
                    await self.bot.send_message(call.message.chat.id, "Недостаточно денег((")

        @self.router.callback_query(F.data.startswith("statuetka_confirm_"))
        async def confirm_statuetka_purchase(call: CallbackQuery):
            """Handle statuetka purchase confirmation"""
            await call.answer()
            await call.message.edit_reply_markup(reply_markup=None)

            player_id = call.from_user.id
            player = await asyncio.to_thread(self.player_service.get_player, player_id)
            item_name = call.data.split("_", 2)[2]
            item_price = self.statuetki_data['prices'].get(item_name, 0)

            if player and item_price > 0:
                if player.spend_coins(item_price):
                    player.statuetki.append(item_name)
                    await asyncio.to_thread(self.player_service.save_player, player)
                    await self.bot.send_message(call.message.chat.id, f"Вы купили {item_name} за {item_price} BTC.")
                else:
                    await self.bot.send_message(call.message.chat.id, "Недостаточно денег((")

        @self.router.callback_query(F.data.startswith("statuetki_buy_"))
        async def handle_statuetki_purchase(call: CallbackQuery):
            """Handle statuetki purchase from inline keyboard"""
            player_id = call.from_user.id
            player = await asyncio.to_thread(self.player_service.get_player, player_id)

            if not player:
                await call.answer("Вы не зарегистрированы как игрок")
                return

            item_name = call.data.split("_", 2)[2]
            item_price = self.statuetki_data['prices'].get(item_name, 0)

            if item_price <= 0:
                await call.answer("Предмет не найден")
                return

            if item_name in player.statuetki:
                await call.answer("У вас уже есть эта статуэтка!")
                return

            if player.coins < item_price:
                await call.answer(f"Недостаточно денег. Нужно {item_price} BTC")
                return

            await call.answer()

            confirm_button = InlineKeyboardButton(text="✅ Купить", callback_data=f"statuetka_confirm_{item_name}")
            cancel_button = InlineKeyboardButton(text="❌ Отмена", callback_data="statuetka_cancel")
            markup = InlineKeyboardMarkup(inline_keyboard=[[confirm_button, cancel_button]])

            description = self.statuetki_data.get('description', {}).get(item_name, 'Описание не найдено')

            confirmation_message = "🏰 Подтверждение покупки\n\n"
            confirmation_message += f"🗿 Статуэтка: {item_name}\n"
            confirmation_message += f"💰 Цена: {item_price} BTC\n\n"
            confirmation_message += f"📜 Описание: {description}\n\n"
            confirmation_message += "Вы уверены, что хотите купить эту статуэтку?"

            await call.message.edit_text(text=confirmation_message, reply_markup=markup)

        @self.router.callback_query(F.data.startswith("shop_buy_"))
        async def handle_shop_purchase(call: CallbackQuery):
            """Handle shop purchase from inline keyboard"""
            player_id = call.from_user.id
            player = await asyncio.to_thread(self.player_service.get_player, player_id)

            if not player:
                await call.answer("Вы не зарегистрированы как игрок")
                return

            item_name = call.data.split("_", 2)[2]
            base_price = self.shop_data['prices'].get(item_name, 0)

            if base_price <= 0:
                await call.answer("Предмет не найден")
                return

            discounted_price = self.game_service.calculate_shop_discount(player, base_price)

            if player.coins < discounted_price:
                await call.answer(f"Недостаточно денег. Нужно {discounted_price} BTC")
                return

            await call.answer()

            confirm_button = InlineKeyboardButton(text="✅ Купить", callback_data=f"buy_confirm_{item_name}")
            cancel_button = InlineKeyboardButton(text="❌ Отмена", callback_data="buy_cancel")
            markup = InlineKeyboardMarkup(inline_keyboard=[[confirm_button, cancel_button]])

            display_name = self.shop_data.get('names', {}).get(item_name, item_name)
            description = self.shop_data.get('description', {}).get(item_name, 'Описание не найдено')

            confirmation_message = "🛍️ Подтверждение покупки\n\n"
            confirmation_message += f"🏷️ Предмет: {display_name}\n"
            confirmation_message += f"💰 Цена: {discounted_price} BTC\n\n"
            confirmation_message += f"📜 Описание: {description}\n\n"
            confirmation_message += "Вы уверены, что хотите купить этот предмет?"

            await call.message.edit_text(text=confirmation_message, reply_markup=markup)

        @self.router.callback_query(F.data.in_({"buy_cancel", "statuetka_cancel"}))
        async def cancel_purchase(call: CallbackQuery):
            """Handle purchase cancellation"""
            await call.answer("Покупка отменена")
            await call.message.edit_text(text="❌ Покупка отменена")

        # Characteristic upgrade callbacks
        @self.router.callback_query(F.data.startswith("selectchar"))
        async def select_characteristic_for_upgrade(call: CallbackQuery):
            """Handle characteristic selection for upgrade"""
            await call.answer()
            selected_characteristic = call.data.split("_")[1]

            buttons = []
            for i in range(1, 15):
                button_text = f"Повысить на {i} уровень(ей)"
                buttons.append([InlineKeyboardButton(text=button_text, callback_data=f"upgrade_{selected_characteristic}_{i}")])

            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

            await self.bot.send_message(call.message.chat.id, "Выберите количество уровней для улучшения:", reply_markup=keyboard)

        @self.router.callback_query(F.data.startswith("upgrade"))
        async def handle_characteristic_upgrade(call: CallbackQuery):
            """Handle characteristic upgrade"""
            await call.answer()
            chat_id = call.message.chat.id
            player_id = call.from_user.id
            player = await asyncio.to_thread(self.player_service.get_player, player_id)

            if not player:
                await self.bot.send_message(chat_id, "Игрок не найден")
                return

            call_data = call.data.split("_")
            selected_characteristic, levels_to_upgrade = call_data[1], int(call_data[2])

            result = await asyncio.to_thread(
                self.game_service.upgrade_characteristic,
                player, selected_characteristic.split(":")[0], levels_to_upgrade
            )

            if result['success']:
                await self.bot.send_message(chat_id, f"Вы улучшили {result['characteristic']} до уровня {result['new_level']}!")
            else:
                await self.bot.send_message(chat_id, result['message'])

        # Stock-related handlers
        @self.router.message(Command('stocks_update'))
        async def stocks_update(message: Message):
            """Handle /stocks_update command (admin only)"""
            from config.settings import ADMIN_IDS
            if message.from_user.id in ADMIN_IDS:
                try:
                    conn = self.player_service.get_connection()
                    cursor = conn.cursor()

                    old_stock_data = self.stock_service.get_stock_data(cursor)
                    self.stock_service.update_stock_prices(cursor)
                    conn.commit()
                    new_stock_data = self.stock_service.get_stock_data(cursor)

                    stock_message = "Акции компаний на данный момент:\n\n"
                    for company, new_price in new_stock_data.items():
                        old_price = old_stock_data.get(company, new_price)
                        change, arrow = self.stock_service.calculate_price_change(old_price, new_price)
                        stock_message += f"{company}: {new_price} BTC ({abs(change):.2f}% {arrow})\n"

                    cursor.close()
                    conn.close()

                    await self.bot.send_message(message.chat.id, stock_message)
                    await self.bot.send_message(
                        message.chat.id,
                        "Чтобы купить акции используйте /buy_stocks \nЧтобы посмотреть свои акции используйте /my_stocks. \nЧтобы посмотреть стоимость акций на данный момент используйте /current_stocks"
                    )
                except Exception as e:
                    await self.bot.send_message(message.chat.id, f"Ошибка обновления акций: {str(e)}")
            else:
                await self.bot.send_message(message.chat.id, "Вы не админ((((((((((((")

        @self.router.message(Command('current_stocks'))
        async def current_stocks(message: Message):
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

                await message.reply(stock_message)
            except Exception as e:
                await message.reply(f"Ошибка получения данных об акциях: {str(e)}")

        @self.router.message(Command('my_stocks'))
        async def my_stocks(message: Message):
            """Handle /my_stocks command"""
            player_id = message.from_user.id
            player = await asyncio.to_thread(self.player_service.get_player, player_id)

            if not player:
                await message.reply("Вы не зарегистрированы как игрок, используйте /start")
                return

            if not hasattr(player, 'player_stocks') or not player.player_stocks:
                await message.reply("У вас нет акций")
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

                await message.reply(stocks_text)
            except Exception as e:
                await message.reply(f"Ошибка получения ваших акций: {str(e)}")

        @self.router.message(Command('buy_stocks'))
        async def buy_stocks(message: Message):
            """Handle /buy_stocks command"""
            companies = ['ATB', 'Rockstar', 'Google', 'Apple', 'Valve', 'Obuhov toilet paper']
            buttons = [[InlineKeyboardButton(text=company, callback_data=f"buy_stocks_{company}")] for company in companies]
            markup = InlineKeyboardMarkup(inline_keyboard=buttons)
            await self.bot.send_message(message.chat.id, "Выберите компанию акции которой хотите купить:", reply_markup=markup)

        @self.router.message(Command('sell_stocks'))
        async def sell_stocks(message: Message):
            """Handle /sell_stocks command"""
            player_id = message.from_user.id
            player = await asyncio.to_thread(self.player_service.get_player, player_id)

            if not player or not hasattr(player, 'player_stocks') or not player.player_stocks:
                await self.bot.send_message(message.chat.id, "Ты бомж, у тебя вообще нету акций.")
                return

            owned_stocks = set(stock.split(':')[0] for stock in player.player_stocks if stock)
            buttons = [[InlineKeyboardButton(text=company, callback_data=f"sell_stocks_{company}")] for company in owned_stocks]
            markup = InlineKeyboardMarkup(inline_keyboard=buttons)
            await self.bot.send_message(message.chat.id, "Выберите свою компанию:", reply_markup=markup)

        # Stock purchase callbacks — FSM for quantity input
        @self.router.callback_query(F.data.startswith("buy_stocks_"))
        async def handle_company_selection(call: CallbackQuery, state: FSMContext):
            """Handle company selection for stock purchase"""
            parts = safe_split_callback(call.data, "_", 3)
            if not parts:
                await call.answer("Неверный формат данных")
                return
            company = parts[2]
            await call.answer()
            await state.set_state(ShopStates.waiting_buy_quantity)
            await state.update_data(company=company)
            await self.bot.send_message(call.message.chat.id, f"Сколько акций компании {company} вы хотите купить?")

        @self.router.callback_query(F.data.startswith("sell_stocks_"))
        async def handle_sell_company_selection(call: CallbackQuery, state: FSMContext):
            """Handle company selection for stock sale"""
            parts = safe_split_callback(call.data, "_", 3)
            if not parts:
                await call.answer("Неверный формат данных")
                return
            company = parts[2]
            await call.answer()
            await state.set_state(ShopStates.waiting_sell_quantity)
            await state.update_data(company_to_sell=company)
            await self.bot.send_message(call.message.chat.id, f"Сколько акций компании {company} вы хотите продать?")

        # Stock quantity input handlers (FSM states)
        @self.router.message(ShopStates.waiting_buy_quantity, F.text.regexp(r'^\d+$'))
        async def handle_quantity_selection(message: Message, state: FSMContext):
            """Handle stock purchase quantity input"""
            data = await state.get_data()
            await state.clear()
            try:
                quantity = int(message.text)
                company = data['company']

                player = await asyncio.to_thread(self.player_service.get_player, message.from_user.id)
                if not player:
                    await message.reply("Игрок не найден")
                    return

                conn = self.player_service.get_connection()
                cursor = conn.cursor()

                cursor.execute("SELECT price FROM stocks WHERE company_name = %s", (company,))
                result = cursor.fetchone()
                if not result:
                    await message.reply(f"Company {company} not found.")
                    return

                stock_price = result[0]
                total_cost = stock_price * quantity

                if player.coins < total_cost:
                    await message.reply(f"Недостаточно BTC для покупки. Надо {total_cost} BTC")
                    return

                if not hasattr(player, 'player_stocks'):
                    player.player_stocks = []

                player_stocks_set = set(player.player_stocks)
                updated_stocks, cost = self.stock_service.process_stock_transaction(
                    player_stocks_set, company, quantity, stock_price, True
                )

                player.spend_coins(int(cost))
                player.player_stocks = list(updated_stocks)
                await asyncio.to_thread(self.player_service.save_player, player)

                cursor.close()
                conn.close()

                await message.reply(f"Мои поздравления! Вы купили {quantity} акций компании {company}.")

            except Exception as e:
                await message.reply(f"An error occurred: {str(e)}")

        @self.router.message(ShopStates.waiting_sell_quantity, F.text.regexp(r'^\d+$'))
        async def handle_sell_quantity_selection(message: Message, state: FSMContext):
            """Handle stock sale quantity input"""
            data = await state.get_data()
            await state.clear()
            try:
                quantity = int(message.text)
                company = data['company_to_sell']

                player = await asyncio.to_thread(self.player_service.get_player, message.from_user.id)
                if not player:
                    await message.reply("Игрок не найден")
                    return

                user_stock = next((stock for stock in player.player_stocks if stock.startswith(company)), None)
                if not user_stock:
                    await message.reply(f"У вас нет акций компании {company}")
                    return

                stock_parts = user_stock.split(':')
                if len(stock_parts) < 2:
                    logger.error(f"Invalid stock format: {user_stock}")
                    await message.reply("Ошибка формата данных акций")
                    return
                current_quantity = safe_int(stock_parts[1], 0)
                if quantity > current_quantity:
                    await message.reply(f"У вас нет столько акций. У вас {current_quantity} акций.")
                    return

                conn = self.player_service.get_connection()
                cursor = conn.cursor()

                cursor.execute("SELECT price FROM stocks WHERE company_name = %s", (company,))
                result = cursor.fetchone()
                if not result:
                    await message.reply(f"Company {company} not found.")
                    return

                current_price = result[0]

                player_stocks_set = set(player.player_stocks)
                updated_stocks, earnings = self.stock_service.process_stock_transaction(
                    player_stocks_set, company, quantity, current_price, False
                )

                player.add_coins(int(abs(earnings)))
                player.player_stocks = list(updated_stocks)
                await asyncio.to_thread(self.player_service.save_player, player)

                cursor.close()
                conn.close()

                await message.reply(f"Вы успешно продали {quantity} акций компании {company}.\nИ вы заработали: {abs(earnings)}")

            except Exception as e:
                await message.reply(f"An error occurred: {str(e)}")

    async def _handle_all_statuetki_collected(self, player, message):
        """Handle special event when player collects all statuetki"""
        try:
            with open('/home/spedymax/tg-bot/assets/data/plot.json', 'r', encoding='utf-8') as f:
                plot_data = json.load(f)

            with open('/home/spedymax/tg-bot/assets/data/char.json', 'r', encoding='utf-8') as f:
                char_data = json.load(f)

            story_lines = plot_data.get('strochki2', [])

            for i, line in enumerate(story_lines):
                await self.bot.send_message(message.chat.id, line)
                if "яркая вспышка" in line.lower() or "ослепляет" in line.lower():
                    await asyncio.sleep(3)
                elif "..." in line or "...." in line:
                    await asyncio.sleep(2)
                elif i < len(story_lines) - 2:
                    await asyncio.sleep(1.5)

            player.statuetki.clear()

            available_characteristics = list(char_data['description'].keys())

            if not hasattr(player, 'characteristics') or player.characteristics is None:
                player.characteristics = []

            existing_characteristics = []
            for char in player.characteristics:
                parts = char.split(':')
                if parts:
                    existing_characteristics.append(parts[0])

            available_characteristics = [char for char in available_characteristics if char not in existing_characteristics]

            if not available_characteristics:
                selected_characteristic = random.choice(list(char_data['description'].keys()))
                for i, char in enumerate(player.characteristics):
                    parts = char.split(':')
                    if len(parts) >= 2:
                        char_name = parts[0]
                        level = safe_int(parts[1], 1)
                        if char_name == selected_characteristic:
                            player.characteristics[i] = f"{char_name}:{level + 1}"
                            break
            else:
                selected_characteristic = random.choice(available_characteristics)
                new_characteristic = f"{selected_characteristic}:1"
                player.characteristics.append(new_characteristic)

            await asyncio.to_thread(self.player_service.save_player, player)

            characteristic_description = char_data['description'][selected_characteristic]
            final_message = f"🎉 Поздравляем! Вы получили новую характеристику: **{selected_characteristic}**\n\n"
            final_message += f"📝 Описание: {characteristic_description}\n\n"
            final_message += "✨ Используйте /characteristics чтобы посмотреть все ваши характеристики!"

            await self.bot.send_message(message.chat.id, final_message, parse_mode='Markdown')

        except FileNotFoundError as e:
            await self.bot.send_message(message.chat.id, f"Ошибка: не удалось найти файл данных - {str(e)}")
        except Exception as e:
            await self.bot.send_message(message.chat.id, f"Произошла ошибка во время особого события: {str(e)}")
            player.statuetki.clear()
            await asyncio.to_thread(self.player_service.save_player, player)
