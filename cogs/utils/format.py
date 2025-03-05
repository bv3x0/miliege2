from typing import Union, Final
from datetime import datetime
import logging

# Color constants for embeds
class Colors:
    """Color constants for embeds"""
    EMBED_BORDER: Final = 0x5b594f
    LONG_COLOR: Final = 0x00ff00
    SHORT_COLOR: Final = 0xff0000

# Bot constants
class BotConstants:
    """General bot constants"""
    MAX_TOKENS: Final = 1000
    CACHE_TIMEOUT: Final = 3600
    DEFAULT_API_TIMEOUT: Final = 30
    DEFAULT_RATE_LIMIT: Final = 1.0
    MAX_ERRORS: Final = 50
    UPDATE_INTERVAL: Final = 300  # 5 minutes

class Messages:
    """Standard messages used by the bot"""
    ERROR_GENERIC: Final = "❌ An unexpected error occurred"
    NO_RESULTS: Final = "<:dwbb:1321571679109124126>"
    SUCCESS: Final = "✅"

def format_large_number(number: Union[int, float, str]) -> str:
    """Format large numbers with K, M, B suffixes"""
    try:
        num = float(str(number).replace(',', ''))
    except (ValueError, TypeError):
        return "0"

    if num == 0:
        return "0"

    magnitude = 0
    while abs(num) >= 1000:
        magnitude += 1
        num /= 1000.0

    # Always use exactly 1 decimal place
    formatted = f"{num:.1f}".rstrip('0').rstrip('.')
    return f"{formatted}{'KMB'[magnitude-1] if magnitude > 0 else ''}"

def format_currency(amount: Union[str, float]) -> str:
    """Format currency with appropriate precision"""
    try:
        clean_amount = str(amount).replace('$', '').replace(',', '')
        num = float(clean_amount)
    except (ValueError, TypeError):
        return "$0"

    if num >= 1000000:
        return f"${format_large_number(num)}"
    elif num >= 1:
        return f"${num:,.2f}"
    else:
        return f"${num:.4f}"

def format_percent(value: Union[float, str]) -> str:
    """Format percentage with appropriate precision"""
    try:
        num = float(str(value).replace(',', ''))
    except (ValueError, TypeError):
        return "0%"

    if abs(num) >= 100:
        return f"{round(num)}%"
    elif abs(num) >= 10:
        return f"{num:.1f}%"
    else:
        return f"{num:.2f}%"

def format_age(timestamp) -> str:
    """Format timestamp as human-readable age"""
    if not timestamp:
        return None

    try:
        if isinstance(timestamp, (int, str)):
            timestamp = datetime.fromtimestamp(int(timestamp) / 1000)

        diff = datetime.now() - timestamp
        days = diff.days
        hours = diff.seconds // 3600
        minutes = (diff.seconds % 3600) // 60

        if days > 0:
            return f"{days}d"
        elif hours > 0:
            return f"{hours}h"
        else:
            return f"{minutes}m"
    except Exception as e:
        logging.error(f"Error calculating age: {e}")
        return None