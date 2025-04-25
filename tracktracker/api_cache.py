"""
API caching module for tracktracker.

This module provides caching functionality for API responses to reduce
the number of API calls and improve performance.
"""

import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

# Try to get the cache directory from the config
try:
    from tracktracker.config import settings
    CACHE_DIR = settings.paths.cache_dir
except ImportError:
    # Fallback to a default
    import pathlib
    CACHE_DIR = pathlib.Path.home() / ".tracktracker"

# Ensure the cache directory exists
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR, exist_ok=True)


def generate_cache_key(url: str, params: Optional[Dict[str, Any]] = None) -> str:
    """
    Generate a cache key from a URL and optional parameters.
    
    Args:
        url: The URL of the API request
        params: Optional query parameters
        
    Returns:
        A string key suitable for caching
    """
    # Clean up URL by removing protocol and trailing slashes
    url = url.replace("https://", "").replace("http://", "").rstrip("/")
    
    # Add parameters to the key if present
    if params:
        # Convert params to a stable string representation
        param_str = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        key = f"{url}?{param_str}"
    else:
        key = url
        
    # Make the key filesystem-safe
    key = key.replace("/", "_").replace(":", "_").replace("?", "_").replace("&", "_")
    key = key.replace("=", "_").replace(" ", "_").replace(".", "_")
    
    return key


def get_cache_path(cache_key: str) -> str:
    """
    Get the filesystem path for a cache key.
    
    Args:
        cache_key: The cache key
        
    Returns:
        Absolute path to the cache file
    """
    return os.path.join(CACHE_DIR, f"api_cache_{cache_key}.json")


def get_from_cache(url: str, params: Optional[Dict[str, Any]] = None, max_age_seconds: int = 3600) -> Optional[Dict[str, Any]]:
    """
    Get a cached API response if available and not expired.
    
    Args:
        url: The URL of the API request
        params: Optional query parameters
        max_age_seconds: Maximum age of the cache in seconds (default: 1 hour)
        
    Returns:
        The cached response data if available and fresh, None otherwise
    """
    cache_key = generate_cache_key(url, params)
    cache_path = get_cache_path(cache_key)
    
    if not os.path.exists(cache_path):
        return None
    
    try:
        with open(cache_path, "r") as f:
            cache_data = json.load(f)
        
        # Check if cache is expired
        timestamp = cache_data.get("timestamp", 0)
        current_time = time.time()
        
        if current_time - timestamp > max_age_seconds:
            logging.debug(f"Cache expired for {url}")
            return None
        
        logging.debug(f"Cache hit for {url}")
        return cache_data.get("data")
    except Exception as e:
        logging.warning(f"Error reading cache for {url}: {e}")
        return None


def save_to_cache(url: str, data: Dict[str, Any], params: Optional[Dict[str, Any]] = None) -> None:
    """
    Save API response data to cache.
    
    Args:
        url: The URL of the API request
        data: The response data to cache
        params: Optional query parameters
    """
    cache_key = generate_cache_key(url, params)
    cache_path = get_cache_path(cache_key)
    
    try:
        cache_data = {
            "timestamp": time.time(),
            "data": data
        }
        
        with open(cache_path, "w") as f:
            json.dump(cache_data, f)
            
        logging.debug(f"Cached response for {url}")
    except Exception as e:
        logging.warning(f"Error caching response for {url}: {e}")


def clear_cache(url: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> int:
    """
    Clear the API cache.
    
    Args:
        url: Optional URL to clear specific cache entry, None to clear all
        params: Optional query parameters if clearing a specific URL
        
    Returns:
        Number of cache entries cleared
    """
    if url:
        # Clear specific cache entry
        cache_key = generate_cache_key(url, params)
        cache_path = get_cache_path(cache_key)
        
        if os.path.exists(cache_path):
            os.remove(cache_path)
            logging.info(f"Cleared cache for {url}")
            return 1
        return 0
    else:
        # Clear all cache entries
        count = 0
        for filename in os.listdir(CACHE_DIR):
            if filename.startswith("api_cache_") and filename.endswith(".json"):
                os.remove(os.path.join(CACHE_DIR, filename))
                count += 1
                
        logging.info(f"Cleared {count} cache entries")
        return count


def clear_expired_cache(max_age_seconds: int = 3600) -> int:
    """
    Clear expired cache entries.
    
    Args:
        max_age_seconds: Maximum age of the cache in seconds (default: 1 hour)
        
    Returns:
        Number of cache entries cleared
    """
    count = 0
    current_time = time.time()
    
    for filename in os.listdir(CACHE_DIR):
        if filename.startswith("api_cache_") and filename.endswith(".json"):
            cache_path = os.path.join(CACHE_DIR, filename)
            
            try:
                with open(cache_path, "r") as f:
                    cache_data = json.load(f)
                
                timestamp = cache_data.get("timestamp", 0)
                
                if current_time - timestamp > max_age_seconds:
                    os.remove(cache_path)
                    count += 1
            except Exception:
                # If we can't read the cache file, consider it corrupted and remove it
                os.remove(cache_path)
                count += 1
                
    logging.info(f"Cleared {count} expired cache entries")
    return count


def get_cached_api_request(
    make_request_func: callable,
    url: str,
    params: Optional[Dict[str, Any]] = None,
    max_age_seconds: int = 3600,
    force_refresh: bool = False
) -> Tuple[Dict[str, Any], bool]:
    """
    Get data from cache or make an API request and cache the result.
    
    Args:
        make_request_func: Function to make the API request if cache miss
        url: The URL to request
        params: Optional query parameters
        max_age_seconds: Maximum age of the cache in seconds
        force_refresh: Force refresh the cache even if not expired
        
    Returns:
        Tuple of (response_data, from_cache) where from_cache is True if data came from cache
    """
    if not force_refresh:
        # Try to get from cache first
        cached_data = get_from_cache(url, params, max_age_seconds)
        if cached_data is not None:
            return cached_data, True
    
    # Cache miss or forced refresh, make the real request
    response_data = make_request_func(url, params)
    
    # Cache the response
    save_to_cache(url, response_data, params)
    
    return response_data, False