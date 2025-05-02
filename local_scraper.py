#!/usr/bin/env python3
"""
Local scraper workflow for TrackTracker.

This script provides a simplified workflow for:
1. Scraping tracks from NTS Radio shows
2. Creating/updating Spotify playlists
3. Updating shows.json data locally

No automatic deployment is performed - deployment to GitHub Pages is done manually.
"""

import argparse
import logging
import os
import sys
import json
from pathlib import Path
from typing import Dict, Any

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
from tracktracker.api_utils import APIError, AuthenticationError


def update_show(nts_url: str, verbose: bool = False) -> None:
    """
    Process an NTS show: scrape tracks, update Spotify playlist, and update shows.json.
    
    Args:
        nts_url: URL to an NTS Radio show
        verbose: Whether to enable verbose output
    """
    logging.info(f"Updating show from NTS: {nts_url}")
    
    # Scrape show info and episodes from NTS
    try:
        show_info = nts.scrape(nts_url)
    except Exception as e:
        logging.error(f"Error while scraping from NTS: {e}", exc_info=verbose)
        raise ValueError(f"Failed to scrape show from NTS: {e}")
    
    # Verify this is a show URL with episodes data
    if not show_info.get("is_show", False) or "episodes_data" not in show_info:
        raise ValueError("The provided URL is not for a show or no episodes were found")
    
    show_name = show_info.get("show_name", "NTS Show")
    episodes_data = show_info.get("episodes_data", [])
    episode_count = show_info.get("episode_count", 0)
    
    logging.info(f"Processing show: {show_name}")
    logging.info(f"Found {episode_count} episodes with tracklists")
    
    if not episodes_data:
        logging.warning("No episodes with tracks found. Exiting.")
        return
        
    # Handle Spotify interactions
    logging.info("Authenticating with Spotify...")
    spotify_client = spotify.authenticate("playlist-modify-public")
    
    # Process tracks and create/update playlist
    playlist_url, stats = spotify.update_show_archive(
        spotify_client, 
        show_name, 
        episodes_data, 
        verbose
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
    
    # Check if the show exists in shows.json
    shows = website.load_shows_data()
    show_exists = False
    
    for i, show in enumerate(shows):
        if show.get("nts") == nts_url:
            show_exists = True
            
            # Update the end date
            latest_episode_date = get_latest_episode_date(episodes_data)
            if latest_episode_date and latest_episode_date != show.get("endDate", ""):
                logging.info(f"Updating end date from {show.get('endDate', 'not set')} to {latest_episode_date}")
                show["endDate"] = latest_episode_date
                
                # Save the updated shows data WITHOUT auto-push
                website.save_shows_data(shows, auto_push=False)
                logging.info("Updated shows.json with new end date")
            else:
                logging.info("End date is already up to date, no changes needed to shows.json")
            
            break
    
    if not show_exists:
        logging.info("Show not found in shows.json. You can add it by running this script with the add command")

    logging.info("\nLocal update complete! To deploy to GitHub Pages:")
    logging.info("1. Navigate to your GitHub Pages repository")
    logging.info("2. Copy the updated shows.json file from tracktracker/website/src/data/shows.json")
    logging.info("3. Commit and push the changes to GitHub")


def add_to_website(nts_url: str, spotify_url: str, verbose: bool = False) -> None:
    """
    Add an NTS show to the website data (shows.json).
    
    Args:
        nts_url: URL to an NTS Radio show
        spotify_url: URL to the Spotify playlist
        verbose: Whether to enable verbose output
    """
    logging.info(f"Adding show to website data: {nts_url}")
    
    try:
        # Validate the show URL and get show info
        url_info = nts.parse_nts_url(nts_url)
        if not url_info.get("is_show", False):
            logging.warning("The provided URL is not for a show. Using show URL instead.")
            # Construct show URL from episode URL if possible
            show_alias = url_info.get("show_alias")
            if show_alias:
                nts_url = f"https://www.nts.live/shows/{show_alias}"
                logging.info(f"Using show URL: {nts_url}")
            else:
                raise ValueError("Could not determine the show URL from the provided URL.")
        
        # Scrape show information
        show_info = nts.scrape(nts_url)
        show_name = show_info.get("show_name", "NTS Show")
        
        # Prompt for short title
        short_title = input(f"Enter a short title for the show [default: {show_name}]: ").strip()
        if not short_title:
            short_title = show_name
        
        # Prompt for artwork file
        while True:
            artwork_path = input("Enter path to artwork file (jpg/jpeg): ").strip()
            if os.path.exists(artwork_path) and artwork_path.lower().endswith((".jpg", ".jpeg")):
                break
            print("File does not exist or is not a jpg/jpeg. Please try again.")
        
        # Prompt for Apple Music link
        apple_url = input("Enter Apple Music playlist URL (leave empty if none): ").strip()
        
        # Prompt for show description if not available
        description = show_info.get("description", "")
        if not description:
            print("Enter a description for the show (enter a blank line when done):")
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
        
        # Create show data
        show_data = website.create_show_data_from_nts(
            nts_url=nts_url,
            nts_data=show_info,
            spotify_url=formatted_spotify_url,
            apple_url=apple_url,
            short_title=short_title,
            artwork_path=artwork_path,
            custom_description=description
        )
        
        # Add to website WITHOUT auto-push
        shows = website.load_shows_data()
        shows.insert(0, show_data)
        website.save_shows_data(shows, auto_push=False)
        
        logging.info("\n--- Website Data Update Complete ---")
        logging.info(f"Added show to shows.json: {short_title}")
        
        logging.info("\nLocal update complete! To deploy to GitHub Pages:")
        logging.info("1. Navigate to your GitHub Pages repository")
        logging.info("2. Copy the updated shows.json file from tracktracker/website/src/data/shows.json")
        logging.info("3. Commit and push the changes to GitHub")
        
    except Exception as e:
        logging.error(f"Error adding show to website data: {e}", exc_info=verbose)
        raise ValueError(f"Failed to add show to website data: {e}")


def get_latest_episode_date(episodes_data):
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


def export_shows_data(export_path: str = None) -> None:
    """
    Export the shows.json data to a file or stdout.
    
    Args:
        export_path: Path to export the shows data to. If None, print to stdout.
    """
    shows = website.load_shows_data()
    
    if export_path:
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(os.path.abspath(export_path)), exist_ok=True)
        
        with open(export_path, 'w') as f:
            json.dump(shows, f, indent=2)
        logging.info(f"Exported shows data to {export_path}")
    else:
        print(json.dumps(shows, indent=2))


