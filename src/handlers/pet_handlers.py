import logging
from telebot import types
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

    def setup_handlers(self):
        """Setup all pet-related command handlers."""

        @self.bot.message_handler(commands=['pet'])
        def pet_command(message):
            self.show_pet_menu(message.chat.id, message.from_user.id)

        @self.bot.callback_query_handler(func=lambda call: call.data.startswith('pet_'))
        def pet_callback(call):
            self.handle_pet_callback(call)

    # ──────────────────────────────────────────────
    # Core display
    # ──────────────────────────────────────────────

    def show_pet_menu(self, chat_id: int, user_id: int, delete_message_id: int = None):
        """Send a fresh pet menu, optionally deleting an old message first."""
        if delete_message_id:
            try:
                self.bot.delete_message(chat_id, delete_message_id)
            except Exception:
                pass

        player = self.player_service.get_player(user_id)
        if not player:
            self.bot.send_message(chat_id, "Вы не зарегистрированы как игрок.")
            return

        pet = getattr(player, 'pet', None)

        if not pet:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🥚 Создать питомца", callback_data="pet_create"))
            self.bot.send_message(chat_id, "У тебя ещё нет питомца!", reply_markup=markup)
            return

        active_title = getattr(player, 'pet_active_title', None)
        revives_used = getattr(player, 'pet_revives_used', 0)
        streak = getattr(player, 'trivia_streak', 0)

        text = self.pet_service.format_pet_display(pet, active_title, revives_used, streak)
        markup = self._get_pet_buttons(pet, player)

        if pet.get('image_file_id'):
            try:
                self.bot.send_photo(chat_id, pet['image_file_id'], caption=text,
                                    reply_markup=markup, parse_mode='HTML')
                return
            except Exception as e:
                logger.error(f"Error sending pet image: {e}")

        self.bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')

    def _get_pet_buttons(self, pet: dict, player) -> types.InlineKeyboardMarkup:
        """Get appropriate buttons based on pet state."""
        markup = types.InlineKeyboardMarkup()

        if not pet.get('is_alive'):
            # Dead pet
            markup.add(types.InlineKeyboardButton("❤️ Возродить", callback_data="pet_revive"))
            markup.add(types.InlineKeyboardButton("🗑 Удалить навсегда", callback_data="pet_delete_confirm"))

        elif not pet.get('is_locked'):
            # Initial setup (new, never confirmed)
            markup.row(
                types.InlineKeyboardButton("✏️ Изменить имя", callback_data="pet_name"),
                types.InlineKeyboardButton("🖼 Изменить фото", callback_data="pet_image")
            )
            markup.add(types.InlineKeyboardButton("✅ Подтвердить", callback_data="pet_confirm"))

        else:
            # Alive and active — customization always available
            markup.row(
                types.InlineKeyboardButton("✏️ Имя", callback_data="pet_name"),
                types.InlineKeyboardButton("🖼 Фото", callback_data="pet_image")
            )
            pet_titles = getattr(player, 'pet_titles', [])
            if pet_titles:
                markup.add(types.InlineKeyboardButton("🏷 Титулы", callback_data="pet_titles"))
            markup.add(types.InlineKeyboardButton("💀 Убить", callback_data="pet_kill_confirm"))

        return markup

    # ──────────────────────────────────────────────
    # Callback routing
    # ──────────────────────────────────────────────

    def handle_pet_callback(self, call):
        """Route pet callbacks to appropriate handlers."""
        user_id = call.from_user.id
        chat_id = call.message.chat.id
        message_id = call.message.message_id
        action = call.data.replace('pet_', '', 1)

        # Title selection by index: pet_title_0, pet_title_1, ...
        if action.startswith('title_') and action != 'titles' and action != 'titles_back':
            try:
                idx = int(action.replace('title_', '', 1))
                self.select_title(call, idx)
            except ValueError:
                self.bot.answer_callback_query(call.id, "Ошибка выбора титула")
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
        }

        handler = handlers.get(action)
        if handler:
            handler()
        else:
            self.bot.answer_callback_query(call.id, "Неизвестное действие")

    # ──────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────

    def _dismiss_and_reopen(self, call):
        """Delete current message and reopen pet menu."""
        self.show_pet_menu(call.message.chat.id, call.from_user.id,
                           delete_message_id=call.message.message_id)

    def _replace_with_text(self, call, text, markup):
        """Delete current message, send a plain text message."""
        try:
            self.bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        self.bot.send_message(call.message.chat.id, text, reply_markup=markup)

    # ──────────────────────────────────────────────
    # Pet creation
    # ──────────────────────────────────────────────

    def create_pet(self, call):
        user_id = call.from_user.id
        player = self.player_service.get_player(user_id)
        if not player:
            self.bot.answer_callback_query(call.id, "Игрок не найден")
            return

        player.pet = self.pet_service.create_pet("Новый питомец")
        self.player_service.save_player(player)
        self.bot.answer_callback_query(call.id, "Питомец создан!")
        self.show_pet_menu(call.message.chat.id, user_id,
                           delete_message_id=call.message.message_id)

    # ──────────────────────────────────────────────
    # Name / image customization
    # ──────────────────────────────────────────────

    def request_name(self, call):
        self.bot.answer_callback_query(call.id)
        msg = self.bot.send_message(call.message.chat.id, "Напиши новое имя для питомца:")
        self.bot.register_next_step_handler(msg, self.process_name_input)

    def process_name_input(self, message):
        user_id = message.from_user.id
        new_name = message.text.strip()[:50]

        player = self.player_service.get_player(user_id)
        if player and player.pet:
            player.pet['name'] = escape_html(new_name)
            self.player_service.save_player(player)
            self.bot.send_message(message.chat.id, f"Имя изменено на: {new_name}")

        self.show_pet_menu(message.chat.id, user_id)

    def request_image(self, call):
        self.bot.answer_callback_query(call.id)
        msg = self.bot.send_message(call.message.chat.id, "Пришли новое фото для питомца:")
        self.bot.register_next_step_handler(msg, self.process_image_input)

    def process_image_input(self, message):
        user_id = message.from_user.id

        if not message.photo:
            self.bot.send_message(message.chat.id, "Это не фото. Пришли изображение.")
            self.bot.register_next_step_handler(message, self.process_image_input)
            return

        file_id = message.photo[-1].file_id
        player = self.player_service.get_player(user_id)
        if player and player.pet:
            player.pet['image_file_id'] = file_id
            self.player_service.save_player(player)
            self.bot.send_message(message.chat.id, "Фото обновлено!")

        self.show_pet_menu(message.chat.id, user_id)

    # ──────────────────────────────────────────────
    # Confirm (initial setup only)
    # ──────────────────────────────────────────────

    def confirm_pet(self, call):
        user_id = call.from_user.id
        player = self.player_service.get_player(user_id)
        if player and player.pet:
            player.pet['is_locked'] = True
            self.player_service.save_player(player)
            self.bot.answer_callback_query(call.id, "Питомец подтверждён! Теперь он будет расти.")

        self.show_pet_menu(call.message.chat.id, user_id,
                           delete_message_id=call.message.message_id)

    # ──────────────────────────────────────────────
    # Revive
    # ──────────────────────────────────────────────

    def revive_pet(self, call):
        user_id = call.from_user.id
        player = self.player_service.get_player(user_id)

        if not player or not player.pet:
            self.bot.answer_callback_query(call.id, "Питомец не найден")
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
            self.player_service.save_player(player)
            self.bot.answer_callback_query(call.id, "Питомец возрождён!")
        else:
            self.bot.answer_callback_query(call.id, "Нет возрождений на этот месяц!")

        self.show_pet_menu(call.message.chat.id, user_id,
                           delete_message_id=call.message.message_id)

    # ──────────────────────────────────────────────
    # Kill
    # ──────────────────────────────────────────────

    def show_kill_confirm(self, call):
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("❌ Нет, оставить", callback_data="pet_kill_no"),
            types.InlineKeyboardButton("✅ Да, убить", callback_data="pet_kill_yes")
        )
        self._replace_with_text(call, "⚠️ Ты уверен? Питомец умрёт и потребует возрождения!", markup)

    def kill_pet(self, call):
        user_id = call.from_user.id
        player = self.player_service.get_player(user_id)
        if player and player.pet:
            player.pet = self.pet_service.kill_pet(player.pet)
            self.player_service.save_player(player)
            self.bot.answer_callback_query(call.id, "Питомец умер 💀")

        self.show_pet_menu(call.message.chat.id, user_id,
                           delete_message_id=call.message.message_id)

    # ──────────────────────────────────────────────
    # Delete
    # ──────────────────────────────────────────────

    def show_delete_confirm(self, call):
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("❌ Нет, оставить", callback_data="pet_delete_no"),
            types.InlineKeyboardButton("✅ Да, удалить", callback_data="pet_delete_yes")
        )
        self._replace_with_text(call,
            "⚠️ Ты уверен? Питомец будет удалён НАВСЕГДА! Весь прогресс будет потерян!", markup)

    def delete_pet(self, call):
        user_id = call.from_user.id
        player = self.player_service.get_player(user_id)
        if player:
            player.pet = None
            self.player_service.save_player(player)
            self.bot.answer_callback_query(call.id, "Питомец удалён")

        self.show_pet_menu(call.message.chat.id, user_id,
                           delete_message_id=call.message.message_id)

    # ──────────────────────────────────────────────
    # Titles
    # ──────────────────────────────────────────────

    def show_titles(self, call):
        user_id = call.from_user.id
        player = self.player_service.get_player(user_id)

        if not player:
            self.bot.answer_callback_query(call.id)
            return

        titles = getattr(player, 'pet_titles', [])
        active_title = getattr(player, 'pet_active_title', None)

        if not titles:
            self.bot.answer_callback_query(call.id, "У тебя ещё нет титулов!")
            return

        self.bot.answer_callback_query(call.id)

        text = "🏷 Твои титулы:\n\n"
        for title in titles:
            marker = " ✅" if title == active_title else ""
            text += f"• {escape_html(title)}{marker}\n"

        markup = types.InlineKeyboardMarkup(row_width=2)
        # Use index as callback data — avoids UTF-8 byte limit issues
        buttons = [
            types.InlineKeyboardButton(t, callback_data=f"pet_title_{i}")
            for i, t in enumerate(titles)
        ]
        markup.add(*buttons)
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="pet_titles_back"))

        try:
            self.bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        self.bot.send_message(call.message.chat.id, text, reply_markup=markup)

    def select_title(self, call, idx: int):
        """Activate title by index."""
        user_id = call.from_user.id
        player = self.player_service.get_player(user_id)

        if player:
            titles = getattr(player, 'pet_titles', [])
            if 0 <= idx < len(titles):
                title = titles[idx]
                player.pet_active_title = title
                self.player_service.save_player(player)
                self.bot.answer_callback_query(call.id, f"Титул «{title}» активирован!")
            else:
                self.bot.answer_callback_query(call.id, "Титул не найден")
        else:
            self.bot.answer_callback_query(call.id)

        self.show_titles(call)

    def get_player_mention(self, user_id: int, player_name: str, username: Optional[str] = None) -> str:
        if username:
            return f"@{username}"
        return f'<a href="tg://user?id={user_id}">{escape_html(player_name)}</a>'
