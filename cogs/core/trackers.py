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
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import desc

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
        self.session_factory = session_factory
        self.buy_counts = {}  # Keep this in memory for now
        
        # Load tokens from database if session is provided
        if session_factory:
            self._load_tokens_from_db()
    
    def _load_tokens_from_db(self):
        """Load the most recent tokens from database into memory cache."""
        try:
            if not self.session_factory:
                logging.warning("Database session not available, skipping token load")
                return
                
            # Get the most recent tokens up to max_tokens
            with self.update_lock:
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
        """Log a token, maintaining only the most recent tokens but preserving first alert data.
        
        Args:
            contract: Token contract address
            data: Token data dictionary
            source: Source of the alert (e.g., 'cielo', 'rick')
            user: Username who triggered the alert
        """
        # Remove oldest tokens if max size reached in memory
        while len(self.tokens) >= self.max_tokens:
            self.tokens.popitem(last=False)
        
        current_time = datetime.now()
        
        # Update in-memory cache
        if contract in self.tokens:
            # Update timestamp but preserve original source, user, and initial market cap
            self.tokens[contract].update({
                **data,
                'timestamp': current_time,
                # Preserve these fields from the first alert
                'source': self.tokens[contract]['source'],
                'user': self.tokens[contract]['user'],
                'initial_market_cap': self.tokens[contract]['initial_market_cap'],
                'initial_market_cap_formatted': self.tokens[contract]['initial_market_cap_formatted'],
            })
        else:
            # This is the first alert for this token
            self.tokens[contract] = {
                **data,
                'timestamp': current_time,
                'source': source,
                'user': user
            }
        
        # Update database if session is available
        if self.session_factory:
            try:
                # Check if token exists in database
                db_token = self.session_factory.query(Token).filter_by(contract_address=contract).first()
                
                if db_token:
                    # Update existing token
                    db_token.name = data.get('name', db_token.name)
                    db_token.chart_url = data.get('chart_url', db_token.chart_url)
                    db_token.chain = data.get('chain', db_token.chain)
                    db_token.current_market_cap = data.get('market_cap_value', db_token.current_market_cap)
                    db_token.current_market_cap_formatted = data.get('market_cap', db_token.current_market_cap_formatted)
                    db_token.message_id = data.get('message_id', db_token.message_id)
                    db_token.channel_id = data.get('channel_id', db_token.channel_id)
                    db_token.guild_id = data.get('guild_id', db_token.guild_id)
                    db_token.last_updated = current_time
                    
                    # Create market cap update record if market cap was provided
                    if 'market_cap_value' in data or 'market_cap' in data:
                        market_update = MarketCapUpdate(
                            token_id=db_token.id,
                            market_cap=data.get('market_cap_value'),
                            market_cap_formatted=data.get('market_cap'),
                            timestamp=current_time
                        )
                        self.session_factory.add(market_update)
                    
                else:
                    # Create new token record
                    new_token = Token(
                        contract_address=contract,
                        name=data.get('name', 'Unknown'),
                        chain=data.get('chain'),
                        chart_url=data.get('chart_url'),
                        initial_market_cap=data.get('initial_market_cap'),
                        initial_market_cap_formatted=data.get('initial_market_cap_formatted'),
                        current_market_cap=data.get('market_cap_value'),
                        current_market_cap_formatted=data.get('market_cap'),
                        message_id=data.get('message_id'),
                        channel_id=data.get('channel_id'),
                        guild_id=data.get('guild_id'),
                        source=source,
                        credited_user=user,
                        first_seen=current_time,
                        last_updated=current_time
                    )
                    self.session_factory.add(new_token)
                    
                    # Flush to get the new token ID
                    self.session_factory.flush()
                    
                    # Create initial market cap record if provided
                    if 'market_cap_value' in data or 'market_cap' in data:
                        market_update = MarketCapUpdate(
                            token_id=new_token.id,
                            market_cap=data.get('market_cap_value'),
                            market_cap_formatted=data.get('market_cap'),
                            timestamp=current_time
                        )
                        self.session_factory.add(market_update)
                
                # Commit changes
                self.session_factory.commit()
                logging.info(f"Token {contract} saved to database")
                
            except SQLAlchemyError as e:
                logging.error(f"Database error when logging token {contract}: {e}")
                if self.session_factory:
                    self.session_factory.rollback()
            except Exception as e:
                logging.error(f"Unexpected error when logging token {contract}: {e}")
                if self.session_factory:
                    self.session_factory.rollback()

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