#!/usr/bin/env python3
"""
Export shows data for the static GitHub Pages website.

This script:
1. Reads the shows.json file from the tracktracker website directory
2. Formats it properly for the static site
3. Writes it to a shows.js file that can be directly used in the GitHub Pages site
"""

import os
import json
import argparse
import logging
from pathlib import Path
import shutil


def get_shows_data_path():
    """
    Get the path to the shows data file.
    
    Returns:
        Path to the shows.json file
    """
    try:
        # Get the path from settings
        from tracktracker.config import settings
        return str(settings.paths.shows_data_path)
    except ImportError:
        # Fallback to legacy path if config is not available
        project_root = "/Users/duncancooper/Documents/tracktracker"
        return os.path.join(project_root, "website", "src", "data", "shows.json")


def load_shows_data():
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
            logging.error(f"Failed to load shows data: {e}")
            return []
    else:
        logging.error(f"Shows data file doesn't exist at {shows_file}")
        return []


def export_for_web(output_path, copy_images=False, images_dir=None):
    """
    Export shows data for the static website.
    
    Args:
        output_path: Path to write the shows.js file
        copy_images: Whether to copy show images to the output directory
        images_dir: Directory to copy images to (defaults to output_dir/show-images)
    """
    shows = load_shows_data()
    
    if not shows:
        logging.error("No shows data found.")
        return False
    
    # Format for web
    js_content = f"window.shows = {json.dumps(shows, indent=2)};"
    
    # Create output directory if it doesn't exist
    output_dir = os.path.dirname(output_path)
    os.makedirs(output_dir, exist_ok=True)
    
    # Write the shows.js file
    with open(output_path, "w") as f:
        f.write(js_content)
    
    logging.info(f"Exported shows data to {output_path}")
    
    # Copy images if requested
    if copy_images:
        # Set default images directory if not provided
        if not images_dir:
            images_dir = os.path.join(output_dir, "show-images")
        
        os.makedirs(images_dir, exist_ok=True)
        
        # Check where show images are stored
        try:
            from tracktracker.config import settings
            show_images_src = settings.paths.show_images_dir
        except ImportError:
            # Fallback to legacy path
            project_root = "/Users/duncancooper/Documents/tracktracker"
            show_images_src = os.path.join(project_root, "website", "public", "show-images")
        
        if os.path.exists(show_images_src):
            # Copy all images
            image_files = [f for f in os.listdir(show_images_src) 
                         if f.lower().endswith(('.jpg', '.jpeg', '.png', '.gif'))]
            
            for image in image_files:
                src_path = os.path.join(show_images_src, image)
                dst_path = os.path.join(images_dir, image)
                shutil.copy2(src_path, dst_path)
                logging.info(f"Copied image: {image}")
            
            logging.info(f"Copied {len(image_files)} images to {images_dir}")
        else:
            logging.warning(f"Show images directory not found at {show_images_src}")
    
    return True


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Export shows data for the static GitHub Pages website."
    )
    
    parser.add_argument(
        "-o", "--output",
        default="shows.js",
        help="Path to write the shows.js file (default: shows.js in current directory)"
    )
    
    parser.add_argument(
        "--copy-images",
        action="store_true",
        help="Copy show images to the output directory"
    )
    
    parser.add_argument(
        "--images-dir",
        help="Directory to copy images to (defaults to output_dir/show-images)"
    )
    
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output"
    )
    
    args = parser.parse_args()
    
    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format="%(levelname)s: %(message)s")
    
    try:
        export_for_web(args.output, args.copy_images, args.images_dir)
    except Exception as e:
        logging.error(f"Error exporting shows data: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    main()