"""
«Месть Пуджинио-Фамозы» — Telegram side of the boss event.

Owns everything that talks to the chat: the intro/phase/final cutscenes, the
pinned HP message, the day-7 merchant riddle and the admin commands. All state
lives in services/boss_service.py; a 30-second tick polls it so damage dealt by
the mini-app process shows up here without any cross-process signalling.
"""
import asyncio
import json
import logging
import math
import os
import random
import re
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from html import escape
from zoneinfo import ZoneInfo

from aiogram import BaseMiddleware, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config.settings import Settings
from services.boss_service import MERCHANT_DAY, RESPECT_DAYS, get_boss_service

logger = logging.getLogger(__name__)

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DATA_DIR = os.path.join(_BASE_DIR, 'assets', 'data')
_PUDGE_IMAGE = os.path.join(_BASE_DIR, 'assets', 'images', 'statuetki', 'pudginio_famoza.jpg')

DEFAULT_HP = 2500
DEFAULT_DAYS = 14
LOBBY_WINDOW_SECONDS = 10
KYIV = ZoneInfo("Europe/Kyiv")

# Telegram allows roughly 20 messages per minute per group and counts message
# edits towards the same budget. The 35-line intro and the lobby countdown used
# to spend it at the same time, which earned the bot a flood ban on the whole
# chat — Jarvis went mute for half a minute and the event failed to launch.
# Every chat write from the event now goes through one per-chat gate.
CHAT_RATE_LIMIT = 18
CHAT_RATE_WINDOW = 60.0
# Countdown refresh: never more often than this, and rounded to whole steps so
# a 10-second round costs two edits instead of ten.
LOBBY_EDIT_MIN_INTERVAL = 3.0
LOBBY_COUNTDOWN_STEP = 5

_LOBBY_NAME_OVERRIDES = {
    'Spatifilum': 'Юра',
    'Летучий сын мияги 🏴‍☠️': 'Юра',
    'Богдан.': 'Богдан',
    'Адольфус': 'Богдан',
    'Максим': 'Макс',
    'Максимилиано': 'Макс',
}


