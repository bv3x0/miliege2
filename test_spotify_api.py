#!/usr/bin/env python3
"""
Simple script to test Spotify API connectivity before running a full archive.
This helps diagnose API rate limit issues.
"""

import logging
import sys
import time
import argparse

from tracktracker import spotify


def test_spotify_connection(verbose=False):
    """Test basic Spotify API connectivity"""
    logging.info("Testing Spotify API connectivity...")
    
    try:
        # First authenticate
        logging.info("Step 1: Authenticating with Spotify...")
        spotify_client = spotify.authenticate("playlist-modify-public")
        logging.info("✓ Authentication successful!")
        
        # Then try to get current user
        logging.info("Step 2: Getting current user...")
        user = spotify_client.current_user()
        logging.info(f"✓ Got user: {user['display_name']} ({user['id']})")
        
        # Then try to get user playlists
        logging.info("Step 3: Getting user playlists...")
        playlists = spotify_client.current_user_playlists(limit=5)
        playlist_count = len(playlists["items"])
        logging.info(f"✓ Got {playlist_count} playlists (limited to 5)")
        
        if playlists["items"]:
            playlist = playlists["items"][0]
            logging.info(f"  First playlist: {playlist['name']} ({playlist['id']})")
        
        # All tests passed
        logging.info("\n✓ All Spotify API tests passed!")
        logging.info("You should be able to create playlists successfully.")
        logging.info("\nRecommended next steps:")
        logging.info("1. Try a small test first: python -m tracktracker.cli playlist <url> --archive --small-test")
        logging.info("2. Then try with a chunk size: python -m tracktracker.cli playlist <url> --archive --chunk-size 3")
        
        return True
    except Exception as e:
        logging.error(f"× Spotify API test failed: {e}")
        if verbose:
            import traceback
            traceback.print_exc()
        
        logging.info("\nSuggestions:")
        logging.info("1. Wait a few minutes before trying again (rate limits reset over time)")
        logging.info("2. Check your Spotify API credentials in the .env file")
        logging.info("3. Try clearing the token cache: rm ~/.tracktracker/spotify_token.json")
        
        return False


if __name__ == "__main__":
    # Parse arguments
    parser = argparse.ArgumentParser(description="Test Spotify API connectivity")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output")
    parser.add_argument("--wait", type=int, default=0, help="Wait time in seconds before testing (to allow rate limits to reset)")
    args = parser.parse_args()
    
    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format="%(levelname)s: %(message)s")
    
    # Wait if requested
    if args.wait > 0:
        logging.info(f"Waiting {args.wait} seconds before testing...")
        time.sleep(args.wait)
    
    # Run the test
    success = test_spotify_connection(args.verbose)
    sys.exit(0 if success else 1)