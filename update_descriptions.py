#!/usr/bin/env python3
"""
Script to strip trailing newlines from descriptions in shows.json.
This ensures consistent formatting for all show descriptions.
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
    
    # Update descriptions to remove trailing newlines
    updated_count = 0
    for show in shows:
        if "description" in show and show["description"].endswith("\n"):
            show["description"] = show["description"].rstrip()
            updated_count += 1
    
    # Save the updated shows data
    if updated_count > 0:
        try:
            with open(shows_file, "w") as f:
                json.dump(shows, f, indent=2)
            logging.info(f"Updated {updated_count} show descriptions in {shows_file}")
        except Exception as e:
            logging.error(f"Failed to save shows data: {e}")
    else:
        logging.info("No descriptions needed updating (none had trailing newlines)")

if __name__ == "__main__":
    main()