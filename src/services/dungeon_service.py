"""
Daily dungeon — persistence + lore lookup, shared by the bot and the mini-app.

dungeon_daily : one generated layout per Kyiv calendar day (everyone plays the same one)
dungeon_runs  : one run per (day, player); the whole state JSON lives here
"""
import json
import logging
from datetime import date, datetime
from html import escape
from typing import Optional
from zoneinfo import ZoneInfo

from services import dungeon_logic as logic

logger = logging.getLogger(__name__)

KYIV = ZoneInfo("Europe/Kyiv")
# messages.name stores whatever display name Telegram had at the time; align with how
# the guys are actually called (same override the prophecy feature uses).
NAME_OVERRIDES = {"Spatifilum": "Юра", "Богдан.": "Богдан", "Максим": "Макс", "Максимилиано": "Макс"}


class DungeonService:
    def __init__(self, db_manager, content: dict):
        self.db = db_manager
        self.content = content or {}
        self._tables_ready = False

    @staticmethod
    def today() -> date:
        return datetime.now(KYIV).date()

    async def ensure_tables(self):
        if self._tables_ready:
            return
        await self.db.execute_query_strict(
            "CREATE TABLE IF NOT EXISTS dungeon_daily ("
            "date DATE PRIMARY KEY, "
            "layout JSONB NOT NULL, "
            "rage BOOLEAN NOT NULL DEFAULT FALSE, "
            "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())", ()
        )
        await self.db.execute_query_strict(
            "CREATE TABLE IF NOT EXISTS dungeon_runs ("
            "date DATE NOT NULL, "
            "player_id BIGINT NOT NULL, "
            "player_name TEXT, "
            "state JSONB NOT NULL, "
            "finished BOOLEAN NOT NULL DEFAULT FALSE, "
            "won BOOLEAN NOT NULL DEFAULT FALSE, "
            "rooms_cleared INTEGER NOT NULL DEFAULT 0, "
            "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
            "finished_at TIMESTAMPTZ, "
            "PRIMARY KEY (date, player_id))", ()
        )
        self._tables_ready = True

    # ── lore from the chat ────────────────────────────────────────────────────
    async def _player_names(self) -> dict:
        """{user_id: display name} for everyone registered in the main game."""
        rows = await self.db.execute_query("SELECT player_id FROM pisunchik_data", ())
        ids = [r[0] for r in (rows or [])]
        if not ids:
            return {}
        names = await self.db.execute_query(
            "SELECT DISTINCT ON (user_id) user_id, name FROM messages "
            "WHERE user_id = ANY(%s) AND name IS NOT NULL ORDER BY user_id, timestamp DESC", (ids,)
        )
        result = {}
        for uid, name in (names or []):
            result[uid] = NAME_OVERRIDES.get(name, name)
        return result

    async def build_lore(self) -> dict:
        lore = {'players': [], 'highlights': [], 'messages': []}
        try:
            names = await self._player_names()
            lore['players'] = sorted(set(names.values()))
            if names:
                rows = await self.db.execute_query(
                    "SELECT user_id, message_text FROM messages "
                    "WHERE user_id = ANY(%s) AND length(message_text) BETWEEN 25 AND 140 "
                    "AND message_text NOT LIKE '/%%' AND message_text NOT LIKE 'http%%' "
                    "ORDER BY random() LIMIT 60", (list(names.keys()),)
                )
                lore['messages'] = [{'name': names[uid], 'text': text} for uid, text in (rows or []) if uid in names]
            rows = await self.db.execute_query(
                "SELECT candidates, votes FROM weekly_highlights WHERE status = 'finished' ORDER BY id DESC LIMIT 12", ()
            )
            for candidates, votes in (rows or []):
                if isinstance(candidates, str):
                    candidates = json.loads(candidates)
                if isinstance(votes, str):
                    votes = json.loads(votes or '{}')
                counts = {}
                for idx in (votes or {}).values():
                    counts[idx] = counts.get(idx, 0) + 1
                if not counts:
                    continue
                best = max(counts, key=counts.get)
                try:
                    c = candidates[int(best)]
                except (IndexError, ValueError, TypeError):
                    continue
                name = names.get(c.get('user_id')) or NAME_OVERRIDES.get(c.get('name'), c.get('name', '?'))
                lore['highlights'].append({'name': name, 'text': c.get('text', '')})
        except Exception as e:
            logger.warning(f"Dungeon: lore lookup failed, using plain layout: {e}")
        return lore

    # ── daily layout ──────────────────────────────────────────────────────────
    async def get_or_create_daily(self, day: date) -> list:
        await self.ensure_tables()
        rows = await self.db.execute_query_strict("SELECT layout FROM dungeon_daily WHERE date = %s", (day,))
        if rows:
            layout = rows[0][0]
            return json.loads(layout) if isinstance(layout, str) else layout
        rage = False
        try:
            from services.boss_service import get_boss_service
            boss = get_boss_service()
            ev = await boss.get_active_event() if boss else None
            rage = bool(ev and ev.get('rage'))
        except Exception:
            pass
        lore = await self.build_lore()
        layout = logic.generate_layout(f"dungeon:{day.isoformat()}", self.content, lore, rage)
        await self.db.execute_query_strict(
            "INSERT INTO dungeon_daily (date, layout, rage) VALUES (%s, %s, %s) ON CONFLICT (date) DO NOTHING",
            (day, json.dumps(layout, ensure_ascii=False), rage),
        )
        rows = await self.db.execute_query_strict("SELECT layout FROM dungeon_daily WHERE date = %s", (day,))
        if not rows:
            raise RuntimeError('Dungeon daily layout was not persisted')
        layout = rows[0][0]
        return json.loads(layout) if isinstance(layout, str) else layout

    # ── runs ──────────────────────────────────────────────────────────────────
    async def get_run(self, day: date, player_id: int) -> Optional[dict]:
        await self.ensure_tables()
        rows = await self.db.execute_query_strict(
            "SELECT state FROM dungeon_runs WHERE date = %s AND player_id = %s", (day, player_id)
        )
        if not rows:
            return None
        st = rows[0][0]
        return json.loads(st) if isinstance(st, str) else st

    async def get_or_create_run(self, day: date, player_id: int, player_name: str) -> dict:
        state = await self.get_run(day, player_id)
        if state:
            return state
        layout = await self.get_or_create_daily(day)
        state = logic.new_run(f"dungeon:{day.isoformat()}:{player_id}", layout,
                              modifier=logic.daily_modifier(f"dungeon:{day.isoformat()}"))
        # Opening a second tab must never overwrite a run created by another request.
        await self.save_run(day, player_id, player_name, state, create_only=True)
        persisted = await self.get_run(day, player_id)
        if persisted is None:
            raise RuntimeError('Dungeon run was not persisted')
        return persisted

    async def save_run(self, day: date, player_id: int, player_name: str, state: dict,
                       *, create_only: bool = False, connection=None):
        finished = logic.is_finished(state)
        conflict = "ON CONFLICT (date, player_id) DO NOTHING" if create_only else (
            "ON CONFLICT (date, player_id) DO UPDATE SET state = EXCLUDED.state, player_name = EXCLUDED.player_name, "
            "finished = EXCLUDED.finished, won = EXCLUDED.won, rooms_cleared = EXCLUDED.rooms_cleared, "
            "finished_at = COALESCE(dungeon_runs.finished_at, EXCLUDED.finished_at)"
        )
        execute = connection.execute if connection is not None else self.db.execute_query_strict
        await execute(
            "INSERT INTO dungeon_runs (date, player_id, player_name, state, finished, won, rooms_cleared, finished_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) " + conflict,
            (day, player_id, player_name, json.dumps(state, ensure_ascii=False), finished,
             state['phase'] == 'won', state['rooms_cleared'], datetime.now(KYIV) if finished else None),
        )

    async def act(self, player_id: int, player_name: str, action: str) -> tuple:
        """Apply one action to today's run. Returns (state, events) where events tells the
        caller what just happened so it can deal boss damage / notify the chat."""
        day = self.today()
        await self.get_or_create_run(day, player_id, player_name)
        # Lock in PostgreSQL, so requests from different processes share the same guard.
        async with self.db.connection() as conn:
            async with conn.transaction():
                cursor = await conn.execute(
                    "SELECT state FROM dungeon_runs WHERE date = %s AND player_id = %s FOR UPDATE",
                    (day, player_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise RuntimeError('Dungeon run disappeared before action')
                state = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                before_cleared = state['rooms_cleared']
                before_finished = logic.is_finished(state)
                before_boss = state['boss_killed']
                if not before_finished:
                    logic.apply_action(state, action, self.content)
                    await self.save_run(day, player_id, player_name, state, connection=conn)
        events = {
            'rooms_delta': state['rooms_cleared'] - before_cleared,
            'boss_killed_now': state['boss_killed'] and not before_boss,
            'finished_now': logic.is_finished(state) and not before_finished,
        }
        return state, events

    def view(self, state: dict) -> dict:
        return logic.public_view(state, self.content)

    # ── results ───────────────────────────────────────────────────────────────
    async def today_results(self, day: Optional[date] = None) -> list:
        await self.ensure_tables()
        day = day or self.today()
        rows = await self.db.execute_query(
            "SELECT player_name, rooms_cleared, won, finished, state->'boss_killed' FROM dungeon_runs "
            "WHERE date = %s ORDER BY won DESC, rooms_cleared DESC, finished_at ASC NULLS LAST", (day,)
        )
        return [(r[0] or 'Игрок', int(r[1]), bool(r[2]), bool(r[3])) for r in (rows or [])]

    @staticmethod
    def result_line(name: str, rooms: int, won: bool, finished: bool) -> str:
        if won:
            return f"👑 {name} — прошёл все 10 комнат. Мини-Пуджик побеждён"
        if finished:
            return f"💀 {name} — погиб в комнате {min(rooms + 1, logic.ROOMS)}"
        return f"🚶 {name} — проходит данж, комната {min(rooms + 1, logic.ROOMS)}"

    async def summary_block(self, day: Optional[date] = None) -> str:
        """Block for the evening «правильные ответы» post."""
        try:
            results = await self.today_results(day)
        except Exception as e:
            logger.warning(f"Dungeon: summary failed: {e}")
            return ""
        if not results:
            return "\n\n🏰 <b>Данж дня</b>\nСегодня в подземелье никто не спускался. Мини-Пуджик выспался."
        lines = ["", "", "🏰 <b>Данж дня</b>"]
        for name, rooms, won, finished in results:
            lines.append(escape(self.result_line(name, rooms, won, finished)))
        return "\n".join(lines)


_instance: Optional[DungeonService] = None


def get_dungeon_service(db_manager=None, content: Optional[dict] = None) -> Optional[DungeonService]:
    global _instance
    if _instance is None and db_manager is not None and content is not None:
        _instance = DungeonService(db_manager, content)
    return _instance
