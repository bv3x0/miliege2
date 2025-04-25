"""
Spotify integration module for tracktracker.

This module handles all interactions with the Spotify API,
including authentication, playlist creation, and track searching.
"""

import logging
import os
import re
import sys
import time
import json
import csv
import functools
import concurrent.futures
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple, Optional, Set, Any, Callable, TypeVar

import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotipy.exceptions import SpotifyException

from tracktracker.batch_search import batch_process

from tracktracker.api_utils import (
    retry_with_backoff,
    APIError,
    RateLimitError,
    AuthenticationError,
    NonRecoverableError,
    DataValidationError,
)

# Type variable for function return
T = TypeVar('T')


# Global track search cache
_TRACK_CACHE = {}

# Spotify API error handler decorator
def handle_spotify_errors(func: Callable[..., T]) -> Callable[..., T]:
    """
    Decorator to handle Spotify API errors with appropriate retry logic and error mapping.
    
    Args:
        func: The function to decorate
        
    Returns:
        Decorated function
    """
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        try:
            return func(*args, **kwargs)
        except SpotifyException as e:
            # Map Spotify errors to our standard error types
            if e.http_status == 429:  # Rate limiting
                # Get retry_after value, with more careful handling
                retry_after = None
                if hasattr(e, "headers") and e.headers:
                    retry_header = e.headers.get("Retry-After")
                    if retry_header:
                        try:
                            retry_after = int(retry_header)
                        except (ValueError, TypeError):
                            # If we can't parse the value, use a default value
                            retry_after = 15  # Use a conservative default
                
                # If we still don't have a value, use a default
                if retry_after is None:
                    retry_after = 15  # Use a conservative default
                
                # Log this for debugging with detailed information
                logging.warning(
                    f"Spotify rate limit exceeded. "
                    f"Retry-After: {retry_after} seconds. "
                    f"Headers: {e.headers if hasattr(e, 'headers') else 'N/A'}. "
                    f"Message: {str(e)}"
                )
                raise RateLimitError(
                    f"Spotify API rate limit exceeded: {e}",
                    retry_after=retry_after,
                    status_code=e.http_status,
                    response=e.response if hasattr(e, "response") else None
                ) from e
            elif e.http_status in (401, 403):  # Auth errors
                raise AuthenticationError(
                    f"Spotify authentication error: {e}",
                    status_code=e.http_status,
                    response=e.response if hasattr(e, "response") else None
                ) from e
            elif e.http_status >= 500:  # Server errors
                raise APIError(
                    f"Spotify server error: {e}",
                    status_code=e.http_status,
                    response=e.response if hasattr(e, "response") else None
                ) from e
            else:  # Other client errors
                raise NonRecoverableError(
                    f"Spotify API error: {e}",
                    status_code=e.http_status,
                    response=e.response if hasattr(e, "response") else None
                ) from e
        except Exception as e:  # Catch-all for non-Spotify exceptions
            # Don't wrap our own error types
            if isinstance(e, (APIError, RateLimitError, AuthenticationError, NonRecoverableError)):
                raise
            # Wrap other exceptions
            raise APIError(f"Error in Spotify operation: {e}") from e
    
    return wrapper

@retry_with_backoff(max_retries=3, base_delay=5.0, backoff_factor=3.0)
def authenticate(scope: str) -> spotipy.Spotify:
    """
    Authenticate with Spotify API.
    
    Args:
        scope: Spotify API permission scope
        
    Returns:
        Authenticated Spotify client
        
    Raises:
        AuthenticationError: If authentication fails due to API issues
        NonRecoverableError: If authentication fails due to missing credentials
    """
    from tracktracker.config import settings
    
    try:
        # Ensure cache directory exists
        settings.ensure_directories()
        
        # Get Spotify credentials from settings
        client_id = settings.spotify.client_id
        client_secret = settings.spotify.client_secret
        redirect_uri = settings.spotify.redirect_uri
        cache_path = settings.paths.spotify_token_path
        
        # Log current status
        logging.info("Setting up Spotify authentication...")
        
        # Add a sleep before attempting authentication to avoid rate limits
        # This gives Spotify a chance to reset rate limits between runs
        time.sleep(3)
        
        # Create a Spotify client using credentials from settings
        client = spotipy.Spotify(auth_manager=SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=scope,
            cache_path=str(cache_path),
            open_browser=False  # Don't open browser automatically
        ))
        
        # Test the connection to validate authentication
        try:
            logging.info("Testing Spotify connection...")
            client.current_user()
            logging.info("✓ Successfully authenticated with Spotify!")
        except SpotifyException as e:
            if e.http_status in (401, 403):
                # For auth errors, try clearing the cache and retrying once
                logging.warning("Authentication failed, clearing token cache and retrying...")
                
                if os.path.exists(cache_path):
                    try:
                        os.remove(cache_path)
                        logging.info("Token cache cleared")
                    except Exception as cache_e:
                        logging.warning(f"Failed to clear token cache: {cache_e}")
                
                raise AuthenticationError("Failed to authenticate with Spotify: Invalid credentials") from e
            elif e.http_status == 429:
                # Special handling for rate limits during authentication
                retry_after = e.headers.get("Retry-After", "15") if hasattr(e, "headers") else "15"
                logging.warning(f"Rate limit during authentication. Retry-After: {retry_after} seconds")
                # Let the retry decorator handle this
                raise RateLimitError(
                    f"Rate limit during Spotify authentication: {e}",
                    retry_after=int(retry_after) if retry_after.isdigit() else 15
                ) from e
            else:
                raise
                
        return client
    except (AuthenticationError, NonRecoverableError):
        # Re-raise our custom exceptions
        raise
    except Exception as e:
        logging.error(f"Failed to authenticate with Spotify: {e}")
        # For backward compatibility, wrap in ValueError
        raise ValueError(
            "Spotify authentication failed. Make sure you have set the following environment variables "
            "or added them to your .env file:\n"
            "  - SPOTIFY_CLIENT_ID\n"
            "  - SPOTIFY_CLIENT_SECRET\n"
            "  - SPOTIFY_REDIRECT_URI (optional, defaults to http://127.0.0.1:8888/callback)"
        ) from e


