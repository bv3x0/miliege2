from datetime import datetime
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional
import aiohttp
import asyncio
from utils import EMBED_BORDER

# Color constants for consistent use across the bot
EMBED_BORDER = 0x5b594f  # Gray color used for all alert borders
LONG_COLOR = 0x00FF00    # Green (reference only)
SHORT_COLOR = 0xFF0000   # Red (reference only)

def format_large_number(number):
    """Format a large number as a human-readable string (e.g., 32.3m, 32k)."""
    if number >= 1_000_000_000:
        return f"{number / 1_000_000_000:.1f}b"
    elif number >= 1_000_000:
        return f"{number / 1_000_000:.1f}m"
    elif number >= 1_000:
        return f"{int(round(number / 1_000))}k"  # Round to nearest thousand, no decimal
    else:
        return str(int(number))

def format_percentage(value):
    return f"{value}%" if isinstance(value, (int, float)) else value

def get_age_string(created_at):
    """Convert timestamp to human readable age string"""
    if not created_at:
        return None

    try:
        # Convert timestamp to datetime if it's not already
        if isinstance(created_at, (int, str)):
            created_at = datetime.fromtimestamp(int(created_at) / 1000)

        now = datetime.now()
        diff = now - created_at

        days = diff.days
        hours = diff.seconds // 3600
        minutes = (diff.seconds % 3600) // 60

        if days > 0:
            return f"{days} day{'s' if days != 1 else ''} old"
        elif hours > 0:
            return f"{hours} hour{'s' if hours != 1 else ''} old"
        else:
            return f"{minutes} min old"
    except Exception as e:
        logging.error(f"Error calculating age: {e}")
        return None

def format_buy_amount(amount):
    """Format a buy amount according to specific rules:
    - Under $250: '<$250'
    - $250-$1999: '<$2k'
    - $2000+: Round to nearest thousand with 'k' suffix
    """
    try:
        # Convert string to float if needed
        if isinstance(amount, str):
            # Remove commas and dollar sign if present
            amount = float(amount.replace(',', '').replace('$', ''))
        
        if amount < 250:
            return "<$250"
        elif amount < 2000:
            return "<$2k"
        else:
            # Round to nearest thousand
            rounded = round(amount / 1000)
            return f"${rounded}k"
    except (ValueError, TypeError):
        return str(amount)  # Return original value if conversion fails

@asynccontextmanager
async def safe_api_call(session: aiohttp.ClientSession, url: str, timeout: int = 10) -> AsyncGenerator[Optional[dict], None]:
    """Safe context manager for API calls with proper error handling"""
    try:
        async with session.get(url, timeout=timeout) as response:
            if response.status == 200:
                yield await response.json()
            else:
                logging.error(f"API error: {response.status} for {url}")
                yield None
    except asyncio.TimeoutError:
        logging.error(f"Timeout accessing {url}")
        yield None
    except Exception as e:
        logging.error(f"Error accessing {url}: {e}")
        yield None