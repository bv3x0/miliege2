"""
Scraper for NTS Radio show tracklists.

Uses direct JSON API access to extract track information from NTS Radio shows.
"""

import re
import sys
import json
from typing import Dict, List, Any, Optional
from urllib.parse import urlparse

import requests
from collections import defaultdict
import csv
import datetime
from bs4 import BeautifulSoup

from tracktracker.api_utils import (
    make_json_request,
    make_request,
    retry_with_backoff,
    APIError,
    RateLimitError,
    NonRecoverableError,
    DataValidationError,
)


def parse_nts_url(url: str) -> Dict[str, str]:
    """
    Parse an NTS Radio URL to extract show and episode aliases.
    
    Args:
        url: NTS Radio episode URL
        
    Returns:
        Dictionary with 'show_alias' and optionally 'episode_alias'
        
    Raises:
        ValueError: If the URL format is not recognized or missing required components
    """
    parsed = urlparse(url)
    
    if "nts.live" not in parsed.netloc:
        raise ValueError("Not an NTS Radio URL")
    
    # Extract path components
    path = parsed.path.strip("/").split("/")
    
    # Show URL format: /shows/{show}
    if len(path) == 2 and path[0] == "shows":
        return {
            "show_alias": path[1],
            "is_show": True
        }
    
    # Standard URL format: /shows/{show}/episodes/{episode}
    if len(path) >= 4 and path[0] == "shows" and path[2] == "episodes":
        return {
            "show_alias": path[1],
            "episode_alias": path[3],
            "is_show": False
        }
    
    # Alternative format: /shows/{show}/{episode}
    elif len(path) >= 3 and path[0] == "shows":
        return {
            "show_alias": path[1],
            "episode_alias": path[2],
            "is_show": False
        }
    
    # Handle direct episode URL: /{show_or_episode}
    elif len(path) == 1:
        # Assume it's an episode alias
        # Try to extract show alias from a common pattern
        parts = path[0].split("-")
        if len(parts) > 1:
            # Use first part as show and full path as episode
            return {
                "show_alias": parts[0],
                "episode_alias": path[0],
                "is_show": False
            }
        return {
            "show_alias": "guests",  # Default to guests
            "episode_alias": path[0],
            "is_show": False
        }
    
    # If we can't parse it with any of our rules
    raise ValueError(
        "Couldn't parse NTS URL format. Expected formats:\n"
        "- https://www.nts.live/shows/{show}/episodes/{episode}\n"
        "- https://www.nts.live/shows/{show}/{episode}\n"
        "- https://www.nts.live/{episode}\n"
        "- https://www.nts.live/shows/{show} (show archive)"
    )


@retry_with_backoff(max_retries=5, base_delay=2.0)
def get_show_info(show_alias: str) -> Dict[str, Any]:
    """
    Get information about a show from NTS API.
    
    Args:
        show_alias: The show alias from the URL
        
    Returns:
        Dictionary containing show information
        
    Raises:
        APIError: If the API request fails
        DataValidationError: If the response is not valid JSON
        AuthenticationError: If authentication fails
        NonRecoverableError: For other non-recoverable errors
    """
    url = f"https://www.nts.live/api/v2/shows/{show_alias}"
    
    headers = {
        "Accept": "application/json",
        "User-Agent": "tracktracker/1.0"
    }
    
    try:
        print(f"Requesting JSON from show page: {url}")
        return make_json_request(url=url, headers=headers)
    except (APIError, NonRecoverableError) as e:
        # Convert to standard ValueError for backward compatibility
        # In the future, we could propagate these more specific errors
        raise ValueError(f"Failed to fetch NTS show data: {e}") from e


