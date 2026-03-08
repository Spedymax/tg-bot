import asyncio
import logging
from aiogram import Router, F, Bot
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from services.court_service import CourtService
from states.court import CourtStates

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
        # Group-scoped setup state: chat_id → {'state': str, 'game_id': int, ...}
        # Kept as dict because any group member can respond (FSMContext is per user).
        self._wait: dict[int, dict] = {}
        self._bot_username: str | None = None
        self._bot_id: int | None = None
        # Сбор финальных слов по игре: game_id → {statements: {role: text}, needed: set, chat_id}
        self._final_word_state: dict[int, dict] = {}
        # Test mode: game_ids where user is prosecutor and AI plays defense
        self._test_games: set[int] = set()
        # Pending speech input: chat_id → {game_id, user_id, role, card, round_num, prompt_msg_id}
        self._pending_speech: dict[int, dict] = {}
        # Fallback timers: game_id → asyncio.Task
        self._fallback_timers: dict[int, asyncio.Task] = {}
        # AI role IDs (fake, never sent DMs)
        self.AI_LAWYER_ID = 0
        self.AI_WITNESS_ID = -1
        # Per-game locks to prevent simultaneous card plays
        self._game_locks: dict[int, asyncio.Lock] = {}
        # Track chats with active court games (for filter efficiency)
        self._active_game_chats: set[int] = set()

        self.router = Router()
        self._register()

    def _register(self):

        # ── Group commands ────────────────────────────────────────────────────

        @self.router.message(Command('court', 'sud'))
        async def cmd_court(message: Message):
            if message.chat.type == 'private':
                await message.reply("Эта команда работает только в групповом чате.")
                return
            chat_id = message.chat.id
            existing = await asyncio.to_thread(self.court_service.get_active_game, chat_id)
            if existing:
                await message.reply("⚖️ Заседание уже идёт! Используй /court_stop чтобы завершить.")
                return
            # Чистим зависший _wait если вдруг остался без активной игры
            self._wait.pop(chat_id, None)

            await self.bot.send_message(chat_id, RULES_TEXT, parse_mode='HTML')
            await self.bot.send_message(
                chat_id,
                "👤 Кого обвиняем? Напишите имя или описание подсудимого (например: «Кот Леопольд», «Юра с 3-го этажа», «ChatGPT»):\n\n<i>Ответьте реплаем на это сообщение.</i>",
                parse_mode='HTML',
            )
            self._wait[chat_id] = {'state': 'waiting_defendant', 'initiator': message.from_user.id}

        @self.router.message(Command('court_stop', 'sud_stop'))
        async def cmd_court_stop(message: Message):
            chat_id = message.chat.id
            game = await asyncio.to_thread(self.court_service.get_active_game, chat_id)
            if not game:
                await message.reply("Активного заседания нет.")
                return
            await asyncio.to_thread(self.court_service.set_status, game['id'], 'aborted')
            self._game_locks.pop(game['id'], None)
            self._active_game_chats.discard(chat_id)
            old_task = self._fallback_timers.pop(game['id'], None)
            if old_task:
                old_task.cancel()
            self._wait.pop(chat_id, None)
            await self.bot.send_message(chat_id, "⚖️ Заседание досрочно прекращено.")

        # ── Private test mode (FSMContext-based) ──────────────────────────────

        @self.router.message(Command('court_test'))
        async def cmd_court_test(message: Message, state: FSMContext):
            if message.chat.type != 'private':
                await message.reply("Тест-режим работает только в личке с ботом.")
                return
            await state.set_state(CourtStates.private_waiting_defendant)
            await state.update_data(initiator=message.from_user.id)
            await self.bot.send_message(
                message.from_user.id,
                "⚖️ <b>Тест-режим суда</b>\n\nТы — Прокурор. AI играет за защиту.\n\nКого обвиняем?",
                parse_mode='HTML',
            )

        @self.router.message(CourtStates.private_waiting_defendant)
        async def handle_private_waiting_defendant(message: Message, state: FSMContext):
            user_id = message.from_user.id
            defendant = (message.text or "").strip()
            if not defendant or len(defendant) > 200:
                await self.bot.send_message(user_id, "Введите имя подсудимого (до 200 символов).")
                return
            await state.update_data(defendant=defendant)
            await state.set_state(CourtStates.private_waiting_crime)
            await self.bot.send_message(
                user_id,
                f"📋 Подсудимый: <b>{defendant}</b>\n\nОпишите преступление:",
                parse_mode='HTML',
            )

        @self.router.message(CourtStates.private_waiting_crime)
        async def handle_private_waiting_crime(message: Message, state: FSMContext):
            user_id = message.from_user.id
            crime = (message.text or "").strip()
            if not crime or len(crime) > 500:
                await self.bot.send_message(user_id, "Опишите преступление (до 500 символов).")
                return
            data = await state.get_data()
            defendant = data['defendant']
            await state.clear()
            await self.bot.send_message(user_id, "⚖️ Генерирую карты дела...")
            asyncio.create_task(self._start_game_test(user_id, defendant, crime))

        # ── Private final word (FSMContext-based) ────────────────────────────

        @self.router.message(CourtStates.waiting_final_word)
        async def handle_final_word(message: Message, state: FSMContext):
            user_id = message.from_user.id
            data = await state.get_data()
            await state.clear()

            game_id = data['game_id']
            role = data['role']
            chat_id = data['chat_id']
            statement = (message.text or "").strip()[:500]
            logger.info(f"[COURT] handle_final_word: game={game_id} role={role} user={user_id} statement='{statement[:60]}'")

            await asyncio.to_thread(self.court_service.log_message, game_id, f'final_{role}', statement)
            await message.reply("✅ Ваше финальное слово принято судом.")
            role_ru = ROLE_NAMES.get(role, role)
            try:
                await self.bot.send_message(chat_id, f"✅ {role_ru} предоставил финальное слово.")
            except Exception:
                pass

            fw_state = self._final_word_state.get(game_id)
            if not fw_state:
                return
            fw_state['statements'][role] = statement
            fw_state['needed'].discard(role)

            if not fw_state['needed']:
                self._final_word_state.pop(game_id, None)
                asyncio.create_task(self._deliver_verdict(game_id, chat_id, fw_state['statements']))

        # ── Group reply handler: speech input OR judge reply (merged to avoid aiogram routing conflict) ──

        @self.router.message(
            F.chat.type.in_({'group', 'supergroup'}),
            F.reply_to_message.as_('reply'),
            F.func(lambda m, self=self: (
                self._bot_id is not None
                and m.reply_to_message is not None
                and m.reply_to_message.from_user is not None
                and m.reply_to_message.from_user.id == self._bot_id
                and (m.chat.id in self._pending_speech
                     or m.chat.id in self._active_game_chats)
            )),
        )
        async def handle_group_reply(message: Message, reply: Message):
            chat_id = message.chat.id

            # Path 1: speech input (player arguing after playing a card)
            pending = self._pending_speech.get(chat_id)
            if pending and message.from_user.id == pending['user_id']:
                self._pending_speech.pop(chat_id, None)
                speech = (message.text or "").strip()[:500]
                logger.info(
                    f"[COURT] speech_input: game={pending['game_id']} chat={chat_id} "
                    f"role={pending['role']} user={message.from_user.id} speech='{speech[:60]}'"
                )
                asyncio.create_task(
                    self._after_speech_received(
                        pending['game_id'], chat_id, pending['role'],
                        pending['card'], pending['round_num'], speech,
                    )
                )
                return

            # Path 2: judge reply (player answering a judge question)
            if chat_id in self._pending_speech:
                return  # speech pending for another user — don't interfere
            game = await asyncio.to_thread(self.court_service.get_active_game, chat_id)
            if not game or game['status'] != 'in_progress':
                return

            # Only trigger if replying to the last judge message
            if reply.message_id != game.get('last_judge_msg_id'):
                return

            user_id = message.from_user.id
            role = None
            if user_id == game['prosecutor_id']:
                role = 'prosecutor'
            elif user_id == game['lawyer_id']:
                role = 'lawyer'
            elif user_id == game['witness_id']:
                role = 'witness'

            if not role:
                return

            reply_text = (message.text or "").strip()[:500]
            if not reply_text:
                return

            logger.info(f"[COURT] handle_judge_reply: game={game['id']} role={role} user={user_id} text='{reply_text[:60]}'")

            old_task = self._fallback_timers.pop(game['id'], None)
            if old_task:
                old_task.cancel()

            asyncio.create_task(
                self._process_judge_reply(game['id'], chat_id, role, reply_text, game['current_round'])
            )

        # ── Group wait state (defendant/crime input, dict-based) ──────────────

        @self.router.message(
            F.chat.type.in_({'group', 'supergroup'}),
            F.func(lambda m, self=self: (
                m.chat.id in self._wait
                and not (m.text and m.text.startswith('/'))
            )),
        )
        async def handle_wait_state(message: Message):
            chat_id = message.chat.id
            state_data = self._wait.get(chat_id)
            if not state_data:
                return

            state = state_data['state']

            # Require reply to bot's message
            bot_id = await self._get_bot_id()
            if (
                not message.reply_to_message
                or message.reply_to_message.from_user is None
                or message.reply_to_message.from_user.id != bot_id
            ):
                return

            if state == 'waiting_defendant':
                defendant = (message.text or "").strip()
                if not defendant or len(defendant) > 200:
                    await message.reply("Введите имя подсудимого (до 200 символов).")
                    return
                state_data['defendant'] = defendant
                state_data['state'] = 'waiting_crime'
                await self.bot.send_message(
                    chat_id,
                    f"📋 Подсудимый: <b>{defendant}</b>\n\nТеперь опишите преступление:\n\n<i>Ответьте реплаем на это сообщение.</i>",
                    parse_mode='HTML',
                )

            elif state == 'waiting_crime':
                crime = (message.text or "").strip()
                if not crime or len(crime) > 500:
                    await message.reply("Опишите преступление (до 500 символов).")
                    return
                defendant = state_data['defendant']
                game_id = await asyncio.to_thread(
                    self.court_service.create_game, chat_id, defendant, crime
                )
                state_data['game_id'] = game_id
                state_data['state'] = 'role_selection'
                state_data['roles_taken'] = {}
                state_data.pop('prompt_msg_id', None)
                self._wait[chat_id] = state_data
                await self._send_role_keyboard(chat_id, game_id)

        # ── Callback handlers ─────────────────────────────────────────────────

        @self.router.callback_query(F.data.startswith("court_role:"))
        async def handle_role_selection(call: CallbackQuery):
            _, role, game_id_str = call.data.split(":")
            game_id = int(game_id_str)
            chat_id = call.message.chat.id
            user_id = call.from_user.id
            user_name = call.from_user.first_name or call.from_user.username or str(user_id)

            state_data = self._wait.get(chat_id, {})
            roles_taken = state_data.get('roles_taken', {})

            if role in roles_taken:
                await call.answer("Эта роль уже занята!", show_alert=True)
                return
            if user_id in roles_taken.values():
                await call.answer("Ты уже выбрал роль!", show_alert=True)
                return

            roles_taken[role] = user_id
            state_data['roles_taken'] = roles_taken
            await asyncio.to_thread(self.court_service.assign_role, game_id, role, user_id)

            remaining_roles = [r for r in ("prosecutor", "lawyer", "witness") if r not in roles_taken]
            if remaining_roles:
                markup = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=ROLE_NAMES[r], callback_data=f"court_role:{r}:{game_id}")]
                    for r in remaining_roles
                ])
                await call.message.edit_reply_markup(reply_markup=markup)
            else:
                await call.message.delete()

            role_ru = ROLE_NAMES[role]
            await self.bot.send_message(chat_id, f"✅ <b>{user_name}</b> берёт роль {role_ru}", parse_mode='HTML')
            await call.answer(f"Ты {role_ru}!")

            if len(roles_taken) == 3:
                self._wait.pop(chat_id, None)
                asyncio.create_task(self._start_game(chat_id, game_id, roles_taken))

        @self.router.callback_query(F.data.startswith("court_solo:"))
        async def handle_solo_test(call: CallbackQuery):
            game_id = int(call.data.split(":")[1])
            chat_id = call.message.chat.id
            user_id = call.from_user.id
            user_name = call.from_user.first_name or call.from_user.username or str(user_id)
            logger.info(f"[COURT] solo_test: game={game_id} chat={chat_id} user={user_id} ({user_name})")

            self._wait.pop(chat_id, None)
            await call.message.delete()
            await call.answer("Ты — Прокурор, AI играет защиту!")
            await self.bot.send_message(
                chat_id,
                f"🤖 <b>Соло-тест:</b> {user_name} — Прокурор, AI — Адвокат и Свидетель.",
                parse_mode='HTML',
            )

            await asyncio.to_thread(self.court_service.assign_role, game_id, 'prosecutor', user_id)
            await asyncio.to_thread(self.court_service.assign_role, game_id, 'lawyer', self.AI_LAWYER_ID)
            await asyncio.to_thread(self.court_service.assign_role, game_id, 'witness', self.AI_WITNESS_ID)
            self._test_games.add(game_id)

            roles_taken = {'prosecutor': user_id, 'lawyer': self.AI_LAWYER_ID, 'witness': self.AI_WITNESS_ID}
            asyncio.create_task(self._start_game(chat_id, game_id, roles_taken))

        @self.router.callback_query(F.data.startswith("court_play:"))
        async def handle_play_card(call: CallbackQuery):
            parts = call.data.split(":", 3)
            game_id, role, card_index = int(parts[1]), parts[2], int(parts[3])
            user_id = call.from_user.id

            game = await asyncio.to_thread(self.court_service.get_active_game_by_id, game_id)
            if not game:
                await call.answer("Игра не найдена.", show_alert=True)
                return

            if game['status'] != 'in_progress':
                await call.answer("Игра уже завершена.", show_alert=True)
                return

            lock = self._game_locks.setdefault(game_id, asyncio.Lock())
            async with lock:
                game = await asyncio.to_thread(self.court_service.get_active_game_by_id, game_id)
                if not game or game['status'] != 'in_progress':
                    await call.answer("Игра уже завершена.", show_alert=True)
                    return

                current_phase = game.get('current_phase', 'prosecution')
                if role == 'prosecutor' and current_phase != 'prosecution':
                    await call.answer(
                        "⚖️ Не ваша очередь — суд ещё не передал вам слово!",
                        show_alert=True,
                    )
                    return
                if role in ('lawyer', 'witness') and current_phase != 'defense':
                    await call.answer(
                        "⚖️ Не ваша очередь — суд ещё не передал вам слово!",
                        show_alert=True,
                    )
                    return

                expected_role_id = game[f"{role}_id"]
                if user_id != expected_role_id:
                    await call.answer("Сейчас не твой ход!", show_alert=True)
                    return

                cards_left_key = f"{role}_cards_left"
                if game[cards_left_key] <= 0:
                    await call.answer("Ты уже сыграл все свои карты!", show_alert=True)
                    return

                if role in ('lawyer', 'witness'):
                    current_round = game['current_round']
                    played_defense_role = next(
                        (p['role'] for p in game['played_cards']
                         if p['role'] in ('lawyer', 'witness') and p['round'] == current_round),
                        None,
                    )
                    if played_defense_role is not None:
                        who = "🛡️ Адвокат" if played_defense_role == 'lawyer' else "👁️ Свидетель"
                        await call.answer(f"{who} уже ответил в этом раунде!", show_alert=True)
                        return

                cards_key = f"{role}_cards"
                try:
                    card_text = game[cards_key][card_index]
                except (KeyError, IndexError):
                    await call.answer("Карта не найдена (устаревшая кнопка).", show_alert=True)
                    return

                logger.info(
                    f"[COURT] handle_play_card: game={game_id} role={role} "
                    f"card_index={card_index} user={user_id} card='{card_text[:60]}'"
                )

                if role == 'prosecutor':
                    await asyncio.to_thread(self.court_service.set_phase, game_id, 'prosecution_speech')
                elif role in ('lawyer', 'witness'):
                    await asyncio.to_thread(self.court_service.set_phase, game_id, 'defense_speech')

            # UI updates outside the lock
            await call.answer("Карта сыграна!")
            try:
                existing_keyboard = call.message.reply_markup.inline_keyboard if call.message.reply_markup else []
                new_rows = [
                    row for row in existing_keyboard
                    if not any(btn.callback_data == call.data for btn in row)
                ]
                new_markup = InlineKeyboardMarkup(inline_keyboard=new_rows) if new_rows else None
                await call.message.edit_reply_markup(reply_markup=new_markup)
            except Exception as e:
                logger.warning(f"handle_play_card: не удалось обновить разметку: {e}")

            asyncio.create_task(
                self._process_played_card(game_id, game['chat_id'], role, card_text, game['current_round'])
            )

    # ── Internal game logic (all async) ──────────────────────────────────────

    async def _send_role_keyboard(self, chat_id: int, game_id: int):
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚔️ Прокурор", callback_data=f"court_role:prosecutor:{game_id}")],
            [InlineKeyboardButton(text="🛡️ Адвокат", callback_data=f"court_role:lawyer:{game_id}")],
            [InlineKeyboardButton(text="👁️ Свидетель защиты", callback_data=f"court_role:witness:{game_id}")],
            [InlineKeyboardButton(text="🤖 Соло-тест (я Прокурор, AI защита)", callback_data=f"court_solo:{game_id}")],
        ])
        await self.bot.send_message(
            chat_id,
            "⚖️ Выберите роль для участия в заседании:",
            reply_markup=markup,
        )

    async def _start_game_test(self, user_id: int, defendant: str, crime: str):
        """Запустить тест-игру: пользователь — прокурор, AI — защита."""
        try:
            game_id = await asyncio.to_thread(self.court_service.create_game, user_id, defendant, crime)
            await asyncio.to_thread(self.court_service.assign_role, game_id, 'prosecutor', user_id)
            await asyncio.to_thread(self.court_service.assign_role, game_id, 'lawyer', self.AI_LAWYER_ID)
            await asyncio.to_thread(self.court_service.assign_role, game_id, 'witness', self.AI_WITNESS_ID)

            prosecutor_cards, lawyer_cards, witness_cards = await asyncio.to_thread(
                self.court_service.generate_cards, defendant, crime
            )
            if not prosecutor_cards:
                await self.bot.send_message(user_id, "❌ Ошибка генерации карт. Попробуй /court_test ещё раз.")
                return

            await asyncio.to_thread(self.court_service.save_cards, game_id, prosecutor_cards, lawyer_cards, witness_cards)
            await asyncio.to_thread(self.court_service.set_status, game_id, 'in_progress')
            await asyncio.to_thread(self.court_service.advance_round, game_id, 1)
            await asyncio.to_thread(self.court_service.set_phase, game_id, 'prosecution')
            await asyncio.to_thread(self.court_service.log_message, game_id, 'system', f'Дело: {defendant} обвиняется в «{crime}»')
            self._test_games.add(game_id)

            await self._send_cards_dm(user_id, game_id, 'prosecutor', prosecutor_cards)
            await self.bot.send_message(
                user_id,
                f"⚖️ <b>Раунд 1 из 4</b>\n\nТвой ход, Прокурор. Сыграй карту:",
                parse_mode='HTML',
            )
        except Exception as e:
            logger.error(f"_start_game_test: ошибка: {e}")
            try:
                await self.bot.send_message(user_id, "❌ Ошибка запуска тест-игры. Попробуй /court_test ещё раз.")
            except Exception:
                pass

    async def _ai_play_defense_test(self, game_id: int, chat_id: int, prosecutor_card: str, round_num: int):
        """AI автоматически разыгрывает карту защиты в тест-режиме."""
        logger.info(f"[COURT] _ai_play_defense_test: game={game_id} chat={chat_id} round={round_num}")
        try:
            logger.info(f"[COURT] _ai_play_defense_test: generating AI defense card")
            card = await asyncio.to_thread(self.court_service.ai_defense_card, game_id, prosecutor_card, round_num)
            logger.info(f"[COURT] _ai_play_defense_test: AI card='{card[:60]}'")

            await self.bot.send_message(chat_id, f"🃏 <b>🛡️ Адвокат (AI)</b> играет карту:\n\n«{card}»", parse_mode='HTML')
            await asyncio.to_thread(self.court_service.record_played_card, game_id, 'lawyer', card, round_num)
            await asyncio.to_thread(self.court_service.log_message, game_id, 'lawyer', card, round_num)
            await asyncio.to_thread(self.court_service.set_phase, game_id, 'defense_speech')

            speech = await asyncio.to_thread(self.court_service.player_argue, game_id, 'lawyer', card, round_num)
            if speech:
                await self.bot.send_message(chat_id, f"🛡️ <i>{speech}</i>", parse_mode='HTML')

            reaction, signal = await asyncio.to_thread(self.court_service.judge_react, game_id, 'lawyer', card, round_num)
            if reaction:
                judge_msg = await self.bot.send_message(chat_id, f"⚖️ <i>{reaction}</i>", parse_mode='HTML')
                await asyncio.to_thread(self.court_service.set_last_judge_msg, game_id, judge_msg.message_id)

            if signal in ("ВОПРОС", None):
                signal = "ПРОКУРОР_ВАШ_ХОД" if round_num < 4 else "ФИНАЛ"

            await self._handle_judge_signal(game_id, chat_id, signal, round_num)

        except Exception as e:
            logger.error(f"_ai_play_defense_test: ошибка: {e}", exc_info=True)

    async def _start_game(self, chat_id: int, game_id: int, roles_taken: dict):
        """Сгенерировать карты, отправить в личку, начать раунд 1."""
        required = {'prosecutor', 'lawyer', 'witness'}
        if not required.issubset(roles_taken.keys()):
            logger.error(f"[COURT] _start_game: неверный roles_taken: {roles_taken}")
            return
        logger.info(f"[COURT] _start_game: game={game_id} chat={chat_id} roles={roles_taken}")
        try:
            game = await asyncio.to_thread(self.court_service.get_active_game_by_id, game_id)
            defendant = game['defendant']
            crime = game['crime']

            await self.bot.send_message(chat_id, "⚖️ <b>Состав суда сформирован. Генерирую материалы дела...</b>", parse_mode='HTML')

            logger.info(f"[COURT] _start_game: generating cards for '{defendant}' / '{crime}'")
            prosecutor_cards, lawyer_cards, witness_cards = await asyncio.to_thread(
                self.court_service.generate_cards, defendant, crime
            )
            logger.info(
                f"[COURT] _start_game: cards generated — "
                f"prosecutor={len(prosecutor_cards)} lawyer={len(lawyer_cards)} witness={len(witness_cards)}"
            )

            if not prosecutor_cards:
                await self.bot.send_message(chat_id, "❌ Ошибка генерации карт. Попробуйте /court ещё раз.")
                await asyncio.to_thread(self.court_service.set_status, game_id, 'aborted')
                return

            await asyncio.to_thread(self.court_service.save_cards, game_id, prosecutor_cards, lawyer_cards, witness_cards)
            await asyncio.to_thread(self.court_service.set_status, game_id, 'in_progress')
            self._active_game_chats.add(chat_id)
            await asyncio.to_thread(self.court_service.advance_round, game_id, 1)
            await asyncio.to_thread(self.court_service.log_message, game_id, 'system', f'Дело: {defendant} обвиняется в «{crime}»')
            logger.info(f"[COURT] _start_game: game status=in_progress round=1")

            await self._send_cards_dm(roles_taken['prosecutor'], game_id, 'prosecutor', prosecutor_cards)
            if roles_taken['lawyer'] not in (self.AI_LAWYER_ID, self.AI_WITNESS_ID):
                await self._send_cards_dm(
                    roles_taken['lawyer'], game_id, 'lawyer', lawyer_cards,
                    partner_cards=witness_cards, partner_role='witness',
                )
            if roles_taken['witness'] not in (self.AI_LAWYER_ID, self.AI_WITNESS_ID):
                await self._send_cards_dm(
                    roles_taken['witness'], game_id, 'witness', witness_cards,
                    partner_cards=lawyer_cards, partner_role='lawyer',
                )

            await self.bot.send_message(
                chat_id,
                f"📬 <b>Карты отправлены в личные сообщения.</b>\n\n"
                f"⚖️ <b>Раунд 1 из 4</b>\n"
                f"Слово предоставляется ⚔️ Прокурору. Сыграйте карту в личном чате с ботом.",
                parse_mode='HTML',
            )
        except Exception as e:
            logger.error(f"_start_game: ошибка для game {game_id}: {e}")
            await asyncio.to_thread(self.court_service.set_status, game_id, 'aborted')
            try:
                await self.bot.send_message(chat_id, "❌ Ошибка запуска игры. Попробуйте /court ещё раз.")
            except Exception:
                pass

    async def _send_cards_dm(self, user_id: int, game_id: int, role: str, cards: list,
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

        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"🃏 {card[:40]}{'…' if len(card) > 40 else ''}",
                callback_data=f"court_play:{game_id}:{role}:{i}",
            )]
            for i, card in enumerate(cards)
        ])

        try:
            await self.bot.send_message(user_id, text, parse_mode='HTML', reply_markup=markup)
        except Exception as e:
            logger.error(f"CourtHandlers: не удалось отправить личку {user_id}: {e}")
            game = await asyncio.to_thread(self.court_service.get_active_game_by_id, game_id)
            if game:
                await self.bot.send_message(
                    game['chat_id'],
                    f"⚠️ Не удалось отправить карты игроку. "
                    f"Пожалуйста, напишите боту в личку (@{await self._get_bot_username()}) и повторите /court.",
                )

    async def _process_played_card(self, game_id: int, chat_id: int, role: str, card: str, round_num: int):
        """Объявляем сыгранную карту, судья реагирует, двигаем состояние."""
        logger.info(f"[COURT] _process_played_card: game={game_id} chat={chat_id} role={role} round={round_num} card='{card[:60]}'")
        try:
            role_ru = ROLE_NAMES[role]
            await self.bot.send_message(chat_id, f"🃏 <b>{role_ru}</b> играет карту:\n\n«{card}»", parse_mode='HTML')
            logger.info(f"[COURT] _process_played_card: card announced in group")

            await asyncio.to_thread(self.court_service.record_played_card, game_id, role, card, round_num)
            logger.info(f"[COURT] _process_played_card: card recorded in DB")

            game = await asyncio.to_thread(self.court_service.get_active_game_by_id, game_id)
            if not game:
                logger.error(f"[COURT] _process_played_card: game {game_id} not found after record")
                return
            player_user_id = game[f'{role}_id']
            logger.info(f"[COURT] _process_played_card: player user_id={player_user_id}")

            speech_prompt = await self.bot.send_message(
                chat_id,
                f"💬 <b>{role_ru}</b>, опиши свой аргумент — ответь реплаем на это сообщение:",
                parse_mode='HTML',
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
                await self.bot.send_message(chat_id, "⚠️ Ошибка при обработке карты. Попробуйте сыграть карту ещё раз.")
            except Exception:
                pass

    async def _after_speech_received(self, game_id: int, chat_id: int, role: str, card: str, round_num: int, speech: str):
        """Обработать речь игрока: залогировать, показать, запустить реакцию судьи, продвинуть состояние."""
        logger.info(f"[COURT] _after_speech_received: game={game_id} chat={chat_id} role={role} round={round_num} speech='{speech[:60]}'")
        try:
            await asyncio.to_thread(self.court_service.log_message, game_id, role, speech, round_num)
            role_icon = "⚔️" if role == "prosecutor" else ("🛡️" if role == "lawyer" else "👁️")
            await self.bot.send_message(chat_id, f"{role_icon} <i>{speech}</i>", parse_mode='HTML')

            await self.bot.send_chat_action(chat_id, 'typing')

            logger.info(f"[COURT] _after_speech_received: calling judge_react")
            reaction, signal = await asyncio.to_thread(self.court_service.judge_react, game_id, role, card, round_num)
            logger.info(f"[COURT] _after_speech_received: judge reaction='{str(reaction)[:80]}' signal={signal}")

            if reaction:
                judge_msg = await self.bot.send_message(chat_id, f"⚖️ <i>{reaction}</i>", parse_mode='HTML')
                await asyncio.to_thread(self.court_service.set_last_judge_msg, game_id, judge_msg.message_id)

            await self._handle_judge_signal(game_id, chat_id, signal, round_num)

        except Exception as e:
            logger.error(f"[COURT] _after_speech_received: ошибка для game {game_id}: {e}", exc_info=True)

    async def _handle_judge_signal(self, game_id: int, chat_id: int, signal: str | None, round_num: int):
        """Двигает игровой стейт по сигналу судьи."""
        if signal == "ВОПРОС":
            await asyncio.to_thread(self.court_service.set_phase, game_id, 'judge')
            await self._start_fallback_timer(game_id, chat_id, round_num)

        elif signal == "ЗАЩИТА_ВАШ_ХОД":
            await asyncio.to_thread(self.court_service.set_phase, game_id, 'defense')
            if game_id in self._test_games:
                asyncio.create_task(self._ai_play_defense_test(game_id, chat_id, "", round_num))
            else:
                game = await asyncio.to_thread(self.court_service.get_active_game_by_id, game_id)
                if game:
                    await self.bot.send_message(
                        chat_id,
                        f"🛡️ <b>Защита, ваш ответ!</b>\n"
                        f"(Адвокат осталось: {game['lawyer_cards_left']}, Свидетель: {game['witness_cards_left']})",
                        parse_mode='HTML',
                    )

        elif signal == "ПРОКУРОР_ВАШ_ХОД":
            next_round = round_num + 1
            await asyncio.to_thread(self.court_service.advance_round, game_id, next_round)
            await asyncio.to_thread(self.court_service.set_phase, game_id, 'prosecution')
            await self.bot.send_message(
                chat_id,
                f"⚖️ <b>Раунд {next_round} из 4</b>\n⚔️ Прокурор, ваш ход. Сыграйте карту в личке.",
                parse_mode='HTML',
            )

        elif signal == "ФИНАЛ":
            await asyncio.to_thread(self.court_service.set_phase, game_id, 'final')
            await self.bot.send_message(
                chat_id,
                "⚖️ <b>Все раунды завершены.</b>\n\nСуд предоставляет каждой из сторон <b>последнее слово</b>. Напишите ваше финальное заявление боту в личку.",
                parse_mode='HTML',
            )
            await self._request_final_words(game_id, chat_id)

        else:
            logger.warning(f"[COURT] _handle_judge_signal: no signal for game={game_id} round={round_num}, starting fallback")
            await self._start_fallback_timer(game_id, chat_id, round_num)

    async def _start_fallback_timer(self, game_id: int, chat_id: int, round_num: int):
        """Start 5-minute fallback: if no player reply, auto-advance the game."""
        old = self._fallback_timers.pop(game_id, None)
        if old:
            old.cancel()

        async def on_timeout():
            self._fallback_timers.pop(game_id, None)
            game = await asyncio.to_thread(self.court_service.get_active_game_by_id, game_id)
            if not game or game['status'] != 'in_progress':
                return
            if game.get('current_phase') != 'judge':
                return

            logger.info(f"[COURT] fallback_timer: game={game_id} — сторона не ответила на вопрос суда")
            await asyncio.to_thread(
                self.court_service.log_message, game_id, 'system',
                'Сторона не ответила на вопрос суда.', round_num,
            )
            try:
                await self.bot.send_message(
                    chat_id,
                    "⚖️ <i>Сторона не ответила на вопрос суда. Заседание продолжается.</i>",
                    parse_mode='HTML',
                )
            except Exception:
                pass

            played = game.get('played_cards', [])
            has_defense = any(p['role'] in ('lawyer', 'witness') and p['round'] == round_num for p in played)

            if not has_defense:
                await asyncio.to_thread(self.court_service.set_phase, game_id, 'defense')
                try:
                    await self.bot.send_message(chat_id, "🛡️ <b>Защита, ваш ответ!</b>", parse_mode='HTML')
                except Exception:
                    pass
            else:
                if round_num >= 4:
                    await asyncio.to_thread(self.court_service.set_phase, game_id, 'final')
                    await self._request_final_words(game_id, chat_id)
                else:
                    next_round = round_num + 1
                    await asyncio.to_thread(self.court_service.advance_round, game_id, next_round)
                    await asyncio.to_thread(self.court_service.set_phase, game_id, 'prosecution')
                    try:
                        await self.bot.send_message(
                            chat_id,
                            f"⚖️ <b>Раунд {next_round} из 4</b>\n⚔️ Прокурор, ваш ход.",
                            parse_mode='HTML',
                        )
                    except Exception:
                        pass

        async def _timer_wrapper():
            await asyncio.sleep(300)  # 5 minutes
            await on_timeout()

        task = asyncio.create_task(_timer_wrapper())
        self._fallback_timers[game_id] = task
        logger.info(f"[COURT] fallback_timer started: game={game_id} round={round_num} (300s)")

    async def _process_judge_reply(self, game_id: int, chat_id: int, role: str, reply_text: str, round_num: int):
        """Process a player's reply to a judge question."""
        try:
            game = await asyncio.to_thread(self.court_service.get_active_game_by_id, game_id)
            if not game or game.get('current_phase') != 'judge':
                logger.info(f"[COURT] _process_judge_reply: phase already advanced, discarding reply game={game_id}")
                return

            await self.bot.send_chat_action(chat_id, 'typing')
            reaction, signal = await asyncio.to_thread(
                self.court_service.judge_react_to_reply, game_id, role, reply_text, round_num
            )
            logger.info(f"[COURT] _process_judge_reply: game={game_id} role={role} signal={signal} reaction='{str(reaction)[:60]}'")

            if reaction:
                judge_msg = await self.bot.send_message(chat_id, f"⚖️ <i>{reaction}</i>", parse_mode='HTML')
                await asyncio.to_thread(self.court_service.set_last_judge_msg, game_id, judge_msg.message_id)

            await self._handle_judge_signal(game_id, chat_id, signal, round_num)

        except Exception as e:
            logger.error(f"[COURT] _process_judge_reply: ошибка: {e}", exc_info=True)

    async def _request_final_words(self, game_id: int, chat_id: int):
        """Запросить финальное слово у каждого игрока в личку через FSMContext."""
        logger.info(f"[COURT] _request_final_words: game={game_id} chat={chat_id}")
        game = await asyncio.to_thread(self.court_service.get_active_game_by_id, game_id)
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
            try:
                await self._set_final_word_state(user_id, game_id, role, chat_id)
                await self.bot.send_message(
                    user_id,
                    f"⚖️ <b>Финальное слово</b>\n\nСуд предоставляет вам, {role_ru}, последнее слово.\n"
                    f"Напишите ваше финальное заявление (до 500 символов):",
                    parse_mode='HTML',
                )
                await self.bot.send_message(chat_id, f"⏳ Ожидаем финальное слово от {role_ru}...", parse_mode='HTML')
            except Exception as e:
                logger.error(f"_request_final_words: не удалось отправить {user_id}: {e}")
                fw_state = self._final_word_state.get(game_id)
                if fw_state:
                    fw_state['statements'][role] = ''
                    fw_state['needed'].discard(role)

        fw_state = self._final_word_state.get(game_id)
        if fw_state and not fw_state['needed']:
            self._final_word_state.pop(game_id, None)
            asyncio.create_task(self._deliver_verdict(game_id, chat_id, {}))

    async def _set_final_word_state(self, user_id: int, game_id: int, role: str, chat_id: int):
        """Set FSMContext waiting_final_word state for a user's private chat."""
        storage = self._get_storage()
        if storage is None:
            logger.warning(f"[COURT] _set_final_word_state: no storage available")
            return
        key = StorageKey(bot_id=self.bot.id, chat_id=user_id, user_id=user_id)
        ctx = FSMContext(storage=storage, key=key)
        await ctx.set_state(CourtStates.waiting_final_word)
        await ctx.update_data(game_id=game_id, role=role, chat_id=chat_id)

    def set_storage(self, storage):
        """Called from main.py after dispatcher is created to wire FSM storage."""
        self._storage = storage

    def _get_storage(self):
        return getattr(self, '_storage', None)

    async def _deliver_verdict(self, game_id: int, chat_id: int, final_statements: dict = None):
        """Доставить драматичный многосообщный приговор."""
        logger.info(f"[COURT] _deliver_verdict: game={game_id} chat={chat_id} statements={list((final_statements or {}).keys())}")
        try:
            await self.bot.send_message(chat_id, "⚖️ Судья удаляется на совещание... 🤔", parse_mode='HTML')
            self._game_locks.pop(game_id, None)
            logger.info(f"[COURT] _deliver_verdict: generating verdict via LLM")
            parts = await asyncio.to_thread(self.court_service.generate_verdict, game_id, final_statements or {})
            logger.info(f"[COURT] _deliver_verdict: verdict generated, {len(parts)} parts")
            await asyncio.to_thread(self.court_service.save_verdict, game_id, "\n---\n".join(parts))
            self._active_game_chats.discard(chat_id)

            prefixes = [
                "⚖️ <b>Позиция обвинения:</b>",
                "🛡️ <b>Позиция защиты:</b>",
                "🔍 <b>Выводы суда:</b>",
                "🔨 <b>ПРИГОВОР:</b>",
            ]
            for prefix, part in zip(prefixes, parts + [""] * 4):
                if part:
                    await self.bot.send_message(chat_id, f"{prefix}\n\n{part}", parse_mode='HTML')
                    await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"_deliver_verdict: ошибка для game {game_id}: {e}")
            self._active_game_chats.discard(chat_id)
            await asyncio.to_thread(self.court_service.set_status, game_id, 'finished')
            try:
                await self.bot.send_message(chat_id, "⚠️ Ошибка при вынесении приговора. Заседание завершено.")
            except Exception:
                pass

    async def _get_bot_id(self) -> int:
        if not self._bot_id:
            try:
                me = await self.bot.get_me()
                self._bot_id = me.id
                self._bot_username = me.username
            except Exception:
                return -1
        return self._bot_id

    async def _get_bot_username(self) -> str:
        if not self._bot_username:
            try:
                me = await self.bot.get_me()
                self._bot_username = me.username
                self._bot_id = me.id
            except Exception:
                return "бот"
        return self._bot_username
