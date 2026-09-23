"""Tests for moltbot context building helpers."""
import sys, os, importlib.util

# Load moltbot_handlers directly to avoid handlers/__init__.py pulling in psycopg
_src = os.path.join(os.path.dirname(__file__), '..', 'src')
sys.path.insert(0, _src)

# Stub out heavy dependencies before importing the module
import types
for _mod in ('psycopg', 'psycopg_pool', 'google.generativeai'):
    sys.modules.setdefault(_mod, types.ModuleType(_mod))

_spec = importlib.util.spec_from_file_location(
    "handlers.moltbot_handlers",
    os.path.join(_src, "handlers", "moltbot_handlers.py"),
)
_moltbot_mod = importlib.util.module_from_spec(_spec)
sys.modules["handlers.moltbot_handlers"] = _moltbot_mod
_spec.loader.exec_module(_moltbot_mod)
MoltbotHandlers = _moltbot_mod.MoltbotHandlers

import pytest
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import AsyncMock, MagicMock, patch

CPH = ZoneInfo("Europe/Copenhagen")


class TestTimestampFormatting:
    def test_utc_to_copenhagen(self):
        dt = datetime(2026, 3, 14, 15, 30, 0, tzinfo=ZoneInfo("UTC"))
        assert MoltbotHandlers._format_ts(dt) == "[16:30 14.03]"

    def test_naive_datetime_treated_as_utc(self):
        dt = datetime(2026, 3, 14, 15, 30, 0)
        assert MoltbotHandlers._format_ts(dt) == "[16:30 14.03]"

    def test_summer_time_cest(self):
        dt = datetime(2026, 7, 1, 12, 0, 0, tzinfo=ZoneInfo("UTC"))
        assert MoltbotHandlers._format_ts(dt) == "[14:00 01.07]"

    def test_midnight_rolls_date(self):
        dt = datetime(2026, 3, 14, 23, 30, 0, tzinfo=ZoneInfo("UTC"))
        assert MoltbotHandlers._format_ts(dt) == "[00:30 15.03]"

    def test_none_returns_empty(self):
        assert MoltbotHandlers._format_ts(None) == ""


