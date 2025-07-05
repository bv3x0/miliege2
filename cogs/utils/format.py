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
    """Format large numbers with k, m, b suffixes
    
    Rules:
    - Thousands (k): No decimal places ($677k instead of $677.41k)
    - Millions (m): One decimal place ($2.1m)
    - Billions (b): One decimal place ($2.5b)
    """
    try:
        num = float(str(number).replace(',', ''))
    except (ValueError, TypeError):
        return "0"

    if num == 0:
        return "0"

    abs_num = abs(num)
    
    if abs_num >= 1_000_000_000:  # Billions
        formatted = f"{num / 1_000_000_000:.1f}b"
    elif abs_num >= 1_000_000:     # Millions
        formatted = f"{num / 1_000_000:.1f}m"
    elif abs_num >= 1_000:         # Thousands
        formatted = f"{int(num / 1_000)}k"  # No decimal places for thousands
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

def format_social_links(social_info: dict, chain: str = None) -> list:
    """
    Centralized function to format social links including Axiom for Solana tokens
    
    Args:
        social_info: Dictionary containing social information (websites, socials, pair_address, etc.)
        chain: The blockchain chain (e.g., 'solana', 'ethereum')
    
    Returns:
        List of formatted social links in Discord markdown format
    """
    social_parts = []
    
    if not social_info:
        return social_parts
    
    # Process websites
    if 'websites' in social_info and isinstance(social_info['websites'], list):
        for website in social_info['websites']:
            if isinstance(website, dict) and 'url' in website:
                # Skip pump.fun links
                if 'pump.fun' not in website['url']:
                    social_parts.append(f"[web]({website['url']})")
                    logging.debug(f"Added website: {website['url']}")
                    break  # Only add first website
    
    # Process social links
    if 'socials' in social_info and isinstance(social_info['socials'], list):
        for social in social_info['socials']:
            if isinstance(social, dict):
                platform = social.get('platform', '').lower()
                typ = social.get('type', '').lower()
                url = social.get('url', '')
                
                if url:
                    if 'twitter' in platform or 'twitter' in typ:
                        social_parts.append(f"[𝕏]({url})")
                        logging.debug(f"Added Twitter: {url}")
                        break  # Only add first Twitter link
    
    # Check for Telegram
    telegram_added = False
    if 'socials' in social_info and isinstance(social_info['socials'], list):
        for social in social_info['socials']:
            if isinstance(social, dict):
                platform = social.get('platform', '').lower()
                typ = social.get('type', '').lower()
                url = social.get('url', '')
                
                if url and ('telegram' in platform or 'telegram' in typ):
                    social_parts.append(f"[tg]({url})")
                    logging.debug(f"Added Telegram: {url}")
                    telegram_added = True
                    break
    
    # If no Twitter found, check for Discord
    if not any('𝕏' in part for part in social_parts) and not telegram_added:
        if 'socials' in social_info and isinstance(social_info['socials'], list):
            for social in social_info['socials']:
                if isinstance(social, dict):
                    platform = social.get('platform', '').lower()
                    url = social.get('url', '')
                    
                    if url and 'discord' in platform:
                        social_parts.append(f"[dc]({url})")
                        logging.debug(f"Added Discord: {url}")
                        break
    
    # Legacy format fallback
    if not any('𝕏' in part for part in social_parts):
        if twitter := social_info.get('twitter'):
            social_parts.append(f"[𝕏]({twitter})")
            logging.debug(f"Added legacy Twitter: {twitter}")
    
    # Add Axiom link for Solana tokens (always last)
    if chain and chain.lower() == 'solana':
        pair_address = social_info.get('pair_address')
        if pair_address:
            social_parts.append(f"[axiom](https://axiom.trade/meme/{pair_address})")
            logging.debug(f"Added Axiom link for Solana token: {pair_address}")
    
    return social_parts

def parse_market_cap(mcap_str: Union[str, float, int]) -> Union[float, None]:
    """
    Parse market cap string to float value
    
    Args:
        mcap_str: Market cap as string (e.g., "$1.5M", "2.3B"), float, or int
    
    Returns:
        Float value or None if parsing fails
    """
    try:
        # Handle None or 'N/A'
        if not mcap_str or mcap_str == 'N/A':
            return None
        
        # If already a number, return it
        if isinstance(mcap_str, (int, float)):
            return float(mcap_str)

        # Remove $ and any commas
        clean_mcap = str(mcap_str).replace('$', '').replace(',', '')

        # Handle K/M/B suffixes
        multiplier = 1
        if 'K' in clean_mcap.upper():
            multiplier = 1_000
            clean_mcap = clean_mcap.upper().replace('K', '')
        elif 'M' in clean_mcap.upper():
            multiplier = 1_000_000
            clean_mcap = clean_mcap.upper().replace('M', '')
        elif 'B' in clean_mcap.upper():
            multiplier = 1_000_000_000
            clean_mcap = clean_mcap.upper().replace('B', '')

        return float(clean_mcap) * multiplier
    except (ValueError, TypeError):
        return None

def calculate_mcap_status_emoji(current_mcap: Union[str, float], initial_mcap: Union[float, None]) -> tuple[str, Union[float, None]]:
    """
    Calculate market cap percentage change and return appropriate status emoji
    
    Args:
        current_mcap: Current market cap (string with format like "$1.5M" or float)
        initial_mcap: Initial market cap as float (already parsed)
    
    Returns:
        Tuple of (status_emoji, percent_change)
        - status_emoji: " :up:" for +40%, " 🪦" for -40%, or ""
        - percent_change: The calculated percentage or None if unable to calculate
    """
    try:
        current_mcap_value = parse_market_cap(current_mcap)
        
        if current_mcap_value and initial_mcap and initial_mcap > 0:
            percent_change = ((current_mcap_value - initial_mcap) / initial_mcap) * 100
            
            if percent_change >= 40:
                return " :up:", percent_change
            elif percent_change <= -40:
                return " 🪦", percent_change
            else:
                return "", percent_change
        
        return "", None
    except Exception as e:
        logging.error(f"Error calculating market cap change: {e}")
        return "", None