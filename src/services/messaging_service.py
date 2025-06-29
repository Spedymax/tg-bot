import logging
import telebot
from typing import Optional

logger = logging.getLogger(__name__)


class MessagingService:
    """Service for handling message sending to different groups."""
    
    def __init__(self, chat_ids: dict):
        """Initialize with chat IDs configuration."""
        self.chat_ids = chat_ids
    
    def send_message_to_group(self, bot: telebot.TeleBot, message: str, 
                             parse_mode: str = 'HTML') -> bool:
        """Send message to main group chat."""
        try:
            bot.send_message(
                self.chat_ids.get('main'), 
                message, 
                parse_mode=parse_mode
            )
            return True
        except Exception as e:
            logger.error(f"Error sending message to main group: {str(e)}")
            return False
    
    def send_message_to_group2(self, bot: telebot.TeleBot, message: str, 
                              parse_mode: str = 'HTML') -> bool:
        """Send message to secondary group chat."""
        try:
            bot.send_message(
                self.chat_ids.get('secondary'), 
                message, 
                parse_mode=parse_mode
            )
            return True
        except Exception as e:
            logger.error(f"Error sending message to secondary group: {str(e)}")
            return False
    
    def send_message_to_chat(self, bot: telebot.TeleBot, chat_id: int, 
                           message: str, parse_mode: str = 'HTML') -> bool:
        """Send message to a specific chat."""
        try:
            bot.send_message(chat_id, message, parse_mode=parse_mode)
            return True
        except Exception as e:
            logger.error(f"Error sending message to chat {chat_id}: {str(e)}")
            return False
    
    def broadcast_message(self, bot: telebot.TeleBot, message: str, 
                         chat_ids: list, parse_mode: str = 'HTML') -> dict:
        """Broadcast message to multiple chats."""
        results = {}
        for chat_id in chat_ids:
            results[chat_id] = self.send_message_to_chat(bot, chat_id, message, parse_mode)
        return results