class TestGetRecentGroupMessages:
    @pytest.mark.asyncio
    async def test_messages_include_timestamps(self):
        db = AsyncMock()
        # DB returns newest-first; code reverses to get chronological order
        db.execute_query = AsyncMock(return_value=[
            ("Юра", "здарова", datetime(2026, 3, 14, 15, 5, 0)),
            ("Богдан", "привет", datetime(2026, 3, 14, 15, 0, 0)),
        ])

        with patch.object(MoltbotHandlers, '__init__', lambda self, *a, **kw: None):
            handler = MoltbotHandlers.__new__(MoltbotHandlers)
            handler.db = db
            handler._history_reset_time = {}

            result = await handler._get_recent_group_messages(-1001, limit=50)

        assert len(result) == 2
        assert "[16:00 14.03] Богдан: привет" in result[0]
        assert "[16:05 14.03] Юра: здарова" in result[1]

    @pytest.mark.asyncio
    async def test_null_timestamp_handled(self):
        db = AsyncMock()
        db.execute_query = AsyncMock(return_value=[
            ("Юра", "old msg", None),
        ])

        with patch.object(MoltbotHandlers, '__init__', lambda self, *a, **kw: None):
            handler = MoltbotHandlers.__new__(MoltbotHandlers)
            handler.db = db
            handler._history_reset_time = {}

            result = await handler._get_recent_group_messages(-1001, limit=50)

        assert len(result) == 1
        assert "Юра: old msg" in result[0]

    @pytest.mark.asyncio
    async def test_history_is_scoped_to_chat_and_excludes_current_turn(self):
        records = [
            (-1001, 10, "Макс", "только первый чат", datetime(2026, 3, 14, 15, 0)),
            (-2002, 10, "Юра", "секрет второго чата", datetime(2026, 3, 14, 15, 1)),
            (-1001, 11, "Богдан", "текущий turn", datetime(2026, 3, 14, 15, 2)),
        ]

        class ScopedDb:
            async def execute_query(self, query, params):
                assert "WHERE chat_id = %s" in query
                chat_id, excluded, excluded_again, limit = params
                assert excluded == excluded_again
                rows = [
                    (name, text, timestamp)
                    for row_chat_id, message_id, name, text, timestamp in records
                    if row_chat_id == chat_id and message_id != excluded
                ]
                return list(reversed(rows[-limit:]))

        handler = MoltbotHandlers.__new__(MoltbotHandlers)
        handler.db = ScopedDb()
        handler._history_reset_time = {}

        history = await handler._get_recent_group_messages(
            -1001, limit=50, exclude_message_id=11
        )

        assert len(history) == 1
        assert "только первый чат" in history[0]
        assert all("секрет второго чата" not in line for line in history)
        assert all("текущий turn" not in line for line in history)

    @pytest.mark.asyncio
    async def test_current_turn_occurs_once_in_model_messages(self):
        handler = MoltbotHandlers.__new__(MoltbotHandlers)
        with patch.object(_moltbot_mod, '_load_chat_summary', return_value=''), \
                patch.object(_moltbot_mod, '_load_chat_lore', return_value=''):
            messages = await handler._build_persona_messages(
                "Богдан",
                "текущий turn",
                "групповой чат",
                ["[16:00 14.03] Макс: предыдущий turn"],
                -1001,
            )

        assert sum("текущий turn" in (item.get("content") or "") for item in messages) == 1

    @pytest.mark.asyncio
    async def test_reply_chain_is_scoped_to_chat(self):
        db = AsyncMock(return_value=None)
        db.execute_query = AsyncMock(return_value=[
            ("Макс", "корень ветки", datetime(2026, 3, 14, 14, 55)),
            ("Jarvis", "ответ в ветке", datetime(2026, 3, 14, 15, 0)),
        ])
        handler = MoltbotHandlers.__new__(MoltbotHandlers)
        handler.db = db

        chain = await handler._get_reply_chain(-1001, 42)

        query, params = db.execute_query.await_args.args
        assert "WHERE chat_id = %s AND message_id = %s" in query
        assert "parent.chat_id = %s" in query
        assert params[:3] == (-1001, 42, -1001)
        assert "корень ветки" in chain[0]
        assert "ответ в ветке" in chain[1]

    @pytest.mark.asyncio
    async def test_reply_chain_precedes_recent_scene_and_is_deduplicated(self):
        handler = MoltbotHandlers.__new__(MoltbotHandlers)
        handler._get_reply_chain = AsyncMock(return_value=[
            "[15:00 14.03] Макс: начало ветки",
            "[15:05 14.03] Jarvis: ответ",
        ])
        handler._get_recent_group_messages = AsyncMock(return_value=[
            "[15:05 14.03] Jarvis: ответ",
            "[15:10 14.03] Юра: соседняя сцена",
        ])

        history = await handler._build_thread_first_history(-1001, 42, 43)

        assert history == [
            "[15:00 14.03] Макс: начало ветки",
            "[15:05 14.03] Jarvis: ответ",
            "[15:10 14.03] Юра: соседняя сцена",
        ]
        handler._get_recent_group_messages.assert_awaited_once_with(
            -1001, limit=100, exclude_message_id=43
        )

    @pytest.mark.asyncio
    async def test_history_obeys_message_and_character_budgets(self):
        handler = MoltbotHandlers.__new__(MoltbotHandlers)
        handler._get_reply_chain = AsyncMock(return_value=["thread"])
        handler._get_recent_group_messages = AsyncMock(return_value=[
            "old-ambient", "middle", "newest"
        ])

        history = await handler._build_thread_first_history(
            -1001, 42, 43, recent_limit=3, char_budget=19
        )

        assert history == ["thread", "middle", "newest"]


