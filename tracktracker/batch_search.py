"""
Batch processing utilities for tracktracker.

This module provides functions for batch processing of API requests
to improve performance and reduce the number of API calls.
"""

import logging
import time
import concurrent.futures
from typing import List, Dict, Any, Callable, Tuple, Optional, Set, TypeVar

T = TypeVar('T')


def batch_process(
    items: List[Any],
    process_func: Callable[[Any], T],
    max_workers: int = 5,
    max_batch_size: int = 10,
    batch_delay: float = 0.5,
    description: str = "items",
    verbose: bool = False
) -> List[Tuple[Any, Optional[T]]]:
    """
    Process a list of items in parallel batches with a delay between batches.
    
    Args:
        items: List of items to process
        process_func: Function to apply to each item
        max_workers: Maximum number of parallel workers
        max_batch_size: Maximum number of items to process in a batch
        batch_delay: Delay in seconds between batches
        description: Description of the items for logging
        verbose: Whether to enable verbose logging
        
    Returns:
        List of tuples (item, result) where result is the processed result or None if processing failed
    """
    if not items:
        return []
    
    results = []
    total_items = len(items)
    
    # Calculate total batches
    total_batches = (total_items + max_batch_size - 1) // max_batch_size
    
    logging.info(f"Processing {total_items} {description} in {total_batches} batches with {max_workers} parallel workers")
    
    # Process items in batches
    for batch_idx in range(0, total_items, max_batch_size):
        batch = items[batch_idx:batch_idx + max_batch_size]
        batch_num = batch_idx // max_batch_size + 1
        
        if verbose or batch_num % 5 == 0 or batch_num == 1:
            logging.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} {description})")
        
        # Process batch in parallel
        batch_results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(process_func, item): item for item in batch}
            
            for future in concurrent.futures.as_completed(futures):
                item = futures[future]
                try:
                    result = future.result()
                    batch_results.append((item, result))
                    if verbose:
                        logging.debug(f"Successfully processed {description} item")
                except Exception as e:
                    batch_results.append((item, None))
                    logging.warning(f"Error processing {description} item: {e}")
        
        # Add batch results to overall results
        results.extend(batch_results)
        
        # Skip delay for last batch
        if batch_num < total_batches:
            if verbose:
                logging.debug(f"Delaying {batch_delay} seconds before next batch...")
            time.sleep(batch_delay)
    
    logging.info(f"Completed processing {total_items} {description}")
    return results


def validate_batch_results(results: List[Tuple[Any, Optional[T]]]) -> Tuple[List[Any], List[Any]]:
    """
    Validate batch processing results and separate successful and failed items.
    
    Args:
        results: List of tuples (item, result) from batch_process
        
    Returns:
        Tuple of (successful_items, failed_items)
    """
    successful = []
    failed = []
    
    for item, result in results:
        if result is not None:
            successful.append((item, result))
        else:
            failed.append(item)
    
    return successful, failed