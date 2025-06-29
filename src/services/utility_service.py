import time
import logging
import subprocess
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Any
from subprocess import Popen, PIPE

logger = logging.getLogger(__name__)


class UtilityService:
    """Service for utility functions like casino, online monitoring, etc."""
    
    def __init__(self, config=None):
        self.config = config
        self.max_usage_per_day = 5
        self.online_process = None
        
    def kazik(self, player_id: str, player_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Casino function - slot machine game with daily limits.
        Returns: {"success": bool, "message": str, "coins_won": int}
        """
        try:
            current_time = datetime.now(timezone.utc)
            last_usage_time = player_data.get('casino_last_used')
            
            # Check daily limit
            if last_usage_time is not None:
                time_elapsed = current_time - last_usage_time
                
                if (time_elapsed < timedelta(hours=24) and 
                    player_data.get('casino_usage_count', 0) >= self.max_usage_per_day):
                    time_remaining = timedelta(days=1) - time_elapsed
                    return {
                        "success": False,
                        "message": f"Вы достигли лимита использования команды на сегодня.\nВремени осталось: {time_remaining}",
                        "coins_won": 0
                    }
                elif time_elapsed >= timedelta(hours=24):
                    player_data['casino_usage_count'] = 0
            else:
                player_data['casino_last_used'] = current_time
                player_data['casino_usage_count'] = 0
            
            # Update usage
            player_data['casino_last_used'] = current_time
            player_data['casino_usage_count'] = player_data.get('casino_usage_count', 0) + 1
            
            return {
                "success": True,
                "message": "Casino game executed",
                "coins_won": 0  # Will be determined by dice roll in handler
            }
            
        except Exception as e:
            logger.error(f"Error in kazik: {str(e)}")
            return {
                "success": False,
                "message": "Ошибка в казино",
                "coins_won": 0
            }
    
    def start_online_monitoring(self) -> Dict[str, Any]:
        """Start online monitoring script."""
        try:
            if self.online_process is None or self.online_process.poll() is not None:
                self.online_process = Popen(
                    ['python', 'src/legacy/checkOnline.py'], 
                    stdout=PIPE, 
                    stderr=PIPE
                )
                return {"success": True, "message": "Online monitoring started"}
            else:
                return {"success": False, "message": "Online monitoring is already running"}
        except Exception as e:
            logger.error(f"Error starting online monitoring: {str(e)}")
            return {"success": False, "message": f"Error: {str(e)}"}
    
    def stop_online_monitoring(self) -> Dict[str, Any]:
        """Stop online monitoring script."""
        try:
            if self.online_process is not None and self.online_process.poll() is None:
                self.online_process.terminate()
                try:
                    self.online_process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.online_process.kill()
                return {"success": True, "message": "Online monitoring stopped"}
            else:
                return {"success": False, "message": "Online monitoring is not running"}
        except Exception as e:
            logger.error(f"Error stopping online monitoring: {str(e)}")
            return {"success": False, "message": f"Error: {str(e)}"}
    
    def calculate_jackpot(self, dice_value: int) -> int:
        """Calculate jackpot winnings based on dice value."""
        jackpot_values = {1, 22, 43, 64}
        if dice_value in jackpot_values:
            return 300
        return 0


class OnlineMonitoringService:
    """Service for monitoring user online status using Telethon."""
    
    def __init__(self, api_id: int, api_hash: str):
        self.api_id = api_id
        self.api_hash = api_hash
        self.client = None
        self.is_running = False
        
    async def initialize_client(self):
        """Initialize Telethon client."""
        try:
            from telethon import TelegramClient
            self.client = TelegramClient('session', self.api_id, self.api_hash)
            await self.client.start()
            return True
        except Exception as e:
            logger.error(f"Error initializing Telethon client: {str(e)}")
            return False
    
    async def monitor_user_status(self, username: str, callback_function=None):
        """Monitor specific user's online status."""
        if not self.client:
            if not await self.initialize_client():
                return False
        
        try:
            from telethon.tl.types import UserStatusOnline
            
            while self.is_running:
                user = await self.client.get_entity(username)
                
                if isinstance(user.status, UserStatusOnline):
                    if callback_function:
                        await callback_function(user)
                    else:
                        await self.client.send_message('me', 'Надо наругать девушку!')
                    
                    await asyncio.sleep(4 * 60)  # Wait 4 minutes
                
                await asyncio.sleep(60)  # Check every minute
                
        except Exception as e:
            logger.error(f"Error monitoring user status: {str(e)}")
            return False
    
    def start_monitoring(self, username: str):
        """Start monitoring in background."""
        self.is_running = True
        asyncio.create_task(self.monitor_user_status(username))
    
    def stop_monitoring(self):
        """Stop monitoring."""
        self.is_running = False
