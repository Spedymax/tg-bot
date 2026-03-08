import logging
import time
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

from services.metrics import metrics

logger = logging.getLogger(__name__)


class LoggingMiddleware(BaseMiddleware):
    """Middleware that logs every incoming update with user/command context."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        start = time.time()

        # Extract context
        user_id = None
        command = None
        chat_id = None

        if isinstance(event, Message):
            user_id = event.from_user.id if event.from_user else None
            chat_id = event.chat.id
            if event.text and event.text.startswith('/'):
                command = event.text.split()[0].split('@')[0]
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id if event.from_user else None
            chat_id = event.message.chat.id if event.message else None
            command = f"callback:{event.data[:30] if event.data else 'unknown'}"

        # Log the incoming request
        extra = {}
        if user_id:
            extra['user_id'] = user_id
        if command:
            extra['command'] = command
        if chat_id:
            extra['chat_id'] = chat_id

        logger.info(f"→ {command or 'update'}", extra=extra)

        try:
            result = await handler(event, data)
            elapsed = (time.time() - start) * 1000
            logger.info(f"← {command or 'update'} [{elapsed:.0f}ms]", extra=extra)
            metrics.record_command(command or 'unknown', user_id or 0, elapsed, error=False)
            return result
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            logger.error(f"✗ {command or 'update'} [{elapsed:.0f}ms]: {e}", extra=extra)
            metrics.record_command(command or 'unknown', user_id or 0, elapsed, error=True)
            raise
