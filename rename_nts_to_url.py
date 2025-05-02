#!/usr/bin/env python3
"""
Script to rename the 'nts' field to 'url' in the shows.json file.
"""

import json
import os

def main():
    # Path to the shows data file
    shows_file = os.path.join("website", "src", "data", "shows.json")
    
    # Load the shows data
    with open(shows_file, "r") as f:
        shows = json.load(f)
    
    # Rename 'nts' to 'url' for each show
    for show in shows:
        if "nts" in show:
            show["url"] = show.pop("nts")
    
    # Save the updated shows data
    with open(shows_file, "w") as f:
        json.dump(shows, f, indent=2)
    
    print(f"Successfully renamed 'nts' field to 'url' in {shows_file}")

if __name__ == "__main__":
    main()