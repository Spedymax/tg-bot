import threading
import time
import json
import random
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class EventService:
    """Service for managing special events like NoNutNovember."""
    
    def __init__(self):
        self.motivational_messages = self._load_motivations()
        self.memes = self._load_memes()
        self.user_checkins = {}
        
    def _load_motivations(self) -> List[str]:
        """Load motivational messages from JSON file."""
        try:
            with open('data/motivational_messages.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning("Motivational messages file not found, using defaults")
            return [
                "Держись, боец! Ты сильнее своих желаний!",
                "Каждый день без срыва - это победа!",
                "Твоя сила воли растет с каждым днем!",
                "Помни: цель стоит любых усилий!",
                "Ты уже прошел столько - не сдавайся сейчас!"
            ]
        except Exception as e:
            logger.error(f"Error loading motivational messages: {str(e)}")
            return ["Stay strong!"]
    
    def _load_memes(self) -> List[str]:
        """Load meme URLs from JSON file."""
        try:
            with open('data/memes.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning("Memes file not found, using defaults")
            return [
                "https://i.imgur.com/dQw4w9W.jpg",  # Sample meme URL
                "https://i.imgur.com/example.jpg"
            ]
        except Exception as e:
            logger.error(f"Error loading memes: {str(e)}")
            return ["https://i.imgur.com/default.jpg"]
    
    def schedule_daily_checkin(self, bot, chat_id: int):
        """Schedule daily check-in for NoNutNovember."""
        def run():
            while True:
                now = datetime.now()
                if now.month == 11:  # November only
                    next_run = now.replace(hour=11, minute=0, second=0, microsecond=0)
                    if now >= next_run:
                        next_run += timedelta(days=1)
                    
                    time_to_wait = (next_run - now).total_seconds()
                    time.sleep(time_to_wait)
                    
                    self.send_daily_checkin(bot, chat_id)
                else:
                    # If not November, sleep for a day and check again
                    time.sleep(24 * 60 * 60)
        
        threading.Thread(target=run, daemon=True).start()
    
    def send_daily_checkin(self, bot, chat_id: int):
        """Send daily check-in message with button."""
        from telebot import types
        
        keyboard = types.InlineKeyboardMarkup()
        checkin_button = types.InlineKeyboardButton("Check In ✅", callback_data='nnn_checkin')
        keyboard.add(checkin_button)
        
        bot.send_message(
            chat_id=chat_id,
            text="🕛 БОЙЦЫ! Проверка на сперму в яйцах!",
            reply_markup=keyboard
        )
    
    def handle_checkin_callback(self, user_id: str, username: str, 
                              player_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle user check-in callback.
        Returns: {"success": bool, "message": str, "meme": str}
        """
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            
            # Initialize check-ins if not present
            if 'nnn_checkins' not in player_data or player_data['nnn_checkins'] is None:
                player_data['nnn_checkins'] = []
            
            # Record the check-in if not already done today
            if today not in player_data['nnn_checkins']:
                player_data['nnn_checkins'].append(today)
                
                return {
                    "success": True,
                    "message": random.choice(self.motivational_messages),
                    "meme": random.choice(self.memes),
                    "callback_answer": "Check-in successful!"
                }
            else:
                return {
                    "success": False,
                    "message": "Вы уже отметились сегодня!",
                    "meme": None,
                    "callback_answer": "Already checked in today!"
                }
                
        except Exception as e:
            logger.error(f"Error handling checkin callback: {str(e)}")
            return {
                "success": False,
                "message": "Ошибка при регистрации",
                "meme": None,
                "callback_answer": "Error occurred"
            }
    
    def get_motivation(self) -> Dict[str, str]:
        """Get random motivational message and meme."""
        return {
            "message": random.choice(self.motivational_messages),
            "meme": random.choice(self.memes)
        }
    
    def get_leaderboard(self, player_data: Dict[str, Dict[str, Any]]) -> str:
        """Generate NoNutNovember leaderboard."""
        leaderboard_text = "🏆 *NNN Leaderboard:*\n"
        
        # Collect users with check-ins
        user_checkins = []
        for user_id, data in player_data.items():
            if 'nnn_checkins' in data and data['nnn_checkins']:
                checkin_count = len(data['nnn_checkins'])
                username = data.get('player_name', 'User')
                user_checkins.append((username, checkin_count))
        
        # Sort by check-in count (descending)
        user_checkins.sort(key=lambda x: x[1], reverse=True)
        
        # Format leaderboard
        for i, (username, count) in enumerate(user_checkins, 1):
            emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🔸"
            leaderboard_text += f"{emoji} {username}: {count} check-ins\n"
        
        if not user_checkins:
            leaderboard_text += "Пока никто не участвует в челлендже!"
        
        return leaderboard_text
    
    def is_november(self) -> bool:
        """Check if current month is November."""
        return datetime.now().month == 11
    
    def get_checkin_status(self, player_data: Dict[str, Any]) -> Dict[str, Any]:
        """Get player's check-in status for current month."""
        if 'nnn_checkins' not in player_data:
            return {"total_checkins": 0, "checked_in_today": False}
        
        today = datetime.now().strftime('%Y-%m-%d')
        checkins = player_data['nnn_checkins'] or []
        
        return {
            "total_checkins": len(checkins),
            "checked_in_today": today in checkins,
            "checkin_dates": checkins
        }
