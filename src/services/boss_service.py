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
import math
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
WEAK_HOURS = 24          # riddle solved → x2 damage, capped at the rage unlock
REGEN_RATIO = 0.05       # +5% max HP after a full idle day
MERCHANT_DAY = 4         # the riddle exists only on this event day
RIDDLE_EXPIRES_OFFSET_DAYS = 4  # start of event day 5
RAGE_UNLOCK_OFFSET_DAYS = 5     # start of event day 6
RAGE_MIN_DAY = 6
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
        self.event_chat_id: int | None = None

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
        await self.db.execute_query(
            "CREATE TABLE IF NOT EXISTS boss_lobbies ("
            "id SERIAL PRIMARY KEY, "
            "chat_id BIGINT NOT NULL, "
            "message_id BIGINT, "
            "created_by BIGINT NOT NULL, "
            "max_hp INTEGER NOT NULL, "
            "days INTEGER NOT NULL, "
            "status TEXT NOT NULL DEFAULT 'waiting', "
            "required_players JSONB NOT NULL, "
            "ready_players JSONB NOT NULL DEFAULT '{}', "
            "deadline TIMESTAMPTZ, "
            "attempts INTEGER NOT NULL DEFAULT 0, "
            "intro_index INTEGER NOT NULL DEFAULT 0, "
            "event_id INTEGER REFERENCES boss_events(id), "
            "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
            "updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())",
            (),
        )
        await self.db.execute_query(
            "ALTER TABLE boss_lobbies ADD COLUMN IF NOT EXISTS intro_index INTEGER NOT NULL DEFAULT 0",
            (),
        )
        await self.db.execute_query(
            "CREATE UNIQUE INDEX IF NOT EXISTS boss_lobbies_one_open_idx ON boss_lobbies ((1)) "
            "WHERE status IN ('waiting', 'countdown', 'starting')",
            (),
        )
        self._tables_ready = True

    # ── synchronized launch lobby ─────────────────────────────────────────────
    _LOBBY_COLS = ("id, chat_id, message_id, created_by, max_hp, days, status, "
                   "required_players, ready_players, deadline, attempts, intro_index, "
                   "event_id, created_at, updated_at")

    def _row_to_lobby(self, row) -> dict:
        keys = [c.strip() for c in self._LOBBY_COLS.split(',')]
        lobby = dict(zip(keys, row))
        for key in ('required_players', 'ready_players'):
            if isinstance(lobby.get(key), str):
                lobby[key] = json.loads(lobby[key])
            lobby[key] = lobby.get(key) or {}
        return lobby

    async def get_open_lobby(self) -> Optional[dict]:
        await self.ensure_tables()
        rows = await self.db.execute_query(
            f"SELECT {self._LOBBY_COLS} FROM boss_lobbies "
            "WHERE status IN ('waiting', 'countdown', 'starting') ORDER BY id DESC LIMIT 1",
            (),
        )
        return self._row_to_lobby(rows[0]) if rows else None

    async def get_countdown_lobby(self) -> Optional[dict]:
        await self.ensure_tables()
        rows = await self.db.execute_query(
            f"SELECT {self._LOBBY_COLS} FROM boss_lobbies "
            "WHERE status = 'countdown' ORDER BY id DESC LIMIT 1",
            (),
        )
        return self._row_to_lobby(rows[0]) if rows else None

    async def create_lobby(self, chat_id: int, created_by: int, max_hp: int,
                           days: int, required_players: dict) -> Optional[dict]:
        await self.ensure_tables()
        rows = await self.db.execute_query(
            "INSERT INTO boss_lobbies (chat_id, created_by, max_hp, days, required_players) "
            "VALUES (%s, %s, %s, %s, %s::jsonb) RETURNING id",
            (chat_id, created_by, max_hp, days, json.dumps(required_players, ensure_ascii=False)),
        )
        return await self.get_lobby(rows[0][0]) if rows else None

    async def get_lobby(self, lobby_id: int) -> Optional[dict]:
        await self.ensure_tables()
        rows = await self.db.execute_query(
            f"SELECT {self._LOBBY_COLS} FROM boss_lobbies WHERE id = %s", (lobby_id,)
        )
        return self._row_to_lobby(rows[0]) if rows else None

    async def set_lobby_message_id(self, lobby_id: int, message_id: int):
        await self.db.execute_query(
            "UPDATE boss_lobbies SET message_id = %s, updated_at = NOW() WHERE id = %s",
            (message_id, lobby_id),
        )

    async def mark_lobby_ready(self, lobby_id: int, player_id: int, window_seconds: int = 10) -> Optional[dict]:
        """Atomically mark one required player ready; the first click starts the window."""
        player_key = str(player_id)
        rows = await self.db.execute_query(
            "WITH target AS ("
            "  SELECT id FROM boss_lobbies WHERE id = %s "
            "    AND status IN ('waiting', 'countdown') "
            "    AND (deadline IS NULL OR deadline > NOW()) "
            "    AND required_players ? %s FOR UPDATE"
            "), updated AS ("
            "  UPDATE boss_lobbies b SET "
            "    ready_players = b.ready_players || jsonb_build_object(%s::text, true), "
            "    deadline = COALESCE(b.deadline, NOW() + %s * INTERVAL '1 second'), "
            "    status = CASE WHEN NOT EXISTS ("
            "      SELECT 1 FROM jsonb_object_keys(b.required_players) required(player_id) "
            "      WHERE NOT ((b.ready_players || jsonb_build_object(%s::text, true)) ? required.player_id)"
            "    ) THEN 'starting' ELSE 'countdown' END, updated_at = NOW() "
            "  FROM target t WHERE b.id = t.id RETURNING b.id"
            ") SELECT id FROM updated",
            (lobby_id, player_key, player_key, window_seconds, player_key),
        )
        return await self.get_lobby(lobby_id) if rows else None

    async def resolve_lobby_round(self, lobby_id: int) -> Optional[dict]:
        """At the deadline, either claim the lobby for launch or reset the same message."""
        rows = await self.db.execute_query(
            "WITH target AS ("
            "  SELECT id, NOT EXISTS ("
            "    SELECT 1 FROM jsonb_object_keys(required_players) required(player_id) "
            "    WHERE NOT (ready_players ? required.player_id)"
            "  ) AS complete "
            "  FROM boss_lobbies WHERE id = %s AND status = 'countdown' "
            "    AND deadline <= NOW() FOR UPDATE"
            "), updated AS ("
            "  UPDATE boss_lobbies b SET "
            "    status = CASE WHEN t.complete THEN 'starting' ELSE 'waiting' END, "
            "    ready_players = CASE WHEN t.complete THEN b.ready_players ELSE '{}'::jsonb END, "
            "    deadline = CASE WHEN t.complete THEN b.deadline ELSE NULL END, "
            "    attempts = b.attempts + 1, updated_at = NOW() "
            "  FROM target t WHERE b.id = t.id RETURNING b.id"
            ") SELECT id FROM updated",
            (lobby_id,),
        )
        return await self.get_lobby(lobby_id) if rows else None

    async def mark_lobby_started(self, lobby_id: int, event_id: int) -> bool:
        rows = await self.db.execute_query(
            "UPDATE boss_lobbies SET status = 'started', event_id = %s, updated_at = NOW() "
            "WHERE id = %s AND status = 'starting' RETURNING id",
            (event_id, lobby_id),
        )
        return bool(rows)

    async def set_lobby_intro_index(self, lobby_id: int, intro_index: int) -> bool:
        rows = await self.db.execute_query(
            "UPDATE boss_lobbies SET intro_index = %s, updated_at = NOW() "
            "WHERE id = %s AND status = 'starting' RETURNING id",
            (intro_index, lobby_id),
        )
        return bool(rows)

    async def reset_lobby(self, lobby_id: int):
        await self.db.execute_query(
            "UPDATE boss_lobbies SET status = 'waiting', ready_players = '{}'::jsonb, "
            "deadline = NULL, intro_index = 0, updated_at = NOW() WHERE id = %s AND status = 'starting'",
            (lobby_id,),
        )

    async def cancel_open_lobby(self) -> Optional[dict]:
        lobby = await self.get_open_lobby()
        if not lobby:
            return None
        await self.db.execute_query(
            "UPDATE boss_lobbies SET status = 'cancelled', updated_at = NOW() WHERE id = %s",
            (lobby['id'],),
        )
        return lobby

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
        fields = {'finished_at': _now().isoformat()}
        if extra_meta:
            fields.update(extra_meta)
        await self.db.execute_query(
            "UPDATE boss_events SET status = %s, meta = COALESCE(meta, '{}'::jsonb) || %s::jsonb WHERE id = %s",
            (status, json.dumps(fields), event_id),
        )

    async def update_meta(self, event_id: int, **fields):
        await self.db.execute_query(
            "UPDATE boss_events SET meta = COALESCE(meta, '{}'::jsonb) || %s::jsonb WHERE id = %s",
            (json.dumps(fields), event_id),
        )

    async def pop_pending_scenes(self, event_id: int) -> list:
        rows = await self.db.execute_query(
            "WITH target AS ("
            "  SELECT id, COALESCE(meta->'pending', '[]'::jsonb) AS pending "
            "  FROM boss_events WHERE id = %s FOR UPDATE"
            "), updated AS ("
            "  UPDATE boss_events b SET meta = jsonb_set(COALESCE(b.meta, '{}'::jsonb), '{pending}', '[]'::jsonb, true) "
            "  FROM target t WHERE b.id = t.id RETURNING t.pending"
            ") SELECT pending FROM updated",
            (event_id,),
        )
        if not rows:
            return []
        pending = rows[0][0]
        if isinstance(pending, str):
            pending = json.loads(pending)
        return list(pending or [])

    # ── damage ────────────────────────────────────────────────────────────────
    def multiplier(self, ev: dict) -> int:
        weak = ev.get('weak_until')
        # Rage and the riddle weakness are deliberately non-stacking. Even if old
        # or manually edited data contains both flags, damage can never become x4.
        return 2 if ev.get('rage') or (weak and weak > _now()) else 1

    async def deal_damage(self, player_id: int, player_name: str, source: str,
                          amount: Optional[int] = None) -> Optional[dict]:
        """Apply damage from `source`. Safe to call from anywhere: returns None
        when no event is running, never raises."""
        try:
            await self.ensure_tables()
            base = DAMAGE.get(source, 0) if amount is None else int(amount)
            if base <= 0:
                return None
            # Damage can arrive concurrently from the bot and the mini-app. Lock and
            # mutate the active row in one SQL statement so two hits cannot both read
            # the same HP and overwrite each other. Phase transitions and their queued
            # scenes are part of that same mutation, which also prevents duplicates.
            rows = await self.db.execute_query(
                "WITH target AS ("
                "  SELECT id, hp AS old_hp, max_hp, phase AS old_phase, "
                "    CASE WHEN rage OR weak_until > NOW() THEN 2 ELSE 1 END AS multiplier, "
                "    started_at <= NOW() - %s * INTERVAL '1 day' AS rage_available "
                "  FROM boss_events WHERE status = 'active' AND hp > 0 "
                "  ORDER BY id DESC LIMIT 1 FOR UPDATE"
                "), calc AS ("
                "  SELECT *, GREATEST(0, old_hp - %s * multiplier) AS new_hp FROM target"
                "), updated AS ("
                "  UPDATE boss_events b SET "
                "    hp = c.new_hp, last_damage_at = NOW(), "
                "    phase = CASE WHEN c.new_hp > 0 AND c.new_hp <= c.max_hp * %s AND c.rage_available THEN 2 "
                "                 WHEN c.new_hp > 0 AND c.new_hp <= c.max_hp * %s THEN GREATEST(b.phase, 1) "
                "                 ELSE b.phase END, "
                "    rage = b.rage OR (c.new_hp > 0 AND c.new_hp <= c.max_hp * %s AND c.rage_available), "
                "    hijack_until = CASE "
                "      WHEN c.new_hp > 0 AND c.old_phase < 1 AND c.new_hp <= c.max_hp * %s "
                "      THEN NOW() + %s * INTERVAL '1 hour' ELSE b.hijack_until END, "
                "    meta = jsonb_set(COALESCE(b.meta, '{}'::jsonb), '{pending}', "
                "      COALESCE(b.meta->'pending', '[]'::jsonb) || CASE "
                "        WHEN c.new_hp <= 0 THEN '[\"win\"]'::jsonb "
                "        WHEN c.old_phase < 1 AND c.new_hp <= c.max_hp * %s AND c.rage_available THEN '[\"hijack\",\"rage\"]'::jsonb "
                "        WHEN c.old_phase < 2 AND c.new_hp <= c.max_hp * %s AND c.rage_available THEN '[\"rage\"]'::jsonb "
                "        WHEN c.old_phase < 1 AND c.new_hp <= c.max_hp * %s THEN '[\"hijack\"]'::jsonb "
                "        ELSE '[]'::jsonb END, true) "
                "  FROM calc c WHERE b.id = c.id "
                "  RETURNING b.id, b.hp, b.max_hp, c.old_hp, c.old_phase, b.phase, c.multiplier"
                "), logged AS ("
                "  INSERT INTO boss_damage_log (event_id, player_id, player_name, source, amount) "
                "  SELECT id, %s, %s, %s, old_hp - hp FROM updated RETURNING id"
                ") SELECT id, hp, max_hp, old_hp, old_phase, phase, multiplier, "
                "  (SELECT COUNT(*) FROM logged) FROM updated",
                (RAGE_UNLOCK_OFFSET_DAYS, base, RAGE_HP_RATIO, HIJACK_HP_RATIO,
                 RAGE_HP_RATIO, HIJACK_HP_RATIO, HIJACK_HOURS,
                 RAGE_HP_RATIO, RAGE_HP_RATIO, HIJACK_HP_RATIO,
                 player_id, player_name, source),
            )
            if not rows:
                return None
            event_id, new_hp, max_hp, old_hp, old_phase, new_phase, mult, _ = rows[0]
            dmg = old_hp - new_hp
            scenes = []
            if new_hp <= 0:
                scenes.append('win')
            else:
                ratio = new_hp / max_hp
                if old_phase < 1 and ratio <= HIJACK_HP_RATIO:
                    scenes.append('hijack')
                if old_phase < 2 and new_phase == 2 and ratio <= RAGE_HP_RATIO:
                    scenes.append('rage')
            result = {'event_id': event_id, 'damage': dmg, 'hp': new_hp, 'max_hp': max_hp,
                      'killed': new_hp <= 0, 'multiplier': mult, 'scenes': scenes}
            logger.info(f"Boss: {player_name} ({player_id}) dealt {dmg} via {source}, hp {old_hp}→{new_hp}")
            return result
        except Exception as e:
            logger.error(f"Boss: deal_damage failed: {e}", exc_info=True)
            return None

    async def regen_if_idle(self) -> int:
        """+5% max HP if nobody hit the boss for a full day. Returns HP restored."""
        await self.ensure_tables()
        rows = await self.db.execute_query(
            "WITH target AS ("
            "  SELECT id, hp AS old_hp, max_hp, FLOOR(max_hp * %s)::integer AS heal "
            "  FROM boss_events WHERE status = 'active' "
            "    AND COALESCE(last_damage_at, started_at) <= NOW() - INTERVAL '24 hours' "
            "    AND hp < max_hp ORDER BY id DESC LIMIT 1 FOR UPDATE"
            "), updated AS ("
            "  UPDATE boss_events b SET hp = LEAST(t.max_hp, t.old_hp + t.heal), last_damage_at = NOW() "
            "  FROM target t WHERE b.id = t.id AND t.heal > 0 RETURNING b.hp - t.old_hp AS applied"
            ") SELECT applied FROM updated",
            (REGEN_RATIO,),
        )
        return int(rows[0][0]) if rows else 0

    # ── riddle (day 4 merchant) ───────────────────────────────────────────────
    async def set_riddle(self, event_id: int, riddle: dict):
        ev = await self.get_event(event_id)
        if not ev:
            return
        expires_at = ev['started_at'] + timedelta(days=RIDDLE_EXPIRES_OFFSET_DAYS)
        await self.update_meta(
            event_id, merchant_done=True, riddle=riddle, riddle_solved=False,
            riddle_expires_at=expires_at.isoformat(),
        )

    @staticmethod
    def riddle_is_open(ev: dict) -> bool:
        meta = ev.get('meta') or {}
        if not meta.get('riddle') or meta.get('riddle_solved'):
            return False
        expires_at = meta.get('riddle_expires_at')
        if not expires_at:
            return False
        try:
            return datetime.fromisoformat(expires_at) > _now()
        except (TypeError, ValueError):
            return False

    async def try_answer_riddle(self, text: str, player_id: int, player_name: str) -> Optional[dict]:
        """Returns the riddle dict if `text` solves the pending riddle (and marks it solved)."""
        ev = await self.get_active_event()
        if not ev or not self.riddle_is_open(ev):
            return None
        riddle = ev['meta'].get('riddle')
        guess = _norm_answer(text)
        if not guess:
            return None
        answers = [_norm_answer(a) for a in riddle.get('answers', [])]
        if guess not in answers and not any(a and a in guess.split() for a in answers):
            return None
        solver = json.dumps({'id': player_id, 'name': player_name}, ensure_ascii=False)
        rows = await self.db.execute_query(
            "UPDATE boss_events SET weak_until = LEAST("
            "  NOW() + %s * INTERVAL '1 hour', started_at + %s * INTERVAL '1 day'), "
            "meta = jsonb_set(jsonb_set(COALESCE(meta, '{}'::jsonb), '{riddle_solved}', 'true'::jsonb, true), "
            "                 '{riddle_solver}', %s::jsonb, true) "
            "WHERE id = %s AND status = 'active' "
            "  AND NOT COALESCE((meta->>'riddle_solved')::boolean, false) "
            "  AND (meta->>'riddle_expires_at')::timestamptz > NOW() RETURNING id",
            (WEAK_HOURS, RAGE_UNLOCK_OFFSET_DAYS, solver, ev['id']),
        )
        return riddle if rows else None

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
        seconds = (ev['ends_at'] - _now()).total_seconds()
        return max(0, math.ceil(seconds / 86400))

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
        if self.riddle_is_open(ev):
            lines.append("🧩 Загадка Торговца активна — пишите ответ в чат")
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
            self.event_chat_id = ev['chat_id'] if ev else None
            now = _now()
            injection = ""
            if ev:
                self.riddle_active = self.riddle_is_open(ev)
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
