#!/usr/bin/env python3
"""
Script to process large NTS show archives in small chunks with long pauses between.
This is designed to work around Spotify rate limits by being extremely conservative.
"""

import os
import sys
import time
import argparse
import logging
import subprocess
from datetime import datetime
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

def timestamp():
    """Get current timestamp for logging"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def run_chunk(url, chunk_size, start_episode, wait_time, verbose=False):
    """Run one chunk of episodes"""
    logging.info(f"[{timestamp()}] Processing chunk starting at episode {start_episode}")
    
    # Build the command
    cmd = [
        sys.executable,
        "-m", "tracktracker.cli",
        "playlist", url,
        "--archive",
        "--chunk-size", str(chunk_size),
        "--start-episode", str(start_episode)
    ]
    
    if verbose:
        cmd.append("--verbose")
    
    # Run the command and capture output
    logging.info(f"[{timestamp()}] Running command: {' '.join(cmd)}")
    
    try:
        # Run in a separate process
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        
        # Monitor output in real-time
        rate_limit_detected = False
        for line in process.stdout:
            line = line.strip()
            print(line)
            
            # Check for rate limit messages
            if "rate/request limit" in line.lower():
                rate_limit_detected = True
                logging.warning(f"[{timestamp()}] Rate limit detected")
        
        # Wait for process to complete
        process.wait()
        
        # Check if successful
        if process.returncode == 0 and not rate_limit_detected:
            logging.info(f"[{timestamp()}] Chunk completed successfully")
            return True
        else:
            logging.warning(f"[{timestamp()}] Chunk processing failed or rate limited")
            return False
    except Exception as e:
        logging.error(f"[{timestamp()}] Error running chunk: {e}")
        return False

def process_show_in_chunks(url, chunk_size=3, wait_time=900, max_episodes=None, verbose=False):
    """Process a show archive in small chunks with long waits between"""
    logging.info(f"[{timestamp()}] Starting to process show: {url}")
    logging.info(f"[{timestamp()}] Processing in chunks of {chunk_size} episodes with {wait_time} seconds wait between chunks")
    
    # First, run a small test to get total episodes
    logging.info(f"[{timestamp()}] Running small test to get episode count")
    cmd = [
        sys.executable,
        "-m", "tracktracker.cli",
        "playlist", url,
        "--archive",
        "--small-test"
    ]
    
    try:
        # Start the process
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        
        # Parse output to get episode count
        total_episodes = None
        rate_limit_detected = False
        for line in process.stdout:
            line = line.strip()
            print(line)
            
            # Check for episode count
            if "Found " in line and " episodes with tracklists" in line:
                try:
                    total_episodes = int(line.split("Found ")[1].split(" episodes")[0])
                    logging.info(f"[{timestamp()}] Detected {total_episodes} total episodes")
                except:
                    pass
                    
            # Check for rate limit messages
            if "rate/request limit" in line.lower():
                rate_limit_detected = True
                logging.warning(f"[{timestamp()}] Rate limit detected during initial test")
        
        # Wait for process to complete
        process.wait()
        
        # If rate limited, need to wait before continuing
        if rate_limit_detected:
            retry_wait = 1800  # 30 minutes
            logging.warning(f"[{timestamp()}] Rate limited during initial test. Waiting {retry_wait} seconds before continuing...")
            time.sleep(retry_wait)
            
    except Exception as e:
        logging.error(f"[{timestamp()}] Error during initial test: {e}")
        return False
    
    # If we couldn't detect total episodes, use a default large number
    if not total_episodes:
        total_episodes = 100
        logging.warning(f"[{timestamp()}] Could not detect episode count, assuming {total_episodes}")
    
    # Limit maximum episodes if specified
    if max_episodes is not None and max_episodes < total_episodes:
        total_episodes = max_episodes
        logging.info(f"[{timestamp()}] Limiting to {total_episodes} episodes as requested")
    
    # Process in chunks
    start_episode = 0
    while start_episode < total_episodes:
        # Run this chunk
        success = run_chunk(url, chunk_size, start_episode, wait_time, verbose)
        
        # Move to next chunk
        if success:
            start_episode += chunk_size
            logging.info(f"[{timestamp()}] Moving to next chunk starting at episode {start_episode}")
            
            # Wait between chunks
            if start_episode < total_episodes:
                logging.info(f"[{timestamp()}] Waiting {wait_time} seconds before next chunk...")
                time.sleep(wait_time)
        else:
            # If failed, wait longer and try again with the same chunk
            extended_wait = wait_time * 2
            logging.warning(f"[{timestamp()}] Processing failed, waiting {extended_wait} seconds before retrying...")
            time.sleep(extended_wait)
    
    logging.info(f"[{timestamp()}] Processing complete for {url}")
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process NTS show archives in small chunks with pauses")
    parser.add_argument("url", help="URL of the NTS show to process")
    parser.add_argument("--chunk-size", type=int, default=3, help="Number of episodes to process in each chunk")
    parser.add_argument("--wait-time", type=int, default=900, help="Wait time in seconds between chunks")
    parser.add_argument("--max-episodes", type=int, help="Maximum number of episodes to process")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output")
    args = parser.parse_args()
    
    # Process the show
    process_show_in_chunks(
        args.url, 
        chunk_size=args.chunk_size, 
        wait_time=args.wait_time,
        max_episodes=args.max_episodes,
        verbose=args.verbose
    )