"""Atomic Wordle attempts shared by concurrent mini-app requests."""
import json
from datetime import datetime, timezone

from services.wordle_logic import MAX_ATTEMPTS, is_valid_guess, score_guess


async def record_guess(db, day, player_id, player_name, guess, target, expected_attempts=None):
    """Return (game, already_finished); only the finishing request earns a reward."""
    async with db.connection() as conn:
        async with conn.transaction():
            cursor = await conn.execute(
                "SELECT attempts, guesses, won, finished FROM wordle_games "
                "WHERE date=%s AND player_id=%s FOR UPDATE", (day, player_id),
            )
            row = await cursor.fetchone()
            if row is None:
                raise RuntimeError('Wordle game disappeared before guess')
            attempts, guesses, won, finished = row
            guesses = json.loads(guesses) if isinstance(guesses, str) else guesses or []
            if finished:
                return {'attempts': attempts, 'guesses': guesses, 'won': won, 'finished': True}, True
            if expected_attempts is not None and attempts != expected_attempts:
                return {'attempts': attempts, 'guesses': guesses, 'won': won, 'finished': False,
                        'duplicate': True}, False
            if not is_valid_guess(guess, target):
                raise ValueError('not_a_word')
            guesses = guesses + [{'guess': guess, 'marks': score_guess(guess, target)}]
            attempts = len(guesses)
            won = guess == target
            finished = won or attempts >= MAX_ATTEMPTS
            await conn.execute(
                "UPDATE wordle_games SET attempts=%s, guesses=%s, won=%s, finished=%s, "
                "finished_at=%s, player_name=%s WHERE date=%s AND player_id=%s",
                (attempts, json.dumps(guesses), won, finished,
                 datetime.now(timezone.utc) if finished else None, player_name, day, player_id),
            )
    return {'attempts': attempts, 'guesses': guesses, 'won': won, 'finished': finished}, False
