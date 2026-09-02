"""
Boss event service — «Месть Пуджинио-Фамозы».

Pure DB/state layer shared by the main bot (aiogram) and the mini-app (Flask).
All Telegram I/O (pinned HP message, cutscenes) lives in handlers/boss_handlers.py,
which polls this service; the mini-app only ever calls deal_damage().

The event is "on" while a boss_events row has status='active'. There is no
separate global flag to forget to flip: when the row is finalized (won / lost /
stopped by admin) every hook turns into a no-op. PUDGE_EVENT=false in .env is an
extra kill switch that makes the whole service inert.
"""
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

KYIV = ZoneInfo("Europe/Kyiv")

# Base damage per source (before multipliers). Tuned for 3 players, ~2500 HP, ~10-12 days.
DAMAGE = {
    'trivia': 15,        # correct trivia answer
    'wordle': 20,        # wordle win (+5 per unused attempt added by caller)
    'pisunchik': 10,     # /pisunchik use
    'dungeon_room': 5,   # each cleared dungeon room
    'dungeon_boss': 40,  # mini-Pudge kill
}

HIJACK_HP_RATIO = 0.66   # ≤ 66% → Pudginio hijacks Jarvis for a day
RAGE_HP_RATIO = 0.33     # ≤ 33% → rage: damage x2 for the rest of the event
HIJACK_HOURS = 24
WEAK_HOURS = 24          # riddle solved → extra x1 damage for a day
REGEN_RATIO = 0.05       # +5% max HP after a full idle day
MERCHANT_DAY = 7         # day of the event when Торговец returns with the riddle
RESPECT_DAYS = 7         # MVP gets Jarvis' respect for this long after a win

_ENABLED = os.getenv('PUDGE_EVENT', 'true').strip().lower() not in ('0', 'false', 'no', 'off')


def _now():
    return datetime.now(timezone.utc)


def _norm_answer(text: str) -> str:
    return ''.join(ch for ch in (text or '').lower().replace('ё', 'е') if ch.isalnum() or ch == ' ').strip()


