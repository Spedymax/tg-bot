import logging
import threading
from telebot import types
from services.court_service import CourtService

logger = logging.getLogger(__name__)

ROLE_NAMES = {
    "prosecutor": "⚔️ Прокурор",
    "lawyer": "🛡️ Адвокат",
    "witness": "👁️ Свидетель защиты",
}

RULES_TEXT = """⚖️ <b>СУДЕБНОЕ ЗАСЕДАНИЕ ОТКРЫВАЕТСЯ</b>

Суд знакомит стороны с правилами процесса:

<b>Роли:</b>
• ⚔️ <b>Прокурор</b> — получает 8 карт, играет 4. Обвиняет подсудимого.
• 🛡️ <b>Адвокат</b> — получает 4 карты, играет 2. Защищает подсудимого. Видит карты Свидетеля.
• 👁️ <b>Свидетель защиты</b> — получает 4 карты, играет 2. Поддерживает защиту. Видит карты Адвоката.

<b>Ход игры:</b>
1. Каждый получает карты в личные сообщения от бота
2. 4 раунда: Прокурор играет карту → защита отвечает
3. После 4 раундов судья выносит приговор

<b>Важно:</b>
— Защита координирует стратегию между собой (видят руки друг друга)
— Судья фиксирует все противоречия. "Я не так сказал" — не аргумент.
— Подсудимым может быть кто угодно: реальный человек, персонаж, кот Леопольд.

Чтобы играть — каждый участник должен написать боту в личку хотя бы раз."""


