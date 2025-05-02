"""
Website integration module for tracktracker.

This module handles all interactions with the website data,
including updating the shows list in the PlaylistGrid component.
"""

import json
import os
import logging
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

from tracktracker import utils


# Path to the shows data file
def get_shows_data_path() -> str:
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


def load_shows_data() -> List[Dict[str, Any]]:
    """
    Load shows data from the shows.json file.
    
    Returns:
        List of show data dictionaries
    """
    shows_file = get_shows_data_path()
    
    if os.path.exists(shows_file):
        try:
            with open(shows_file, "r") as f:
                return json.load(f)
        except Exception as e:
            logging.warning(f"Failed to load shows data: {e}")
            return []
    else:
        logging.info("Shows data file doesn't exist yet, will create a new one")
        return []


def save_shows_data(shows: List[Dict[str, Any]], auto_push: bool = False) -> None:
    """
    Save shows data to the shows.json file.
    
    Args:
        shows: List of show data dictionaries
        auto_push: Whether to automatically push changes to GitHub
    """
    shows_file = get_shows_data_path()
    
    try:
        with open(shows_file, "w") as f:
            json.dump(shows, f, indent=2)
        logging.info(f"Saved shows data to {shows_file}")
        
        # Automatically push changes to GitHub if requested
        if auto_push:
            push_website_changes()
    except Exception as e:
        logging.error(f"Failed to save shows data: {e}")
        raise ValueError(f"Failed to save shows data: {e}")


def push_website_changes() -> bool:
    """
    Push website changes to GitHub.
    
    This function:
    1. Pulls the latest changes from GitHub
    2. Commits the changes to shows.json
    3. Pushes the changes to GitHub
    4. The GitHub Actions workflow will then deploy the website
    
    Returns:
        True if the push was successful, False otherwise
    """
    try:
        # Get the project root directory
        project_root = Path(__file__).parent.parent.absolute()
        shows_path = get_shows_data_path()
        relative_path = os.path.relpath(shows_path, project_root)
        
        logging.info(f"Pushing changes to GitHub for {relative_path}")
        
        # First, handle image file conflicts
        # This is a common source of conflicts when images are updated
        image_dir = os.path.join(project_root, "website", "public", "show-images")
        if os.path.exists(image_dir):
            # Check if we need to forcibly add any untracked image files
            git_status_cmd = ["git", "status", "--porcelain", image_dir]
            status_output = subprocess.run(git_status_cmd, cwd=project_root, capture_output=True, text=True).stdout
            
            # Look for any "??" lines that indicate untracked files
            untracked_images = [line.split()[1] for line in status_output.splitlines() 
                               if line.startswith("??") and line.split()[1].endswith((".jpg", ".jpeg", ".png", ".gif"))]
            
            if untracked_images:
                logging.info(f"Adding {len(untracked_images)} untracked image files")
                for img in untracked_images:
                    add_cmd = ["git", "add", img]
                    subprocess.run(add_cmd, cwd=project_root, check=False)
        
        # Try to stash any other changes
        stash_cmd = ["git", "stash", "push", "--include-untracked"]
        subprocess.run(stash_cmd, cwd=project_root, capture_output=True, check=False)
        
        # Try to pull changes
        try:
            logging.info("Pulling latest changes from GitHub")
            pull_command = ["git", "pull", "origin", "main", "--no-rebase"]
            subprocess.run(pull_command, cwd=project_root, check=True)
        except Exception as pull_error:
            logging.warning(f"Unable to pull changes: {pull_error}. Will reset to remote state.")
            # If pull fails, do a hard reset to the remote branch
            try:
                # Fetch the latest state
                fetch_cmd = ["git", "fetch", "origin", "main"]
                subprocess.run(fetch_cmd, cwd=project_root, check=True)
                
                # Reset to match the remote
                reset_cmd = ["git", "reset", "--hard", "origin/main"]
                subprocess.run(reset_cmd, cwd=project_root, check=True)
                
                logging.info("Successfully reset to remote state")
            except Exception as reset_error:
                logging.warning(f"Unable to reset to remote state: {reset_error}")
        
        # Apply the stashed changes
        stash_pop_cmd = ["git", "stash", "pop"]
        try:
            subprocess.run(stash_pop_cmd, cwd=project_root, capture_output=True, check=False)
        except Exception as stash_error:
            logging.warning(f"Unable to apply stashed changes: {stash_error}")
        
        # Add the shows data file
        add_command = ["git", "add", relative_path]
        subprocess.run(add_command, cwd=project_root, check=True)
        
        # Check if there are changes to commit
        status_command = ["git", "status", "--porcelain", relative_path]
        status_result = subprocess.run(status_command, cwd=project_root, capture_output=True, text=True, check=False)
        
        if not status_result.stdout.strip():
            logging.info("No changes to commit for shows data")
            return True
        
        # Commit the changes
        commit_msg = f"Update shows data via tracktracker tool - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        commit_command = ["git", "commit", "-m", commit_msg]
        subprocess.run(commit_command, cwd=project_root, check=True)
        
        # Push to GitHub - use force with lease to be safer than force but still override if needed
        logging.info("Pushing changes to GitHub")
        push_command = ["git", "push", "origin", "main", "--force-with-lease"]
        result = subprocess.run(push_command, cwd=project_root, capture_output=True, text=True)
        
        if result.returncode != 0:
            # If push fails, try a direct force push as a last resort
            logging.warning(f"Push failed, trying force push: {result.stderr}")
            force_push_command = ["git", "push", "origin", "main", "--force"]
            push_result = subprocess.run(force_push_command, cwd=project_root, capture_output=True, text=True)
            
            if push_result.returncode != 0:
                raise Exception(f"Failed even with force push: {push_result.stderr}")
            else:
                logging.info("Successfully force pushed changes to GitHub")
        else:
            logging.info("Successfully pushed changes to GitHub")
            
        logging.info("Website update will be deployed automatically via GitHub Actions")
        return True
    except Exception as e:
        logging.error(f"Failed to push website changes to GitHub: {e}")
        return False


