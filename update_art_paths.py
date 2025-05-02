#!/usr/bin/env python3
"""
Script to update the 'art' field paths in shows.json to remove leading slashes.
This ensures consistent formats between existing and new show entries.
"""

import json
import os
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

def get_shows_data_path():
    """
    Get the path to the shows data file.
    
    Returns:
        Path to the shows.json file
    """
    try:
        # Get the path from settings
        from tracktracker.config import settings
        
        # Make sure the directory exists
        settings.ensure_directories()
        
        return str(settings.paths.shows_data_path)
    except ImportError:
        # Fallback to legacy path if config is not available
        project_root = "/Users/duncancooper/Documents/tracktracker"
        
        # Make sure the directory exists
        data_dir = os.path.join(project_root, "website", "src", "data")
        os.makedirs(data_dir, exist_ok=True)
        
        return os.path.join(data_dir, "shows.json")

def main():
    # Path to the shows data file
    shows_file = get_shows_data_path()
    
    # Load the shows data
    try:
        with open(shows_file, "r") as f:
            shows = json.load(f)
    except Exception as e:
        logging.error(f"Failed to load shows data: {e}")
        return
    
    # Update art paths to remove leading slashes
    updated_count = 0
    for show in shows:
        if "art" in show and show["art"].startswith("/"):
            show["art"] = show["art"].lstrip("/")
            updated_count += 1
    
    # Save the updated shows data
    if updated_count > 0:
        try:
            with open(shows_file, "w") as f:
                json.dump(shows, f, indent=2)
            logging.info(f"Updated {updated_count} show art paths in {shows_file}")
        except Exception as e:
            logging.error(f"Failed to save shows data: {e}")
    else:
        logging.info("No art paths needed updating (none had leading slashes)")

if __name__ == "__main__":
    main()