from aiogram import Router, F, Bot
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from config.settings import Settings
import json
from datetime import datetime, timedelta
import socket
from struct import pack
import google.generativeai as genai
import httpx
import logging
import asyncio

from states.registration import RegistrationStates

logger = logging.getLogger(__name__)


class AdminHandlers:
    def __init__(self, bot: Bot, player_service, game_service):
        self.bot = bot
        self.player_service = player_service
        self.game_service = game_service
        self.admin_actions = {}
        self.quiz_scheduler = None  # Will be set by main.py
        self.router = Router()

        # Initialize Gemini for message analysis
        if Settings.GEMINI_API_KEY:
            genai.configure(api_key=Settings.GEMINI_API_KEY)
            self.gemini_model = genai.GenerativeModel('gemini-3-flash-preview')
        else:
            self.gemini_model = None
            logger.warning("GEMINI_API_KEY not found, sho_tam_novogo feature will be disabled")

        # Create messages table if it doesn't exist (scheduled as async task)
        asyncio.ensure_future(self._create_messages_table())

        self._register()

    def set_quiz_scheduler(self, quiz_scheduler):
        """Set the quiz scheduler instance"""
        self.quiz_scheduler = quiz_scheduler

    async def _create_messages_table(self):
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
            await self.player_service.db.execute_query(query)
            # Add message_id column if it doesn't exist yet (migration for existing installs)
            await self.player_service.db.execute_query("""
                ALTER TABLE messages ADD COLUMN IF NOT EXISTS message_id BIGINT
            """)
            logger.info("Messages table created/verified successfully")
        except Exception as e:
            logger.error(f"Error creating messages table: {e}")

    async def _store_message(self, message: Message):
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
                await self.player_service.db.execute_query(query, params)
        except Exception as e:
            logger.error(f"Error storing message: {e}")

    async def _get_recent_messages(self, hours=12, limit=100):
        """Get recent messages from the database"""
        try:
            query = """
                SELECT name, message_text, timestamp
                FROM messages
                WHERE timestamp > NOW() - INTERVAL '1 hour' * %s
                ORDER BY timestamp DESC
                LIMIT %s
            """
            params = (hours, limit)
            results = await self.player_service.db.execute_query(query, params)

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
            logger.error(f"Wake-on-LAN error: {e}")
            return False

    def _register(self):
        """Register all handlers on self.router (replaces setup_priority_handlers + setup_handlers)."""

        # ── /start — registration FSM ─────────────────────────────────────────

        @self.router.message(Command('start'))
        async def cmd_start(message: Message, state: FSMContext):
            """Show profile or start registration flow."""
            player = await self.player_service.get_player(message.from_user.id)
            if player:
                await message.reply(
                    f"🎮 Ваш профиль:\n"
                    f"📏 Писюнчик: {player.pisunchik_size} см\n"
                    f"💰 BTC: {player.coins:.4f}\n"
                    f"🏆 Статуэтки: {len(player.statuetki)}"
                )
            else:
                await message.reply("Добро пожаловать! Напишите ваше имя:")
                await state.set_state(RegistrationStates.waiting_name)

        @self.router.message(RegistrationStates.waiting_name)
        async def handle_registration_name(message: Message, state: FSMContext):
            """Collect player name during registration."""
            await state.update_data(name=message.text.strip())
            await message.reply("Расскажите как вы нашли этого бота?")
            await state.set_state(RegistrationStates.waiting_how_found)

        @self.router.message(RegistrationStates.waiting_how_found)
        async def handle_registration_how_found(message: Message, state: FSMContext):
            """Collect 'how found' answer and send approval request to admin."""
            data = await state.get_data()
            name = data.get('name', message.from_user.first_name or 'Аноним')
            how_found = message.text.strip()
            await state.clear()

            user = message.from_user
            # Send approval request to admin
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Принять",
                        callback_data=f"reg_approve_{user.id}_{name[:30]}"
                    ),
                    InlineKeyboardButton(
                        text="❌ Отклонить",
                        callback_data=f"reg_reject_{user.id}"
                    ),
                ]
            ])
            admin_text = (
                f"🆕 Новый игрок хочет зарегистрироваться:\n"
                f"👤 {user.first_name} (@{user.username})\n"
                f"🆔 ID: {user.id}\n"
                f"📝 Имя: {name}\n"
                f"❓ Как нашёл: {how_found}"
            )
            for admin_id in Settings.ADMIN_IDS:
                try:
                    await self.bot.send_message(admin_id, admin_text, reply_markup=markup)
                except Exception as e:
                    logger.error(f"Failed to notify admin {admin_id}: {e}")

            await message.reply(
                "✅ Ваша заявка отправлена на рассмотрение администратору. Ожидайте одобрения!"
            )

        @self.router.callback_query(F.data.startswith("reg_approve_"))
        async def handle_reg_approve(call: CallbackQuery):
            """Admin approves a registration request."""
            if call.from_user.id not in Settings.ADMIN_IDS:
                await call.answer("Нет доступа.")
                return
            # Format: reg_approve_{user_id}_{name}
            parts = call.data[len("reg_approve_"):].split("_", 1)
            user_id = int(parts[0])
            name = parts[1] if len(parts) > 1 else "Игрок"

            existing = await self.player_service.get_player(user_id)
            if existing:
                await call.answer("Игрок уже зарегистрирован.")
                await call.message.edit_text(call.message.text + "\n\n✅ Уже зарегистрирован.")
                return

            from models.player import Player
            new_player = Player(
                player_id=user_id,
                player_name=name,
                chat_id=[call.message.chat.id],
            )
            ok = await self.player_service.save_player(new_player)
            if ok:
                await call.answer("Игрок добавлен!")
                await call.message.edit_text(call.message.text + f"\n\n✅ Принят как '{name}'.")
                try:
                    await self.bot.send_message(
                        user_id,
                        f"🎉 Вы успешно зарегистрированы как игрок '{name}'!\n"
                        f"Используйте /pisunchik чтобы начать игру."
                    )
                except Exception as e:
                    logger.error(f"Could not notify new player {user_id}: {e}")
            else:
                await call.answer("Ошибка при сохранении.")
                await call.message.edit_text(call.message.text + "\n\n❌ Ошибка при сохранении.")

        @self.router.callback_query(F.data.startswith("reg_reject_"))
        async def handle_reg_reject(call: CallbackQuery):
            """Admin rejects a registration request."""
            if call.from_user.id not in Settings.ADMIN_IDS:
                await call.answer("Нет доступа.")
                return
            user_id = int(call.data[len("reg_reject_"):])
            await call.answer("Отклонено.")
            await call.message.edit_text(call.message.text + "\n\n❌ Отклонено.")
            try:
                await self.bot.send_message(
                    user_id,
                    "❌ К сожалению, ваша заявка на регистрацию была отклонена."
                )
            except Exception as e:
                logger.error(f"Could not notify rejected user {user_id}: {e}")

        # ── /cancel — abort any pending admin action ───────────────────────────

        @self.router.message(Command('cancel'))
        async def cancel_admin_action(message: Message):
            """Cancel current pending admin action."""
            if message.from_user.id in self.admin_actions:
                del self.admin_actions[message.from_user.id]
                await message.reply("❌ Действие отменено.")

        # ── Admin text input (dict-based multi-step flow) ─────────────────────
        # StateFilter(None) ensures FSM states (shop, court, registration) take priority.

        @self.router.message(StateFilter(None), F.func(lambda m: m.from_user.id in self.admin_actions))
        async def handle_admin_text_input(message: Message):
            """Handle text input for admin actions."""
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
                all_players = await self.player_service.get_all_players()
                for player_id, player in all_players.items():
                    try:
                        if player.chat_id:
                            for chat in player.chat_id:
                                await self.bot.send_message(chat, f"📢 Объявление:\n\n{text}")
                                success_count += 1
                    except Exception as e:
                        fail_count += 1
                        logger.error(f"Failed to send broadcast to {player_id}: {e}")
                await message.reply(
                    f"📢 Рассылка завершена\n✅ Успешно: {success_count}\n❌ Неудачно: {fail_count}"
                )
                del self.admin_actions[message.from_user.id]
                return

            # --- Step 1: get numeric amount ---
            if step == "waiting_amount":
                try:
                    amount = float(text.lstrip("+"))
                except ValueError:
                    await message.reply("❌ Введите число.\n\n/cancel — отмена")
                    return

                player = await self.player_service.get_player(user_action["player_id"])
                if not player:
                    await message.reply("❌ Игрок не найден.")
                    del self.admin_actions[message.from_user.id]
                    return

                if action == "increasePisunchik":
                    player.pisunchik_size += int(amount)
                    ok = await self.player_service.save_player(player)
                    await message.reply(
                        f"✅ Писюнчик {player.player_name}: +{int(amount)} см → {player.pisunchik_size} см"
                        if ok else "❌ Ошибка при сохранении."
                    )

                elif action == "decreasePisunchik":
                    player.pisunchik_size -= int(amount)
                    ok = await self.player_service.save_player(player)
                    await message.reply(
                        f"✅ Писюнчик {player.player_name}: -{int(amount)} см → {player.pisunchik_size} см"
                        if ok else "❌ Ошибка при сохранении."
                    )

                elif action == "increaseBtc":
                    player.add_coins(amount)
                    ok = await self.player_service.save_player(player)
                    await message.reply(
                        f"✅ +{amount:.4f} BTC → {player.player_name} имеет {player.coins:.4f} BTC"
                        if ok else "❌ Ошибка при сохранении."
                    )

                elif action == "decreaseBtc":
                    player.coins = max(0.0, player.coins - amount)
                    ok = await self.player_service.save_player(player)
                    await message.reply(
                        f"✅ -{amount:.4f} BTC → {player.player_name} имеет {player.coins:.4f} BTC"
                        if ok else "❌ Ошибка при сохранении."
                    )

                elif action == "quizPoints":
                    delta = int(amount)
                    quiz_chat = user_action.get("quiz_chat_id", message.chat.id)
                    current = player.get_quiz_score(quiz_chat)
                    new_score = max(0, current + delta)
                    player.update_quiz_score(quiz_chat, new_score)
                    ok = await self.player_service.save_player(player)
                    sign = "+" if delta >= 0 else ""
                    await message.reply(
                        f"✅ Квиз {player.player_name}: {current} → {new_score} ({sign}{delta})"
                        if ok else "❌ Ошибка при сохранении."
                    )

                del self.admin_actions[message.from_user.id]

            # --- Step 2: get quantity for item actions ---
            elif step == "waiting_quantity":
                try:
                    quantity = int(text)
                    if quantity < 1:
                        raise ValueError
                except ValueError:
                    await message.reply("❌ Введите целое число больше 0.\n\n/cancel — отмена")
                    return

                item_name = user_action.get("item_name", "")
                player = await self.player_service.get_player(user_action["player_id"])
                if not player:
                    await message.reply("❌ Игрок не найден.")
                    del self.admin_actions[message.from_user.id]
                    return

                if action == "addItem":
                    for _ in range(quantity):
                        player.add_item(item_name)
                    ok = await self.player_service.save_player(player)
                    await message.reply(
                        f"✅ Добавлено {quantity}x {item_name} игроку {player.player_name}"
                        if ok else "❌ Ошибка при сохранении."
                    )

                elif action == "removeItem":
                    removed = sum(1 for _ in range(quantity) if player.remove_item(item_name))
                    if removed == 0:
                        await message.reply(f"❌ Предмет '{item_name}' не найден у {player.player_name}")
                    else:
                        ok = await self.player_service.save_player(player)
                        await message.reply(
                            f"✅ Удалено {removed}x {item_name} у {player.player_name}"
                            if ok else "❌ Ошибка при сохранении."
                        )

                elif action == "addStatue":
                    for _ in range(quantity):
                        player.statuetki.append(item_name)
                    ok = await self.player_service.save_player(player)
                    await message.reply(
                        f"✅ Добавлено {quantity}x '{item_name}' игроку {player.player_name}"
                        if ok else "❌ Ошибка при сохранении."
                    )

                del self.admin_actions[message.from_user.id]

        # ── /admin panel ──────────────────────────────────────────────────────

        @self.router.message(Command('admin'))
        async def admin_panel(message: Message):
            """Handle admin panel command."""
            if message.from_user.id not in Settings.ADMIN_IDS:
                await message.reply("У вас нет доступа к админ-панели.")
                return
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="👤 Управление игроками", callback_data="admin_playerManagement"),
                    InlineKeyboardButton(text="💰 Экономика", callback_data="admin_economy"),
                ],
                [
                    InlineKeyboardButton(text="🎁 Предметы", callback_data="admin_items"),
                    InlineKeyboardButton(text="⚙️ Система", callback_data="admin_system"),
                ],
            ])
            await self.bot.send_message(message.chat.id, "🎮 Админ-панель\nВыберите категорию:", reply_markup=markup)

        # ── Admin category callbacks ───────────────────────────────────────────

        @self.router.callback_query(
            F.data.startswith("admin_"),
            ~F.data.startswith("admin_selectPlayer_"),
            ~F.data.startswith("admin_item::"),
        )
        async def handle_admin_categories(call: CallbackQuery):
            """Handle admin category selection."""
            if call.from_user.id not in Settings.ADMIN_IDS:
                await call.answer("У вас нет доступа к админ-панели.")
                return

            category = call.data.split("_")[1]

            if category == "playerManagement":
                buttons = [
                    [InlineKeyboardButton(text="➕ Увеличить писюнчик", callback_data="action_increasePisunchik"),
                     InlineKeyboardButton(text="➖ Уменьшить писюнчик", callback_data="action_decreasePisunchik")],
                    [InlineKeyboardButton(text="🔄 Сбросить кулдаун", callback_data="action_resetCooldown"),
                     InlineKeyboardButton(text="📊 Статистика игрока", callback_data="action_playerStats")],
                    [InlineKeyboardButton(text="🧠 Изменить очки квиза", callback_data="action_quizPoints")],
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")],
                ]
                await call.message.edit_text(
                    "👤 Управление игроками\nВыберите действие:",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
                )

            elif category == "economy":
                buttons = [
                    [InlineKeyboardButton(text="➕ Добавить BTC", callback_data="action_increaseBtc"),
                     InlineKeyboardButton(text="➖ Убрать BTC", callback_data="action_decreaseBtc")],
                    [InlineKeyboardButton(text="💱 Управление акциями", callback_data="action_manageStocks")],
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")],
                ]
                await call.message.edit_text(
                    "💰 Управление экономикой\nВыберите действие:",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
                )

            elif category == "items":
                buttons = [
                    [InlineKeyboardButton(text="➕ Добавить предмет", callback_data="action_addItem"),
                     InlineKeyboardButton(text="➖ Убрать предмет", callback_data="action_removeItem")],
                    [InlineKeyboardButton(text="🏆 Добавить статуэтку", callback_data="action_addStatue")],
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")],
                ]
                await call.message.edit_text(
                    "🎁 Управление предметами\nВыберите действие:",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
                )

            elif category == "system":
                buttons = [
                    [InlineKeyboardButton(text="🔄 Перезапуск бота", callback_data="action_restartBot"),
                     InlineKeyboardButton(text="💾 Бэкап данных", callback_data="action_backupData")],
                    [InlineKeyboardButton(text="📢 Рассылка", callback_data="action_broadcast"),
                     InlineKeyboardButton(text="💻 Включить ПК", callback_data="action_wakePc")],
                    [InlineKeyboardButton(text="😴 Выключить ПК", callback_data="action_sleepPc"),
                     InlineKeyboardButton(text="🧠 Управление квизами", callback_data="admin_quizManagement")],
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")],
                ]
                await call.message.edit_text(
                    "⚙️ Системные функции\nВыберите действие:",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
                )

            elif category == "quizManagement":
                buttons = [
                    [InlineKeyboardButton(text="▶️ Запустить планировщик", callback_data="action_startQuizScheduler"),
                     InlineKeyboardButton(text="⏹️ Остановить планировщик", callback_data="action_stopQuizScheduler")],
                    [InlineKeyboardButton(text="📊 Статус планировщика", callback_data="action_quizSchedulerStatus"),
                     InlineKeyboardButton(text="🎯 Отправить квиз сейчас", callback_data="action_sendQuizNow")],
                    [InlineKeyboardButton(text="🔄 Пополнить пул (5 вопросов)", callback_data="action_regenQuestions")],
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_system")],
                ]
                await call.message.edit_text(
                    "🧠 Управление квизами\nВыберите действие:",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
                )

            elif category == "back":
                markup = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text="👤 Управление игроками", callback_data="admin_playerManagement"),
                        InlineKeyboardButton(text="💰 Экономика", callback_data="admin_economy"),
                    ],
                    [
                        InlineKeyboardButton(text="🎁 Предметы", callback_data="admin_items"),
                        InlineKeyboardButton(text="⚙️ Система", callback_data="admin_system"),
                    ],
                ])
                await call.message.edit_text(
                    "🎮 Админ-панель\nВыберите категорию:",
                    reply_markup=markup
                )

        # ── Action callbacks ───────────────────────────────────────────────────

        @self.router.callback_query(F.data.startswith("action_"))
        async def handle_admin_actions(call: CallbackQuery):
            """Handle admin action selection."""
            if call.from_user.id not in Settings.ADMIN_IDS:
                await call.answer("Нет доступа.")
                return

            action = call.data.split("_")[1]

            if action == "wakePc":
                try:
                    from services.ollama_wake_manager import OllamaWakeManager
                    wake_manager = OllamaWakeManager()
                    wake_manager.trigger_wake()
                    await call.message.edit_text("✅ WoL пакет отправлен, ПК просыпается (~1–3 мин).")
                except Exception as e:
                    await call.message.edit_text(f"❌ Ошибка: {str(e)}")

            elif action == "sleepPc":
                try:
                    from services.ollama_wake_manager import OllamaWakeManager
                    wake_manager = OllamaWakeManager()
                    await call.message.edit_text("😴 Отправляю команду сна...")
                    wake_manager.sleep_pc()
                    await call.message.edit_text("😴 Команда отправлена, ПК засыпает.")
                except Exception as e:
                    await call.message.edit_text(f"❌ Ошибка: {str(e)}")

            elif action == "startQuizScheduler":
                if self.quiz_scheduler:
                    try:
                        self.quiz_scheduler.start_scheduler()
                        await call.message.edit_text(
                            "✅ Планировщик квизов запущен! Квизы будут отправляться в 12:00, 16:00 и 20:00."
                        )
                    except Exception as e:
                        await call.message.edit_text(f"❌ Ошибка при запуске планировщика: {str(e)}")
                else:
                    await call.message.edit_text("❌ Планировщик квизов не инициализирован.")

            elif action == "stopQuizScheduler":
                if self.quiz_scheduler:
                    try:
                        self.quiz_scheduler.stop_scheduler()
                        await call.message.edit_text("⏹️ Планировщик квизов остановлен.")
                    except Exception as e:
                        await call.message.edit_text(f"❌ Ошибка при остановке планировщика: {str(e)}")
                else:
                    await call.message.edit_text("❌ Планировщик квизов не инициализирован.")

            elif action == "quizSchedulerStatus":
                if self.quiz_scheduler:
                    try:
                        status = self.quiz_scheduler.get_schedule_info()
                        status_text = (
                            f"📊 Статус планировщика квизов:\n\n"
                            f"🔄 Работает: {'Да' if status['is_running'] else 'Нет'}\n"
                            f"⏰ Времена квизов: {', '.join(status['quiz_times'])}\n"
                            f"📱 Целевой чат: {status['target_chat_id']}\n"
                            f"⏳ Следующий квиз: {status['next_run']}"
                        )
                        await call.message.edit_text(status_text)
                    except Exception as e:
                        await call.message.edit_text(f"❌ Ошибка при получении статуса: {str(e)}")
                else:
                    await call.message.edit_text("❌ Планировщик квизов не инициализирован.")

            elif action == "sendQuizNow":
                if self.quiz_scheduler:
                    try:
                        result = self.quiz_scheduler.manual_quiz()
                        if result['success']:
                            await call.message.edit_text("✅ Квиз отправлен в целевой чат!")
                        else:
                            await call.message.edit_text(f"❌ Ошибка при отправке квиза: {result['message']}")
                    except Exception as e:
                        await call.message.edit_text(f"❌ Ошибка при отправке квиза: {str(e)}")
                else:
                    await call.message.edit_text("❌ Планировщик квизов не инициализирован.")

            elif action == "regenQuestions":
                if self.quiz_scheduler:
                    try:
                        await call.message.edit_text("🔄 Генерирую 5 вопросов для пула, подождите...")
                        result = await self.quiz_scheduler.refill_question_pool(5)
                        await call.message.edit_text(
                            f"✅ Готово!\n\n"
                            f"Добавлено в пул: {result['added']}\n"
                            f"Пропущено (дубли/ошибки): {result['skipped']}"
                        )
                    except Exception as e:
                        await call.message.edit_text(f"❌ Ошибка при генерации вопросов: {str(e)}")
                else:
                    await call.message.edit_text("❌ Планировщик квизов не инициализирован.")

            elif action == "backupData":
                try:
                    all_players = await self.player_service.get_all_players()
                    backup_time = datetime.now().strftime("%Y%m%d_%H%M%S")
                    backup_filename = f"backup_{backup_time}.json"

                    backup_data = {}
                    for player_id, player in all_players.items():
                        backup_data[str(player_id)] = player.to_db_dict()

                    with open(backup_filename, 'w', encoding='utf-8') as f:
                        json.dump(backup_data, f, ensure_ascii=False, indent=4, default=str)

                    await call.message.edit_text(f"✅ Бэкап успешно создан: {backup_filename}")
                except Exception as e:
                    await call.message.edit_text(f"❌ Ошибка при создании бэкапа: {str(e)}")

            elif action == "broadcast":
                self.admin_actions[call.from_user.id] = {"action": "broadcast"}
                await call.message.edit_text("Введите сообщение для рассылки всем игрокам:")

            elif action == "restartBot":
                import os, sys
                await call.message.edit_text("🔄 Перезапускаю бота...")
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
                all_players = await self.player_service.get_all_players()
                player_buttons = [
                    [InlineKeyboardButton(
                        text=p.player_name,
                        callback_data=f"admin_selectPlayer_{action}_{pid}"
                    )]
                    for pid, p in all_players.items()
                ]
                player_buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back")])
                await call.message.edit_text(
                    f"🎯 {action_labels.get(action, action)}\n\nВыберите игрока:",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=player_buttons)
                )

        # ── Player selection callbacks ─────────────────────────────────────────

        @self.router.callback_query(F.data.startswith("admin_selectPlayer_"))
        async def handle_player_selection(call: CallbackQuery):
            """Handle player selection from inline keyboard for admin actions."""
            if call.from_user.id not in Settings.ADMIN_IDS:
                await call.answer("Нет доступа.")
                return
            # Format: admin_selectPlayer_{action}_{player_id}
            remainder = call.data[len("admin_selectPlayer_"):]
            action, player_id_str = remainder.rsplit("_", 1)
            player_id = int(player_id_str)
            player = await self.player_service.get_player(player_id)
            if not player:
                await call.answer("Игрок не найден.")
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
                await call.message.edit_text(stats)

            elif action == "resetCooldown":
                from datetime import timezone
                player.last_used = datetime.min.replace(tzinfo=timezone.utc)
                ok = await self.player_service.save_player(player)
                await call.message.edit_text(
                    f"✅ Кулдаун {player.player_name} сброшен." if ok else "❌ Ошибка при сохранении."
                )

            elif action in ("increasePisunchik", "decreasePisunchik"):
                self.admin_actions[call.from_user.id] = {
                    "action": action, "player_id": player_id, "step": "waiting_amount"
                }
                await call.message.edit_text(
                    f"✅ {player.player_name} (сейчас {player.pisunchik_size} см)\n\nВведите количество см:\n\n/cancel — отмена"
                )

            elif action in ("increaseBtc", "decreaseBtc"):
                self.admin_actions[call.from_user.id] = {
                    "action": action, "player_id": player_id, "step": "waiting_amount"
                }
                await call.message.edit_text(
                    f"✅ {player.player_name} (сейчас {player.coins:.4f} BTC)\n\nВведите количество BTC:\n\n/cancel — отмена"
                )

            elif action == "quizPoints":
                current_score = player.get_quiz_score(call.message.chat.id)
                self.admin_actions[call.from_user.id] = {
                    "action": action, "player_id": player_id, "step": "waiting_amount",
                    "quiz_chat_id": call.message.chat.id
                }
                await call.message.edit_text(
                    f"✅ {player.player_name} (сейчас {current_score} очков)\n\nВведите изменение (например: 5 или -3):\n\n/cancel — отмена"
                )

            elif action == "addItem":
                try:
                    with open('/home/spedymax/tg-bot/assets/data/shop.json', 'r', encoding='utf-8') as f:
                        shop_data = json.load(f)
                    item_names = shop_data.get("names", {})
                except Exception:
                    item_names = {}
                item_buttons = [
                    [InlineKeyboardButton(text=item_label, callback_data=f"admin_item::{item_key}")]
                    for item_key, item_label in item_names.items()
                ]
                item_buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back")])
                self.admin_actions[call.from_user.id] = {
                    "action": action, "player_id": player_id, "step": "waiting_item_selection"
                }
                await call.message.edit_text(
                    f"✅ {player.player_name}\n\nВыберите предмет:",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=item_buttons)
                )

            elif action == "removeItem":
                unique_items = list(dict.fromkeys(player.items))
                if not unique_items:
                    await call.answer("У игрока нет предметов.")
                    return
                try:
                    with open('/home/spedymax/tg-bot/assets/data/shop.json', 'r', encoding='utf-8') as f:
                        shop_data = json.load(f)
                    item_names = shop_data.get("names", {})
                except Exception:
                    item_names = {}
                item_buttons = [
                    [InlineKeyboardButton(text=item_names.get(item_key, item_key), callback_data=f"admin_item::{item_key}")]
                    for item_key in unique_items
                ]
                item_buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back")])
                self.admin_actions[call.from_user.id] = {
                    "action": action, "player_id": player_id, "step": "waiting_item_selection"
                }
                await call.message.edit_text(
                    f"✅ {player.player_name}\n\nВыберите предмет для удаления:",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=item_buttons)
                )

            elif action == "addStatue":
                try:
                    with open('/home/spedymax/tg-bot/assets/data/statuetki.json', 'r', encoding='utf-8') as f:
                        stat_data = json.load(f)
                    statue_names = list(stat_data.get("prices", {}).keys())
                except Exception:
                    statue_names = []
                statue_buttons = [
                    [InlineKeyboardButton(text=name, callback_data=f"admin_item::{name}")]
                    for name in statue_names
                ]
                statue_buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back")])
                self.admin_actions[call.from_user.id] = {
                    "action": action, "player_id": player_id, "step": "waiting_item_selection"
                }
                await call.message.edit_text(
                    f"✅ {player.player_name}\n\nВыберите статуэтку:",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=statue_buttons)
                )

        # ── Item selection callbacks ───────────────────────────────────────────

        @self.router.callback_query(F.data.startswith("admin_item::"))
        async def handle_item_selection(call: CallbackQuery):
            """Handle item selection from inline keyboard."""
            if call.from_user.id not in Settings.ADMIN_IDS:
                await call.answer("Нет доступа.")
                return
            user_action = self.admin_actions.get(call.from_user.id)
            if not user_action or user_action.get("step") != "waiting_item_selection":
                await call.answer("Нет активного действия.")
                return
            item_name = call.data[len("admin_item::"):]
            user_action["item_name"] = item_name
            user_action["step"] = "waiting_quantity"
            await call.message.edit_text(
                f"✅ Выбрано: {item_name}\n\nВведите количество (число):\n\n/cancel — отмена"
            )

        # ── /giveChar ─────────────────────────────────────────────────────────

        @self.router.message(Command('giveChar'))
        async def add_characteristic_command(message: Message):
            """Give random characteristic to player."""
            if message.from_user.id not in Settings.ADMIN_IDS:
                await message.reply("У вас нет доступа к этой команде.")
                return
            player = await self.player_service.get_player(message.from_user.id)
            if player:
                await message.reply("Характеристика добавлена!")
            else:
                await message.reply(f"Игрок с ID {message.from_user.id} не найден")

        # ── /sho_tam_novogo ───────────────────────────────────────────────────

        @self.router.message(Command('sho_tam_novogo'))
        async def analyze_recent_messages_command(message: Message):
            """Analyze recent chat messages with Qwen AI."""
            if message.from_user.id not in Settings.ADMIN_IDS:
                await message.reply("У вас нет доступа к этой команде.")
                return
            try:
                waiting_msg = await message.reply("🔍 Анализирую сообщения за последние 12 часов...")
                messages = await self._get_recent_messages(12, 100)
                analysis = await asyncio.to_thread(self._analyze_messages_with_qwen, messages)
                await self.bot.edit_message_text(
                    analysis,
                    waiting_msg.chat.id,
                    waiting_msg.message_id
                )
            except Exception as e:
                logger.error(f"Error in sho_tam_novogo command: {e}")
                await message.reply(f"❌ Ошибка: {str(e)}")

        # ── /metrics ─────────────────────────────────────────────────────────

        @self.router.message(Command('metrics'))
        async def show_metrics(message: Message):
            """Show bot metrics (admin-only)."""
            if message.from_user.id not in Settings.ADMIN_IDS:
                return
            from services.metrics import metrics
            await message.reply(metrics.format_report())

        # ── Catch-all: store non-command messages (StateFilter(None) = no FSM active) ──

        @self.router.message(StateFilter(None), F.text, ~F.text.startswith('/'))
        async def store_message_handler(message: Message):
            """Store NON-COMMAND text messages for later analysis (only when no FSM state is active)."""
            await self._store_message(message)
