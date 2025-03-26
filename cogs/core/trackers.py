from datetime import datetime
import logging
from typing import Dict, Set, Any
from collections import OrderedDict  # For ordered token storage
import asyncio

from cogs.utils import (
    format_large_number,
    safe_api_call,
    DexScreenerAPI,
    UI,
    Colors
)

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
    def __init__(self, max_tokens: int = 50, max_age_hours: int = 24):
        self.tokens = OrderedDict()
        self.max_tokens = max_tokens
        self.max_age_hours = max_age_hours
        self.update_lock = asyncio.Lock()
        
        # Add major tokens set
        self.major_tokens = {
            'ETH', 'WETH',  # Ethereum
            'SOL', 'WSOL',  # Solana
            'USDC',         # Major stablecoins
            'USDT',
            'DAI',
            'BNB', 'WBNB',  # Binance
            'S', 'wS', 'x33', 'USDC.e', # Sonic
            'MATIC',        # Polygon
            'AVAX',         # Avalanche
            'ARB'           # Arbitrum
        }
        self.major_tokens.update({f'W{t}' for t in self.major_tokens})

    def log_token(self, contract: str, data: Dict[str, Any], source: str, user: str = None) -> None:
        """Log a token, maintaining only the most recent tokens."""
        try:
            current_time = datetime.now()
            
            # Extract social links if present
            social_info = {}
            if 'info' in data:
                info = data['info']
                # Store websites
                if 'websites' in info and isinstance(info['websites'], list):
                    social_info['websites'] = [
                        website['url'] for website in info['websites'] 
                        if isinstance(website, dict) and 'url' in website
                    ]
                
                # Store social links
                if 'socials' in info and isinstance(info['socials'], list):
                    social_info['socials'] = [
                        {
                            'platform': social['platform'],
                            'url': social['url']
                        }
                        for social in info['socials']
                        if isinstance(social, dict) and 'platform' in social and 'url' in social
                    ]
            
            # Remove oldest tokens if max size reached
            while len(self.tokens) >= self.max_tokens:
                self.tokens.popitem(last=False)
            
            # Update or create token data
            if contract in self.tokens:
                # Update timestamp but preserve original source and user
                self.tokens[contract].update({
                    **data,
                    'timestamp': current_time,
                    'source': self.tokens[contract]['source'],
                    'user': self.tokens[contract]['user'],
                    'initial_market_cap': self.tokens[contract].get('initial_market_cap'),
                    'initial_market_cap_formatted': self.tokens[contract].get('initial_market_cap_formatted'),
                    'social_info': social_info if social_info else self.tokens[contract].get('social_info', {})
                })
            else:
                # First alert for this token
                self.tokens[contract] = {
                    **data,
                    'timestamp': current_time,
                    'source': source,
                    'user': user,
                    'social_info': social_info
                }
            
        except Exception as e:
            logging.error(f"Error logging token {contract}: {e}", exc_info=True)

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
                last_update = self.tokens.get(contract, {}).get('timestamp')
                if last_update and (now - last_update).seconds < 300:
                    continue
                    
                # Add rate limiting delay
                if update_count > 0:  # Don't delay first request
                    await asyncio.sleep(rate_limit)
                
                try:
                    dex_data = await DexScreenerAPI.get_token_info(session, contract)
                    if dex_data and dex_data.get('pairs'):
                        pair = dex_data['pairs'][0]
                        if 'fdv' in pair:
                            market_cap_value = float(pair['fdv'])
                            market_cap_formatted = format_large_number(market_cap_value)
                            
                            # Update in-memory cache
                            token_data['market_cap'] = market_cap_formatted
                            token_data['market_cap_value'] = market_cap_value
                            self.tokens[contract]['timestamp'] = now
                            
                            update_count += 1
                            logging.info(f"Updated market cap for {token_data['name']}")
                            
                except Exception as e:
                    logging.error(f"Error updating market cap for {contract}: {e}")
                    continue
            
            return update_count

    async def cleanup_old_tokens(self):
        """Remove tokens older than max_age_hours"""
        now = datetime.now()
        with self.update_lock:
            to_remove = []
            for contract, data in self.tokens.items():
                if 'timestamp' in data:
                    age = now - data['timestamp']
                    if age.total_seconds() > self.max_age_hours * 3600:
                        to_remove.append(contract)
            
            for contract in to_remove:
                del self.tokens[contract]

    def is_major_token(self, token: str) -> bool:
        """Check if a token is considered a major token"""
        return token.upper() in self.major_tokens

    def add_token(self, contract_address: str, name: str, initial_mcap: str, source: str, user: str = None, message_link: str = None):
        """Add or update a token in the tracker"""
        current_time = datetime.now()
        
        # If token exists and new alert is from Cielo, always update the source
        if contract_address in self.tokens and source.lower() == 'cielo':
            self.tokens[contract_address].update({
                'source': 'cielo',
                'user': user,
                'message_link': message_link
            })
            logging.info(f"Updated existing token {name} source to cielo")
            return

        # For other cases, only add if token doesn't exist
        if contract_address not in self.tokens:
            self.tokens[contract_address] = {
                'name': name,
                'initial_mcap': initial_mcap,
                'timestamp': current_time,
                'source': source,
                'user': user,
                'message_link': message_link
            }
            logging.info(f"Added new token {name} from {source}")