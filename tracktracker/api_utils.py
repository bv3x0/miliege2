"""
API utilities module for tracktracker.

This module provides common utilities for API interaction, including
retry mechanisms, error handling, and request formatting.
"""

import logging
import time
import functools
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar, Union, cast
import requests
from requests.exceptions import RequestException, HTTPError, ConnectionError, Timeout

from tracktracker.api_cache import get_cached_api_request, get_from_cache, save_to_cache, clear_cache

# Type variable for function return
T = TypeVar('T')

# Define error classes for better error classification
class TrackTrackerError(Exception):
    """Base exception class for all TrackTracker errors."""
    pass


class RecoverableError(TrackTrackerError):
    """Error class for recoverable errors (can retry)."""
    pass


class NonRecoverableError(TrackTrackerError):
    """Error class for non-recoverable errors (cannot retry)."""
    pass


class APIError(RecoverableError):
    """Error class for API-related errors."""
    def __init__(self, message: str, status_code: Optional[int] = None, response: Optional[Any] = None):
        self.status_code = status_code
        self.response = response
        super().__init__(message)


class RateLimitError(APIError):
    """Error class for rate limit errors."""
    def __init__(self, message: str, retry_after: Optional[int] = None, **kwargs):
        self.retry_after = retry_after
        super().__init__(message, **kwargs)


class AuthenticationError(NonRecoverableError):
    """Error class for authentication-related errors."""
    pass


class DataValidationError(NonRecoverableError):
    """Error class for data validation errors."""
    pass


# Get configuration settings
def get_retry_config():
    """Get retry configuration from settings."""
    try:
        from tracktracker.config import settings
        return {
            "max_retries": settings.api.max_retries,
            "base_delay": settings.api.base_delay,
            "max_delay": settings.api.max_delay,
            "backoff_factor": settings.api.retry_backoff
        }
    except ImportError:
        # Fallback to defaults if config module is not available
        return {
            "max_retries": 3,
            "base_delay": 1.0,
            "max_delay": 60.0,
            "backoff_factor": 2.0
        }


