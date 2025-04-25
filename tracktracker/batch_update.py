"""
Batch update module for tracktracker.

This module provides functionality to check for new NTS Radio episodes and update
Spotify playlists and website information accordingly.
"""

import logging
import sys
import time
from datetime import datetime
from typing import Dict, List, Tuple, Any, Optional

from tracktracker.scrapers import nts
from tracktracker import spotify
from tracktracker import utils
from tracktracker import website
from tracktracker.api_utils import (
    retry_with_backoff,
    APIError,
    RateLimitError,
    AuthenticationError,
    NonRecoverableError,
    DataValidationError,
    TrackTrackerError,
)


def get_latest_episode_date(episodes_data: List[Dict]) -> Optional[str]:
    """
    Get the most recent episode date from episode data.
    
    Args:
        episodes_data: List of episode data, each with 'broadcast_date' key
        
    Returns:
        Latest broadcast date in ISO format (YYYY-MM-DD), or None if not found
    """
    if not episodes_data:
        return None
    
    # Collect all dates
    dates = []
    for episode in episodes_data:
        episode_date = episode.get("broadcast_date", "")
        if episode_date:
            # Extract just the date part if it's an ISO format with time
            if "T" in episode_date:
                date_str = episode_date.split("T")[0]
            else:
                date_str = episode_date
            # Add to our list if it's a valid date
            if date_str:
                dates.append(date_str)
    
    # Sort dates and get latest
    if dates:
        dates.sort()  # This sorts in ascending order (oldest to newest)
        return dates[-1]  # Latest date
    
    return None


def check_for_new_episodes(show_url: str, latest_known_date: str) -> Tuple[bool, List[Dict]]:
    """
    Check if there are new episodes after the latest known date.
    
    Args:
        show_url: URL to the NTS Radio show
        latest_known_date: Latest known episode date in ISO format (YYYY-MM-DD)
        
    Returns:
        Tuple of (has_new_episodes, new_episodes_data)
    """
    logging.info(f"Checking for new episodes for show: {show_url}")
    
    # Scrape show information and episodes - but we'll optimize this to avoid
    # processing all episodes if not needed
    try:
        # Instead of using nts.scrape (which processes all episodes), we'll
        # use the lower-level functions to get just the episodes we need
        
        # Parse the URL to get the show alias
        url_info = nts.parse_nts_url(show_url)
        if not url_info.get("is_show", False):
            logging.error(f"URL is not for a show: {show_url}")
            return False, []
            
        show_alias = url_info.get("show_alias")
        if not show_alias:
            logging.error(f"Could not extract show alias from URL: {show_url}")
            return False, []
        
        # Get basic show info
        show_info = nts.get_show_info(show_alias)
        show_name = show_info.get("name", show_alias)
        
        # Get initial episodes batch - limit to 20 episodes since NTS orders newest first
        # This is a major optimization to avoid fetching the entire episode history
        episodes = nts.get_show_episodes(
            show_alias,
            limit_count=20,  # Only fetch the 20 newest episodes for checking
            use_cache=True,  # Use cache to avoid repeated API calls
            force_refresh=False  # Don't force refresh unless needed
        )
        
        if not episodes:
            logging.warning(f"No episodes found for show: {show_name}")
            return False, []
        
        # Process episodes in order (newest first), stopping when we hit an episode
        # that's older than or equal to our latest known date
        new_episodes = []
        for episode in episodes:
            # Get episode date
            episode_date = episode.get("broadcast", "")
            if not episode_date:
                continue
                
            # Extract just the date part if it's an ISO format with time
            if "T" in episode_date:
                date_str = episode_date.split("T")[0]
            else:
                date_str = episode_date
            
            # If this episode is not newer than our latest known date, we can stop
            if date_str <= latest_known_date:
                logging.info(f"Reached episode with date {date_str}, which is not newer than {latest_known_date}. Stopping search.")
                break
                
            logging.info(f"Found new episode with date {date_str}")
            
            # Get episode alias to fetch detailed data
            episode_alias = episode.get("episode_alias") or episode.get("slug")
            if not episode_alias:
                logging.warning(f"Skipping episode with no alias")
                continue
                
            # Get detailed episode data with tracklist
            try:
                episode_data = nts.get_tracklist_from_episode_page(show_alias, episode_alias)
                episode_info = nts.parse_tracklist(episode_data)
                
                # Only add episodes with tracks
                if episode_info.get("tracks"):
                    new_episodes.append(episode_info)
            except Exception as e:
                logging.error(f"Error processing episode {episode_alias}: {e}")
        
        return len(new_episodes) > 0, new_episodes
        
    except Exception as e:
        logging.error(f"Error while checking for new episodes: {e}")
        return False, []


