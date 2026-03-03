from __future__ import annotations
import threading
import time
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class WakeState(Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    WAKING = "waking"


@dataclass
class WakeRequest:
    prompt: str
    chat_id: int
    message_id: int
    reply_fn: Callable[[str], None]


class OllamaWakeManager:
    _instance: Optional["OllamaWakeManager"] = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def _init_state(self):
        self._state = WakeState.ONLINE
        self._queue: list[WakeRequest] = []
        self._queue_lock = threading.Lock()
        self._last_ollama_request: float = 0.0
        self._initialized = True

    @property
    def state(self) -> WakeState:
        return self._state

    def _set_state(self, new_state: WakeState):
        old = self._state
        self._state = new_state
        logger.info(f"OllamaWakeManager: {old.value} → {new_state.value}")

    def _enqueue(self, prompt: str, chat_id: int, message_id: int,
                 reply_fn: Callable[[str], None]):
        with self._queue_lock:
            self._queue.append(WakeRequest(prompt, chat_id, message_id, reply_fn))

    def _drain_queue(self, ollama_fn: Callable[[str], str]):
        with self._queue_lock:
            requests = list(self._queue)
            self._queue.clear()
        for req in requests:
            try:
                result = ollama_fn(req.prompt)
                req.reply_fn(result)
            except Exception as e:
                logger.error(f"OllamaWakeManager: drain error: {e}")