class TestAskMoltbotContext:
    @pytest.mark.asyncio
    async def test_persona_messages_keep_history_memory_and_current_user_separate(self):
        with patch.object(MoltbotHandlers, '__init__', lambda self, *a, **kw: None):
            handler = MoltbotHandlers.__new__(MoltbotHandlers)
            with patch.object(_moltbot_mod, '_load_chat_summary', return_value='Память компании'), \
                    patch.object(_moltbot_mod, '_load_chat_lore', return_value=''):
                messages = await handler._build_persona_messages(
                    "Юра", "привет", "групповой чат",
                    history=["[16:00 14.03] Богдан: тест"]
                )
            assert messages[-1] == {'role': 'user', 'content': 'Юра: привет'}
            assert {'role': 'user', 'content': 'Богдан: тест'} in messages
            assert 'групповой чат' in messages[0]['content']
            assert 'Память компании' in messages[0]['content']
            assert messages[-2]['role'] == 'system'
            assert messages[-2]['content'].startswith(handler._POST_PROMPT_BASE)
            assert 'Текущее время' in messages[-2]['content']


def _make_message(text=None, caption=None, from_user_id=855951767,
                  from_user_name="Богдан", is_bot=False,
                  photo=None, sticker_emoji=None,
                  reply_to=None, date=None):
    """Build a mock Message with common fields."""
    msg = MagicMock()
    msg.text = text
    msg.caption = caption
    msg.date = date or datetime(2026, 3, 14, 15, 30, 0, tzinfo=ZoneInfo("UTC"))

    if from_user_id is not None:
        msg.from_user = MagicMock()
        msg.from_user.id = from_user_id
        msg.from_user.first_name = from_user_name
        msg.from_user.is_bot = is_bot
    else:
        msg.from_user = None

    msg.photo = photo
    msg.sticker = None
    msg.voice = None
    msg.audio = None
    msg.video_note = None
    msg.animation = None
    msg.document = None
    msg.video = None

    if sticker_emoji:
        msg.sticker = MagicMock()
        msg.sticker.emoji = sticker_emoji

    msg.reply_to_message = reply_to
    return msg


class TestBuildReplyContext:
    @pytest.mark.asyncio
    async def test_no_reply_returns_empty(self):
        with patch.object(MoltbotHandlers, '__init__', lambda self, *a, **kw: None):
            handler = MoltbotHandlers.__new__(MoltbotHandlers)
            msg = _make_message(text="hello")
            msg.reply_to_message = None
            result = await handler._build_reply_context(msg)
            assert result == ""

    @pytest.mark.asyncio
    async def test_reply_to_text_message(self):
        with patch.object(MoltbotHandlers, '__init__', lambda self, *a, **kw: None):
            handler = MoltbotHandlers.__new__(MoltbotHandlers)
            reply_msg = _make_message(text="синагогу достроил")
            msg = _make_message(text="@bot что скажешь?", reply_to=reply_msg)
            result = await handler._build_reply_context(msg)
            assert "Богдан" in result
            assert "синагогу достроил" in result
            assert "16:30 14.03" in result

    @pytest.mark.asyncio
    async def test_reply_to_bot_message_uses_first_name(self):
        with patch.object(MoltbotHandlers, '__init__', lambda self, *a, **kw: None):
            handler = MoltbotHandlers.__new__(MoltbotHandlers)
            reply_msg = _make_message(
                text="Нормально. Молодец.",
                from_user_id=8197808127, from_user_name="Jarvis", is_bot=True,
            )
            msg = _make_message(text="не согласен", reply_to=reply_msg)
            result = await handler._build_reply_context(msg)
            assert "Jarvis" in result
            assert "Нормально. Молодец." in result

    @pytest.mark.asyncio
    async def test_reply_to_sticker(self):
        with patch.object(MoltbotHandlers, '__init__', lambda self, *a, **kw: None):
            handler = MoltbotHandlers.__new__(MoltbotHandlers)
            handler._media = MagicMock()
            handler._media.fragment = AsyncMock(return_value="[Стикер 😂: кот ржёт до слёз]")
            reply_msg = _make_message(text=None, sticker_emoji="😂")
            msg = _make_message(text="@bot лол", reply_to=reply_msg)
            result = await handler._build_reply_context(msg)
            assert "[Стикер 😂: кот ржёт до слёз]" in result
            handler._media.fragment.assert_awaited_once_with(reply_msg)

    @pytest.mark.asyncio
    async def test_reply_from_none_user(self):
        with patch.object(MoltbotHandlers, '__init__', lambda self, *a, **kw: None):
            handler = MoltbotHandlers.__new__(MoltbotHandlers)
            reply_msg = _make_message(text="channel post", from_user_id=None)
            msg = _make_message(text="@bot what", reply_to=reply_msg)
            result = await handler._build_reply_context(msg)
            assert "Аноним" in result
            assert "channel post" in result

    @pytest.mark.asyncio
    async def test_sender_from_user_none(self):
        with patch.object(MoltbotHandlers, '__init__', lambda self, *a, **kw: None):
            handler = MoltbotHandlers.__new__(MoltbotHandlers)
            reply_msg = _make_message(text="some text")
            msg = _make_message(text="@bot what", from_user_id=None, reply_to=reply_msg)
            result = await handler._build_reply_context(msg)
            assert "Аноним" in result
            assert "some text" in result

    @pytest.mark.asyncio
    async def test_reply_to_voice(self):
        with patch.object(MoltbotHandlers, '__init__', lambda self, *a, **kw: None):
            handler = MoltbotHandlers.__new__(MoltbotHandlers)
            handler._media = MagicMock()
            handler._media.fragment = AsyncMock(return_value="[Голосовое (7 с), расшифровка: «го в доту»]")
            reply_msg = _make_message(text=None)
            reply_msg.voice = MagicMock()
            msg = _make_message(text="@bot что он сказал?", reply_to=reply_msg)
            result = await handler._build_reply_context(msg)
            assert "расшифровка: «го в доту»" in result

    @pytest.mark.asyncio
    async def test_reply_to_photo_uses_cached_media_description(self):
        with patch.object(MoltbotHandlers, '__init__', lambda self, *a, **kw: None):
            handler = MoltbotHandlers.__new__(MoltbotHandlers)
            handler._media = MagicMock()
            handler._media.fragment = AsyncMock(return_value="[Картинка: мем с котом]")

            reply_msg = _make_message(text=None, caption="ну вот")
            reply_msg.photo = [MagicMock()]
            msg = _make_message(text="@bot глянь", reply_to=reply_msg)

            result = await handler._build_reply_context(msg)

            assert "[Картинка: мем с котом]" in result
            assert "ну вот" in result
            handler._media.fragment.assert_awaited_once_with(reply_msg)


