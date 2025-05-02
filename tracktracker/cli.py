#!/usr/bin/env python3
"""
Command-line interface for the tracktracker utility.

Scrapes track listings from NTS Radio episodes or entire shows, then creates
Spotify playlists with those tracks.

Modes of operation:
1. Single episode: Create a playlist from a single NTS episode
2. Show archive: Create a playlist containing all tracks from all episodes of a show
3. Weekly report: Generate a CSV report of all tracks played on NTS in the past week
4. Website: Create a show entry for the website
5. Batch update: Check for new episodes for all shows and update playlists
"""

import argparse
import logging
import sys
import os
import inquirer
import pathlib
from typing import Dict, Optional, Tuple, Any, List

try:
    from dotenv import load_dotenv
    # Try to load from .env file if it exists
    load_dotenv()
except ImportError:
    pass  # dotenv is optional

from tracktracker.scrapers import nts
from tracktracker import spotify
from tracktracker import utils
from tracktracker import website
from tracktracker import batch_update
from tracktracker.api_utils import (
    APIError,
    RateLimitError,
    AuthenticationError,
    NonRecoverableError,
    TrackTrackerError,
)


def get_episode_title(tracks_info: Dict) -> str:
    """
    Extract the episode title from the NTS tracks info.
    
    Args:
        tracks_info: Dictionary containing track information and metadata from NTS
        
    Returns:
        Episode title string
    """
    return tracks_info.get("episode_title", "NTS Episode")


def process_single_episode(url: str, verbose: bool = False) -> None:
    """
    Process a single NTS episode and create or update a Spotify playlist.
    
    Args:
        url: URL to an NTS Radio episode
        verbose: Whether to enable verbose output
        
    Raises:
        ValueError: If any processing step fails
    """
    logging.info(f"Fetching tracklist from NTS episode: {url}")

    # Scrape tracks from NTS
    try:
        tracks_info = nts.scrape(url)
        if verbose:
            logging.debug(f"NTS API response keys: {list(tracks_info.keys())}")
            if 'tracks' in tracks_info:
                logging.debug(f"Found {len(tracks_info['tracks'])} raw tracks in response")
    except Exception as e:
        logging.error(f"Error while scraping from NTS: {e}", exc_info=verbose)
        raise ValueError(f"Failed to scrape tracks from NTS: {e}")

    tracks = tracks_info.get("tracks", [])
    episode_title = get_episode_title(tracks_info)
    show_name = tracks_info.get("show_name", "NTS Show")
    broadcast_date = tracks_info.get("broadcast_date", "")

    logging.info(f"Processing episode: {episode_title}")
    logging.info(f"Found {len(tracks)} tracks initially.")

    # Save the raw tracklist to CSV for manual verification
    if tracks:
        raw_csv_path = spotify.save_tracklist_to_csv(tracks, f"{show_name}_{episode_title}_raw")
        logging.info(f"Raw tracklist saved to {raw_csv_path} for manual verification")

    # Deduplicate tracks
    unique_tracks = utils.deduplicate_tracks(tracks)
    logging.info(f"After deduplication: {len(unique_tracks)} unique tracks.")

    # Save the deduplicated tracklist to CSV
    if unique_tracks:
        csv_path = spotify.save_tracklist_to_csv(unique_tracks, f"{show_name}_{episode_title}")
        logging.info(f"Deduplicated tracklist saved to {csv_path} for manual verification")

    if not unique_tracks:
        logging.warning("No unique tracks found after deduplication. Exiting.")
        return

    # Handle Spotify interactions
    logging.info("Authenticating with Spotify...")
    spotify_client = spotify.authenticate("playlist-modify-public")
    
    # Process tracks and create/update playlist
    playlist_url, stats = spotify.process_episode_tracks(
        spotify_client, 
        show_name, 
        episode_title, 
        broadcast_date, 
        unique_tracks, 
        verbose
    )

    # Results Summary
    logging.info("\n--- Processing Complete ---")
    
    if stats["already_in_playlist"] > 0:
        logging.info(f"Found existing playlist for this episode")
        logging.info(f"✓ {stats['new_tracks_added']} new tracks added to playlist")
        logging.info(f"✓ {stats['already_in_playlist']} tracks were already in the playlist")
    else:
        logging.info(f"✓ {stats['found_tracks']} tracks added to new playlist")
    
    if stats['not_found_tracks'] > 0:
        logging.warning(f"× {stats['not_found_tracks']} tracks could not be found on Spotify")
        logging.info(f"Check {csv_path} to see all tracks and make manual corrections if needed")
        if verbose and 'not_found' in locals():
            logging.debug("Tracks not found:")
            for track in not_found:
                logging.debug(f"  - {track['artist']} - {track['title']}")

    logging.info(f"\nPlaylist URL: {playlist_url}")