# Retry decorator with exponential backoff
def retry_with_backoff(
    max_retries: Optional[int] = None,
    base_delay: Optional[float] = None,
    max_delay: Optional[float] = None,
    backoff_factor: Optional[float] = None,
    retryable_exceptions: Optional[List[Type[Exception]]] = None,
    retryable_status_codes: Optional[List[int]] = None
) -> Callable:
    """
    Retry decorator with exponential backoff.
    
    Args:
        max_retries: Maximum number of retries (if None, uses settings)
        base_delay: Initial delay between retries in seconds (if None, uses settings)
        max_delay: Maximum delay between retries in seconds (if None, uses settings)
        backoff_factor: Backoff factor for exponential delay calculation (if None, uses settings)
        retryable_exceptions: List of exceptions that should trigger a retry
        retryable_status_codes: List of HTTP status codes that should trigger a retry
        
    Returns:
        Decorator function
    """
    # Get defaults from config if not provided
    config = get_retry_config()
    if max_retries is None:
        max_retries = config["max_retries"]
    if base_delay is None:
        base_delay = config["base_delay"]
    if max_delay is None:
        max_delay = config["max_delay"]
    if backoff_factor is None:
        backoff_factor = config["backoff_factor"]
        
    if retryable_exceptions is None:
        retryable_exceptions = [
            requests.exceptions.RequestException,
            ConnectionError,
            Timeout,
            RecoverableError,
            RateLimitError
        ]
        
    if retryable_status_codes is None:
        retryable_status_codes = [429, 500, 502, 503, 504]

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            retry_count = 0
            delay = base_delay
            
            while True:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    # Check if this exception is retryable
                    is_retryable = False
                    retry_after = None
                    
                    # Check if it's a retryable exception type
                    if any(isinstance(e, exc) for exc in retryable_exceptions):
                        is_retryable = True
                        
                        # Check for rate limit info with more detailed logging
                        if isinstance(e, RateLimitError) and e.retry_after:
                            retry_after = e.retry_after
                            logging.warning(f"Rate limit encountered. Server specified Retry-After: {retry_after} seconds")
                    
                    # Check if it's a requests HTTPError with a retryable status code
                    elif isinstance(e, HTTPError) and hasattr(e, 'response'):
                        status_code = e.response.status_code
                        if status_code in retryable_status_codes:
                            is_retryable = True
                            # Check for Retry-After header
                            retry_after_header = e.response.headers.get('Retry-After')
                            if retry_after_header:
                                try:
                                    retry_after = int(retry_after_header)
                                except (ValueError, TypeError):
                                    pass
                    
                    # Decide whether to retry
                    retry_count += 1
                    if not is_retryable or retry_count > max_retries:
                        # Wrap non-TrackTrackerError exceptions in appropriate error types
                        if not isinstance(e, TrackTrackerError):
                            if isinstance(e, (RequestException, ConnectionError, Timeout)):
                                raise APIError(f"API request failed: {str(e)}", 
                                              getattr(e.response, 'status_code', None) if hasattr(e, 'response') else None,
                                              getattr(e, 'response', None) if hasattr(e, 'response') else None) from e
                            else:
                                # Re-raise the original exception for non-API related errors
                                raise
                        # Re-raise TrackTrackerError exceptions directly
                        raise
                    
                    # Add detailed logging for each retry attempt
                    logging.warning(
                        f"Retry attempt {retry_count}/{max_retries} for {func.__name__} due to error: {str(e)[:150]}"
                    )
                    
                    # Calculate delay (prefer retry_after if provided)
                    if retry_after is not None:
                        # For Spotify rate limits, add a small buffer to the retry time
                        wait_time = retry_after + 1.0  # Add 1 second buffer
                        logging.warning(f"Using server-specified retry delay of {retry_after}s (plus 1s buffer)")
                    else:
                        wait_time = min(delay, max_delay)
                        delay = delay * backoff_factor
                    
                    # Make sure wait_time is at least a minimum value
                    wait_time = max(wait_time, 3.0)  # At least 3 seconds between retries
                    
                    logging.warning(
                        f"Retrying {func.__name__} after error: {str(e)[:150]}... "
                        f"Retry {retry_count}/{max_retries} in {wait_time:.2f}s"
                    )
                    
                    # Actually wait the full time - this is critical
                    start_wait = time.time()
                    time.sleep(wait_time)
                    actual_wait = time.time() - start_wait
                    
                    # Log that we've finished waiting
                    logging.info(f"Finished waiting {actual_wait:.2f}s, now retrying {func.__name__}")
                    if retry_after is not None:
                        # For Spotify rate limits, add a small buffer to the retry time
                        wait_time = retry_after + 1.0  # Add 1 second buffer
                        logging.warning(f"Using server-specified retry delay of {retry_after}s (plus 1s buffer)")
                    else:
                        wait_time = min(delay, max_delay)
                        delay = delay * backoff_factor
                    
                    # Make sure wait_time is at least a minimum value
                    wait_time = max(wait_time, 3.0)  # At least 3 seconds between retries
                    
                    logging.warning(
                        f"Retrying {func.__name__} after error: {str(e)[:150]}... "
                        f"Retry {retry_count}/{max_retries} in {wait_time:.2f}s"
                    )
                    
                    # Actually wait the full time - this is critical
                    start_wait = time.time()
                    time.sleep(wait_time)
                    actual_wait = time.time() - start_wait
                    
                    # Log that we've finished waiting
                    logging.info(f"Finished waiting {actual_wait:.2f}s, now retrying {func.__name__}")
            
        return wrapper
    return decorator


