import pytest
from unittest.mock import MagicMock, patch
from src.services.ollama_wake_manager import OllamaWakeManager, WakeState


class TestWakeManagerState:
    def setup_method(self):
        self.mgr = OllamaWakeManager.__new__(OllamaWakeManager)
        self.mgr._state = WakeState.ONLINE
        self.mgr._queue = []
        self.mgr._queue_lock = __import__('threading').Lock()
        self.mgr._last_ollama_request = 0.0

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

    def test_queue_request_when_waking(self):
        self.mgr._state = WakeState.WAKING
        mock_fn = MagicMock()
        self.mgr._enqueue("test prompt", 123, 456, mock_fn)
        assert len(self.mgr._queue) == 1
        assert self.mgr._queue[0].prompt == "test prompt"

    def test_drain_queue_calls_all_callbacks(self):
        results = []
        self.mgr._enqueue("prompt1", 1, 1, lambda r: results.append(r))
        self.mgr._enqueue("prompt2", 2, 2, lambda r: results.append(r))
        self.mgr._drain_queue(lambda p: f"reply:{p}")
        assert results == ["reply:prompt1", "reply:prompt2"]

    def test_drain_queue_clears_queue(self):
        self.mgr._enqueue("p", 1, 1, lambda r: None)
        self.mgr._drain_queue(lambda p: "x")
        assert len(self.mgr._queue) == 0
