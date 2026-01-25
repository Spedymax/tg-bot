"""
Utility functions for safe Telegram bot operations
"""

import logging
from functools import wraps
from telebot.apihelper import ApiTelegramException

logger = logging.getLogger(__name__)

def safe_bot_action(action_name: str = "bot_action"):
    """
    Simple decorator for safe bot actions with minimal dependencies
    
    Usage:
        @safe_bot_action("send_message")
        def my_function():
            bot.send_message(chat_id, text)
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except ApiTelegramException as e:
                error_code = getattr(e, 'error_code', None)
                description = getattr(e, 'description', str(e))
                
                # Handle common blocking errors silently
                if error_code == 403 and any(phrase in description for phrase in [
                    "bot was blocked by the user",
                    "user is deactivated", 
                    "bot can't initiate conversation"
                ]):
                    logger.warning(f"User blocked bot during {action_name}: {description}")
                    return False
                elif error_code == 400 and "chat not found" in description:
                    logger.warning(f"Chat not found during {action_name}")
                    return False
                else:
                    logger.error(f"Telegram API error in {action_name}: {error_code} - {description}")
                    raise
            except Exception as e:
                logger.error(f"Unexpected error in {action_name}: {e}")
                raise
        return wrapper
    return decorator

def safe_send_message(bot, chat_id, text, **kwargs):
    """Safely send message with error handling"""
    try:
        return bot.send_message(chat_id, text, **kwargs)
    except ApiTelegramException as e:
        error_code = getattr(e, 'error_code', None)
        description = getattr(e, 'description', str(e))
        
        if error_code == 403 and "bot was blocked by the user" in description:
            logger.warning(f"User {chat_id} has blocked the bot")
            return None
        else:
            logger.error(f"Failed to send message to {chat_id}: {description}")
            raise
    except Exception as e:
        logger.error(f"Unexpected error sending message to {chat_id}: {e}")
        raise

def safe_reply_to(bot, message, text, **kwargs):
    """Safely reply to message with error handling"""  
    try:
        return bot.reply_to(message, text, **kwargs)
    except ApiTelegramException as e:
        error_code = getattr(e, 'error_code', None)
        description = getattr(e, 'description', str(e))
        
        if error_code == 403 and "bot was blocked by the user" in description:
            logger.warning(f"User {message.from_user.id} has blocked the bot")
            return None
        else:
            logger.error(f"Failed to reply to message from {message.from_user.id}: {description}")
            raise
    except Exception as e:
        logger.error(f"Unexpected error replying to message from {message.from_user.id}: {e}")
        raise