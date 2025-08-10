from flask import Flask, render_template, request, jsonify, send_from_directory
import os
import sys
import json
import logging
import random
from datetime import datetime, timezone
from decimal import Decimal

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src_dir = os.path.join(parent_dir, 'src')
sys.path.insert(0, parent_dir)
sys.path.insert(0, src_dir)

try:
    from config.settings import Settings
    from database.db_manager import DatabaseManager
    from database.player_service import PlayerService
except ImportError as e:
    Settings = DatabaseManager = PlayerService = None

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

@app.route('/miniapp/api/player/<int:player_id>')
def get_player_data(player_id):
    logger.info(f"Getting player data for player_id: {player_id}")
    if player_service:
        try:
            player = player_service.get_player(player_id)
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
                player_service.save_player(player)
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
                player = player_service.get_player(player_id)
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
                player_service.save_player(player)
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
                player = player_service.get_player(player_id)
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
            player_service.save_player(player)
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
                player = player_service.get_player(player_id)
            except Exception as e:
                logger.error(f"DB error in refresh for {player_id}: {e}")
                return jsonify({'success': False, 'error': 'Database error'}), 500
            if not player:
                return jsonify({'success': False, 'error': 'Player not found'}), 404
            player.miniapp_daily_spins = 0
            player.miniapp_last_spin_date = datetime.now(timezone.utc)
            player_service.save_player(player)
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
        players = player_service.get_all_players()
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