def process_show_archive(
    url: str, 
    verbose: bool = False, 
    add_to_website: bool = False, 
    chunk_size: Optional[int] = None,
    start_episode: int = 0,
    small_test: bool = False
) -> Tuple[str, Dict]:
    """
    Process an entire NTS show archive and create or update a Spotify playlist with all tracks.
    
    Args:
        url: URL to an NTS Radio show
        verbose: Whether to enable verbose output
        add_to_website: Whether to add the show to the website
        chunk_size: Optional number of episodes to process at a time (None for all)
        
    Returns:
        Tuple of (playlist_url, show_info)
        
    Raises:
        ValueError: If any processing step fails
    """
    logging.info(f"Fetching show archive from NTS: {url}")

    # Scrape show information and all episodes from NTS
    try:
        show_info = nts.scrape(url)
        if verbose:
            logging.debug(f"NTS API response keys: {list(show_info.keys())}")
            if 'episode_count' in show_info:
                logging.debug(f"Found {show_info['episode_count']} episodes with tracklists")
    except Exception as e:
        logging.error(f"Error while scraping from NTS: {e}", exc_info=verbose)
        raise ValueError(f"Failed to scrape show archive from NTS: {e}")

    # Verify this is a show URL with episodes data
    if not show_info.get("is_show", False) or "episodes_data" not in show_info:
        raise ValueError("The provided URL is not for a show or no episodes were found")
    
    show_name = show_info.get("show_name", "NTS Show")
    episodes_data = show_info.get("episodes_data", [])
    episode_count = show_info.get("episode_count", 0)

    logging.info(f"Processing show archive: {show_name}")
    logging.info(f"Found {episode_count} episodes with tracklists")

    if not episodes_data:
        logging.warning("No episodes with tracks found. Exiting.")
        return "", show_info
        
    # Apply small test option if requested
    if small_test:
        logging.info("Running in small test mode - using only the latest episode")
        if episodes_data:
            episodes_data = [episodes_data[0]]  # Just take the latest episode
            episode_count = 1
            logging.info(f"Selected latest episode: {episodes_data[0].get('episode_title', 'Unknown')}")
    
    # Apply start_episode option if specified
    elif start_episode > 0:
        if start_episode < len(episodes_data):
            logging.info(f"Starting from episode index {start_episode} out of {len(episodes_data)}")
            episodes_data = episodes_data[start_episode:]
            episode_count = len(episodes_data)
        else:
            logging.warning(f"Start episode index {start_episode} is out of range (max: {len(episodes_data)-1})")
            return "", show_info
    
    # Collect all tracks from all episodes
    all_tracks = []
    for episode in episodes_data:
        all_tracks.extend(episode.get("tracks", []))
    
    # Save the tracklist to CSV for manual verification
    if all_tracks:
        csv_path = spotify.save_tracklist_to_csv(all_tracks, show_name)
        logging.info(f"Tracklist saved to {csv_path} for manual verification")

    # Handle Spotify interactions
    logging.info("Authenticating with Spotify...")
    spotify_client = spotify.authenticate("playlist-modify-public")
    
    # Always use update_show_archive which handles both creating and updating playlists
    logging.info(f"Processing archive playlist for show: {show_name}")
    
    # Add chunking information if enabled
    if chunk_size:
        logging.info(f"Processing in chunks of up to {chunk_size} episodes to avoid rate limits")
    
    playlist_url, stats = spotify.update_show_archive(
        spotify_client, 
        show_name, 
        episodes_data, 
        verbose,
        chunk_size=chunk_size,
        delay_between_chunks=60.0  # 1 minute between chunks
    )
    
    # Results Summary
    if stats.get("already_in_playlist", 0) > 0:
        logging.info("\n--- Archive Update Complete ---")
        logging.info(f"Processed {stats['total_episodes']} episodes with {stats['total_tracks']} tracks")
        logging.info(f"✓ {stats['new_tracks_added']} new tracks added to archive playlist")
        logging.info(f"✓ {stats['already_in_playlist']} tracks were already in the playlist")
    else:
        logging.info("\n--- Archive Creation Complete ---")
        logging.info(f"Processed {stats['total_episodes']} episodes with {stats['total_tracks']} tracks")
        logging.info(f"✓ {stats['found_tracks']} tracks added to archive playlist")
    
    if stats['not_found_tracks'] > 0:
        logging.warning(f"× {stats['not_found_tracks']} tracks could not be found on Spotify")
        logging.info(f"Check {csv_path} to see all tracks and make manual corrections if needed")

    logging.info(f"\nPlaylist URL: {playlist_url}")
    
    # Return the playlist URL and show info for potential website use
    return playlist_url, show_info


