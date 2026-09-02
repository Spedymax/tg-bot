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
import os
import random
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config.settings import Settings
from services.boss_service import MERCHANT_DAY, RESPECT_DAYS, get_boss_service

logger = logging.getLogger(__name__)

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DATA_DIR = os.path.join(_BASE_DIR, 'assets', 'data')
_PUDGE_IMAGE = os.path.join(_BASE_DIR, 'assets', 'images', 'statuetki', 'pudginio.jpg')

DEFAULT_HP = 2500
DEFAULT_DAYS = 14
KYIV = ZoneInfo("Europe/Kyiv")


def _load_json(name: str) -> dict:
    try:
        with open(os.path.join(_DATA_DIR, name), encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Boss: failed to load {name}: {e}")
        return {}


class BossHandlers:
    def __init__(self, bot, db_manager):
        self.bot = bot
        self.db = db_manager
        self.svc = get_boss_service(db_manager)
        self.router = Router()
        self._scheduler = None
        self._last_pin_text: dict[int, str] = {}
        self._tick_lock = asyncio.Lock()
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
            if await self.svc.get_active_event():
                await message.reply("Ивент уже идёт. /pudge_status или /pudge_stop")
                return
            args = (command.args or '').split()
            hp = int(args[0]) if len(args) > 0 and args[0].isdigit() else DEFAULT_HP
            days = int(args[1]) if len(args) > 1 and args[1].isdigit() else DEFAULT_DAYS
            chat_id = Settings.CHAT_IDS['main'] if message.chat.type == 'private' else message.chat.id
            asyncio.create_task(self.start_event(chat_id, hp, days))
            if message.chat.type == 'private':
                await message.reply(f"Запускаю в основном чате: {hp} HP, {days} дней")

        @self.router.message(Command('pudge_stop'))
        async def pudge_stop(message: Message):
            if not self._is_admin(message):
                return
            ev = await self.svc.get_active_event()
            if not ev:
                await message.reply("Активного ивента нет")
                return
            await self.svc.finalize(ev['id'], 'stopped')
            await self._unpin(ev)
            await self.svc.refresh_caches(self.content)
            await message.reply("Ивент остановлен без катсцены. Пуджинио уползает в базу.")

        @self.router.message(Command('pudge_status'))
        async def pudge_status(message: Message):
            if not self._is_admin(message):
                return
            ev = await self.svc.get_active_event()
            if not ev:
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
                                  image_trigger="ПУДЖИНИО-ФАМОЗА'")

        @self.router.message(Command('pudge_merchant_test'))
        async def pudge_merchant_test(message: Message):
            """Force the day-7 merchant return now (needs an active event)."""
            if not self._is_admin(message):
                return
            ev = await self.svc.get_active_event()
            if not ev:
                await message.reply("Активного ивента нет")
                return
            await self._merchant_return(ev)

        # Group riddle answers. Only matches while a riddle is pending (sync cache),
        # and always re-raises SkipHandler so moltbot still logs/answers the message.
        @self.router.message(F.text, F.chat.type.in_({'group', 'supergroup'}), lambda m: self.svc.riddle_active)
        async def riddle_answer(message: Message):
            try:
                riddle = await self.svc.try_answer_riddle(
                    message.text, message.from_user.id, message.from_user.first_name or 'Игрок'
                )
                if riddle:
                    self.svc.riddle_active = False
                    ctx = {'solver': message.from_user.first_name or 'Игрок'}
                    await self.play_scene(message.chat.id, self.content.get('riddle_solved', []), ctx)
                    await self.tick()
            except Exception as e:
                logger.error(f"Boss: riddle_answer failed: {e}")
            raise SkipHandler()

    # ── event flow ────────────────────────────────────────────────────────────
    async def _intro_context(self, days: int) -> dict:
        """{summoner} = the player with the most-upgraded characteristic (he fed
        Pudginio the most), {summon_count} = that level."""
        summoner, count = 'одному из вас', 'МНОГО'
        try:
            rows = await self.db.execute_query("SELECT player_name, characteristics FROM pisunchik_data", ())
            best = (None, -1)
            for name, chars in (rows or []):
                for ch in (chars or []):
                    parts = str(ch).split(':')
                    if len(parts) == 2 and parts[1].isdigit() and int(parts[1]) > best[1]:
                        best = (name, int(parts[1]))
            if best[0]:
                summoner, count = best[0], str(best[1])
        except Exception as e:
            logger.warning(f"Boss: intro context lookup failed: {e}")
        return {'summoner': summoner, 'summon_count': count, 'days': str(days)}

    async def start_event(self, chat_id: int, hp: int, days: int):
        try:
            ctx = await self._intro_context(days)
            await self.play_scene(chat_id, self.content.get('boss_intro', []), ctx,
                                  image_trigger="ПУДЖИНИО-ФАМОЗА'")
            ev = await self.svc.start_event(chat_id, hp, days)
            text = await self.svc.build_pin_text(ev)
            sent = await self.bot.send_message(chat_id, text, parse_mode='HTML', reply_markup=self._markup(),
                                               disable_notification=True)
            await self.svc.set_message_id(ev['id'], sent.message_id)
            self._last_pin_text[ev['id']] = text
            try:
                await self.bot.pin_chat_message(chat_id, sent.message_id, disable_notification=True)
            except Exception as e:
                logger.warning(f"Boss: pin failed: {e}")
            await self.svc.refresh_caches(self.content)
            logger.info(f"Boss: event {ev['id']} started in {chat_id}: {hp} HP, {days} days")
        except Exception as e:
            logger.error(f"Boss: start_event failed: {e}", exc_info=True)

    def _markup(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="⚔️ В данж", url=f"https://t.me/{Settings.BOT_USERNAME}?start=dungeon")
        ]])

    async def play_scene(self, chat_id: int, lines: list, ctx: dict, fast: bool = False,
                         image_trigger: str | None = None):
        """Send a cutscene line by line with the same pacing as the old statuetki plot."""
        for i, raw in enumerate(lines):
            try:
                line = raw.format(**ctx) if ctx else raw
            except (KeyError, IndexError):
                line = raw
            try:
                await self.bot.send_message(chat_id, line, disable_notification=True)
                if image_trigger and image_trigger in raw and os.path.exists(_PUDGE_IMAGE):
                    await self.bot.send_photo(chat_id, FSInputFile(_PUDGE_IMAGE), disable_notification=True)
            except Exception as e:
                logger.warning(f"Boss: scene line failed: {e}")
            if fast:
                await asyncio.sleep(0.05)
            elif 'вспышка' in line.lower() or 'ослепляет' in line.lower():
                await asyncio.sleep(3.5)
            elif line.strip() in ('...', '.....'):
                await asyncio.sleep(2.5)
            elif re.search(r"[А-ЯЁ]{3,}(?:[ ,.!?-]+[А-ЯЁ]{3,}){1,}", line) or line.startswith('*'):
                await asyncio.sleep(3)          # shouted lines and *event markers* need to land
            elif len(line) > 110:
                await asyncio.sleep(2.6)        # long line: give people time to read it
            elif i < len(lines) - 1:
                await asyncio.sleep(1.8)

    async def _unpin(self, ev: dict):
        if ev.get('message_id'):
            try:
                await self.bot.unpin_chat_message(ev['chat_id'], message_id=ev['message_id'])
            except Exception as e:
                logger.warning(f"Boss: unpin failed: {e}")

    async def _refresh_pin(self, ev: dict):
        if not ev.get('message_id'):
            return
        text = await self.svc.build_pin_text(ev)
        if self._last_pin_text.get(ev['id']) == text:
            return
        try:
            await self.bot.edit_message_text(text, chat_id=ev['chat_id'], message_id=ev['message_id'],
                                             parse_mode='HTML', reply_markup=self._markup())
            self._last_pin_text[ev['id']] = text
        except TelegramBadRequest as e:
            if 'not modified' in str(e):
                self._last_pin_text[ev['id']] = text
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
        await self.play_scene(ev['chat_id'], self.content.get('merchant_return', []), {'riddle': riddle['question']})
        await self.svc.refresh_caches(self.content)

    async def _finish(self, ev: dict, won: bool):
        standings = await self.svc.standings(ev)
        mvp = standings[0] if standings else (0, 'никто', 0)
        loser = standings[-1] if standings else (0, 'никто', 0)
        ctx = {
            'mvp': mvp[1], 'mvp_damage': str(mvp[2]),
            'loser': loser[1], 'loser_damage': str(loser[2]),
        }
        extra = {'mvp': {'id': mvp[0], 'name': mvp[1], 'damage': mvp[2]},
                 'loser': {'id': loser[0], 'name': loser[1], 'damage': loser[2]}}
        if won:
            until = datetime.now(timezone.utc).replace(microsecond=0)
            extra['respect'] = {'id': mvp[0], 'name': mvp[1], 'until': (until + timedelta(days=RESPECT_DAYS)).isoformat()}
        await self.svc.finalize(ev['id'], 'won' if won else 'lost', extra)
        # Final pin state, then unpin so the list doesn't accumulate like Wordle used to.
        fresh = await self.svc.get_event(ev['id'])
        if fresh:
            self._last_pin_text.pop(ev['id'], None)
            await self._refresh_pin(fresh)
        await self._unpin(ev)
        await self.play_scene(ev['chat_id'], self.content.get('win_scene' if won else 'lose_scene', []), ctx)
        await self.svc.refresh_caches(self.content)
        logger.info(f"Boss: event {ev['id']} finished, won={won}, mvp={mvp}, loser={loser}")

    # ── periodic tick ─────────────────────────────────────────────────────────
    async def tick(self):
        if self._tick_lock.locked():
            return
        async with self._tick_lock:
            try:
                ev = await self.svc.get_active_event()
                if not ev:
                    await self.svc.refresh_caches(self.content)
                    return
                now = datetime.now(timezone.utc)

                for scene in await self.svc.pop_pending_scenes(ev['id']):
                    if scene == 'win':
                        await self._finish(ev, won=True)
                        return
                    if scene in ('hijack', 'rage'):
                        await self.play_scene(ev['chat_id'], self.content.get(f'{scene}_scene', []), {})

                if ev['hp'] <= 0:
                    await self._finish(ev, won=True)
                    return
                if now >= ev['ends_at']:
                    await self._finish(ev, won=False)
                    return

                if (not ev['meta'].get('merchant_done') and self.svc.day_number(ev) >= MERCHANT_DAY
                        and datetime.now(KYIV).hour >= 10):
                    await self._merchant_return(ev)
                    ev = await self.svc.get_active_event() or ev

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
                    await self.bot.send_message(ev['chat_id'], random.choice(taunts).format(heal=healed),
                                                disable_notification=True)
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
        self._scheduler.add_job(self.tick, IntervalTrigger(seconds=30), max_instances=1, coalesce=True)
        self._scheduler.add_job(self.daily_regen, CronTrigger(hour=4, minute=0, timezone=KYIV))
        self._scheduler.start()
        logger.info("Boss: scheduler started (tick 30s, regen check 04:00 Kyiv)")
