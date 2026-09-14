from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from aiogram import Bot, Dispatcher, Router
from aiogram.types import Chat, Message, Update, User

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from handlers.boss_handlers import BossHandlers, BossRiddleMiddleware
from services import boss_service
from services.boss_service import BossService


def test_days_left_rounds_partial_days_up(monkeypatch):
    now = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(boss_service, "_now", lambda: now)

    assert BossService.days_left({"ends_at": now + timedelta(days=14)}) == 14
    assert BossService.days_left({"ends_at": now + timedelta(days=13, seconds=1)}) == 14
    assert BossService.days_left({"ends_at": now - timedelta(seconds=1)}) == 0


def test_duration_text_uses_russian_plural_forms():
    assert BossHandlers._duration_text(1) == "1 день"
    assert BossHandlers._duration_text(2) == "2 дня"
    assert BossHandlers._duration_text(5) == "5 дней"
    assert BossHandlers._duration_text(14) == "14 дней"
    assert BossHandlers._duration_text(21) == "21 день"
    assert BossHandlers._duration_elapsed_text(1) == "1 день прошёл"
    assert BossHandlers._duration_elapsed_text(14) == "14 дней прошло"


def test_intro_uses_noise_motive_and_only_days_placeholder():
    import json

    plot_path = Path(__file__).resolve().parents[1] / "assets" / "data" / "plot.json"
    intro = json.loads(plot_path.read_text(encoding="utf-8"))["boss_intro"]
    joined = "\n".join(intro)

    assert intro.count("...") == 1
    assert intro.count(".....") == 1
    assert "An IQ too low?" in joined
    assert "Quiz" not in joined
    assert "Мини-Пуджик" in joined
    assert "{days}" in joined
    assert "summon_count" not in joined
    assert "summoner" not in joined


@pytest.mark.asyncio
async def test_mvp_respect_is_injected_into_jarvis_context_for_one_week(monkeypatch):
    import json

    now = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(boss_service, "_now", lambda: now)
    content_path = Path(__file__).resolve().parents[1] / "assets" / "data" / "pudge_event.json"
    content = json.loads(content_path.read_text(encoding="utf-8"))
    event = {
        "status": "won",
        "meta": {
            "respect": {
                "name": "Макс",
                "until": (now + timedelta(days=boss_service.RESPECT_DAYS)).isoformat(),
            }
        },
    }
    service = BossService(None)

    async def no_active_event():
        return None

    async def last_event():
        return event

    service.get_active_event = no_active_event
    service.get_last_event = last_event

    await service.refresh_caches(content)

    assert boss_service.RESPECT_DAYS == 7
    assert "Макс" in service.persona_injection
    assert "искренним уважением" in service.persona_injection
    assert "любое изменение" in service.persona_injection

    event["meta"]["respect"]["until"] = now.isoformat()
    await service.refresh_caches(content)
    assert service.persona_injection == ""


class DamageDB:
    def __init__(self, row):
        self.row = row
        self.calls = []

    async def execute_query(self, query, params=None):
        self.calls.append((query, params))
        return [self.row]


@pytest.mark.asyncio
async def test_damage_uses_one_atomic_state_and_log_query():
    db = DamageDB((7, 620, 1000, 670, 0, 1, 1, 1))
    service = BossService(db)
    service._tables_ready = True

    result = await service.deal_damage(42, "Макс", "dungeon_room", 50)

    assert result == {
        "event_id": 7,
        "damage": 50,
        "hp": 620,
        "max_hp": 1000,
        "killed": False,
        "multiplier": 1,
        "scenes": ["hijack"],
    }
    assert len(db.calls) == 1
    query, params = db.calls[0]
    assert "FOR UPDATE" in query
    assert "INSERT INTO boss_damage_log" in query
    assert "rage_available" in query
    assert params[0] == boss_service.RAGE_UNLOCK_OFFSET_DAYS
    assert params[-3:] == (42, "Макс", "dungeon_room")


@pytest.mark.asyncio
async def test_overkill_records_only_hp_actually_removed():
    db = DamageDB((7, 0, 1000, 12, 2, 2, 2, 1))
    service = BossService(db)
    service._tables_ready = True

    result = await service.deal_damage(42, "Макс", "admin", 50)

    assert result["damage"] == 12
    assert result["killed"] is True
    assert result["scenes"] == ["win"]


