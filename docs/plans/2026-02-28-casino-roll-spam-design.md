# Casino & Roll Spam Reduction Design

**Date:** 2026-02-28
**Status:** Approved

## Overview

`/kazik` floods the chat with 6 dice messages + per-jackpot shouts + a summary (up to 13 messages, all with notifications). `/roll` sends 3 separate result messages and jackpots fire near-constantly at high roll counts (63% at 100 dice due to 1/101 per-die probability). Both are annoying in group chats.

---

## Section 1: Casino — silent dice + delete + single result

### New flow

1. Send 6 dice with `disable_notification=True` — group sees animation, no ping
2. Collect all 6 message IDs; accumulate jackpot count silently (no per-jackpot text messages)
3. After last die, sleep ~3 seconds for the final animation to finish
4. Delete all 6 dice messages via `bot.delete_message`
5. Send 1 summary with `disable_notification=True`:
   - Wins > 0: `🎰 Казино: X/6 побед! Выигрыш: Y BTC 🎉`
   - No wins: `🎰 Казино: 0/6. Ничего не выиграл.`

### What's removed

- Per-jackpot text message (`🎰 ДЖЕКПОТ ЕБАТЬ! Вы получаете 300 BTC!`) — win count folded into summary

### Files changed

- `src/handlers/game_handlers.py` — casino_command loop

---

## Section 2: Roll — merged result + lower jackpot chance

### Result messages

3 separate messages → 1 merged message:

```
🎲 Потрачено: 60 BTC | [3 1 6 2 4 ...] | Писюнчик🐣: 42 см
```

(Pet badge included when applicable.)

### Jackpot probability

`random.randint(1, 300) == 14` → ~1/300 per die

| Roll count | Old chance | New chance |
|------------|------------|------------|
| 5          | ~4.9%      | ~1.7%      |
| 20         | ~18.1%     | ~6.5%      |
| 100        | ~63.2%     | ~28.4%     |

Jackpot messages stay dramatic and separate — they just fire less often.

### Files changed

- `src/handlers/game_handlers.py` — handle_roll_callback (merge 3 sends → 1)
- `src/services/game_service.py` — execute_roll_command (jackpot probability)

---

## Out of Scope

- Changing casino jackpot values or rewards
- Adding cooldowns or limits to roll
- Modifying jackpot message text
