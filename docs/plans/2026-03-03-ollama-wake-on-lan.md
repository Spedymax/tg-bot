# Ollama Wake-on-LAN Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wake the Windows PC (192.168.1.3) via WoL when Ollama is needed, queue requests while booting, auto-reply when ready, and sleep the PC after 15 min combined bot+user idle.

**Architecture:** A singleton `OllamaWakeManager` wraps all Ollama calls. It maintains a state machine (ONLINE→OFFLINE→WAKING→ONLINE), sends WoL magic packets, queues pending requests in memory, and uses SSH to check Windows user idle time and trigger sleep. Admin Telegram DMs are sent on every state transition.

**Tech Stack:** Python 3.11, `wakeonlan` (pip), `subprocess ssh` (existing key at `~/.ssh/id_ed25519`), pyTelegramBotAPI, `httpx` (existing), `threading`

---

## Prerequisites: Windows WoL Setup

Run these steps **from the Linux server** before any code changes.

### Task 0: Enable WoL on Windows PC via SSH

**Step 1: Get Windows NIC name and MAC address**

```bash
ssh Spedy@192.168.1.3 'powershell -Command "Get-NetAdapter | Select-Object Name, MacAddress, Status"'
```

Note the adapter Name (e.g. `Ethernet`) and MAC address — you'll need it for `.env`.

**Step 2: Enable WoL on NIC power management**

```bash
ssh Spedy@192.168.1.3 'powershell -Command "
$adapter = Get-NetAdapter | Where-Object {$_.Status -eq \"Up\"} | Select-Object -First 1
$powerMgmt = Get-WmiObject MSPower_DeviceWakeEnable -Namespace root/wmi | Where-Object {$_.InstanceName -like \"*$($adapter.InterfaceDescription)*\"}
$powerMgmt.Enable = $true
$powerMgmt.Put()
Write-Output \"WoL enabled for: $($adapter.Name)\"
"'
```

**Step 3: Disable Fast Startup (required for WoL to work from sleep)**

```bash
ssh Spedy@192.168.1.3 'powershell -Command "powercfg /h off; Write-Output \"Fast startup disabled\""'
```

**Step 4: Verify WoL is armed**

```bash
ssh Spedy@192.168.1.3 'powershell -Command "powercfg /devicequery wake_armed"'
```

Expected: your NIC name appears in the output.

**Step 5: Test idle time check (used by sleep controller)**

```bash
ssh Spedy@192.168.1.3 'powershell -Command "
Add-Type @\"
using System; using System.Runtime.InteropServices;
public class Idle {
    [DllImport(\"user32.dll\")] public static extern bool GetLastInputInfo(ref LASTINPUTINFO p);
    public struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }
    public static double GetIdleSeconds() {
        var l = new LASTINPUTINFO(); l.cbSize = (uint)System.Runtime.InteropServices.Marshal.SizeOf(l);
        GetLastInputInfo(ref l); return (Environment.TickCount - l.dwTime) / 1000.0;
    }
}
\"@
[Idle]::GetIdleSeconds()
"'
```

Expected: a number (seconds since last mouse/keyboard input).

---

## Task 1: Add Dependency and Configuration

**Files:**
- Modify: `requirements.txt`
- Modify: `src/config/settings.py`

**Step 1: Add `wakeonlan` to requirements.txt**

Open `requirements.txt` and add:
```
wakeonlan==2.1.0
```

**Step 2: Add config fields to `settings.py`**

In the `Settings` class (after `LOCAL_LLM_MODEL` line ~68), add:

```python
# Wake-on-LAN / PC sleep control
PC_MAC_ADDRESS = os.getenv('PC_MAC_ADDRESS', '')          # e.g. "AA:BB:CC:DD:EE:FF"
PC_SSH_HOST = os.getenv('PC_SSH_HOST', '192.168.1.3')
PC_SSH_USER = os.getenv('PC_SSH_USER', 'Spedy')
PC_SSH_KEY = os.getenv('PC_SSH_KEY', os.path.expanduser('~/.ssh/id_ed25519'))
OLLAMA_IDLE_SLEEP_MINUTES = int(os.getenv('OLLAMA_IDLE_SLEEP_MINUTES', '15'))
ADMIN_TELEGRAM_ID = int(os.getenv('ADMIN_TELEGRAM_ID', '0'))
```

**Step 3: Add vars to `.env` on the Linux server**

