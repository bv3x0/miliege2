from datetime import datetime
import logging
from typing import Dict, Set, Any
from collections import OrderedDict  # For ordered token storage

class BotMonitor:
    def __init__(self):
        self.last_message_time = datetime.now()
        self.errors_since_restart = 0
        self.max_errors = 50
        self.start_time = datetime.now()

    def log_message_processed(self):
        self.last_message_time = datetime.now()

    def log_error(self, error):
        self.errors_since_restart += 1
        logging.error(f"Bot error: {error}")
        return self.errors_since_restart >= self.max_errors

    def get_uptime(self):
        return datetime.now() - self.start_time

    def reset_error_count(self):
        self.errors_since_restart = 0

class TokenTracker:
    def __init__(self, max_tokens: int = 1000, cache_timeout: int = 3600):
        self.tokens: OrderedDict = OrderedDict()
        self.buy_counts: Dict[str, Set[int]] = {}
        self.max_tokens = max_tokens
        self.cache_timeout = cache_timeout
        self.last_cleared = datetime.now()

    def clear_daily(self) -> None:
        """Clear daily tracking data and log the statistics."""
        logging.info(f"Daily clear - Tracked {len(self.tokens)} tokens with {len(self.buy_counts)} buy events")
        self.buy_counts.clear()
        self.tokens.clear()
        self.last_cleared = datetime.now()

    def log_token(self, contract: str, data: Dict[str, Any]) -> None:
        """Log a token with automatic cleanup of old entries."""
        # Clear old tokens if max size reached
        while len(self.tokens) >= self.max_tokens:
            self.tokens.popitem(last=False)  # Remove oldest item
            
        self.tokens[contract] = {
            **data,
            'timestamp': datetime.now()
        }

    def log_buy(self, token_name, buyer_id):
        if token_name not in self.buy_counts:
            self.buy_counts[token_name] = set()
            logging.info(f"New token detected: {token_name}")

        previous_count = len(self.buy_counts[token_name])
        self.buy_counts[token_name].add(buyer_id)
        new_count = len(self.buy_counts[token_name])

        logging.info(f"Token: {token_name}, Previous buyers: {previous_count}, New buyers: {new_count}, Buyer ID: {buyer_id}")
        return new_count