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
from db.models import Token, MarketCapUpdate
from sqlalchemy.exc import SQLAlchemyError # type: ignore
from sqlalchemy import desc # type: ignore

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
    def __init__(self, session_factory=None, max_tokens: int = 50, max_age_hours: int = 24):
        self.tokens = OrderedDict()
        self.max_tokens = max_tokens
        self.max_age_hours = max_age_hours
        self.update_lock = asyncio.Lock()
        
        # Store both the session and factory
        self.session_factory = session_factory
        self.db_session = session_factory  # Add this line - store the session directly
        
        # Load tokens from database if session is provided
        if session_factory:
            self._load_tokens_from_db()
        
        # Add major tokens set
        self.major_tokens = {
            'ETH', 'WETH',  # Ethereum
            'SOL', 'WSOL',  # Solana
            'USDC',         # Major stablecoins
            'USDT',
            'DAI',
            'BNB', 'WBNB',  # Binance
            'S', 'wS',      # Sonic
            'MATIC',        # Polygon
            'AVAX',         # Avalanche
            'ARB'           # Arbitrum
        }
        
        # Add common variations
        self.major_tokens.update({f'W{t}' for t in self.major_tokens})  # Add wrapped versions
    
    def _load_tokens_from_db(self):
        """Load the most recent tokens from database into memory cache."""
        try:
            if not self.session_factory:
                logging.warning("Database session not available, skipping token load")
                return
                
            # Get the most recent tokens up to max_tokens
            # Remove the lock since this is synchronous code
            tokens = self.session_factory.query(Token).order_by(desc(Token.last_updated)).limit(self.max_tokens).all()
            
            # Reset the in-memory cache
            self.tokens = OrderedDict()
            
            # Populate cache from database records
            for token in tokens:
                self.tokens[token.contract_address] = {
                    'name': token.name,
                    'chart_url': token.chart_url,
                    'chain': token.chain,
                    'initial_market_cap': token.initial_market_cap,
                    'initial_market_cap_formatted': token.initial_market_cap_formatted,
                    'market_cap': token.current_market_cap_formatted,
                    'timestamp': token.last_updated,
                    'source': token.source,
                    'user': token.credited_user,
                    'message_id': token.message_id,
                    'channel_id': token.channel_id,
                    'guild_id': token.guild_id
                }
            
            logging.info(f"Loaded {len(self.tokens)} tokens from database")
        
        except Exception as e:
            logging.error(f"Error loading tokens from database: {e}")

    def log_token(self, contract: str, data: Dict[str, Any], source: str, user: str = None) -> None:
        """Log a token, maintaining only the most recent tokens but preserving first alert data."""
        try:
            current_time = datetime.now()
            
            # Remove oldest tokens if max size reached
            while len(self.tokens) >= self.max_tokens:
                self.tokens.popitem(last=False)
            
            # Update or create token data
            if contract in self.tokens:
                # Update timestamp but preserve original source, user, and initial market cap
                self.tokens[contract].update({
                    **data,
                    'timestamp': current_time,
                    'source': self.tokens[contract]['source'],
                    'user': self.tokens[contract]['user'],
                    'initial_market_cap': self.tokens[contract].get('initial_market_cap'),
                    'initial_market_cap_formatted': self.tokens[contract].get('initial_market_cap_formatted'),
                })
            else:
                # First alert for this token
                self.tokens[contract] = {
                    **data,
                    'timestamp': current_time,
                    'source': source,
                    'user': user
                }
            
            # Update database if session available
            if self.db_session:
                self._update_database(contract, self.tokens[contract])
            
        except Exception as e:
            logging.error(f"Error logging token {contract}: {e}", exc_info=True)

    def _update_database(self, contract: str, token_data: Dict[str, Any]):
        """Update token information in database"""
        try:
            db_token = self.db_session.query(Token).filter_by(contract_address=contract).first()
            
            if db_token:
                # Update existing token while preserving initial values
                for key, value in token_data.items():
                    if key not in ['initial_market_cap', 'initial_market_cap_formatted'] or not getattr(db_token, key):
                        if hasattr(db_token, key):
                            setattr(db_token, key, value)
            else:
                # Create new token record
                new_token = Token(
                    contract_address=contract,
                    **{k: v for k, v in token_data.items() if hasattr(Token, k)}
                )
                self.db_session.add(new_token)
            
            self.db_session.commit()
            
        except Exception as e:
            logging.error(f"Database error updating token {contract}: {e}")
            if self.db_session:
                self.db_session.rollback()

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
                            
                            # Update database if session available
                            if self.session_factory:
                                try:
                                    db_token = self.session_factory.query(Token).filter_by(contract_address=contract).first()
                                    if db_token:
                                        db_token.current_market_cap = market_cap_value
                                        db_token.current_market_cap_formatted = market_cap_formatted
                                        db_token.last_updated = now
                                        
                                        # Create market cap update record
                                        market_update = MarketCapUpdate(
                                            token_id=db_token.id,
                                            market_cap=market_cap_value,
                                            market_cap_formatted=market_cap_formatted,
                                            timestamp=now
                                        )
                                        self.session_factory.add(market_update)
                                        self.session_factory.commit()
                                except SQLAlchemyError as e:
                                    logging.error(f"Database error updating market cap for {contract}: {e}")
                                    if self.session_factory:
                                        self.session_factory.rollback()
                            
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