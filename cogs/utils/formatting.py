from typing import Union
import re
from datetime import datetime
import logging

def format_large_number(number: Union[int, float, str]) -> str:
    """
    Format large numbers into a readable format with K, M, B suffixes.
    
    Args:
        number: Number to format (can be int, float, or numeric string)
        
    Returns:
        Formatted string with appropriate suffix
    """
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

    # Add .0 for whole numbers to maintain consistency
    decimal_places = 1 if num % 1 == 0 else 2
    formatted = f"{num:.{decimal_places}f}"
    
    # Remove trailing .0 if present
    formatted = formatted.rstrip('0').rstrip('.')
    
    return f"{formatted}{'KMB'[magnitude-1] if magnitude > 0 else ''}"

def format_percentage(value: Union[float, str]) -> str:
    """
    Format a number as a percentage with appropriate precision.
    
    Args:
        value: Number to format as percentage
        
    Returns:
        Formatted percentage string
    """
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

def format_buy_amount(amount: Union[str, float]) -> str:
    """
    Format buy amount with appropriate precision and currency symbol.
    
    Args:
        amount: Buy amount to format
        
    Returns:
        Formatted buy amount string
    """
    try:
        # Remove any existing currency symbols and commas
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