from datetime import datetime
import logging
from typing import Dict, Set, Any
from collections import OrderedDict  # For ordered token storage
import asyncio

class BotMonitor:
    def __init__(self):
        self.last_message_time = datetime.now()
        self.errors_since_restart = 0
        self.max_errors = 50
        self.start_time = datetime.now()
        self.messages_processed = 0

    def record_message(self):
        """Record when a message is processed"""
        self.last_message_time = datetime.now()
        self.messages_processed += 1

    def record_error(self):
        """Record an error occurrence"""
        self.errors_since_restart += 1
        logging.error("Bot error occurred")
        return self.errors_since_restart >= self.max_errors

    def get_uptime(self):
        return datetime.now() - self.start_time

    def reset_error_count(self):
        self.errors_since_restart = 0

class TokenTracker:
    def __init__(self, max_tokens: int = 50):
        self.tokens = OrderedDict()
        self.max_tokens = max_tokens
        self.update_lock = asyncio.Lock()
        self.last_update_time = {}

    def log_token(self, contract: str, data: Dict[str, Any]) -> None:
        """Log a token, maintaining only the most recent tokens."""
        # Remove oldest tokens if max size reached
        while len(self.tokens) >= self.max_tokens:
            self.tokens.popitem(last=False)
            
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

    async def update_market_caps(self, session, max_tokens: int = 20, rate_limit: float = 0.5):
        """
        Update market caps for tracked tokens with rate limiting.
        
        Args:
            session: aiohttp ClientSession to use for requests
            max_tokens: Maximum number of tokens to update
            rate_limit: Seconds to wait between API calls
        """
        async with self.update_lock:  # Prevent concurrent updates
            now = datetime.now()
            update_count = 0
            
            for contract, token_data in list(self.tokens.items()):
                # Skip if we've hit our max token update limit
                if update_count >= max_tokens:
                    break
                    
                # Skip if token was updated recently (within last 5 minutes)
                last_update = self.last_update_time.get(contract)
                if last_update and (now - last_update).seconds < 300:
                    continue
                    
                # Add rate limiting delay
                if update_count > 0:  # Don't delay first request
                    await asyncio.sleep(rate_limit)
                
                try:
                    dex_api_url = f"https://api.dexscreener.com/latest/dex/tokens/{contract}"
                    async with safe_api_call(session, dex_api_url) as dex_data:
                        if dex_data and dex_data.get('pairs'):
                            pair = dex_data['pairs'][0]
                            if 'fdv' in pair:
                                token_data['market_cap'] = format_large_number(float(pair['fdv']))
                                self.last_update_time[contract] = now
                                update_count += 1
                                logging.info(f"Updated market cap for {token_data['name']}")
                                
                except Exception as e:
                    logging.error(f"Error updating market cap for {contract}: {e}")
                    continue
            
            return update_count