@retry_with_backoff(max_retries=3, base_delay=2.0)
def update_spotify_playlist_description(spotify_client, playlist_id: str, new_date: str, show_name: str = None) -> bool:
    """
    Update the description of a Spotify playlist with a new date.
    
    Args:
        spotify_client: Authenticated Spotify client
        playlist_id: ID of the playlist to update
        new_date: New date to add to the description in ISO format (YYYY-MM-DD)
        show_name: Name of the show (optional)
        
    Returns:
        True if the update was successful, False otherwise
        
    Raises:
        APIError: If the API request fails after retries
        RateLimitError: If rate limit is exceeded even after retries
        AuthenticationError: If authentication fails
        NonRecoverableError: For other non-recoverable errors
    """
    try:
        # Get the current playlist info
        try:
            playlist_info = spotify_client.playlist(playlist_id)
            current_description = playlist_info.get('description', '')
        except Exception as e:
            # Convert Spotify exceptions to our standard error types
            if isinstance(e, spotify.SpotifyException):
                if e.http_status == 429:
                    raise RateLimitError(f"Rate limit exceeded: {e}", 
                                         retry_after=int(e.headers.get("Retry-After", 1)) if hasattr(e, "headers") else None)
                elif e.http_status in (401, 403):
                    raise AuthenticationError(f"Authentication failed: {e}")
                elif e.http_status >= 500:
                    raise APIError(f"Spotify server error: {e}")
                else:
                    raise NonRecoverableError(f"Spotify API error: {e}")
            else:
                raise APIError(f"Error getting playlist info: {e}")
        
        # Format the new date
        formatted_date = datetime.strptime(new_date, "%Y-%m-%d").strftime("%m/%d/%y")
        
        # Check if the description already contains this date
        if f"Updated {formatted_date}" in current_description:
            logging.info(f"Playlist description already contains date {formatted_date}, no update needed")
            return False
        
        # If we don't have the show name, try to extract it from the description
        if not show_name and "Archive of " in current_description:
            try:
                show_name = current_description.split("Archive of ")[1].split(" from NTS Radio")[0]
            except:
                # If extraction fails, use a generic show name
                show_name = "this show"
        elif not show_name:
            show_name = "this show"
        
        # Format the new description in the desired format:
        # "Archive of XXX from NTS Radio. Updated [date] via TrackTracker."
        new_description = f"Archive of {show_name} from NTS Radio. Updated {formatted_date} via TrackTracker."
        
        # Update the playlist description
        try:
            user_id = spotify_client.me()["id"]
            spotify_client.user_playlist_change_details(
                user=user_id,
                playlist_id=playlist_id,
                description=new_description
            )
        except Exception as e:
            # Convert Spotify exceptions to our standard error types
            if isinstance(e, spotify.SpotifyException):
                if e.http_status == 429:
                    raise RateLimitError(f"Rate limit exceeded: {e}", 
                                         retry_after=int(e.headers.get("Retry-After", 1)) if hasattr(e, "headers") else None)
                elif e.http_status in (401, 403):
                    raise AuthenticationError(f"Authentication failed: {e}")
                elif e.http_status >= 500:
                    raise APIError(f"Spotify server error: {e}")
                else:
                    raise NonRecoverableError(f"Spotify API error: {e}")
            else:
                raise APIError(f"Error updating playlist description: {e}")
        
        logging.info(f"Updated playlist description: {new_description}")
        return True
        
    except (APIError, RateLimitError, AuthenticationError, NonRecoverableError) as e:
        # Let retry_with_backoff handle these errors
        raise
    except Exception as e:
        # Catch all other exceptions and turn them into API errors
        logging.error(f"Unexpected error updating playlist description: {e}")
        return False


