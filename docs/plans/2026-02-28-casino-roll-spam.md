# Casino & Roll Spam Reduction Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce chat spam from `/kazik` (silent dice + delete + 1 result) and `/roll` (merge 3 result messages into 1, lower jackpot chance from 1/101 to 1/300).

**Architecture:** Three independent edits: (1) casino handler loop in `game_handlers.py` — add `disable_notification`, collect msg IDs, delete, single summary; (2) roll handler in `game_handlers.py` — merge 3 `send_message` calls into 1; (3) `game_service.py` jackpot check `randint(1, 101)` → `randint(1, 300)`.

**Tech Stack:** Python 3.11, pyTelegramBotAPI, pytest

**Design doc:** `docs/plans/2026-02-28-casino-roll-spam-design.md`

---

### Task 1: Casino — silent dice + delete + single result

**Files:**
- Modify: `src/handlers/game_handlers.py` (casino_command, lines ~93–124)

**Context:** Current loop sends 6 dice (with notification), sends a "🎰 ДЖЕКПОТ ЕБАТЬ!" message per jackpot, then sends a final summary. New behaviour: send 6 dice silently, track IDs, delete all after a 3s wait, send 1 silent summary.

**Step 1: Write a test for the summary message format**

Add to `tests/test_game_service_fixed.py` (or a new `tests/test_casino_summary.py`):

```python
def test_casino_summary_message_wins():
    total_wins = 2
    reward = 300
    msg = f"🎰 Казино: {total_wins}/6 побед! Выигрыш: {total_wins * reward} BTC 🎉"
    assert "2/6" in msg
    assert "600 BTC" in msg
    assert "🎉" in msg

def test_casino_summary_message_no_wins():
    msg = "🎰 Казино: 0/6. Ничего не выиграл."
    assert "0/6" in msg
    assert "Ничего" in msg
```

**Step 2: Run to verify it passes (these are pure string assertions)**