def add_new_show(show_data: Dict[str, Any], auto_push: bool = True) -> None:
    """
    Add a new show to the shows data.
    
    Args:
        show_data: Show data dictionary with all required fields
        auto_push: Whether to automatically push changes to GitHub
    """
    # Load existing shows
    shows = load_shows_data()
    
    # Add the new show at the top of the list
    shows.insert(0, show_data)
    
    # Save the updated shows data and try to push
    save_shows_data(shows, auto_push=auto_push)
    logging.info(f"Added new show: {show_data.get('shortTitle', 'Unknown')}")
    
    if auto_push:
        logging.info("Automatic GitHub push was attempted - check for success or error messages above")
        logging.info("If push failed, you can manually push changes with: git add . && git commit -m 'Update shows' && git push")


def update_show_end_date(show_index: int, new_end_date: str, auto_push: bool = True) -> bool:
    """
    Update the end date for a show in the shows data.
    
    Args:
        show_index: Index of the show to update
        new_end_date: New end date in ISO format (YYYY-MM-DD)
        auto_push: Whether to automatically push changes to GitHub
        
    Returns:
        True if the date was updated, False if no change was needed
    """
    # Load existing shows
    shows = load_shows_data()
    
    # Check if the index is valid
    if show_index >= 0 and show_index < len(shows):
        # Check if the date is actually changing
        current_end_date = shows[show_index].get("endDate", "")
        if current_end_date == new_end_date:
            logging.info(f"End date for {shows[show_index].get('shortTitle', 'Unknown')} is already {new_end_date}, no update needed")
            return False
            
        # Update the end date
        shows[show_index]["endDate"] = new_end_date
        
        # Save the updated shows data
        save_shows_data(shows, auto_push=auto_push)
        logging.info(f"Updated end date for {shows[show_index].get('shortTitle', 'Unknown')} to {new_end_date}")
        
        if auto_push:
            logging.info("Automatic GitHub push was attempted - check for success or error messages above")
            logging.info("If push failed, you can manually push changes with: git add . && git commit -m 'Update shows' && git push")
        return True
    else:
        logging.error(f"Invalid show index: {show_index}")
        raise ValueError(f"Invalid show index: {show_index}")


