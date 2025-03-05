import aiohttp
import logging
from typing import Optional
from .config import settings

async def safe_api_call(
    session: aiohttp.ClientSession, 
    url: str, 
    timeout: int = settings.DEFAULT_API_TIMEOUT
) -> Optional[dict]:
    """
    Safely make an API call with error handling and timeout.
    
    Args:
        session: aiohttp ClientSession to use for the request
        url: The URL to call
        timeout: Timeout in seconds
        
    Returns:
        The JSON response if successful, None if failed
    """
    try:
        async with session.get(url, timeout=timeout) as response:
            if response.status == 200:
                return await response.json()
            logging.warning(f"API call failed with status {response.status}: {url}")
            return None
    except Exception as e:
        logging.error(f"API call error for {url}: {str(e)}")
        return None

class DexScreenerAPI:
    """Wrapper for DexScreener API calls"""
    BASE_URL = "https://api.dexscreener.com/latest/dex"
    
    @staticmethod
    async def get_token_info(session: aiohttp.ClientSession, contract: str) -> Optional[dict]:
        """Get token information from DexScreener"""
        url = f"{DexScreenerAPI.BASE_URL}/tokens/{contract}"
        return await safe_api_call(session, url)

class HyperliquidAPI:
    """Wrapper for Hyperliquid API calls"""
    BASE_URL = "https://api.hyperliquid.xyz"
    
    @staticmethod
    async def get_asset_info(session: aiohttp.ClientSession) -> Optional[dict]:
        """Get asset information from Hyperliquid"""
        url = f"{HyperliquidAPI.BASE_URL}/info"
        return await safe_api_call(session, url)

    @staticmethod
    async def get_user_fills(session: aiohttp.ClientSession, address: str) -> Optional[dict]:
        """Get user trade fills from Hyperliquid"""
        url = f"{HyperliquidAPI.BASE_URL}/fills/{address}"
        return await safe_api_call(session, url)

    @staticmethod
    async def get_user_state(session: aiohttp.ClientSession, address: str) -> Optional[dict]:
        """Get user state (positions) from Hyperliquid"""
        url = f"{HyperliquidAPI.BASE_URL}/user/{address}"
        return await safe_api_call(session, url)