class CourtHandlers:
    def __init__(self, bot, db_manager):
        self.bot = bot
        self.db = db_manager
        self.court_service = CourtService(db_manager)
        # Состояния ожидания по чату: chat_id → {'state': str, 'game_id': int, ...}
        self._wait: dict[int, dict] = {}

    def setup_handlers(self):

        @self.bot.message_handler(commands=['court', 'sud'])
        def cmd_court(message):
            if message.chat.type == 'private':
                self.bot.reply_to(message, "Эта команда работает только в групповом чате.")
                return
            chat_id = message.chat.id
            existing = self.court_service.get_active_game(chat_id)
            if existing:
                self.bot.reply_to(message, "⚖️ Заседание уже идёт! Используй /court_stop чтобы завершить.")
                return

            self.bot.send_message(chat_id, RULES_TEXT, parse_mode='HTML')
            self.bot.send_message(chat_id, "👤 Кого обвиняем? Напишите имя или описание подсудимого (например: «Кот Леопольд», «Юра с 3-го этажа», «ChatGPT»):")
            self._wait[chat_id] = {'state': 'waiting_defendant', 'initiator': message.from_user.id}

        @self.bot.message_handler(commands=['court_stop', 'sud_stop'])
        def cmd_court_stop(message):
            chat_id = message.chat.id
            game = self.court_service.get_active_game(chat_id)
            if not game:
                self.bot.reply_to(message, "Активного заседания нет.")
                return
            self.court_service.set_status(game['id'], 'aborted')
            self._wait.pop(chat_id, None)
            self.bot.send_message(chat_id, "⚖️ Заседание досрочно прекращено.")

        @self.bot.message_handler(func=lambda m: m.chat.type != 'private' and m.chat.id in self._wait)
        def handle_wait_state(message):
            chat_id = message.chat.id
            state_data = self._wait.get(chat_id)
            if not state_data:
                return

            state = state_data['state']

            if state == 'waiting_defendant':
                defendant = message.text.strip()
                if not defendant or len(defendant) > 200:
                    self.bot.reply_to(message, "Введите имя подсудимого (до 200 символов).")
                    return
                state_data['defendant'] = defendant
                state_data['state'] = 'waiting_crime'
                self.bot.send_message(chat_id, f"📋 Подсудимый: <b>{defendant}</b>\n\nТеперь опишите преступление:", parse_mode='HTML')

            elif state == 'waiting_crime':
                crime = message.text.strip()
                if not crime or len(crime) > 500:
                    self.bot.reply_to(message, "Опишите преступление (до 500 символов).")
                    return
                defendant = state_data['defendant']
                game_id = self.court_service.create_game(chat_id, defendant, crime)
                state_data['game_id'] = game_id
                state_data['state'] = 'role_selection'
                state_data['roles_taken'] = {}
                self._wait[chat_id] = state_data
                self._send_role_keyboard(chat_id, game_id)

    def _send_role_keyboard(self, chat_id: int, game_id: int):
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("⚔️ Прокурор", callback_data=f"court_role:prosecutor:{game_id}"))
        markup.row(types.InlineKeyboardButton("🛡️ Адвокат", callback_data=f"court_role:lawyer:{game_id}"))
        markup.row(types.InlineKeyboardButton("👁️ Свидетель защиты", callback_data=f"court_role:witness:{game_id}"))
        self.bot.send_message(
            chat_id,
            "⚖️ Выберите роль для участия в заседании:",
            reply_markup=markup,
        )

    def setup_callback_handlers(self):

        @self.bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("court_role:"))
        def handle_role_selection(call):
            _, role, game_id_str = call.data.split(":")
            game_id = int(game_id_str)
            chat_id = call.message.chat.id
            user_id = call.from_user.id
            user_name = call.from_user.first_name or call.from_user.username or str(user_id)

            state_data = self._wait.get(chat_id, {})
            roles_taken = state_data.get('roles_taken', {})

            # Проверяем не занята ли роль
            if role in roles_taken:
                self.bot.answer_callback_query(call.id, "Эта роль уже занята!", show_alert=True)
                return
            # Проверяем что у юзера ещё нет роли
            if user_id in roles_taken.values():
                self.bot.answer_callback_query(call.id, "Ты уже выбрал роль!", show_alert=True)
                return

            roles_taken[role] = user_id
            state_data['roles_taken'] = roles_taken
            self.court_service.assign_role(game_id, role, user_id)

            # Убираем занятую кнопку из клавиатуры
            remaining_roles = [r for r in ("prosecutor", "lawyer", "witness") if r not in roles_taken]
            if remaining_roles:
                markup = types.InlineKeyboardMarkup()
                for r in remaining_roles:
                    markup.row(types.InlineKeyboardButton(ROLE_NAMES[r], callback_data=f"court_role:{r}:{game_id}"))
                self.bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=markup)
            else:
                self.bot.delete_message(chat_id, call.message.message_id)

            role_ru = ROLE_NAMES[role]
            self.bot.send_message(chat_id, f"✅ <b>{user_name}</b> берёт роль {role_ru}", parse_mode='HTML')
            self.bot.answer_callback_query(call.id, f"Ты {role_ru}!")

            # Все роли заняты → начинаем игру
            if len(roles_taken) == 3:
                self._wait.pop(chat_id, None)
                threading.Thread(target=self._start_game, args=(chat_id, game_id, roles_taken), daemon=True).start()

        @self.bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("court_play:"))
        def handle_play_card(call):
            # Формат: court_play:{game_id}:{role}:{card_index}
            parts = call.data.split(":", 3)
            game_id, role, card_index = int(parts[1]), parts[2], int(parts[3])
            user_id = call.from_user.id

            game = self.court_service.get_active_game_by_id(game_id)
            if not game:
                self.bot.answer_callback_query(call.id, "Игра не найдена.", show_alert=True)
                return

            # Проверяем что это карта этого игрока
            expected_role_id = game[f"{role}_id"]
            if user_id != expected_role_id:
                self.bot.answer_callback_query(call.id, "Сейчас не твой ход!", show_alert=True)
                return

            cards_left_key = f"{role}_cards_left"
            if game[cards_left_key] <= 0:
                self.bot.answer_callback_query(call.id, "Ты уже сыграл все свои карты!", show_alert=True)
                return

            cards_key = f"{role}_cards"
            card_text = game[cards_key][card_index]

            self.bot.answer_callback_query(call.id, "Карта сыграна!")
            # Убираем кнопки в личке после розыгрыша
            self.bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)

            threading.Thread(
                target=self._process_played_card,
                args=(game_id, game['chat_id'], role, card_text, game['current_round']),
                daemon=True
            ).start()

    def _start_game(self, chat_id: int, game_id: int, roles_taken: dict):
        """Сгенерировать карты, отправить в личку, начать раунд 1."""
        game = self.court_service.get_active_game_by_id(game_id)
        defendant = game['defendant']
        crime = game['crime']

        self.bot.send_message(chat_id, "⚖️ <b>Состав суда сформирован. Генерирую материалы дела...</b>", parse_mode='HTML')

        prosecutor_cards, lawyer_cards, witness_cards = self.court_service.generate_cards(defendant, crime)

        if not prosecutor_cards:
            self.bot.send_message(chat_id, "❌ Ошибка генерации карт. Попробуйте /court ещё раз.")
            self.court_service.set_status(game_id, 'aborted')
            return

        self.court_service.save_cards(game_id, prosecutor_cards, lawyer_cards, witness_cards)
        self.court_service.set_status(game_id, 'in_progress')
        self.court_service.advance_round(game_id, 1)
        self.court_service.log_message(game_id, 'system', f'Дело: {defendant} обвиняется в «{crime}»')

        # Отправляем карты в личку
        self._send_cards_dm(roles_taken['prosecutor'], game_id, 'prosecutor', prosecutor_cards)
        self._send_cards_dm(roles_taken['lawyer'], game_id, 'lawyer', lawyer_cards, partner_cards=witness_cards, partner_role='witness')
        self._send_cards_dm(roles_taken['witness'], game_id, 'witness', witness_cards, partner_cards=lawyer_cards, partner_role='lawyer')

        self.bot.send_message(
            chat_id,
            f"📬 <b>Карты отправлены в личные сообщения.</b>\n\n"
            f"⚖️ <b>Раунд 1 из 4</b>\n"
            f"Слово предоставляется ⚔️ Прокурору. Сыграйте карту в личном чате с ботом.",
            parse_mode='HTML'
        )

    def _send_cards_dm(self, user_id: int, game_id: int, role: str, cards: list,
                       partner_cards: list = None, partner_role: str = None):
        """Отправить игроку его руку в личку с inline-кнопками."""
        role_ru = ROLE_NAMES[role]
        plays = 4 if role == 'prosecutor' else 2
        text = f"⚖️ <b>Твоя роль: {role_ru}</b>\n\n<b>Твои карты ({len(cards)} шт, играешь {plays}):</b>\n"
        for i, card in enumerate(cards, 1):
            text += f"{i}. {card}\n"

        if partner_cards and partner_role:
            partner_ru = ROLE_NAMES[partner_role]
            text += f"\n<b>Карты {partner_ru} (для координации):</b>\n"
            for i, card in enumerate(partner_cards, 1):
                text += f"{i}. {card}\n"

        markup = types.InlineKeyboardMarkup()
        for i, card in enumerate(cards):
            markup.row(types.InlineKeyboardButton(
                f"🃏 {card[:40]}{'…' if len(card) > 40 else ''}",
                callback_data=f"court_play:{game_id}:{role}:{i}"
            ))

        try:
            self.bot.send_message(user_id, text, parse_mode='HTML', reply_markup=markup)
        except Exception as e:
            logger.error(f"CourtHandlers: не удалось отправить личку {user_id}: {e}")
            game = self.court_service.get_active_game_by_id(game_id)
            if game:
                self.bot.send_message(
                    game['chat_id'],
                    f"⚠️ Не удалось отправить карты игроку. "
                    f"Пожалуйста, напишите боту в личку (@{self._get_bot_username()}) и повторите /court."
                )

    def _process_played_card(self, game_id: int, chat_id: int, role: str, card: str, round_num: int):
        """Объявляем сыгранную карту, судья реагирует, двигаем состояние."""
        role_ru = ROLE_NAMES[role]
        self.bot.send_message(chat_id, f"🃏 <b>{role_ru}</b> играет карту:\n\n«{card}»", parse_mode='HTML')

        self.court_service.record_played_card(game_id, role, card, round_num)
        self.court_service.log_message(game_id, role, card, round_num)

        # Реакция судьи
        reaction = self.court_service.judge_react(game_id, role, card, round_num)
        if reaction:
            self.bot.send_message(chat_id, f"⚖️ <i>{reaction}</i>", parse_mode='HTML')

        game = self.court_service.get_active_game_by_id(game_id)
        if not game:
            return

        if role == 'prosecutor':
            self.bot.send_message(
                chat_id,
                f"🛡️ <b>Защита может ответить.</b> Адвокат или Свидетель — сыграйте карту в личных сообщениях.\n"
                f"(Адвокат осталось: {game['lawyer_cards_left']}, Свидетель: {game['witness_cards_left']})",
                parse_mode='HTML'
            )
        else:
            played_this_round = [p for p in game['played_cards'] if p['round'] == round_num]
            has_prosecution = any(p['role'] == 'prosecutor' for p in played_this_round)
            has_defense = any(p['role'] in ('lawyer', 'witness') for p in played_this_round)

            if has_prosecution and has_defense:
                next_round = round_num + 1
                if next_round > 4:
                    self.bot.send_message(chat_id, "⚖️ <b>Все раунды завершены. Суд удаляется на совещание...</b>", parse_mode='HTML')
                    self._deliver_verdict(game_id, chat_id)
                else:
                    self.court_service.advance_round(game_id, next_round)
                    self.bot.send_message(
                        chat_id,
                        f"⚖️ <b>Раунд {next_round} из 4</b>\nСлово предоставляется ⚔️ Прокурору.",
                        parse_mode='HTML'
                    )

    def _deliver_verdict(self, game_id: int, chat_id: int):
        """Доставить драматичный многосообщный приговор."""
        import time
        parts = self.court_service.generate_verdict(game_id)
        self.court_service.set_status(game_id, 'finished')

        prefixes = [
            "⚖️ <b>Позиция обвинения:</b>",
            "🛡️ <b>Позиция защиты:</b>",
            "🔍 <b>Выводы суда:</b>",
            "🔨 <b>ПРИГОВОР:</b>",
        ]
        for prefix, part in zip(prefixes, parts):
            if part:
                self.bot.send_message(chat_id, f"{prefix}\n\n{part}", parse_mode='HTML')
                time.sleep(2)

        self.court_service.log_message(game_id, 'verdict', "\n---\n".join(parts))

    def _get_bot_username(self) -> str:
        try:
            return self.bot.get_me().username
        except Exception:
            return "бот"
