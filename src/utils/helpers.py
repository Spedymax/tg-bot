"""Utility functions for the bot."""
import html
import logging
from typing import Optional, Tuple, List

logger = logging.getLogger(__name__)


def safe_split_callback(callback_data: str, delimiter: str = "_", expected_parts: int = 2) -> Optional[List[str]]:
    """
    Safely split callback_data and validate the number of parts.

    Args:
        callback_data: The callback data string to split
        delimiter: The delimiter to split on
        expected_parts: Minimum number of parts expected

    Returns:
        List of parts if valid, None if invalid
    """
    if not callback_data:
        return None

    parts = callback_data.split(delimiter)
    if len(parts) < expected_parts:
        logger.warning(f"Invalid callback_data format: {callback_data}, expected {expected_parts} parts")
        return None

    return parts


def safe_split_callback_maxsplit(callback_data: str, delimiter: str = "_",
                                  maxsplit: int = 1, expected_parts: int = 2) -> Optional[List[str]]:
    """
    Safely split callback_data with maxsplit and validate.

    Args:
        callback_data: The callback data string to split
        delimiter: The delimiter to split on
        maxsplit: Maximum number of splits
        expected_parts: Minimum number of parts expected

    Returns:
        List of parts if valid, None if invalid
    """
    if not callback_data:
        return None

    parts = callback_data.split(delimiter, maxsplit)
    if len(parts) < expected_parts:
        logger.warning(f"Invalid callback_data format: {callback_data}, expected {expected_parts} parts")
        return None

    return parts


def safe_int(value: str, default: int = 0) -> int:
    """
    Safely convert string to int.

    Args:
        value: String value to convert
        default: Default value if conversion fails

    Returns:
        Integer value or default
    """
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def escape_html(text: str) -> str:
    """
    Escape HTML special characters to prevent XSS.

    Args:
        text: Text to escape

    Returns:
        Escaped text safe for HTML
    """
    if not text:
        return ""
    return html.escape(str(text))


def safe_username(username: Optional[str], user_id: int) -> str:
    """
    Get safe username for display, escaping HTML.

    Args:
        username: Telegram username (may be None)
        user_id: User ID as fallback

    Returns:
        Safe string for display
    """
    if username:
        return escape_html(username)
    return f"user_{user_id}"


def parse_colon_separated(value: str, default_second: str = "0") -> Tuple[str, str]:
    """
    Safely parse colon-separated values like "name:level".

    Args:
        value: String in format "key:value"
        default_second: Default value for second part

    Returns:
        Tuple of (first_part, second_part)
    """
    if not value or ":" not in value:
        return (value or "", default_second)

    parts = value.split(":", 1)
    return (parts[0], parts[1] if len(parts) > 1 else default_second)
