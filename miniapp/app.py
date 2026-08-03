from flask import Flask, render_template, request, jsonify, send_from_directory
import os
import sys
import json
import logging
import random
import re
import hmac
import hashlib
import time
import urllib.parse
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal
import asyncio
import threading

import requests

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src_dir = os.path.join(parent_dir, 'src')
sys.path.insert(0, parent_dir)
sys.path.insert(0, src_dir)

try:
    from config.settings import Settings
    from database.db_manager import DatabaseManager
    from database.player_service import PlayerService
    from services.wordle_logic import (
        score_guess, is_valid_guess, build_message_text, build_share_text,
        word_for_date, WORD_LENGTH, MAX_ATTEMPTS,
    )
except ImportError as e:
    Settings = DatabaseManager = PlayerService = None
    score_guess = is_valid_guess = build_message_text = build_share_text = word_for_date = None
    WORD_LENGTH, MAX_ATTEMPTS = 5, 6

app = Flask(__name__)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

if DatabaseManager and PlayerService:
    try:
        db_manager = DatabaseManager()
        player_service = PlayerService(db_manager)
        logger.info("Database integration enabled")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        db_manager = None
        player_service = None
else:
    db_manager = None
    player_service = None

# --- async→sync bridge for the async DB layer (psycopg AsyncConnectionPool) ---
# The DB layer (PlayerService/DatabaseManager) is fully async, but Flask is sync.
# Run all DB coroutines on a single background event loop where the pool is opened.
_db_loop = asyncio.new_event_loop()
threading.Thread(target=_db_loop.run_forever, daemon=True, name="db-loop").start()


def run_async(coro):
    """Run a coroutine on the background DB loop and block for its result."""
    return asyncio.run_coroutine_threadsafe(coro, _db_loop).result()


if db_manager and player_service:
    try:
        run_async(db_manager.init_pool())
        logger.info("Async DB connection pool opened")
    except Exception as e:
        logger.error(f"Failed to open DB pool, falling back to in-memory: {e}")
        db_manager = None
        player_service = None


async def _ensure_wordle_tables():
    await db_manager.execute_query(
        "CREATE TABLE IF NOT EXISTS wordle_daily ("
        "id SERIAL PRIMARY KEY, "
        "date DATE UNIQUE NOT NULL, "
        "word TEXT NOT NULL, "
        "chat_id BIGINT NOT NULL, "
        "message_id BIGINT, "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
        (),
    )
    await db_manager.execute_query(
        "CREATE TABLE IF NOT EXISTS wordle_games ("
        "id SERIAL PRIMARY KEY, "
        "date DATE NOT NULL, "
        "player_id BIGINT NOT NULL, "
        "player_name TEXT, "
        "attempts INTEGER DEFAULT 0, "
        "guesses JSONB DEFAULT '[]', "
        "won BOOLEAN DEFAULT FALSE, "
        "finished BOOLEAN DEFAULT FALSE, "
        "finished_at TIMESTAMP, "
        "UNIQUE(date, player_id))",
        (),
    )


if db_manager and player_service:
    try:
        run_async(_ensure_wordle_tables())
        logger.info("Wordle tables ensured")
    except Exception as e:
        logger.error(f"Failed to ensure wordle tables: {e}")

player_data = {}
MAX_DAILY_SPINS = 6

def _today_str():
    return datetime.now(timezone.utc).date().isoformat()

def _to_int(val):
    try:
        return int(val)
    except Exception:
        return None

def _select_prize(rand_value):
    if rand_value < 0.03:
        return {'text': '🎰 МЕГА ДЖЕКПОТ! ЕБААААТЬ!🎰', 'type': 'jackpot', 'value': 500}
    elif rand_value < 0.08:
        return {'text': '🎉 БОЛЬШОЙ ВЫИГРЫШ!🎉', 'type': 'big_win', 'value': 300}
    elif rand_value < 0.15:
        return {'text': '✨ Хороший выигрыш! ✨', 'type': 'medium_win', 'value': 150}
    elif rand_value < 0.25:
        return {'text': '💰 Небольшой выигрыш! 💰', 'type': 'small_win', 'value': 50}
    else:
        return {'text': 'Попробуйте ещё раз! 🎲', 'type': 'lose', 'value': 0}

@app.route('/miniapp')
@app.route('/miniapp/')
def index():
    return send_from_directory('.', 'slot_casino.html')