@retry_with_backoff(max_retries=3, base_delay=1.0)
def get_show_episodes(
    show_alias: str, 
    limit_count: Optional[int] = None,
    use_cache: bool = True,
    force_refresh: bool = False
) -> List[Dict[str, Any]]:
    """
    Get episodes for a show from NTS API, with optional lazy loading.
    
    Args:
        show_alias: The show alias from the URL
        limit_count: Maximum number of episodes to fetch (None for all)
        use_cache: Whether to use cached data
        force_refresh: Force refresh the cache
        
    Returns:
        List of episode dictionaries with their information
        
    Raises:
        ValueError: If the request fails or returns an invalid response
    """
    try:
        # Get basic show information first (this will be cached if caching is enabled)
        show_data = get_show_info(show_alias)
        
        # Episodes are accessed via the embeds.episodes path
        if "embeds" not in show_data or "episodes" not in show_data["embeds"]:
            raise ValueError(f"Could not find episodes for show: {show_alias}")
        
        episodes_data = show_data["embeds"]["episodes"]
        
        # Initialize empty list for all episodes
        all_episodes = []
        
        # Check if we have episodes data and metadata for pagination
        if "results" in episodes_data and isinstance(episodes_data["results"], list):
            all_episodes.extend(episodes_data["results"])
            
            # Get pagination metadata if available
            if "metadata" in episodes_data and "resultset" in episodes_data["metadata"]:
                total_count = episodes_data["metadata"]["resultset"].get("count", 0)
                api_limit = episodes_data["metadata"]["resultset"].get("limit", 12)
                
                # Use limit_count if specified, otherwise fetch all episodes
                if limit_count is not None:
                    episodes_to_fetch = min(limit_count, total_count)
                else:
                    episodes_to_fetch = total_count
                
                # If we need more episodes and have not reached our limit
                if episodes_to_fetch > len(all_episodes):
                    print(f"Show has {total_count} episodes, fetching up to {episodes_to_fetch}...")
                    
                    # Fetch remaining pages as needed
                    offset = api_limit
                    while offset < total_count and len(all_episodes) < episodes_to_fetch:
                        url = f"https://www.nts.live/api/v2/shows/{show_alias}/episodes?offset={offset}&limit={api_limit}"
                        
                        headers = {
                            "Accept": "application/json",
                            "User-Agent": "tracktracker/1.0"
                        }
                        
                        try:
                            print(f"Fetching more episodes from offset {offset}...")
                            # Use our centralized request function with caching
                            page_data = make_json_request(
                                url=url, 
                                headers=headers,
                                use_cache=use_cache,
                                force_refresh=force_refresh,
                                cache_max_age=86400  # Cache for 24 hours by default
                            )
                            
                            # Extract episodes from this page
                            if "results" in page_data and isinstance(page_data["results"], list):
                                # Only add episodes up to our desired limit
                                if limit_count is not None:
                                    remaining = episodes_to_fetch - len(all_episodes)
                                    all_episodes.extend(page_data["results"][:remaining])
                                else:
                                    all_episodes.extend(page_data["results"])
                            
                            # Move to the next page
                            offset += api_limit
                        except (APIError, DataValidationError) as e:
                            # If we fail to get a page, we can still continue with what we have
                            print(f"Warning: Failed to fetch episodes page at offset {offset}: {e}")
                            # We've already retried with backoff, so we'll just move on
                            break
        
        # Limit the final result if needed
        if limit_count is not None and len(all_episodes) > limit_count:
            all_episodes = all_episodes[:limit_count]
            
        print(f"Found {len(all_episodes)} episodes for show: {show_alias}")
        return all_episodes
    except Exception as e:
        # Capture any unexpected errors and standardize the error message
        # While maintaining backward compatibility with existing code
        raise ValueError(f"Failed to get episodes for show {show_alias}: {e}") from e


@retry_with_backoff(max_retries=5, base_delay=2.0)
def get_tracklist_from_episode_page(show_alias: str, episode_alias: str) -> Dict[str, Any]:
    """
    Get the tracklist directly from the episode page JSON API.
    
    This is the method used by NTS Archiver - requesting the page with Accept: application/json
    to get the JSON data including the tracklist.
    
    Args:
        show_alias: The show alias from the URL
        episode_alias: The episode alias from the URL
        
    Returns:
        Dictionary containing API response with tracklist
        
    Raises:
        APIError: If the API request fails
        DataValidationError: If the response is not valid JSON
        AuthenticationError: If authentication fails
        NonRecoverableError: For other non-recoverable errors
    """
    # Get the episode data
    url = f"https://www.nts.live/api/v2/shows/{show_alias}/episodes/{episode_alias}"
    
    headers = {
        "Accept": "application/json",
        "User-Agent": "tracktracker/1.0"
    }
    
    try:
        print(f"Requesting JSON from episode page: {url}")
        # Using our standardized API request function with built-in retry logic
        return make_json_request(url=url, headers=headers)
    except (APIError, DataValidationError) as e:
        # Convert to standard ValueError for backward compatibility
        raise ValueError(f"Failed to fetch NTS episode data: {e}") from e


