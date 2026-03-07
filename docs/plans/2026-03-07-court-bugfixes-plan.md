# Court Game Bug Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 6 bugs in the court game that cause game hangs, race conditions, and broken verdict display.

**Architecture:** Changes spread across `court_service.py` (LLM retry/fallback logic, verdict format) and `court_handlers.py` (per-game locking, phase guard, UX messages). No DB changes.

**Tech Stack:** Python, threading.Lock, pyTelegramBotAPI, Gemini via google.generativeai

---

### Task 1: Bug 1+2 — LLM failure / missing tag in judge_react()

**Files:**
- Modify: `src/services/court_service.py:346-384`

**Step 1: Locate judge_react() in court_service.py**

It starts at line 346. The relevant section is the `raw = self._call_judge_llm(prompt)` call and the `parse_judge_signal` call after it.

**Step 2: Replace the end of judge_react() with retry + fallback logic**

Find the block starting at line 380:
```python
        raw = self._call_judge_llm(prompt)
        clean, signal = self.parse_judge_signal(raw)
        self.log_message(game_id, "judge", clean, round_num)
        return clean, signal
```

Replace with:
```python
        raw = self._call_judge_llm(prompt)
        clean, signal = self.parse_judge_signal(raw)

        # Retry once if LLM returned empty or no signal tag
        if not raw or signal is None:
            logger.warning(f"[COURT] judge_react: no signal (empty={not raw}), retrying")
            raw = self._call_judge_llm(prompt)
            clean, signal = self.parse_judge_signal(raw)

        # Fallback if still no signal
        if not raw or signal is None:
            logger.error(f"[COURT] judge_react: fallback after 2 failed LLM calls")
            clean = "Суд принял к сведению. Продолжаем заседание."
            if role == "prosecutor":
                signal = "ЗАЩИТА_ВАШ_ХОД"
            elif is_last_round:
                signal = "ФИНАЛ"
            else:
                signal = "ПРОКУРОР_ВАШ_ХОД"

        self.log_message(game_id, "judge", clean, round_num)
        return clean, signal
```

**Step 3: Apply same fix to judge_react_to_reply()**

Find the block at lines 400-406:
```python
        raw = self._call_judge_llm(prompt)
        clean, signal = self.parse_judge_signal(raw)
        self.log_message(game_id, role, reply_text, round_num)
        self.log_message(game_id, "judge", clean, round_num)
        return clean, signal
```

Replace with:
```python
        raw = self._call_judge_llm(prompt)
        clean, signal = self.parse_judge_signal(raw)

        if not raw or signal is None:
            logger.warning(f"[COURT] judge_react_to_reply: no signal, retrying")
            raw = self._call_judge_llm(prompt)
            clean, signal = self.parse_judge_signal(raw)

        if not raw or signal is None:
            logger.error(f"[COURT] judge_react_to_reply: fallback after 2 failed LLM calls")
            clean = "Суд принял к сведению. Продолжаем заседание."
            game = self.get_active_game_by_id(game_id)
            is_last = game and game.get('current_round', 0) >= 4
            if role == "prosecutor":
                signal = "ЗАЩИТА_ВАШ_ХОД"
            elif is_last:
                signal = "ФИНАЛ"
            else:
                signal = "ПРОКУРОР_ВАШ_ХОД"

        self.log_message(game_id, role, reply_text, round_num)
        self.log_message(game_id, "judge", clean, round_num)
        return clean, signal
```

**Step 4: Verify the file looks correct**