def process_weekly_report(days: int = 7, verbose: bool = False) -> None:
    """
    Generate a report of tracks played on NTS in the past days.

    Args:
        days: Number of days to look back
        verbose: Whether to enable verbose output
    """
    logging.info(f"Generating report of tracks played on NTS in the past {days} days")
    
    try:
        output_file = f"nts_weekly_report_{days}days.csv"
        analysis = nts.generate_weekly_report(days, output_file)
        
        if not analysis:
            logging.warning("No episodes found for the specified time period")
            return
            
        # Print summary to console
        logging.info("\n--- Weekly Report Summary ---")
        
        # The updated scraper no longer returns track analysis data
        # Instead, we just show episode information
        episodes = analysis.get("episodes", [])
        logging.info(f"Found {len(episodes)} episodes from NTS Radio")
        
        # Show the first few episodes as a sample
        sample_size = min(5, len(episodes))
        if sample_size > 0:
            logging.info(f"\nSample of {sample_size} episodes:")
            for i, episode in enumerate(episodes[:sample_size], 1):
                show_name = episode.get("show_name", "Unknown Show")
                channel = episode.get("channel", "")
                broadcast_date = episode.get("broadcast_date", "")
                logging.info(f"{i}. {show_name} (Channel {channel}) - {broadcast_date}")
            
        logging.info(f"\nFull report saved to: {output_file}")
        logging.info("\nNote: Track information is not available from the NTS API at this time.")
        
    except Exception as e:
        logging.error(f"Error generating weekly report: {e}", exc_info=verbose)
        raise ValueError(f"Failed to generate weekly report: {e}")


