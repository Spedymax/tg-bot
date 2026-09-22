from datetime import date, datetime, timedelta, timezone
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
    db = DamageDB((7, 620, 1000, 670, 0, 1, 1, 50, 0, 1))
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
        "rage_hp_bonus": 0,
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
    db = DamageDB((7, 0, 1000, 12, 2, 2, 2, 12, 0, 1))
    service = BossService(db)
    service._tables_ready = True

    result = await service.deal_damage(42, "Макс", "admin", 50)

    assert result["damage"] == 12
    assert result["killed"] is True
    assert result["scenes"] == ["win"]


@pytest.mark.asyncio
async def test_rage_levelup_adds_thirty_percent_hp_without_hiding_hit_damage():
    # The hit takes 10 HP (830 -> 820), then the one-off Flesh Heap talent adds
    # 750 to both current and maximum HP (2500 * 30%).
    db = DamageDB((7, 1570, 3250, 830, 1, 2, 1, 10, 750, 1))
    service = BossService(db)
    service._tables_ready = True

    result = await service.deal_damage(42, "Макс", "admin", 10)

    assert result["damage"] == 10
    assert result["hp"] == 1570
    assert result["max_hp"] == 3250
    assert result["rage_hp_bonus"] == 750
    assert result["scenes"] == ["rage"]
    query, params = db.calls[0]
    assert "max_hp = c.max_hp + c.rage_hp_bonus" in query
    assert "SELECT id, %s, %s, %s, applied_damage" in query
    assert params[4] == boss_service.RAGE_HP_BONUS_RATIO


@pytest.mark.asyncio
async def test_daily_damage_can_be_requested_for_previous_calendar_day():
    db = DamageDB((42, "Макс", 123))
    service = BossService(db)
    service._tables_ready = True

    rows = await service.damage_by_player(7, today_only=True, day=date(2026, 9, 20))

    assert rows == [(42, "Макс", 123)]
    query, params = db.calls[0]
    assert "created_at >= %s AND created_at < %s" in query
    assert params[1].date() == date(2026, 9, 20)
    assert params[2].date() == date(2026, 9, 21)
    assert str(params[1].tzinfo) == "Europe/Kyiv"


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


# ── chat write budget ────────────────────────────────────────────────────────
# Telegram allows ~20 messages/min per group and counts edits. A per-second
# lobby countdown plus a 35-line intro blew through that on 2026-09-15: the
# chat was flood-banned for ~35s and the event failed to launch.

class _AsyncioWithFakeSleep:
    """Everything real except sleep — patching asyncio.sleep globally would
    reach the test loop itself."""

    def __init__(self, real, sleep):
        self._real = real
        self.sleep = sleep

    def __getattr__(self, name):
        return getattr(self._real, name)


def _patch_sleep(monkeypatch):
    """Make boss_handlers' sleeps instant; returns the list of slept seconds."""
    import asyncio as _asyncio
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    module = sys.modules[BossHandlers.__module__]
    monkeypatch.setattr(module, "asyncio", _AsyncioWithFakeSleep(_asyncio, fake_sleep))
    return slept


def _retry_after(seconds: int):
    from aiogram.methods import SendMessage
    from aiogram.exceptions import TelegramRetryAfter
    return TelegramRetryAfter(SendMessage(chat_id=-100, text="x"), "Too Many Requests", seconds)


def _gated_handler():
    handler = object.__new__(BossHandlers)
    handler._chat_calls = {}
    handler._flood_until = {}
    handler._last_lobby_text = {}
    handler._last_lobby_edit = {}
    return handler


def _spend_budget(handler, chat_id):
    from handlers.boss_handlers import CHAT_RATE_LIMIT
    import time as _time
    from collections import deque
    handler._chat_calls[chat_id] = deque([_time.monotonic()] * CHAT_RATE_LIMIT)


