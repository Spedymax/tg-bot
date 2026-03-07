import logging
import asyncio
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from typing import Optional
from services.pet_service import PetService
from utils.helpers import escape_html

logger = logging.getLogger(__name__)


class PetHandlers:
    """Handlers for pet system commands and callbacks."""

    def __init__(self, bot, player_service, game_service):
        self.bot = bot
        self.player_service = player_service
        self.game_service = game_service
        self.pet_service = PetService()

        self.router = Router()
        self._register()

    def _register(self):
        """Setup all pet-related command handlers."""

        @self.router.message(Command('pet'))
        async def pet_command(message: Message):
            await self.show_pet_menu(message.chat.id, message.from_user.id)

        @self.router.callback_query(F.data.startswith('pet_'))
        async def pet_callback(call: CallbackQuery):
            await self.handle_pet_callback(call)

    # ──────────────────────────────────────────────
    # Core display
    # ──────────────────────────────────────────────

    async def show_pet_menu(self, chat_id: int, user_id: int, delete_message_id: int = None):
        """Send a fresh pet menu, optionally deleting an old message first."""
        if delete_message_id:
            try:
                await self.bot.delete_message(chat_id, delete_message_id)
            except Exception:
                pass

        player = await asyncio.to_thread(self.player_service.get_player, user_id)
        if not player:
            await self.bot.send_message(chat_id, "Вы не зарегистрированы как игрок.")
            return

        # Apply lazy decay on every pet view
        if player.pet and player.pet.get('is_alive') and player.pet.get('is_locked'):
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            self.pet_service.apply_hunger_decay(player, now)
            self.pet_service.apply_happiness_decay(player, now)
            await asyncio.to_thread(self.player_service.save_player, player)

        pet = getattr(player, 'pet', None)

        if not pet:
            markup = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🥚 Создать питомца", callback_data="pet_create")
            ]])
            await self.bot.send_message(chat_id, "У тебя ещё нет питомца!", reply_markup=markup)
            return

        active_title = getattr(player, 'pet_active_title', None)
        revives_used = getattr(player, 'pet_revives_used', 0)
        streak = getattr(player, 'trivia_streak', 0)

        text = self.pet_service.format_pet_display(pet, active_title, revives_used, streak, player)
        markup = self._get_pet_buttons(pet, player)

        if pet.get('image_file_id'):
            try:
                await self.bot.send_photo(chat_id, pet['image_file_id'], caption=text,
                                          reply_markup=markup, parse_mode='HTML')
                return
            except Exception as e:
                logger.error(f"Error sending pet image: {e}")

        await self.bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')

    def _get_pet_buttons(self, pet: dict, player) -> InlineKeyboardMarkup:
        """Get appropriate buttons based on pet state."""
        rows = []

        if not pet.get('is_alive'):
            # Dead pet
            revives_used = getattr(player, 'pet_revives_used', 0)
            revives_remaining = self.pet_service.max_revives - revives_used
            if revives_remaining <= 0:
                rows.append([InlineKeyboardButton(text="❤️ Возродить (нет возрождений)", callback_data="pet_revive")])
            else:
                rows.append([InlineKeyboardButton(text="❤️ Возродить", callback_data="pet_revive")])
            rows.append([InlineKeyboardButton(text="🗑 Удалить навсегда", callback_data="pet_delete_confirm")])

        elif not pet.get('is_locked'):
            # Initial setup (new, never confirmed)
            rows.append([
                InlineKeyboardButton(text="✏️ Изменить имя", callback_data="pet_name"),
                InlineKeyboardButton(text="🖼 Изменить фото", callback_data="pet_image")
            ])
            rows.append([InlineKeyboardButton(text="✅ Подтвердить", callback_data="pet_confirm")])

        else:
            # Alive and active — customization always available
            rows.append([
                InlineKeyboardButton(text="✏️ Имя", callback_data="pet_name"),
                InlineKeyboardButton(text="🖼 Фото", callback_data="pet_image")
            ])
            pet_titles = getattr(player, 'pet_titles', [])
            if pet_titles:
                rows.append([InlineKeyboardButton(text="🏷 Титулы", callback_data="pet_titles")])
            stage = pet.get('stage', 'egg')
            if self.pet_service.is_ulta_available(player):
                ulta_name = self.pet_service.get_ulta_name(stage)
                rows.append([InlineKeyboardButton(
                    text=f"⚡ {ulta_name}", callback_data="pet_ulta"
                )])
            else:
                stage = player.pet.get('stage', 'egg')
                ulta_name = self.pet_service.get_ulta_name(stage)
                remaining = self.pet_service.get_ulta_cooldown_remaining(player)
                if remaining is not None:
                    total_minutes = int(remaining.total_seconds() // 60)
                    if total_minutes >= 60:
                        time_label = f"через {total_minutes // 60}ч"
                    else:
                        time_label = f"через {total_minutes}м"
                    happiness = getattr(player, 'pet_happiness', 50)
                    suffix = ' 😢' if happiness < 20 else ''
                    label = f"⚡ {ulta_name} ({time_label}){suffix}"
                else:
                    label = f"⚡ {ulta_name} (не готова)"
                rows.append([InlineKeyboardButton(text=label, callback_data="pet_ulta_info")])
            rows.append([InlineKeyboardButton(text="💀 Убить", callback_data="pet_kill_confirm")])
            rows.append([InlineKeyboardButton(text="🍖 Покормить", callback_data="pet_feed")])

        return InlineKeyboardMarkup(inline_keyboard=rows)

    # ──────────────────────────────────────────────
    # Callback routing
    # ──────────────────────────────────────────────

    async def handle_pet_callback(self, call: CallbackQuery):
        """Route pet callbacks to appropriate handlers."""
        user_id = call.from_user.id
        chat_id = call.message.chat.id
        message_id = call.message.message_id
        action = call.data.replace('pet_', '', 1)

        # Title selection by index: pet_title_0, pet_title_1, ...
        if action.startswith('title_') and action != 'titles' and action != 'titles_back':
            try:
                idx = int(action.replace('title_', '', 1))
                await self.select_title(call, idx)
            except ValueError:
                await call.answer("Ошибка выбора титула")
            return

        handlers = {
            'create':         lambda: self.create_pet(call),
            'name':           lambda: self.request_name(call),
            'image':          lambda: self.request_image(call),
            'confirm':        lambda: self.confirm_pet(call),
            'revive':         lambda: self.revive_pet(call),
            'kill_confirm':   lambda: self.show_kill_confirm(call),
            'kill_yes':       lambda: self.kill_pet(call),
            'kill_no':        lambda: self._dismiss_and_reopen(call),
            'delete_confirm': lambda: self.show_delete_confirm(call),
            'delete_yes':     lambda: self.delete_pet(call),
            'delete_no':      lambda: self._dismiss_and_reopen(call),
            'titles':         lambda: self.show_titles(call),
            'titles_back':    lambda: self._dismiss_and_reopen(call),
            'feed':           lambda: self.show_feed_menu(call),
            'feed_basic':     lambda: self.feed_pet(call, 'basic'),
            'feed_deluxe':    lambda: self.feed_pet(call, 'deluxe'),
            'feed_back':      lambda: self._dismiss_and_reopen(call),
            'ulta':           lambda: self.activate_ulta(call),
            'ulta_info':      lambda: self._show_ulta_info(call),
            'oracle_yes':     lambda: self.oracle_confirm(call),
            'oracle_no':      lambda: self.oracle_cancel(call),
        }

        handler = handlers.get(action)
        if handler:
            await handler()
        else:
            await call.answer("Неизвестное действие")

    # ──────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────

    async def _dismiss_and_reopen(self, call: CallbackQuery):
        """Delete current message and reopen pet menu."""
        await self.show_pet_menu(call.message.chat.id, call.from_user.id,
                                 delete_message_id=call.message.message_id)

    async def _replace_with_text(self, call: CallbackQuery, text, markup):
        """Delete current message, send a plain text message."""
        try:
            await self.bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        await self.bot.send_message(call.message.chat.id, text, reply_markup=markup)

    # ──────────────────────────────────────────────
    # Feed
    # ──────────────────────────────────────────────

    async def show_feed_menu(self, call: CallbackQuery):
        """Show food selection menu."""
        user_id = call.from_user.id
        player = await asyncio.to_thread(self.player_service.get_player, user_id)
        if not player or not player.pet:
            await call.answer()
            return

        basic_count = player.items.count('pet_food_basic')
        deluxe_count = player.items.count('pet_food_deluxe')

        if basic_count == 0 and deluxe_count == 0:
            await call.answer("У тебя нет еды для питомца!")
            return

        await call.answer()
        rows = []
        if basic_count > 0:
            rows.append([InlineKeyboardButton(
                text=f"🍖 Корм ({basic_count} шт.) +30 голод",
                callback_data="pet_feed_basic"
            )])
        if deluxe_count > 0:
            rows.append([InlineKeyboardButton(
                text=f"🍗 Деликатес ({deluxe_count} шт.) +60 голод +20 настроение",
                callback_data="pet_feed_deluxe"
            )])
        rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="pet_feed_back")])
        markup = InlineKeyboardMarkup(inline_keyboard=rows)
        await self._replace_with_text(call, "🍽 Чем покормить питомца?", markup)

    async def feed_pet(self, call: CallbackQuery, food_type: str):
        """Feed the pet with selected food item."""
        from datetime import datetime, timezone
        user_id = call.from_user.id
        player = await asyncio.to_thread(self.player_service.get_player, user_id)
        if not player or not player.pet:
            await call.answer("Питомец не найден")
            return

        item_key = 'pet_food_basic' if food_type == 'basic' else 'pet_food_deluxe'
        effects = {
            'pet_food_basic':  {'hunger': 30, 'happiness': 0,  'name': 'Корм'},
            'pet_food_deluxe': {'hunger': 60, 'happiness': 20, 'name': 'Деликатес'},
        }
        effect = effects[item_key]

        if not player.remove_item(item_key):
            await call.answer("Еда не найдена!")
            return

        now = datetime.now(timezone.utc)
        self.pet_service.apply_hunger_decay(player, now)
        player.pet_hunger = min(100, getattr(player, 'pet_hunger', 100) + effect['hunger'])
        if effect['happiness'] > 0:
            player.pet_happiness = min(100, getattr(player, 'pet_happiness', 50) + effect['happiness'])

        await asyncio.to_thread(self.player_service.save_player, player)
        await call.answer(f"🐾 {effect['name']} съеден!")
        await self.show_pet_menu(call.message.chat.id, user_id,
                                 delete_message_id=call.message.message_id)

    # ──────────────────────────────────────────────
    # Pet creation
    # ──────────────────────────────────────────────

    async def create_pet(self, call: CallbackQuery):
        user_id = call.from_user.id
        player = await asyncio.to_thread(self.player_service.get_player, user_id)
        if not player:
            await call.answer("Игрок не найден")
            return

        player.pet = self.pet_service.create_pet("Новый питомец")
        await asyncio.to_thread(self.player_service.save_player, player)
        await call.answer("Питомец создан!")
        await self.show_pet_menu(call.message.chat.id, user_id,
                                 delete_message_id=call.message.message_id)

    # ──────────────────────────────────────────────
    # Name / image customization
    # ──────────────────────────────────────────────

    async def request_name(self, call: CallbackQuery):
        await call.answer()
        await self.bot.send_message(call.message.chat.id, "Напиши новое имя для питомца:")
        # Note: register_next_step_handler is telebot-specific.
        # In aiogram v3 the next message from the user is handled via state machine (FSM).
        # For now we store pending state in a simple dict keyed by user_id.
        self._pending_name[call.from_user.id] = call.message.chat.id

    async def process_name_input(self, message: Message):
        user_id = message.from_user.id
        new_name = message.text.strip()[:50]

        player = await asyncio.to_thread(self.player_service.get_player, user_id)
        if player and player.pet:
            player.pet['name'] = escape_html(new_name)
            await asyncio.to_thread(self.player_service.save_player, player)
            await self.bot.send_message(message.chat.id, f"Имя изменено на: {new_name}")

        await self.show_pet_menu(message.chat.id, user_id)

    async def request_image(self, call: CallbackQuery):
        await call.answer()
        await self.bot.send_message(call.message.chat.id, "Пришли новое фото для питомца:")

    async def process_image_input(self, message: Message):
        user_id = message.from_user.id

        if not message.photo:
            await self.bot.send_message(message.chat.id, "Это не фото. Пришли изображение.")
            return

        file_id = message.photo[-1].file_id
        player = await asyncio.to_thread(self.player_service.get_player, user_id)
        if player and player.pet:
            player.pet['image_file_id'] = file_id
            await asyncio.to_thread(self.player_service.save_player, player)
            await self.bot.send_message(message.chat.id, "Фото обновлено!")

        await self.show_pet_menu(message.chat.id, user_id)

    # ──────────────────────────────────────────────
    # Confirm (initial setup only)
    # ──────────────────────────────────────────────

    async def confirm_pet(self, call: CallbackQuery):
        user_id = call.from_user.id
        player = await asyncio.to_thread(self.player_service.get_player, user_id)
        if player and player.pet:
            player.pet['is_locked'] = True
            await asyncio.to_thread(self.player_service.save_player, player)
            await call.answer("Питомец подтверждён! Теперь он будет расти.")

        await self.show_pet_menu(call.message.chat.id, user_id,
                                 delete_message_id=call.message.message_id)

    # ──────────────────────────────────────────────
    # Revive
    # ──────────────────────────────────────────────

    async def revive_pet(self, call: CallbackQuery):
        user_id = call.from_user.id
        player = await asyncio.to_thread(self.player_service.get_player, user_id)

        if not player or not player.pet:
            await call.answer("Питомец не найден")
            return

        revives_used = getattr(player, 'pet_revives_used', 0)
        reset_date = getattr(player, 'pet_revives_reset_date', None)

        pet, new_revives, new_reset, success = self.pet_service.revive_pet(
            player.pet, revives_used, reset_date
        )

        if success:
            player.pet = pet
            player.pet_revives_used = new_revives
            player.pet_revives_reset_date = new_reset
            await asyncio.to_thread(self.player_service.save_player, player)
            await call.answer("Питомец возрождён!")
        else:
            await call.answer("Нет возрождений на этот месяц!")

        await self.show_pet_menu(call.message.chat.id, user_id,
                                 delete_message_id=call.message.message_id)

    # ──────────────────────────────────────────────
    # Kill
    # ──────────────────────────────────────────────

    async def show_kill_confirm(self, call: CallbackQuery):
        markup = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ Нет, оставить", callback_data="pet_kill_no"),
            InlineKeyboardButton(text="✅ Да, убить", callback_data="pet_kill_yes")
        ]])
        await self._replace_with_text(call, "⚠️ Ты уверен? Питомец умрёт и потребует возрождения!", markup)

    async def kill_pet(self, call: CallbackQuery):
        user_id = call.from_user.id
        player = await asyncio.to_thread(self.player_service.get_player, user_id)
        if player and player.pet:
            player.pet = self.pet_service.kill_pet(player.pet)
            await asyncio.to_thread(self.player_service.save_player, player)
            await call.answer("Питомец умер 💀")

        await self.show_pet_menu(call.message.chat.id, user_id,
                                 delete_message_id=call.message.message_id)

    # ──────────────────────────────────────────────
    # Delete
    # ──────────────────────────────────────────────

    async def show_delete_confirm(self, call: CallbackQuery):
        markup = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ Нет, оставить", callback_data="pet_delete_no"),
            InlineKeyboardButton(text="✅ Да, удалить", callback_data="pet_delete_yes")
        ]])
        await self._replace_with_text(call,
            "⚠️ Ты уверен? Питомец будет удалён НАВСЕГДА! Весь прогресс будет потерян!", markup)

    async def delete_pet(self, call: CallbackQuery):
        user_id = call.from_user.id
        player = await asyncio.to_thread(self.player_service.get_player, user_id)
        if player:
            player.pet = None
            await asyncio.to_thread(self.player_service.save_player, player)
            await call.answer("Питомец удалён")

        await self.show_pet_menu(call.message.chat.id, user_id,
                                 delete_message_id=call.message.message_id)

    # ──────────────────────────────────────────────
    # Titles
    # ──────────────────────────────────────────────

    async def show_titles(self, call: CallbackQuery):
        user_id = call.from_user.id
        player = await asyncio.to_thread(self.player_service.get_player, user_id)

        if not player:
            await call.answer()
            return

        titles = getattr(player, 'pet_titles', [])
        active_title = getattr(player, 'pet_active_title', None)

        if not titles:
            await call.answer("У тебя ещё нет титулов!")
            return

        await call.answer()

        text = "🏷 Твои титулы:\n\n"
        for title in titles:
            marker = " ✅" if title == active_title else ""
            text += f"• {escape_html(title)}{marker}\n"

        # Use index as callback data — avoids UTF-8 byte limit issues
        rows = [
            [InlineKeyboardButton(text=t, callback_data=f"pet_title_{i}")]
            for i, t in enumerate(titles)
        ]
        rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="pet_titles_back")])
        markup = InlineKeyboardMarkup(inline_keyboard=rows)

        try:
            await self.bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        await self.bot.send_message(call.message.chat.id, text, reply_markup=markup)

    async def select_title(self, call: CallbackQuery, idx: int):
        """Activate title by index."""
        user_id = call.from_user.id
        player = await asyncio.to_thread(self.player_service.get_player, user_id)

        if player:
            titles = getattr(player, 'pet_titles', [])
            if 0 <= idx < len(titles):
                title = titles[idx]
                player.pet_active_title = title
                await asyncio.to_thread(self.player_service.save_player, player)
                await call.answer(f"Титул «{title}» активирован!")
            else:
                await call.answer("Титул не найден")
        else:
            await call.answer()

        await self.show_titles(call)

    # ──────────────────────────────────────────────
    # Ulta system
    # ──────────────────────────────────────────────

    async def activate_ulta(self, call: CallbackQuery):
        """Dispatch to stage-specific ulta handler."""
        user_id = call.from_user.id
        player = await asyncio.to_thread(self.player_service.get_player, user_id)
        if not player or not player.pet:
            await call.answer("Питомец не найден")
            return
        if not self.pet_service.is_ulta_available(player):
            await call.answer("Ульта ещё не готова!")
            return

        stage = player.pet.get('stage', 'egg')
        dispatch = {
            'egg':       self._ulta_casino_plus,
            'baby':      self._ulta_free_roll,
            'adult':     self._ulta_oracle,
            'legendary': self._ulta_khalyava,
        }
        handler = dispatch.get(stage)
        if handler:
            await handler(call, player)
        else:
            await call.answer("Неизвестная стадия")

    async def _show_ulta_info(self, call: CallbackQuery):
        """Show info about ulta cooldown."""
        await call.answer(
            "Ульта будет готова через 24 часа после последнего использования "
            "(48 часов если питомец подавлен, настроение < 20). "
            "Убедись, что питомец не голоден (голод ≥ 10).",
            show_alert=True
        )

    async def _ulta_casino_plus(self, call: CallbackQuery, player):
        """Egg ulta: +2 casino attempts today."""
        player.pet_casino_extra_spins = getattr(player, 'pet_casino_extra_spins', 0) + 2
        self.pet_service.mark_ulta_used(player)
        await asyncio.to_thread(self.player_service.save_player, player)
        await call.answer("🎰 Казино+: +2 попытки казино сегодня!", show_alert=True)
        await self.show_pet_menu(call.message.chat.id, call.from_user.id,
                                 delete_message_id=call.message.message_id)

    async def _ulta_free_roll(self, call: CallbackQuery, player):
        """Baby ulta: next roll is free."""
        player.pet_ulta_free_roll_pending = True
        self.pet_service.mark_ulta_used(player)
        await asyncio.to_thread(self.player_service.save_player, player)
        await call.answer(
            "🎲 Халявный ролл активирован! Следующий /roll бесплатный.",
            show_alert=True
        )
        await self.show_pet_menu(call.message.chat.id, call.from_user.id,
                                 delete_message_id=call.message.message_id)

    async def _ulta_oracle(self, call: CallbackQuery, player):
        """Adult ulta: preview pisunchik result before rolling."""
        preview = self.game_service.preview_pisunchik_result(player)
        player.pet_ulta_oracle_pending = True
        player.pet_ulta_oracle_preview = preview
        self.pet_service.mark_ulta_used(player)
        await asyncio.to_thread(self.player_service.save_player, player)
        await call.answer()

        markup = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Бросить!", callback_data="pet_oracle_yes"),
            InlineKeyboardButton(text="❌ Пропустить", callback_data="pet_oracle_no"),
        ]])
        sign = '+' if preview['size_change'] >= 0 else ''
        text = (
            f"🔮 Оракул предсказывает:\n\n"
            f"Изменение: {sign}{preview['size_change']} см\n"
            f"Монеты: +{preview['coins_change']} BTC\n\n"
            f"Бросать?"
        )
        try:
            await self.bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        await self.bot.send_message(call.message.chat.id, text, reply_markup=markup)

    async def _ulta_khalyava(self, call: CallbackQuery, player):
        """Legendary ulta: auto-correct next trivia answer."""
        player.pet_ulta_trivia_pending = True
        self.pet_service.mark_ulta_used(player)
        await asyncio.to_thread(self.player_service.save_player, player)
        await call.answer(
            "✅ Халява активирована! Следующий вопрос викторины засчитается автоматически.",
            show_alert=True
        )
        await self.show_pet_menu(call.message.chat.id, call.from_user.id,
                                 delete_message_id=call.message.message_id)

    async def oracle_confirm(self, call: CallbackQuery):
        """Oracle: player confirmed — apply the stored preview result."""
        from datetime import datetime, timezone
        user_id = call.from_user.id
        player = await asyncio.to_thread(self.player_service.get_player, user_id)
        if not player or not player.pet_ulta_oracle_preview:
            await call.answer("Предсказание устарело")
            await self._dismiss_and_reopen(call)
            return

        preview = player.pet_ulta_oracle_preview
        player.pet_ulta_oracle_pending = False
        player.pet_ulta_oracle_preview = None
        player.pisunchik_size += preview['size_change']
        player.add_coins(preview['coins_change'])
        player.last_used = datetime.now(timezone.utc)
        await asyncio.to_thread(self.player_service.save_player, player)

        await call.answer()
        sign = '+' if preview['size_change'] >= 0 else ''
        try:
            await self.bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        await self.bot.send_message(
            call.message.chat.id,
            f"🔮 Бросок совершён!\n"
            f"Ваш писюнчик: {player.pisunchik_size} см ({sign}{preview['size_change']} см)\n"
            f"Монеты: +{preview['coins_change']} BTC"
        )

    async def oracle_cancel(self, call: CallbackQuery):
        """Oracle: player skipped — no cooldown refund (ulta was already used)."""
        user_id = call.from_user.id
        player = await asyncio.to_thread(self.player_service.get_player, user_id)
        if player:
            player.pet_ulta_oracle_pending = False
            player.pet_ulta_oracle_preview = None
            await asyncio.to_thread(self.player_service.save_player, player)
        await call.answer("Пропущено. Писюнчик не брошен.")
        await self.show_pet_menu(call.message.chat.id, user_id,
                                 delete_message_id=call.message.message_id)

    def get_player_mention(self, user_id: int, player_name: str, username: Optional[str] = None) -> str:
        if username:
            return f"@{username}"
        return f'<a href="tg://user?id={user_id}">{escape_html(player_name)}</a>'