@handle_spotify_errors
@retry_with_backoff(max_retries=3, base_delay=2.0)
def create_playlist(spotify: spotipy.Spotify, playlist_name: str, description: str = "") -> str:
    """
    Creates a new Spotify playlist.
    
    Args:
        spotify: Authenticated Spotify client
        playlist_name: Name for the new playlist
        description: Optional playlist description
        
    Returns:
        Playlist ID of the created playlist
        
    Raises:
        APIError: If the API request fails
        AuthenticationError: If authentication fails
        NonRecoverableError: For other non-recoverable errors
    """
    try:
        user_id = spotify.me()["id"]
        
        playlist = spotify.user_playlist_create(
            user=user_id,
            name=playlist_name,
            public=True,
            description=description
        )
        return playlist["id"]
    except (APIError, AuthenticationError, NonRecoverableError):
        # Re-raise our own exceptions
        raise
    except Exception as e:
        # For backward compatibility, wrap in ValueError
        logging.error(f"Failed to create Spotify playlist: {e}")
        raise ValueError(f"Failed to create Spotify playlist: {e}") from e


def load_track_cache() -> Dict[str, str]:
    """
    Load the track search cache from disk.
    
    Returns:
        Dictionary mapping track signatures to Spotify URIs
    """
    from tracktracker.config import settings
    
    global _TRACK_CACHE
    
    if _TRACK_CACHE:
        return _TRACK_CACHE
    
    cache_file = settings.paths.track_cache_path
    
    # Ensure cache directory exists
    settings.ensure_directories()
    
    if cache_file.exists():
        try:
            with open(cache_file, "r") as f:
                _TRACK_CACHE = json.load(f)
            logging.info(f"Loaded {len(_TRACK_CACHE)} cached track entries")
        except Exception as e:
            logging.warning(f"Failed to load track cache: {e}")
            _TRACK_CACHE = {}
    else:
        _TRACK_CACHE = {}
        
    return _TRACK_CACHE


def clear_track_cache() -> None:
    """
    Clear the track search cache.
    """
    from tracktracker.config import settings
    
    global _TRACK_CACHE
    
    cache_file = settings.paths.track_cache_path
    
    if cache_file.exists():
        try:
            cache_file.unlink()
            logging.info("Track cache cleared")
        except Exception as e:
            logging.warning(f"Failed to clear track cache: {e}")
    
    _TRACK_CACHE = {}


def save_track_cache() -> None:
    """Save the track search cache to disk."""
    from tracktracker.config import settings
    
    global _TRACK_CACHE
    
    cache_file = settings.paths.track_cache_path
    
    # Ensure cache directory exists
    settings.ensure_directories()
    
    try:
        with open(cache_file, "w") as f:
            json.dump(_TRACK_CACHE, f)
        logging.debug(f"Saved {len(_TRACK_CACHE)} entries to track cache")
    except Exception as e:
        logging.warning(f"Failed to save track cache: {e}")