Check that `is_last_round` variable is in scope in judge_react (it's defined at line ~371).

**Step 5: Commit**

```bash
git add src/services/court_service.py
git commit -m "fix: retry LLM and fallback signal when judge_react returns no tag"
```

---

### Task 2: Bug 4 — Race condition, two players press card button simultaneously

**Files:**
- Modify: `src/handlers/court_handlers.py:38-61` (\_\_init\_\_)
- Modify: `src/handlers/court_handlers.py:416-500` (handle\_play\_card)

**Step 1: Add _game_locks dict to __init__**

In `CourtHandlers.__init__()`, after the existing instance variables (around line 57), add:
```python
        # Per-game locks to prevent simultaneous card plays
        self._game_locks: dict[int, threading.Lock] = {}
```

**Step 2: Wrap phase check + set_phase in handle_play_card with a lock**

In `setup_callback_handlers()` → `handle_play_card()`, find the section that:
1. Checks `current_phase`
2. Checks `defense_played`
3. Calls `self.court_service.set_phase(game_id, ...)`

Wrap that entire block with a lock. Find the phase check (around line 432):
```python
            current_phase = game.get('current_phase', 'prosecution')
            if role == 'prosecutor' and current_phase != 'prosecution':
                ...
            if role in ('lawyer', 'witness') and current_phase != 'defense':
                ...
```

Add before it:
```python
            lock = self._game_locks.setdefault(game_id, threading.Lock())
            with lock:
```

And indent everything through the `set_phase` calls (lines ~491-494) under the `with lock:` block. The thread spawn (`threading.Thread(...)`) can stay outside the lock.

The resulting structure:
```python
            lock = self._game_locks.setdefault(game_id, threading.Lock())
            with lock:
                # Re-fetch game state inside lock for freshness
                game = self.court_service.get_active_game_by_id(game_id)
                if not game or game['status'] != 'in_progress':
                    self.bot.answer_callback_query(call.id, "Игра уже завершена.", show_alert=True)
                    return

                current_phase = game.get('current_phase', 'prosecution')
                if role == 'prosecutor' and current_phase != 'prosecution':
                    self.bot.answer_callback_query(
                        call.id,
                        "⚖️ Не ваша очередь — суд ещё не передал вам слово!",
                        show_alert=True
                    )
                    return
                if role in ('lawyer', 'witness') and current_phase != 'defense':
                    self.bot.answer_callback_query(
                        call.id,
                        "⚖️ Не ваша очередь — суд ещё не передал вам слово!",
                        show_alert=True
                    )
                    return

                # ... existing checks for user_id, cards_left, defense_played ...

                if role == 'prosecutor':
                    self.court_service.set_phase(game_id, 'prosecution_speech')
                elif role in ('lawyer', 'witness'):
                    self.court_service.set_phase(game_id, 'defense_speech')

            # Thread spawn stays outside lock
            threading.Thread(
                target=self._process_played_card,
                ...
            ).start()
```

**Step 3: Commit**

```bash
git add src/handlers/court_handlers.py
git commit -m "fix: add per-game lock to prevent simultaneous card play race condition"
```

---

### Task 3: Bug 7 — Fallback fires while player is typing reply

**Files:**
- Modify: `src/handlers/court_handlers.py:761-775` (_process_judge_reply)

**Step 1: Add phase guard at start of _process_judge_reply()**

Find `_process_judge_reply()` at line 761. After `self.bot.send_chat_action(chat_id, 'typing')`, add:

```python
    def _process_judge_reply(self, game_id: int, chat_id: int, role: str, reply_text: str, round_num: int):
        """Process a player's reply to a judge question."""
        try:
            # Guard: if fallback already fired and moved phase on, discard this reply
            game = self.court_service.get_active_game_by_id(game_id)
            if not game or game.get('current_phase') != 'judge':
                logger.info(f"[COURT] _process_judge_reply: phase already advanced, discarding reply game={game_id}")
                return

            self.bot.send_chat_action(chat_id, 'typing')
            reaction, signal = self.court_service.judge_react_to_reply(game_id, role, reply_text, round_num)
            ...
```

**Step 2: Commit**

```bash
git add src/handlers/court_handlers.py
git commit -m "fix: discard judge reply if fallback already advanced game phase"
```

---

### Task 4: Bug 8 — Vague "Защита уже ответила" message

**Files:**
- Modify: `src/handlers/court_handlers.py:461-469` (inside handle_play_card)

**Step 1: Find the defense_played check**

Around line 461 in `handle_play_card`:
```python
            if role in ('lawyer', 'witness'):
                current_round = game['current_round']
                defense_played = any(
                    p['role'] in ('lawyer', 'witness') and p['round'] == current_round
                    for p in game['played_cards']
                )
                if defense_played:
                    self.bot.answer_callback_query(call.id, "Защита уже ответила в этом раунде!", show_alert=True)
                    return
```

**Step 2: Replace with specific message**

```python
            if role in ('lawyer', 'witness'):
                current_round = game['current_round']
                played_defense_role = next(
                    (p['role'] for p in game['played_cards']
                     if p['role'] in ('lawyer', 'witness') and p['round'] == current_round),
                    None
                )
                if played_defense_role is not None:
                    who = "🛡️ Адвокат" if played_defense_role == 'lawyer' else "👁️ Свидетель"
                    self.bot.answer_callback_query(
                        call.id,
                        f"{who} уже ответил в этом раунде!",
                        show_alert=True
                    )
                    return
```

**Step 3: Commit**

```bash
git add src/handlers/court_handlers.py
git commit -m "fix: show specific role name when defense already played this round"
```

---

### Task 5: Bug 9 — Verdict skips --- separators → empty blocks

**Files:**
- Modify: `src/services/court_service.py:408-454` (generate_verdict)

**Step 1: Add format example to verdict prompt**

In `generate_verdict()`, find the prompt section with the 4 blocks (around line 438). After the block descriptions and before the ironic instruction, add an example:

```python
        prompt = f"""...(existing content)...

Вынеси приговор в 4 отдельных блоках, разделённых строкой "---":

Блок 1: Резюме позиции обвинения (2-3 предложения, со ссылкой на конкретные аргументы)
---
Блок 2: Резюме позиции защиты (2-3 предложения)
---
Блок 3: Ключевые противоречия и наблюдения суда (2-3 предложения, которые решили дело)
---
Блок 4: ПРИГОВОР (драматично, 2-4 предложения)
ОБЯЗАТЕЛЬНО: первая строка блока 4 — ровно одно из двух слов: **ВИНОВЕН** или **НЕ ВИНОВЕН** (жирным, отдельной строкой). Затем — сам приговор с характером.

Пример правильного формата ответа:
Обвинение настаивало на том, что...
---
Защита утверждала, что...
---
Ключевое противоречие состоит в том, что...
---
**НЕ ВИНОВЕН**
Суд постановил: ...

Будь ироничным...(existing text)..."""
```

**Step 2: Add retry logic after LLM call**

Find (around line 450):
```python
        raw = self._call_judge_llm(prompt)
        parts = [p.strip() for p in raw.split("---") if p.strip()]
        if len(parts) < 4:
            parts = parts + [""] * (4 - len(parts))
        return parts[:4]
```

Replace with:
```python
        raw = self._call_judge_llm(prompt)
        parts = [p.strip() for p in raw.split("---") if p.strip()]

        if len(parts) < 4:
            logger.warning(f"[COURT] generate_verdict: got {len(parts)} blocks, retrying")
            raw = self._call_judge_llm(prompt)
            parts = [p.strip() for p in raw.split("---") if p.strip()]

        if len(parts) < 4:
            logger.error(f"[COURT] generate_verdict: still {len(parts)} blocks after retry, using fallback")
            # Use entire response as ПРИГОВОР block if we have nothing
            if not parts:
                parts = ["", "", "", raw.strip()]
            else:
                parts = parts + [""] * (4 - len(parts))

        return parts[:4]
```

**Step 3: Commit**

```bash
git add src/services/court_service.py
git commit -m "fix: retry verdict generation and add format example when blocks < 4"
```
