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
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple, Optional, Set

import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotipy.exceptions import SpotifyException


# Global track search cache
_TRACK_CACHE = {}

def authenticate(scope: str) -> spotipy.Spotify:
    """
    Authenticate with Spotify API.
    
    Args:
        scope: Spotify API permission scope
        
    Returns:
        Authenticated Spotify client
        
    Raises:
        ValueError: If authentication fails due to missing credentials
    """
    try:
        # Set up cache directory
        cache_dir = Path.home() / ".tracktracker"
        if not cache_dir.exists():
            cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Create a cache file path for persistent token storage
        cache_path = cache_dir / "spotify_token.json"
        
        # Create a Spotify client using credentials from environment variables
        client = spotipy.Spotify(auth_manager=SpotifyOAuth(
            client_id=os.environ.get("SPOTIFY_CLIENT_ID"),
            client_secret=os.environ.get("SPOTIFY_CLIENT_SECRET"),
            redirect_uri=os.environ.get("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback"),
            scope=scope,
            cache_path=str(cache_path)
        ))
        return client
    except Exception as e:
        logging.error(f"Failed to authenticate with Spotify: {e}")
        raise ValueError(
            "Spotify authentication failed. Make sure you have set the following environment variables:\n"
            "  - SPOTIFY_CLIENT_ID\n"
            "  - SPOTIFY_CLIENT_SECRET\n"
            "  - SPOTIFY_REDIRECT_URI (optional, defaults to http://127.0.0.1:8888/callback)"
        )


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
        ValueError: If playlist creation fails
    """
    user_id = spotify.me()["id"]
    
    try:
        playlist = spotify.user_playlist_create(
            user=user_id,
            name=playlist_name,
            public=True,
            description=description
        )
        return playlist["id"]
    except Exception as e:
        logging.error(f"Failed to create Spotify playlist: {e}")
        raise ValueError(f"Failed to create Spotify playlist: {e}")


def load_track_cache() -> Dict[str, str]:
    """
    Load the track search cache from disk.
    
    Returns:
        Dictionary mapping track signatures to Spotify URIs
    """
    global _TRACK_CACHE
    
    if _TRACK_CACHE:
        return _TRACK_CACHE
        
    cache_dir = Path.home() / ".tracktracker"
    cache_file = cache_dir / "track_cache.json"
    
    if not cache_dir.exists():
        cache_dir.mkdir(parents=True, exist_ok=True)
    
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


def save_track_cache() -> None:
    """Save the track search cache to disk."""
    cache_dir = Path.home() / ".tracktracker"
    cache_file = cache_dir / "track_cache.json"
    
    if not cache_dir.exists():
        cache_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        with open(cache_file, "w") as f:
            json.dump(_TRACK_CACHE, f)
        logging.debug(f"Saved {len(_TRACK_CACHE)} entries to track cache")
    except Exception as e:
        logging.warning(f"Failed to save track cache: {e}")


def search_track_with_retry(
    spotify: spotipy.Spotify, 
    artist: str, 
    title: str, 
    verbose: bool = False,
    max_retries: int = 3
) -> Optional[str]:
    """
    Search for a track on Spotify with retry logic for rate limits.
    
    Args:
        spotify: Authenticated Spotify client
        artist: Artist name
        title: Track title
        verbose: Whether to print verbose output
        max_retries: Maximum number of retries on rate limit errors
        
    Returns:
        Spotify track URI if found, None otherwise
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
    
    # Remove special characters that might interfere with search
    clean_artist = re.sub(r'[\'"\(\)\[\]]', '', artist)
    clean_title = re.sub(r'[\'"\(\)\[\]]', '', title)
    
    # Try different search approaches
    search_queries = [
        f"track:{clean_title} artist:{clean_artist}",  # Most specific
        f"{clean_artist} {clean_title}",               # Simple combination
        f"{clean_title} {clean_artist}"                # Reversed order
    ]
    
    for attempt in range(max_retries):
        for query in search_queries:
            try:
                results = spotify.search(q=query, type="track", limit=5)
                
                if results and results["tracks"]["items"]:
                    # Get the track URI
                    track_uri = results["tracks"]["items"][0]["uri"]
                    
                    # Cache the result
                    track_cache[cache_key] = track_uri
                    if attempt == 0:  # Only save cache on first attempt to avoid excessive writes
                        save_track_cache()
                    
                    return track_uri
                    
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