def _load_json(name: str) -> dict:
    try:
        with open(os.path.join(_DATA_DIR, name), encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Boss: failed to load {name}: {e}")
        return {}


class BossRiddleMiddleware(BaseMiddleware):
    """Observe riddle answers without consuming messages meant for other handlers."""

    def __init__(self, boss_handlers):
        self.boss_handlers = boss_handlers

    async def __call__(self, handler, event: Message, data: dict):
        try:
            await self.boss_handlers.inspect_riddle_message(event)
        except Exception as e:
            # A side event must never stop court/shop/moltbot or message logging.
            logger.error(f"Boss: riddle middleware failed: {e}", exc_info=True)
        return await handler(event, data)


class BossHandlers:
    def __init__(self, bot, db_manager):
        self.bot = bot
        self.db = db_manager
        self.svc = get_boss_service(db_manager)
        self.router = Router()
        self._scheduler = None
        self._last_pin_text: dict[int, str] = {}
        self._tick_lock = asyncio.Lock()
        self._start_lock = asyncio.Lock()
        self._lobby_tick_lock = asyncio.Lock()
        self._last_lobby_text: dict[int, tuple] = {}
        self._last_lobby_edit: dict[int, float] = {}
        self._chat_calls: dict[int, deque] = {}
        self._flood_until: dict[int, float] = {}
        self._launch_tasks: set[asyncio.Task] = set()
        self._launching_lobby_ids: set[int] = set()
        self._scene_tasks: set[asyncio.Task] = set()
        self.content = _load_json('pudge_event.json')
        self.content['boss_intro'] = _load_json('plot.json').get('boss_intro', [])
        self._register()

    # ── admin commands ────────────────────────────────────────────────────────
    def _is_admin(self, message: Message) -> bool:
        return message.from_user and message.from_user.id in Settings.ADMIN_IDS

    def _register(self):
        @self.router.message(Command('pudge_start'))
        async def pudge_start(message: Message, command: CommandObject):
            if not self._is_admin(message):
                return
            if not self.svc.enabled:
                await message.reply("PUDGE_EVENT выключен в .env")
                return
            if message.chat.type != 'private':
                await message.reply("Запускай ивент командой /pudge_start в личке с ботом.")
                return
            if await self.svc.get_active_event():
                await message.reply("Ивент уже идёт. /pudge_status или /pudge_stop")
                return
            existing = await self.svc.get_open_lobby()
            if existing:
                await message.reply("Лобби уже ждёт в основном чате. Второе не создаю.")
                return
            args = (command.args or '').split()
            nums = [a for a in args if a.isdigit()]
            hp = max(1, int(nums[0])) if len(nums) > 0 else DEFAULT_HP
            days = max(1, int(nums[1])) if len(nums) > 1 else DEFAULT_DAYS
            players = await self._required_lobby_players()
            if len(players) != 3:
                await message.reply(
                    f"Не могу создать лобби: в игре найдено {len(players)} игроков, а нужно ровно 3."
                )
                return
            chat_id = Settings.CHAT_IDS['main']
            lobby = await self.svc.create_lobby(chat_id, message.from_user.id, hp, days, players)
            if not lobby:
                await message.reply("Не удалось создать лобби. Проверь /pudge_status.")
                return
            try:
                sent = await self._chat_write(chat_id, lambda: self.bot.send_message(
                    chat_id, self._lobby_text(lobby), parse_mode='HTML',
                    reply_markup=self._lobby_markup(lobby), disable_notification=True,
                ))
                await self.svc.set_lobby_message_id(lobby['id'], sent.message_id)
                self._last_lobby_text[lobby['id']] = (self._lobby_text(lobby), True)
                self._last_lobby_edit[lobby['id']] = time.monotonic()
                await message.reply(f"Лобби создано: {hp} HP, {days} дней. Ждём первого нажатия.")
            except Exception as e:
                await self.svc.cancel_open_lobby()
                logger.error(f"Boss: lobby post failed: {e}", exc_info=True)
                await message.reply("Не смог отправить лобби в группу.")

        @self.router.message(Command('pudge_stop'))
        async def pudge_stop(message: Message):
            if not self._is_admin(message):
                return
            ev = await self.svc.get_active_event()
            if not ev:
                lobby = await self.svc.cancel_open_lobby()
                if lobby:
                    await self._edit_lobby(lobby, "❌ <b>Лобби отменено.</b>", with_button=False, wait=True)
                    await message.reply("Лобби Пуджинио отменено.")
                else:
                    await message.reply("Активного ивента или лобби нет")
                return
            await self.svc.finalize(ev['id'], 'stopped')
            await self._unpin(ev)
            await self.svc.refresh_caches(self.content)
            await message.reply("Ивент остановлен без катсцены. Пуджинио уползает в базу.")

        @self.router.callback_query(F.data.startswith('pudge_ready:'))
        async def pudge_ready(call: CallbackQuery):
            try:
                lobby_id = int(call.data.rsplit(':', 1)[1])
            except (TypeError, ValueError):
                await call.answer("Это лобби уже не существует.", show_alert=True)
                return
            lobby = await self.svc.mark_lobby_ready(lobby_id, call.from_user.id, LOBBY_WINDOW_SECONDS)
            if not lobby:
                await call.answer("Ты не в списке или этот раунд уже закрыт.", show_alert=True)
                return
            await call.answer("Готовность принята.")
            if lobby['status'] == 'starting':
                await self._edit_lobby(lobby, "✅ <b>Все трое на месте. Начинаем...</b>", with_button=False)
                self._track_launch(lobby)
            else:
                await self._edit_lobby(lobby)

        @self.router.message(Command('pudge_status'))
        async def pudge_status(message: Message):
            if not self._is_admin(message):
                return
            ev = await self.svc.get_active_event()
            if not ev:
                lobby = await self.svc.get_open_lobby()
                if lobby:
                    await message.reply(self._lobby_text(lobby), parse_mode='HTML')
                else:
                    await message.reply("Активного ивента нет")
                return
            text = await self.svc.build_pin_text(ev)
            extra = (f"\n\n<i>id={ev['id']} phase={ev['phase']} rage={ev['rage']} "
                     f"hijack_until={ev['hijack_until']} weak_until={ev['weak_until']} "
                     f"merchant_done={ev['meta'].get('merchant_done')} riddle_solved={ev['meta'].get('riddle_solved')}</i>")
            await message.reply(text + extra, parse_mode='HTML')

        @self.router.message(Command('pudge_hit'))
        async def pudge_hit(message: Message, command: CommandObject):
            """Test damage: /pudge_hit 100 [source]"""
            if not self._is_admin(message):
                return
            args = (command.args or '').split()
            amount = int(args[0]) if args and args[0].isdigit() else 50
            source = args[1] if len(args) > 1 else 'admin'
            res = await self.svc.deal_damage(message.from_user.id, message.from_user.first_name, source, amount)
            if not res:
                await message.reply("Активного ивента нет")
                return
            await message.reply(f"-{res['damage']} HP → {res['hp']}/{res['max_hp']} (x{res['multiplier']}), scenes={res['scenes']}")
            await self.tick()

        @self.router.message(Command('pudge_intro_test'))
        async def pudge_intro_test(message: Message):
            """Preview the intro in the admin's DM with the real pacing (add `fast` to skip pauses)."""
            if not self._is_admin(message):
                return
            ctx = await self._intro_context(DEFAULT_DAYS)
            fast = 'fast' in (message.text or '')
            await self.play_scene(message.from_user.id, self.content.get('boss_intro', []), ctx, fast=fast,
                                  image_trigger="ПУДЖИНИО-ФАМОЗА", pace=1.2)

        @self.router.message(Command('pudge_merchant_test'))
        async def pudge_merchant_test(message: Message):
            """Force the day-4 merchant scene now (needs an active event)."""
            if not self._is_admin(message):
                return
            ev = await self.svc.get_active_event()
            if not ev:
                await message.reply("Активного ивента нет")
                return
            await self._merchant_return(ev)

        @self.router.message(Command('pudge_finish'))
        async def pudge_finish(message: Message, command: CommandObject):
            """Force the finale: /pudge_finish win | lose"""
            if not self._is_admin(message):
                return
            ev = await self.svc.get_active_event()
            if not ev:
                await message.reply("Активного ивента нет")
                return
            won = (command.args or '').strip().lower() in ('win', 'победа', 'won')
            await self._finish(ev, won=won)

        @self.router.message(Command('pudge_day'))
        async def pudge_day(message: Message, command: CommandObject):
            """Time travel: /pudge_day 7 → it is now day 7; /pudge_day end → the event expires now."""
            if not self._is_admin(message):
                return
            ev = await self.svc.get_active_event()
            if not ev:
                await message.reply("Активного ивента нет")
                return
            arg = (command.args or '').strip().lower()
            if arg in ('end', 'конец'):
                await self.db.execute_query("UPDATE boss_events SET ends_at = NOW() WHERE id = %s", (ev['id'],))
                await message.reply("Срок ивента истёк. Финал прилетит на следующем тике (до 30 с).")
            elif arg.isdigit():
                day = max(1, int(arg))
                await self.db.execute_query(
                    "UPDATE boss_events SET started_at = NOW() - INTERVAL '1 day' * %s, "
                    "ends_at = NOW() + INTERVAL '1 day' * %s WHERE id = %s",
                    (day - 1, max(0, ev['meta'].get('days', DEFAULT_DAYS) - day + 1), ev['id']),
                )
                await message.reply(
                    f"Теперь день {day}. Торговец приходит только на 4-й день после 10:00 Kyiv, "
                    "или принудительно: /pudge_merchant_test"
                )
            else:
                await message.reply("Использование: /pudge_day 7  или  /pudge_day end")
            await self.tick()

        @self.router.message(Command('pudge_regen_test'))
        async def pudge_regen_test(message: Message):
            """Pretend nobody hit the boss for a day and run the regen job now."""
            if not self._is_admin(message):
                return
            ev = await self.svc.get_active_event()
            if not ev:
                await message.reply("Активного ивента нет")
                return
            await self.db.execute_query("UPDATE boss_events SET last_damage_at = NOW() - INTERVAL '25 hours' WHERE id = %s", (ev['id'],))
            await self.daily_regen()

        @self.router.message(Command('pudge_summary'))
        async def pudge_summary(message: Message):
            """Show the blocks that get appended to tonight's «правильные ответы»."""
            if not self._is_admin(message):
                return
            text = await self.svc.summary_block()
            try:
                from services.dungeon_service import get_dungeon_service
                dg = get_dungeon_service()
                if dg:
                    text += await dg.summary_block()
            except Exception as e:
                text += f"\n(данж: {e})"
            await message.reply(text.strip() or "Пусто: ивента нет и в данж никто не ходил.", parse_mode='HTML')

        @self.router.message(Command('pudge_help'))
        async def pudge_help(message: Message):
            if not self._is_admin(message):
                return
            await message.reply(
                "🗿 <b>Пуджинио — админка</b>\n"
                "/pudge_start [hp] [days] — один раз создать постоянное лобби (только из ЛС)\n"
                "/pudge_status · /pudge_stop (без катсцены)\n"
                "/pudge_hit 100 — урон себе в зачёт; фазы: ≤66% захват Джарвиса, ≤33% ярость\n"
                "/pudge_day 7 · /pudge_day end — перемотка времени\n"
                "/pudge_merchant_test — Торговец с загадкой сейчас (ответ пишется в чат ивента)\n"
                "/pudge_regen_test — реген за день тишины\n"
                "/pudge_finish win|lose — финал сразу\n"
                "/pudge_summary — блок для вечерних ответов\n"
                "/pudge_intro_test [fast] — интро в ЛС\n\n"
                "Тест-прогон: в ЛС <code>/pudge_start 200 1</code> → всем троим нажать кнопку за 10 секунд → /pudge_hit 70 (захват) → поговорить с Джарвисом → "
                "/pudge_hit 70 (ярость) → /pudge_merchant_test → ответить → /pudge_regen_test → /pudge_summary → /pudge_finish win.",
                parse_mode='HTML',
            )

    # ── event flow ────────────────────────────────────────────────────────────
    async def inspect_riddle_message(self, message: Message):
        """Claim a correct answer if present; never owns or consumes the message."""
        if (not message.text or not message.from_user or not self.svc.riddle_active
                or message.chat.id != self.svc.event_chat_id):
            return
        riddle = await self.svc.try_answer_riddle(
            message.text, message.from_user.id, message.from_user.first_name or 'Игрок'
        )
        if not riddle:
            return
        # Close the cheap sync filter immediately. The SQL update in try_answer_riddle
        # is the authoritative claim and prevents two simultaneous correct answers.
        self.svc.riddle_active = False
        ctx = {'solver': message.from_user.first_name or 'Игрок'}
        task = asyncio.create_task(self._announce_riddle_solution(message.chat.id, ctx))
        self._scene_tasks.add(task)
        task.add_done_callback(self._scene_tasks.discard)

    async def _announce_riddle_solution(self, chat_id: int, ctx: dict):
        try:
            await self.play_scene(chat_id, self.content.get('riddle_solved', []), ctx)
            await self.tick()
        except Exception as e:
            logger.error(f"Boss: riddle solution scene failed: {e}", exc_info=True)

    async def _required_lobby_players(self) -> dict[str, str]:
        """Build the exact three-person roster from game accounts, with current chat names."""
        rows = await self.db.execute_query(
            "SELECT p.player_id, COALESCE(("
            "  SELECT m.name FROM messages m WHERE m.user_id = p.player_id "
            "    AND m.name IS NOT NULL AND m.name <> 'Jarvis' "
            "  ORDER BY m.timestamp DESC LIMIT 1"
            "), p.player_name) "
            "FROM pisunchik_data p ORDER BY p.player_id",
            (),
        )
        players = {}
        for player_id, raw_name in (rows or []):
            name = _LOBBY_NAME_OVERRIDES.get(str(raw_name), str(raw_name or player_id))
            players[str(player_id)] = name
        return players

    @staticmethod
    def _ordered_lobby_players(lobby: dict) -> list[tuple[str, str]]:
        priority = {'Макс': 0, 'Юра': 1, 'Богдан': 2}
        return sorted(
            ((str(player_id), str(name)) for player_id, name in lobby['required_players'].items()),
            key=lambda item: (priority.get(item[1], 99), item[1]),
        )

    def _lobby_text(self, lobby: dict) -> str:
        ready = lobby.get('ready_players') or {}
        lines = ["⚠️ <b>Сегодня здесь должны быть все.</b>", ""]
        for player_id, name in self._ordered_lobby_players(lobby):
            lamp = '🟢' if player_id in ready else '⚪️'
            lines.append(f"{lamp} <b>{escape(name)}</b>")
        lines.append("")
        if lobby.get('status') == 'countdown' and lobby.get('deadline'):
            remaining = max(0, math.ceil((lobby['deadline'] - datetime.now(timezone.utc)).total_seconds()))
            # Rounded up to whole steps: a per-second number would mean a per-second
            # edit, and edits count against the chat's flood limit.
            shown = math.ceil(remaining / LOBBY_COUNTDOWN_STEP) * LOBBY_COUNTDOWN_STEP
            lines.append(f"⏳ Осталось: <b>~{shown}</b> сек.")
        elif lobby.get('status') == 'starting':
            lines.append("✅ <b>Все трое на месте. Начинаем...</b>")
        else:
            if lobby.get('attempts', 0) > 0:
                lines.append("❌ <b>Не собрались.</b> Готовность сброшена.")
            lines.append("Первое нажатие запустит 10 секунд.")
        return '\n'.join(lines)

    @staticmethod
    def _lobby_markup(lobby: dict) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="⚡ Я на месте", callback_data=f"pudge_ready:{lobby['id']}")
        ]])

    # ── per-chat write budget ────────────────────────────────────────────────
    def _chat_slot_delay(self, chat_id: int) -> float:
        """Seconds to wait before the next write to this chat (0 = go ahead)."""
        now = time.monotonic()
        delay = max(0.0, self._flood_until.get(chat_id, 0.0) - now)
        calls = self._chat_calls.setdefault(chat_id, deque())
        while calls and now - calls[0] >= CHAT_RATE_WINDOW:
            calls.popleft()
        if len(calls) >= CHAT_RATE_LIMIT:
            delay = max(delay, CHAT_RATE_WINDOW - (now - calls[0]))
        return delay

    def _note_chat_write(self, chat_id: int):
        self._chat_calls.setdefault(chat_id, deque()).append(time.monotonic())

    def _note_flood(self, chat_id: int, e: TelegramRetryAfter):
        """Telegram said stop. Hold every write to this chat until it is over."""
        until = time.monotonic() + e.retry_after + 1
        if until > self._flood_until.get(chat_id, 0.0):
            self._flood_until[chat_id] = until
            logger.warning(f"Boss: chat {chat_id} flood-limited, holding writes for {e.retry_after}s")

    async def _chat_write(self, chat_id: int, send, fast: bool = False):
        """One chat write: wait out the budget, retry once if Telegram floods us.

        Used by everything that must not be dropped (cutscene lines, the pinned
        message). Periodic refreshes skip instead of waiting — see _edit_lobby.
        """
        if fast:
            return await send()
        for attempt in range(2):
            delay = self._chat_slot_delay(chat_id)
            if delay > 0:
                logger.info(f"Boss: holding a write to {chat_id} for {delay:.1f}s")
                await asyncio.sleep(delay)
            try:
                result = await send()
            except TelegramRetryAfter as e:
                self._note_flood(chat_id, e)
                if attempt == 0:
                    continue
                raise
            self._note_chat_write(chat_id)
            return result

    async def _edit_lobby(self, lobby: dict, text: str | None = None, with_button: bool = True,
                          wait: bool = False):
        """Edit the lobby message. Periodic refreshes are dropped when the chat's
        budget is spent; `wait=True` (the last word on a lobby: started, cancelled)
        holds for a free slot instead, so that line is never lost."""
        if not lobby.get('message_id'):
            return
        rendered = text if text is not None else self._lobby_text(lobby)
        state = (rendered, with_button)
        # Nothing to say. This also covers the tick repeating "Начинаем..." every
        # second while the intro plays: an edit rejected as "not modified" still
        # spends a slot of the chat's budget.
        if self._last_lobby_text.get(lobby['id']) == state:
            return
        now = time.monotonic()
        if text is None and now - self._last_lobby_edit.get(lobby['id'], 0.0) < LOBBY_EDIT_MIN_INTERVAL:
            return  # countdown refresh, not worth a slot yet
        if not wait and self._chat_slot_delay(lobby['chat_id']) > 0:
            return  # the chat is busy or flood-limited; the next tick will retry

        def edit():
            return self.bot.edit_message_text(
                rendered, chat_id=lobby['chat_id'], message_id=lobby['message_id'],
                parse_mode='HTML', reply_markup=self._lobby_markup(lobby) if with_button else None,
            )

        def accept():
            self._last_lobby_text[lobby['id']] = state
            self._last_lobby_edit[lobby['id']] = time.monotonic()

        try:
            if wait:
                await self._chat_write(lobby['chat_id'], edit)
            else:
                await edit()
                self._note_chat_write(lobby['chat_id'])
            accept()
        except TelegramRetryAfter as e:
            self._note_flood(lobby['chat_id'], e)
        except TelegramBadRequest as e:
            self._note_chat_write(lobby['chat_id'])
            if 'not modified' in str(e).lower():
                accept()
            else:
                logger.warning(f"Boss: lobby edit failed: {e}")
        except Exception as e:
            logger.warning(f"Boss: lobby edit failed: {e}")

    def _track_launch(self, lobby: dict):
        lobby_id = lobby['id']
        if lobby_id in self._launching_lobby_ids:
            return
        self._launching_lobby_ids.add(lobby_id)
        task = asyncio.create_task(self._launch_from_lobby(lobby))
        self._launch_tasks.add(task)
        task.add_done_callback(self._launch_tasks.discard)

    async def _launch_from_lobby(self, lobby: dict):
        lobby_id = lobby['id']
        try:
            await self.start_event(lobby['chat_id'], lobby['max_hp'], lobby['days'], lobby=lobby)
        finally:
            self._launching_lobby_ids.discard(lobby_id)

    async def _intro_context(self, days: int) -> dict:
        return {'days': str(days)}

    async def start_event(self, chat_id: int, hp: int, days: int, lobby: dict | None = None):
        async with self._start_lock:
            try:
                # /pudge_start launches a background task, so two quick commands can
                # otherwise both pass the handler's pre-check before either inserts.
                active = await self.svc.get_active_event()
                if active:
                    logger.warning("Boss: duplicate start ignored")
                    await self._refresh_pin(active)
                    if lobby:
                        claimed = await self.svc.mark_lobby_started(lobby['id'], active['id'])
                        if claimed:
                            await self._edit_lobby(lobby, "✅ <b>Ивент уже начался.</b>",
                                                   with_button=False, wait=True)
                    return active
                ctx = await self._intro_context(days)
                async def save_progress(index: int):
                    if lobby:
                        saved = await self.svc.set_lobby_intro_index(lobby['id'], index)
                        if not saved:
                            raise RuntimeError("lobby was cancelled while the intro was playing")
                await self.play_scene(chat_id, self.content.get('boss_intro', []), ctx,
                                      image_trigger="ПУДЖИНИО-ФАМОЗА",
                                      start_at=lobby.get('intro_index', 0) if lobby else 0,
                                      on_progress=save_progress if lobby else None, pace=1.2)
                if lobby:
                    fresh_lobby = await self.svc.get_lobby(lobby['id'])
                    if not fresh_lobby or fresh_lobby['status'] != 'starting':
                        raise RuntimeError("lobby was cancelled before event creation")
                ev = await self.svc.start_event(chat_id, hp, days)
                text = await self.svc.build_pin_text(ev)
                sent = await self._chat_write(chat_id, lambda: self.bot.send_message(
                    chat_id, text, parse_mode='HTML', reply_markup=self._markup(), disable_notification=True))
                await self.svc.set_message_id(ev['id'], sent.message_id)
                self._last_pin_text[ev['id']] = text
                try:
                    await self.bot.pin_chat_message(chat_id, sent.message_id, disable_notification=True)
                except Exception as e:
                    logger.warning(f"Boss: pin failed: {e}")
                await self.svc.refresh_caches(self.content)
                if lobby:
                    claimed = await self.svc.mark_lobby_started(lobby['id'], ev['id'])
                    if not claimed:
                        await self.svc.finalize(ev['id'], 'stopped')
                        await self._unpin(ev)
                        await self.svc.refresh_caches(self.content)
                        logger.warning(f"Boss: lobby {lobby['id']} was cancelled during event creation")
                        return None
                    await self._edit_lobby(lobby, "✅ <b>Все собрались. Ивент начался.</b>",
                                           with_button=False, wait=True)
                logger.info(f"Boss: event {ev['id']} started in {chat_id}: {hp} HP, {days} days")
                return ev
            except TelegramRetryAfter as e:
                # Flood control is temporary. Leave the lobby 'starting' so the tick
                # relaunches and the intro resumes from its checkpoint instead of
                # making everyone press the button again.
                self._note_flood(chat_id, e)
                logger.warning(f"Boss: launch paused by flood control, will resume: {e}")
                return None
            except Exception as e:
                logger.error(f"Boss: start_event failed: {e}", exc_info=True)
                if lobby:
                    await self.svc.reset_lobby(lobby['id'])
                    reset = await self.svc.get_lobby(lobby['id'])
                    if reset and reset['status'] == 'waiting':
                        await self._edit_lobby(reset)
                return None

    def _markup(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="⚔️ В данж", url=f"https://t.me/{Settings.BOT_USERNAME}?start=dungeon")
        ]])

    # Cutscene pacing. People read ~15 chars/s in a chat, so the pause before a line
    # grows with the length of the line they are still reading.
    READ_CHARS_PER_SEC = 15
    # The floor stays above CHAT_RATE_WINDOW / CHAT_RATE_LIMIT (3.33s), so a long
    # cutscene paces itself inside the chat's budget instead of being held up by
    # the gate mid-scene, which would read as a random stall.
    MIN_PAUSE = 3.4
    MIN_PAUSE_IMPORTANT = 4.2
    MAX_PAUSE = 8.0
    IMAGE_PAUSE = 3.5
    IMAGE_VIEW_TIME = 4.0

    @classmethod
    def _pause_before(cls, prev_line: str | None, important: bool, after_image: bool = False) -> float:
        base = cls.MIN_PAUSE_IMPORTANT if important else cls.MIN_PAUSE
        read = 1.0 + len(prev_line or '') / cls.READ_CHARS_PER_SEC
        if important:
            read += 1.0
        if after_image:
            read = max(read, cls.IMAGE_VIEW_TIME)
        return min(cls.MAX_PAUSE, max(base, read))

    async def play_scene(self, chat_id: int, lines: list, ctx: dict, fast: bool = False,
                         image_trigger: str | None = None, start_at: int = 0,
                         on_progress=None, pace: float = 1.0):
        """Send a cutscene line by line. The pause before each line depends on how long the
        previous line was (reading time), with a floor of 3.4s (4.2s before an important line:
        shouted caps, *event markers*, the sky-sign line) and 3.5s before the Pudginio picture.

        Every line goes through the per-chat write gate, so a flood penalty pauses
        the scene instead of killing it halfway."""
        prev = None
        after_image = False
        for i, raw in enumerate(lines):
            if i < start_at:
                continue
            try:
                line = raw.format(**ctx) if ctx else raw
            except (KeyError, IndexError):
                line = raw
            important = (
                bool(re.search(r"[А-ЯЁ]{3,}(?:[ ,.!?-]+[А-ЯЁ]{3,}){1,}", line))
                or line.startswith('*')
                or (image_trigger is not None and image_trigger in raw)
                or 'вспышка' in line.lower() or 'ослепляет' in line.lower()
            )
            if i > start_at:
                pause = self._pause_before(prev, important, after_image) * pace
                await asyncio.sleep(0.05 if fast else pause)
            after_image = False
            try:
                await self._chat_write(
                    chat_id, lambda: self.bot.send_message(chat_id, line, disable_notification=True), fast=fast)
                if image_trigger and image_trigger in raw and os.path.exists(_PUDGE_IMAGE):
                    await asyncio.sleep(0.05 if fast else self.IMAGE_PAUSE * pace)
                    await self._chat_write(
                        chat_id,
                        lambda: self.bot.send_photo(chat_id, FSInputFile(_PUDGE_IMAGE), disable_notification=True),
                        fast=fast)
                    after_image = True
            except Exception as e:
                logger.warning(f"Boss: scene line failed: {e}")
                if on_progress:
                    raise
            else:
                if on_progress:
                    result = on_progress(i + 1)
                    if asyncio.iscoroutine(result):
                        await result
            prev = line

    async def _unpin(self, ev: dict):
        if ev.get('message_id'):
            try:
                await self.bot.unpin_chat_message(ev['chat_id'], message_id=ev['message_id'])
            except Exception as e:
                logger.warning(f"Boss: unpin failed: {e}")

    async def _refresh_pin(self, ev: dict):
        text = await self.svc.build_pin_text(ev)
        if not ev.get('message_id'):
            sent = await self._chat_write(ev['chat_id'], lambda: self.bot.send_message(
                ev['chat_id'], text, parse_mode='HTML', reply_markup=self._markup(),
                disable_notification=True))
            await self.svc.set_message_id(ev['id'], sent.message_id)
            ev['message_id'] = sent.message_id
            self._last_pin_text[ev['id']] = text
            try:
                await self.bot.pin_chat_message(ev['chat_id'], sent.message_id, disable_notification=True)
            except Exception as e:
                logger.warning(f"Boss: pin failed: {e}")
            return
        if self._last_pin_text.get(ev['id']) == text:
            return
        if self._chat_slot_delay(ev['chat_id']) > 0:
            return  # the next tick will refresh it
        try:
            await self.bot.edit_message_text(text, chat_id=ev['chat_id'], message_id=ev['message_id'],
                                             parse_mode='HTML', reply_markup=self._markup())
            self._note_chat_write(ev['chat_id'])
            self._last_pin_text[ev['id']] = text
        except TelegramRetryAfter as e:
            self._note_flood(ev['chat_id'], e)
        except TelegramBadRequest as e:
            if 'not modified' in str(e):
                self._last_pin_text[ev['id']] = text
            elif 'message to edit not found' in str(e).lower():
                await self.svc.set_message_id(ev['id'], None)
                ev['message_id'] = None
                await self._refresh_pin(ev)
            else:
                logger.warning(f"Boss: pin edit failed: {e}")
        except Exception as e:
            logger.warning(f"Boss: pin edit failed: {e}")

    async def _merchant_return(self, ev: dict):
        riddles = self.content.get('riddles') or []
        if not riddles:
            await self.svc.update_meta(ev['id'], merchant_done=True)
            return
        riddle = random.choice(riddles)
        await self.svc.set_riddle(ev['id'], riddle)
        fresh = await self.svc.get_event(ev['id'])
        await self._resume_merchant(fresh)
        await self.svc.refresh_caches(self.content)

    async def _resume_merchant(self, ev: dict):
        if not ev['meta'].get('merchant_pending'):
            return
        # An expired question must not be posted after a long outage.
        if self.svc.riddle_is_open(ev):
            await self.play_scene(
                ev['chat_id'], self.content.get('merchant_return', []),
                {'riddle': ev['meta']['riddle']['question']},
                start_at=ev['meta'].get('merchant_index', 0),
                on_progress=lambda index: self.svc.update_meta(ev['id'], merchant_index=index))
        await self.svc.update_meta(ev['id'], merchant_pending=False)

    async def _resume_finale(self, ev: dict):
        await self.svc.refresh_caches(self.content)
        await self._refresh_pin(ev)
        await self._unpin(ev)
        await self.play_scene(
            ev['chat_id'], self.content.get('win_scene' if ev['status'] == 'won' else 'lose_scene', []),
            ev['meta']['finale_context'], start_at=ev['meta'].get('finale_index', 0),
            on_progress=lambda index: self.svc.update_meta(ev['id'], finale_index=index))
        await self.svc.update_meta(ev['id'], finale_pending=False)

    async def _finish(self, ev: dict, won: bool):
        standings = await self.svc.standings(ev)
        mvp = standings[0] if standings else (0, 'никто', 0)
        loser = standings[-1] if standings else (0, 'никто', 0)
        ctx = {
            'mvp': mvp[1], 'mvp_damage': str(mvp[2]),
            'loser': loser[1], 'loser_damage': str(loser[2]),
            'duration_elapsed': self._duration_elapsed_text(ev['meta'].get('days', DEFAULT_DAYS)),
        }
        extra = {'mvp': {'id': mvp[0], 'name': mvp[1], 'damage': mvp[2]},
                 'loser': {'id': loser[0], 'name': loser[1], 'damage': loser[2]}}
        if won:
            until = datetime.now(timezone.utc).replace(microsecond=0)
            extra['respect'] = {'id': mvp[0], 'name': mvp[1], 'until': (until + timedelta(days=RESPECT_DAYS)).isoformat()}
        extra.update(finale_pending=True, finale_context=ctx, finale_index=0)
        await self.svc.finalize(ev['id'], 'won' if won else 'lost', extra)
        fresh = await self.svc.get_event(ev['id'])
        if fresh:
            self._last_pin_text.pop(ev['id'], None)
            await self._resume_finale(fresh)
        logger.info(f"Boss: event {ev['id']} finished, won={won}, mvp={mvp}, loser={loser}")

    @staticmethod
    def _duration_text(days: int) -> str:
        days = int(days)
        tail = days % 100
        if 11 <= tail <= 14:
            word = 'дней'
        elif days % 10 == 1:
            word = 'день'
        elif days % 10 in (2, 3, 4):
            word = 'дня'
        else:
            word = 'дней'
        return f"{days} {word}"

    @classmethod
    def _duration_elapsed_text(cls, days: int) -> str:
        days = int(days)
        singular = days % 10 == 1 and days % 100 != 11
        return f"{cls._duration_text(days)} {'прошёл' if singular else 'прошло'}"

    # ── periodic tick ─────────────────────────────────────────────────────────
    async def lobby_tick(self):
        """Refresh the countdown and atomically resolve an expired lobby round."""
        if self._lobby_tick_lock.locked():
            return
        async with self._lobby_tick_lock:
            try:
                lobby = await self.svc.get_open_lobby()
                if not lobby:
                    return
                if lobby['status'] == 'starting':
                    await self._edit_lobby(lobby, "✅ <b>Все трое на месте. Начинаем...</b>", with_button=False)
                    self._track_launch(lobby)
                    return
                if lobby['status'] != 'countdown':
                    return
                if lobby.get('deadline') and lobby['deadline'] > datetime.now(timezone.utc):
                    await self._edit_lobby(lobby)
                    return

                resolved = await self.svc.resolve_lobby_round(lobby['id'])
                if not resolved:
                    return
                if resolved['status'] == 'starting':
                    await self._edit_lobby(
                        resolved, "✅ <b>Все трое на месте. Начинаем...</b>", with_button=False,
                    )
                    self._track_launch(resolved)
                else:
                    await self._edit_lobby(resolved)
            except Exception as e:
                logger.error(f"Boss: lobby tick failed: {e}", exc_info=True)

    async def tick(self):
        if self._tick_lock.locked():
            return
        async with self._tick_lock:
            try:
                ev = await self.svc.get_active_event()
                if not ev:
                    last = await self.svc.get_last_event()
                    if last and last['status'] in ('won', 'lost') and last['meta'].get('finale_pending'):
                        await self._resume_finale(last)
                    await self.svc.refresh_caches(self.content)
                    return
                now = datetime.now(timezone.utc)

                for scene in ev['meta'].get('pending', []):
                    if scene == 'win':
                        await self._finish(ev, won=True)
                        return
                    if scene in ('hijack', 'rage'):
                        await self.play_scene(
                            ev['chat_id'], self.content.get(f'{scene}_scene', []), {},
                            start_at=ev['meta'].get('scene_index', 0),
                            on_progress=lambda index: self.svc.update_meta(ev['id'], scene_index=index))
                    await self.svc.ack_pending_scene(ev['id'], scene)
                    ev['meta'].pop('scene_index', None)

                ev = await self.svc.get_active_event()
                if not ev:
                    return
                now = datetime.now(timezone.utc)
                if ev['hp'] <= 0:
                    await self._finish(ev, won=True)
                    return
                if now >= ev['ends_at']:
                    await self._finish(ev, won=False)
                    return

                event_day = self.svc.day_number(ev)
                if not ev['meta'].get('merchant_done'):
                    if event_day == MERCHANT_DAY and datetime.now(KYIV).hour >= 10:
                        await self._merchant_return(ev)
                        ev = await self.svc.get_active_event() or ev
                    elif event_day > MERCHANT_DAY:
                        # Never deliver a delayed day-4 riddle close to the day-6 rage unlock.
                        await self.svc.update_meta(ev['id'], merchant_done=True, merchant_skipped=True)
                        ev = await self.svc.get_active_event() or ev

                await self._resume_merchant(ev)
                await self._refresh_pin(ev)
                await self.svc.refresh_caches(self.content)
            except Exception as e:
                logger.error(f"Boss: tick failed: {e}", exc_info=True)

    async def daily_regen(self):
        try:
            ev = await self.svc.get_active_event()
            if not ev:
                return
            healed = await self.svc.regen_if_idle()
            if healed > 0:
                taunts = self.content.get('regen_taunts') or []
                if taunts:
                    taunt = random.choice(taunts).format(heal=healed)
                    await self._chat_write(ev['chat_id'], lambda: self.bot.send_message(
                        ev['chat_id'], taunt, disable_notification=True))
                await self.tick()
        except Exception as e:
            logger.error(f"Boss: daily_regen failed: {e}")

    def start_scheduler(self):
        if not self.svc.enabled:
            logger.info("Boss: PUDGE_EVENT disabled, scheduler not started")
            return
        # the 30s tick would otherwise log two INFO lines a minute forever
        logging.getLogger('apscheduler.executors.default').setLevel(logging.WARNING)
        self._scheduler = AsyncIOScheduler(timezone=KYIV)
        self._scheduler.add_job(self.lobby_tick, IntervalTrigger(seconds=1), max_instances=1, coalesce=True)
        self._scheduler.add_job(self.tick, IntervalTrigger(seconds=30), max_instances=1, coalesce=True)
        self._scheduler.add_job(self.daily_regen, CronTrigger(hour=4, minute=0, timezone=KYIV))
        self._scheduler.start()
        logger.info("Boss: scheduler started (lobby 1s, tick 30s, regen check 04:00 Kyiv)")