def test_rage_and_riddle_weakness_never_stack_above_x2(monkeypatch):
    now = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(boss_service, "_now", lambda: now)
    service = BossService(None)

    assert service.multiplier({"rage": True, "weak_until": now + timedelta(hours=2)}) == 2
    assert service.multiplier({"rage": True, "weak_until": None}) == 2
    assert service.multiplier({"rage": False, "weak_until": now + timedelta(hours=2)}) == 2
    assert service.multiplier({"rage": False, "weak_until": now - timedelta(seconds=1)}) == 1


def test_riddle_closes_at_its_persisted_deadline(monkeypatch):
    now = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(boss_service, "_now", lambda: now)
    service = BossService(None)
    event = {"meta": {"riddle": {"question": "?"}, "riddle_solved": False}}

    event["meta"]["riddle_expires_at"] = (now + timedelta(seconds=1)).isoformat()
    assert service.riddle_is_open(event) is True
    event["meta"]["riddle_expires_at"] = now.isoformat()
    assert service.riddle_is_open(event) is False


@pytest.mark.asyncio
async def test_riddle_middleware_observes_then_passes_message_once():
    calls = []

    class Boss:
        async def inspect_riddle_message(self, event):
            calls.append(("riddle", event))

    async def downstream(event, data):
        calls.append(("downstream", event))
        return "handled"

    event = SimpleNamespace(text="ответ")
    result = await BossRiddleMiddleware(Boss())(downstream, event, {})

    assert result == "handled"
    assert calls == [("riddle", event), ("downstream", event)]


@pytest.mark.asyncio
async def test_riddle_middleware_failure_never_intercepts_message():
    downstream_calls = []

    class BrokenBoss:
        async def inspect_riddle_message(self, event):
            raise RuntimeError("broken side event")

    async def downstream(event, data):
        downstream_calls.append(event)

    event = SimpleNamespace(text="сообщение суда")
    await BossRiddleMiddleware(BrokenBoss())(downstream, event, {})

    assert downstream_calls == [event]


@pytest.mark.asyncio
async def test_outer_riddle_middleware_runs_before_a_catch_all_router():
    calls = []

    class Boss:
        async def inspect_riddle_message(self, event):
            calls.append("riddle")

    router = Router()

    @router.message()
    async def catch_all(message):
        calls.append("catch_all")

    dispatcher = Dispatcher()
    dispatcher.message.outer_middleware(BossRiddleMiddleware(Boss()))
    dispatcher.include_router(router)
    bot = Bot(token="123456:TEST_TOKEN")
    message = Message(
        message_id=1, date=datetime.now(timezone.utc),
        chat=Chat(id=-100, type="group"),
        from_user=User(id=11, is_bot=False, first_name="Макс"),
        text="ответ",
    )
    try:
        await dispatcher.feed_update(bot, Update(update_id=1, message=message))
    finally:
        await bot.session.close()

    assert calls == ["riddle", "catch_all"]


@pytest.mark.asyncio
async def test_regen_is_one_locked_update():
    db = DamageDB((50,))
    service = BossService(db)
    service._tables_ready = True

    assert await service.regen_if_idle() == 50
    assert len(db.calls) == 1
    query, params = db.calls[0]
    assert "FOR UPDATE" in query
    assert "last_damage_at" in query
    assert params == (boss_service.REGEN_RATIO,)


LOBBY_ROW = (
    4, -100, 77, 1, 2500, 14, "countdown",
    {"11": "Макс", "22": "Юра", "33": "Богдан"}, {"11": True},
    datetime.now(timezone.utc) + timedelta(seconds=10), 0, 0, None,
    datetime.now(timezone.utc), datetime.now(timezone.utc),
)


class SequencedDB:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def execute_query(self, query, params=None):
        self.calls.append((query, params))
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_ready_click_is_atomic_and_first_click_owns_deadline():
    db = SequencedDB([[(4,)], [LOBBY_ROW]])
    service = BossService(db)
    service._tables_ready = True

    lobby = await service.mark_lobby_ready(4, 11, 10)

    assert lobby["ready_players"] == {"11": True}
    query, params = db.calls[0]
    assert "FOR UPDATE" in query
    assert "required_players ? %s" in query
    assert "COALESCE(b.deadline" in query
    assert "jsonb_build_object" in query
    assert params == (4, "11", "11", 10, "11")
    assert "THEN 'starting' ELSE 'countdown'" in query


@pytest.mark.asyncio
async def test_rejected_ready_click_returns_none_without_followup_read():
    db = SequencedDB([[]])
    service = BossService(db)
    service._tables_ready = True

    assert await service.mark_lobby_ready(4, 999, 10) is None
    assert len(db.calls) == 1


