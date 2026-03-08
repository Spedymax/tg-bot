import asyncio
import pytest
import time
from unittest.mock import MagicMock, patch, AsyncMock
from src.services.ollama_wake_manager import OllamaWakeManager, WakeState


class TestWakeManagerState:
    def setup_method(self):
        self.mgr = OllamaWakeManager.__new__(OllamaWakeManager)
        self.mgr._state = WakeState.ONLINE
        self.mgr._queue = []
        self.mgr._queue_lock = asyncio.Lock()
        self.mgr._last_ollama_request = 0.0

    def teardown_method(self):
        OllamaWakeManager._instance = None

    def test_initial_state_is_online(self):
        mgr = OllamaWakeManager.__new__(OllamaWakeManager)
        mgr._init_state()
        assert mgr.state == WakeState.ONLINE

    def test_transition_online_to_offline(self):
        self.mgr._set_state(WakeState.OFFLINE)
        assert self.mgr.state == WakeState.OFFLINE

    def test_transition_offline_to_waking(self):
        self.mgr._state = WakeState.OFFLINE
        self.mgr._set_state(WakeState.WAKING)
        assert self.mgr.state == WakeState.WAKING

    def test_transition_waking_to_online(self):
        self.mgr._state = WakeState.WAKING
        self.mgr._set_state(WakeState.ONLINE)
        assert self.mgr.state == WakeState.ONLINE

    @pytest.mark.asyncio
    async def test_queue_request_when_waking(self):
        self.mgr._state = WakeState.WAKING
        mock_fn = MagicMock()
        await self.mgr._enqueue("test prompt", 123, 456, mock_fn)
        assert len(self.mgr._queue) == 1
        assert self.mgr._queue[0].prompt == "test prompt"

    @pytest.mark.asyncio
    async def test_drain_queue_calls_all_callbacks(self):
        results = []
        await self.mgr._enqueue("prompt1", 1, 1, lambda r: results.append(r))
        await self.mgr._enqueue("prompt2", 2, 2, lambda r: results.append(r))
        await self.mgr._drain_queue(lambda p: f"reply:{p}")
        assert results == ["reply:prompt1", "reply:prompt2"]

    @pytest.mark.asyncio
    async def test_drain_queue_clears_queue(self):
        await self.mgr._enqueue("p", 1, 1, lambda r: None)
        await self.mgr._drain_queue(lambda p: "x")
        assert len(self.mgr._queue) == 0


class TestHeartbeat:
    def setup_method(self):
        OllamaWakeManager._instance = None

    def teardown_method(self):
        OllamaWakeManager._instance = None

    @pytest.mark.asyncio
    async def test_heartbeat_transitions_to_offline_on_failure(self):
        mgr = OllamaWakeManager.__new__(OllamaWakeManager)
        mgr._init_state()
        mgr._state = WakeState.ONLINE
        mgr._bot = None
        notify_calls = []
        mgr._notify_admin = AsyncMock(side_effect=lambda msg: notify_calls.append(msg))

        with patch('src.services.ollama_wake_manager.httpx.get', side_effect=Exception("timeout")):
            await mgr._heartbeat_tick()

        assert mgr.state == WakeState.OFFLINE
        assert any("sleep" in m.lower() or "went" in m.lower() for m in notify_calls)

    @pytest.mark.asyncio
    async def test_heartbeat_stays_online_on_success(self):
        mgr = OllamaWakeManager.__new__(OllamaWakeManager)
        mgr._init_state()
        mgr._bot = None
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        with patch('src.services.ollama_wake_manager.httpx.get', return_value=mock_resp):
            await mgr._heartbeat_tick()

        assert mgr.state == WakeState.ONLINE


class TestWakeFlow:
    def setup_method(self):
        OllamaWakeManager._instance = None

    def teardown_method(self):
        OllamaWakeManager._instance = None

    def _make_mgr(self):
        mgr = OllamaWakeManager.__new__(OllamaWakeManager)
        mgr._init_state()
        mgr._state = WakeState.OFFLINE
        mgr._notify_admin = AsyncMock()
        return mgr

    def test_trigger_wake_sends_wol_and_transitions_to_waking(self):
        mgr = self._make_mgr()
        with patch('src.services.ollama_wake_manager.wakeonlan.send_magic_packet') as mock_wol:
            with patch.object(mgr, '_poll_until_online'):
                with patch('src.config.settings.Settings.PC_MAC_ADDRESS', new="AA:BB:CC:DD:EE:FF"):
                    mgr._trigger_wake()
        mock_wol.assert_called_once()
        assert mgr.state == WakeState.WAKING

    def test_second_trigger_does_not_send_duplicate_wol(self):
        mgr = self._make_mgr()
        mgr._state = WakeState.WAKING
        with patch('src.services.ollama_wake_manager.wakeonlan.send_magic_packet') as mock_wol:
            mgr._trigger_wake()
        mock_wol.assert_not_called()

    @pytest.mark.asyncio
    async def test_poll_until_online_succeeds_and_drains(self):
        mgr = self._make_mgr()
        results = []
        await mgr._enqueue("hi", 1, 1, lambda r: results.append(r))
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        with patch('src.services.ollama_wake_manager.httpx.get', return_value=mock_resp):
            with patch.object(mgr, '_call_ollama_raw', return_value="hello"):
                await mgr._poll_until_online()

        assert mgr.state == WakeState.ONLINE
        assert results == ["hello"]

    @pytest.mark.asyncio
    async def test_poll_until_online_timeout_uses_claude_fallback(self):
        mgr = self._make_mgr()
        results = []
        await mgr._enqueue("hi", 1, 1, lambda r: results.append(r))

        with patch('src.services.ollama_wake_manager.httpx.get', side_effect=Exception("timeout")):
            with patch.object(mgr, '_call_claude_fallback', return_value="claude reply"):
                await mgr._poll_until_online(timeout=0.1, interval=0.05)

        assert results == ["claude reply"]


