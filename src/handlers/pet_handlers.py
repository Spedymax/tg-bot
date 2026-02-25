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

        # Temp storage for waiting user input
        self.waiting_for_name = {}  # {user_id: message_id}
        self.waiting_for_image = {}  # {user_id: message_id}

    def setup_handlers(self):
        """Setup all pet-related command handlers."""

        @self.bot.message_handler(commands=['pet'])
        def pet_command(message):
            """Handle /pet command - main pet interface."""
            self.show_pet_menu(message.chat.id, message.from_user.id)

        # Callback handlers
        @self.bot.callback_query_handler(func=lambda call: call.data.startswith('pet_'))
        def pet_callback(call):
            """Handle all pet-related callbacks."""
            self.handle_pet_callback(call)

        # Text input handlers
        @self.bot.message_handler(func=lambda m: m.from_user.id in self.waiting_for_name)
        def handle_name_input(message):
            """Handle pet name input."""
            self.process_name_input(message)

        # Photo input handlers
        @self.bot.message_handler(content_types=['photo'],
                                   func=lambda m: m.from_user.id in self.waiting_for_image)
        def handle_image_input(message):
            """Handle pet image upload."""
            self.process_image_input(message)

    def show_pet_menu(self, chat_id: int, user_id: int, message_id: int = None):
        """Show the main pet menu with inline buttons."""
        player = self.player_service.get_player(user_id)

        if not player:
            self.bot.send_message(chat_id, "Ви не зареєстровані як гравець.")
            return

        pet = getattr(player, 'pet', None)

        if not pet:
            # No pet - show create button
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🥚 Створити улюбленця", callback_data="pet_create"))

            text = "У тебе ще немає улюбленця!"

            if message_id:
                self.bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)
            else:
                self.bot.send_message(chat_id, text, reply_markup=markup)
            return

        # Has pet - show pet info with appropriate buttons
        active_title = getattr(player, 'pet_active_title', None)
        revives_used = getattr(player, 'pet_revives_used', 0)
        streak = getattr(player, 'trivia_streak', 0)

        text = self.pet_service.format_pet_display(pet, active_title, revives_used, streak)
        markup = self._get_pet_buttons(pet, player)

        # Send with image if available
        if pet.get('image_file_id') and not message_id:
            try:
                self.bot.send_photo(chat_id, pet['image_file_id'], caption=text,
                                    reply_markup=markup, parse_mode='HTML')
                return
            except Exception as e:
                logger.error(f"Error sending pet image: {e}")

        if message_id:
            self.bot.edit_message_text(text, chat_id, message_id, reply_markup=markup, parse_mode='HTML')
        else:
            self.bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')

    def _get_pet_buttons(self, pet: dict, player) -> types.InlineKeyboardMarkup:
        """Get appropriate buttons based on pet state."""
        markup = types.InlineKeyboardMarkup()

        if not pet.get('is_alive'):
            # Dead pet buttons
            markup.add(types.InlineKeyboardButton("❤️ Відродити", callback_data="pet_revive"))
            markup.add(types.InlineKeyboardButton("🗑 Видалити назавжди", callback_data="pet_delete_confirm"))
        elif not pet.get('is_locked'):
            # Unlocked pet (customization mode)
            markup.row(
                types.InlineKeyboardButton("✏️ Змінити ім'я", callback_data="pet_name"),
                types.InlineKeyboardButton("🖼 Змінити фото", callback_data="pet_image")
            )
            markup.add(types.InlineKeyboardButton("✅ Підтвердити", callback_data="pet_confirm"))
        else:
            # Alive and locked pet
            pet_titles = getattr(player, 'pet_titles', [])
            if pet_titles:
                markup.add(types.InlineKeyboardButton("🏷 Титули", callback_data="pet_titles"))
            markup.add(types.InlineKeyboardButton("💀 Вбити", callback_data="pet_kill_confirm"))

        return markup

    def handle_pet_callback(self, call):
        """Route pet callbacks to appropriate handlers."""
        user_id = call.from_user.id
        chat_id = call.message.chat.id
        message_id = call.message.message_id
        action = call.data.replace('pet_', '')

        handlers = {
            'create': lambda: self.create_pet(call),
            'name': lambda: self.request_name(call),
            'image': lambda: self.request_image(call),
            'confirm': lambda: self.confirm_pet(call),
            'revive': lambda: self.revive_pet(call),
            'kill_confirm': lambda: self.show_kill_confirm(call),
            'kill_yes': lambda: self.kill_pet(call),
            'kill_no': lambda: self.show_pet_menu(chat_id, user_id, message_id),
            'delete_confirm': lambda: self.show_delete_confirm(call),
            'delete_yes': lambda: self.delete_pet(call),
            'delete_no': lambda: self.show_pet_menu(chat_id, user_id, message_id),
            'titles': lambda: self.show_titles(call),
            'titles_back': lambda: self.show_pet_menu(chat_id, user_id, message_id),
        }

        # Handle title selection (pet_title_TitleName)
        if action.startswith('title_') and action != 'titles' and action != 'titles_back':
            self.select_title(call, action.replace('title_', ''))
            return

        handler = handlers.get(action)
        if handler:
            handler()
        else:
            self.bot.answer_callback_query(call.id, "Невідома дія")

    def create_pet(self, call):
        """Start pet creation process."""
        user_id = call.from_user.id
        player = self.player_service.get_player(user_id)

        if not player:
            self.bot.answer_callback_query(call.id, "Гравець не знайдений")
            return

        # Create pet with default name
        pet = self.pet_service.create_pet("Новий улюбленець")
        player.pet = pet
        self.player_service.save_player(player)

        self.bot.answer_callback_query(call.id, "Улюбленця створено!")
        self.show_pet_menu(call.message.chat.id, user_id, call.message.message_id)

    def request_name(self, call):
        """Request new pet name from user."""
        user_id = call.from_user.id
        chat_id = call.message.chat.id

        self.waiting_for_name[user_id] = call.message.message_id

        self.bot.answer_callback_query(call.id)
        self.bot.send_message(chat_id, "Напиши нове ім'я для улюбленця:")

    def process_name_input(self, message):
        """Process pet name input."""
        user_id = message.from_user.id
        chat_id = message.chat.id
        new_name = message.text.strip()[:50]  # Limit name length

        if user_id not in self.waiting_for_name:
            return

        del self.waiting_for_name[user_id]

        player = self.player_service.get_player(user_id)
        if player and player.pet and not player.pet.get('is_locked'):
            player.pet['name'] = escape_html(new_name)
            self.player_service.save_player(player)
            self.bot.send_message(chat_id, f"Ім'я змінено на: {new_name}")

        self.show_pet_menu(chat_id, user_id)

    def request_image(self, call):
        """Request new pet image from user."""
        user_id = call.from_user.id
        chat_id = call.message.chat.id

        self.waiting_for_image[user_id] = call.message.message_id

        self.bot.answer_callback_query(call.id)
        self.bot.send_message(chat_id, "Надішли нове фото для улюбленця:")

    def process_image_input(self, message):
        """Process pet image upload."""
        user_id = message.from_user.id
        chat_id = message.chat.id

        if user_id not in self.waiting_for_image:
            return

        del self.waiting_for_image[user_id]

        # Get the largest photo
        photo = message.photo[-1]
        file_id = photo.file_id

        player = self.player_service.get_player(user_id)
        if player and player.pet and not player.pet.get('is_locked'):
            player.pet['image_file_id'] = file_id
            self.player_service.save_player(player)
            self.bot.send_message(chat_id, "Фото оновлено!")

        self.show_pet_menu(chat_id, user_id)

    def confirm_pet(self, call):
        """Lock pet customization."""
        user_id = call.from_user.id
        player = self.player_service.get_player(user_id)

        if player and player.pet:
            player.pet['is_locked'] = True
            self.player_service.save_player(player)
            self.bot.answer_callback_query(call.id, "Улюбленця підтверджено! Тепер він буде рости.")

        self.show_pet_menu(call.message.chat.id, user_id, call.message.message_id)

    def revive_pet(self, call):
        """Attempt to revive dead pet."""
        user_id = call.from_user.id
        player = self.player_service.get_player(user_id)

        if not player or not player.pet:
            self.bot.answer_callback_query(call.id, "Улюбленця не знайдено")
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
            self.bot.answer_callback_query(call.id, "Улюбленця відроджено!")
        else:
            self.bot.answer_callback_query(call.id, "Немає відроджень на цей місяць!")

        self.show_pet_menu(call.message.chat.id, user_id, call.message.message_id)

    def show_kill_confirm(self, call):
        """Show kill confirmation."""
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("❌ Ні, залишити", callback_data="pet_kill_no"),
            types.InlineKeyboardButton("✅ Так, вбити", callback_data="pet_kill_yes")
        )

        self.bot.edit_message_text(
            "⚠️ Ти впевнений? Улюбленець помре і потребуватиме відродження!",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )

    def kill_pet(self, call):
        """Kill pet (make it dormant)."""
        user_id = call.from_user.id
        player = self.player_service.get_player(user_id)

        if player and player.pet:
            player.pet = self.pet_service.kill_pet(player.pet)
            self.player_service.save_player(player)
            self.bot.answer_callback_query(call.id, "Улюбленець помер 💀")

        self.show_pet_menu(call.message.chat.id, user_id, call.message.message_id)

    def show_delete_confirm(self, call):
        """Show delete confirmation."""
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("❌ Ні, залишити", callback_data="pet_delete_no"),
            types.InlineKeyboardButton("✅ Так, видалити", callback_data="pet_delete_yes")
        )

        self.bot.edit_message_text(
            "⚠️ Ти впевнений? Улюбленця буде видалено НАЗАВЖДИ! Весь прогрес буде втрачено!",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )

    def delete_pet(self, call):
        """Permanently delete pet."""
        user_id = call.from_user.id
        player = self.player_service.get_player(user_id)

        if player:
            player.pet = None
            # Keep titles - they're permanent
            self.player_service.save_player(player)
            self.bot.answer_callback_query(call.id, "Улюбленця видалено")

        self.show_pet_menu(call.message.chat.id, user_id, call.message.message_id)

    def show_titles(self, call):
        """Show titles selection screen."""
        user_id = call.from_user.id
        player = self.player_service.get_player(user_id)

        if not player:
            self.bot.answer_callback_query(call.id)
            return

        titles = getattr(player, 'pet_titles', [])
        active_title = getattr(player, 'pet_active_title', None)

        if not titles:
            self.bot.answer_callback_query(call.id, "У тебе ще немає титулів!")
            return

        self.bot.answer_callback_query(call.id)

        text = "🏷 Твої титули:\n\n"
        for title in titles:
            marker = " ✅ (активний)" if title == active_title else ""
            text += f"• {escape_html(title)}{marker}\n"

        markup = types.InlineKeyboardMarkup(row_width=2)
        buttons = [types.InlineKeyboardButton(t, callback_data=f"pet_title_{t[:40]}") for t in titles]  # Truncate to ensure fits in 64 bytes
        markup.add(*buttons)
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="pet_titles_back"))

        self.bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )

    def select_title(self, call, title: str):
        """Select active title."""
        user_id = call.from_user.id
        player = self.player_service.get_player(user_id)

        if player and title in getattr(player, 'pet_titles', []):
            player.pet_active_title = title
            self.player_service.save_player(player)
            self.bot.answer_callback_query(call.id, f"Титул '{title}' активовано!")

        self.show_titles(call)

    def get_player_mention(self, user_id: int, player_name: str, username: Optional[str] = None) -> str:
        """Get mention string for player."""
        if username:
            return f"@{username}"
        return f'<a href="tg://user?id={user_id}">{escape_html(player_name)}</a>'
