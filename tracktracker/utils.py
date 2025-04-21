"""
Utility functions for tracktracker.

Includes URL parsing, track deduplication, and other helper functions.
"""

import os
import re
import datetime
from typing import Dict, List, Optional
from urllib.parse import urlparse

from rapidfuzz import fuzz


def parse_url(url: str) -> str:
    """
    Parse the input URL to ensure it's an NTS Radio URL.
    
    Args:
        url: The URL to an NTS Radio episode
        
    Returns:
        The validated NTS URL
        
    Raises:
        ValueError: If the URL is not from a supported service
    """
    parsed = urlparse(url)
    
    if "nts.live" in parsed.netloc:
        return url
    else:
        raise ValueError(
            f"Unsupported URL: {url}. Only NTS Radio URLs are supported."
        )


def deduplicate_tracks(tracks: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Remove duplicate tracks using fuzzy matching.
    
    Args:
        tracks: List of track dictionaries with 'artist' and 'title' keys
        
    Returns:
        Deduplicated list of tracks
    """
    if not tracks:
        return []
    
    unique_tracks = [tracks[0]]
    
    for track in tracks[1:]:
        is_duplicate = False
        
        for unique_track in unique_tracks:
            # Combine artist and title for comparison
            track_full = f"{track['artist']} {track['title']}".lower()
            unique_full = f"{unique_track['artist']} {unique_track['title']}".lower()
            
            # Use RapidFuzz to compare strings
            if fuzz.ratio(track_full, unique_full) >= 95:
                is_duplicate = True
                break
        
        if not is_duplicate:
            unique_tracks.append(track)
    
    return unique_tracks


def format_date_us(date_str: str) -> str:
    """
    Format a date string to US format (MM/DD/YYYY).
    
    Args:
        date_str: Date string in various formats
        
    Returns:
        Formatted date string in US format, or original string if parsing fails
    """
    # Common date formats used by NTS
    date_formats = [
        "%Y-%m-%d",      # 2023-12-31
        "%d.%m.%Y",      # 31.12.2023
        "%d/%m/%Y",      # 31/12/2023
        "%Y%m%d",        # 20231231
        "%d-%m-%Y",      # 31-12-2023
        "%B %d, %Y",     # December 31, 2023
        "%d %B %Y"       # 31 December 2023
    ]
    
    for fmt in date_formats:
        try:
            date_obj = datetime.datetime.strptime(date_str, fmt)
            return date_obj.strftime("%m/%d/%Y")  # US format: MM/DD/YYYY
        except ValueError:
            continue
    
    # Also try to extract date from episode title patterns like "New York Naomi 22.03.25"
    date_pattern = r'(\d{2})\.(\d{2})\.(\d{2})$'
    match = re.search(date_pattern, date_str)
    if match:
        try:
            day, month, year = match.groups()
            year = f"20{year}"  # Assume 20xx for 2-digit years
            date_obj = datetime.datetime(int(year), int(month), int(day))
            return date_obj.strftime("%m/%d/%Y")
        except (ValueError, IndexError):
            pass
            
    # Return original if all parsing attempts fail
    return date_str


def format_episode_playlist_name(show_name: str, episode_title: str, broadcast_date: str = "") -> str:
    """
    Format a playlist name for a single episode with US date format.
    
    Args:
        show_name: Show name
        episode_title: Episode title
        broadcast_date: Optional broadcast date
        
    Returns:
        Formatted playlist name with date in US format
    """
    # Try to extract date from the broadcast_date field
    formatted_date = ""
    if broadcast_date:
        formatted_date = format_date_us(broadcast_date)
    
    # If no broadcast_date or parsing failed, try to extract from episode title
    if not formatted_date or formatted_date == broadcast_date:
        # Look for date patterns in episode title
        date_matches = re.findall(r'\d+\.\d+\.\d+|\d+/\d+/\d+|\d+-\d+-\d+', episode_title)
        if date_matches:
            formatted_date = format_date_us(date_matches[0])
    
    # Clean the show name
    clean_name = clean_playlist_name(show_name)
    
    # Add date in parentheses if available
    if formatted_date and formatted_date != broadcast_date:
        return f"{clean_name} ({formatted_date})"
    else:
        return clean_name


def format_show_archive_playlist_name(show_name: str) -> str:
    """
    Format a playlist name for a complete show archive.
    
    Args:
        show_name: Show name
        
    Returns:
        Formatted playlist name with (Full Archive) appended
    """
    # Clean the show name
    clean_name = clean_playlist_name(show_name)
    return f"{clean_name} (NTS Archive)"


def clean_playlist_name(name: str) -> str:
    """
    Clean a string to be used as a playlist name.
    
    Args:
        name: Original name string
        
    Returns:
        Cleaned string suitable for playlist name
    """
    # Remove characters that might cause issues
    name = re.sub(r'[^\w\s\-–:]', '', name)
    return name.strip() 