@handle_spotify_errors
@retry_with_backoff(max_retries=3, base_delay=2.0, backoff_factor=2.0)
def search_track_with_retry(
    spotify: spotipy.Spotify, 
    artist: str, 
    title: str, 
    verbose: bool = False,
    max_retries: int = 3,  # This is for backward compatibility but is replaced by retry_with_backoff
    strict_matching: bool = True
) -> Optional[str]:
    """
    Search for a track on Spotify with retry logic for rate limits.
    
    Args:
        spotify: Authenticated Spotify client
        artist: Artist name
        title: Track title
        verbose: Whether to print verbose output
        max_retries: Maximum number of retries on rate limit errors
        strict_matching: Whether to use strict matching criteria
        
    Returns:
        Spotify track URI if found, None otherwise
        
    Raises:
        APIError: If the API request fails after retries
        RateLimitError: If rate limit is exceeded even after retries
        AuthenticationError: If authentication fails
        NonRecoverableError: For other non-recoverable errors
    """
    # Generate a cache key for this track
    normalized_artist = re.sub(r'[\'"\(\)\[\]]', '', artist).lower().strip()
    normalized_title = re.sub(r'[\'"\(\)\[\]]', '', title).lower().strip()
    cache_key = f"{normalized_artist}|{normalized_title}"
    
    # Check the cache first
    track_cache = load_track_cache()
    if cache_key in track_cache:
        logging.debug(f"  Cache hit: {artist} - {title}")
        return track_cache[cache_key]
    
    # Handle multiple artists (separated by commas, ampersands, etc.)
    artists_to_try = []
    
    # Check for artists with features (Ft. or feat.)
    if ' Ft. ' in artist or ' ft. ' in artist or ' feat. ' in artist or ' Feat. ' in artist:
        # Get the primary artist (before ft./feat.)
        if ' Ft. ' in artist:
            parts = artist.split(' Ft. ')
        elif ' ft. ' in artist:
            parts = artist.split(' ft. ')
        elif ' feat. ' in artist:
            parts = artist.split(' feat. ')
        else:
            parts = artist.split(' Feat. ')
            
        # Add primary artist first
        artists_to_try.append(parts[0].strip())
        
        # Add featured artist(s)
        if len(parts) > 1:
            featured_artists = parts[1].strip()
            # Featured part might itself have multiple artists
            if ',' in featured_artists:
                for featured in [a.strip() for a in featured_artists.split(',')]:
                    artists_to_try.append(featured)
            else:
                artists_to_try.append(featured_artists)
                
        if verbose:
            logging.debug(f"  Featured artists detected: {artists_to_try}")
        # Also add the full artist string for exact matching
        artists_to_try.append(artist)
            
    # Check for multiple artists separated by commas
    elif ',' in artist:
        # Split by comma and add each artist
        artists_to_try = [a.strip() for a in artist.split(',')]
        if verbose:
            logging.debug(f"  Multiple artists detected (comma-separated): {artists_to_try}")
        # Also add the full artist string for exact matching
        artists_to_try.append(artist)
    # Check for & or 'and' separating artists
    elif ' & ' in artist or ' and ' in artist:
        # Split by & or 'and'
        if ' & ' in artist:
            artists_to_try = [a.strip() for a in artist.split(' & ')]
        else:
            artists_to_try = [a.strip() for a in artist.split(' and ')]
        if verbose:
            logging.debug(f"  Multiple artists detected (joined by '&' or 'and'): {artists_to_try}")
        # Also add the full artist string for exact matching
        artists_to_try.append(artist)
    else:
        # Single artist
        artists_to_try = [artist]
    
    # Search for each artist variation
    for current_artist in artists_to_try:
        # Remove special characters that might interfere with search
        clean_artist = re.sub(r'[\'"\(\)\[\]]', '', current_artist)
        clean_title = re.sub(r'[\'"\(\)\[\]]', '', title)
        
        # Try different search approaches
        search_queries = [
            f"track:\"{clean_title}\" artist:\"{clean_artist}\"",  # Most specific with quotes
            f"track:{clean_title} artist:{clean_artist}",          # Specific without quotes
            f"{clean_artist} {clean_title}"                        # Simple combination of artist and title
        ]
        
        # Try with more comprehensive number-to-word and word-to-number substitutions
        title_for_query = clean_title
        
        # Create word substitution patterns
        # These patterns are more specific for exact matches and whole word replacements
        number_to_word_patterns = [
            ("2", "to"),       # "Be Nice 2 Me" -> "Be Nice to Me"
            ("4", "for"),      # "4 Ever" -> "for Ever" 
            ("u", "you"),      # "U Know" -> "You Know"
            ("ur", "your"),    # "In Ur Eyes" -> "In Your Eyes"
            ("2nite", "tonight"), # "2nite" -> "tonight"
            ("4eva", "forever"),  # "4eva" -> "forever"
            (" r ", " are "),  # "U R Mine" -> "U Are Mine"
        ]
        
        word_to_number_patterns = [
            ("to", "2"),       # "Be Nice to Me" -> "Be Nice 2 Me"
            ("for", "4"),      # "for Ever" -> "4 Ever"
            ("you", "u"),      # "You Know" -> "U Know"
            ("your", "ur"),    # "In Your Eyes" -> "In Ur Eyes"
            ("tonight", "2nite"), # "tonight" -> "2nite"
            ("forever", "4eva"),  # "forever" -> "4eva"
            (" are ", " r "),  # "U Are Mine" -> "U R Mine"
        ]
        
        # Apply number-to-word substitutions for queries
        for old, new in number_to_word_patterns:
            if old in title_for_query:
                # Try both full and word-boundary-aware replacements
                substituted_title = title_for_query.replace(old, new)
                search_queries.append(f"track:\"{substituted_title}\" artist:\"{clean_artist}\"")
                search_queries.append(f"track:{substituted_title} artist:{clean_artist}")
                
                # For specific numbers, also try word boundary sensitive replacements
                if old in ["2", "4", "u"]:
                    # Word boundary aware replacement (e.g. " 2 " -> " to " but not "2nite" -> "tonite")
                    # Create patterns like " 2 ", "2 ", " 2"
                    word_boundary_patterns = [f" {old} ", f"{old} ", f" {old}"]
                    for pattern in word_boundary_patterns:
                        if pattern in title_for_query:
                            boundary_title = title_for_query.replace(pattern, pattern.replace(old, new))
                            search_queries.append(f"track:\"{boundary_title}\" artist:\"{clean_artist}\"")
                
        # Apply word-to-number substitutions for queries
        for old, new in word_to_number_patterns:
            if old in title_for_query:
                # Try both full and word-boundary-aware replacements
                substituted_title = title_for_query.replace(old, new)
                search_queries.append(f"track:\"{substituted_title}\" artist:\"{clean_artist}\"")
                search_queries.append(f"track:{substituted_title} artist:{clean_artist}")
                
                # For specific words, also try word boundary sensitive replacements
                if old in ["to", "for", "you"]:
                    # Word boundary aware replacement
                    word_boundary_patterns = [f" {old} ", f"{old} ", f" {old}"]
                    for pattern in word_boundary_patterns:
                        if pattern in title_for_query:
                            boundary_title = title_for_query.replace(pattern, pattern.replace(old, new))
                            search_queries.append(f"track:\"{boundary_title}\" artist:\"{clean_artist}\"")
                            
        # Try exact pattern for the "Be Nice 2 Me" vs "Be Nice To Me" case
        if "nice to me" in title_for_query.lower():
            exact_match = title_for_query.lower().replace("nice to me", "nice 2 me")
            search_queries.append(f"track:\"{exact_match}\" artist:\"{clean_artist}\"")
        elif "nice 2 me" in title_for_query.lower():
            exact_match = title_for_query.lower().replace("nice 2 me", "nice to me")
            search_queries.append(f"track:\"{exact_match}\" artist:\"{clean_artist}\"")
            
        # For the Bladee specific case, add exact searches for both variations
        if clean_artist.lower() == "bladee" and ("nice to me" in title_for_query.lower() or "nice 2 me" in title_for_query.lower()):
            search_queries.append(f"track:\"be nice to me\" artist:\"bladee\"")
            search_queries.append(f"track:\"be nice 2 me\" artist:\"bladee\"")
        
        for attempt in range(max_retries):
            for query in search_queries:
                try:
                    if verbose:
                        logging.debug(f"  Searching with query: {query}")
                        
                    results = spotify.search(q=query, type="track", limit=10)
                    
                    if results and results["tracks"]["items"]:
                        # Get potential matches
                        tracks = results["tracks"]["items"]
                        
                        # Get the best match using strict criteria
                        best_match = None
                        best_score = 0
                        
                        for track in tracks:
                            # Handle multiple artists in the Spotify result
                            track_artist_names = [a["name"].lower() for a in track["artists"]] if track["artists"] else []
                            primary_track_artist = track_artist_names[0] if track_artist_names else ""
                            
                            # For logging
                            all_artists_str = ", ".join(track_artist_names)
                            
                            track_title = track["name"].lower() if "name" in track else ""
                            
                            if verbose:
                                logging.debug(f"  Potential match: {all_artists_str} - {track_title}")
                            
                            # Calculate match scores
                            from rapidfuzz import fuzz
                            
                            # Artist similarity - check against primary artist and all artist combinations
                            artist_ratio = fuzz.ratio(current_artist.lower(), primary_track_artist)
                            
                            # Also check if our artist appears in any of the track's artists
                            for spotify_artist in track_artist_names:
                                artist_ratio_check = fuzz.ratio(current_artist.lower(), spotify_artist)
                                artist_ratio = max(artist_ratio, artist_ratio_check)
                                
                                # If we found an extremely high match, no need to check others
                                if artist_ratio > 95:
                                    break
                            
                            # Check for common text substitutions (2 for to, 4 for for, etc.)
                            # Replace these in both normalized and track titles before comparison
                            normalized_title_for_check = normalized_title
                            track_title_for_check = track_title.lower()
                            
                            # Define comprehensive substitution patterns
                            number_to_word_substitutions = [
                                (" 2 ", " to "), ("2 ", "to "), (" 2", " to"), ("2", "to"),
                                (" 4 ", " for "), ("4 ", "for "), (" 4", " for"), ("4", "for"),
                                (" u ", " you "), ("u ", "you "), (" u", " you"), ("u", "you"),
                                (" ur ", " your "), ("ur ", "your "), (" ur", " your"), ("ur", "your"),
                                (" r ", " are "), ("r ", "are "), (" r", " are"),
                                ("2nite", "tonight"), ("2night", "tonight"), ("2nit", "tonit"),
                                ("4eva", "forever"), ("4ever", "forever"),
                                ("b4", "before")
                            ]
                            
                            # Specialized substitutions for specific patterns
                            special_pattern_subs = []
                            
                            # Special case for "nice 2 me" vs "nice to me"
                            if "nice 2 me" in normalized_title or "nice to me" in normalized_title:
                                special_pattern_subs.append(("nice 2 me", "nice to me"))
                            
                            # Bladee special case for "Be Nice 2 Me" vs "Be Nice To Me"
                            if current_artist.lower() == "bladee" and ("nice 2 me" in normalized_title or "nice to me" in normalized_title):
                                special_pattern_subs.append(("nice 2 me", "nice to me"))
                                special_pattern_subs.append(("be nice 2 me", "be nice to me"))
                            
                            # Create two versions for comparison - original to word and word to original
                            normalized_title_word_version = normalized_title
                            track_title_word_version = track_title.lower()
                            
                            # Apply number to word substitutions for better comparison
                            for old, new in number_to_word_substitutions:
                                normalized_title_word_version = normalized_title_word_version.replace(old, new)
                                track_title_word_version = track_title_word_version.replace(old, new)
                            
                            # Apply special pattern substitutions
                            for old, new in special_pattern_subs:
                                if old in normalized_title:
                                    normalized_title_word_version = normalized_title_word_version.replace(old, new)
                                if old in track_title.lower():
                                    track_title_word_version = track_title_word_version.replace(old, new)
                            
                            # Calculate title ratio after number-to-word substitutions
                            title_ratio_with_subs = fuzz.ratio(normalized_title_word_version, track_title_word_version)
                            
                            # Double-check the specific Bladee case with a targeted match
                            if current_artist.lower() == "bladee":
                                # If either title contains "nice to me" or "nice 2 me", give a direct comparison boost
                                if ("nice 2 me" in normalized_title.lower() and "nice to me" in track_title.lower()) or \
                                   ("nice to me" in normalized_title.lower() and "nice 2 me" in track_title.lower()):
                                    title_ratio_with_subs = max(title_ratio_with_subs, 95)  # Strong boost for this case
                            
                            # Title similarity - use the better of the two scores
                            title_ratio = fuzz.ratio(normalized_title, track_title.lower())
                            title_ratio = max(title_ratio, title_ratio_with_subs)
                            
                            # Check for 1-2 character differences (likely typos)
                            try:
                                import Levenshtein
                                if len(normalized_title) > 5 and len(track_title) > 5:  # Only for reasonably long titles
                                    # Levenshtein distance of 1 or 2
                                    lev_distance = Levenshtein.distance(normalized_title, track_title.lower())
                                    if lev_distance <= 2:  # Just 1-2 character differences
                                        title_ratio = max(title_ratio, 95)  # Strong boost for tiny edit distances
                                        if verbose:
                                            logging.debug(f"  Found possible title typo (Levenshtein distance = {lev_distance})")
                                
                                # Also check artist for typos (like Haustchildt vs Hauschildt)
                                if len(current_artist) > 4:  # Only for reasonably long artist names
                                    lev_artist_distance = Levenshtein.distance(current_artist.lower(), primary_track_artist)
                                    if lev_artist_distance <= 2:  # Just 1-2 character differences
                                        artist_ratio = max(artist_ratio, 95)  # Strong boost for tiny edit distances
                                        if verbose:
                                            logging.debug(f"  Found possible artist typo (Levenshtein distance = {lev_artist_distance})")
                            except ImportError:
                                # Fall back to fuzzy matching if Levenshtein is not available
                                pass
                            
                            # Overall similarity
                            overall_score = (artist_ratio + title_ratio) / 2
                            
                            if verbose:
                                logging.debug(f"  Match scores: Artist={artist_ratio}, Title={title_ratio}, Overall={overall_score}")
                            
                            # Strict matching criteria
                            if strict_matching:
                                # Case 1: Both artist and title have good individual matches
                                if artist_ratio >= 80 and title_ratio >= 80 and overall_score > best_score:
                                    best_match = track
                                    best_score = overall_score
                                
                                # Case 2: Artist is an exact/near-exact match and title is a partial match
                                # This handles classical pieces, live recordings, and other special cases
                                elif artist_ratio >= 95 and title_ratio >= 65 and overall_score > best_score:
                                    # Check if the query title is contained within the result title
                                    # or the result title is contained within the query title
                                    if (normalized_title in track_title.lower() or 
                                        track_title.lower() in normalized_title or
                                        normalized_title_word_version in track_title_word_version or
                                        track_title_word_version in normalized_title_word_version):
                                        best_match = track
                                        best_score = overall_score
                                        if verbose:
                                            logging.debug(f"  Special case match: Exact artist with partial title")
                                            
                                    # Special case for number-word substitutions (like "2" vs "to")
                                    # Check if these are likely the same track with number-word variations
                                    elif (("2" in normalized_title and "to" in track_title.lower()) or
                                          ("to" in normalized_title and "2" in track_title.lower()) or
                                          ("4" in normalized_title and "for" in track_title.lower()) or
                                          ("for" in normalized_title and "4" in track_title.lower()) or
                                          ("u" in normalized_title and "you" in track_title.lower()) or
                                          ("you" in normalized_title and "u" in track_title.lower())):
                                        
                                        # Further check if these appear to be the same song with number/word substitutions
                                        # by comparing the word versions
                                        if title_ratio_with_subs >= 85:  # Higher threshold for substitution-based matches
                                            best_match = track
                                            best_score = overall_score
                                            if verbose:
                                                logging.debug(f"  Special case match: Number-word substitution detected with good title similarity")
                                
                                # Case 3: Title is an exact/near-exact match and artist is a good match
                                # This handles artist name variations and collaborations
                                elif title_ratio >= 95 and artist_ratio >= 70 and overall_score > best_score:
                                    best_match = track
                                    best_score = overall_score
                                    if verbose:
                                        logging.debug(f"  Special case match: Exact title with good artist match")
                            else:
                                # Less strict, just use overall score
                                if overall_score > best_score and overall_score >= 75:
                                    best_match = track
                                    best_score = overall_score
                        
                        # If we found a good match
                        if best_match:
                            track_uri = best_match["uri"]
                            
                            # Log match details
                            if verbose:
                                found_artists = [a["name"] for a in best_match["artists"]] if best_match["artists"] else ["Unknown"]
                                found_artist_str = ", ".join(found_artists)
                                found_title = best_match["name"] if "name" in best_match else "Unknown"
                                logging.debug(f"  Found match: {found_artist_str} - {found_title} (Score: {best_score})")
                            
                            # Cache the result
                            track_cache[cache_key] = track_uri
                            if attempt == 0:  # Only save cache on first attempt to avoid excessive writes
                                save_track_cache()
                            
                            return track_uri
                        else:
                            if verbose:
                                logging.debug(f"  No matches met the strict criteria for {current_artist} - {title}")
                        
                except SpotifyException as e:
                    if e.http_status == 429:  # Rate limit error
                        # Get retry-after time from headers, default to exponential backoff
                        retry_after = int(e.headers.get("Retry-After", 2 ** attempt))
                        logging.warning(f"  Rate limit hit, retrying in {retry_after} seconds")
                        time.sleep(retry_after)
                    else:
                        # Log other Spotify errors
                        if verbose:
                            logging.warning(f"  Spotify search error with query '{query}': {e}")
                except Exception as e:
                    # Log general errors only if verbose is enabled
                    if verbose:
                        logging.warning(f"  Spotify search error with query '{query}': {e}")

    # Return None if no track was found after trying all queries and retries
    return None


