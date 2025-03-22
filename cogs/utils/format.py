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
    """Format large numbers with K, M, B suffixes
    
    Rules:
    - Thousands (K): No decimal places ($677K instead of $677.41K)
    - Millions (M): One decimal place ($2.1M)
    - Billions (B): One decimal place ($2.5B)
    """
    try:
        num = float(str(number).replace(',', ''))
    except (ValueError, TypeError):
        return "0"

    if num == 0:
        return "0"

    abs_num = abs(num)
    
    if abs_num >= 1_000_000_000:  # Billions
        formatted = f"{num / 1_000_000_000:.1f}B"
    elif abs_num >= 1_000_000:     # Millions
        formatted = f"{num / 1_000_000:.1f}M"
    elif abs_num >= 1_000:         # Thousands
        formatted = f"{int(num / 1_000)}K"  # No decimal places for thousands
    else:
        formatted = f"{int(num)}"  # Regular numbers
        
    # Remove .0 if it exists
    return formatted.replace('.0', '')

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

def format_token_header(name: str, url: str) -> str:
    """Format token name and URL as a Discord header with link"""
    # Use bold for field values since ### only works in embed description
    return f"**[{name}]({url})**"