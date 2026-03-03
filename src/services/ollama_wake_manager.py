from __future__ import annotations
import threading
import time
import logging
import httpx
import wakeonlan
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

    def __init__(self):
        if not getattr(self, '_initialized', False):
            self._init_state()

    def _init_state(self):
        self._state = WakeState.ONLINE
        self._queue: list[WakeRequest] = []
        self._queue_lock = threading.Lock()
        self._last_ollama_request: float = 0.0
        self._bot = None
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

    def _heartbeat_tick(self):
        """Called by background thread every 30s. Detects PC going to sleep."""
        if self._state != WakeState.ONLINE:
            return
        try:
            from src.config.settings import Settings
            r = httpx.get(f"{Settings.LOCAL_LLM_URL}/api/tags", timeout=5)
            r.raise_for_status()
        except Exception:
            self._set_state(WakeState.OFFLINE)
            self._notify_admin("😴 PC went to sleep (Ollama unreachable)")

    def _notify_admin(self, text: str):
        """Send DM to admin. No-op if bot or admin_id not configured."""
        try:
            from src.config.settings import Settings
            if self._bot and Settings.ADMIN_TELEGRAM_ID:
                self._bot.send_message(Settings.ADMIN_TELEGRAM_ID, text)
        except Exception as e:
            logger.warning(f"OllamaWakeManager: admin notify failed: {e}")

    def start(self, bot):
        """Start background threads. Call once at bot startup."""
        self._bot = bot
        t = threading.Thread(target=self._heartbeat_loop, daemon=True, name="ollama-heartbeat")
        t.start()
        logger.info("OllamaWakeManager: started heartbeat thread")

    def _heartbeat_loop(self):
        while True:
            try:
                time.sleep(30)
                self._heartbeat_tick()
            except Exception as e:
                logger.error(f"OllamaWakeManager: heartbeat loop error: {e}")

    def _trigger_wake(self):
        """Send WoL packet and start polling. No-op if already waking."""
        if self._state == WakeState.WAKING:
            return
        self._set_state(WakeState.WAKING)
        try:
            from src.config.settings import Settings
            if Settings.PC_MAC_ADDRESS:
                wakeonlan.send_magic_packet(Settings.PC_MAC_ADDRESS)
                logger.info(f"OllamaWakeManager: WoL packet sent to {Settings.PC_MAC_ADDRESS}")
            else:
                logger.warning("OllamaWakeManager: PC_MAC_ADDRESS not set, skipping WoL")
        except Exception as e:
            logger.error(f"OllamaWakeManager: WoL send failed: {e}")
        t = threading.Thread(target=self._poll_until_online, daemon=True, name="ollama-poll")
        t.start()

    def _poll_until_online(self, timeout: float = 180.0, interval: float = 5.0):
        """Poll Ollama every interval seconds up to timeout. Drain queue when ready."""
        from src.config.settings import Settings
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                r = httpx.get(f"{Settings.LOCAL_LLM_URL}/api/tags", timeout=5)
                r.raise_for_status()
                self._set_state(WakeState.ONLINE)
                self._notify_admin("✅ PC is online (Ollama ready)")
                self._drain_queue(self._call_ollama_raw)
                # Second drain catches requests that arrived during the WAKING→ONLINE transition
                self._drain_queue(self._call_ollama_raw)
                return
            except Exception:
                time.sleep(interval)
        logger.warning("OllamaWakeManager: PC did not wake within timeout, using Claude fallback")
        self._notify_admin("⚠️ PC did not wake (3 min timeout) — using Claude fallback")
        self._drain_queue(self._call_claude_fallback)
        self._set_state(WakeState.OFFLINE)

    def _call_ollama_raw(self, prompt: str) -> str:
        """Direct Ollama call (no WoL logic)."""
        from src.config.settings import Settings
        r = httpx.post(
            f"{Settings.LOCAL_LLM_URL}/v1/chat/completions",
            json={"model": Settings.LOCAL_LLM_MODEL,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    def call(self, prompt: str, bot, message,
             reply_fn: Callable[[str], None] | None = None) -> str | None:
        """
        Main entry point for all Ollama calls.

        If ONLINE: calls Ollama synchronously and returns the result string.
        If OFFLINE/WAKING: enqueues request, sends "waking up" message (OFFLINE only),
        returns None. reply_fn is called from background thread when result is ready.
        If reply_fn is None, defaults to bot.reply_to(message, result).
        """
        self._last_ollama_request = time.time()

        if self._state == WakeState.ONLINE:
            try:
                return self._call_ollama_raw(prompt)
            except Exception as e:
                logger.warning(f"OllamaWakeManager: online call failed: {e}")
                self._set_state(WakeState.OFFLINE)
                # Fall through to wake flow

        # OFFLINE or WAKING — queue it
        # Cannot queue without message context
        if message is None or bot is None:
            logger.warning("OllamaWakeManager: call() invoked without message context in OFFLINE/WAKING state")
            return None

        if reply_fn is None:
            def reply_fn(text: str):
                try:
                    bot.reply_to(message, text)
                except Exception as ex:
                    logger.error(f"OllamaWakeManager: reply failed: {ex}")

        self._enqueue(prompt, message.chat.id, message.message_id, reply_fn)

        if self._state == WakeState.OFFLINE:
            try:
                bot.send_message(message.chat.id,
                    "⏳ Ollama is waking up… (~1–3 min). I'll reply when ready!")
            except Exception:
                pass
            self._trigger_wake()

        return None

    def _call_claude_fallback(self, prompt: str) -> str:
        """Call OpenClaw/Claude as fallback when Ollama is unavailable."""
        from src.config.settings import Settings
        if not Settings.JARVIS_TOKEN:
            logger.error("OllamaWakeManager: JARVIS_TOKEN not configured, cannot use Claude fallback")
            return ""
        try:
            r = httpx.post(
                Settings.JARVIS_URL,
                headers={"Authorization": f"Bearer {Settings.JARVIS_TOKEN}"},
                json={"model": "openclaw:main",
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=30,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"OllamaWakeManager: Claude fallback also failed: {e}")
            return ""