@handle_spotify_errors
@retry_with_backoff(max_retries=5, base_delay=2.0, backoff_factor=2.0)
def add_tracks_to_playlist_with_retry(
    spotify: spotipy.Spotify, 
    playlist_id: str, 
    tracks: List[Dict[str, str]], 
    verbose: bool = False,
    max_retries: int = 3,  # For backward compatibility, retry_with_backoff decorator handles this now
    parallel_searches: int = 3,  # Number of parallel search operations
    search_batch_size: int = 10  # Number of tracks to search in each batch
) -> Tuple[List[str], List[Dict[str, str]], Dict[str, str]]:
    """
    Add tracks to a Spotify playlist with retry logic for rate limits.
    
    Args:
        spotify: Authenticated Spotify client
        playlist_id: ID of the playlist to add tracks to
        tracks: List of tracks with 'artist' and 'title' keys
        verbose: Whether to print verbose output
        max_retries: Maximum number of retries on rate limit errors
        parallel_searches: Number of parallel search operations
        search_batch_size: Number of tracks to search in each batch
        
    Returns:
        Tuple of (added_track_uris, tracks_not_found, search_results)
        
    Raises:
        APIError: If the API request fails after retries
        RateLimitError: If rate limit is exceeded even after retries
        AuthenticationError: If authentication fails
        NonRecoverableError: For other non-recoverable errors
    """
    track_uris = []
    tracks_not_found = []
    search_results = {}  # Dictionary to track search results for all tracks
    
    total_tracks = len(tracks)
    logging.info(f"Processing {total_tracks} tracks using batch processing")
    
    # Get track cache first to reduce duplicative API calls
    cache = load_track_cache()
    
    # Define the search function for batch processing
    def search_single_track(track):
        try:
            artist = track["artist"]
            title = track["title"]
            
            # Create track signature for the search results dictionary
            normalized_artist = re.sub(r'[\'"\(\)\[\]]', '', artist).lower().strip()
            normalized_title = re.sub(r'[\'"\(\)\[\]]', '', title).lower().strip()
            track_sig = f"{normalized_artist}|{normalized_title}"
            
            # Check if track is already in cache
            if track_sig in cache:
                if verbose:
                    logging.debug(f"  Cache hit: {artist} - {title}")
                return {
                    "track": track,
                    "uri": cache[track_sig],
                    "signature": track_sig,
                    "found": bool(cache[track_sig])  # Empty string means not found
                }
            
            # Use the retry-enabled search function with strict matching
            track_uri = search_track_with_retry(
                spotify, artist, title, verbose, max_retries, strict_matching=True
            )
            
            return {
                "track": track,
                "uri": track_uri,
                "signature": track_sig,
                "found": bool(track_uri)
            }
        except Exception as e:
            # Log the error but don't fail the entire batch
            logging.warning(f"  Error searching for track {track.get('artist', '')} - {track.get('title', '')}: {e}")
            return {
                "track": track,
                "uri": None,
                "signature": None,
                "error": str(e),
                "found": False
            }
    
    # Use batch processing for track searches but with more conservative parameters
    search_results_list = batch_process(
        items=tracks,
        process_func=search_single_track,
        max_workers=2,  # Reduce parallel workers to avoid rate limits
        max_batch_size=5,  # Process smaller batches
        batch_delay=2.5,  # Longer delay between batches
        description="tracks",
        verbose=verbose
    )
    
    # Process search results
    for track_item, search_result in search_results_list:
        if search_result is None:
            # Search failed completely, add to not found
            tracks_not_found.append(track_item)
            continue
            
        # Add to search results dictionary
        if search_result["signature"]:
            search_results[search_result["signature"]] = search_result["uri"] or ""
            
        # Process search result
        if search_result["found"] and search_result["uri"]:
            track_uris.append(search_result["uri"])
            if verbose:
                logging.debug(f"  ✓ Found: {track_item['artist']} - {track_item['title']}")
        else:
            tracks_not_found.append(track_item)
            if verbose:
                logging.info(f"  × Not found: {track_item['artist']} - {track_item['title']}")
            
    # Add tracks to playlist in batches
    if track_uris:
        logging.info(f"Adding {len(track_uris)} tracks to playlist in batches")
        batch_size = 100  # Spotify API limit
        
        for i in range(0, len(track_uris), batch_size):
            batch = track_uris[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(track_uris) + batch_size - 1) // batch_size
            
            logging.info(f"  Processing batch {batch_num}/{total_batches} ({len(batch)} tracks)")
            
            try:
                # Add the batch with automatic retries from decorator
                spotify.playlist_add_items(playlist_id, batch)
                logging.info(f"  ✓ Successfully added batch {batch_num}")
            except (APIError, AuthenticationError, NonRecoverableError) as e:
                # Log the specific error
                logging.error(f"Error adding tracks to playlist (batch {batch_num}): {e}")
                # Convert to ValueError for backward compatibility
                raise ValueError(f"Failed to add tracks to playlist: {e}") from e
    
    # Also save a CSV with the search results
    csv_file = save_tracklist_to_csv(tracks, f"{playlist_id}_results", None, search_results)
    logging.info(f"Search results saved to {csv_file}")
    
    return track_uris, tracks_not_found, search_results


