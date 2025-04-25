#!/usr/bin/env python3
"""
Script to reset Spotify authentication and clear any cached tokens.
This can help when rate limits are preventing normal authentication.
"""

import os
import sys
import time
import logging
import argparse
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

def get_token_path():
    """Get the path to the Spotify token cache file"""
    try:
        from tracktracker.config import settings
        return settings.paths.spotify_token_path
    except ImportError:
        # Fallback to default location
        home_dir = Path.home()
        return home_dir / ".tracktracker" / "spotify_token.json"

def reset_authentication(force=False):
    """Reset the Spotify authentication by removing token cache"""
    token_path = get_token_path()
    
    if os.path.exists(token_path):
        if not force:
            confirm = input(f"This will delete your Spotify token cache at {token_path}. Continue? (y/N): ")
            if confirm.lower() != 'y':
                logging.info("Operation cancelled.")
                return False
                
        try:
            # Backup the file first
            backup_path = str(token_path) + ".bak"
            if os.path.exists(token_path):
                with open(token_path, 'r') as f_in:
                    with open(backup_path, 'w') as f_out:
                        f_out.write(f_in.read())
                logging.info(f"Backed up token to {backup_path}")
                
            # Remove the token file
            os.remove(token_path)
            logging.info(f"Removed Spotify token cache from {token_path}")
            logging.info("Next time you use tracktracker, you'll need to authenticate with Spotify again.")
            return True
        except Exception as e:
            logging.error(f"Error removing token cache: {e}")
            return False
    else:
        logging.info(f"No token cache found at {token_path}. Nothing to do.")
        return True

def suggest_next_steps():
    """Suggest next steps for the user"""
    logging.info("\nNext steps:")
    logging.info("1. Wait at least 30 minutes before trying again")
    logging.info("2. Run a small test first:")
    logging.info("   python -m tracktracker.cli playlist [URL] --archive --small-test")
    logging.info("3. If that works, process in small chunks:")
    logging.info("   python -m tracktracker.cli playlist [URL] --archive --chunk-size 3")
    logging.info("\nIf you continue to see rate limit errors, try waiting a few hours")
    logging.info("before attempting again. Spotify rate limits typically fully reset after 24 hours.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reset Spotify authentication")
    parser.add_argument("-f", "--force", action="store_true", help="Force reset without confirmation")
    parser.add_argument("--clear-cache", action="store_true", help="Also clear the track search cache")
    args = parser.parse_args()
    
    logging.info("Resetting Spotify authentication...")
    success = reset_authentication(args.force)
    
    if success:
        if args.clear_cache:
            try:
                from tracktracker import spotify
                spotify.clear_track_cache()
                logging.info("Cleared track search cache.")
            except Exception as e:
                logging.error(f"Failed to clear track search cache: {e}")
                
        suggest_next_steps()
        sys.exit(0)
    else:
        sys.exit(1)