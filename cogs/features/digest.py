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
            
        except Exception as e:
            logging.error(f"DigestCog: Error loading tokens from database: {e}", exc_info=True)

    def cog_unload(self):
        self.hourly_digest.cancel()  # Clean up task when cog is unloaded
        
    @property
    def current_hour_key(self):
        """Get the current hour key and ensure the hour bucket exists"""
        ny_time = datetime.now(self.ny_tz)
        key = ny_time.strftime("%Y-%m-%d-%H")
        if key not in self.hour_tokens:
            self.hour_tokens[key] = OrderedDict()
        return key

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
                
                # Add this before trying to construct the token_line
                if 'chart_url' not in token or not token['chart_url']:
                    # Set a default chart URL if missing
                    token['chart_url'] = f"https://dexscreener.com/{chain.lower()}/{contract}"
                    logging.warning(f"Missing chart_url for {name}, creating default")
                
                # Then construct token_line
                token_line = f"### [{name}]({token['chart_url']})"
                
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
                    current_mcap_value = self.parse_market_cap(current_mcap)
                    initial_mcap_value = token.get('initial_market_cap')  # Already parsed when stored
                    
                    status_emoji = ""
                    if current_mcap_value and initial_mcap_value and initial_mcap_value > 0:
                        percent_change = ((current_mcap_value - initial_mcap_value) / initial_mcap_value) * 100
                        logging.info(f"Token {name} mcap change: {percent_change}% (from {initial_mcap_value} to {current_mcap_value})")
                        
                        if percent_change >= 40:
                            status_emoji = " :up:"
                        elif percent_change <= -40:
                            status_emoji = " 🪦"
                except Exception as e:
                    logging.error(f"Error calculating percent change for {name}: {e}")
                    status_emoji = ""
                
                # Make sure we have valid values for display
                if not source or source == "":
                    source = "unknown"
                if not user or user == "":
                    user = "unknown"
                if not chain or chain == "":
                    chain = "unknown"
                
                # Log the values for debugging
                logging.info(f"Digest display for {name}: chain={chain}, source={source}, user={user}")
                
                # If we have trade data, log details about it for debugging
                if contract in self.hourly_trades:
                    trade_data = self.hourly_trades[contract]
                    for user, user_data in trade_data['users'].items():
                        logging.info(f"Trade data for {user}: message_link={user_data.get('message_link', 'None')}")
                
                # Format the description lines
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
                
                # If we have trade data, always show it regardless of source
                if contract in self.hourly_trades:
                    trade_data = self.hourly_trades[contract]
                    if trade_data.get('sells', 0) > 0 or trade_data.get('buys', 0) > 0:
                        # Format trade info with proper links
                        trade_info = self._format_trade_info(trade_data)
                        if trade_info:
                            new_lines.append(trade_info)
                        else:
                            # Fallback to source via user only if trade info formatting failed
                            source_line = f"{source} via [{user}]({original_message_link or message_link})" if (original_message_link or message_link) else f"{source} via {user}"
                            new_lines.append(source_line)
                    else:
                        # No transaction amounts, use source via user
                        source_line = f"{source} via [{user}]({original_message_link or message_link})" if (original_message_link or message_link) else f"{source} via {user}"
                        new_lines.append(source_line)
                else:
                    # No trade data at all, use source via user
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
        
    def parse_market_cap(self, mcap_str):
        """Parse market cap string to float value"""
        try:
            if not mcap_str or mcap_str == 'N/A':
                return None
            
            # Remove $ and any commas
            clean_mcap = mcap_str.replace('$', '').replace(',', '')
            
            # Handle K/M/B suffixes
            multiplier = 1
            if 'K' in clean_mcap.upper():
                multiplier = 1000
                clean_mcap = clean_mcap.upper().replace('K', '')
            elif 'M' in clean_mcap.upper():
                multiplier = 1000000
                clean_mcap = clean_mcap.upper().replace('M', '')
            elif 'B' in clean_mcap.upper():
                multiplier = 1000000000
                clean_mcap = clean_mcap.upper().replace('B', '')
            
            return float(clean_mcap) * multiplier
        except (ValueError, TypeError):
            return None

    def process_new_token(self, contract, token_data):
        """Process a new token and add it to both the global tracker and hour-specific tracker"""
        current_hour = self.current_hour_key
        
        # Extract initial market cap from message_embed if available
        if 'message_embed' in token_data:
            try:
                embed_data = token_data['message_embed']
                first_field = next((f['value'] for f in embed_data['fields'] if 'value' in f), None)
                if first_field:
                    mc_match = re.search(r'MC:\s*\$([0-9,.]+[KMB]?)', first_field)
                    if mc_match:
                        mcap_str = mc_match.group(1)
                        mcap_value = self.parse_market_cap(mcap_str)
                        if mcap_value is not None:
                            token_data['initial_market_cap'] = mcap_value
                            token_data['initial_market_cap_formatted'] = f"${mcap_str}"
                            logging.info(f"Extracted initial market cap: {mcap_str} for {token_data.get('name', 'Unknown')}")
            except Exception as e:
                logging.error(f"Error extracting initial market cap: {e}")
        
        # Add to hour tokens
        if contract not in self.hour_tokens.get(current_hour, {}):
            self.hour_tokens[current_hour][contract] = token_data
        
        # Track the trade data
        if contract not in self.hourly_trades:
            self.hourly_trades[contract] = {'buys': 0.0, 'sells': 0.0, 'users': {}}
        
        trade_data = self.hourly_trades[contract]
        
        # Update amounts and determine action
        action = None
        if 'buy' in token_data:
            trade_data['buys'] += token_data['buy']
            action = 'bought'
        elif 'sell' in token_data:
            trade_data['sells'] += token_data['sell']
            action = 'sold'
        
        # Update user info only if we have an action
        if action and 'user' in token_data:
            if token_data['user'] not in trade_data['users']:
                trade_data['users'][token_data['user']] = {
                    'message_link': token_data.get('message_link', ''),
                    'actions': set(),
                    'is_first_trade': token_data.get('is_first_trade', False)
                }
            if action:  # Only add action if it was determined
                trade_data['users'][token_data['user']]['actions'].add(action)

            logging.info(f"Tracked trade: {token_data['user']} {action} {token_data['name']} for ${token_data['buy'] if 'buy' in token_data else token_data['sell']}")

    @commands.command()
    async def digest(self, ctx):
        """Show the current hour's token digest on demand"""
        try:
            # Add debug logging
            logging.info(f"Running digest command")
            logging.info(f"Current hour key: {self.current_hour_key}")
            logging.info(f"Available hours: {list(self.hour_tokens.keys())}")
            logging.info(f"Current hour trades: {self.hourly_trades}")
            
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

    def track_trade(self, token_address, token_name, user, amount, trade_type, message_link, 
                    dexscreener_url, swap_info=None, message_embed=None, is_first_trade=False, 
                    chain=None, token_data=None):
        """Track a trade for the digest"""
        try:
            if not token_address or not token_name or not user:
                logging.warning(f"Missing required trade data: address={token_address}, name={token_name}, user={user}")
                return
            
            if amount <= 0:
                logging.warning(f"Invalid trade amount: ${amount}")
                return
            
            if trade_type not in ['buy', 'sell']:
                logging.warning(f"Invalid trade type: {trade_type}")
                return
            
            current_hour = self.current_hour_key
            
            # Ensure dexscreener_url is always set - this is the critical part
            if not dexscreener_url and chain and token_address:
                dexscreener_url = f"https://dexscreener.com/{chain.lower()}/{token_address}"
                logging.info(f"Generated chart URL: {dexscreener_url}")
            
            # Process new token or update existing token
            if token_address not in self.hour_tokens.get(current_hour, {}):
                # Create a new entry
                token_entry = {
                    'name': token_name,
                    'chart_url': dexscreener_url,  # Always set this!
                    'source': 'cielo',
                    'user': user,
                    'chain': chain or 'unknown'
                }
                
                # Add additional data from token_data if available
                if token_data:
                    token_entry.update({k: v for k, v in token_data.items() if v is not None})
                
                # Store in hour_tokens
                self.hour_tokens[current_hour][token_address] = token_entry
                logging.info(f"Created new token entry for {token_name} with chart_url: {dexscreener_url}")
            else:
                # Update existing entry
                token_entry = self.hour_tokens[current_hour][token_address]
                
                # Always update these fields
                token_entry['source'] = 'cielo'
                token_entry['user'] = user if user != "unknown" else token_entry.get('user', 'unknown')
                
                # CRITICAL: Ensure chart_url exists
                if 'chart_url' not in token_entry or not token_entry['chart_url']:
                    token_entry['chart_url'] = dexscreener_url
                    logging.info(f"Updated missing chart_url for {token_name}: {dexscreener_url}")
                
                # Update other fields if needed
                if chain:
                    token_entry['chain'] = chain
                
                # Merge any additional data from token_data
                if token_data:
                    for k, v in token_data.items():
                        if v is not None and (k not in token_entry or not token_entry[k]):
                            token_entry[k] = v
            
            # Update trade tracking
            if token_address not in self.hourly_trades:
                self.hourly_trades[token_address] = {'buys': 0.0, 'sells': 0.0, 'users': {}}
            
            trade_data = self.hourly_trades[token_address]
            if trade_type == 'buy':
                trade_data['buys'] += amount
            else:
                trade_data['sells'] += amount
            
            if user not in trade_data['users']:
                trade_data['users'][user] = {
                    'message_link': message_link,
                    'actions': set(),
                    'is_first_trade': is_first_trade
                }
            
            trade_data['users'][user]['actions'].add(trade_type)
            
            logging.info(f"Tracked {trade_type}: {user} {trade_type} {token_name} for ${amount}")
            
        except Exception as e:
            logging.error(f"Error tracking trade: {e}", exc_info=True)

    def _format_trade_info(self, trade_data):
        """Format trade information for a token"""
        action_groups = {
            'bought': [],
            'sold': [],
            'bought and sold': []
        }
        
        # Debug logging to verify message links
        for user, user_data in trade_data['users'].items():
            logging.info(f"Trade data for {user}: message_link={user_data.get('message_link', 'None')}")
            
            actions = user_data['actions']
            # Only create user link if we have a message_link
            user_link = f"[{user}]({user_data['message_link']})" if user_data.get('message_link') else user
            is_first = user_data.get('is_first_trade', False)
            
            if 'bought' in actions and 'sold' in actions:
                action_groups['bought and sold'].append((user_link, is_first))
            elif 'bought' in actions:
                action_groups['bought'].append((user_link, is_first))
            elif 'sold' in actions:
                action_groups['sold'].append((user_link, is_first))
        
        trade_parts = []
        
        def format_amount(amount):
            return format_large_number(amount) if amount >= 1000 else str(int(amount))
        
        if action_groups['bought']:
            users, is_first = zip(*action_groups['bought'])
            amount = format_amount(trade_data['buys'])
            star = " ⭐" if any(is_first) else ""
            trade_parts.append(f"{', '.join(users)} bought ${amount}{star}")
        
        if action_groups['sold']:
            users, _ = zip(*action_groups['sold'])
            amount = format_amount(trade_data['sells'])
            trade_parts.append(f"{', '.join(users)} sold ${amount}")
        
        if action_groups['bought and sold']:
            users, is_first = zip(*action_groups['bought and sold'])
            buy_amount = format_amount(trade_data['buys'])
            sell_amount = format_amount(trade_data['sells'])
            star = " ⭐" if any(is_first) else ""
            trade_parts.append(f"{', '.join(users)} bought ${buy_amount} and sold ${sell_amount}{star}")
        
        return '\n'.join(trade_parts) if trade_parts else ""