def get_playlist_url(spotify: spotipy.Spotify, playlist_id: str) -> str:
    """
    Get the public URL for a Spotify playlist.
    
    Args:
        spotify: Authenticated Spotify client
        playlist_id: ID of the playlist
        
    Returns:
        Public URL for the playlist
        
    Raises:
        ValueError: If retrieving the playlist info fails
    """
    try:
        playlist_info = spotify.playlist(playlist_id)
        return playlist_info['external_urls']['spotify']
    except Exception as e:
        logging.error(f"Could not retrieve playlist URL: {e}")
        raise ValueError(f"Could not retrieve playlist URL: {e}")


def save_tracklist_to_csv(tracks: List[Dict[str, str]], show_name: str, file_path: Optional[str] = None, search_results: Optional[Dict[str, str]] = None) -> str:
    """
    Save tracklist to a CSV file for manual verification.
    
    Args:
        tracks: List of tracks with 'artist' and 'title' keys
        show_name: Name of the show
        file_path: Optional path to save the CSV file (defaults to show_name_tracklist.csv)
        search_results: Optional dictionary mapping track signatures to search results
        
    Returns:
        Path to the saved CSV file
    """
    if not file_path:
        # Use the show name to create a filename
        clean_name = show_name.replace(" ", "_").replace("/", "_").replace("\\", "_").lower()
        file_path = f"{clean_name}_tracklist.csv"
    
    with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        # Write header
        writer.writerow(['Artist', 'Title', 'Found on Spotify?', 'Spotify URI', 'Corrections'])
        
        # Write each track
        for track in tracks:
            artist = track.get('artist', '')
            title = track.get('title', '')
            
            # Check if we have search results
            found_status = 'Unknown'
            spotify_uri = ''
            
            if search_results:
                # Generate the track signature used for lookup
                normalized_artist = re.sub(r'[\'"\(\)\[\]]', '', artist).lower().strip()
                normalized_title = re.sub(r'[\'"\(\)\[\]]', '', title).lower().strip()
                track_sig = f"{normalized_artist}|{normalized_title}"
                
                if track_sig in search_results:
                    found_status = 'Yes'
                    spotify_uri = search_results[track_sig]
                else:
                    found_status = 'No'
            
            writer.writerow([
                artist,
                title,
                found_status,
                spotify_uri,
                ''  # Leave blank for corrections
            ])
    
    logging.info(f"Tracklist saved to {file_path} for manual verification")
    return file_path


