import logging
import threading
import time
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
        self._bot_username: str | None = None
        self._bot_id: int | None = None
        # Финальное слово: user_id → {game_id, role, chat_id}
        self._pending_final_word: dict[int, dict] = {}
        # Сбор финальных слов по игре: game_id → {statements: {role: text}, needed: set, chat_id}
        self._final_word_state: dict[int, dict] = {}
        # Test mode: game_ids where user is prosecutor and AI plays defense
        self._test_games: set[int] = set()
        # Private DM wait states: user_id → state dict
        self._private_wait: dict[int, dict] = {}
        # Pending speech input: chat_id → {game_id, user_id, role, card, round_num, prompt_msg_id}
        self._pending_speech: dict[int, dict] = {}
        # AI role IDs (fake, never sent DMs)
        self.AI_LAWYER_ID = 0
        self.AI_WITNESS_ID = -1

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
            # Чистим зависший _wait если вдруг остался без активной игры
            self._wait.pop(chat_id, None)

            self.bot.send_message(chat_id, RULES_TEXT, parse_mode='HTML')
            self.bot.send_message(chat_id, "👤 Кого обвиняем? Напишите имя или описание подсудимого (например: «Кот Леопольд», «Юра с 3-го этажа», «ChatGPT»):\n\n<i>Ответьте реплаем на это сообщение.</i>", parse_mode='HTML')
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

        @self.bot.message_handler(commands=['court_test'])
        def cmd_court_test(message):
            if message.chat.type != 'private':
                self.bot.reply_to(message, "Тест-режим работает только в личке с ботом.")
                return
            user_id = message.from_user.id
            self._private_wait[user_id] = {'state': 'waiting_defendant', 'initiator': user_id}
            self.bot.send_message(user_id, "⚖️ <b>Тест-режим суда</b>\n\nТы — Прокурор. AI играет за защиту.\n\nКого обвиняем?", parse_mode='HTML')

        @self.bot.message_handler(func=lambda m: m.chat.type == 'private' and m.from_user.id in self._private_wait)
        def handle_private_wait(message):
            user_id = message.from_user.id
            state_data = self._private_wait.get(user_id)
            if not state_data:
                return
            state = state_data['state']

            if state == 'waiting_defendant':
                defendant = message.text.strip()
                if not defendant or len(defendant) > 200:
                    self.bot.send_message(user_id, "Введите имя подсудимого (до 200 символов).")
                    return
                state_data['defendant'] = defendant
                state_data['state'] = 'waiting_crime'
                self.bot.send_message(user_id, f"📋 Подсудимый: <b>{defendant}</b>\n\nОпишите преступление:", parse_mode='HTML')

            elif state == 'waiting_crime':
                crime = message.text.strip()
                if not crime or len(crime) > 500:
                    self.bot.send_message(user_id, "Опишите преступление (до 500 символов).")
                    return
                defendant = state_data['defendant']
                self._private_wait.pop(user_id, None)
                self.bot.send_message(user_id, "⚖️ Генерирую карты дела...")
                threading.Thread(
                    target=self._start_game_test,
                    args=(user_id, defendant, crime),
                    daemon=True
                ).start()

        @self.bot.message_handler(func=lambda m: m.chat.type == 'private' and m.from_user.id in self._pending_final_word)
        def handle_final_word(message):
            user_id = message.from_user.id
            pending = self._pending_final_word.pop(user_id, None)
            if not pending:
                return
            game_id = pending['game_id']
            role = pending['role']
            chat_id = pending['chat_id']
            statement = message.text.strip()[:500]
            logger.info(f"[COURT] handle_final_word: game={game_id} role={role} user={user_id} statement='{statement[:60]}'")

            self.court_service.log_message(game_id, f'final_{role}', statement)
            self.bot.reply_to(message, "✅ Ваше финальное слово принято судом.")
            role_ru = ROLE_NAMES.get(role, role)
            try:
                self.bot.send_message(chat_id, f"✅ {role_ru} предоставил финальное слово.")
            except Exception:
                pass

            state = self._final_word_state.get(game_id)
            if not state:
                return
            state['statements'][role] = statement
            state['needed'].discard(role)

            if not state['needed']:
                self._final_word_state.pop(game_id, None)
                threading.Thread(
                    target=self._deliver_verdict,
                    args=(game_id, chat_id, state['statements']),
                    daemon=True
                ).start()

        @self.bot.message_handler(func=lambda m: (
            m.chat.type != 'private'
            and m.chat.id in self._pending_speech
            and m.reply_to_message is not None
            and m.reply_to_message.from_user.id == self._get_bot_id()
            and m.from_user.id == self._pending_speech[m.chat.id]['user_id']
        ))
        def handle_speech_input(message):
            chat_id = message.chat.id
            pending = self._pending_speech.pop(chat_id, None)
            if not pending:
                return
            speech = message.text.strip()[:500]
            logger.info(f"[COURT] speech_input: game={pending['game_id']} chat={chat_id} role={pending['role']} user={message.from_user.id} speech='{speech[:60]}'")
            threading.Thread(
                target=self._after_speech_received,
                args=(pending['game_id'], chat_id, pending['role'], pending['card'], pending['round_num'], speech),
                daemon=True
            ).start()

        @self.bot.message_handler(func=lambda m: m.chat.type != 'private' and m.chat.id in self._wait)
        def handle_wait_state(message):
            # Игнорируем команды
            if message.text and message.text.startswith('/'):
                return
            chat_id = message.chat.id
            state_data = self._wait.get(chat_id)
            if not state_data:
                return

            state = state_data['state']

            # Требуем реплай на сообщение бота
            if not message.reply_to_message or message.reply_to_message.from_user.id != self._get_bot_id():
                return

            if state == 'waiting_defendant':
                defendant = message.text.strip()
                if not defendant or len(defendant) > 200:
                    self.bot.reply_to(message, "Введите имя подсудимого (до 200 символов).")
                    return
                state_data['defendant'] = defendant
                state_data['state'] = 'waiting_crime'
                self.bot.send_message(chat_id, f"📋 Подсудимый: <b>{defendant}</b>\n\nТеперь опишите преступление:\n\n<i>Ответьте реплаем на это сообщение.</i>", parse_mode='HTML')

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
                state_data.pop('prompt_msg_id', None)
                self._wait[chat_id] = state_data
                self._send_role_keyboard(chat_id, game_id)

    def _start_game_test(self, user_id: int, defendant: str, crime: str):
        """Запустить тест-игру: пользователь — прокурор, AI — защита."""
        try:
            game_id = self.court_service.create_game(user_id, defendant, crime)
            self.court_service.assign_role(game_id, 'prosecutor', user_id)
            self.court_service.assign_role(game_id, 'lawyer', self.AI_LAWYER_ID)
            self.court_service.assign_role(game_id, 'witness', self.AI_WITNESS_ID)

            prosecutor_cards, lawyer_cards, witness_cards = self.court_service.generate_cards(defendant, crime)
            if not prosecutor_cards:
                self.bot.send_message(user_id, "❌ Ошибка генерации карт. Попробуй /court_test ещё раз.")
                return

            self.court_service.save_cards(game_id, prosecutor_cards, lawyer_cards, witness_cards)
            self.court_service.set_status(game_id, 'in_progress')
            self.court_service.advance_round(game_id, 1)
            self.court_service.log_message(game_id, 'system', f'Дело: {defendant} обвиняется в «{crime}»')
            self._test_games.add(game_id)

            self._send_cards_dm(user_id, game_id, 'prosecutor', prosecutor_cards)
            self.bot.send_message(
                user_id,
                f"⚖️ <b>Раунд 1 из 4</b>\n\nТвой ход, Прокурор. Сыграй карту:",
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"_start_game_test: ошибка: {e}")
            try:
                self.bot.send_message(user_id, "❌ Ошибка запуска тест-игры. Попробуй /court_test ещё раз.")
            except Exception:
                pass

    def _ai_play_defense_test(self, game_id: int, chat_id: int, prosecutor_card: str, round_num: int):
        """AI автоматически разыгрывает карту защиты в тест-режиме."""
        logger.info(f"[COURT] _ai_play_defense_test: game={game_id} chat={chat_id} round={round_num}")
        try:
            logger.info(f"[COURT] _ai_play_defense_test: generating AI defense card")
            card = self.court_service.ai_defense_card(game_id, prosecutor_card, round_num)
            logger.info(f"[COURT] _ai_play_defense_test: AI card='{card[:60]}'")

            role_ru = "🛡️ Адвокат (AI)"

            self.bot.send_message(chat_id, f"🃏 <b>{role_ru}</b> играет карту:\n\n«{card}»", parse_mode='HTML')
            self.court_service.record_played_card(game_id, 'lawyer', card, round_num)
            self.court_service.log_message(game_id, 'lawyer', card, round_num)

            speech = self.court_service.player_argue(game_id, 'lawyer', card, round_num)
            if speech:
                self.bot.send_message(chat_id, f"🛡️ <i>{speech}</i>", parse_mode='HTML')

            reaction = self.court_service.judge_react(game_id, 'lawyer', card, round_num)
            if reaction:
                self.bot.send_message(chat_id, f"⚖️ <i>{reaction}</i>", parse_mode='HTML')

            game = self.court_service.get_active_game_by_id(game_id)
            if not game:
                return

            next_round = round_num + 1
            if next_round > 4:
                logger.info(f"[COURT] _ai_play_defense_test: all rounds done, requesting final words")
                prosecutor_user_id = game['prosecutor_id']
                self.bot.send_message(chat_id, "⚖️ <b>Все раунды завершены.</b>\n\nНапиши своё финальное слово боту в личку:", parse_mode='HTML')
                self._final_word_state[game_id] = {
                    'statements': {},
                    'needed': {'prosecutor', 'lawyer', 'witness'},
                    'chat_id': chat_id,
                }
                # AI защита пишет финальные слова сразу
                for ai_role in ('lawyer', 'witness'):
                    ai_card = self.court_service.ai_defense_card(game_id, "финальное слово", 0)
                    self._final_word_state[game_id]['statements'][ai_role] = ai_card
                    self._final_word_state[game_id]['needed'].discard(ai_role)
                # Прокурор пишет финальное слово в личку
                self._pending_final_word[prosecutor_user_id] = {'game_id': game_id, 'role': 'prosecutor', 'chat_id': chat_id}
                try:
                    self.bot.send_message(prosecutor_user_id, "⚖️ <b>Финальное слово</b>\n\nНапишите ваше финальное заявление (до 500 символов):", parse_mode='HTML')
                except Exception as e:
                    logger.error(f"[COURT] _ai_play_defense_test: не удалось отправить DM прокурору {prosecutor_user_id}: {e}")
                    self._pending_final_word.pop(prosecutor_user_id, None)
                    self._final_word_state[game_id]['statements']['prosecutor'] = ''
                    self._final_word_state[game_id]['needed'].discard('prosecutor')
            else:
                self.court_service.advance_round(game_id, next_round)
                self.bot.send_message(
                    chat_id,
                    f"⚖️ <b>Раунд {next_round} из 4</b>\n\nТвой ход, Прокурор. Сыграй карту:",
                    parse_mode='HTML'
                )
        except Exception as e:
            logger.error(f"_ai_play_defense_test: ошибка: {e}")

    def _send_role_keyboard(self, chat_id: int, game_id: int):
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("⚔️ Прокурор", callback_data=f"court_role:prosecutor:{game_id}"))
        markup.row(types.InlineKeyboardButton("🛡️ Адвокат", callback_data=f"court_role:lawyer:{game_id}"))
        markup.row(types.InlineKeyboardButton("👁️ Свидетель защиты", callback_data=f"court_role:witness:{game_id}"))
        markup.row(types.InlineKeyboardButton("🤖 Соло-тест (я Прокурор, AI защита)", callback_data=f"court_solo:{game_id}"))
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

        @self.bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("court_solo:"))
        def handle_solo_test(call):
            game_id = int(call.data.split(":")[1])
            chat_id = call.message.chat.id
            user_id = call.from_user.id
            user_name = call.from_user.first_name or call.from_user.username or str(user_id)
            logger.info(f"[COURT] solo_test: game={game_id} chat={chat_id} user={user_id} ({user_name})")

            self._wait.pop(chat_id, None)
            self.bot.delete_message(chat_id, call.message.message_id)
            self.bot.answer_callback_query(call.id, "Ты — Прокурор, AI играет защиту!")
            self.bot.send_message(chat_id, f"🤖 <b>Соло-тест:</b> {user_name} — Прокурор, AI — Адвокат и Свидетель.", parse_mode='HTML')

            self.court_service.assign_role(game_id, 'prosecutor', user_id)
            self.court_service.assign_role(game_id, 'lawyer', self.AI_LAWYER_ID)
            self.court_service.assign_role(game_id, 'witness', self.AI_WITNESS_ID)
            self._test_games.add(game_id)

            roles_taken = {'prosecutor': user_id, 'lawyer': self.AI_LAWYER_ID, 'witness': self.AI_WITNESS_ID}
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

            if game['status'] != 'in_progress':
                self.bot.answer_callback_query(call.id, "Игра уже завершена.", show_alert=True)
                return

            # Check it's the player's turn
            current_phase = game.get('current_phase', 'prosecution')
            if role == 'prosecutor' and current_phase != 'prosecution':
                self.bot.answer_callback_query(
                    call.id,
                    "⚖️ Не ваша очередь — суд ещё не передал вам слово!",
                    show_alert=True
                )
                return
            if role in ('lawyer', 'witness') and current_phase != 'defense':
                self.bot.answer_callback_query(
                    call.id,
                    "⚖️ Не ваша очередь — суд ещё не передал вам слово!",
                    show_alert=True
                )
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

            # Защита может сыграть только одну карту за раунд
            if role in ('lawyer', 'witness'):
                current_round = game['current_round']
                defense_played = any(
                    p['role'] in ('lawyer', 'witness') and p['round'] == current_round
                    for p in game['played_cards']
                )
                if defense_played:
                    self.bot.answer_callback_query(call.id, "Защита уже ответила в этом раунде!", show_alert=True)
                    return

            cards_key = f"{role}_cards"
            try:
                card_text = game[cards_key][card_index]
            except (KeyError, IndexError):
                self.bot.answer_callback_query(call.id, "Карта не найдена (устаревшая кнопка).", show_alert=True)
                return

            logger.info(f"[COURT] handle_play_card: game={game_id} role={role} card_index={card_index} user={user_id} card='{card_text[:60]}'")
            self.bot.answer_callback_query(call.id, "Карта сыграна!")
            try:
                new_markup = types.InlineKeyboardMarkup()
                for row in (call.message.reply_markup.keyboard or []):
                    for btn in row:
                        if btn.callback_data != call.data:
                            new_markup.row(types.InlineKeyboardButton(btn.text, callback_data=btn.callback_data))
                self.bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=new_markup)
            except Exception as e:
                logger.warning(f"handle_play_card: не удалось обновить разметку: {e}")

            # Advance phase to speech-waiting (blocks other cards while speech is pending)
            if role == 'prosecutor':
                self.court_service.set_phase(game_id, 'prosecution_speech')
            elif role in ('lawyer', 'witness'):
                self.court_service.set_phase(game_id, 'defense_speech')

            threading.Thread(
                target=self._process_played_card,
                args=(game_id, game['chat_id'], role, card_text, game['current_round']),
                daemon=True
            ).start()

    def _start_game(self, chat_id: int, game_id: int, roles_taken: dict):
        """Сгенерировать карты, отправить в личку, начать раунд 1."""
        required = {'prosecutor', 'lawyer', 'witness'}
        if not required.issubset(roles_taken.keys()):
            logger.error(f"[COURT] _start_game: неверный roles_taken: {roles_taken}")
            return
        logger.info(f"[COURT] _start_game: game={game_id} chat={chat_id} roles={roles_taken}")
        try:
            game = self.court_service.get_active_game_by_id(game_id)
            defendant = game['defendant']
            crime = game['crime']

            self.bot.send_message(chat_id, "⚖️ <b>Состав суда сформирован. Генерирую материалы дела...</b>", parse_mode='HTML')

            logger.info(f"[COURT] _start_game: generating cards for '{defendant}' / '{crime}'")
            prosecutor_cards, lawyer_cards, witness_cards = self.court_service.generate_cards(defendant, crime)
            logger.info(f"[COURT] _start_game: cards generated — prosecutor={len(prosecutor_cards)} lawyer={len(lawyer_cards)} witness={len(witness_cards)}")

            if not prosecutor_cards:
                self.bot.send_message(chat_id, "❌ Ошибка генерации карт. Попробуйте /court ещё раз.")
                self.court_service.set_status(game_id, 'aborted')
                return

            self.court_service.save_cards(game_id, prosecutor_cards, lawyer_cards, witness_cards)
            self.court_service.set_status(game_id, 'in_progress')
            self.court_service.advance_round(game_id, 1)
            self.court_service.log_message(game_id, 'system', f'Дело: {defendant} обвиняется в «{crime}»')
            logger.info(f"[COURT] _start_game: game status=in_progress round=1")

            # Отправляем карты в личку (AI-роли пропускаем)
            self._send_cards_dm(roles_taken['prosecutor'], game_id, 'prosecutor', prosecutor_cards)
            if roles_taken['lawyer'] not in (self.AI_LAWYER_ID, self.AI_WITNESS_ID):
                self._send_cards_dm(roles_taken['lawyer'], game_id, 'lawyer', lawyer_cards, partner_cards=witness_cards, partner_role='witness')
            if roles_taken['witness'] not in (self.AI_LAWYER_ID, self.AI_WITNESS_ID):
                self._send_cards_dm(roles_taken['witness'], game_id, 'witness', witness_cards, partner_cards=lawyer_cards, partner_role='lawyer')

            self.bot.send_message(
                chat_id,
                f"📬 <b>Карты отправлены в личные сообщения.</b>\n\n"
                f"⚖️ <b>Раунд 1 из 4</b>\n"
                f"Слово предоставляется ⚔️ Прокурору. Сыграйте карту в личном чате с ботом.",
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"_start_game: ошибка для game {game_id}: {e}")
            self.court_service.set_status(game_id, 'aborted')
            try:
                self.bot.send_message(chat_id, "❌ Ошибка запуска игры. Попробуйте /court ещё раз.")
            except Exception:
                pass

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
        logger.info(f"[COURT] _process_played_card: game={game_id} chat={chat_id} role={role} round={round_num} card='{card[:60]}'")
        try:
            role_ru = ROLE_NAMES[role]
            self.bot.send_message(chat_id, f"🃏 <b>{role_ru}</b> играет карту:\n\n«{card}»", parse_mode='HTML')
            logger.info(f"[COURT] _process_played_card: card announced in group")

            self.court_service.record_played_card(game_id, role, card, round_num)
            logger.info(f"[COURT] _process_played_card: card recorded in DB")

            game = self.court_service.get_active_game_by_id(game_id)
            if not game:
                logger.error(f"[COURT] _process_played_card: game {game_id} not found after record")
                return
            player_user_id = game[f'{role}_id']
            logger.info(f"[COURT] _process_played_card: player user_id={player_user_id}")

            # Ask player to type their speech
            speech_prompt = self.bot.send_message(
                chat_id,
                f"💬 <b>{role_ru}</b>, опиши свой аргумент — ответь реплаем на это сообщение:",
                parse_mode='HTML'
            )
            logger.info(f"[COURT] _process_played_card: speech prompt sent msg_id={speech_prompt.message_id}")
            self._pending_speech[chat_id] = {
                'game_id': game_id,
                'user_id': player_user_id,
                'role': role,
                'card': card,
                'round_num': round_num,
                'prompt_msg_id': speech_prompt.message_id,
            }
            logger.info(f"[COURT] _process_played_card: pending_speech set for chat={chat_id} user={player_user_id}")
        except Exception as e:
            logger.error(f"[COURT] _process_played_card: ошибка для game {game_id}: {e}", exc_info=True)
            try:
                self.bot.send_message(chat_id, "⚠️ Ошибка при обработке карты. Попробуйте сыграть карту ещё раз.")
            except Exception:
                pass

    def _after_speech_received(self, game_id: int, chat_id: int, role: str, card: str, round_num: int, speech: str):
        """Обработать речь игрока: залогировать, показать, запустить реакцию судьи, продвинуть состояние."""
        logger.info(f"[COURT] _after_speech_received: game={game_id} chat={chat_id} role={role} round={round_num} speech='{speech[:60]}'")
        try:
            self.court_service.log_message(game_id, role, speech, round_num)
            role_icon = "⚔️" if role == "prosecutor" else ("🛡️" if role == "lawyer" else "👁️")
            self.bot.send_message(chat_id, f"{role_icon} <i>{speech}</i>", parse_mode='HTML')

            self.bot.send_chat_action(chat_id, 'typing')

            logger.info(f"[COURT] _after_speech_received: calling judge_react")
            reaction, signal = self.court_service.judge_react(game_id, role, card, round_num)
            logger.info(f"[COURT] _after_speech_received: judge reaction='{str(reaction)[:80]}' signal={signal}")

            if reaction:
                judge_msg = self.bot.send_message(chat_id, f"⚖️ <i>{reaction}</i>", parse_mode='HTML')
                self.court_service.set_last_judge_msg(game_id, judge_msg.message_id)

            self._handle_judge_signal(game_id, chat_id, signal, round_num)

        except Exception as e:
            logger.error(f"[COURT] _after_speech_received: ошибка для game {game_id}: {e}", exc_info=True)

    def _handle_judge_signal(self, game_id: int, chat_id: int, signal: str | None, round_num: int):
        """Двигает игровой стейт по сигналу судьи."""
        if signal == "ВОПРОС":
            self.court_service.set_phase(game_id, 'judge')
            self._start_fallback_timer(game_id, chat_id, round_num)

        elif signal == "ЗАЩИТА_ВАШ_ХОД":
            self.court_service.set_phase(game_id, 'defense')
            game = self.court_service.get_active_game_by_id(game_id)
            if game:
                self.bot.send_message(
                    chat_id,
                    f"🛡️ <b>Защита, ваш ответ!</b>\n"
                    f"(Адвокат осталось: {game['lawyer_cards_left']}, Свидетель: {game['witness_cards_left']})",
                    parse_mode='HTML'
                )

        elif signal == "ПРОКУРОР_ВАШ_ХОД":
            next_round = round_num + 1
            self.court_service.advance_round(game_id, next_round)
            self.court_service.set_phase(game_id, 'prosecution')
            self.bot.send_message(
                chat_id,
                f"⚖️ <b>Раунд {next_round} из 4</b>\n⚔️ Прокурор, ваш ход. Сыграйте карту в личке.",
                parse_mode='HTML'
            )

        elif signal == "ФИНАЛ":
            self.court_service.set_phase(game_id, 'final')
            self.bot.send_message(
                chat_id,
                "⚖️ <b>Все раунды завершены.</b>\n\nСуд предоставляет каждой из сторон <b>последнее слово</b>. Напишите ваше финальное заявление боту в личку.",
                parse_mode='HTML'
            )
            self._request_final_words(game_id, chat_id)

        else:
            # LLM did not return a tag — log warning and start fallback timer
            logger.warning(f"[COURT] _handle_judge_signal: no signal for game={game_id} round={round_num}, starting fallback")
            self._start_fallback_timer(game_id, chat_id, round_num)

    def _start_fallback_timer(self, game_id: int, chat_id: int, round_num: int):
        """Stub — будет реализован в следующем шаге."""
        pass

    def _request_final_words(self, game_id: int, chat_id: int):
        """Запросить финальное слово у каждого игрока в личку."""
        logger.info(f"[COURT] _request_final_words: game={game_id} chat={chat_id}")
        game = self.court_service.get_active_game_by_id(game_id)
        if not game:
            logger.error(f"[COURT] _request_final_words: game {game_id} not found")
            return

        role_user_map = {
            'prosecutor': game['prosecutor_id'],
            'lawyer': game['lawyer_id'],
            'witness': game['witness_id'],
        }

        self._final_word_state[game_id] = {
            'statements': {},
            'needed': set(role_user_map.keys()),
            'chat_id': chat_id,
        }

        for role, user_id in role_user_map.items():
            role_ru = ROLE_NAMES[role]
            self._pending_final_word[user_id] = {'game_id': game_id, 'role': role, 'chat_id': chat_id}
            try:
                self.bot.send_message(
                    user_id,
                    f"⚖️ <b>Финальное слово</b>\n\nСуд предоставляет вам, {role_ru}, последнее слово.\n"
                    f"Напишите ваше финальное заявление (до 500 символов):",
                    parse_mode='HTML'
                )
                self.bot.send_message(chat_id, f"⏳ Ожидаем финальное слово от {role_ru}...", parse_mode='HTML')
            except Exception as e:
                logger.error(f"_request_final_words: не удалось отправить {user_id}: {e}")
                self._pending_final_word.pop(user_id, None)
                self._final_word_state[game_id]['statements'][role] = ''
                self._final_word_state[game_id]['needed'].discard(role)

        # Если все DM упали — сразу к приговору
        state = self._final_word_state.get(game_id)
        if state and not state['needed']:
            self._final_word_state.pop(game_id, None)
            threading.Thread(target=self._deliver_verdict, args=(game_id, chat_id, {}), daemon=True).start()

    def _deliver_verdict(self, game_id: int, chat_id: int, final_statements: dict = None):
        """Доставить драматичный многосообщный приговор."""
        logger.info(f"[COURT] _deliver_verdict: game={game_id} chat={chat_id} statements={list((final_statements or {}).keys())}")
        try:
            self.bot.send_message(chat_id, "⚖️ Судья удаляется на совещание... 🤔", parse_mode='HTML')
            logger.info(f"[COURT] _deliver_verdict: generating verdict via LLM")
            parts = self.court_service.generate_verdict(game_id, final_statements or {})
            logger.info(f"[COURT] _deliver_verdict: verdict generated, {len(parts)} parts")
            self.court_service.save_verdict(game_id, "\n---\n".join(parts))

            prefixes = [
                "⚖️ <b>Позиция обвинения:</b>",
                "🛡️ <b>Позиция защиты:</b>",
                "🔍 <b>Выводы суда:</b>",
                "🔨 <b>ПРИГОВОР:</b>",
            ]
            for prefix, part in zip(prefixes, parts + [""] * 4):
                if part:
                    self.bot.send_message(chat_id, f"{prefix}\n\n{part}", parse_mode='HTML')
                    time.sleep(2)
        except Exception as e:
            logger.error(f"_deliver_verdict: ошибка для game {game_id}: {e}")
            self.court_service.set_status(game_id, 'finished')
            try:
                self.bot.send_message(chat_id, "⚠️ Ошибка при вынесении приговора. Заседание завершено.")
            except Exception:
                pass

    def _get_bot_id(self) -> int:
        if not self._bot_id:
            try:
                self._bot_id = self.bot.get_me().id
            except Exception:
                return -1
        return self._bot_id

    def _get_bot_username(self) -> str:
        if not self._bot_username:
            try:
                me = self.bot.get_me()
                self._bot_username = me.username
                self._bot_id = me.id
            except Exception:
                return "бот"
        return self._bot_username
