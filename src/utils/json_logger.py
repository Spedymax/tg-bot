import json
import logging
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """JSON structured log formatter for file output."""

    def format(self, record):
        log_entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        # Add correlation context if available
        if hasattr(record, 'user_id'):
            log_entry['user_id'] = record.user_id
        if hasattr(record, 'command'):
            log_entry['command'] = record.command
        if hasattr(record, 'chat_id'):
            log_entry['chat_id'] = record.chat_id

        # Add exception info
        if record.exc_info and record.exc_info[0]:
            log_entry['exception'] = self.formatException(record.exc_info)

        return json.dumps(log_entry, ensure_ascii=False)