class RecordingBot:
    def __init__(self, fail_times=0, retry_after=1):
        self.edits = []
        self.messages = []
        self.fail_times = fail_times
        self.retry_after = retry_after

    async def edit_message_text(self, text, **kwargs):
        self.edits.append(text)

    async def send_message(self, chat_id, text, **kwargs):
        if self.fail_times > 0:
            self.fail_times -= 1
            raise _retry_after(self.retry_after)
        self.messages.append((chat_id, text))


def _countdown_lobby(seconds):
    return {
        "id": 4, "chat_id": -100, "message_id": 77, "status": "countdown",
        "attempts": 0, "required_players": {"11": "Макс", "22": "Юра", "33": "Богдан"},
        "ready_players": {"11": True},
        "deadline": datetime.now(timezone.utc) + timedelta(seconds=seconds),
    }


def test_countdown_is_rounded_instead_of_ticking_every_second():
    handler = object.__new__(BossHandlers)
    assert "~10" in handler._lobby_text(_countdown_lobby(9))
    assert "~10" in handler._lobby_text(_countdown_lobby(7))
    assert "~5" in handler._lobby_text(_countdown_lobby(4))


@pytest.mark.asyncio
async def test_same_text_is_never_re_sent():
    """The tick repeats "Начинаем..." every second while the intro plays; an edit
    rejected as "not modified" still costs a slot of the chat's budget."""
    handler = _gated_handler()
    handler.bot = RecordingBot()
    lobby = _countdown_lobby(10)

    for _ in range(5):
        await handler._edit_lobby(lobby, "✅ Начинаем...", with_button=False)

    assert handler.bot.edits == ["✅ Начинаем..."]


@pytest.mark.asyncio
async def test_countdown_refresh_is_throttled():
    handler = _gated_handler()
    handler.bot = RecordingBot()

    await handler._edit_lobby(_countdown_lobby(10))
    await handler._edit_lobby(_countdown_lobby(3))  # different text, too soon

    assert len(handler.bot.edits) == 1


@pytest.mark.asyncio
async def test_edit_is_skipped_when_the_chat_budget_is_spent():
    handler = _gated_handler()
    handler.bot = RecordingBot()
    _spend_budget(handler, -100)

    await handler._edit_lobby(_countdown_lobby(10), "✅ Начинаем...", with_button=False)

    assert handler.bot.edits == []


@pytest.mark.asyncio
async def test_flood_response_holds_every_write_to_that_chat():
    handler = _gated_handler()
    handler.bot = RecordingBot()
    handler._note_flood(-100, _retry_after(30))

    assert handler._chat_slot_delay(-100) > 25
    assert handler._chat_slot_delay(-999) == 0  # other chats unaffected
    await handler._edit_lobby(_countdown_lobby(10), "✅ Начинаем...", with_button=False)
    assert handler.bot.edits == []


@pytest.mark.asyncio
async def test_chat_write_waits_out_a_flood_and_retries_once(monkeypatch):
    slept = _patch_sleep(monkeypatch)
    handler = _gated_handler()
    bot = RecordingBot(fail_times=1, retry_after=7)

    await handler._chat_write(-100, lambda: bot.send_message(-100, "строка"))

    assert bot.messages == [(-100, "строка")]
    assert slept and slept[0] >= 7  # waited out the penalty instead of hammering
    assert len(handler._chat_calls[-100]) == 1


@pytest.mark.asyncio
async def test_chat_write_gives_up_after_the_second_flood(monkeypatch):
    _patch_sleep(monkeypatch)
    handler = _gated_handler()
    bot = RecordingBot(fail_times=2)
    from aiogram.exceptions import TelegramRetryAfter

    with pytest.raises(TelegramRetryAfter):
        await handler._chat_write(-100, lambda: bot.send_message(-100, "строка"))