def create_show_data_from_nts(
    nts_url: str,
    nts_data: Dict[str, Any],
    spotify_url: str,
    apple_url: str,
    short_title: str,
    artwork_path: str,
    custom_description: str = ""
) -> Dict[str, Any]:
    """
    Create a show data dictionary from NTS data and user inputs.
    
    Args:
        nts_url: NTS show URL
        nts_data: Data from NTS API
        spotify_url: Spotify playlist URL
        apple_url: Apple Music playlist URL
        short_title: Short title for the show
        artwork_path: Path to artwork file
        custom_description: Custom description to use if not available from API
        
    Returns:
        Show data dictionary
    """
    # Extract information from NTS data
    long_title = nts_data.get("show_name", short_title)
    
    # Process dates - get from episodes data if available
    start_date = ""
    end_date = ""
    if nts_data.get("episodes_data"):
        # Use date arrays to sort and determine earliest/latest date
        dates = []
        for episode in nts_data.get("episodes_data", []):
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
        
        # Sort dates and get earliest and latest
        if dates:
            dates.sort()  # This sorts in ascending order (oldest to newest)
            start_date = dates[0]     # Earliest date
            end_date = dates[-1]      # Latest date
    
    frequency = nts_data.get("frequency", "Monthly")
    
    # Use custom description if provided, otherwise try to get from API
    description = custom_description or nts_data.get("description", "")
    
    # Copy artwork to the website directory
    art_web_path = utils.copy_artwork(artwork_path)
    
    # Format Spotify URL
    formatted_spotify_url = utils.format_spotify_url(spotify_url)
    
    # Create embed codes
    spotify_embed = utils.create_spotify_embed(formatted_spotify_url)
    apple_embed = utils.create_apple_embed(apple_url)
    
    # Create the show data
    show_data = {
        "shortTitle": short_title,
        "longTitle": long_title,
        "art": art_web_path,
        "url": nts_url,
        "apple": apple_url,
        "spotify": formatted_spotify_url,
        "appleEmbed": apple_embed,
        "spotifyEmbed": spotify_embed,
        "frequency": frequency,
        "startDate": start_date,
        "endDate": end_date,
        "source": "NTS"  # Default source for NTS shows
    }
    
    # Add description if available, stripping trailing newlines
    if description:
        show_data["description"] = description.rstrip()
    
    return show_data


def create_show_data_manual(
    show_url: str,
    spotify_url: str,
    apple_url: str,
    short_title: str,
    long_title: str,
    artwork_path: str,
    description: str,
    source: str,
    frequency: str = "Monthly",
    start_date: str = "",
    end_date: str = ""
) -> Dict[str, Any]:
    """
    Create a show data dictionary from manual inputs for non-NTS shows.
    
    Args:
        show_url: URL to the show (Mixcloud, Soundcloud, etc.)
        spotify_url: Spotify playlist URL
        apple_url: Apple Music playlist URL
        short_title: Short title for the show
        long_title: Full title for the show
        artwork_path: Path to artwork file
        description: Description of the show
        source: Source of the show (Mixcloud, Soundcloud, etc.)
        frequency: Show frequency (default: Monthly)
        start_date: First episode date in YYYY-MM-DD format
        end_date: Latest episode date in YYYY-MM-DD format
        
    Returns:
        Show data dictionary
    """
    # Copy artwork to the website directory
    art_web_path = utils.copy_artwork(artwork_path)
    
    # Format Spotify URL
    formatted_spotify_url = utils.format_spotify_url(spotify_url)
    
    # Create embed codes
    spotify_embed = utils.create_spotify_embed(formatted_spotify_url)
    apple_embed = utils.create_apple_embed(apple_url)
    
    # Create the show data
    show_data = {
        "shortTitle": short_title,
        "longTitle": long_title,
        "art": art_web_path,
        "url": show_url,  # Using "url" field instead of "nts"
        "apple": apple_url,
        "spotify": formatted_spotify_url,
        "appleEmbed": apple_embed,
        "spotifyEmbed": spotify_embed,
        "frequency": frequency,
        "startDate": start_date,
        "endDate": end_date,
        "source": source
    }
    
    # Add description if available, stripping trailing newlines
    if description:
        show_data["description"] = description.rstrip()
    
    return show_data


def deploy_website() -> bool:
    """
    Manually deploy the website by pushing any changes to GitHub.
    
    This is useful when you want to push changes to the website without making
    changes to the shows data.
    
    Returns:
        True if the deploy was successful, False otherwise
    """
    return push_website_changes()