def process_add_to_website(show_url: str, spotify_url: str, verbose: bool = False, is_nts: bool = True) -> None:
    """
    Add a show to the website.
    
    Args:
        show_url: URL to a show (NTS or other source)
        spotify_url: URL to the Spotify playlist
        verbose: Whether to enable verbose output
        is_nts: Whether this is an NTS show (default: True)
    """
    source_type = "NTS" if is_nts else "non-NTS"
    logging.info(f"Adding {source_type} show to website: {show_url}")
    
    try:
        if is_nts:
            # NTS Show workflow - scrape show information from NTS API
            # Validate the show URL and get show info
            url_info = nts.parse_nts_url(show_url)
            if not url_info.get("is_show", False):
                logging.warning("The provided URL is not for a show. Using show URL instead.")
                # Construct show URL from episode URL if possible
                show_alias = url_info.get("show_alias")
                if show_alias:
                    show_url = f"https://www.nts.live/shows/{show_alias}"
                    logging.info(f"Using show URL: {show_url}")
                else:
                    raise ValueError("Could not determine the show URL from the provided URL.")
            
            # Scrape show information
            show_info = nts.scrape(show_url)
            show_name = show_info.get("show_name", "NTS Show")
            source = "NTS"
            
            # Prompt for short title
            questions = [
                inquirer.Text('short_title',
                              message="Enter a short title for the show",
                              default=show_name)
            ]
            answers = inquirer.prompt(questions)
            short_title = answers.get('short_title', show_name)
            
            # Use the show name from NTS for long title
            long_title = show_name
        else:
            # Non-NTS Show workflow - prompt for all details
            # Prompt for short and long titles
            questions = [
                inquirer.Text('short_title',
                              message="Enter a short title for the show")
            ]
            answers = inquirer.prompt(questions)
            short_title = answers.get('short_title', "")
            
            questions = [
                inquirer.Text('long_title',
                              message="Enter a full title for the show",
                              default=short_title)
            ]
            answers = inquirer.prompt(questions)
            long_title = answers.get('long_title', short_title)
            
            # Prompt for source type
            questions = [
                inquirer.List('source',
                              message="Select the source platform",
                              choices=['Mixcloud', 'Soundcloud', 'YouTube', 'Other'])
            ]
            answers = inquirer.prompt(questions)
            source = answers.get('source', "Other")
            
            # If "Other" was selected, prompt for custom source
            if source == "Other":
                questions = [
                    inquirer.Text('custom_source',
                                 message="Enter the custom source name")
                ]
                answers = inquirer.prompt(questions)
                source = answers.get('custom_source', "Other")
            
            # Prompt for dates
            questions = [
                inquirer.Text('start_date',
                              message="Enter start date (YYYY-MM-DD)",
                              validate=lambda _, x: len(x) == 0 or (len(x) == 10 and x[4] == '-' and x[7] == '-'))
            ]
            answers = inquirer.prompt(questions)
            start_date = answers.get('start_date', "")
            
            questions = [
                inquirer.Text('end_date',
                              message="Enter latest episode date (YYYY-MM-DD)",
                              validate=lambda _, x: len(x) == 0 or (len(x) == 10 and x[4] == '-' and x[7] == '-'))
            ]
            answers = inquirer.prompt(questions)
            end_date = answers.get('end_date', "")
            
            # Prompt for frequency
            questions = [
                inquirer.List('frequency',
                              message="Select show frequency",
                              choices=['Monthly', 'Weekly', 'Biweekly', 'Daily', 'One-off'])
            ]
            answers = inquirer.prompt(questions)
            frequency = answers.get('frequency', "Monthly")
            
            # Create empty show_info dict for non-NTS shows
            show_info = {
                "show_name": long_title,
                "frequency": frequency,
                "description": "",
                "episodes_data": []
            }
        
        # Prompt for artwork file - common for both NTS and non-NTS
        questions = [
            inquirer.Text('artwork_path',
                          message="Enter path to artwork file (jpg/jpeg)",
                          validate=lambda _, x: os.path.exists(x) and x.lower().endswith(('.jpg', '.jpeg')))
        ]
        answers = inquirer.prompt(questions)
        artwork_path = answers.get('artwork_path')
        
        # Prompt for Apple Music link - common for both NTS and non-NTS
        questions = [
            inquirer.Text('apple_url',
                          message="Enter Apple Music playlist URL (leave empty if none)",
                          default="")
        ]
        answers = inquirer.prompt(questions)
        apple_url = answers.get('apple_url', "")
        
        # Prompt for show description if not available - common for both NTS and non-NTS
        description = show_info.get("description", "")
        if not description:
            # Use plain input instead of inquirer for multiline text to avoid repeating issues
            print("[?] Enter a description for the show (press Enter twice when done):")
            lines = []
            while True:
                line = input()
                if not line and (not lines or not lines[-1]):
                    # Break on empty line after another empty line or at start
                    break
                lines.append(line)
            description = "\n".join(lines)
        
        # Format the Spotify URL to the standard format
        formatted_spotify_url = utils.format_spotify_url(spotify_url)
        
        # Create show data based on source
        if is_nts:
            # Use NTS show creation method
            show_data = website.create_show_data_from_nts(
                nts_url=show_url,
                nts_data=show_info,
                spotify_url=formatted_spotify_url,
                apple_url=apple_url,
                short_title=short_title,
                artwork_path=artwork_path,
                custom_description=description
            )
        else:
            # Use manual show creation method for non-NTS sources
            show_data = website.create_show_data_manual(
                show_url=show_url,
                spotify_url=formatted_spotify_url,
                apple_url=apple_url,
                short_title=short_title,
                long_title=long_title,
                artwork_path=artwork_path,
                description=description,
                source=source,
                frequency=frequency,
                start_date=start_date,
                end_date=end_date
            )
        
        # Add to website
        website.add_new_show(show_data)
        
        logging.info("\n--- Website Update Complete ---")
        logging.info(f"Added show to website: {short_title}")
        logging.info(f"Show data: {show_data}")
        
    except Exception as e:
        logging.error(f"Error adding show to website: {e}", exc_info=verbose)
        raise ValueError(f"Failed to add show to website: {e}")