@pytest.mark.asyncio
async def test_cutscene_paces_itself_inside_the_budget(monkeypatch):
    """35 intro lines must not spend the whole per-minute budget in one burst."""
    from handlers.boss_handlers import CHAT_RATE_LIMIT, CHAT_RATE_WINDOW
    slept = _patch_sleep(monkeypatch)
    handler = _gated_handler()
    handler.bot = RecordingBot()

    await handler.play_scene(-100, ["строка номер один"] * 5, {})

    assert len(handler.bot.messages) == 5
    # pacing floor keeps the scene under the budget on its own
    assert min(slept) >= CHAT_RATE_WINDOW / CHAT_RATE_LIMIT


@pytest.mark.asyncio
async def test_flood_during_the_intro_keeps_the_lobby_startable(monkeypatch):
    """A flood ban must not cost the players their round: the lobby stays
    'starting' and the tick resumes the intro from its checkpoint."""
    _patch_sleep(monkeypatch)
    handler = _gated_handler()
    handler.bot = RecordingBot(fail_times=99, retry_after=30)
    handler._start_lock = __import__('asyncio').Lock()
    handler.content = {"boss_intro": ["первая строка"]}
    resets = []

    class LobbyService:
        async def get_active_event(self):
            return None

        async def set_lobby_intro_index(self, lobby_id, index):
            return True

        async def reset_lobby(self, lobby_id):
            resets.append(lobby_id)

    handler.svc = LobbyService()
    handler._intro_context = lambda days: _record_value({"days": str(days)})

    result = await handler.start_event(-100, 2500, 14, lobby={"id": 4, "chat_id": -100, "intro_index": 0})

    assert result is None
    assert resets == []                       # the round is not thrown away
    assert handler._chat_slot_delay(-100) > 25  # and the chat is left alone meanwhile


async def _record_value(value):
    return value


@pytest.mark.asyncio
async def test_final_lobby_line_waits_for_a_slot_instead_of_being_dropped(monkeypatch):
    """After a 35-line intro the budget is spent, but "Ивент начался" still has
    to land — otherwise the lobby message is stuck on "Начинаем..." forever."""
    slept = _patch_sleep(monkeypatch)
    handler = _gated_handler()
    handler.bot = RecordingBot()
    _spend_budget(handler, -100)

    await handler._edit_lobby(_countdown_lobby(10), "✅ Ивент начался.", with_button=False, wait=True)

    assert handler.bot.edits == ["✅ Ивент начался."]
    assert slept and slept[0] > 0


class RestartService:
    """Persisted data outlives each newly constructed handler in these tests."""
    def __init__(self, event):
        self.event = event
        self.enabled = True

    async def get_active_event(self):
        import copy
        return copy.deepcopy(self.event) if self.event['status'] == 'active' else None

    async def get_last_event(self):
        import copy
        return copy.deepcopy(self.event)

    async def get_event(self, event_id):
        return await self.get_last_event()

    async def update_meta(self, event_id, **fields):
        self.event['meta'].update(fields)

    async def ack_pending_scene(self, event_id, scene):
        assert self.event['meta']['pending'][0] == scene
        self.event['meta']['pending'].pop(0)
        self.event['meta'].pop('scene_index', None)

    async def refresh_caches(self, content):
        pass

    day_number = staticmethod(BossService.day_number)
    riddle_is_open = staticmethod(BossService.riddle_is_open)


def restarted_handler(service, sent, fail_on=None):
    import asyncio
    handler = object.__new__(BossHandlers)
    handler.svc = service
    handler._tick_lock = asyncio.Lock()
    handler.content = {'hijack_scene': ['h1', 'h2'], 'rage_scene': ['r1', 'r2'],
                       'win_scene': ['w1', 'w2'], 'merchant_return': ['m1', '{riddle}']}
    handler._refresh_pin = lambda ev: _record_async([], None)
    handler._unpin = lambda ev: _record_async([], None)

    class Bot:
        async def send_message(self, chat_id, text, **kwargs):
            if text == fail_on:
                raise RuntimeError('process interrupted / Telegram unavailable')
            sent.append(text)

    handler.bot = Bot()
    real_play = handler.play_scene

    async def fast_play(*args, **kwargs):
        await real_play(*args, **kwargs, fast=True)

    handler.play_scene = fast_play
    return handler