@pytest.mark.asyncio
async def test_round_resolution_is_one_locked_claim_or_reset():
    reset_row = list(LOBBY_ROW)
    reset_row[6] = "waiting"
    reset_row[8] = {}
    reset_row[9] = None
    reset_row[10] = 1
    db = SequencedDB([[(4,)], [tuple(reset_row)]])
    service = BossService(db)
    service._tables_ready = True

    lobby = await service.resolve_lobby_round(4)

    assert lobby["status"] == "waiting"
    assert lobby["ready_players"] == {}
    query, _ = db.calls[0]
    assert "FOR UPDATE" in query
    assert "status = CASE WHEN t.complete THEN 'starting' ELSE 'waiting' END" in query
    assert "ready_players = CASE WHEN t.complete" in query
    assert "attempts = b.attempts + 1" in query


def test_lobby_text_keeps_same_message_and_shows_failed_attempt():
    handler = object.__new__(BossHandlers)
    lobby = {
        "id": 4,
        "status": "waiting",
        "attempts": 1,
        "required_players": {"11": "Макс", "22": "Юра", "33": "Богдан"},
        "ready_players": {},
        "deadline": None,
    }

    text = handler._lobby_text(lobby)

    assert "Не собрались" in text
    assert text.count("⚪️") == 3
    assert "Первое нажатие запустит 10 секунд" in text


@pytest.mark.asyncio
async def test_expired_incomplete_round_edits_in_place_and_does_not_launch():
    expired = {
        "id": 4, "chat_id": -100, "message_id": 77, "status": "countdown",
        "deadline": datetime.now(timezone.utc) - timedelta(seconds=1),
        "attempts": 0, "required_players": {"11": "Макс", "22": "Юра", "33": "Богдан"},
        "ready_players": {"11": True},
    }
    reset = {**expired, "status": "waiting", "deadline": None, "attempts": 1, "ready_players": {}}

    class LobbyService:
        async def get_open_lobby(self):
            return expired

        async def resolve_lobby_round(self, lobby_id):
            assert lobby_id == 4
            return reset

    edits = []
    handler = object.__new__(BossHandlers)
    handler.svc = LobbyService()
    handler._lobby_tick_lock = __import__('asyncio').Lock()
    handler._edit_lobby = lambda lobby, *args, **kwargs: _record_async(edits, lobby)
    handler._track_launch = lambda lobby: (_ for _ in ()).throw(AssertionError("must not launch"))

    await handler.lobby_tick()

    assert edits == [reset]


@pytest.mark.asyncio
async def test_starting_lobby_is_recovered_after_process_restart():
    starting = {
        "id": 4, "chat_id": -100, "message_id": 77, "status": "starting",
        "deadline": datetime.now(timezone.utc), "attempts": 0,
        "required_players": {"11": "Макс", "22": "Юра", "33": "Богдан"},
        "ready_players": {"11": True, "22": True, "33": True},
    }

    class LobbyService:
        async def get_open_lobby(self):
            return starting

    launches = []
    handler = object.__new__(BossHandlers)
    handler.svc = LobbyService()
    handler._lobby_tick_lock = __import__('asyncio').Lock()
    handler._edit_lobby = lambda *args, **kwargs: _record_async([], None)
    handler._track_launch = launches.append

    await handler.lobby_tick()

    assert launches == [starting]


@pytest.mark.asyncio
async def test_intro_resume_skips_checkpointed_lines_and_saves_each_new_line():
    class Bot:
        def __init__(self):
            self.messages = []

        async def send_message(self, chat_id, text, **kwargs):
            self.messages.append((chat_id, text))

    handler = object.__new__(BossHandlers)
    handler.bot = Bot()
    progress = []

    await handler.play_scene(
        -100, ["первая", "вторая", "третья"], {}, fast=True, start_at=1,
        on_progress=lambda index: _record_async(progress, index),
    )

    assert handler.bot.messages == [(-100, "вторая"), (-100, "третья")]
    assert progress == [2, 3]


@pytest.mark.asyncio
async def test_cancelled_lobby_cannot_be_marked_started():
    db = SequencedDB([[]])
    service = BossService(db)
    service._tables_ready = True

    assert await service.mark_lobby_started(4, 9) is False
    query, params = db.calls[0]
    assert "status = 'starting' RETURNING id" in query
    assert params == (9, 4)


async def _record_async(target, value):
    target.append(value)