def process_config(show: bool = False, create_env: bool = False, verbose: bool = False) -> None:
    """
    View or update configuration settings.
    
    Args:
        show: Whether to show current settings
        create_env: Whether to create a sample .env file
        verbose: Whether to enable verbose output
    """
    try:
        from tracktracker.config import settings
        
        if show:
            # Display current settings
            print("Current Configuration:")
            print(f"  App Name: {settings.app_name}")
            print(f"  App Version: {settings.app_version}")
            print(f"  Log Level: {settings.log_level}")
            print("\nPaths:")
            print(f"  Cache Directory: {settings.paths.cache_dir}")
            print(f"  Data Directory: {settings.paths.data_dir}")
            print(f"  Show Images Directory: {settings.paths.show_images_dir}")
            print(f"  Spotify Token Path: {settings.paths.spotify_token_path}")
            print(f"  Track Cache Path: {settings.paths.track_cache_path}")
            print(f"  Shows Data Path: {settings.paths.shows_data_path}")
            print("\nAPI Settings:")
            print(f"  User Agent: {settings.api.user_agent}")
            print(f"  Timeout: {settings.api.timeout} seconds")
            print(f"  Max Retries: {settings.api.max_retries}")
            print(f"  Base Delay: {settings.api.base_delay} seconds")
            print(f"  Max Delay: {settings.api.max_delay} seconds")
            print(f"  Retry Backoff Factor: {settings.api.retry_backoff}")
            print("\nSpotify Settings:")
            print(f"  Client ID: {'set' if settings.spotify.client_id else 'not set'}")
            print(f"  Client Secret: {'set' if settings.spotify.client_secret else 'not set'}")
            print(f"  Redirect URI: {settings.spotify.redirect_uri}")
            
        if create_env:
            # Create a sample .env file with current settings
            env_path = os.path.join(os.getcwd(), ".env")
            
            # Import datetime here to avoid circular imports
            from datetime import datetime
            
            # Check if file exists and ask for confirmation using a simpler method
            if os.path.exists(env_path):
                print(f".env file already exists at {env_path}.")
                confirm = input("Do you want to overwrite it? (y/N): ").strip().lower()
                if confirm != 'y':
                    print("Aborted.")
                    return
                
            # Create the file
            with open(env_path, "w") as f:
                f.write("# TrackTracker Configuration\n")
                f.write("# Generated on {}\n\n".format(datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                
                # Spotify settings
                f.write("# Spotify API credentials\n")
                f.write(f"SPOTIFY_CLIENT_ID={settings.spotify.client_id}\n")
                f.write(f"SPOTIFY_CLIENT_SECRET={settings.spotify.client_secret}\n")
                f.write(f"SPOTIFY_REDIRECT_URI={settings.spotify.redirect_uri}\n\n")
                
                # Logging
                f.write("# Logging\n")
                f.write(f"LOG_LEVEL={settings.log_level}\n\n")
                
                # Path overrides (commented out by default)
                f.write("# Optional: Override the default paths\n")
                f.write(f"# TRACKTRACKER_CACHE_DIR={settings.paths.cache_dir}\n")
                f.write(f"# TRACKTRACKER_DATA_DIR={settings.paths.data_dir}\n")
                f.write(f"# TRACKTRACKER_SHOW_IMAGES_DIR={settings.paths.show_images_dir}\n")
                
            print(f"Created .env file at {env_path}")
            
        if not show and not create_env:
            # If no options specified, show help
            print("Use --show to view current settings or --create-env to create a sample .env file.")
            
    except ImportError:
        print("Configuration module not available. Make sure pydantic and python-dotenv are installed.")
        print("You can install them with: pip install pydantic python-dotenv")


def process_batch_update(verbose: bool = False) -> None:
    """
    Check for new episodes for all shows and update playlists.
    
    Args:
        verbose: Whether to enable verbose output
    """
    logging.info("Starting batch update of playlists")
    
    try:
        # Run the batch update
        stats = batch_update.batch_update_playlists()
        
        # Display summary
        logging.info("\n--- Batch Update Complete ---")
        logging.info(f"Shows checked: {stats['shows_checked']}")
        logging.info(f"Shows updated: {stats['shows_updated']}")
        logging.info(f"Episodes added: {stats['episodes_added']}")
        logging.info(f"Tracks added: {stats['tracks_added']}")
        
        if stats["errors"] > 0:
            logging.warning(f"Encountered {stats['errors']} errors during the update")
        
    except AuthenticationError as e:
        logging.error(f"Authentication failed: {e}", exc_info=verbose)
        logging.error("Please check your Spotify API credentials in the environment variables")
        raise ValueError(f"Authentication failed: {e}")
    except RateLimitError as e:
        logging.error(f"Rate limit exceeded: {e}", exc_info=verbose)
        logging.error(f"Please try again later. Retry after: {e.retry_after or 'unknown'} seconds")
        raise ValueError(f"Rate limit exceeded. Please try again later: {e}")
    except APIError as e:
        logging.error(f"API error: {e}", exc_info=verbose)
        logging.error("Please check your internet connection and try again")
        raise ValueError(f"API error: {e}")
    except NonRecoverableError as e:
        logging.error(f"Non-recoverable error: {e}", exc_info=verbose)
        raise ValueError(f"Non-recoverable error: {e}")
    except TrackTrackerError as e:
        logging.error(f"TrackTracker error: {e}", exc_info=verbose)
        raise ValueError(f"TrackTracker error: {e}")
    except Exception as e:
        logging.error(f"Unexpected error during batch update: {e}", exc_info=verbose)
        raise ValueError(f"Failed to run batch update: {e}")


def main():
    """Main entry point for the tracktracker CLI."""
    # Try to initialize configuration
    try:
        from tracktracker.config import settings
        # Ensure all required directories exist
        settings.ensure_directories()
    except ImportError:
        # Config module not available, continue with legacy behavior
        pass
    
    parser = argparse.ArgumentParser(
        description="Utility for NTS Radio tracks - create Spotify playlists or generate weekly reports."
    )
    
    # Create subparsers for different commands
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Playlist command
    playlist_parser = subparsers.add_parser("playlist", help="Create a Spotify playlist from NTS tracks")
    playlist_parser.add_argument(
        "url", 
        help="URL to an NTS Radio episode or show"
    )
    playlist_parser.add_argument(
        "-a", "--archive",
        action="store_true",
        help="Create or update a complete archive playlist for the show instead of a single episode"
    )
    playlist_parser.add_argument(
        "-w", "--website",
        action="store_true",
        help="Add the show to the website after creating the playlist"
    )
    playlist_parser.add_argument(
        "-c", "--clear-cache",
        action="store_true",
        help="Clear the track search cache before running to ensure fresh results"
    )
    playlist_parser.add_argument(
        "--strict",
        action="store_true",
        help="Use strict matching criteria when searching for tracks on Spotify"
    )
    playlist_parser.add_argument(
        "--chunk-size",
        type=int,
        help="Process episodes in chunks of this size to avoid rate limits (for archive mode)"
    )
    playlist_parser.add_argument(
        "--start-episode",
        type=int,
        default=0,
        help="Start processing from this episode index (0-based, for archive mode)"
    )
    playlist_parser.add_argument(
        "--small-test",
        action="store_true",
        help="Run a small test with just the latest episode to verify functionality"
    )
    
    # Website command
    website_parser = subparsers.add_parser("website", help="Add a show to the website")
    website_parser.add_argument(
        "show_url", 
        help="URL to the show (NTS, Mixcloud, Soundcloud, etc.)"
    )
    website_parser.add_argument(
        "spotify_url", 
        help="URL to the Spotify playlist for the show"
    )
    website_parser.add_argument(
        "--non-nts",
        action="store_true",
        help="Explicitly specify this flag for non-NTS shows (optional, as the tool will auto-detect based on URL)"
    )
    
    # Report command
    report_parser = subparsers.add_parser("report", help="Generate a weekly report of tracks played on NTS")
    report_parser.add_argument(
        "-d", "--days",
        type=int,
        default=7,
        help="Number of days to look back (default: 7)"
    )
    
    # Batch update command
    batch_parser = subparsers.add_parser("batch-update", help="Check for new episodes for all shows and update playlists")
    
    # Config command
    config_parser = subparsers.add_parser("config", help="View or update configuration settings")
    config_parser.add_argument(
        "--show", 
        action="store_true",
        help="Show current configuration settings"
    )
    config_parser.add_argument(
        "--create-env", 
        action="store_true",
        help="Create a sample .env file with current settings"
    )
    
    # Common options
    for p in [playlist_parser, report_parser, website_parser, batch_parser, config_parser]:
        p.add_argument(
            "-v", "--verbose", 
            action="store_true",
            help="Enable verbose output for debugging"
        )
    
    args = parser.parse_args()
    
    # For backwards compatibility - if no command is specified but URL is provided,
    # assume "playlist" command
    if len(sys.argv) > 1 and args.command is None and not sys.argv[1].startswith('-'):
        # Legacy mode - assume first argument is a URL for playlist
        args.command = "playlist"
        args.url = sys.argv[1]
        args.archive = "--archive" in sys.argv or "-a" in sys.argv
        args.website = "--website" in sys.argv or "-w" in sys.argv
        args.verbose = "--verbose" in sys.argv or "-v" in sys.argv
        args.clear_cache = "--clear-cache" in sys.argv or "-c" in sys.argv
        args.strict = "--strict" in sys.argv
    
    # Configure logging
    log_level = logging.DEBUG if getattr(args, "verbose", False) else logging.INFO
    logging.basicConfig(level=log_level, format="%(levelname)s: %(message)s")
    # Suppress overly verbose logs from underlying libraries if not in verbose mode
    if not getattr(args, "verbose", False):
        logging.getLogger("spotipy").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)

    try:
        if args.command == "playlist":
            # Clear track cache if requested
            if getattr(args, "clear_cache", False):
                logging.info("Clearing track search cache...")
                spotify.clear_track_cache()
                
            # Set strict matching flag globally
            strict_matching = getattr(args, "strict", True)  # Default to True for strict matching
            if strict_matching:
                logging.info("Using strict matching criteria for track search")
            
            # Validate the URL is for NTS
            url = utils.parse_url(args.url)
            
            # Detect whether this is a show URL or an episode URL
            # If archive flag is explicitly set, treat as show
            if args.archive:
                # Process entire show archive
                playlist_url, show_info = process_show_archive(
                    url, 
                    args.verbose, 
                    add_to_website=args.website,
                    chunk_size=args.chunk_size,
                    start_episode=args.start_episode,
                    small_test=args.small_test
                )
                
                # Add to website if requested
                if args.website and playlist_url:
                    process_add_to_website(url, playlist_url, args.verbose)
                    
                # Suggest chunking if chunk_size wasn't provided
                if not args.chunk_size:
                    logging.info("\nTIP: If you hit rate limits, try using the --chunk-size option:")
                    logging.info("   python -m tracktracker.cli playlist [URL] --archive --chunk-size 5")
            else:
                # Check URL structure to determine if it's a show or episode
                url_info = nts.parse_nts_url(url)
                is_show = url_info.get("is_show", False)
                
                if is_show:
                    logging.info(f"Detected URL is for a show. Processing as show archive.")
                    playlist_url, show_info = process_show_archive(
                        url, 
                        args.verbose, 
                        add_to_website=args.website,
                        chunk_size=args.chunk_size,
                        start_episode=args.start_episode,
                        small_test=args.small_test
                    )
                    
                    # Add to website if requested
                    if args.website and playlist_url:
                        process_add_to_website(url, playlist_url, args.verbose)
                        
                    # Suggest chunking if chunk_size wasn't provided
                    if not args.chunk_size:
                        logging.info("\nTIP: If you hit rate limits, try using the --chunk-size option:")
                        logging.info("   python -m tracktracker.cli playlist [URL] --archive --chunk-size 5")
                else:
                    # Process single episode
                    process_single_episode(url, args.verbose)
                    
        elif args.command == "website":
            # Add show to website
            # Auto-detect if this is an NTS show from the URL
            is_nts = "nts.live" in args.show_url.lower()
            
            # If the user explicitly specified --non-nts, override the auto-detection
            if hasattr(args, 'non_nts') and args.non_nts:
                is_nts = False
                
            process_add_to_website(
                args.show_url, 
                args.spotify_url, 
                args.verbose,
                is_nts=is_nts
            )
                    
        elif args.command == "report":
            # Generate weekly report
            process_weekly_report(args.days, args.verbose)
            
        elif args.command == "batch-update":
            # Run batch update of playlists
            process_batch_update(getattr(args, "verbose", False))
            
        elif args.command == "config":
            # View or update configuration
            process_config(
                show=getattr(args, "show", False),
                create_env=getattr(args, "create_env", False),
                verbose=getattr(args, "verbose", False)
            )
            
        else:
            # No command specified
            parser.print_help()
            sys.exit(1)

    except ValueError as e:
        # Catch specific expected errors like invalid URL
        logging.error(f"Configuration Error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logging.info("\nOperation canceled by user.")
        sys.exit(1)
    except Exception as e:
        # Catch any other unexpected errors
        logging.error(f"An unexpected error occurred: {e}", exc_info=getattr(args, "verbose", False))
        sys.exit(1)


if __name__ == "__main__":
    main()