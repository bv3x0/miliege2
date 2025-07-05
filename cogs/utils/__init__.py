"""
Utility package providing common functionality for the bot.
Includes configuration, formatting, and API utilities.
"""

from .config import settings, UI
from .format import (
    format_large_number,
    format_currency,
    format_percent,
    format_age,
    format_social_links,
    parse_market_cap,
    calculate_mcap_status_emoji,
    Colors,
    BotConstants,
    Messages
)
from .api import safe_api_call, DexScreenerAPI, HyperliquidAPI

__all__ = [
    # Configuration
    'settings',
    'UI',
    
    # Formatting utilities and constants
    'format_large_number',
    'format_currency',
    'format_percent',
    'format_age',
    'format_social_links',
    'parse_market_cap',
    'calculate_mcap_status_emoji',
    'Colors',
    'BotConstants',
    'Messages',
    
    # API utilities
    'safe_api_call',
    'DexScreenerAPI',
    'HyperliquidAPI',
]