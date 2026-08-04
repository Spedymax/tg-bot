"""
Pure Wordle game logic — word selection, guess scoring, results rendering.
No aiogram/Flask/DB imports here on purpose: this module is shared between the
bot process (src/handlers/wordle_handlers.py, posts the daily message) and the
Flask mini-app process (miniapp/app.py, scores guesses), which don't otherwise
share a dependency footprint.
"""

import json
import os
from datetime import date

WORD_LENGTH = 5
MAX_ATTEMPTS = 6

# Fixed anchor so the same calendar date always maps to the same word index —
# no shared state needed between the two processes that use this module.
EPOCH_DATE = date(2024, 1, 1)

EMOJI = {'correct': '🟩', 'present': '🟨', 'absent': '⬜'}

_ANSWERS_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'assets', 'data', 'wordle_answers.json')
_GUESSES_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'assets', 'data', 'wordle_valid_guesses.json')

_answers_cache = None
_valid_guesses_cache = None


def load_answers() -> list[str]:
    global _answers_cache
    if _answers_cache is None:
        with open(_ANSWERS_PATH, encoding='utf-8') as f:
            _answers_cache = json.load(f)
    return _answers_cache


def load_valid_guesses() -> set[str]:
    global _valid_guesses_cache
    if _valid_guesses_cache is None:
        with open(_GUESSES_PATH, encoding='utf-8') as f:
            _valid_guesses_cache = set(json.load(f))
    return _valid_guesses_cache


def word_for_date(d: date) -> str:
    answers = load_answers()
    index = (d - EPOCH_DATE).days % len(answers)
    return answers[index]


def is_valid_guess(guess: str, target: str) -> bool:
    """The target word is always accepted even if it got trimmed from the
    valid-guesses dictionary during curation (blacklist filtering)."""
    return guess == target or guess in load_valid_guesses()


def score_guess(guess: str, target: str) -> list[str]:
    """Standard two-pass Wordle scoring, correct for repeated letters."""
    n = len(target)
    marks = ['absent'] * n
    remaining = list(target)
    for i in range(n):
        if guess[i] == remaining[i]:
            marks[i] = 'correct'
            remaining[i] = None
    for i in range(n):
        if marks[i] == 'correct':
            continue
        ch = guess[i]
        if ch in remaining:
            marks[i] = 'present'
            remaining[remaining.index(ch)] = None
    return marks


def marks_to_emoji(marks: list[str]) -> str:
    return ''.join(EMOJI[m] for m in marks)


def build_share_text(d: date, attempts: int, won: bool, all_marks: list[list[str]]) -> str:
    result_label = f"{attempts}/{MAX_ATTEMPTS}" if won else f"X/{MAX_ATTEMPTS}"
    grid = "\n".join(marks_to_emoji(m) for m in all_marks)
    return f"Wordle дня {d.isoformat()} {result_label}\n\n{grid}"


def build_message_text(rows: list[tuple[str, int, bool, list[list[str]] | None]]) -> str:
    """rows: list of (player_name, attempts, won, all_guess_marks) for players who
    have FINISHED today's puzzle — in-progress games are never shown, so nobody's
    partial attempts leak into the group chat. all_guess_marks holds only the
    attempts actually made (no padding to MAX_ATTEMPTS)."""
    parts = [
        "🟩🟨⬜ <b>WORDLE ДНЯ</b> ⬜🟨🟩",
        "",
        "Угадай английское слово из 5 букв за 6 попыток. Жми на кнопку ниже, чтобы играть — "
        "твой результат появится тут же, без лишних сообщений в чат.",
        "",
    ]
    if not rows:
        parts.append("📊 Результаты: пока никто не сыграл")
    else:
        parts.append("📊 <b>Результаты дня:</b>")
        for name, attempts, won, all_marks in rows:
            status = f"{attempts}/6" if won else "❌"
            parts.append("")
            parts.append(f"{status} — <b>{name}</b>")
            if all_marks:
                parts.append("\n".join(marks_to_emoji(m) for m in all_marks))
    return "\n".join(parts)