def main():
    """Main entry point for the local scraper workflow."""
    parser = argparse.ArgumentParser(
        description="Local scraper workflow for TrackTracker - no automatic deployment."
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Update show command
    update_parser = subparsers.add_parser("update", help="Update a show: scrape tracks and update Spotify playlist")
    update_parser.add_argument("url", help="URL to an NTS Radio show")
    
    # Add to website command
    add_parser = subparsers.add_parser("add", help="Add a show to the website data (shows.json)")
    add_parser.add_argument("nts_url", help="URL to an NTS Radio show")
    add_parser.add_argument("spotify_url", help="URL to the Spotify playlist for the show")
    
    # Export command
    export_parser = subparsers.add_parser("export", help="Export shows.json data")
    export_parser.add_argument("-o", "--output", help="Path to export the shows data to. If not specified, print to stdout.")
    
    # Common options
    for p in [update_parser, add_parser, export_parser]:
        p.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output for debugging")
    
    args = parser.parse_args()
    
    # Configure logging
    log_level = logging.DEBUG if getattr(args, "verbose", False) else logging.INFO
    logging.basicConfig(level=log_level, format="%(levelname)s: %(message)s")
    
    # Suppress overly verbose logs from underlying libraries if not in verbose mode
    if not getattr(args, "verbose", False):
        logging.getLogger("spotipy").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
    
    try:
        if args.command == "update":
            update_show(args.url, args.verbose)
        elif args.command == "add":
            add_to_website(args.nts_url, args.spotify_url, args.verbose)
        elif args.command == "export":
            export_shows_data(args.output)
        else:
            parser.print_help()
    except AuthenticationError as e:
        logging.error(f"Authentication failed: {e}")
        logging.error("Please check your Spotify API credentials in the environment variables")
        sys.exit(1)
    except APIError as e:
        logging.error(f"API error: {e}")
        logging.error("Please check your internet connection and try again")
        sys.exit(1)
    except ValueError as e:
        logging.error(f"Error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logging.info("\nOperation canceled by user.")
        sys.exit(1)
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}", exc_info=getattr(args, "verbose", False))
        sys.exit(1)


if __name__ == "__main__":
    main()