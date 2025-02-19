from datetime import datetime
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional
import aiohttp
import asyncio

def format_large_number(number):
    """Format a large number as a human-readable string (e.g., 32.3M, 32.5K)."""
    if number >= 1_000_000_000:
        return f"{number / 1_000_000_000:.1f}B"
    elif number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    elif number >= 1_000:
        return f"{number / 1_000:.1f}K"
    else:
        return str(number)

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
            return f"{minutes} minute{'s' if minutes != 1 else ''} old"
    except Exception as e:
        logging.error(f"Error calculating age: {e}")
        return None

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