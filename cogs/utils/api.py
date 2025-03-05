import aiohttp
import logging
from typing import Optional, AsyncGenerator
from cogs.utils.constants import BotConstants

async def safe_api_call(
    session: aiohttp.ClientSession, 
    url: str, 
    timeout: int = BotConstants.DEFAULT_TIMEOUT
) -> AsyncGenerator[Optional[dict], None]:
    """
    Safely make an API call with error handling and timeout.
    
    Args:
        session: aiohttp ClientSession to use for the request
        url: The URL to call
        timeout: Timeout in seconds
        
    Yields:
        The JSON response if successful, None if failed
    """
    try:
        async with session.get(url, timeout=timeout) as response:
            if response.status == 200:
                data = await response.json()
                yield data
            else:
                logging.warning(f"API call failed with status {response.status}: {url}")
                yield None
    except aiohttp.ClientError as e:
        logging.error(f"API request error for {url}: {str(e)}")
        yield None
    except Exception as e:
        logging.error(f"Unexpected error in API call to {url}: {str(e)}")
        yield None

class DexScreenerAPI:
    """Wrapper for DexScreener API calls"""
    BASE_URL = "https://api.dexscreener.com/latest/dex"
    
    @staticmethod
    async def get_token_info(session: aiohttp.ClientSession, contract: str) -> Optional[dict]:
        """Get token information from DexScreener"""
        url = f"{DexScreenerAPI.BASE_URL}/tokens/{contract}"
        async with safe_api_call(session, url) as data:
            return data

class HyperliquidAPI:
    """Wrapper for Hyperliquid API calls"""
    BASE_URL = "https://api.hyperliquid.xyz"
    
    @staticmethod
    async def get_asset_info(session: aiohttp.ClientSession) -> Optional[dict]:
        """Get asset information from Hyperliquid"""
        url = f"{HyperliquidAPI.BASE_URL}/info"
        async with safe_api_call(session, url) as data:
            return data

    @staticmethod
    async def get_user_fills(session: aiohttp.ClientSession, address: str) -> Optional[dict]:
        """Get user trade fills from Hyperliquid"""
        url = f"{HyperliquidAPI.BASE_URL}/fills/{address}"
        async with safe_api_call(session, url) as data:
            return data

    @staticmethod
    async def get_user_state(session: aiohttp.ClientSession, address: str) -> Optional[dict]:
        """Get user state (positions) from Hyperliquid"""
        url = f"{HyperliquidAPI.BASE_URL}/user/{address}"
        async with safe_api_call(session, url) as data:
            return data