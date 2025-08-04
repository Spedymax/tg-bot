from flask import Flask, render_template, request, jsonify, send_from_directory
import os
import sys
import json
import logging
import random
from datetime import datetime, timedelta, timezone

# Add the parent directory to the Python path to import from the main bot
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the bot's database classes
try:
    from src.config.settings import Settings
    from src.database.db_manager import DatabaseManager
    from src.database.player_service import PlayerService
except ImportError as e:
    print(f"Warning: Could not import bot modules: {e}")
    print("Running in standalone mode without database integration")
    Settings = DatabaseManager = PlayerService = None

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize database connection if available
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

# Fallback store for player data when database is not available
player_data = {}

@app.route('/miniapp')
@app.route('/miniapp/')
def index():
    """Serve the main slot machine page"""
    logger.info(f"Serving slot_casino.html from {os.getcwd()}")
    return send_from_directory('.', 'slot_casino.html')

@app.route('/miniapp/slots')
def slots():
    """Alternative route for slot machine"""
    return send_from_directory('.', 'slot_casino.html')

@app.route('/miniapp/casino')
def casino():
    """Legacy route for casino (wheel version)"""
    return send_from_directory('.', 'casino.html')

@app.route('/miniapp/api/player/<int:player_id>')
def get_player_data(player_id):
    """Get player data for the mini-app"""
    try:
        if player_service:
            # Use actual database
            player = player_service.get_player(player_id)
            if not player:
                return jsonify({'success': False, 'error': 'Player not found'}), 404
            
            # Check if it's a new day and reset spins
            today = datetime.now(timezone.utc).date()
            last_spin_date = getattr(player, 'miniapp_last_spin_date', datetime.min.replace(tzinfo=timezone.utc)).date()
            
            if last_spin_date != today:
                player.miniapp_daily_spins = 0
                player.miniapp_last_spin_date = datetime.now(timezone.utc)
                player_service.save_player(player)
            
            max_daily_spins = 6
            spins_left = max(0, max_daily_spins - getattr(player, 'miniapp_daily_spins', 0))
            
            return jsonify({
                'success': True,
                'data': {
                    'coins': int(player.coins),
                    'spins_left': spins_left,
                    'daily_spins': getattr(player, 'miniapp_daily_spins', 0),
                    'max_daily_spins': max_daily_spins,
                    'total_winnings': getattr(player, 'miniapp_total_winnings', 0.0)
                }
            })
        else:
            # Fallback to in-memory store
            if player_id not in player_data:
                player_data[player_id] = {
                    'coins': 100,
                    'daily_spins': 0,
                    'last_spin_date': datetime.now().strftime('%Y-%m-%d'),
                    'max_daily_spins': 6
                }
            
            player = player_data[player_id]
            
            # Check if it's a new day and reset spins
            today = datetime.now().strftime('%Y-%m-%d')
            if player['last_spin_date'] != today:
                player['daily_spins'] = 0
                player['last_spin_date'] = today
            
            spins_left = max(0, player['max_daily_spins'] - player['daily_spins'])
            
            return jsonify({
                'success': True,
                'data': {
                    'coins': player['coins'],
                    'spins_left': spins_left,
                    'daily_spins': player['daily_spins'],
                    'max_daily_spins': player['max_daily_spins']
                }
            })
        
    except Exception as e:
        logger.error(f"Error getting player data: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/miniapp/api/spin', methods=['POST'])
def spin_wheel():
    """Handle wheel spin request"""
    try:
        data = request.json
        player_id = data.get('player_id')
        
        if not player_id:
            return jsonify({'success': False, 'error': 'Player ID required'}), 400
        
        if player_service:
            # Use actual database
            player = player_service.get_player(player_id)
            if not player:
                return jsonify({'success': False, 'error': 'Player not found'}), 404
            
            # Check if it's a new day and reset spins
            today = datetime.now(timezone.utc).date()
            last_spin_date = getattr(player, 'miniapp_last_spin_date', datetime.min.replace(tzinfo=timezone.utc)).date()
            
            if last_spin_date != today:
                player.miniapp_daily_spins = 0
                player.miniapp_last_spin_date = datetime.now(timezone.utc)
            
            max_daily_spins = 6
            current_spins = getattr(player, 'miniapp_daily_spins', 0)
            
            # Check if player has spins left
            if current_spins >= max_daily_spins:
                return jsonify({
                    'success': False, 
                    'error': 'No spins left for today'
                }), 400
            
            # Improved winning logic with multiple prize tiers and better odds
            rand_value = random.random()
            
            # Better winning chances - total 25% chance to win something
            if rand_value < 0.03:  # 3% chance for jackpot
                selected_prize = {
                    'text': '🎰 МЕГА ДЖЕКПОТ! ЕБААААТЬ!🎰',
                    'type': 'jackpot', 
                    'value': 500
                }
            elif rand_value < 0.08:  # 5% chance for big win
                selected_prize = {
                    'text': '🎉 БОЛЬШОЙ ВЫИГРЫШ!🎉',
                    'type': 'big_win', 
                    'value': 300
                }
            elif rand_value < 0.15:  # 7% chance for medium win
                selected_prize = {
                    'text': '✨ Хороший выигрыш! ✨', 
                    'type': 'medium_win', 
                    'value': 150
                }
            elif rand_value < 0.25:  # 10% chance for small win
                selected_prize = {
                    'text': '💰 Небольшой выигрыш! 💰', 
                    'type': 'small_win', 
                    'value': 50
                }
            else:  # 75% chance for no win
                selected_prize = {
                    'text': 'Попробуйте ещё раз! 🎲', 
                    'type': 'lose', 
                    'value': 0
                }
            
            # Apply the prize
            original_coins = player.coins
            coins_gained = 0
            
            if selected_prize['type'] != 'lose':
                player.coins += selected_prize['value']
                coins_gained = selected_prize['value']
                player.miniapp_total_winnings = getattr(player, 'miniapp_total_winnings', 0.0) + selected_prize['value']
            
            # Increment spin count
            player.miniapp_daily_spins = current_spins + 1
            player.miniapp_last_spin_date = datetime.now(timezone.utc)
            
            # Save player to database
            player_service.save_player(player)
            
            # Calculate spins left
            spins_left = max(0, max_daily_spins - player.miniapp_daily_spins)
            
            return jsonify({
                'success': True,
                'data': {
                    'prize': selected_prize,
                    'coins': int(player.coins),
                    'coins_gained': coins_gained,
                    'spins_left': spins_left,
                    'daily_spins': player.miniapp_daily_spins,
                    'total_winnings': player.miniapp_total_winnings
                }
            })
        else:
            # Fallback to in-memory store
            if player_id not in player_data:
                return jsonify({'success': False, 'error': 'Player not found'}), 404
            
            player = player_data[player_id]
            
            # Check if it's a new day
            today = datetime.now().strftime('%Y-%m-%d')
            if player['last_spin_date'] != today:
                player['daily_spins'] = 0
                player['last_spin_date'] = today
            
            # Check if player has spins left
            if player['daily_spins'] >= player['max_daily_spins']:
                return jsonify({
                    'success': False, 
                    'error': 'No spins left for today'
                }), 400
            
            # Improved winning logic for fallback mode too
            rand_value = random.random()
            
            if rand_value < 0.03:  # 3% jackpot
                selected_prize = {
                    'text': '🎰 МЕГА ДЖЕКПОТ! 🎰', 
                    'type': 'jackpot', 
                    'value': 500
                }
            elif rand_value < 0.08:  # 5% big win
                selected_prize = {
                    'text': '🎉 БОЛЬШОЙ ВЫИГРЫШ! 🎉', 
                    'type': 'big_win', 
                    'value': 300
                }
            elif rand_value < 0.15:  # 7% medium win
                selected_prize = {
                    'text': '✨ Хороший выигрыш! ✨', 
                    'type': 'medium_win', 
                    'value': 150
                }
            elif rand_value < 0.25:  # 10% small win
                selected_prize = {
                    'text': '💰 Небольшой выигрыш! 💰', 
                    'type': 'small_win', 
                    'value': 50
                }
            else:
                selected_prize = {
                    'text': 'Попробуйте ещё раз! 🎲', 
                    'type': 'lose', 
                    'value': 0
                }
            
            # Apply the prize
            original_coins = player['coins']
            if selected_prize['type'] != 'lose':
                player['coins'] += selected_prize['value']
            
            # Increment spin count
            player['daily_spins'] += 1
            
            # Calculate spins left
            spins_left = max(0, player['max_daily_spins'] - player['daily_spins'])
            
            return jsonify({
                'success': True,
                'data': {
                    'prize': selected_prize,
                    'coins': player['coins'],
                    'coins_gained': player['coins'] - original_coins,
                    'spins_left': spins_left,
                    'daily_spins': player['daily_spins']
                }
            })
        
    except Exception as e:
        logger.error(f"Error processing spin: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/miniapp/api/save_progress', methods=['POST'])
def save_progress():
    """Save player progress back to main bot database"""
    try:
        data = request.json
        player_id = data.get('player_id')
        coins = data.get('coins')
        spins_used = data.get('spins_used', 0)
        
        if not player_id:
            return jsonify({'success': False, 'error': 'Player ID required'}), 400
        
        # Here you would save to your main bot's database
        # For now, we'll just update our local store
        if player_id in player_data:
            player_data[player_id]['coins'] = coins
            player_data[player_id]['daily_spins'] = spins_used
        
        logger.info(f"Saved progress for player {player_id}: {coins} coins, {spins_used} spins used")
        
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"Error saving progress: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/miniapp/dog.jpg')
def serve_dog_image():
    """Serve the dog image"""
    try:
        return send_from_directory('.', 'dog.jpg')
    except FileNotFoundError:
        # Return 404 if dog.jpg doesn't exist
        return '', 404

@app.route('/miniapp/audio/<path:filename>')
def serve_audio_files(filename):
    """Serve audio files from the audio directory"""
    # Only serve audio file types for security
    allowed_extensions = ['.mp3', '.ogg', '.wav', '.m4a']
    if any(filename.lower().endswith(ext) for ext in allowed_extensions):
        try:
            return send_from_directory('audio', filename)
        except FileNotFoundError:
            return '', 404
    return '', 404

@app.route('/miniapp/<path:filename>')
def serve_static_files(filename):
    """Serve static files like images, CSS, JS"""
    # Only serve certain file types for security
    allowed_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.css', '.js', '.ico']
    if any(filename.lower().endswith(ext) for ext in allowed_extensions):
        try:
            return send_from_directory('.', filename)
        except FileNotFoundError:
            return '', 404
    return '', 404

@app.route('/miniapp/health')
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'active_players': len(player_data)
    })

@app.route('/miniapp/debug')
def debug_info():
    """Debug information"""
    import os
    return jsonify({
        'working_directory': os.getcwd(),
        'files_in_directory': os.listdir('.'),
        'slot_casino_exists': os.path.exists('slot_casino.html'),
        'audio_directory_exists': os.path.exists('audio'),
        'routes': [str(rule) for rule in app.url_map.iter_rules()]
    })

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    # Create logs directory if it doesn't exist
    if not os.path.exists('logs'):
        os.makedirs('logs')
    
    # Run the app
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True,
        use_reloader=False  # Disable reloader to prevent issues with threading
    )