class BossService:
    def __init__(self, db_manager):
        self.db = db_manager
        self._tables_ready = False
        # Sync-readable caches refreshed by BossHandlers' tick so hot paths
        # (persona prompt, riddle filter) never touch the DB.
        self.persona_injection: str = ""
        self.riddle_active: bool = False
        self.event_active: bool = False

    @property
    def enabled(self) -> bool:
        return _ENABLED

    # ── schema ────────────────────────────────────────────────────────────────
    async def ensure_tables(self):
        if self._tables_ready:
            return
        await self.db.execute_query(
            "CREATE TABLE IF NOT EXISTS boss_events ("
            "id SERIAL PRIMARY KEY, "
            "name TEXT NOT NULL, "
            "chat_id BIGINT NOT NULL, "
            "max_hp INTEGER NOT NULL, "
            "hp INTEGER NOT NULL, "
            "status TEXT NOT NULL DEFAULT 'active', "
            "started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
            "ends_at TIMESTAMPTZ NOT NULL, "
            "message_id BIGINT, "
            "phase INTEGER NOT NULL DEFAULT 0, "
            "rage BOOLEAN NOT NULL DEFAULT FALSE, "
            "hijack_until TIMESTAMPTZ, "
            "weak_until TIMESTAMPTZ, "
            "last_damage_at TIMESTAMPTZ, "
            "meta JSONB NOT NULL DEFAULT '{}')",
            (),
        )
        await self.db.execute_query(
            "CREATE TABLE IF NOT EXISTS boss_damage_log ("
            "id SERIAL PRIMARY KEY, "
            "event_id INTEGER NOT NULL REFERENCES boss_events(id), "
            "player_id BIGINT NOT NULL, "
            "player_name TEXT, "
            "source TEXT NOT NULL, "
            "amount INTEGER NOT NULL, "
            "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())",
            (),
        )
        await self.db.execute_query(
            "CREATE INDEX IF NOT EXISTS boss_damage_log_event_idx ON boss_damage_log (event_id, created_at)", ()
        )
        self._tables_ready = True

    # ── event lookup ──────────────────────────────────────────────────────────
    _COLS = ("id, name, chat_id, max_hp, hp, status, started_at, ends_at, message_id, "
             "phase, rage, hijack_until, weak_until, last_damage_at, meta")

    def _row_to_event(self, row) -> dict:
        keys = [c.strip() for c in self._COLS.split(',')]
        ev = dict(zip(keys, row))
        if isinstance(ev.get('meta'), str):
            try:
                ev['meta'] = json.loads(ev['meta'])
            except Exception:
                ev['meta'] = {}
        ev['meta'] = ev.get('meta') or {}
        return ev

    async def get_active_event(self) -> Optional[dict]:
        if not self.enabled:
            return None
        await self.ensure_tables()
        rows = await self.db.execute_query(
            f"SELECT {self._COLS} FROM boss_events WHERE status = 'active' ORDER BY id DESC LIMIT 1", ()
        )
        return self._row_to_event(rows[0]) if rows else None

    async def get_last_event(self) -> Optional[dict]:
        await self.ensure_tables()
        rows = await self.db.execute_query(f"SELECT {self._COLS} FROM boss_events ORDER BY id DESC LIMIT 1", ())
        return self._row_to_event(rows[0]) if rows else None

    async def get_event(self, event_id: int) -> Optional[dict]:
        rows = await self.db.execute_query(f"SELECT {self._COLS} FROM boss_events WHERE id = %s", (event_id,))
        return self._row_to_event(rows[0]) if rows else None

    async def is_active(self) -> bool:
        return (await self.get_active_event()) is not None

    # ── lifecycle ─────────────────────────────────────────────────────────────
    async def start_event(self, chat_id: int, max_hp: int, days: int, name: str = "Пуджинио-Фамоза") -> dict:
        await self.ensure_tables()
        ends_at = _now() + timedelta(days=days)
        rows = await self.db.execute_query(
            "INSERT INTO boss_events (name, chat_id, max_hp, hp, ends_at, last_damage_at, meta) "
            "VALUES (%s, %s, %s, %s, %s, NOW(), %s) RETURNING id",
            (name, chat_id, max_hp, max_hp, ends_at, json.dumps({'days': days, 'pending': []})),
        )
        return await self.get_event(rows[0][0])

    async def set_message_id(self, event_id: int, message_id: int):
        await self.db.execute_query("UPDATE boss_events SET message_id = %s WHERE id = %s", (message_id, event_id))

    async def finalize(self, event_id: int, status: str, extra_meta: Optional[dict] = None):
        ev = await self.get_event(event_id)
        if not ev:
            return
        meta = dict(ev['meta'])
        meta['finished_at'] = _now().isoformat()
        if extra_meta:
            meta.update(extra_meta)
        await self.db.execute_query(
            "UPDATE boss_events SET status = %s, meta = %s WHERE id = %s", (status, json.dumps(meta), event_id)
        )

    async def update_meta(self, event_id: int, **fields):
        ev = await self.get_event(event_id)
        if not ev:
            return
        meta = dict(ev['meta'])
        meta.update(fields)
        await self.db.execute_query("UPDATE boss_events SET meta = %s WHERE id = %s", (json.dumps(meta), event_id))

    async def _push_pending(self, event_id: int, scene: str):
        ev = await self.get_event(event_id)
        if not ev:
            return
        meta = dict(ev['meta'])
        pending = list(meta.get('pending') or [])
        pending.append(scene)
        meta['pending'] = pending
        await self.db.execute_query("UPDATE boss_events SET meta = %s WHERE id = %s", (json.dumps(meta), event_id))

    async def pop_pending_scenes(self, event_id: int) -> list:
        ev = await self.get_event(event_id)
        if not ev:
            return []
        pending = list(ev['meta'].get('pending') or [])
        if pending:
            meta = dict(ev['meta'])
            meta['pending'] = []
            await self.db.execute_query("UPDATE boss_events SET meta = %s WHERE id = %s", (json.dumps(meta), event_id))
        return pending

    # ── damage ────────────────────────────────────────────────────────────────
    def multiplier(self, ev: dict) -> int:
        mult = 1
        if ev.get('rage'):
            mult += 1
        weak = ev.get('weak_until')
        if weak and weak > _now():
            mult += 1
        return mult

    async def deal_damage(self, player_id: int, player_name: str, source: str,
                          amount: Optional[int] = None) -> Optional[dict]:
        """Apply damage from `source`. Safe to call from anywhere: returns None
        when no event is running, never raises."""
        try:
            ev = await self.get_active_event()
            if not ev or ev['hp'] <= 0:
                return None
            base = DAMAGE.get(source, 0) if amount is None else int(amount)
            if base <= 0:
                return None
            mult = self.multiplier(ev)
            dmg = base * mult
            new_hp = max(0, ev['hp'] - dmg)
            await self.db.execute_query(
                "UPDATE boss_events SET hp = %s, last_damage_at = NOW() WHERE id = %s", (new_hp, ev['id'])
            )
            await self.db.execute_query(
                "INSERT INTO boss_damage_log (event_id, player_id, player_name, source, amount) VALUES (%s, %s, %s, %s, %s)",
                (ev['id'], player_id, player_name, source, dmg),
            )
            result = {'event_id': ev['id'], 'damage': dmg, 'hp': new_hp, 'max_hp': ev['max_hp'],
                      'killed': new_hp <= 0, 'multiplier': mult, 'scenes': []}
            ratio = new_hp / ev['max_hp']
            phase = ev['phase']
            if new_hp <= 0:
                await self._push_pending(ev['id'], 'win')
                result['scenes'].append('win')
            else:
                if phase < 1 and ratio <= HIJACK_HP_RATIO:
                    phase = 1
                    until = _now() + timedelta(hours=HIJACK_HOURS)
                    await self.db.execute_query(
                        "UPDATE boss_events SET phase = 1, hijack_until = %s WHERE id = %s", (until, ev['id'])
                    )
                    await self._push_pending(ev['id'], 'hijack')
                    result['scenes'].append('hijack')
                if phase < 2 and ratio <= RAGE_HP_RATIO:
                    await self.db.execute_query(
                        "UPDATE boss_events SET phase = 2, rage = TRUE WHERE id = %s", (ev['id'],)
                    )
                    await self._push_pending(ev['id'], 'rage')
                    result['scenes'].append('rage')
            logger.info(f"Boss: {player_name} ({player_id}) dealt {dmg} via {source}, hp {ev['hp']}→{new_hp}")
            return result
        except Exception as e:
            logger.error(f"Boss: deal_damage failed: {e}", exc_info=True)
            return None

    async def regen_if_idle(self) -> int:
        """+5% max HP if nobody hit the boss for a full day. Returns HP restored."""
        ev = await self.get_active_event()
        if not ev:
            return 0
        last = ev.get('last_damage_at') or ev['started_at']
        if _now() - last < timedelta(hours=24):
            return 0
        heal = int(ev['max_hp'] * REGEN_RATIO)
        new_hp = min(ev['max_hp'], ev['hp'] + heal)
        applied = new_hp - ev['hp']
        if applied > 0:
            await self.db.execute_query(
                "UPDATE boss_events SET hp = %s, last_damage_at = NOW() WHERE id = %s", (new_hp, ev['id'])
            )
        return applied

    # ── riddle (day 7 merchant) ───────────────────────────────────────────────
    async def set_riddle(self, event_id: int, riddle: dict):
        await self.update_meta(event_id, merchant_done=True, riddle=riddle, riddle_solved=False)

    async def try_answer_riddle(self, text: str, player_id: int, player_name: str) -> Optional[dict]:
        """Returns the riddle dict if `text` solves the pending riddle (and marks it solved)."""
        ev = await self.get_active_event()
        if not ev:
            return None
        riddle = ev['meta'].get('riddle')
        if not riddle or ev['meta'].get('riddle_solved'):
            return None
        guess = _norm_answer(text)
        if not guess:
            return None
        answers = [_norm_answer(a) for a in riddle.get('answers', [])]
        if guess not in answers and not any(a and a in guess.split() for a in answers):
            return None
        until = _now() + timedelta(hours=WEAK_HOURS)
        await self.db.execute_query("UPDATE boss_events SET weak_until = %s WHERE id = %s", (until, ev['id']))
        await self.update_meta(ev['id'], riddle_solved=True, riddle_solver={'id': player_id, 'name': player_name})
        return riddle

    # ── stats ─────────────────────────────────────────────────────────────────
    async def damage_by_player(self, event_id: int, today_only: bool = False) -> list:
        """[(player_id, name, total)] sorted desc. `today` is a Kyiv calendar day."""
        where = ""
        params: tuple = (event_id,)
        if today_only:
            start = datetime.now(KYIV).replace(hour=0, minute=0, second=0, microsecond=0)
            where = " AND created_at >= %s"
            params = (event_id, start)
        rows = await self.db.execute_query(
            "SELECT player_id, MAX(player_name), SUM(amount) FROM boss_damage_log "
            f"WHERE event_id = %s{where} GROUP BY player_id ORDER BY 3 DESC", params
        )
        return [(r[0], r[1] or 'Игрок', int(r[2])) for r in (rows or [])]

    async def registered_players(self, chat_id: int) -> list:
        """[(player_id, name)] for everyone playing the main game — so a player with
        zero damage still shows up (and can be the loser)."""
        rows = await self.db.execute_query("SELECT player_id, player_name FROM pisunchik_data", ())
        return [(r[0], r[1] or 'Игрок') for r in (rows or [])]

    async def standings(self, ev: dict, today_only: bool = False) -> list:
        dealt = {pid: (name, total) for pid, name, total in await self.damage_by_player(ev['id'], today_only)}
        result = []
        for pid, name in await self.registered_players(ev['chat_id']):
            # prefer the main-game name over whatever the damage source captured
            result.append((pid, name, dealt.get(pid, (name, 0))[1]))
        for pid, (name, total) in dealt.items():
            if not any(r[0] == pid for r in result):
                result.append((pid, name, total))
        result.sort(key=lambda r: -r[2])
        return result

    # ── presentation ──────────────────────────────────────────────────────────
    @staticmethod
    def day_number(ev: dict) -> int:
        return max(1, (_now() - ev['started_at']).days + 1)

    @staticmethod
    def days_left(ev: dict) -> int:
        return max(0, (ev['ends_at'] - _now()).days)

    @staticmethod
    def hp_bar(hp: int, max_hp: int, width: int = 12) -> str:
        filled = round(width * max(0, hp) / max(1, max_hp))
        return '█' * filled + '░' * (width - filled)

    def phase_label(self, ev: dict) -> str:
        now = _now()
        bits = []
        if ev.get('hijack_until') and ev['hijack_until'] > now:
            bits.append("Джарвис захвачен")
        if ev.get('rage'):
            bits.append("ЯРОСТЬ")
        if ev.get('weak_until') and ev['weak_until'] > now:
            bits.append("уязвим")
        mult = self.multiplier(ev)
        label = ", ".join(bits) if bits else "спокоен"
        if mult > 1:
            label += f" · урон x{mult}"
        return label

    async def build_pin_text(self, ev: dict) -> str:
        today = await self.standings(ev, today_only=True)
        total = await self.standings(ev)
        pct = int(100 * ev['hp'] / max(1, ev['max_hp']))
        days = ev['meta'].get('days', 14)
        lines = [
            "🗿 <b>МЕСТЬ ПУДЖИНИО-ФАМОЗЫ</b>",
            f"❤️ <b>{ev['hp']}</b> / {ev['max_hp']}  <code>[{self.hp_bar(ev['hp'], ev['max_hp'])}]</code> {pct}%",
            f"⏳ День {self.day_number(ev)} из {days} · осталось {self.days_left(ev)} дн.",
            f"😈 Фаза: {self.phase_label(ev)}",
        ]
        if ev['meta'].get('riddle') and not ev['meta'].get('riddle_solved'):
            lines.append("🧩 Загадка Торговца не решена — пишите ответ в чат")
        lines.append("")
        lines.append("⚔️ <b>Урон сегодня:</b> " + (" · ".join(f"{escape(n)} {d}" for _, n, d in today) or "пока никто"))
        lines.append("🏆 <b>Всего:</b> " + (" · ".join(f"{escape(n)} {d}" for _, n, d in total) or "—"))
        lines.append("")
        lines.append("Тривия, Wordle, /pisunchik и данж ранят его.")
        return "\n".join(lines)

    async def summary_block(self) -> str:
        """Short block appended to the evening «правильные ответы» post."""
        ev = await self.get_active_event()
        if not ev:
            return ""
        today = await self.standings(ev, today_only=True)
        pct = int(100 * ev['hp'] / max(1, ev['max_hp']))
        parts = [
            "",
            "🗿 <b>Пуджинио-Фамоза</b>",
            f"❤️ {ev['hp']} / {ev['max_hp']} ({pct}%) · день {self.day_number(ev)}, осталось {self.days_left(ev)} дн.",
        ]
        dealt = [f"{escape(n)} {d}" for _, n, d in today if d > 0]
        parts.append("⚔️ Урон за день: " + (" · ".join(dealt) if dealt else "никто его сегодня не тронул 🙄"))
        return "\n".join(parts)

    # ── persona injection (read by moltbot synchronously) ─────────────────────
    async def refresh_caches(self, content: dict):
        """Called from the bot's tick: recompute the sync caches."""
        try:
            ev = await self.get_active_event()
            self.event_active = ev is not None
            now = _now()
            injection = ""
            if ev:
                self.riddle_active = bool(ev['meta'].get('riddle')) and not ev['meta'].get('riddle_solved')
                if ev.get('hijack_until') and ev['hijack_until'] > now:
                    injection = content.get('hijack_persona', '')
            else:
                self.riddle_active = False
                last = await self.get_last_event()
                if last and last['status'] == 'won':
                    respect = last['meta'].get('respect') or {}
                    until = respect.get('until')
                    if until and datetime.fromisoformat(until) > now:
                        injection = content.get('respect_persona', '').format(name=respect.get('name', ''))
            self.persona_injection = injection
        except Exception as e:
            logger.error(f"Boss: refresh_caches failed: {e}")


_instance: Optional[BossService] = None


def get_boss_service(db_manager=None) -> Optional[BossService]:
    """Process-wide singleton. First call must pass db_manager."""
    global _instance
    if _instance is None and db_manager is not None:
        _instance = BossService(db_manager)
    return _instance