# Standardized API request function
@retry_with_backoff()
def make_request(
    url: str,
    method: str = 'GET',
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
    expected_status_codes: Optional[List[int]] = None
) -> requests.Response:
    """
    Make an API request with standardized error handling and retries.
    
    Args:
        url: URL to make the request to
        method: HTTP method (GET, POST, etc.)
        headers: HTTP headers
        params: URL parameters
        json_data: JSON data for POST/PUT requests
        timeout: Request timeout in seconds
        expected_status_codes: List of expected status codes (default: [200])
        
    Returns:
        Response object
        
    Raises:
        APIError: If the API request fails
        RateLimitError: If the API rate limit is exceeded
        AuthenticationError: If authentication fails
        NonRecoverableError: For other non-recoverable errors
    """
    if expected_status_codes is None:
        expected_status_codes = [200]
        
    if headers is None:
        headers = {}
    
    # Try to get the user agent from settings
    try:
        from tracktracker.config import settings
        default_user_agent = settings.api.user_agent
        default_timeout = settings.api.timeout
    except ImportError:
        default_user_agent = 'tracktracker/1.0'
        default_timeout = timeout
        
    # Add default headers if not provided
    if 'User-Agent' not in headers:
        headers['User-Agent'] = default_user_agent
        
    try:
        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json=json_data,
            timeout=default_timeout
        )
        
        # Check if status code is in expected codes
        if response.status_code not in expected_status_codes:
            # Handle specific error codes
            if response.status_code == 429:
                # Rate limit exceeded
                retry_after = response.headers.get('Retry-After')
                retry_seconds = int(retry_after) if retry_after and retry_after.isdigit() else None
                raise RateLimitError(
                    f"Rate limit exceeded: {response.status_code}",
                    retry_after=retry_seconds,
                    status_code=response.status_code,
                    response=response
                )
            elif response.status_code in (401, 403):
                # Authentication/authorization error
                raise AuthenticationError(f"Authentication failed: {response.status_code}", status_code=response.status_code, response=response)
            elif response.status_code >= 500:
                # Server error (potentially retryable)
                raise APIError(f"Server error: {response.status_code}", status_code=response.status_code, response=response)
            else:
                # Other client errors
                raise NonRecoverableError(f"API error: {response.status_code}", status_code=response.status_code, response=response)
                
        return response
        
    except requests.exceptions.Timeout:
        raise APIError("Request timed out", None, None)
    except requests.exceptions.ConnectionError:
        raise APIError("Connection error", None, None)
    except requests.exceptions.RequestException as e:
        raise APIError(f"Request failed: {str(e)}", getattr(e, 'response.status_code', None), getattr(e, 'response', None))


# JSON API request helper
def make_json_request(
    url: str,
    method: str = 'GET',
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
    use_cache: bool = True,
    cache_max_age: int = 3600,
    force_refresh: bool = False
) -> Dict[str, Any]:
    """
    Make an API request and return the JSON response.
    
    Args:
        url: URL to make the request to
        method: HTTP method (GET, POST, etc.)
        headers: HTTP headers
        params: URL parameters
        json_data: JSON data for POST/PUT requests
        timeout: Request timeout in seconds
        use_cache: Whether to use caching (only for GET requests)
        cache_max_age: Maximum age of cached response in seconds
        force_refresh: Force refresh the cache even if not expired
        
    Returns:
        JSON response as a dictionary
        
    Raises:
        APIError: If the API request fails
        RateLimitError: If the API rate limit is exceeded
        AuthenticationError: If authentication fails
        DataValidationError: If the response is not valid JSON
        NonRecoverableError: For other non-recoverable errors
    """
    # Ensure we request JSON response if not already specified
    if headers is None:
        headers = {}
    if 'Accept' not in headers:
        headers['Accept'] = 'application/json'
    
    # Check if we can use caching (only for GET requests)
    if method == 'GET' and use_cache and not json_data:
        def make_actual_request(request_url, request_params):
            actual_response = make_request(
                url=request_url,
                method=method,
                headers=headers,
                params=request_params,
                json_data=json_data,
                timeout=timeout
            )
            try:
                return actual_response.json()
            except ValueError:
                raise DataValidationError("Response is not valid JSON", 
                                          status_code=actual_response.status_code, 
                                          response=actual_response)
        
        # Use the cached request helper
        return get_cached_api_request(
            make_request_func=make_actual_request,
            url=url,
            params=params,
            max_age_seconds=cache_max_age,
            force_refresh=force_refresh
        )[0]  # Return just the data part of the tuple
    else:
        # For non-GET requests or when caching is disabled, make a regular request
        response = make_request(
            url=url,
            method=method,
            headers=headers,
            params=params,
            json_data=json_data,
            timeout=timeout
        )
        
        try:
            return response.json()
        except ValueError:
            raise DataValidationError("Response is not valid JSON", status_code=response.status_code, response=response)