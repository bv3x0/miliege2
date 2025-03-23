import discord
from discord.ext import commands, tasks
import logging
from collections import deque, OrderedDict
import aiohttp
from cogs.utils import safe_api_call, format_large_number, Colors # type: ignore
from datetime import datetime, timedelta
import pytz
import asyncio
from sqlalchemy.exc import SQLAlchemyError # type: ignore
from sqlalchemy import desc # type: ignore
from db.models import Token
import re
from cogs.utils.format import format_token_header, Colors  # Fix import path
from cogs.utils import (
    DexScreenerAPI,
    UI
)
import json

class DigestCog(commands.Cog):
    def __init__(self, bot, token_tracker, channel_id, monitor=None):
        self.bot = bot
        self.token_tracker = token_tracker
        self.channel_id = channel_id
        self.ny_tz = pytz.timezone('America/New_York')
        # Store tokens by hour for better separation
        self.hour_tokens = OrderedDict()
        self.current_hour_key = self._get_current_hour_key()
        
        # Load tokens from database if token_tracker has a db_session
        self.db_session = None
        if hasattr(token_tracker, 'db_session') and token_tracker.db_session:
            self.db_session = token_tracker.db_session
            self._load_tokens_from_db()
        else:
            logging.warning("DigestCog: No database session available - token data will not persist across reboots")
        
        # Start the hourly task
        self.hourly_digest.start()
        
        # Flag to track if the hook is installed
        self.hook_installed = False
        
        # Use the monitor if provided, otherwise track errors locally
        self.monitor = monitor if monitor else None
        self.error_count = 0
        
        # Add trade tracking from TradeSummaryCog
        self.hourly_trades = {}  # Format: {token_address: {'buys': float, 'sells': float, 'users': {user: {'message_link': str, 'actions': set()}}}}
        
        # Define major tokens (copied from TradeSummaryCog)
        self.major_tokens = {
            'ETH', 'WETH',  # Ethereum
            'SOL', 'WSOL',  # Solana
            'USDC',         # Major stablecoins
            'USDT',
            'DAI',
            'BNB', 'WBNB',  # Binance
            'S',            # Base
            'MATIC',        # Polygon
            'AVAX',         # Avalanche
            'ARB'           # Arbitrum
        }
        self.major_tokens.update({f'W{t}' for t in self.major_tokens})

    def _load_tokens_from_db(self):
        """Load tokens from the database into the hour buckets"""
        try:
            if not self.db_session:
                logging.warning("Cannot load digest tokens: No database session")
                return
                
            # Get the current time and 24 hours ago
            now = datetime.now()
            one_day_ago = now - timedelta(hours=24)
            
            # Query tokens from the last 24 hours (covers all digestible tokens)
            recent_tokens = self.db_session.query(Token).filter(
                Token.first_seen >= one_day_ago
            ).order_by(Token.first_seen).all()
            
            token_count = 0
            
            # Group tokens by hour and add to the appropriate hour bucket
            for token in recent_tokens:
                # Get the hour key for when this token was first seen
                token_time = token.first_seen
                if token_time:
                    token_time_ny = token_time.astimezone(self.ny_tz)
                    hour_key = token_time_ny.strftime("%Y-%m-%d-%H")
                    
                    # Initialize the hour bucket if needed
                    if hour_key not in self.hour_tokens:
                        self.hour_tokens[hour_key] = OrderedDict()
                    
                    # Convert the token to the format used by digest
                    token_data = {
                        'name': token.name,
                        'chart_url': token.chart_url,
                        'initial_market_cap': token.initial_market_cap,
                        'initial_market_cap_formatted': token.initial_market_cap_formatted,
                        'chain': token.chain,
                        'source': token.source,
                        'user': token.credited_user,
                        'message_id': token.message_id,
                        'channel_id': token.channel_id,
                        'guild_id': token.guild_id
                    }
                    
                    # Add to the appropriate hour bucket
                    self.hour_tokens[hour_key][token.contract_address] = token_data
                    token_count += 1
            
            # Log success message with count
            logging.info(f"DigestCog: Loaded {token_count} tokens from database into {len(self.hour_tokens)} hour buckets")
            
            # Ensure current hour is initialized
            if self.current_hour_key not in self.hour_tokens:
                self.hour_tokens[self.current_hour_key] = OrderedDict()
                
        except Exception as e:
            logging.error(f"DigestCog: Error loading tokens from database: {e}", exc_info=True)

    def cog_unload(self):
        self.hourly_digest.cancel()  # Clean up task when cog is unloaded
        
    def _get_current_hour_key(self):
        """Get a string key for the current hour"""
        ny_time = datetime.now(self.ny_tz)
        return ny_time.strftime("%Y-%m-%d-%H")
        
    def _update_token_hour(self):
        """Update the current hour key if needed"""
        current_key = self._get_current_hour_key()
        if current_key != self.current_hour_key:
            self.current_hour_key = current_key
            # Initialize new hour
            if current_key not in self.hour_tokens:
                self.hour_tokens[current_key] = OrderedDict()
        return current_key

    async def create_digest_embed(self, tokens, is_hourly=True):
        """Create the digest embed(s) - shared between auto and manual digests"""
        if not tokens:
            return None

        recent_tokens = list(tokens.items())[-10:]  # Last 10 tokens
        
        # Add debug logging
        logging.info(f"Creating digest embed with {len(tokens)} total tokens, showing last {len(recent_tokens)}")
        
        for contract, token in recent_tokens:
            logging.info(f"Processing token: {token.get('name')} ({contract})")
            if contract in self.hourly_trades:
                trade_data = self.hourly_trades[contract]
                logging.info(f"Found trade data: {trade_data}")
                logging.info(f"Total buys: ${trade_data.get('buys', 0)}")
                logging.info(f"Total sells: ${trade_data.get('sells', 0)}")
                logging.info(f"Users: {list(trade_data.get('users', {}).keys())}")
            else:
                logging.info(f"No trade data found for token {contract}")

        embeds = []
        current_description_lines = []
        
        async with aiohttp.ClientSession() as session:
            for contract, token in recent_tokens:
                name = token['name']
                chain = token.get('chain', 'Unknown')
                initial_mcap = token.get('initial_market_cap_formatted', 'N/A')
                source = token.get('source', 'unknown')
                user = token.get('user', 'unknown')
                
                # Create Discord message link if we have the necessary info
                message_link = None
                original_message_link = None

                # Check for original message link first (Cielo message)
                if token.get('original_message_id') and token.get('original_channel_id') and token.get('original_guild_id'):
                    original_message_link = f"https://discord.com/channels/{token['original_guild_id']}/{token['original_channel_id']}/{token['original_message_id']}"

                # Fall back to grabber message link if original not available
                if not original_message_link and token.get('message_id') and token.get('channel_id') and token.get('guild_id'):
                    message_link = f"https://discord.com/channels/{token['guild_id']}/{token['channel_id']}/{token['message_id']}"

                # Fetch current market cap
                dex_data = await DexScreenerAPI.get_token_info(session, contract)
                current_mcap = 'N/A'
                if dex_data and dex_data.get('pairs'):
                    pair = dex_data['pairs'][0]
                    if 'fdv' in pair:
                        current_mcap = f"${format_large_number(float(pair['fdv']))}"

                # Format token information
                # Compare market caps and add emoji based on 40% threshold
                try:
                    # Fix the string to number conversion
                    def parse_market_cap(mcap_str):
                        if not mcap_str or mcap_str == 'N/A':
                            return None
                            
                        # Remove $ symbol
                        clean_str = mcap_str.replace('$', '')
                        
                        # Remove Discord emoji patterns (like <:wow:1149703956746997871>)
                        clean_str = re.sub(r'<:[a-zA-Z0-9_]+:[0-9]+>', '', clean_str)
                        
                        # Strip any extra whitespace that might be left after removing emojis
                        clean_str = clean_str.strip()
                        
                        # Handle suffixes properly (both uppercase and lowercase)
                        if 'M' in clean_str or 'm' in clean_str:
                            clean_str = clean_str.replace('M', '').replace('m', '')
                            return float(clean_str) * 1000000
                        elif 'K' in clean_str or 'k' in clean_str:
                            clean_str = clean_str.replace('K', '').replace('k', '')
                            return float(clean_str) * 1000
                        elif 'B' in clean_str or 'b' in clean_str:
                            clean_str = clean_str.replace('B', '').replace('b', '')
                            return float(clean_str) * 1000000000
                        else:
                            return float(clean_str)
                    
                    current_mcap_value = parse_market_cap(current_mcap)
                    initial_mcap_value = parse_market_cap(initial_mcap)
                    
                    # Calculate percentage change only if both values are valid numbers
                    status_emoji = ""
                    if current_mcap_value is not None and initial_mcap_value is not None and initial_mcap_value > 0:
                        # Calculate percentage change
                        percent_change = ((current_mcap_value - initial_mcap_value) / initial_mcap_value) * 100
                        
                        # Debug log the calculation
                        logging.info(f"Token {name} mcap change: {percent_change}% (from {initial_mcap_value} to {current_mcap_value})")
                        
                        # Changed threshold to 40% and updated emojis
                        if percent_change >= 40:
                            status_emoji = " :up:"  # Discord "UP" emoji for 40%+ up
                        elif percent_change <= -40:
                            status_emoji = " 🪦"  # gravestone for 40%+ down
                except Exception as e:
                    logging.error(f"Error calculating percent change for {name}: {e}")
                    status_emoji = ""  # If there's any error in conversion, don't show any emoji
                
                # Make sure we have valid values for display
                if not source or source == "":
                    source = "unknown"
                if not user or user == "":
                    user = "unknown"
                if not chain or chain == "":
                    chain = "unknown"
                
                # Log the values for debugging
                logging.info(f"Digest display for {name}: chain={chain}, source={source}, user={user}")
                
                # Check if we have trade data for this token
                trade_info = ""
                if contract in self.hourly_trades:
                    trade_data = self.hourly_trades[contract]
                    
                    # Group users by their actions
                    action_groups = {
                        'bought': [],
                        'sold': [],
                        'bought and sold': []
                    }
                    
                    for user, user_data in trade_data['users'].items():
                        actions = user_data['actions']
                        link = user_data['message_link']
                        user_link = f"[{user}]({link})"
                        
                        if 'bought' in actions and 'sold' in actions:
                            action_groups['bought and sold'].append((user_link, user_data.get('is_first_trade', False)))
                        elif 'bought' in actions:
                            action_groups['bought'].append((user_link, user_data.get('is_first_trade', False)))
                        elif 'sold' in actions:
                            action_groups['sold'].append((user_link, user_data.get('is_first_trade', False)))
                    
                    # Build the trade description
                    trade_parts = []
                    
                    if action_groups['bought']:
                        users = []
                        is_first = False
                        for user_link, first_trade in action_groups['bought']:
                            users.append(user_link)
                            is_first = is_first or first_trade
                        amount = float(trade_data['buys'])
                        formatted_amount = format_large_number(amount) if amount >= 1000 else str(int(amount))
                        star = " ⭐" if is_first else ""
                        trade_parts.append(f"{', '.join(users)} bought ${formatted_amount}{star}")
                    
                    if action_groups['sold']:
                        users = []
                        for user_link, _ in action_groups['sold']:  # No star for sells
                            users.append(user_link)
                        amount = float(trade_data['sells'])
                        formatted_amount = format_large_number(amount) if amount >= 1000 else str(int(amount))
                        trade_parts.append(f"{', '.join(users)} sold ${formatted_amount}")
                    
                    if action_groups['bought and sold']:
                        users = []
                        is_first = False
                        for user_link, first_trade in action_groups['bought and sold']:
                            users.append(user_link)
                            is_first = is_first or first_trade
                        buy_amount = float(trade_data['buys'])
                        sell_amount = float(trade_data['sells'])
                        formatted_buy = format_large_number(buy_amount) if buy_amount >= 1000 else str(int(buy_amount))
                        formatted_sell = format_large_number(sell_amount) if sell_amount >= 1000 else str(int(sell_amount))
                        star = " ⭐" if is_first else ""
                        trade_parts.append(f"{', '.join(users)} bought ${formatted_buy} and sold ${formatted_sell}{star}")
                    
                    if trade_parts:
                        trade_info = '\n'.join(trade_parts)
                
                # Format the description lines
                token_line = f"### [{name}]({token['chart_url']})"
                
                # Add status emoji and X in correct order
                if status_emoji:
                    token_line += status_emoji
                
                # Add red X if the token only has sells
                if contract in self.hourly_trades:
                    trade_data = self.hourly_trades[contract]
                    has_buys = trade_data.get('buys', 0) > 0
                    has_sells = trade_data.get('sells', 0) > 0
                    if has_sells and not has_buys:
                        token_line += " ❌"
                
                # Remove any existing $ from initial_mcap if it exists
                initial_mcap_clean = initial_mcap.replace('$', '') if initial_mcap else 'N/A'
                stats_line = f"{current_mcap} mc (was ${initial_mcap_clean}) ⋅ {chain.lower()}"
                
                # Calculate the length of new lines to be added
                new_lines = [token_line, stats_line]
                if trade_info and source.lower() == 'cielo':
                    new_lines.append(trade_info)
                else:
                    source_line = f"{source} via [{user}]({original_message_link or message_link})" if (original_message_link or message_link) else f"{source} via {user}"
                    new_lines.append(source_line)
                
                # Check if adding these lines would exceed Discord's limit
                potential_description = "\n".join(current_description_lines + new_lines)
                if len(potential_description) > 4000 and current_description_lines:  # Leave some buffer
                    # Create new embed with current lines
                    embed = discord.Embed(color=Colors.EMBED_BORDER)
                    embed.set_author(name="Latest Alerts")
                    embed.description = "\n".join(current_description_lines)
                    embeds.append(embed)
                    
                    # Start new collection of lines
                    current_description_lines = new_lines
                else:
                    current_description_lines.extend(new_lines)
        
        # Create final embed with any remaining lines
        if current_description_lines:
            embed = discord.Embed(color=Colors.EMBED_BORDER)
            embed.set_author(name="Latest Alerts")
            embed.description = "\n".join(current_description_lines)
            embeds.append(embed)
        
        return embeds

    @tasks.loop(hours=1)
    async def hourly_digest(self):
        """Automatically post digest every hour"""
        try:
            logging.info("Starting hourly digest task")
            channel = self.bot.get_channel(self.channel_id)
            if not channel:
                logging.error(f"Could not find channel {self.channel_id}")
                return

            # Add retry logic for critical operations
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    # Process tokens from the hour that just ended
                    hour_key = self.current_hour_key
                    self._update_token_hour()
                    
                    tokens_to_report = self.hour_tokens.get(hour_key, OrderedDict())
                    
                    if tokens_to_report:
                        embeds = await self.create_digest_embed(tokens_to_report, is_hourly=True)
                        if embeds:
                            for embed in embeds:
                                await channel.send(embed=embed)
                            # Clear data only after successful send
                            self._clear_hour_data(hour_key)
                    break  # Success, exit retry loop
                except discord.HTTPException as e:
                    if attempt == max_retries - 1:  # Last attempt
                        raise  # Re-raise if all retries failed
                    await asyncio.sleep(1 * (attempt + 1))  # Exponential backoff
                
        except Exception as e:
            logging.error(f"Critical error in hourly digest: {e}", exc_info=True)
            if self.monitor:
                self.monitor.record_error()
            else:
                self.error_count += 1

    @hourly_digest.before_loop
    async def before_hourly_digest(self):
        """Wait until the start of the next hour before starting the digest loop"""
        await self.bot.wait_until_ready()
        logging.info("Waiting for bot to be ready before starting hourly digest")
        now = datetime.utcnow()
        next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        wait_seconds = (next_hour - now).total_seconds()
        logging.info(f"Hourly digest scheduled to start in {wait_seconds} seconds (at {next_hour})")
        await asyncio.sleep(wait_seconds)
        
    def process_new_token(self, contract, token_data):
        """Process a new token and add it to both the global tracker and hour-specific tracker"""
        # Update the current hour key
        self._update_token_hour()
        
        # Create a copy to avoid modifying the original
        token_data_copy = token_data.copy()
        
        # Ensure we capture the initial market cap when first processing the token
        if 'initial_market_cap' in token_data_copy:
            token_data_copy['initial_market_cap_formatted'] = f"${format_large_number(token_data_copy['initial_market_cap'])}"
        
        # Log the current state before adding
        logging.info(f"DigestCog: Adding token to hour {self.current_hour_key}")
        logging.info(f"DigestCog: Current hour buckets: {list(self.hour_tokens.keys())}")
        logging.info(f"DigestCog: Token data: {token_data_copy}")
        
        # Initialize the hour if it doesn't exist
        if self.current_hour_key not in self.hour_tokens:
            self.hour_tokens[self.current_hour_key] = OrderedDict()
            logging.info(f"DigestCog: Created new hour bucket for {self.current_hour_key}")
        
        # Ensure we have all required fields
        token_data_copy = token_data_copy.copy()  # Create a copy to avoid modifying the original
        
        # Only set default values if they're not already present
        if 'source' not in token_data_copy:
            token_data_copy['source'] = 'unknown'
        if 'user' not in token_data_copy:
            token_data_copy['user'] = 'unknown'
        if 'chain' not in token_data_copy:
            token_data_copy['chain'] = 'unknown'
            
        # Add to hour-specific tracker
        self.hour_tokens[self.current_hour_key][contract] = token_data_copy
        logging.info(f"DigestCog: Added token {token_data_copy.get('name', contract)} to hour {self.current_hour_key}")
        logging.info(f"DigestCog: Current tokens in hour: {len(self.hour_tokens[self.current_hour_key])}")

    @commands.command()
    async def digest(self, ctx):
        """Show the current hour's token digest on demand"""
        try:
            # Add debug logging
            logging.info(f"Running digest command")
            logging.info(f"Current hour key: {self.current_hour_key}")
            logging.info(f"Available hours: {list(self.hour_tokens.keys())}")
            logging.info(f"Current hour trades: {self.hourly_trades}")
            
            # Update the current hour key
            self._update_token_hour()
            
            # Get tokens only from the current hour
            current_hour_tokens = self.hour_tokens.get(self.current_hour_key, OrderedDict())
            
            logging.info(f"Found {len(current_hour_tokens)} tokens for current hour")
            for token_addr, token_data in current_hour_tokens.items():
                logging.info(f"Token: {token_addr}")
                logging.info(f"Trade data: {self.hourly_trades.get(token_addr)}")
            
            # Ensure the hook is installed
            if not self.hook_installed:
                self._install_token_tracker_hook()
                await ctx.send("⚠️ Token tracking hook was not installed. Installing now...")
            
            if not current_hour_tokens:
                await ctx.send("<:dwbb:1321571679109124126>")
                return

            embeds = await self.create_digest_embed(current_hour_tokens, is_hourly=False)
            if embeds:
                for embed in embeds:
                    await ctx.send(embed=embed)
                
        except Exception as e:
            logging.error(f"Error sending digest: {e}", exc_info=True)
            await ctx.send("❌ **Error:** Unable to generate the digest.")

    def _install_token_tracker_hook(self):
        """Install hook on token_tracker if not already installed"""
        if self.hook_installed:
            logging.info("DigestCog: Token tracker hook already installed")
            return
            
        # Replace the token_tracker's log_token method with our wrapped version
        original_log_token = self.token_tracker.log_token
        
        def wrapped_log_token(contract, data, source, user=None):
            # Call the original method
            result = original_log_token(contract, data, source, user)
            
            # Create a copy of the data with source and user explicitly included
            digest_data = data.copy()
            
            # Only set these if they're not already in the data
            if 'source' not in digest_data:
                digest_data['source'] = source
            if 'user' not in digest_data:
                digest_data['user'] = user if user else 'unknown'
            
            # Also add to our hour tracking
            self.process_new_token(contract, digest_data)
            
            logging.info(f"DigestCog: Processed token {data.get('name', contract)} from {digest_data.get('source')} via {digest_data.get('user')}")
            
            return result
            
        # Replace the method
        self.token_tracker.log_token = wrapped_log_token
        self.hook_installed = True
        logging.info("DigestCog: Added hook to token_tracker.log_token")

    @commands.Cog.listener()
    async def on_ready(self):
        """Set up token_tracker hook when cog is ready"""
        self._install_token_tracker_hook()
        
    @commands.command()
    async def refresh_digest(self, ctx):
        """Manually reload tokens from database and refresh the hook"""
        try:
            # Reload tokens from database
            self._load_tokens_from_db()
            
            # Reinstall the hook
            self._install_token_tracker_hook()
            
            # Log the current state
            hour_counts = {hour: len(tokens) for hour, tokens in self.hour_tokens.items()}
            
            await ctx.send(f"✅ Digest refreshed! Loaded tokens from database into {len(self.hour_tokens)} hour buckets.")
            await ctx.send(f"Current hour: {self.current_hour_key} with {len(self.hour_tokens.get(self.current_hour_key, {}))} tokens.")
            
        except Exception as e:
            logging.error(f"Error refreshing digest: {e}", exc_info=True)
            await ctx.send("❌ **Error:** Failed to refresh digest system.")

    def _clear_hour_data(self, hour_key):
        """Clear the token data for a specific hour after it has been processed"""
        if hour_key in self.hour_tokens:
            del self.hour_tokens[hour_key]
            logging.info(f"Cleared token data for hour: {hour_key}")

    def track_trade(self, token_address, token_name, user, amount, trade_type, message_link, dexscreener_url, swap_info=None, message_embed=None, is_first_trade=False):
        try:
            # Add debug logging at start
            logging.info(f"DigestCog.track_trade starting for {token_name} ({token_address})")
            logging.info(f"Current hour tokens: {list(self.hour_tokens.get(self.current_hour_key, {}).keys())}")
            
            # Initialize token data in hour_tokens if not present
            if self.current_hour_key not in self.hour_tokens:
                self.hour_tokens[self.current_hour_key] = OrderedDict()
            
            # Add token to hour_tokens if not present
            if token_address not in self.hour_tokens[self.current_hour_key]:
                # Get token data from token_tracker or create new entry
                token_data = self.token_tracker.tokens.get(token_address, {})
                if not token_data:
                    token_data = {
                        'name': token_name,
                        'chart_url': dexscreener_url,
                        'source': 'cielo',
                        'user': user,
                        'chain': 'solana',  # Default to solana since it's from Cielo
                    }
                self.hour_tokens[self.current_hour_key][token_address] = token_data
                logging.info(f"Added new token {token_name} to hour {self.current_hour_key}")
            
            # Track the trade data
            if token_address not in self.hourly_trades:
                self.hourly_trades[token_address] = {
                    'buys': 0.0,
                    'sells': 0.0,
                    'users': {}
                }
            
            trade_data = self.hourly_trades[token_address]
            
            # Update amounts
            if trade_type == 'buy':
                trade_data['buys'] += amount
                action = 'bought'
            else:
                trade_data['sells'] += amount
                action = 'sold'
            
            # Update user info
            if user not in trade_data['users']:
                trade_data['users'][user] = {
                    'message_link': message_link, 
                    'actions': set(),
                    'is_first_trade': is_first_trade
                }
            trade_data['users'][user]['actions'].add(action)

            logging.info(f"Successfully tracked trade for token {token_address} (first trade: {is_first_trade})")
            
            # Add debug logging after adding to hour_tokens
            logging.info(f"Updated hour tokens: {list(self.hour_tokens.get(self.current_hour_key, {}).keys())}")
            logging.info(f"Updated trade data: {self.hourly_trades.get(token_address)}")
        except Exception as e:
            logging.error(f"Error tracking trade: {e}", exc_info=True)