def add_tracks_to_playlist(
    spotify: spotipy.Spotify, 
    playlist_id: str, 
    tracks: List[Dict[str, str]], 
    verbose: bool = False
) -> Tuple[List[str], List[Dict[str, str]], Dict[str, str]]:
    """
    Add tracks to a Spotify playlist.
    
    Wrapper around add_tracks_to_playlist_with_retry with default max_retries.
    
    Args:
        spotify: Authenticated Spotify client
        playlist_id: ID of the playlist to add tracks to
        tracks: List of tracks with 'artist' and 'title' keys
        verbose: Whether to print verbose output
        
    Returns:
        Tuple of (added_track_uris, tracks_not_found, search_results)
    """
    return add_tracks_to_playlist_with_retry(spotify, playlist_id, tracks, verbose)


def archive_show_history(
    spotify: spotipy.Spotify,
    show_name: str,
    episodes_data: List[Dict],
    verbose: bool = False
) -> Tuple[str, Dict[str, int]]:
    """
    Archive a show's entire history into a single playlist.
    
    Args:
        spotify: Authenticated Spotify client
        show_name: Name of the show
        episodes_data: List of episode data, each with 'episode_title' and 'tracks' keys
        verbose: Whether to print verbose output
        
    Returns:
        Tuple of (playlist_url, stats_dict)
        
    Raises:
        ValueError: If playlist creation or track addition fails
    """
    # For backwards compatibility, now just calls update_show_archive
    # which handles both creating new playlists and updating existing ones
    return update_show_archive(spotify, show_name, episodes_data, verbose)