def extract_playlist_id_from_url(playlist_url: str) -> Optional[str]:
    """
    Extract the playlist ID from a Spotify playlist URL.
    
    Args:
        playlist_url: Spotify playlist URL
        
    Returns:
        Playlist ID, or None if not found
    """
    import re
    
    match = re.search(r'playlist/([a-zA-Z0-9]+)', playlist_url)
    if match:
        return match.group(1)
    
    return None


def batch_update_playlists() -> Dict[str, Any]:
    """
    Check for new episodes for all shows in the website data and update playlists.
    
    Returns:
        Dictionary with statistics about the update operation
        
    Raises:
        TrackTrackerError: Base class for all tracktracker errors
        APIError: If an API request fails
        AuthenticationError: If authentication fails
        NonRecoverableError: For other non-recoverable errors
    """
    logging.info("Starting batch update of playlists")
    
    # Statistics for reporting
    stats = {
        "shows_checked": 0,
        "shows_updated": 0,
        "episodes_added": 0,
        "tracks_added": 0,
        "errors": 0,
        "updates": []  # Detailed info about updates
    }
    
    # Load shows data from website
    try:
        shows = website.load_shows_data()
        
        if not shows:
            logging.warning("No shows found in website data")
            return stats
    except Exception as e:
        logging.error(f"Failed to load shows data: {e}")
        stats["errors"] += 1
        raise NonRecoverableError(f"Failed to load shows data: {e}") from e
    
    # Authenticate with Spotify
    try:
        logging.info("Authenticating with Spotify...")
        spotify_client = spotify.authenticate("playlist-modify-public")
    except AuthenticationError as e:
        logging.error(f"Failed to authenticate with Spotify: {e}")
        stats["errors"] += 1
        raise
    except Exception as e:
        logging.error(f"Failed to authenticate with Spotify: {e}")
        stats["errors"] += 1
        raise NonRecoverableError(f"Failed to authenticate with Spotify: {e}") from e
    
    # Process each show
    for i, show in enumerate(shows):
        show_name = show.get("shortTitle", "Unknown Show")
        nts_url = show.get("nts", "")
        spotify_url = show.get("spotify", "")
        current_end_date = show.get("endDate", "")
        
        stats["shows_checked"] += 1
        
        # Skip shows without NTS URL or Spotify URL
        if not nts_url or not spotify_url:
            logging.warning(f"Skipping show '{show_name}' - missing NTS URL or Spotify URL")
            continue
        
        # Extract playlist ID from Spotify URL
        playlist_id = extract_playlist_id_from_url(spotify_url)
        if not playlist_id:
            logging.warning(f"Skipping show '{show_name}' - could not extract playlist ID from URL: {spotify_url}")
            continue
        
        logging.info(f"Processing show: {show_name}")
        logging.info(f"Current end date: {current_end_date}")
        
        # Check for new episodes
        has_new_episodes, new_episodes = check_for_new_episodes(nts_url, current_end_date)
        
        if has_new_episodes and new_episodes:
            logging.info(f"Found {len(new_episodes)} new episodes for '{show_name}'")
            
            # Get the latest episode date
            latest_episode_date = get_latest_episode_date(new_episodes)
            
            if not latest_episode_date:
                logging.warning(f"Could not determine latest episode date for '{show_name}'")
                continue
            
            # Update the Spotify playlist
            try:
                logging.info(f"Updating playlist for '{show_name}'")
                
                # Prepare data for update_show_archive
                episodes_data = new_episodes.copy()
                
                # Update the playlist
                _, update_stats = spotify.update_show_archive(
                    spotify_client, show_name, episodes_data, verbose=False
                )
                
                # Update counters
                stats["episodes_added"] += len(new_episodes)
                tracks_added = update_stats.get("new_tracks_added", 0)
                stats["tracks_added"] += tracks_added
                
                # Only update playlist description if tracks were actually added
                description_updated = False
                if tracks_added > 0:
                    # Update playlist description with new date and show name
                    description_updated = update_spotify_playlist_description(
                        spotify_client, playlist_id, latest_episode_date, show_name
                    )
                
                # Update the end date in the website data
                end_date_updated = website.update_show_end_date(i, latest_episode_date)
                
                # Only count show as updated if tracks were added or the end date changed
                if update_stats.get("new_tracks_added", 0) > 0 or end_date_updated:
                    stats["shows_updated"] += 1
                    stats["updates"].append({
                        "show_name": show_name,
                        "new_episodes": len(new_episodes),
                        "new_tracks": update_stats.get("new_tracks_added", 0),
                        "new_end_date": latest_episode_date
                    })
                
                logging.info(f"Successfully updated show '{show_name}' with {len(new_episodes)} new episodes and {update_stats.get('new_tracks_added', 0)} new tracks")
                
                # Longer pause to avoid rate limits
                # Try to get delay from config, fall back to a reasonable default
                try:
                    from tracktracker.config import settings
                    delay = max(settings.api.base_delay * 2, 5)  # At least 5 seconds, or 2x base delay
                except ImportError:
                    delay = 5  # Default to 5 seconds if config not available
                
                logging.info(f"Pausing for {delay} seconds to avoid rate limits...")
                time.sleep(delay)
                
            except RateLimitError as e:
                # Special handling for rate limits
                retry_after = e.retry_after or 15  # Default to 15 seconds if not specified
                logging.warning(f"Rate limit hit while updating '{show_name}'. Waiting {retry_after} seconds before next show...")
                time.sleep(retry_after)
                stats["errors"] += 1
                # Add specific rate limit info to stats
                stats.setdefault("rate_limits", 0)
                stats["rate_limits"] += 1
            except RateLimitError as e:
                # Special handling for rate limits
                retry_after = e.retry_after or 15  # Default to 15 seconds if not specified
                logging.warning(f"Rate limit hit while updating '{show_name}'. Waiting {retry_after} seconds before next show...")
                time.sleep(retry_after)
                stats["errors"] += 1
                # Add specific rate limit info to stats
                stats.setdefault("rate_limits", 0)
                stats["rate_limits"] += 1
            except Exception as e:
                logging.error(f"Error updating playlist for '{show_name}': {e}")
                stats["errors"] += 1
        else:
            logging.info(f"No new episodes found for '{show_name}'")
    
    # Generate summary
    logging.info("\n--- Batch Update Summary ---")
    logging.info(f"Shows checked: {stats['shows_checked']}")
    logging.info(f"Shows updated: {stats['shows_updated']}")
    logging.info(f"Episodes added: {stats['episodes_added']}")
    logging.info(f"Tracks added: {stats['tracks_added']}")
    logging.info(f"Errors: {stats['errors']}")
    
    # Show rate limit errors if any occurred
    if stats.get("rate_limits", 0) > 0:
        logging.warning(f"Rate limit errors: {stats['rate_limits']}")
        logging.warning("Consider adjusting API_BASE_DELAY and API_MAX_RETRIES in your .env file")
    
    if stats["updates"]:
        logging.info("\nDetailed Updates:")
        for update in stats["updates"]:
            logging.info(f"- {update['show_name']}: {update['new_episodes']} episodes, {update['new_tracks']} tracks, end date: {update['new_end_date']}")
    
    return stats


if __name__ == "__main__":
    """
    Allow standalone execution of the batch update.
    """
    # Configure logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    
    # Run the batch update
    try:
        stats = batch_update_playlists()
        sys.exit(0 if stats["errors"] == 0 else 1)
    except AuthenticationError as e:
        logging.error(f"Authentication failed: {e}")
        # Suggest to check credentials
        logging.error("Please check your Spotify API credentials in the environment variables")
        sys.exit(2)
    except RateLimitError as e:
        logging.error(f"Rate limit exceeded: {e}")
        # Suggest to try again later
        logging.error(f"Please try again later. Retry after: {e.retry_after or 'unknown'} seconds")
        sys.exit(3)
    except APIError as e:
        logging.error(f"API error: {e}")
        # Suggest to check internet connection
        logging.error("Please check your internet connection and try again")
        sys.exit(4)
    except NonRecoverableError as e:
        logging.error(f"Non-recoverable error: {e}")
        sys.exit(5)
    except TrackTrackerError as e:
        logging.error(f"TrackTracker error: {e}")
        sys.exit(6)
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        sys.exit(1)