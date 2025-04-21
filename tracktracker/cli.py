#!/usr/bin/env python3
"""
Command-line interface for the tracktracker utility.

Scrapes track listings from NTS Radio episodes or entire shows, then creates
Spotify playlists with those tracks.

Three modes of operation:
1. Single episode: Create a playlist from a single NTS episode
2. Show archive: Create a playlist containing all tracks from all episodes of a show
3. Weekly report: Generate a CSV report of all tracks played on NTS in the past week
"""

import argparse
import logging
import sys
from typing import Dict, Optional

from tracktracker.scrapers import nts
from tracktracker import spotify
from tracktracker import utils


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

    # Deduplicate tracks
    unique_tracks = utils.deduplicate_tracks(tracks)
    logging.info(f"After deduplication: {len(unique_tracks)} unique tracks.")

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
        if verbose and 'not_found' in locals():
            logging.debug("Tracks not found:")
            for track in not_found:
                logging.debug(f"  - {track['artist']} - {track['title']}")

    logging.info(f"\nPlaylist URL: {playlist_url}")


def process_show_archive(url: str, verbose: bool = False) -> None:
    """
    Process an entire NTS show archive and create or update a Spotify playlist with all tracks.
    
    Args:
        url: URL to an NTS Radio show
        verbose: Whether to enable verbose output
        
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
        return

    # Handle Spotify interactions
    logging.info("Authenticating with Spotify...")
    spotify_client = spotify.authenticate("playlist-modify-public")
    
    # Always use update_show_archive which handles both creating and updating playlists
    logging.info(f"Processing archive playlist for show: {show_name}")
    playlist_url, stats = spotify.update_show_archive(
        spotify_client, show_name, episodes_data, verbose
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

    logging.info(f"\nPlaylist URL: {playlist_url}")


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


def main():
    """Main entry point for the tracktracker CLI."""
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
    
    # Report command
    report_parser = subparsers.add_parser("report", help="Generate a weekly report of tracks played on NTS")
    report_parser.add_argument(
        "-d", "--days",
        type=int,
        default=7,
        help="Number of days to look back (default: 7)"
    )
    
    # Common options
    for p in [playlist_parser, report_parser]:
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
        args.verbose = "--verbose" in sys.argv or "-v" in sys.argv
    
    # Configure logging
    log_level = logging.DEBUG if getattr(args, "verbose", False) else logging.INFO
    logging.basicConfig(level=log_level, format="%(levelname)s: %(message)s")
    # Suppress overly verbose logs from underlying libraries if not in verbose mode
    if not getattr(args, "verbose", False):
        logging.getLogger("spotipy").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)

    try:
        if args.command == "playlist":
            # Validate the URL is for NTS
            url = utils.parse_url(args.url)
            
            # Detect whether this is a show URL or an episode URL
            # If archive flag is explicitly set, treat as show
            if args.archive:
                # Process entire show archive
                process_show_archive(url, args.verbose)
            else:
                # Check URL structure to determine if it's a show or episode
                url_info = nts.parse_nts_url(url)
                is_show = url_info.get("is_show", False)
                
                if is_show:
                    logging.info(f"Detected URL is for a show. Processing as show archive.")
                    process_show_archive(url, args.verbose)
                else:
                    # Process single episode
                    process_single_episode(url, args.verbose)
                    
        elif args.command == "report":
            # Generate weekly report
            process_weekly_report(args.days, args.verbose)
            
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
