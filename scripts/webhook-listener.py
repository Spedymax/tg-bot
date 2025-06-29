from flask import Flask, request
import git
import subprocess
import time
from threading import Thread
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('webhook.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

def restart_service(service_name):
    """Restart a systemd service"""
    try:
        result = subprocess.run(['sudo', 'systemctl', 'restart', service_name], 
                              capture_output=True, text=True, check=True)
        logger.info(f"Successfully restarted {service_name}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to restart {service_name}: {e}")
        return False

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    """Handle general webhook for the main bot"""
    logger.info("Received webhook request for main bot")
    if request.method == 'POST':
        repo_path = '/home/spedymax/tg-bot'
        try:
            repo = git.Repo(repo_path)
            logger.info("Executing git pull with rebase...")
            try:
                repo.git.pull('--rebase')
            except git.GitCommandError as e:
                if 'unable to update local ref' in str(e):
                    logger.warning("Detected refs conflict. Resetting local changes...")
                    repo.git.fetch('--all')
                    repo.git.reset('--hard', 'origin/main')
                    logger.info("Local changes reset. Update completed.")
                else:
                    raise e

            logger.info("Repository updated successfully. Restarting main bot...")
            # Restart the main bot service
            if restart_service('btc_bot.service'):
                return 'Repository updated and main bot restarted.', 200
            else:
                return 'Repository updated but failed to restart main bot.', 500
                
        except Exception as e:
            logger.error(f"Error updating repository: {e}")
            return f"Error updating repository: {e}", 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return {'status': 'healthy', 'timestamp': time.time()}, 200

if __name__ == '__main__':
    logger.info("Starting webhook listener on port 5000...")
    app.run(host='0.0.0.0', port=5000, debug=False)