SSH to server and add to `/home/spedymax/tg-bot/.env`:
```
PC_MAC_ADDRESS=<MAC from Task 0 Step 1>
ADMIN_TELEGRAM_ID=<your Telegram user ID>
```
(PC_SSH_HOST, PC_SSH_USER, PC_SSH_KEY use defaults and don't need to be set)

**Step 4: Install dependency on server**

```bash
ssh -i ~/.ssh/mac-max spedymax@192.168.1.35 'source /home/spedymax/venv/bin/activate && pip install wakeonlan==2.1.0'
```

**Step 5: Verify install**

```bash
ssh -i ~/.ssh/mac-max spedymax@192.168.1.35 'source /home/spedymax/venv/bin/activate && python -c "import wakeonlan; print(wakeonlan.__version__)"'
```

Expected: `2.1.0`

**Step 6: Commit**

```bash
git add requirements.txt src/config/settings.py
git commit -m "feat: add WoL config and wakeonlan dependency"
```

---

## Task 2: Create `OllamaWakeManager` — Core Structure & Tests

**Files:**
- Create: `src/services/ollama_wake_manager.py`
- Create: `tests/services/test_ollama_wake_manager.py`

**Step 1: Write failing tests for state machine**

Create `tests/services/test_ollama_wake_manager.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
from src.services.ollama_wake_manager import OllamaWakeManager, WakeState


class TestWakeManagerState:
    def setup_method(self):
        self.mgr = OllamaWakeManager.__new__(OllamaWakeManager)
        self.mgr._state = WakeState.ONLINE
        self.mgr._queue = []
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
        self.mgr._state = WakeState.WAKING
        results = []
        self.mgr._enqueue("prompt1", 1, 1, lambda r: results.append(r))
        self.mgr._enqueue("prompt2", 2, 2, lambda r: results.append(r))
        self.mgr._drain_queue(lambda p: f"reply:{p}")
        assert results == ["reply:prompt1", "reply:prompt2"]

    def test_drain_queue_clears_queue(self):
        self.mgr._enqueue("p", 1, 1, lambda r: None)
        self.mgr._drain_queue(lambda p: "x")
        assert len(self.mgr._queue) == 0
```

**Step 2: Run tests to verify they fail**

```bash
cd /Users/mso/PycharmProjects/tg-bot
python -m pytest tests/services/test_ollama_wake_manager.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'src.services.ollama_wake_manager'`

**Step 3: Create `src/services/ollama_wake_manager.py`**

```python
from __future__ import annotations
import threading
import time
import logging
from dataclasses import dataclass, field
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
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/services/test_ollama_wake_manager.py -v
```

Expected: all 7 tests PASS

**Step 5: Commit**

```bash
git add src/services/ollama_wake_manager.py tests/services/test_ollama_wake_manager.py
git commit -m "feat: add OllamaWakeManager core state machine"
```

---

## Task 3: Heartbeat Thread (Online → Offline Detection)

**Files:**
- Modify: `src/services/ollama_wake_manager.py`
- Modify: `tests/services/test_ollama_wake_manager.py`

**Step 1: Write failing test for heartbeat**

Add to `tests/services/test_ollama_wake_manager.py`:

```python
class TestHeartbeat:
    def test_heartbeat_transitions_to_offline_on_failure(self):
        mgr = OllamaWakeManager.__new__(OllamaWakeManager)
        mgr._init_state()
        mgr._state = WakeState.ONLINE
        mgr._bot = None
        notify_calls = []
        mgr._notify_admin = lambda msg: notify_calls.append(msg)

        with patch('src.services.ollama_wake_manager.httpx.get', side_effect=Exception("timeout")):
            mgr._heartbeat_tick()

        assert mgr.state == WakeState.OFFLINE
        assert any("sleep" in m.lower() or "went" in m.lower() for m in notify_calls)

    def test_heartbeat_stays_online_on_success(self):
        mgr = OllamaWakeManager.__new__(OllamaWakeManager)
        mgr._init_state()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        with patch('src.services.ollama_wake_manager.httpx.get', return_value=mock_resp):
            mgr._heartbeat_tick()

        assert mgr.state == WakeState.ONLINE
```

**Step 2: Run to verify failure**

```bash
python -m pytest tests/services/test_ollama_wake_manager.py::TestHeartbeat -v
```

Expected: FAIL — `_heartbeat_tick` not defined

**Step 3: Add heartbeat method to `OllamaWakeManager`**

Add these methods to the class:

```python
import httpx  # add to top of file

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
    if not self._initialized:
        self._init_state()
    self._bot = bot
    t = threading.Thread(target=self._heartbeat_loop, daemon=True, name="ollama-heartbeat")
    t.start()
    s = threading.Thread(target=self._sleep_check_loop, daemon=True, name="ollama-sleep-check")
    s.start()
    logger.info("OllamaWakeManager: started heartbeat and sleep-check threads")

def _heartbeat_loop(self):
    while True:
        time.sleep(30)
        self._heartbeat_tick()
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/services/test_ollama_wake_manager.py -v
```

Expected: all tests PASS

**Step 5: Commit**

```bash
git add src/services/ollama_wake_manager.py tests/services/test_ollama_wake_manager.py
git commit -m "feat: add OllamaWakeManager heartbeat (online→offline detection)"
```

---

## Task 4: Wake Flow (WoL + Queue Drain)

**Files:**
- Modify: `src/services/ollama_wake_manager.py`
- Modify: `tests/services/test_ollama_wake_manager.py`

**Step 1: Write failing tests for wake flow**

Add to test file:

```python
class TestWakeFlow:
    def setup_method(self):
        self.mgr = OllamaWakeManager.__new__(OllamaWakeManager)
        self.mgr._init_state()
        self.mgr._state = WakeState.OFFLINE
        self.mgr._bot = MagicMock()
        self.mgr._notify_admin = MagicMock()

    def test_wake_request_sends_wol_and_transitions_to_waking(self):
        with patch('src.services.ollama_wake_manager.wakeonlan.send_magic_packet') as mock_wol:
            with patch.object(self.mgr, '_poll_until_online', return_value=None):
                self.mgr._trigger_wake()
        mock_wol.assert_called_once()
        assert self.mgr.state == WakeState.WAKING

    def test_second_trigger_does_not_send_duplicate_wol(self):
        self.mgr._state = WakeState.WAKING
        with patch('src.services.ollama_wake_manager.wakeonlan.send_magic_packet') as mock_wol:
            self.mgr._trigger_wake()
        mock_wol.assert_not_called()

    def test_poll_until_online_succeeds_and_drains(self):
        results = []
        self.mgr._enqueue("hi", 1, 1, lambda r: results.append(r))
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        with patch('src.services.ollama_wake_manager.httpx.get', return_value=mock_resp):
            with patch.object(self.mgr, '_call_ollama_raw', return_value="hello"):
                self.mgr._poll_until_online()

        assert self.mgr.state == WakeState.ONLINE
        assert results == ["hello"]

    def test_poll_until_online_timeout_uses_claude_fallback(self):
        results = []
        self.mgr._enqueue("hi", 1, 1, lambda r: results.append(r))

        with patch('src.services.ollama_wake_manager.httpx.get', side_effect=Exception("timeout")):
            with patch.object(self.mgr, '_call_claude_fallback', return_value="claude reply"):
                self.mgr._poll_until_online(timeout=0.1, interval=0.05)

        assert results == ["claude reply"]
```

**Step 2: Run to verify failure**

```bash
python -m pytest tests/services/test_ollama_wake_manager.py::TestWakeFlow -v
```

Expected: FAIL

**Step 3: Add wake methods**

Add to `ollama_wake_manager.py`:

```python
import wakeonlan  # add to top of file

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
    # Poll in background thread
    t = threading.Thread(target=self._poll_until_online, daemon=True, name="ollama-poll")
    t.start()

def _poll_until_online(self, timeout: float = 180.0, interval: float = 5.0):
    """Poll Ollama every `interval` seconds up to `timeout`. Drain queue when ready."""
    from src.config.settings import Settings
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(f"{Settings.LOCAL_LLM_URL}/api/tags", timeout=5)
            r.raise_for_status()
            # Online!
            self._set_state(WakeState.ONLINE)
            self._notify_admin("✅ PC is online (Ollama ready)")
            self._drain_queue(self._call_ollama_raw)
            return
        except Exception:
            time.sleep(interval)
    # Timeout
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

def _call_claude_fallback(self, prompt: str) -> str:
    """Call OpenClaw/Claude as fallback when Ollama is unavailable."""
    from src.config.settings import Settings
    import httpx as _httpx
    try:
        r = _httpx.post(
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
```

**Step 4: Run all tests**

```bash
python -m pytest tests/services/test_ollama_wake_manager.py -v
```

Expected: all tests PASS

**Step 5: Commit**

```bash
git add src/services/ollama_wake_manager.py tests/services/test_ollama_wake_manager.py
git commit -m "feat: add OllamaWakeManager wake flow, WoL packet, queue drain, Claude fallback"
```

---

## Task 5: Public API — `call()` Method

**Files:**
- Modify: `src/services/ollama_wake_manager.py`
- Modify: `tests/services/test_ollama_wake_manager.py`

**Step 1: Write failing test for `call()`**

Add to test file:

```python
class TestCallMethod:
    def setup_method(self):
        self.mgr = OllamaWakeManager.__new__(OllamaWakeManager)
        self.mgr._init_state()
        self.mgr._bot = MagicMock()
        self.mgr._notify_admin = MagicMock()

    def test_call_when_online_returns_synchronously(self):
        self.mgr._state = WakeState.ONLINE
        with patch.object(self.mgr, '_call_ollama_raw', return_value="hello"):
            result = self.mgr.call("prompt", bot=None, message=None)
        assert result == "hello"

    def test_call_when_offline_sends_waking_message_and_returns_none(self):
        self.mgr._state = WakeState.OFFLINE
        bot = MagicMock()
        message = MagicMock()
        message.chat.id = 99
        message.message_id = 77

        with patch.object(self.mgr, '_trigger_wake'):
            result = self.mgr.call("prompt", bot=bot, message=message,
                                   reply_fn=lambda r: None)

        assert result is None
        bot.send_message.assert_called_once()
        assert "waking" in bot.send_message.call_args[0][1].lower() or \
               "⏳" in bot.send_message.call_args[0][1]
```

**Step 2: Run to verify failure**

```bash
python -m pytest tests/services/test_ollama_wake_manager.py::TestCallMethod -v
```

**Step 3: Add `call()` method**

```python
def call(self, prompt: str, bot, message,
         reply_fn: Callable[[str], None] | None = None) -> str | None:
    """
    Main entry point for callers.

    - If ONLINE: call Ollama synchronously, return result string.
    - If OFFLINE/WAKING: enqueue request, send "waking up" message, return None.
      `reply_fn(result)` is called from background thread when result is ready.
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
    if reply_fn is None:
        def reply_fn(text: str):
            try:
                bot.reply_to(message, text)
            except Exception as ex:
                logger.error(f"OllamaWakeManager: reply failed: {ex}")

    self._enqueue(prompt, message.chat.id, message.message_id, reply_fn)

    if self._state == WakeState.OFFLINE:
        # First request triggers wake
        try:
            bot.send_message(message.chat.id,
                "⏳ Ollama is waking up… (~1–3 min). I'll reply when ready!")
        except Exception:
            pass
        self._trigger_wake()

    return None
```

**Step 4: Run all tests**

```bash
python -m pytest tests/services/test_ollama_wake_manager.py -v
```

Expected: all tests PASS

**Step 5: Commit**

```bash
git add src/services/ollama_wake_manager.py tests/services/test_ollama_wake_manager.py
git commit -m "feat: add OllamaWakeManager.call() public API"
```

---

## Task 6: Sleep Controller (Idle-Based PC Sleep)

**Files:**
- Modify: `src/services/ollama_wake_manager.py`
- Modify: `tests/services/test_ollama_wake_manager.py`

**Step 1: Write failing test**

Add to test file:

```python
class TestSleepController:
    def setup_method(self):
        self.mgr = OllamaWakeManager.__new__(OllamaWakeManager)
        self.mgr._init_state()
        self.mgr._bot = MagicMock()
        self.mgr._notify_admin = MagicMock()
        self.mgr._last_ollama_request = 0.0  # very old

    def test_sleep_check_skips_when_not_online(self):
        self.mgr._state = WakeState.WAKING
        self.mgr._sleep_check_tick()  # should not raise or sleep PC

    def test_sleep_check_skips_when_bot_recently_active(self):
        self.mgr._state = WakeState.ONLINE
        self.mgr._last_ollama_request = time.time()  # just now
        with patch.object(self.mgr, '_get_windows_idle_seconds', return_value=9999):
            with patch.object(self.mgr, '_send_sleep_command') as mock_sleep:
                self.mgr._sleep_check_tick()
        mock_sleep.assert_not_called()

    def test_sleep_check_skips_when_user_active_on_pc(self):
        self.mgr._state = WakeState.ONLINE
        with patch.object(self.mgr, '_get_windows_idle_seconds', return_value=30):
            with patch.object(self.mgr, '_send_sleep_command') as mock_sleep:
                self.mgr._sleep_check_tick()
        mock_sleep.assert_not_called()

    def test_sleep_check_sleeps_when_both_idle(self):
        self.mgr._state = WakeState.ONLINE
        with patch.object(self.mgr, '_get_windows_idle_seconds', return_value=9999):
            with patch.object(self.mgr, '_send_sleep_command') as mock_sleep:
                self.mgr._sleep_check_tick()
        mock_sleep.assert_called_once()
```

**Step 2: Run to verify failure**

```bash
python -m pytest tests/services/test_ollama_wake_manager.py::TestSleepController -v
```

**Step 3: Add sleep controller methods**

```python
import subprocess  # add to top of file

POWERSHELL_IDLE = (
    'Add-Type @"\\n'
    'using System; using System.Runtime.InteropServices;\\n'
    'public class Idle {\\n'
    '    [DllImport(\\"user32.dll\\")] public static extern bool GetLastInputInfo(ref LASTINPUTINFO p);\\n'
    '    public struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }\\n'
    '    public static double GetIdleSeconds() {\\n'
    '        var l = new LASTINPUTINFO(); l.cbSize = (uint)System.Runtime.InteropServices.Marshal.SizeOf(l);\\n'
    '        GetLastInputInfo(ref l); return (Environment.TickCount - l.dwTime) / 1000.0;\\n'
    '    }\\n'
    '}\\n'
    '"@\\n'
    '[Idle]::GetIdleSeconds()'
)

def _ssh_run(self, command: str, timeout: int = 10) -> str:
    """Run a command on Windows PC via SSH. Returns stdout."""
    from src.config.settings import Settings
    result = subprocess.run(
        ['ssh', '-i', Settings.PC_SSH_KEY, '-o', 'StrictHostKeyChecking=no',
         '-o', 'ConnectTimeout=8',
         f"{Settings.PC_SSH_USER}@{Settings.PC_SSH_HOST}", command],
        capture_output=True, text=True, timeout=timeout
    )
    return result.stdout.strip()

def _get_windows_idle_seconds(self) -> float:
    """Returns seconds since last user input on Windows PC. Returns 0 on error (conservative)."""
    try:
        output = self._ssh_run(f'powershell -Command "{POWERSHELL_IDLE}"')
        return float(output)
    except Exception as e:
        logger.warning(f"OllamaWakeManager: idle check failed: {e}")
        return 0.0  # conservative: assume user is active

def _send_sleep_command(self):
    """SSH to Windows PC and put it to sleep."""
    try:
        self._ssh_run('rundll32.exe powrprof.dll,SetSuspendState 0,1,0', timeout=5)
        logger.info("OllamaWakeManager: sleep command sent")
    except Exception as e:
        logger.error(f"OllamaWakeManager: sleep command failed: {e}")
        self._notify_admin(f"⚠️ Failed to put PC to sleep: {e}")

def _sleep_check_tick(self):
    """Called every 5 min. Sleeps PC if both bot and user have been idle 15+ min."""
    if self._state != WakeState.ONLINE:
        return
    from src.config.settings import Settings
    threshold = Settings.OLLAMA_IDLE_SLEEP_MINUTES * 60
    bot_idle = time.time() - self._last_ollama_request
    if bot_idle < threshold:
        return
    user_idle = self._get_windows_idle_seconds()
    if user_idle < threshold:
        return
    self._notify_admin(
        f"😴 PC going to sleep (bot idle {int(bot_idle//60)}m, user idle {int(user_idle//60)}m)"
    )
    self._send_sleep_command()
    self._set_state(WakeState.OFFLINE)

def _sleep_check_loop(self):
    while True:
        time.sleep(300)  # every 5 min
        self._sleep_check_tick()
```

**Step 4: Run all tests**

```bash
python -m pytest tests/services/test_ollama_wake_manager.py -v
```

Expected: all tests PASS

**Step 5: Commit**

```bash
git add src/services/ollama_wake_manager.py tests/services/test_ollama_wake_manager.py
git commit -m "feat: add OllamaWakeManager idle-based sleep controller"
```

---

## Task 7: Integrate into `moltbot_handlers.py`

**Files:**
- Modify: `src/handlers/moltbot_handlers.py`
- Modify: `src/main.py`

**Step 1: Read current `_call_ollama_direct` usage in `moltbot_handlers.py`**

Look at every call to `self._call_ollama_direct(...)`. Each is a fire-and-return pattern inside a handler. We'll add an `async_reply` parameter — if a message context is available, use the new manager; otherwise keep the old path.

**Step 2: Add import and manager access**

At the top of `moltbot_handlers.py`, add after existing imports:

```python
from src.services.ollama_wake_manager import OllamaWakeManager
```

**Step 3: Replace `_call_ollama_direct` with manager-aware version**

Replace the existing `_call_ollama_direct` method body:

```python
def _call_ollama_direct(self, content: str, bot=None, message=None) -> str:
    """Call Ollama. If bot+message provided and PC is waking, queues for async reply."""
    manager = OllamaWakeManager()
    if bot is not None and message is not None:
        result = manager.call(content, bot=bot, message=message)
        return result if result is not None else ""
    # Synchronous path (no message context — internal use)
    try:
        return manager._call_ollama_raw(content)
    except Exception as e:
        logger.error(f"MoltBot: Ollama direct call failed: {e}")
        return ""
```

**Step 4: Update call sites that have `message` context**

Search for `self._call_ollama_direct(` in `moltbot_handlers.py`. For calls inside handler methods that have access to `message` (the Telegram message object), update to pass it:

```python
# Before:
result = self._call_ollama_direct(prompt)

# After (in handlers with `message` parameter):
result = self._call_ollama_direct(prompt, bot=bot, message=message)
```

Note: calls used for internal summarization / background tasks (no user message context) keep the old signature.

**Step 5: Start manager in `main.py`**

Find where the bot is initialized in `src/main.py`. After `bot = telebot.TeleBot(...)`, add:

```python
from src.services.ollama_wake_manager import OllamaWakeManager
wake_manager = OllamaWakeManager()
wake_manager.start(bot)
logger.info("OllamaWakeManager started")
```

**Step 6: Smoke test locally**

```bash
# Start the bot locally (or on server) and trigger an Ollama-dependent command
# Check logs for "OllamaWakeManager: started heartbeat and sleep-check threads"
```

**Step 7: Commit**

```bash
git add src/handlers/moltbot_handlers.py src/main.py
git commit -m "feat: integrate OllamaWakeManager into moltbot_handlers and main"
```

---

## Task 8: Deploy to Server

**Step 1: Push to remote**

```bash
git push origin main
```

**Step 2: Pull and restart on server**

```bash
ssh -i ~/.ssh/mac-max spedymax@192.168.1.35 '
  cd /home/spedymax/tg-bot &&
  git pull &&
  source /home/spedymax/venv/bin/activate &&
  pip install wakeonlan==2.1.0 &&
  echo "123" | sudo -S systemctl restart bot-manager.service
'
```

**Step 3: Verify service started cleanly**

```bash
ssh -i ~/.ssh/mac-max spedymax@192.168.1.35 'echo "123" | sudo -S journalctl -u bot-manager.service -n 30 --no-pager'
```

Expected: `OllamaWakeManager started` and `started heartbeat and sleep-check threads` in logs.

**Step 4: Test WoL end-to-end**

1. Manually sleep the Windows PC
2. Send a message to the bot that triggers Ollama (e.g. react to something)
3. Verify: "⏳ Ollama is waking up" message appears in Telegram
4. Verify: PC wakes up within ~60s
5. Verify: bot auto-replies with the result
6. Check admin DM for "✅ PC is online" notification

**Step 5: Test idle sleep**

1. Leave the PC and bot idle for 16+ minutes
2. Verify admin DM: "😴 PC going to sleep"
3. Verify PC actually sleeps

---

## Summary of New Files

| File | Purpose |
|------|---------|
| `src/services/ollama_wake_manager.py` | Singleton manager: state machine, WoL, queue, heartbeat, sleep |
| `tests/services/test_ollama_wake_manager.py` | Unit tests for all manager behavior |

## Environment Variables to Add to `.env`

```
PC_MAC_ADDRESS=XX:XX:XX:XX:XX:XX
ADMIN_TELEGRAM_ID=<your Telegram user ID>
```
