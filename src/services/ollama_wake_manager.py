from __future__ import annotations
import asyncio
import subprocess
import threading
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
        self._queue_lock = asyncio.Lock()
        self._last_ollama_request: float = 0.0
        self._bot = None
        self._woke_by_bot: bool = False  # True only when bot sent WoL for Ollama
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._heartbeat_failures: int = 0
        self._initialized = True

    @property
    def state(self) -> WakeState:
        return self._state

    def _set_state(self, new_state: WakeState):
        old = self._state
        self._state = new_state
        logger.info(f"OllamaWakeManager: {old.value} → {new_state.value}")

    async def _enqueue(self, prompt: str, chat_id: int, message_id: int,
                 reply_fn: Callable[[str], None]):
        async with self._queue_lock:
            self._queue.append(WakeRequest(prompt, chat_id, message_id, reply_fn))

    async def _drain_queue(self, ollama_fn: Callable[[str], str]):
        async with self._queue_lock:
            requests = list(self._queue)
            self._queue.clear()
        for req in requests:
            try:
                result = await asyncio.to_thread(ollama_fn, req.prompt)
                req.reply_fn(result)
            except Exception as e:
                logger.error(f"OllamaWakeManager: drain error: {e}")

    async def _heartbeat_tick(self):
        """Called by async loop every 120s. Detects PC going to sleep.
        Requires 2 consecutive failures before going OFFLINE to avoid false triggers
        when Ollama is busy processing a request."""
        if self._state != WakeState.ONLINE:
            return
        try:
            from src.config.settings import Settings
            url = f"{Settings.LOCAL_LLM_URL}/api/tags"
            await asyncio.to_thread(lambda: httpx.get(url, timeout=30).raise_for_status())
            self._heartbeat_failures = 0
        except Exception:
            self._heartbeat_failures += 1
            if self._heartbeat_failures >= 5:
                self._heartbeat_failures = 0
                self._set_state(WakeState.OFFLINE)
                await self._notify_admin("😴 PC went to sleep (Ollama unreachable)")
            else:
                logger.info(f"OllamaWakeManager: heartbeat fail {self._heartbeat_failures}/3, retrying")

    async def _notify_admin(self, text: str):
        """Send DM to admin. No-op if bot or admin_id not configured."""
        try:
            from src.config.settings import Settings
            if self._bot and Settings.ADMIN_TELEGRAM_ID:
                await self._bot.send_message(Settings.ADMIN_TELEGRAM_ID, text)
        except Exception as e:
            logger.warning(f"OllamaWakeManager: admin notify failed: {e}")

    def _ssh_run(self, command: str, timeout: int = 10) -> str:
        """Run a command on Windows PC via SSH. Returns stdout."""
        from src.config.settings import Settings
        result = subprocess.run(
            ['ssh', '-i', Settings.PC_SSH_KEY,
             '-o', 'StrictHostKeyChecking=no',
             '-o', 'ConnectTimeout=8',
             f"{Settings.PC_SSH_USER}@{Settings.PC_SSH_HOST}",
             command],
            capture_output=True, text=True, timeout=timeout
        )
        if result.returncode != 0:
            raise RuntimeError(f"SSH command failed (exit {result.returncode}): {result.stderr.strip()}")
        return result.stdout.strip()

    def _get_windows_idle_seconds(self) -> float:
        """Returns seconds since last user input on Windows PC. Returns 0 on error (conservative)."""
        try:
            output = self._ssh_run('powershell -File C:\\idle_check.ps1')
            seconds = float(output.replace(',', '.'))
            # GetLastInputInfo tick counter wraps at ~49.7 days; cap at 2h to avoid false triggers
            return min(seconds, 7200.0)
        except Exception as e:
            logger.warning(f"OllamaWakeManager: idle check failed: {e}")
            return 0.0  # conservative: assume user is active

    def _send_sleep_command(self):
        """SSH to Windows PC and put it to sleep."""
        try:
            self._ssh_run('rundll32.exe powrprof.dll,SetSuspendState 0,1,0', timeout=5)
            logger.info("OllamaWakeManager: sleep command sent")
        except subprocess.TimeoutExpired:
            # PC went to sleep mid-SSH — connection killed before exit; this is expected
            logger.info("OllamaWakeManager: sleep command timed out (PC likely asleep — OK)")
        except Exception as e:
            logger.error(f"OllamaWakeManager: sleep command failed: {e}")
            # _notify_admin is async; schedule it as a fire-and-forget task
            try:
                asyncio.get_event_loop().create_task(
                    self._notify_admin(f"⚠️ Failed to put PC to sleep: {e}")
                )
            except RuntimeError:
                pass  # no event loop available at this point

    async def _sleep_check_tick(self):
        """Called every 5 min. Sleeps PC only if bot woke it and user has been idle 15+ min."""
        if self._state != WakeState.ONLINE or not self._woke_by_bot:
            return
        from src.config.settings import Settings
        threshold = Settings.OLLAMA_IDLE_SLEEP_MINUTES * 60
        user_idle = await asyncio.to_thread(self._get_windows_idle_seconds)
        if user_idle < threshold:
            return
        await self._notify_admin(
            f"😴 PC going to sleep (user idle {int(user_idle // 60)}m)"
        )
        await self.sleep_pc()

    async def _sleep_check_loop(self):
        while True:
            try:
                await asyncio.sleep(300)  # every 5 min
                await self._sleep_check_tick()
            except Exception as e:
                logger.error(f"OllamaWakeManager: sleep check loop error: {e}")

    def start(self, bot):
        """Start background asyncio tasks. Call once at bot startup."""
        self._bot = bot
        self._main_loop = asyncio.get_event_loop()
        asyncio.create_task(self._heartbeat_loop())
        asyncio.create_task(self._sleep_check_loop())
        logger.info("OllamaWakeManager: started heartbeat and sleep-check tasks")

    def trigger_wake(self):
        """Public: send WoL and transition to WAKING. No-op if already waking/online."""
        if self._state == WakeState.ONLINE:
            logger.info("OllamaWakeManager: trigger_wake called but already ONLINE")
            return
        self._trigger_wake()

    async def sleep_pc(self):
        """Public: SSH to Windows PC and put it to sleep."""
        await asyncio.to_thread(self._send_sleep_command)
        self._woke_by_bot = False
        self._set_state(WakeState.OFFLINE)

    async def _heartbeat_loop(self):
        while True:
            try:
                await asyncio.sleep(120)
                await self._heartbeat_tick()
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
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._poll_until_online())
        except RuntimeError:
            # Called from a worker thread (e.g. asyncio.to_thread)
            if self._main_loop is not None and self._main_loop.is_running():
                asyncio.run_coroutine_threadsafe(self._poll_until_online(), self._main_loop)
            else:
                logger.warning("OllamaWakeManager: WoL sent but polling skipped (no event loop)")

    async def _poll_until_online(self, timeout: float = 180.0, interval: float = 5.0):
        """Poll Ollama every interval seconds up to timeout. Drain queue when ready."""
        from src.config.settings import Settings
        self._main_loop = asyncio.get_event_loop()
        deadline = self._main_loop.time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            try:
                url = f"{Settings.LOCAL_LLM_URL}/api/tags"
                await asyncio.to_thread(lambda: httpx.get(url, timeout=5).raise_for_status())
                self._set_state(WakeState.ONLINE)
                await self._notify_admin("✅ PC is online (Ollama ready)")
                await self._drain_queue(self._call_ollama_raw)
                # Second drain catches requests that arrived during the WAKING→ONLINE transition
                await self._drain_queue(self._call_ollama_raw)
                return
            except Exception:
                await asyncio.sleep(interval)
        logger.warning("OllamaWakeManager: PC did not wake within timeout, using Claude fallback")
        await self._notify_admin("⚠️ PC did not wake (3 min timeout) — using Claude fallback")
        await self._drain_queue(self._call_claude_fallback)
        self._set_state(WakeState.OFFLINE)

    def _call_ollama_raw(self, prompt: str) -> str:
        """Direct Ollama call (no WoL logic)."""
        from src.config.settings import Settings
        r = httpx.post(
            f"{Settings.LOCAL_LLM_URL}/api/chat",
            json={"model": Settings.LOCAL_LLM_MODEL,
                  "think": False,
                  "stream": False,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=180,
        )
        r.raise_for_status()
        text = r.json()["message"]["content"]
        # Strip <think>...</think> blocks and Qwen artifacts
        import re
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
        text = text.split('<|endoftext|>')[0].split('<|im_start|>')[0].strip()
        return text

    async def call(self, prompt: str, bot, message,
             reply_fn: Callable[[str], None] | None = None) -> str | None:
        """
        Main entry point for all Ollama calls.

        If ONLINE: calls Ollama synchronously and returns the result string.
        If OFFLINE/WAKING: enqueues request, sends "waking up" message (OFFLINE only),
        returns None. reply_fn is called from background task when result is ready.
        If reply_fn is None, defaults to bot.send_message(chat_id, result).
        """
        self._last_ollama_request = asyncio.get_event_loop().time()

        if self._state == WakeState.ONLINE:
            try:
                return await asyncio.to_thread(self._call_ollama_raw, prompt)
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
            chat_id = message.chat.id
            msg_id = message.message_id

            def reply_fn(text: str):
                try:
                    asyncio.create_task(bot.send_message(chat_id, text, reply_to_message_id=msg_id))
                except Exception as ex:
                    logger.error(f"OllamaWakeManager: reply failed: {ex}")

        await self._enqueue(prompt, message.chat.id, message.message_id, reply_fn)

        if self._state == WakeState.OFFLINE:
            try:
                await bot.send_message(message.chat.id,
                    "⏳ Ollama is waking up… (~1–3 min). I'll reply when ready!")
            except Exception:
                pass
            self._woke_by_bot = True
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