def restart_event():
    now = datetime.now(timezone.utc)
    return {'id': 7, 'chat_id': -100, 'status': 'active', 'hp': 600, 'max_hp': 1000,
            'started_at': now, 'ends_at': now + timedelta(days=14),
            'meta': {'pending': ['hijack', 'rage'], 'merchant_done': True}}


@pytest.mark.asyncio
async def test_phase_scenes_resume_after_restart_without_losing_next_scene():
    service = RestartService(restart_event())
    sent = []
    await restarted_handler(service, sent, fail_on='h2').tick()
    assert sent == ['h1']
    assert service.event['meta']['pending'] == ['hijack', 'rage']
    assert service.event['meta']['scene_index'] == 1

    await restarted_handler(service, sent).tick()
    assert sent == ['h1', 'h2', 'r1', 'r2']
    assert service.event['meta']['pending'] == []
    await restarted_handler(service, sent).tick()
    assert len(sent) == 4


@pytest.mark.asyncio
async def test_finalized_event_resumes_finale_after_restart():
    event = restart_event()
    event['status'] = 'won'
    event['meta'].update(finale_pending=True, finale_context={}, finale_index=0)
    service = RestartService(event)
    sent = []
    await restarted_handler(service, sent, fail_on='w2').tick()
    assert event['meta']['finale_pending'] is True
    assert event['meta']['finale_index'] == 1
    await restarted_handler(service, sent).tick()
    assert sent == ['w1', 'w2']
    assert event['meta']['finale_pending'] is False
    await restarted_handler(service, sent).tick()
    assert sent == ['w1', 'w2']


@pytest.mark.asyncio
async def test_merchant_resumes_same_question_after_restart():
    event = restart_event()
    event['meta'].update(pending=[], merchant_pending=True, merchant_index=0,
                         riddle={'question': 'Вопрос'}, riddle_solved=False,
                         riddle_expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
    service = RestartService(event)
    sent = []
    await restarted_handler(service, sent, fail_on='Вопрос').tick()
    assert event['meta']['merchant_index'] == 1
    await restarted_handler(service, sent).tick()
    assert sent == ['m1', 'Вопрос']
    assert event['meta']['merchant_pending'] is False


@pytest.mark.asyncio
async def test_restart_does_not_post_expired_merchant_question():
    event = restart_event()
    event['meta'].update(pending=[], merchant_pending=True, riddle={'question': 'Вопрос'},
                         riddle_expires_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
    sent = []
    await restarted_handler(RestartService(event), sent).tick()
    assert sent == []
    assert event['meta']['merchant_pending'] is False


@pytest.mark.asyncio
async def test_missing_hp_message_is_recreated_after_restart():
    handler = object.__new__(BossHandlers)
    sent, saved, pinned = [], [], []
    class Service:
        async def build_pin_text(self, ev):
            return 'HP 600/1000'
        async def set_message_id(self, event_id, message_id):
            saved.append((event_id, message_id))
    class Bot:
        async def send_message(self, chat_id, text, **kwargs):
            sent.append(text)
            return SimpleNamespace(message_id=99)
        async def pin_chat_message(self, chat_id, message_id, **kwargs):
            pinned.append(message_id)
    handler.svc, handler.bot = Service(), Bot()
    handler._last_pin_text = {}
    handler._chat_write = lambda chat_id, operation: operation()
    handler._markup = lambda: None
    event = restart_event()
    await handler._refresh_pin(event)
    assert sent == ['HP 600/1000']
    assert saved == [(7, 99)]
    assert pinned == [99]


@pytest.mark.asyncio
async def test_boss_state_writes_propagate_database_failures():
    class DB:
        async def execute_query(self, *args):
            raise AssertionError('legacy swallowing API must not be used')
        async def execute_query_strict(self, *args):
            raise RuntimeError('database disconnected')
    service = BossService(DB())
    with pytest.raises(RuntimeError, match='database disconnected'):
        await service.update_meta(7, scene_index=1)