def parse_tracklist(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse the NTS API response to extract track information.
    
    Args:
        data: The episode JSON data
        
    Returns:
        Dictionary with 'tracks' list and 'episode_title'
    """
    result = {
        "tracks": [],
        "episode_title": data.get("name", ""),
        "broadcast_date": data.get("broadcast", "")
    }
    
    # Try to get show information
    if "show" in data and isinstance(data["show"], dict):
        result["show_name"] = data["show"].get("name", "")
    
    # Check if there's a location in the episode details
    if "location" in data:
        result["location"] = data.get("location", "")
    elif "location_long" in data:
        result["location"] = data.get("location_long", "")
    
    # Check if tracklist exists in the data under the new structure (embeds.tracklist.results)
    tracklist_items = []
    if "embeds" in data and "tracklist" in data["embeds"] and "results" in data["embeds"]["tracklist"]:
        tracklist_items = data["embeds"]["tracklist"]["results"]
    elif "tracklist" in data and isinstance(data["tracklist"], list):
        # Fallback to the old format if present
        tracklist_items = data["tracklist"]
    
    if not tracklist_items:
        print("No tracklist found in episode data")
        return result
    
    print(f"Found {len(tracklist_items)} tracks in the tracklist")
    
    # Process each track in the tracklist
    for track_item in tracklist_items:
        try:
            # In the new API format, artist and title are directly in the track object
            artist = track_item.get("artist", "")
            title = track_item.get("title", "")
            
            # If we don't have artist/title directly, try the old format with mainArtists
            if not artist and "mainArtists" in track_item and track_item["mainArtists"]:
                if isinstance(track_item["mainArtists"], list) and len(track_item["mainArtists"]) > 0:
                    artist = track_item["mainArtists"][0].get("name", "")
                    
                    # If a second artist exists, add it
                    if len(track_item["mainArtists"]) > 1:
                        second_artist = track_item["mainArtists"][1].get("name", "")
                        if second_artist:
                            artist += f" & {second_artist}"
            
            # Skip if missing artist or title
            if not artist or not title:
                print(f"Skipping track missing artist or title: {track_item}")
                continue
            
            result["tracks"].append({
                "artist": artist,
                "title": title
            })
        except Exception as e:
            # Skip problematic entries but continue processing
            print(f"Error parsing track: {e}")
            continue
    
    return result


def scrape(url: str) -> Dict[str, Any]:
    """
    Scrape track information from an NTS Radio episode or show.
    
    Args:
        url: URL to an NTS Radio episode or show
        
    Returns:
        Dictionary with 'tracks' list, 'episode_title', and other metadata.
        If URL is for a show, includes 'episodes_data' list with all episodes.
        
    Raises:
        ValueError: If the URL is invalid or the scrape fails
    """
    # Parse the URL to get show and episode aliases
    aliases = parse_nts_url(url)
    
    # Check if this is a show URL or an episode URL
    if aliases.get("is_show", False):
        # If it's a show URL, fetch all episodes
        show_alias = aliases["show_alias"]
        
        # Get basic show information
        show_data = get_show_info(show_alias)
        show_name = show_data.get("name", show_alias)
        
        # Get episodes list
        episodes = get_show_episodes(show_alias)
        
        # Process each episode
        episodes_data = []
        for episode in episodes:
            # Episode aliases may be under different fields depending on the API version
            episode_alias = episode.get("episode_alias") or episode.get("slug")
            if not episode_alias:
                print(f"Skipping episode with no alias: {episode}")
                continue
                
            try:
                # Get detailed episode information including tracklist
                episode_data = get_tracklist_from_episode_page(show_alias, episode_alias)
                tracklist_data = parse_tracklist(episode_data)
                
                # Only add episodes with tracks
                if tracklist_data["tracks"]:
                    episodes_data.append(tracklist_data)
            except Exception as e:
                print(f"Error processing episode {episode_alias}: {e}")
                continue
        
        # Return show information and episodes data
        return {
            "show_name": show_name,
            "show_alias": show_alias,
            "is_show": True,
            "episodes_data": episodes_data,
            "episode_count": len(episodes_data)
        }
    else:
        # If it's an episode URL, fetch the single episode data
        show_alias = aliases["show_alias"]
        episode_alias = aliases["episode_alias"]
        
        # Get the episode data from the JSON API
        data = get_tracklist_from_episode_page(show_alias, episode_alias)
        
        # Parse the tracklist to extract track information
        result = parse_tracklist(data)
        
        # For the show name, check in multiple places where it might be found
        show_name = None
        if "show" in data and isinstance(data["show"], dict):
            show_name = data["show"].get("name") 
        
        if not show_name and "show_alias" in data:
            # If we couldn't find the show name in the episode data but have the show alias,
            # try to get the show information separately
            try:
                show_data = get_show_info(data["show_alias"])
                show_name = show_data.get("name")
            except:
                # If that fails, just use the show alias from the URL
                pass
        
        # If we still don't have a show name, fall back to the show alias from the URL
        if not show_name:
            show_name = show_alias
            
        result["show_name"] = show_name
        result["show_alias"] = show_alias
        result["is_show"] = False
        
        return result


def get_latest_episodes(days=7):
    """
    Get episodes published in the last N days.
    
    Args:
        days: Number of days to look back
        
    Returns:
        List of episode data with their tracklists
    """
    # Calculate the date N days ago
    end_date = datetime.datetime.now(datetime.timezone.utc)
    start_date = end_date - datetime.timedelta(days=days)
    
    print(f"Looking for episodes between {start_date.strftime('%Y-%m-%d')} and {end_date.strftime('%Y-%m-%d')} (UTC)")
    
    # Headers for API requests
    headers = {
        "Accept": "application/json",
        "User-Agent": "tracktracker/1.0"
    }
    
    # Initialize episodes collection
    recent_episodes = []
    
    # 1. First fetch the latest page content with full scrolling to load all shows
    try:
        # Use Playwright to automate scrolling
        from playwright.sync_api import sync_playwright
        import time
        
        print("Starting browser to scrape the latest page with scrolling...")
        with sync_playwright() as p:
            # Launch browser (headless by default)
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            )
            
            # Go to the latest page
            print("Navigating to https://www.nts.live/latest")
            page.goto("https://www.nts.live/latest", wait_until="networkidle")
            
            # Wait for content to load - first check if there are any episode cards
            print("Waiting for content to load...")
            page.wait_for_load_state("domcontentloaded")
            
            # Give extra time for any JavaScript to run and render content
            time.sleep(5)
            
            # Now check for any elements that look like episode cards
            # Try different selectors that might match episode cards
            episode_card_selectors = [
                "article", ".episode-card", "[class*=episode]", "[class*=show]",
                "a[href*='/shows/']", ".latest a", ".latest-episode", "a[href*='episodes']"
            ]
            
            # Try each selector until we find something
            found_valid_selector = False
            for selector in episode_card_selectors:
                try:
                    print(f"Trying to find episodes with selector: {selector}")
                    count = page.locator(selector).count()
                    if count > 0:
                        print(f"Found {count} elements with selector '{selector}'")
                        found_valid_selector = True
                        break
                except Exception as e:
                    print(f"Error with selector '{selector}': {e}")
                    continue
            
            if not found_valid_selector:
                print("Could not find any episode elements with standard selectors.")
                print("Taking a screenshot to diagnose the issue...")
                page.screenshot(path="nts_latest_screenshot.png")
                print("Screenshot saved as nts_latest_screenshot.png")
            
            # Scroll down repeatedly to trigger lazy loading
            print("Scrolling to load all episodes...")
            max_scroll_attempts = 15
            scroll_count = 0
            
            # Get initial page height
            prev_height = page.evaluate("document.body.scrollHeight")
            
            while scroll_count < max_scroll_attempts:
                # Scroll to bottom of page
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                
                # Wait for content to load
                time.sleep(3)
                
                # Get new page height
                new_height = page.evaluate("document.body.scrollHeight")
                
                scroll_count += 1
                print(f"Scroll attempt {scroll_count}/{max_scroll_attempts}: page height changed from {prev_height} to {new_height}")
                
                # If height didn't change, we've reached the bottom or no more content is loading
                if new_height == prev_height:
                    # Try one more scroll with longer wait time to be sure
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(5)
                    final_height = page.evaluate("document.body.scrollHeight")
                    
                    if final_height == new_height:
                        print("Reached the end of content, no more shows to load")
                        break
                    else:
                        # Still loading content, continue scrolling
                        prev_height = final_height
                        continue
                
                prev_height = new_height
            
            # Get all links on the page after scrolling
            # We'll extract episode URLs directly
            all_links = page.evaluate("""
                Array.from(document.querySelectorAll('a[href]')).map(a => a.href)
                .filter(href => href.includes('/shows/') && (href.includes('/episodes/') || href.includes('latest')))
            """)
            
            print(f"Found {len(all_links)} potential episode links on the page")
            
            # Get the page content after scrolling
            html_content = page.content()
            
            # Close the browser
            browser.close()
            
            print("Browser session completed, processing the loaded content")
            
            # Process all the scraped links
            episode_links = []
            for link in all_links:
                try:
                    # Parse URL to extract show and episode slugs
                    url_parts = parse_nts_url(link)
                    
                    if "show_alias" in url_parts and "episode_alias" in url_parts and not url_parts.get("is_show", False):
                        # It's a valid episode link
                        episode_links.append({
                            "url": link,
                            "show_alias": url_parts["show_alias"],
                            "episode_alias": url_parts["episode_alias"]
                        })
                except Exception as e:
                    print(f"Error parsing link {link}: {e}")
                    continue
                
            print(f"Found {len(episode_links)} valid episode links")
            
            # Now process each valid episode link to get detailed info
            for link_info in episode_links:
                try:
                    show_alias = link_info["show_alias"]
                    episode_alias = link_info["episode_alias"]
                    
                    print(f"Processing episode: {show_alias}/{episode_alias}")
                    
                    # Get episode data with tracklist
                    episode_data = get_tracklist_from_episode_page(show_alias, episode_alias)
                    
                    # Get broadcast date for filtering
                    broadcast_date = episode_data.get("broadcast", "")
                    if not broadcast_date:
                        print(f"No broadcast date found for {show_alias}/{episode_alias}")
                        continue
                    
                    # Convert to datetime for filtering
                    if broadcast_date.endswith('Z'):
                        broadcast_date = broadcast_date.replace("Z", "+00:00")
                    
                    try:
                        episode_date = datetime.datetime.fromisoformat(broadcast_date)
                        
                        # If it's a naive datetime, assume UTC
                        if episode_date.tzinfo is None:
                            episode_date = episode_date.replace(tzinfo=datetime.timezone.utc)
                        
                        # Only include episodes in the requested time range
                        if episode_date >= start_date and episode_date <= end_date:
                            print(f"Found episode in time range: {episode_data.get('name', '')}")
                            
                            # Parse tracklist to extract track information
                            episode_info = parse_tracklist(episode_data)
                            
                            # Add to our collection
                            recent_episodes.append(episode_info)
                        else:
                            print(f"Episode outside time range: {broadcast_date}")
                    except Exception as e:
                        print(f"Error parsing date {broadcast_date}: {e}")
                        continue
                    
                except Exception as e:
                    print(f"Error processing episode link {link_info['url']}: {e}")
                    continue
            
            # Also process the HTML content to find episodes that might have been missed
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Find all episode cards
            episode_containers = soup.select('article') or soup.select('.episode-card') or soup.select('[class*="episode"]') or soup.select('[class*="show"]')
            
            print(f"Found {len(episode_containers)} episode containers on the latest page after scrolling")
            
            for container in episode_containers:
                try:
                    # Extract episode details
                    # Find the episode link - it typically contains the show/episode slug
                    episode_link = container.select_one('a')
                    if not episode_link or not episode_link.get('href'):
                        continue
                        
                    episode_url = episode_link.get('href')
                    
                    # Parse the URL to extract show and episode slugs
                    try:
                        url_parts = parse_nts_url("https://www.nts.live" + episode_url if not episode_url.startswith('http') else episode_url)
                        
                        show_alias = url_parts.get('show_alias')
                        episode_alias = url_parts.get('episode_alias')
                        
                        if not show_alias or not episode_alias:
                            continue
                            
                        # Try to extract basic info from HTML elements
                        show_name = ''
                        episode_title = ''
                        
                        # Look for h2, h3, h4 elements for titles
                        title_elements = container.select('h2, h3, h4, h5')
                        if title_elements:
                            # If there are multiple titles, assume first is show name and second is episode title
                            if len(title_elements) >= 2:
                                show_name = title_elements[0].get_text().strip()
                                episode_title = title_elements[1].get_text().strip()
                            else:
                                # If only one title, use it for both
                                show_name = title_elements[0].get_text().strip()
                                episode_title = show_name
                        
                        # If titles are missing, try looking for text in spans or strong elements
                        if not show_name:
                            title_spans = container.select('span strong, strong, span.title, .show-name, .episode-title')
                            if title_spans:
                                show_name = title_spans[0].get_text().strip()
                                if len(title_spans) >= 2:
                                    episode_title = title_spans[1].get_text().strip()
                                else:
                                    episode_title = show_name

                        # Extract location if available
                        location = ""
                        location_elem = container.select_one('[class*="location"], .subtitle')
                        if location_elem:
                            location = location_elem.get_text().strip()
                        
                        # Look for date element which could be a time tag or div with date class
                        date_elem = container.select_one('time') or container.select_one('[class*="date"]')
                        broadcast_date = date_elem.get('datetime') if date_elem and date_elem.get('datetime') else None
                        
                        # If we couldn't find a valid date, try alternatives
                        if not broadcast_date:
                            # Try to see if there's a date in text format (like the displayed date)
                            date_text = date_elem.get_text().strip() if date_elem else None
                            if date_text:
                                # Try common date formats and combinations with the year
                                import dateutil.parser
                                try:
                                    # First try as is
                                    parsed_date = dateutil.parser.parse(date_text)
                                    broadcast_date = parsed_date.isoformat()
                                except:
                                    # If simple parsing fails, try adding current year
                                    current_year = datetime.datetime.now().year
                                    try:
                                        parsed_date = dateutil.parser.parse(f"{date_text} {current_year}")
                                        broadcast_date = parsed_date.isoformat()
                                    except:
                                        pass
                        
                        # If we still don't have a date, try to fetch the detailed info
                        if not broadcast_date:
                            try:
                                # Fetch episode details to get broadcast date
                                episode_data = get_tracklist_from_episode_page(show_alias, episode_alias)
                                broadcast_date = episode_data.get('broadcast', '')
                            except:
                                # If we can't get the date, we'll have to skip this episode
                                continue
                        
                        # Convert to datetime for filtering
                        if broadcast_date:
                            # Make sure we have a timezone-aware datetime for comparison
                            if broadcast_date.endswith('Z'):
                                # UTC time with Z suffix
                                broadcast_date = broadcast_date.replace("Z", "+00:00")
                            
                            episode_date = datetime.datetime.fromisoformat(broadcast_date) 
                            
                            # If it's a naive datetime, assume UTC
                            if episode_date.tzinfo is None:
                                episode_date = episode_date.replace(tzinfo=datetime.timezone.utc)
                            
                            # Only include episodes in the requested time range
                            if episode_date >= start_date and episode_date <= end_date:
                                print(f"Found episode in time range: {episode_title or show_name}")
                                
                                # Try to get detailed episode data with tracklist
                                try:
                                    episode_data = get_tracklist_from_episode_page(show_alias, episode_alias)
                                    episode_info = parse_tracklist(episode_data)
                                    
                                    # Add show/episode information if missing
                                    if not episode_info.get('show_name') and show_name:
                                        episode_info['show_name'] = show_name
                                    if not episode_info.get('episode_title') and episode_title:
                                        episode_info['episode_title'] = episode_title
                                    
                                    episode_info['show_alias'] = show_alias
                                    episode_info['location'] = location
                                    
                                    # Add to our collection
                                    recent_episodes.append(episode_info)
                                except Exception as e:
                                    print(f"Error fetching tracklist for {show_alias}/{episode_alias}: {e}")
                                    
                                    # Still add a minimal episode record
                                    recent_episodes.append({
                                        "show_name": show_name or show_alias,
                                        "episode_title": episode_title or show_name or episode_alias,
                                        "broadcast_date": broadcast_date,
                                        "show_alias": show_alias,
                                        "location": location,
                                        "tracks": []
                                    })
                    except Exception as e:
                        print(f"Error parsing URL or date: {e}")
                        continue
                except Exception as e:
                    print(f"Error processing episode container: {e}")
                    continue
                    
    except ImportError:
        print("Playwright not available. Falling back to basic HTML scraping...")
        # Fallback to basic HTML scraping without scrolling
        try:
            url = "https://www.nts.live/latest"
            print(f"Requesting content from latest page: {url}")
            
            # Use standard HTML headers for the webpage 
            html_headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1"
            }
            
            response = requests.get(url, headers=html_headers)
            response.raise_for_status()
            
            # Process the HTML content to find episode entries
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # The latest page displays episodes in a grid/list
            # Look for article elements or other containers with episode information
            episode_containers = soup.select('article') or soup.select('.episode-card') or soup.select('.latest-episode')
            
            # If we can't find using standard selectors, look for common patterns
            if not episode_containers:
                # Look for any div with episode data attributes
                episode_containers = soup.select('div[data-episode-id]') or soup.select('div[data-episode]')
                
                # As a fallback, look for elements with show or episode in class names
                if not episode_containers:
                    episode_containers = soup.select('[class*="episode"]') or soup.select('[class*="show"]')
            
            print(f"Found {len(episode_containers)} episode containers on the latest page")
            
            # Rest of the code to process episode containers - same as above
            for container in episode_containers:
                # ... processing code (same as in the Playwright section) ...
                # This code is intentionally omitted to avoid duplication
                # It's the same logic for processing each container
                try:
                    # Extract episode details
                    # Find the episode link - it typically contains the show/episode slug
                    episode_link = container.select_one('a')
                    if not episode_link or not episode_link.get('href'):
                        continue
                        
                    episode_url = episode_link.get('href')
                    
                    # Parse the URL to extract show and episode slugs
                    try:
                        url_parts = parse_nts_url("https://www.nts.live" + episode_url if not episode_url.startswith('http') else episode_url)
                        
                        show_alias = url_parts.get('show_alias')
                        episode_alias = url_parts.get('episode_alias')
                        
                        if not show_alias or not episode_alias:
                            continue
                            
                        # Try to extract basic info from HTML elements
                        show_name = ''
                        episode_title = ''
                        
                        # Look for h2, h3, h4 elements for titles
                        title_elements = container.select('h2, h3, h4, h5')
                        if title_elements:
                            # If there are multiple titles, assume first is show name and second is episode title
                            if len(title_elements) >= 2:
                                show_name = title_elements[0].get_text().strip()
                                episode_title = title_elements[1].get_text().strip()
                            else:
                                # If only one title, use it for both
                                show_name = title_elements[0].get_text().strip()
                                episode_title = show_name
                        
                        # If titles are missing, try looking for text in spans or strong elements
                        if not show_name:
                            title_spans = container.select('span strong, strong, span.title, .show-name, .episode-title')
                            if title_spans:
                                show_name = title_spans[0].get_text().strip()
                                if len(title_spans) >= 2:
                                    episode_title = title_spans[1].get_text().strip()
                                else:
                                    episode_title = show_name

                        # Extract location if available
                        location = ""
                        location_elem = container.select_one('[class*="location"], .subtitle')
                        if location_elem:
                            location = location_elem.get_text().strip()
                        
                        # Look for date element which could be a time tag or div with date class
                        date_elem = container.select_one('time') or container.select_one('[class*="date"]')
                        broadcast_date = date_elem.get('datetime') if date_elem and date_elem.get('datetime') else None
                        
                        # If we couldn't find a valid date, skip this episode as we need to filter by date
                        if not broadcast_date:
                            # Try to see if there's a date in text format
                            date_text = date_elem.get_text().strip() if date_elem else None
                            if date_text:
                                # Try common date formats
                                import dateutil.parser
                                try:
                                    parsed_date = dateutil.parser.parse(date_text)
                                    broadcast_date = parsed_date.isoformat()
                                except:
                                    pass
                        
                        # If we still don't have a date, try to fetch the detailed info
                        if not broadcast_date:
                            try:
                                # Fetch episode details to get broadcast date
                                episode_data = get_tracklist_from_episode_page(show_alias, episode_alias)
                                broadcast_date = episode_data.get('broadcast', '')
                            except:
                                # If we can't get the date, we'll have to skip this episode
                                continue
                        
                        # Convert to datetime for filtering
                        if broadcast_date:
                            # Make sure we have a timezone-aware datetime for comparison
                            if broadcast_date.endswith('Z'):
                                # UTC time with Z suffix
                                broadcast_date = broadcast_date.replace("Z", "+00:00")
                            
                            episode_date = datetime.datetime.fromisoformat(broadcast_date) 
                            
                            # If it's a naive datetime, assume UTC
                            if episode_date.tzinfo is None:
                                episode_date = episode_date.replace(tzinfo=datetime.timezone.utc)
                            
                            # Only include episodes in the requested time range
                            if episode_date >= start_date and episode_date <= end_date:
                                print(f"Found episode in time range: {episode_title or show_name}")
                                
                                # Try to get detailed episode data with tracklist
                                try:
                                    episode_data = get_tracklist_from_episode_page(show_alias, episode_alias)
                                    episode_info = parse_tracklist(episode_data)
                                    
                                    # Add show/episode information if missing
                                    if not episode_info.get('show_name') and show_name:
                                        episode_info['show_name'] = show_name
                                    if not episode_info.get('episode_title') and episode_title:
                                        episode_info['episode_title'] = episode_title
                                    
                                    episode_info['show_alias'] = show_alias
                                    episode_info['location'] = location
                                    
                                    # Add to our collection
                                    recent_episodes.append(episode_info)
                                except Exception as e:
                                    print(f"Error fetching tracklist for {show_alias}/{episode_alias}: {e}")
                                    
                                    # Still add a minimal episode record
                                    recent_episodes.append({
                                        "show_name": show_name or show_alias,
                                        "episode_title": episode_title or show_name or episode_alias,
                                        "broadcast_date": broadcast_date,
                                        "show_alias": show_alias,
                                        "location": location,
                                        "tracks": []
                                    })
                    except Exception as e:
                        print(f"Error parsing URL or date: {e}")
                        continue
                except Exception as e:
                    print(f"Error processing episode container: {e}")
                    continue
        except Exception as e:
            print(f"Failed to scrape latest page: {e}")
            print("Falling back to API methods...")
    except Exception as e:
        print(f"Error using Playwright to scrape the latest page: {e}")
        print("Falling back to API methods...")
    
    # 2. Also try the live endpoint to get current and upcoming shows (might not be in latest yet)
    try:
        url = "https://www.nts.live/api/v2/live"
        print(f"Requesting live data from: {url}")
        
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        live_data = response.json()
        
        # The live endpoint has data in a different format
        # Extract channel information and episodes
        for channel in live_data.get("results", []):
            channel_name = channel.get("channel_name", "")
            
            # Check for scheduled shows
            upcoming_shows = []
            if "now" in channel:
                upcoming_shows.append(channel["now"])
            if "next" in channel:
                upcoming_shows.append(channel["next"])
            if "upcoming" in channel:
                upcoming_shows.extend(channel.get("upcoming", []))
                
            for show in upcoming_shows:
                # Extract broadcast date
                broadcast_date = show.get("start_timestamp", "")
                if not broadcast_date:
                    continue
                    
                # Convert to datetime for comparison
                try:
                    # Make sure we have a timezone-aware datetime for comparison
                    if broadcast_date.endswith('Z'):
                        # UTC time with Z suffix
                        broadcast_date = broadcast_date.replace("Z", "+00:00")
                    
                    episode_date = datetime.datetime.fromisoformat(broadcast_date)
                    
                    # If it's a naive datetime, assume UTC
                    if episode_date.tzinfo is None:
                        episode_date = episode_date.replace(tzinfo=datetime.timezone.utc)
                    
                    # Only include episodes in the requested time range
                    if episode_date >= start_date and episode_date <= end_date:
                        # Get the show information from the embeds
                        show_name = show.get("broadcast_title", "")
                        show_details = None
                        
                        if "embeds" in show and "details" in show["embeds"]:
                            show_details = show["embeds"]["details"]
                        
                        # Create episode record with the basic information
                        combined_data = {
                            "show_name": show_name,
                            "episode_title": show_name,
                            "broadcast_date": broadcast_date,
                            "channel": channel_name,
                            "tracks": []  # Empty tracklist as we can't get this from /live
                        }
                        
                        # Add additional details if available
                        if show_details:
                            # Add location and other available metadata
                            if "location_long" in show_details:
                                combined_data["location"] = show_details.get("location_long", "")
                            if "genres" in show_details:
                                combined_data["genres"] = [g.get("value") for g in show_details.get("genres", [])]
                            if "description" in show_details:
                                combined_data["description"] = show_details.get("description", "")
                        
                        recent_episodes.append(combined_data)
                            
                except Exception as e:
                    print(f"Error parsing show data: {e}")
                    continue
    except Exception as e:
        print(f"Failed to fetch live data: {e}")
    
    # Report results
    print(f"Found {len(recent_episodes)} episodes in the past {days} days")
    
    # Remove duplicates by episode title and date if any
    unique_episodes = {}
    for episode in recent_episodes:
        key = (episode.get("episode_title", ""), episode.get("broadcast_date", ""))
        # Only replace if the new version has more tracks
        if key not in unique_episodes or len(episode.get("tracks", [])) > len(unique_episodes[key].get("tracks", [])):
            unique_episodes[key] = episode
    
    final_episodes = list(unique_episodes.values())
    if len(final_episodes) < len(recent_episodes):
        print(f"Removed {len(recent_episodes) - len(final_episodes)} duplicate episodes")
    
    return final_episodes


def analyze_weekly_tracks(episodes):
    """
    Analyze track plays across episodes and generate statistics.
    
    Args:
        episodes: List of episode data with tracklists
        
    Returns:
        Dictionary with top artists, tracks, and detailed play information
    """
    # Track counts
    track_plays = defaultdict(list)
    artist_plays = defaultdict(list)
    
    for episode in episodes:
        show_name = episode.get("show_name", "Unknown Show")
        broadcast_date = episode.get("broadcast_date", "")
        
        for track in episode.get("tracks", []):
            artist = track.get("artist", "")
            title = track.get("title", "")
            
            if artist and title:
                # Create unique track identifier
                track_id = f"{artist} - {title}"
                
                # Record play with show attribution
                play_info = {
                    "show_name": show_name,
                    "broadcast_date": broadcast_date
                }
                
                track_plays[track_id].append(play_info)
                artist_plays[artist].append({
                    "track": title,
                    "show_name": show_name,
                    "broadcast_date": broadcast_date
                })
    
    # Sort by number of plays
    top_tracks = sorted(track_plays.items(), key=lambda x: len(x[1]), reverse=True)
    top_artists = sorted(artist_plays.items(), key=lambda x: len(x[1]), reverse=True)
    
    return {
        "top_tracks": top_tracks,
        "top_artists": top_artists,
        "track_plays": dict(track_plays),
        "artist_plays": dict(artist_plays)
    }


def generate_weekly_report(days=7, output_csv="nts_weekly_report.csv"):
    """
    Generate a report of the past week's NTS plays.
    
    Args:
        days: Number of days to look back
        output_csv: Path to output CSV file
        
    Returns:
        Report statistics and writes CSV file
    """
    print(f"Generating NTS report for the past {days} days...")
    
    # Get episodes
    episodes = get_latest_episodes(days)
    
    if not episodes:
        print("No episodes found in the specified time period.")
        return None
    
    print(f"Found {len(episodes)} episodes in the past {days} days.")
    
    # Collect track data when available
    tracks_found = False
    all_tracks = []
    for episode in episodes:
        if "tracks" in episode and episode["tracks"]:
            tracks_found = True
            all_tracks.extend(episode["tracks"])
    
    # Write CSV report
    with open(output_csv, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        
        # Header
        start_date = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
        end_date = datetime.datetime.now().strftime("%Y-%m-%d")
        
        writer.writerow([f"NTS Weekly Report: {start_date} to {end_date}"])
        writer.writerow([f"Total Episodes: {len(episodes)}"])
        writer.writerow([])
        
        # Episode details section
        writer.writerow(["EPISODES"])
        writer.writerow(["Show", "Episode Title", "Broadcast Date", "Location", "Track Count"])
        
        for episode in episodes:
            track_count = len(episode.get("tracks", []))
            writer.writerow([
                episode.get("show_name", ""),
                episode.get("episode_title", ""),
                episode.get("broadcast_date", ""),
                episode.get("location", ""),
                track_count
            ])
        
        writer.writerow([])
        
        # If we have track data, add it to the report
        if tracks_found:
            # Analyze tracks if available
            if all_tracks:
                # Create a pseudo-episode with all tracks for analysis
                combined_episode = {"tracks": all_tracks}
                all_episodes = [combined_episode]
                analysis = analyze_weekly_tracks(all_episodes)
                
                # Top tracks section
                writer.writerow(["TOP TRACKS"])
                writer.writerow(["Rank", "Track", "Play Count"])
                
                for i, (track, plays) in enumerate(analysis["top_tracks"][:20], 1):
                    writer.writerow([i, track, len(plays)])
                
                writer.writerow([])
                
                # Top artists section
                writer.writerow(["TOP ARTISTS"])
                writer.writerow(["Rank", "Artist", "Play Count"])
                
                for i, (artist, plays) in enumerate(analysis["top_artists"][:20], 1):
                    writer.writerow([i, artist, len(plays)])
        else:
            writer.writerow(["NOTE: No track information was found for the episodes in this time period."])
    
    print(f"Report generated and saved to {output_csv}")
    return {"episodes": episodes}


if __name__ == "__main__":
    """
    Allow standalone testing of the NTS scraper.
    """
    if len(sys.argv) == 1:
        print("Usage: python -m tracktracker.scrapers.nts <nts_url>")
        print("   OR: python -m tracktracker.scrapers.nts report [days]")
        sys.exit(1)
    
    if sys.argv[1] == "report":
        # Generate weekly report
        days = 7
        if len(sys.argv) > 2:
            try:
                days = int(sys.argv[2])
            except ValueError:
                print(f"Invalid number of days: {sys.argv[2]}. Using default of 7 days.")
        
        generate_weekly_report(days)
    else:
        # Original functionality to scrape a specific URL
        try:
            result = scrape(sys.argv[1])
            
            if result.get("is_show", False):
                print(f"Show: {result['show_name']}")
                print(f"Found {result['episode_count']} episodes with tracklists")
                
                # Print a summary of episodes and track counts
                for idx, episode in enumerate(result["episodes_data"], 1):
                    print(f"{idx}. {episode['episode_title']} - {len(episode['tracks'])} tracks")
            else:
                print(f"Show: {result['show_name']}")
                print(f"Episode: {result['episode_title']}")
                print(f"Found {len(result['tracks'])} tracks:")
                
                for idx, track in enumerate(result['tracks'], 1):
                    print(f"{idx}. {track['artist']} - {track['title']}")
        
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)