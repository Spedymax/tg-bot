"""
Centralized Telegram API error handling service
"""

import logging
from typing import Callable, Any, Optional
from functools import wraps
import telebot
from telebot.apihelper import ApiTelegramException

logger = logging.getLogger(__name__)

class TelegramErrorHandler:
    """Centralized handler for Telegram API errors"""
    
    @staticmethod
    def handle_api_error(error: ApiTelegramException, user_id: Optional[int] = None, action: str = "send message") -> bool:
        """
        Handle Telegram API errors with proper logging and user management
        
        Args:
            error: The Telegram API exception
            user_id: User ID if available
            action: Description of the action being performed
            
        Returns:
            bool: True if error was handled gracefully, False if it should be re-raised
        """
        error_code = getattr(error, 'error_code', None)
        description = getattr(error, 'description', str(error))
        
        if error_code == 403:
            if "bot was blocked by the user" in description:
                logger.warning(f"User {user_id} has blocked the bot during {action}")
                return True
            elif "Forbidden: user is deactivated" in description:
                logger.warning(f"User {user_id} account is deactivated during {action}")
                return True
            elif "bot can't initiate conversation" in description:
                logger.warning(f"Cannot initiate conversation with user {user_id} during {action}")
                return True
        elif error_code == 400:
            if "chat not found" in description:
                logger.warning(f"Chat not found for user {user_id} during {action}")
                return True
            elif "message to delete not found" in description:
                logger.warning(f"Message to delete not found during {action}")
                return True
            elif "message is not modified" in description:
                logger.debug(f"Message not modified during {action}")
                return True
        elif error_code == 429:
            logger.warning(f"Rate limit exceeded during {action} - consider implementing backoff")
            return False  # Should be re-raised to implement retry logic
        elif error_code == 500:
            logger.error(f"Telegram server error during {action}: {description}")
            return False
        
        # Log unhandled errors
        logger.error(f"Unhandled Telegram API error {error_code} during {action}: {description}")
        return False

    @staticmethod
    def safe_send_message(bot: telebot.TeleBot, chat_id: int, text: str, **kwargs) -> bool:
        """
        Safely send a message with error handling
        
        Returns:
            bool: True if message was sent successfully, False otherwise
        """
        try:
            bot.send_message(chat_id, text, **kwargs)
            return True
        except ApiTelegramException as e:
            return TelegramErrorHandler.handle_api_error(e, chat_id, "send_message")
        except Exception as e:
            logger.error(f"Unexpected error sending message to {chat_id}: {e}")
            return False

    @staticmethod
    def safe_reply_to(bot: telebot.TeleBot, message, text: str, **kwargs) -> bool:
        """
        Safely reply to a message with error handling
        
        Returns:
            bool: True if reply was sent successfully, False otherwise
        """
        try:
            bot.reply_to(message, text, **kwargs)
            return True
        except ApiTelegramException as e:
            return TelegramErrorHandler.handle_api_error(e, message.from_user.id, "reply_to")
        except Exception as e:
            logger.error(f"Unexpected error replying to message from {message.from_user.id}: {e}")
            return False

    @staticmethod
    def safe_edit_message(bot: telebot.TeleBot, chat_id: int, message_id: int, text: str, **kwargs) -> bool:
        """
        Safely edit a message with error handling
        
        Returns:
            bool: True if message was edited successfully, False otherwise
        """
        try:
            bot.edit_message_text(text, chat_id, message_id, **kwargs)
            return True
        except ApiTelegramException as e:
            return TelegramErrorHandler.handle_api_error(e, chat_id, "edit_message")
        except Exception as e:
            logger.error(f"Unexpected error editing message {message_id} in chat {chat_id}: {e}")
            return False

    @staticmethod
    def safe_delete_message(bot: telebot.TeleBot, chat_id: int, message_id: int) -> bool:
        """
        Safely delete a message with error handling
        
        Returns:
            bool: True if message was deleted successfully, False otherwise
        """
        try:
            bot.delete_message(chat_id, message_id)
            return True
        except ApiTelegramException as e:
            return TelegramErrorHandler.handle_api_error(e, chat_id, "delete_message")
        except Exception as e:
            logger.error(f"Unexpected error deleting message {message_id} in chat {chat_id}: {e}")
            return False

def telegram_error_handler(action: str = "telegram_action"):
    """
    Decorator for handling Telegram API errors in bot handlers
    
    Usage:
        @telegram_error_handler("command_name")
        def my_handler(message):
            # handler code here
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            try:
                return func(*args, **kwargs)
            except ApiTelegramException as e:
                # Try to get user ID from message if available
                user_id = None
                if args and hasattr(args[0], 'from_user'):
                    user_id = args[0].from_user.id
                
                handled = TelegramErrorHandler.handle_api_error(e, user_id, action)
                if not handled:
                    raise
            except Exception as e:
                logger.error(f"Unexpected error in {action}: {e}")
                raise
        return wrapper
    return decorator