class TestEmptyTagGreeting:
    def test_empty_tag_no_reply_returns_greeting(self):
        result = MoltbotHandlers._should_greet(user_text="", reply_to=None)
        assert result == "Чё надо?"

    def test_empty_tag_with_reply_returns_none(self):
        reply_msg = _make_message(text="some text")
        result = MoltbotHandlers._should_greet(user_text="", reply_to=reply_msg)
        assert result is None

    def test_tag_with_text_returns_none(self):
        result = MoltbotHandlers._should_greet(user_text="что думаешь?", reply_to=None)
        assert result is None

    def test_whitespace_only_tag_returns_greeting(self):
        result = MoltbotHandlers._should_greet(user_text="  ", reply_to=None)
        assert result == "Чё надо?"


@pytest.mark.parametrize('prefix', ['[16:00 14.03] ', '[16:00] ', '16:00 ', ''])
def test_history_parser_preserves_bot_role_and_multiword_names(prefix):
    handler = MoltbotHandlers.__new__(MoltbotHandlers)
    bot_name = next(iter(handler._BOT_NAMES))
    messages = handler._history_to_messages(
        [f'{prefix}Сказочный Богдан: тест', f'{prefix}{bot_name}: ответ'], 'Юра', 'привет')
    assert messages == [
        {'role': 'user', 'content': 'Сказочный Богдан: тест'},
        {'role': 'assistant', 'content': 'ответ'},
        {'role': 'user', 'content': 'Юра: привет'},
    ]


@pytest.mark.parametrize('bot_name', ['Jarvis', 'Джарвис', 'MoltBot', 'Лолита'])
def test_history_parser_recognizes_historical_bot_names(bot_name):
    handler = MoltbotHandlers.__new__(MoltbotHandlers)
    messages = handler._history_to_messages(
        [f'[16:00 14.03] {bot_name}: ответ'], 'Юра', 'привет'
    )
    assert messages[0] == {'role': 'assistant', 'content': 'ответ'}