class TestCallMethod:
    def setup_method(self):
        OllamaWakeManager._instance = None

    def teardown_method(self):
        OllamaWakeManager._instance = None

    def _make_mgr(self):
        mgr = OllamaWakeManager.__new__(OllamaWakeManager)
        mgr._init_state()
        mgr._notify_admin = AsyncMock()
        return mgr

    @pytest.mark.asyncio
    async def test_call_when_online_returns_synchronously(self):
        mgr = self._make_mgr()
        mgr._state = WakeState.ONLINE
        with patch.object(mgr, '_call_ollama_raw', return_value="hello"):
            result = await mgr.call("prompt", bot=None, message=None)
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_call_when_offline_sends_waking_message_and_returns_none(self):
        mgr = self._make_mgr()
        mgr._state = WakeState.OFFLINE
        bot = AsyncMock()
        message = MagicMock()
        message.chat.id = 99
        message.message_id = 77

        with patch.object(mgr, '_trigger_wake'):
            result = await mgr.call("prompt", bot=bot, message=message,
                              reply_fn=lambda r: None)

        assert result is None
        bot.send_message.assert_called_once()
        sent_text = bot.send_message.call_args[0][1]
        assert "⏳" in sent_text or "waking" in sent_text.lower()

    @pytest.mark.asyncio
    async def test_call_when_waking_queues_without_sending_message(self):
        mgr = self._make_mgr()
        mgr._state = WakeState.WAKING
        bot = AsyncMock()
        message = MagicMock()
        message.chat.id = 99
        message.message_id = 77

        result = await mgr.call("prompt", bot=bot, message=message,
                          reply_fn=lambda r: None)

        assert result is None
        bot.send_message.assert_not_called()
        assert len(mgr._queue) == 1

    @pytest.mark.asyncio
    async def test_call_online_failure_triggers_wake_flow(self):
        mgr = self._make_mgr()
        mgr._state = WakeState.ONLINE
        bot = AsyncMock()
        message = MagicMock()
        message.chat.id = 99
        message.message_id = 77

        with patch.object(mgr, '_call_ollama_raw', side_effect=Exception("conn refused")):
            with patch.object(mgr, '_trigger_wake'):
                result = await mgr.call("prompt", bot=bot, message=message,
                                  reply_fn=lambda r: None)

        assert result is None
        assert mgr.state == WakeState.OFFLINE

    @pytest.mark.asyncio
    async def test_call_offline_with_no_message_returns_none_gracefully(self):
        mgr = self._make_mgr()
        mgr._state = WakeState.OFFLINE
        result = await mgr.call("prompt", bot=None, message=None)
        assert result is None
        assert len(mgr._queue) == 0


class TestSleepController:
    def setup_method(self):
        OllamaWakeManager._instance = None

    def teardown_method(self):
        OllamaWakeManager._instance = None

    def _make_mgr(self):
        mgr = OllamaWakeManager.__new__(OllamaWakeManager)
        mgr._init_state()
        mgr._bot = MagicMock()
        mgr._notify_admin = AsyncMock()
        mgr._last_ollama_request = 0.0  # very old
        return mgr

    @pytest.mark.asyncio
    async def test_sleep_check_skips_when_not_online(self):
        mgr = self._make_mgr()
        mgr._state = WakeState.WAKING
        with patch.object(mgr, '_send_sleep_command') as mock_sleep:
            await mgr._sleep_check_tick()
        mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_sleep_check_skips_when_bot_recently_active(self):
        mgr = self._make_mgr()
        mgr._state = WakeState.ONLINE
        mgr._last_ollama_request = time.time()  # just now
        with patch.object(mgr, '_get_windows_idle_seconds', return_value=9999):
            with patch.object(mgr, '_send_sleep_command') as mock_sleep:
                await mgr._sleep_check_tick()
        mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_sleep_check_skips_when_user_active_on_pc(self):
        mgr = self._make_mgr()
        mgr._state = WakeState.ONLINE
        with patch.object(mgr, '_get_windows_idle_seconds', return_value=30):
            with patch.object(mgr, '_send_sleep_command') as mock_sleep:
                await mgr._sleep_check_tick()
        mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_sleep_check_sleeps_when_both_idle(self):
        mgr = self._make_mgr()
        mgr._state = WakeState.ONLINE
        mgr._woke_by_bot = True
        with patch.object(mgr, '_get_windows_idle_seconds', return_value=9999):
            with patch.object(mgr, 'sleep_pc', new_callable=AsyncMock) as mock_sleep:
                await mgr._sleep_check_tick()
        mock_sleep.assert_called_once()
