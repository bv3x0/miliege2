# This file makes the utils directory a proper Python package 

from datetime import datetime
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional
import aiohttp
import asyncio

# Import color constants from colors.py
from .colors import EMBED_BORDER, LONG_COLOR, SHORT_COLOR

# Import formatting functions from formatting.py
from .formatting import (
    format_large_number,
    format_percentage,
    get_age_string,
    format_buy_amount
)

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