def update_show_archive(
    spotify: spotipy.Spotify,
    show_name: str,
    episodes_data: List[Dict],
    verbose: bool = False,
    chunk_size: Optional[int] = None,
    delay_between_chunks: float = 60.0
) -> Tuple[str, Dict[str, int]]:
    """
    Update an existing show archive playlist with new episodes, or create a new one if it doesn't exist.
    
    Args:
        spotify: Authenticated Spotify client
        show_name: Name of the show
        episodes_data: List of episode data, each with 'episode_title' and 'tracks' keys
        verbose: Whether to print verbose output
        
    Returns:
        Tuple of (playlist_url, stats_dict)
        
    Raises:
        ValueError: If playlist creation or track addition fails
    """
    # Import here to avoid circular imports
    from tracktracker import utils
    
    # Format playlist name for this show archive
    playlist_name = utils.format_show_archive_playlist_name(show_name)
    
    # Get earliest and latest dates from episodes data
    earliest_date = None
    latest_date = None
    
    for episode in episodes_data:
        if "broadcast_date" in episode:
            date_str = episode["broadcast_date"]
            try:
                # Parse the date string to a datetime object
                episode_date = datetime.strptime(date_str, "%Y-%m-%d")
                
                # Update earliest date
                if earliest_date is None or episode_date < earliest_date:
                    earliest_date = episode_date
                
                # Update latest date
                if latest_date is None or episode_date > latest_date:
                    latest_date = episode_date
            except (ValueError, TypeError):
                # Skip dates that can't be parsed
                continue
    
    # Format the description with date range if available
    if earliest_date and latest_date:
        # Format dates as MM/DD/YY - handle platform differences
        try:
            # Try with the no-padding format (works on Linux/macOS)
            earliest_str = earliest_date.strftime("%-m/%-d/%y")
            latest_str = latest_date.strftime("%-m/%-d/%y")
        except ValueError:
            # Fallback for Windows which doesn't support the - flag
            earliest_str = earliest_date.strftime("%m/%d/%y").lstrip("0").replace("/0", "/")
            latest_str = latest_date.strftime("%m/%d/%y").lstrip("0").replace("/0", "/")
        # Add "via TrackTracker" to the description
        description = f"Archive of {show_name} from NTS Radio. Updated {latest_str} via TrackTracker."
    else:
        # If we don't have dates, use a simpler format
        description = f"Archive of {show_name} from NTS Radio. via TrackTracker."
    
    # Check if the archive playlist already exists
    existing_playlist_id = find_existing_playlist(spotify, playlist_name)
    
    # Create new playlist if none exists
    if existing_playlist_id is None:
        logging.info(f"Creating new archive playlist: {playlist_name}")
        playlist_id = create_playlist(spotify, playlist_name, description)
        existing_tracks = set()
    else:
        playlist_id = existing_playlist_id
        logging.info(f"Updating existing archive playlist: {playlist_name}")
        # Get existing tracks in the playlist
        existing_tracks = get_existing_playlist_tracks(spotify, playlist_id)
    
    # Track metrics
    all_tracks = []
    processed_episodes = 0
    stats = {
        "total_episodes": len(episodes_data),
        "found_tracks": 0,
        "new_tracks_added": 0,
        "not_found_tracks": 0,
        "total_tracks": 0,
        "already_in_playlist": 0
    }
    
    # Process episodes in chunks if requested
    if chunk_size is not None and chunk_size > 0:
        # Process episodes in smaller chunks to avoid rate limits
        total_episodes = len(episodes_data)
        chunks = []
        
        # Divide episodes into chunks
        for i in range(0, total_episodes, chunk_size):
            chunk = episodes_data[i:i + chunk_size]
            chunks.append(chunk)
            
        logging.info(f"Processing {total_episodes} episodes in {len(chunks)} chunks of up to {chunk_size} episodes each")
        
        # Process each chunk
        for chunk_idx, chunk in enumerate(chunks):
            logging.info(f"Processing chunk {chunk_idx + 1}/{len(chunks)} ({len(chunk)} episodes)")
            
            # Process episodes in this chunk
            for episode_data in chunk:
                episode_title = episode_data.get("episode_title", "Unknown Episode")
                tracks = episode_data.get("tracks", [])
                
                if not tracks:
                    logging.warning(f"No tracks found for episode: {episode_title}")
                    continue
                    
                logging.info(f"Processing episode: {episode_title} ({len(tracks)} tracks)")
                
                # Add all tracks to our collection
                for track in tracks:
                    # Add episode metadata to track
                    track["episode_title"] = episode_title
                    all_tracks.append(track)
                
                processed_episodes += 1
            
            # Pause between chunks (except for the last chunk)
            if chunk_idx < len(chunks) - 1:
                logging.info(f"Pausing for {delay_between_chunks} seconds before next chunk...")
                time.sleep(delay_between_chunks)
    else:
        # Process all episodes at once (original behavior)
        for episode_data in episodes_data:
            episode_title = episode_data.get("episode_title", "Unknown Episode")
            tracks = episode_data.get("tracks", [])
            
            if not tracks:
                logging.warning(f"No tracks found for episode: {episode_title}")
                continue
                
            logging.info(f"Processing episode: {episode_title} ({len(tracks)} tracks)")
            
            # Add all tracks to our collection
            for track in tracks:
                # Add episode metadata to track
                track["episode_title"] = episode_title
                all_tracks.append(track)
            
            processed_episodes += 1
    
    # Update total tracks stat
    stats["total_tracks"] = len(all_tracks)
    logging.info(f"Found {stats['total_tracks']} total tracks across {processed_episodes} episodes")
    
    # Add all tracks to the playlist
    if all_tracks:
        found_uris, not_found, search_results = add_tracks_to_playlist_with_retry(
            spotify, playlist_id, all_tracks, verbose
        )
        
        # Count how many tracks were actually new
        new_tracks = [uri for uri in found_uris if uri not in existing_tracks]
        
        stats["found_tracks"] = len(found_uris)
        stats["new_tracks_added"] = len(new_tracks)
        stats["already_in_playlist"] = len(found_uris) - len(new_tracks)
        stats["not_found_tracks"] = len(not_found)
        
        # Save a detailed CSV with search results
        save_tracklist_to_csv(all_tracks, f"{show_name}_archive_results", None, search_results)
        
        logging.info(f"Added {stats['new_tracks_added']} new tracks to archive playlist")
        logging.info(f"Found {stats['already_in_playlist']} tracks already in the playlist")
        logging.info(f"Could not find {stats['not_found_tracks']} tracks")
    
    # Get the playlist URL
    playlist_url = get_playlist_url(spotify, playlist_id)
    return playlist_url, stats


