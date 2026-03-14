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

            result = await handler._get_recent_group_messages(limit=50)

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

            result = await handler._get_recent_group_messages(limit=50)

        assert len(result) == 1
        assert "Юра: old msg" in result[0]


class TestAskMoltbotContext:
    @pytest.mark.asyncio
    async def test_history_block_includes_time_header_and_instruction(self):
        with patch.object(MoltbotHandlers, '__init__', lambda self, *a, **kw: None):
            handler = MoltbotHandlers.__new__(MoltbotHandlers)
            handler._user_key_suffix = {}

            captured = {}
            async def capture_openclaw(content, user_key, model="openclaw:main"):
                captured['content'] = content
                return "test reply"
            handler._call_openclaw = capture_openclaw

            with patch.object(_moltbot_mod, '_load_chat_summary', return_value=''):
                await handler._ask_moltbot(
                    "Юра", "привет", "групповой чат", "key",
                    history=["[16:00 14.03] Богдан: тест"]
                )

            content = captured['content']
            assert "[Сейчас:" in content
            assert "Copenhagen]" in content
            assert "фоновый контекст" in content
            assert "Не поднимай старые темы" in content


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
            reply_msg = _make_message(text=None, sticker_emoji="😂")
            msg = _make_message(text="@bot лол", reply_to=reply_msg)
            result = await handler._build_reply_context(msg)
            assert "Стикер: 😂" in result

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
            reply_msg = _make_message(text=None)
            reply_msg.voice = MagicMock()
            msg = _make_message(text="@bot что он сказал?", reply_to=reply_msg)
            result = await handler._build_reply_context(msg)
            assert "Голосовое сообщение" in result

    @pytest.mark.asyncio
    async def test_reply_to_photo_calls_gemini(self):
        with patch.object(MoltbotHandlers, '__init__', lambda self, *a, **kw: None):
            handler = MoltbotHandlers.__new__(MoltbotHandlers)
            handler.bot = AsyncMock()
            handler._gemini_model = MagicMock()

            file_mock = MagicMock()
            file_mock.file_path = "photos/file.jpg"
            handler.bot.get_file = AsyncMock(return_value=file_mock)
            bio = MagicMock()
            bio.read.return_value = b"fake_image_bytes"
            handler.bot.download_file = AsyncMock(return_value=bio)

            reply_msg = _make_message(text=None, caption="ну вот")
            reply_msg.photo = [MagicMock()]
            reply_msg.photo[-1].file_id = "abc123"

            msg = _make_message(text="@bot глянь", reply_to=reply_msg)

            with patch.object(handler, '_analyze_image_with_gemini', return_value="мем с котом"):
                result = await handler._build_reply_context(msg)

            assert "мем с котом" in result
            assert "ну вот" in result


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