@app.route('/miniapp/slots')
def slots():
    return send_from_directory('.', 'slot_casino.html')

@app.route('/miniapp/casino')
def casino():
    return send_from_directory('.', 'casino.html')

@app.route('/miniapp/api/players', methods=['GET'])
def list_players():
    if player_service:
        players = run_async(player_service.get_all_players())
        data = []
        for p in players:
            data.append({
                'id': int(players[p].player_id),
                'name': players[p].player_name,
                'coins': int(players[p].coins),
            })
    else:
        data = [
            {'id': pid, 'name': pdata.get('name', name), 'coins': pdata['coins']}
            for pid, name, pdata in player_data.items()
        ]
    return jsonify({'success': True, 'data': data})


@app.route('/miniapp/api/player/<int:player_id>')
def get_player_data(player_id):
    logger.info(f"Getting player data for player_id: {player_id}")
    if player_service:
        try:
            player = run_async(player_service.get_player(player_id))
        except Exception as e:
            logger.error(f"DB error getting player {player_id}: {e}")
            player = None
        if not player:
            if player_id not in player_data:
                player_data[player_id] = {'coins': 100, 'daily_spins': 0, 'last_spin_date': _today_str(), 'max_daily_spins': MAX_DAILY_SPINS}
                logger.info(f"Created fallback player data for {player_id}")
            player_dict = player_data[player_id]
            today = _today_str()
            if player_dict['last_spin_date'] != today:
                player_dict['daily_spins'] = 0
                player_dict['last_spin_date'] = today
            spins_left = max(0, player_dict['max_daily_spins'] - player_dict['daily_spins'])
            return jsonify({'success': True, 'data': {'coins': player_dict['coins'], 'spins_left': spins_left, 'daily_spins': player_dict['daily_spins'], 'max_daily_spins': player_dict['max_daily_spins'], 'fallback_mode': True}})
        try:
            today = datetime.now(timezone.utc).date()
            last_spin = getattr(player, 'miniapp_last_spin_date', None)
            if isinstance(last_spin, str):
                try:
                    last_spin_date = datetime.fromisoformat(last_spin).date()
                except Exception:
                    last_spin_date = datetime.min.replace(tzinfo=timezone.utc).date()
            elif last_spin is None:
                last_spin_date = datetime.min.replace(tzinfo=timezone.utc).date()
            else:
                last_spin_date = last_spin.date()
            if last_spin_date != today:
                player.miniapp_daily_spins = 0
                player.miniapp_last_spin_date = datetime.now(timezone.utc)
                run_async(player_service.save_player(player))
            max_daily_spins = MAX_DAILY_SPINS
            spins_left = max(0, max_daily_spins - getattr(player, 'miniapp_daily_spins', 0))
            return jsonify({'success': True, 'data': {'coins': int(player.coins), 'spins_left': spins_left, 'daily_spins': getattr(player, 'miniapp_daily_spins', 0), 'max_daily_spins': max_daily_spins, 'total_winnings': getattr(player, 'miniapp_total_winnings', 0.0)}})
        except Exception as e:
            logger.error(f"Error building player data for DB player {player_id}: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    else:
        if player_id not in player_data:
            player_data[player_id] = {'coins': 100, 'daily_spins': 0, 'last_spin_date': _today_str(), 'max_daily_spins': MAX_DAILY_SPINS}
        player = player_data[player_id]
        today = _today_str()
        if player['last_spin_date'] != today:
            player['daily_spins'] = 0
            player['last_spin_date'] = today
        spins_left = max(0, player['max_daily_spins'] - player['daily_spins'])
        return jsonify({'success': True, 'data': {'coins': player['coins'], 'spins_left': spins_left, 'daily_spins': player['daily_spins'], 'max_daily_spins': player['max_daily_spins']}})

@app.route('/miniapp/api/spin', methods=['POST'])
def spin_wheel():
    try:
        data = request.json or {}
        player_id_raw = data.get('player_id')
        player_id = _to_int(player_id_raw)
        if player_id is None:
            return jsonify({'success': False, 'error': 'Player ID required and must be integer'}), 400
        debug_mode = request.args.get('debug') == '1' or app.debug
        rand_value = random.random()
        prize = _select_prize(rand_value)
        logger.debug(f"Spin rand={rand_value} prize={prize} for player {player_id}")
        if player_service:
            try:
                player = run_async(player_service.get_player(player_id))
            except Exception as e:
                logger.error(f"DB error getting player {player_id}: {e}")
                return jsonify({'success': False, 'error': 'Database error'}), 500
            if not player:
                return jsonify({'success': False, 'error': 'Player not found'}), 404
            try:
                today = datetime.now(timezone.utc).date()
                last_spin = getattr(player, 'miniapp_last_spin_date', None)
                if isinstance(last_spin, str):
                    try:
                        last_spin_date = datetime.fromisoformat(last_spin).date()
                    except Exception:
                        last_spin_date = datetime.min.replace(tzinfo=timezone.utc).date()
                elif last_spin is None:
                    last_spin_date = datetime.min.replace(tzinfo=timezone.utc).date()
                else:
                    last_spin_date = last_spin.date()
                if last_spin_date != today:
                    player.miniapp_daily_spins = 0
                    player.miniapp_last_spin_date = datetime.now(timezone.utc)
                max_daily_spins = MAX_DAILY_SPINS
                current_spins = getattr(player, 'miniapp_daily_spins', 0)
                if current_spins >= max_daily_spins:
                    return jsonify({'success': False, 'error': 'No spins left for today'}), 400
                original_coins = int(player.coins)
                coins_gained = 0
                if prize['type'] != 'lose':
                    player.coins = int(player.coins) + int(prize['value'])
                    coins_gained = int(prize['value'])
                    player.miniapp_total_winnings = getattr(player, 'miniapp_total_winnings', Decimal('0')) + Decimal(
                        str(prize['value']))
                player.miniapp_daily_spins = current_spins + 1
                player.miniapp_last_spin_date = datetime.now(timezone.utc)
                run_async(player_service.save_player(player))
                spins_left = max(0, max_daily_spins - player.miniapp_daily_spins)
                resp = {'success': True, 'data': {'prize': prize, 'coins': int(player.coins), 'coins_gained': coins_gained, 'spins_left': spins_left, 'daily_spins': player.miniapp_daily_spins, 'total_winnings': player.miniapp_total_winnings}}
                if debug_mode:
                    resp['debug'] = {'rand_value': rand_value}
                return jsonify(resp)
            except Exception as e:
                logger.error(f"Error processing spin for DB player {player_id}: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500
        else:
            if player_id not in player_data:
                return jsonify({'success': False, 'error': 'Player not found'}), 404
            player = player_data[player_id]
            today = _today_str()
            if player['last_spin_date'] != today:
                player['daily_spins'] = 0
                player['last_spin_date'] = today
            if player['daily_spins'] >= player['max_daily_spins']:
                return jsonify({'success': False, 'error': 'No spins left for today'}), 400
            original_coins = player['coins']
            if prize['type'] != 'lose':
                player['coins'] = player['coins'] + int(prize['value'])
            player['daily_spins'] += 1
            spins_left = max(0, player['max_daily_spins'] - player['daily_spins'])
            resp = {'success': True, 'data': {'prize': prize, 'coins': player['coins'], 'coins_gained': player['coins'] - original_coins, 'spins_left': spins_left, 'daily_spins': player['daily_spins']}}
            if debug_mode:
                resp['debug'] = {'rand_value': rand_value}
            return jsonify(resp)
    except Exception as e:
        logger.error(f"Error processing spin: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/miniapp/api/save_progress', methods=['POST'])
def save_progress():
    try:
        data = request.json or {}
        player_id_raw = data.get('player_id')
        coins_raw = data.get('coins')
        spins_used = data.get('spins_used', 0)
        force = bool(data.get('force', False))
        player_id = _to_int(player_id_raw)
        if player_id is None:
            return jsonify({'success': False, 'error': 'Player ID required and must be integer'}), 400
        if coins_raw is None:
            return jsonify({'success': False, 'error': 'coins required'}), 400
        try:
            coins = int(coins_raw)
        except Exception:
            return jsonify({'success': False, 'error': 'coins must be integer'}), 400
        if player_service:
            try:
                player = run_async(player_service.get_player(player_id))
            except Exception as e:
                logger.error(f"DB error in save_progress for {player_id}: {e}")
                return jsonify({'success': False, 'error': 'Database error'}), 500
            if not player:
                return jsonify({'success': False, 'error': 'Player not found'}), 404
            current_coins = int(getattr(player, 'coins', 0))
            if coins < current_coins and not force:
                logger.warning(f"Ignored save_progress with lower coins for player {player_id}")
                return jsonify({'success': False, 'error': 'Provided coins lower than current; use force to override'}), 400
            player.coins = coins
            player.miniapp_daily_spins = int(spins_used)
            run_async(player_service.save_player(player))
            logger.info(f"Saved progress for DB player {player_id}: {coins} coins, {spins_used} spins used")
            return jsonify({'success': True})
        else:
            if player_id not in player_data:
                return jsonify({'success': False, 'error': 'Player not found'}), 404
            current = player_data[player_id]['coins']
            if coins < current and not force:
                logger.warning(f"Ignored save_progress with lower coins for fallback player {player_id}")
                return jsonify({'success': False, 'error': 'Provided coins lower than current; use force to override'}), 400
            player_data[player_id]['coins'] = coins
            player_data[player_id]['daily_spins'] = int(spins_used)
            logger.info(f"Saved progress for player {player_id}: {coins} coins, {spins_used} spins used")
            return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error saving progress: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/miniapp/refresh', methods=['GET', 'POST'])
def refresh_spins():
    try:
        if request.method == 'POST':
            data = request.json or {}
            player_id_raw = data.get('player_id')
        else:
            player_id_raw = request.args.get('player_id')
        player_id = _to_int(player_id_raw)
        if player_id is None:
            return jsonify({'success': False, 'error': 'player_id required'}), 400
        if player_service:
            try:
                player = run_async(player_service.get_player(player_id))
            except Exception as e:
                logger.error(f"DB error in refresh for {player_id}: {e}")
                return jsonify({'success': False, 'error': 'Database error'}), 500
            if not player:
                return jsonify({'success': False, 'error': 'Player not found'}), 404
            player.miniapp_daily_spins = 0
            player.miniapp_last_spin_date = datetime.now(timezone.utc)
            run_async(player_service.save_player(player))
            spins_left = MAX_DAILY_SPINS
            return jsonify({'success': True, 'message': 'Spins reset', 'spins_left': spins_left})
        else:
            if player_id not in player_data:
                player_data[player_id] = {'coins': 100, 'daily_spins': 0, 'last_spin_date': _today_str(), 'max_daily_spins': MAX_DAILY_SPINS}
            player_data[player_id]['daily_spins'] = 0
            player_data[player_id]['last_spin_date'] = _today_str()
            spins_left = MAX_DAILY_SPINS
            logger.info(f"Refreshed spins for fallback player {player_id}")
            return jsonify({'success': True, 'message': 'Spins reset', 'spins_left': spins_left})
    except Exception as e:
        logger.error(f"Error refreshing spins: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ── Wordle ───────────────────────────────────────────────────────────────────

def _today_kyiv():
    return datetime.now(ZoneInfo("Europe/Kyiv")).date()


def _validate_init_data(init_data: str, max_age_seconds: int = 86400):
    """Validate Telegram WebApp initData per the documented HMAC scheme, so a
    guess/result can never be attributed to the wrong Telegram user. Returns the
    parsed `user` dict on success, None otherwise."""
    if not init_data or not Settings or not Settings.TELEGRAM_BOT_TOKEN:
        return None
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data, strict_parsing=True))
    except Exception:
        return None
    received_hash = parsed.pop('hash', None)
    if not received_hash:
        return None
    data_check_string = '\n'.join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", Settings.TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed_hash, received_hash):
        return None
    try:
        auth_date = int(parsed.get('auth_date', '0'))
    except ValueError:
        return None
    if time.time() - auth_date > max_age_seconds:
        return None
    user_raw = parsed.get('user')
    if not user_raw:
        return None
    try:
        user = json.loads(user_raw)
    except Exception:
        return None
    if 'id' not in user:
        return None
    return user


def _get_or_create_game(today, player_id, player_name):
    row = run_async(db_manager.execute_query(
        "SELECT attempts, guesses, won, finished FROM wordle_games WHERE date=%s AND player_id=%s",
        (today, player_id),
    ))
    if row:
        attempts, guesses, won, finished = row[0]
        return {'attempts': attempts, 'guesses': guesses or [], 'won': won, 'finished': finished}
    run_async(db_manager.execute_query(
        "INSERT INTO wordle_games (date, player_id, player_name, attempts, guesses, won, finished) "
        "VALUES (%s, %s, %s, 0, %s, FALSE, FALSE) ON CONFLICT (date, player_id) DO NOTHING",
        (today, player_id, player_name, json.dumps([])),
    ))
    return {'attempts': 0, 'guesses': [], 'won': False, 'finished': False}


def _telegram_edit_message(chat_id, message_id, text):
    if not message_id or not Settings or not Settings.TELEGRAM_BOT_TOKEN:
        return
    markup = {
        "inline_keyboard": [[
            {"text": "🎮 Играть в Wordle", "web_app": {"url": Settings.WORDLE_WEB_APP_URL}}
        ]]
    }
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{Settings.TELEGRAM_BOT_TOKEN}/editMessageText",
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "parse_mode": "HTML",
                "reply_markup": markup,
            },
            timeout=10,
        )
        if not resp.ok:
            logger.error(f"Wordle: editMessageText failed: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"Wordle: editMessageText request error: {e}")


def _refresh_wordle_message(today):
    daily = run_async(db_manager.execute_query(
        "SELECT chat_id, message_id FROM wordle_daily WHERE date=%s", (today,)
    ))
    if not daily:
        return
    chat_id, message_id = daily[0]
    games = run_async(db_manager.execute_query(
        "SELECT player_name, attempts, won, guesses FROM wordle_games "
        "WHERE date=%s AND finished=TRUE ORDER BY finished_at ASC", (today,)
    ))
    rows = []
    for player_name, attempts, won, guesses in (games or []):
        last_marks = guesses[-1]['marks'] if guesses else None
        rows.append((player_name or 'Игрок', attempts, won, last_marks))
    text = build_message_text(rows)
    _telegram_edit_message(chat_id, message_id, text)


def _apply_wordle_reward(player_id, player_name, today, won, attempts):
    player = run_async(player_service.get_player(player_id))
    if not player:
        player = run_async(player_service.create_player(player_id, player_name))

    if won:
        last_played = getattr(player, 'wordle_last_played_date', None)
        last_date = last_played.date() if last_played is not None else None
        if last_date is not None and (today - last_date).days == 1:
            new_streak = getattr(player, 'wordle_streak', 0) + 1
        else:
            new_streak = 1
        player.wordle_streak = new_streak
        player.wordle_max_streak = max(getattr(player, 'wordle_max_streak', 0), new_streak)
        player.wordle_wins = getattr(player, 'wordle_wins', 0) + 1
        reward = max(10, (MAX_ATTEMPTS + 1 - attempts) * 15)
        # pisunchik_data.coins is bigint — keep integer math, matching the casino routes above.
        player.coins = int(getattr(player, 'coins', 0)) + reward
    else:
        player.wordle_streak = 0

    player.wordle_played = getattr(player, 'wordle_played', 0) + 1
    player.wordle_last_played_date = datetime.now(timezone.utc)
    run_async(player_service.save_player(player))
    return int(player.coins), player.wordle_streak


@app.route('/miniapp/wordle')
def wordle_page():
    return send_from_directory('.', 'wordle.html')


@app.route('/miniapp/api/wordle/today', methods=['GET'])
def wordle_today():
    if not db_manager:
        return jsonify({'success': False, 'error': 'Database not available'}), 503
    user = _validate_init_data(request.args.get('init_data', ''))
    if not user:
        return jsonify({'success': False, 'error': 'invalid_auth'}), 401
    player_id = user['id']
    player_name = user.get('first_name') or user.get('username') or 'Игрок'

    today = _today_kyiv()
    # Deterministic per-date word — computable without waiting on the daily
    # group post, so the mini-app is playable (e.g. via a DM test link) any time.
    target = word_for_date(today)

    game = _get_or_create_game(today, player_id, player_name)
    player = run_async(player_service.get_player(player_id))
    return jsonify({
        'success': True,
        'data': {
            'word_length': WORD_LENGTH,
            'max_attempts': MAX_ATTEMPTS,
            'attempts': game['attempts'],
            'guesses': game['guesses'],
            'finished': game['finished'],
            'won': game['won'],
            # Only reveal the word for a game that's already over.
            'target': target if game['finished'] else None,
            'player_name': player_name,
            'wordle_streak': getattr(player, 'wordle_streak', 0) if player else 0,
            'coins': int(player.coins) if player else 0,
        },
    })


@app.route('/miniapp/api/wordle/guess', methods=['POST'])
def wordle_guess():
    if not db_manager:
        return jsonify({'success': False, 'error': 'Database not available'}), 503
    data = request.json or {}
    user = _validate_init_data(data.get('init_data', ''))
    if not user:
        return jsonify({'success': False, 'error': 'invalid_auth'}), 401
    player_id = user['id']
    player_name = user.get('first_name') or user.get('username') or 'Игрок'

    guess = (data.get('guess') or '').strip().lower()
    if len(guess) != WORD_LENGTH or not re.fullmatch(r'[a-z]+', guess):
        return jsonify({'success': False, 'error': 'invalid_format'}), 400

    today = _today_kyiv()
    target = word_for_date(today)

    game = _get_or_create_game(today, player_id, player_name)
    if game['finished']:
        return jsonify({'success': True, 'data': {
            'finished': True, 'won': game['won'], 'attempts': game['attempts'],
            'guesses': game['guesses'], 'already_finished': True,
        }})

    if not is_valid_guess(guess, target):
        return jsonify({'success': False, 'error': 'not_a_word'}), 400

    marks = score_guess(guess, target)
    guesses = game['guesses'] + [{'guess': guess, 'marks': marks}]
    attempts = len(guesses)
    won = guess == target
    finished = won or attempts >= MAX_ATTEMPTS

    run_async(db_manager.execute_query(
        "UPDATE wordle_games SET attempts=%s, guesses=%s, won=%s, finished=%s, "
        "finished_at=%s, player_name=%s WHERE date=%s AND player_id=%s",
        (attempts, json.dumps(guesses), won, finished,
         datetime.now(timezone.utc) if finished else None, player_name, today, player_id),
    ))

    share_text = None
    coins = None
    wordle_streak = None
    if finished:
        coins, wordle_streak = _apply_wordle_reward(player_id, player_name, today, won, attempts)
        _refresh_wordle_message(today)
        share_text = build_share_text(today, attempts, won, [g['marks'] for g in guesses])

    return jsonify({'success': True, 'data': {
        'marks': marks, 'finished': finished, 'won': won, 'attempts': attempts,
        'max_attempts': MAX_ATTEMPTS, 'target': target if finished else None,
        'share_text': share_text, 'coins': coins, 'wordle_streak': wordle_streak,
    }})


@app.route('/miniapp/dog.jpg')
def serve_dog_image():
    try:
        return send_from_directory('.', 'dog.jpg')
    except FileNotFoundError:
        return '', 404

@app.route('/miniapp/audio/<path:filename>')
def serve_audio_files(filename):
    allowed_extensions = ['.mp3', '.ogg', '.wav', '.m4a']
    if any(filename.lower().endswith(ext) for ext in allowed_extensions):
        try:
            return send_from_directory('audio', filename)
        except FileNotFoundError:
            return '', 404
    return '', 404

@app.route('/miniapp/<path:filename>')
def serve_static_files(filename):
    allowed_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.css', '.js', '.ico']
    if any(filename.lower().endswith(ext) for ext in allowed_extensions):
        try:
            return send_from_directory('.', filename)
        except FileNotFoundError:
            return '', 404
    return '', 404

@app.route('/miniapp/health')
def health_check():
    return jsonify({'status': 'healthy', 'timestamp': datetime.now(timezone.utc).isoformat(), 'active_players': len(player_data)})

@app.route('/miniapp/debug')
def debug_info():
    import os
    return jsonify({'working_directory': os.getcwd(), 'files_in_directory': os.listdir('.'), 'slot_casino_exists': os.path.exists('slot_casino.html'), 'audio_directory_exists': os.path.exists('audio'), 'routes': [str(rule) for rule in app.url_map.iter_rules()], 'database_available': player_service is not None, 'fallback_players': list(player_data.keys())})

@app.route('/miniapp/api/test_db')
def test_database():
    try:
        if not player_service:
            return jsonify({'success': False, 'message': 'Database not available', 'fallback_players': list(player_data.keys())})
        players = run_async(player_service.get_all_players())
        player_list = []
        for player_id, player in players.items():
            player_list.append({'player_id': player.player_id, 'player_name': player.player_name, 'coins': player.coins, 'pisunchik_size': getattr(player, 'pisunchik_size', None)})
        return jsonify({'success': True, 'message': 'Database connection working', 'player_count': len(players), 'players': player_list[:5]})
    except Exception as e:
        logger.error(f"Database test error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    if not os.path.exists('logs'):
        os.makedirs('logs')
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