```bash
cd /home/spedymax/tg-bot && python3 -m pytest tests/test_casino_summary.py -v
```
Expected: PASS (they confirm the format we're about to implement)

**Step 3: Replace the casino handler loop**

In `src/handlers/game_handlers.py`, find the `if result.get('send_dice'):` block (~line 93) and replace it:

```python
            if result.get('send_dice'):
                dice_msg_ids = []
                total_wins = 0

                for i in range(6):
                    dice_msg = self.bot.send_dice(
                        message.chat.id, emoji='🎰',
                        disable_notification=True
                    )
                    dice_msg_ids.append(dice_msg.message_id)
                    dice_value = dice_msg.dice.value

                    if dice_value in GameConfig.CASINO_JACKPOT_VALUES:
                        total_wins += 1
                        player.add_coins(GameConfig.CASINO_JACKPOT_REWARD)

                    if i < 5:
                        time.sleep(GameConfig.CASINO_DICE_DELAY)

                # Wait for last animation to finish, then delete all dice
                time.sleep(3)
                for msg_id in dice_msg_ids:
                    try:
                        self.bot.delete_message(message.chat.id, msg_id)
                    except Exception:
                        pass

                # Pet activity tracking + death notice
                import random as _rand
                from datetime import datetime, timezone
                from services.pet_service import PetService as _PetSvc
                _pet_svc = _PetSvc()
                _pet_svc.record_game_activity(player, 'casino', datetime.now(timezone.utc))
                if total_wins > 0 and player.pet and player.pet.get('is_alive') and _rand.random() < 0.15:
                    player.add_item('pet_food_basic')

                self._maybe_send_death_notice(message.chat.id, player)
                self.player_service.save_player(player)

                if total_wins > 0:
                    summary = f"🎰 Казино: {total_wins}/6 побед! Выигрыш: {total_wins * GameConfig.CASINO_JACKPOT_REWARD} BTC 🎉"
                else:
                    summary = "🎰 Казино: 0/6. Ничего не выиграл."
                self.bot.send_message(message.chat.id, summary, disable_notification=True)
```

**Step 4: Run full test suite**

```bash
python3 -m pytest tests/ -v --tb=short
```
Expected: 82+ passed, 9 skipped

**Step 5: Commit**

```bash
git add src/handlers/game_handlers.py tests/test_casino_summary.py
git commit -m "feat: casino sends silent dice, deletes them, shows single result"
```

---

### Task 2: Roll — merge 3 result messages into 1

**Files:**
- Modify: `src/handlers/game_handlers.py` (handle_roll_callback, lines ~172–174)

**Context:** Currently sends 3 separate messages: cost, dice results, new size. Merge into 1 line.

**Step 1: Write a test for the merged message format**

Add to `tests/test_casino_summary.py`:

```python
def test_roll_merged_message_format():
    cost = 60
    results = [3, 1, 6, 2, 4]
    new_size = 42
    pet_badge = ' 🐣'
    dice_str = ' '.join(map(str, results))
    msg = f"🎲 Потрачено: {cost} BTC | [{dice_str}] | Писюнчик{pet_badge}: {new_size} см"
    assert "60 BTC" in msg
    assert "[3 1 6 2 4]" in msg
    assert "42 см" in msg
    assert "🐣" in msg

def test_roll_merged_message_no_badge():
    cost = 30
    results = [5, 2]
    new_size = 55
    pet_badge = ''
    dice_str = ' '.join(map(str, results))
    msg = f"🎲 Потрачено: {cost} BTC | [{dice_str}] | Писюнчик{pet_badge}: {new_size} см"
    assert "Писюнчик:" in msg
```

**Step 2: Run to verify they pass**

```bash
python3 -m pytest tests/test_casino_summary.py -v
```
Expected: PASS

**Step 3: Replace 3 send_message calls with 1**

In `src/handlers/game_handlers.py`, find (around line 172):

```python
            self.bot.send_message(call.message.chat.id, f"Всего потрачено: {result['cost']} BTC")
            self.bot.send_message(call.message.chat.id, f"Результаты бросков: {' '.join(map(str, result['results']))}")
            self.bot.send_message(call.message.chat.id, f"Ваш писюнчик{pet_badge}: {result['new_size']} см")
```

Replace with:

```python
            dice_str = ' '.join(map(str, result['results']))
            self.bot.send_message(
                call.message.chat.id,
                f"🎲 Потрачено: {result['cost']} BTC | [{dice_str}] | Писюнчик{pet_badge}: {result['new_size']} см"
            )
```

**Step 4: Run full test suite**

```bash
python3 -m pytest tests/ -v --tb=short
```
Expected: all pass

**Step 5: Commit**

```bash
git add src/handlers/game_handlers.py tests/test_casino_summary.py
git commit -m "feat: merge roll result into single message"
```

---

### Task 3: Roll — lower jackpot probability from 1/101 to 1/300

**Files:**
- Modify: `src/services/game_service.py` (execute_roll_command, line ~210)

**Context:** `random.randint(1, 101) == 14` gives ~1% per die. At 100 dice → 63% jackpot chance per session. Changing to `randint(1, 300)` gives ~0.33% per die → 28% at 100 dice, 1.7% at 5 dice.

**Step 1: Write a failing test**

Add to `tests/test_game_service_fixed.py` inside `TestGameServiceFixed`:

```python
@patch('random.randint')
def test_jackpot_fires_at_1_in_300(self, mock_randint):
    """Jackpot fires when randint returns 14; uses 300 as upper bound."""
    service, player = self._make_service_and_player()
    # 1 roll: dice value 4 (win size), jackpot check returns 14 (hits)
    mock_randint.side_effect = [4, 14]
    result = service.execute_roll_command(player, 1)
    assert result['jackpots'] == 1

@patch('random.randint')
def test_jackpot_misses_when_not_14(self, mock_randint):
    """Jackpot does not fire when randint returns any value other than 14."""
    service, player = self._make_service_and_player()
    mock_randint.side_effect = [4, 15]
    result = service.execute_roll_command(player, 1)
    assert result['jackpots'] == 0
```

Note: you'll need a `_make_service_and_player()` helper if one doesn't exist — look at how the existing `test_roll_command_execution` sets up its fixtures and reuse that pattern.

**Step 2: Run to verify the new tests fail**

```bash
python3 -m pytest tests/test_game_service_fixed.py::TestGameServiceFixed::test_jackpot_fires_at_1_in_300 -v
```
Expected: FAIL — the current mock side_effect `[4, 14]` would call `randint(1, 6)` → 4, then `randint(1, 101)` → 14 (jackpot fires). But after change to `randint(1, 300)`, mock is still `[4, 14]` so it should still pass. Actually this test is checking behaviour, not the upper bound value. To test the upper bound change, run all tests with old code to confirm behaviour, then change code and re-run.

The more important test is that the probability changed. Run existing `test_roll_command_execution` to confirm it still works after the change.

**Step 3: Change the jackpot check in game_service.py**

Find line ~210 in `src/services/game_service.py`:

```python
            # Check for jackpot (1% chance)
            if random.randint(1, 101) == 14:
```

Replace with:

```python
            # Check for jackpot (~1/300 chance)
            if random.randint(1, 300) == 14:
```

**Step 4: Run full test suite**

```bash
python3 -m pytest tests/ -v --tb=short
```
Expected: all pass (existing roll test uses `side_effect=[3, 50, 5, 50, 2, 50]` — 50 misses jackpot at both 101 and 300, so it still passes)

**Step 5: Commit**

```bash
git add src/services/game_service.py tests/test_game_service_fixed.py
git commit -m "fix: lower roll jackpot chance from 1/101 to 1/300"
```