def find_existing_playlist(spotify: spotipy.Spotify, playlist_name: str) -> Optional[str]:
    """
    Find an existing playlist with the given name.
    
    Args:
        spotify: Authenticated Spotify client
        playlist_name: Name of the playlist to find
        
    Returns:
        Playlist ID if found, None otherwise
    """
    user_id = spotify.me()["id"]
    
    # Get user's playlists and check for matching name
    playlists = []
    offset = 0
    limit = 50
    
    # Fetch all playlists
    while True:
        results = spotify.user_playlists(user_id, limit=limit, offset=offset)
        playlists.extend(results['items'])
        if results['next']:
            offset += limit
        else:
            break
    
    # Find matching playlist
    for playlist in playlists:
        if playlist['name'] == playlist_name:
            logging.info(f"Found existing playlist: {playlist_name}")
            return playlist['id']
    
    logging.info(f"No existing playlist found with name: {playlist_name}")
    return None


def get_existing_playlist_tracks(spotify: spotipy.Spotify, playlist_id: str) -> Set[str]:
    """
    Get all track URIs from an existing playlist.
    
    Args:
        spotify: Authenticated Spotify client
        playlist_id: ID of the playlist
        
    Returns:
        Set of track URIs in the playlist
    """
    existing_tracks = set()
    offset = 0
    limit = 100
    
    # Fetch all tracks from existing playlist
    while True:
        results = spotify.playlist_items(playlist_id, limit=limit, offset=offset)
        for item in results['items']:
            if item['track'] and 'uri' in item['track']:
                existing_tracks.add(item['track']['uri'])
        
        if results['next']:
            offset += limit
        else:
            break
    
    logging.info(f"Found {len(existing_tracks)} existing tracks in playlist")
    return existing_tracks


def process_episode_tracks(
    spotify: spotipy.Spotify,
    show_name: str,
    episode_title: str,
    broadcast_date: str,
    tracks: List[Dict[str, str]],
    verbose: bool = False
) -> Tuple[str, Dict[str, int]]:
    """
    Process tracks from a single episode and add them to a playlist.
    Checks if a playlist already exists before creating a new one.
    
    Args:
        spotify: Authenticated Spotify client
        show_name: Name of the show
        episode_title: Title of the episode
        broadcast_date: Broadcast date of the episode
        tracks: List of tracks with 'artist' and 'title' keys
        verbose: Whether to print verbose output
        
    Returns:
        Tuple of (playlist_url, stats_dict)
        
    Raises:
        ValueError: If playlist creation or track addition fails
    """
    # Import here to avoid circular imports
    from tracktracker import utils
    
    # Format playlist name with date in US format
    playlist_name = utils.format_episode_playlist_name(show_name, episode_title, broadcast_date)
    
    # Format the broadcast date as MM/DD/YY
    try:
        # Parse the broadcast_date (which should be in YYYY-MM-DD format)
        episode_date = datetime.strptime(broadcast_date, "%Y-%m-%d")
        # Format it as MM/DD/YY without leading zeros
        try:
            # Try with the no-padding format (works on Linux/macOS)
            date_str = episode_date.strftime("%-m/%-d/%y")
        except ValueError:
            # Fallback for Windows which doesn't support the - flag
            date_str = episode_date.strftime("%m/%d/%y").lstrip("0").replace("/0", "/")
        # Use the standardized format with "via TrackTracker"
        description = f"Archive of {show_name} from NTS Radio. Updated {date_str} via TrackTracker."
    except (ValueError, TypeError):
        # Fallback if there's an issue with the date
        description = f"Archive of {show_name} from NTS Radio. via TrackTracker."
    
    # Check if a playlist with this name already exists
    existing_playlist_id = find_existing_playlist(spotify, playlist_name)
    
    # Stats dictionary to track results
    stats = {
        "total_tracks": len(tracks),
        "found_tracks": 0,
        "new_tracks_added": 0,
        "not_found_tracks": 0,
        "already_in_playlist": 0
    }
    
    if existing_playlist_id is None:
        # Create a new playlist if one doesn't exist
        logging.info(f"Creating new playlist: {playlist_name}")
        playlist_id = create_playlist(spotify, playlist_name, description)
        existing_tracks = set()
    else:
        # Use the existing playlist
        playlist_id = existing_playlist_id
        logging.info(f"Updating existing playlist: {playlist_name}")
        existing_tracks = get_existing_playlist_tracks(spotify, playlist_id)
    
    # Add tracks to the playlist
    if tracks:
        found_uris, not_found, search_results = add_tracks_to_playlist_with_retry(
            spotify, playlist_id, tracks, verbose
        )
        
        # Count how many tracks were actually new
        new_tracks = [uri for uri in found_uris if uri not in existing_tracks]
        
        stats["found_tracks"] = len(found_uris)
        stats["new_tracks_added"] = len(new_tracks)
        stats["already_in_playlist"] = len(found_uris) - len(new_tracks)
        stats["not_found_tracks"] = len(not_found)
        
        # Save a detailed CSV with search results
        save_tracklist_to_csv(tracks, f"{show_name}_{episode_title}_results", None, search_results)
    
    # Get the playlist URL
    playlist_url = get_playlist_url(spotify, playlist_id)
    return playlist_url, stats 