def add_tracks_to_playlist_with_retry(
    spotify: spotipy.Spotify, 
    playlist_id: str, 
    tracks: List[Dict[str, str]], 
    verbose: bool = False,
    max_retries: int = 3
) -> Tuple[List[str], List[Dict[str, str]]]:
    """
    Add tracks to a Spotify playlist with retry logic for rate limits.
    
    Args:
        spotify: Authenticated Spotify client
        playlist_id: ID of the playlist to add tracks to
        tracks: List of tracks with 'artist' and 'title' keys
        verbose: Whether to print verbose output
        max_retries: Maximum number of retries on rate limit errors
        
    Returns:
        Tuple of (added_track_uris, tracks_not_found)
    """
    track_uris = []
    tracks_not_found = []
    
    total_tracks = len(tracks)
    logging.info(f"Processing {total_tracks} tracks")
    
    # Find track URIs for all tracks
    for i, track in enumerate(tracks):
        artist = track["artist"]
        title = track["title"]

        logging.debug(f"  [{i+1}/{total_tracks}] Searching for: {artist} - {title}")

        # Use the retry-enabled search function
        track_uri = search_track_with_retry(spotify, artist, title, verbose, max_retries)

        if track_uri:
            track_uris.append(track_uri)
            logging.debug(f"  ✓ Found: {track_uri}")
        else:
            tracks_not_found.append(track)
            logging.info(f"  × Not found: {artist} - {title}")
    
    # Add tracks to playlist in batches with retry logic
    if track_uris:
        logging.info(f"Adding {len(track_uris)} tracks to playlist in batches")
        batch_size = 100  # Spotify API limit
        
        for i in range(0, len(track_uris), batch_size):
            batch = track_uris[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(track_uris) + batch_size - 1) // batch_size
            
            logging.info(f"  Processing batch {batch_num}/{total_batches} ({len(batch)} tracks)")
            
            for attempt in range(max_retries):
                try:
                    spotify.playlist_add_items(playlist_id, batch)
                    logging.info(f"  ✓ Successfully added batch {batch_num}")
                    break
                except SpotifyException as e:
                    if e.http_status == 429 and attempt < max_retries - 1:
                        retry_after = int(e.headers.get("Retry-After", 2 ** attempt))
                        logging.warning(f"  Rate limit hit, retrying batch {batch_num} in {retry_after} seconds")
                        time.sleep(retry_after)
                    else:
                        logging.error(f"Error adding tracks to playlist: {e}")
                        raise ValueError(f"Failed to add tracks to playlist: {e}")
                except Exception as e:
                    logging.error(f"Error adding tracks to playlist: {e}")
                    raise ValueError(f"Failed to add tracks to playlist: {e}")
    
    return track_uris, tracks_not_found


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


def add_tracks_to_playlist(
    spotify: spotipy.Spotify, 
    playlist_id: str, 
    tracks: List[Dict[str, str]], 
    verbose: bool = False
) -> Tuple[List[str], List[Dict[str, str]]]:
    """
    Add tracks to a Spotify playlist.
    
    Wrapper around add_tracks_to_playlist_with_retry with default max_retries.
    
    Args:
        spotify: Authenticated Spotify client
        playlist_id: ID of the playlist to add tracks to
        tracks: List of tracks with 'artist' and 'title' keys
        verbose: Whether to print verbose output
        
    Returns:
        Tuple of (added_track_uris, tracks_not_found)
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
    verbose: bool = False
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
        description = f"Archive of {show_name} from NTS Radio, {earliest_str} - {latest_str}."
    else:
        description = f"Archive of {show_name} from NTS Radio."
    
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
    
    # Process each episode's tracks
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
        found_uris, not_found = add_tracks_to_playlist_with_retry(
            spotify, playlist_id, all_tracks, verbose
        )
        
        # Count how many tracks were actually new
        new_tracks = [uri for uri in found_uris if uri not in existing_tracks]
        
        stats["found_tracks"] = len(found_uris)
        stats["new_tracks_added"] = len(new_tracks)
        stats["already_in_playlist"] = len(found_uris) - len(new_tracks)
        stats["not_found_tracks"] = len(not_found)
        
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
        description = f"Archive of {show_name} from NTS Radio, {date_str}."
    except (ValueError, TypeError):
        # Fallback if there's an issue with the date
        description = f"Archive of {show_name} from NTS Radio."
    
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
        found_uris, not_found = add_tracks_to_playlist_with_retry(
            spotify, playlist_id, tracks, verbose
        )
        
        # Count how many tracks were actually new
        new_tracks = [uri for uri in found_uris if uri not in existing_tracks]
        
        stats["found_tracks"] = len(found_uris)
        stats["new_tracks_added"] = len(new_tracks)
        stats["already_in_playlist"] = len(found_uris) - len(new_tracks)
        stats["not_found_tracks"] = len(not_found)
    
    # Get the playlist URL
    playlist_url = get_playlist_url(spotify, playlist_id)
    return playlist_url, stats 