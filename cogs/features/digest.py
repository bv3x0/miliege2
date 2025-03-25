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
        logging.info(f"Getting current hour key: {key}")
        if key not in self.hour_tokens:
            logging.info(f"Creating new hour bucket for {key}")
            self.hour_tokens[key] = OrderedDict()
        return key

    async def create_digest_embed(self, tokens, is_hourly=True):
        """Create the digest embed(s) - shared between auto and manual digests"""
        if not tokens:
            return None

        # Convert tokens to list and calculate sorting metrics
        token_list = []
        for contract, token in tokens.items():
            # Calculate status score (4=up, 3=normal, 2=x, 1=gravestone)
            status_score = 3  # Default score for normal tokens
            
            # Get current and initial mcap for percentage calculation
            try:
                async with aiohttp.ClientSession() as session:
                    dex_data = await DexScreenerAPI.get_token_info(session, contract)
                    current_mcap = 'N/A'
                    if dex_data and dex_data.get('pairs'):
                        pair = dex_data['pairs'][0]
                        if 'fdv' in pair:
                            current_mcap = f"${format_large_number(float(pair['fdv']))}"
            
                current_mcap_value = self.parse_market_cap(current_mcap)
                initial_mcap_value = token.get('initial_market_cap')
                
                if current_mcap_value and initial_mcap_value and initial_mcap_value > 0:
                    percent_change = ((current_mcap_value - initial_mcap_value) / initial_mcap_value) * 100
                    if percent_change >= 40:
                        status_score = 4  # :up:
                    elif percent_change <= -40:
                        status_score = 1  # 🪦
            except Exception as e:
                logging.error(f"Error calculating percent change: {e}")

            # Check for sell-only tokens
            if contract in self.hourly_trades:
                trade_data = self.hourly_trades[contract]
                total_buys = sum(user_data.get('buys', 0) for user_data in trade_data['users'].values())
                total_sells = sum(user_data.get('sells', 0) for user_data in trade_data['users'].values())
                if total_sells > 0 and total_buys == 0:
                    status_score = 2  # ❌

            # Calculate total buy amount
            total_buys = 0
            if contract in self.hourly_trades:
                trade_data = self.hourly_trades[contract]
                total_buys = sum(user_data.get('buys', 0) for user_data in trade_data['users'].values())

            token_list.append({
                'contract': contract,
                'token': token,
                'status_score': status_score,
                'total_buys': total_buys
            })

        # Sort tokens by status_score (descending) and total_buys (descending)
        token_list.sort(key=lambda x: (-x['status_score'], -x['total_buys']))

        # Take last 10 tokens after sorting
        recent_tokens = [(t['contract'], t['token']) for t in token_list[-10:]]

        # Create embeds with the sorted tokens
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
                
                # IMPORTANT FIX #1: Add red X to tokens with only sells
                if contract in self.hourly_trades:
                    trade_data = self.hourly_trades[contract]
                    total_buys = sum(user_data.get('buys', 0) for user_data in trade_data['users'].values())
                    total_sells = sum(user_data.get('sells', 0) for user_data in trade_data['users'].values())
                    if total_sells > 0 and total_buys == 0:
                        token_line += " ❌"
                
                # Remove any existing $ from initial_mcap if it exists
                initial_mcap_clean = initial_mcap.replace('$', '') if initial_mcap else 'N/A'
                
                # IMPORTANT FIX #2: Always use chain from token data, never default to unknown
                chain_display = chain.lower() if chain and chain != "Unknown" else "unknown"
                stats_line = f"{current_mcap} mc (was ${initial_mcap_clean}) ⋅ {chain_display}"
                
                # Calculate the length of new lines to be added
                new_lines = [token_line, stats_line]
                
                # IMPORTANT FIX #3: Always prioritize displaying trade info when available
                if contract in self.hourly_trades:
                    trade_data = self.hourly_trades[contract]
                    has_trades = sum(user_data.get('buys', 0) > 0 or user_data.get('sells', 0) > 0 for user_data in trade_data['users'].values()) > 0
                    
                    if has_trades:
                        # First try the structured formatting
                        trade_info = self._format_trade_info(trade_data)
                        
                        if trade_info and trade_info.strip():
                            new_lines.append(trade_info)
                            logging.info(f"Added trade info for {name}: {trade_info}")
                        else:
                            # If that fails, directly create trade info for the main users
                            # CRITICAL FALLBACK - Create explicit trade info
                            if total_sells:
                                # Look for users who sold and show the first one
                                for user, user_data in trade_data['users'].items():
                                    if 'sell' in user_data['actions']:
                                        sell_amt = format_large_number(user_data.get('sells', 0))
                                        user_link = f"[{user}]({user_data['message_link']})" if user_data.get('message_link') else user
                                        new_lines.append(f"{user_link}: sell ${sell_amt}")
                                        break
                            elif total_buys:
                                # Look for users who bought and show the first one
                                for user, user_data in trade_data['users'].items():
                                    if 'buy' in user_data['actions']:
                                        buy_amt = format_large_number(user_data.get('buys', 0))
                                        user_link = f"[{user}]({user_data['message_link']})" if user_data.get('message_link') else user
                                        new_lines.append(f"{user_link}: buy ${buy_amt}")
                                        break
                            else:
                                # Last resort - just use the source via user
                                source_line = f"{source} via [{user}]({original_message_link or message_link})" if (original_message_link or message_link) else f"{source} via {user}"
                                new_lines.append(source_line)
                                logging.info(f"Ultimate fallback to source line for {name}: {source_line}")
                    else:
                        # No trade amounts, use source via user
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
            now = datetime.now(self.ny_tz)
            logging.info(f"Current NY time: {now}")
            
            channel = self.bot.get_channel(self.channel_id)
            if not channel:
                logging.error(f"Could not find channel {self.channel_id}")
                return

            # Get the previous hour's key since we want to digest what just finished
            previous_hour = (now - timedelta(hours=1)).strftime("%Y-%m-%d-%H")
            logging.info(f"Processing digest for hour: {previous_hour}")
            
            tokens_to_report = self.hour_tokens.get(previous_hour, OrderedDict())
            logging.info(f"Found {len(tokens_to_report)} tokens to report for hour {previous_hour}")
            
            if tokens_to_report:
                embeds = await self.create_digest_embed(tokens_to_report, is_hourly=True)
                if embeds:
                    for embed in embeds:
                        await channel.send(embed=embed)
                    # Clear data only after successful send
                    self._clear_hour_data(previous_hour)
                    logging.info(f"Successfully posted and cleared digest for hour {previous_hour}")
                else:
                    logging.warning(f"No embeds created for {len(tokens_to_report)} tokens")
            else:
                logging.info(f"No tokens to report for hour {previous_hour}")

        except Exception as e:
            logging.error(f"Critical error in hourly digest: {e}", exc_info=True)

    @hourly_digest.before_loop
    async def before_hourly_digest(self):
        """Wait until the start of the next hour before starting the digest loop"""
        await self.bot.wait_until_ready()
        logging.info("Waiting for bot to be ready before starting hourly digest")
        
        # Use NY timezone consistently
        now = datetime.now(self.ny_tz)
        next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        wait_seconds = (next_hour - now).total_seconds()
        
        logging.info(f"Current NY time: {now}")
        logging.info(f"Next digest scheduled for NY time: {next_hour}")
        logging.info(f"Waiting {wait_seconds} seconds until next digest")
        
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
        
        # Track the trade data with per-user amounts
        if contract not in self.hourly_trades:
            self.hourly_trades[contract] = {'users': {}}
        
        trade_data = self.hourly_trades[contract]
        
        # Update amounts and determine action
        action = None
        if 'buy' in token_data:
            amount = token_data['buy']
            action = 'bought'
        elif 'sell' in token_data:
            amount = token_data['sell']
            action = 'sold'
        
        # Update user info only if we have an action
        if action and 'user' in token_data:
            user = token_data['user']
            if user not in trade_data['users']:
                trade_data['users'][user] = {
                    'message_link': token_data.get('message_link', ''),
                    'actions': set(),
                    'is_first_trade': token_data.get('is_first_trade', False),
                    'buys': 0.0,
                    'sells': 0.0  # Add per-user amount tracking
                }
            
            # Update the specific user's amounts
            if action == 'bought':
                trade_data['users'][user]['buys'] += amount
            else:  # sold
                trade_data['users'][user]['sells'] += amount
            
            trade_data['users'][user]['actions'].add(action)

            logging.info(f"Tracked trade: {user} {action} {token_data['name']} for ${amount}")

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
            
        # Add debug logging
        logging.info("DigestCog: Installing token tracker hook")
        
        # Replace the token_tracker's log_token method with our wrapped version
        original_log_token = self.token_tracker.log_token
        
        def wrapped_log_token(contract, data, source, user=None):
            logging.info(f"DigestCog hook: Processing token {data.get('name', contract)} from {source}")
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
            
            # Extract chain from message_embed if not explicitly provided
            if not chain and message_embed and 'fields' in message_embed:
                for field in message_embed['fields']:
                    # Case-insensitive check for chain field
                    if field.get('name', '').lower() == 'chain':
                        chain = field.get('value', 'unknown')
                        logging.info(f"Extracted chain from embed: {chain}")
                        break
            
            # If we still don't have a chain, try to extract from dexscreener_url
            if (not chain or chain == 'unknown') and dexscreener_url:
                chain_match = re.search(r'dexscreener\.com/([^/]+)/', dexscreener_url)
                if chain_match:
                    chain = chain_match.group(1)
                    logging.info(f"Extracted chain from dexscreener URL: {chain}")
            
            # Default to solana for Cielo trades if still unknown
            if (not chain or chain == 'unknown'):
                chain = "solana"  # Most Cielo tokens are on Solana
                logging.info(f"Defaulting to solana chain for Cielo trade")
            
            # Always normalize chain
            chain = chain.lower() if chain else 'unknown'
            
            # Process new token or update existing token
            if token_address not in self.hour_tokens.get(current_hour, {}):
                # Create new token entry with all required fields
                self.hour_tokens[current_hour][token_address] = {
                    'name': token_name,
                    'chart_url': dexscreener_url,
                    'source': 'cielo',
                    'user': user,
                    'chain': chain,
                    'original_message_id': message_embed.get('id') if message_embed else None,
                    'original_channel_id': message_link.split('/')[5] if message_link else None,
                    'original_guild_id': message_link.split('/')[4] if message_link else None
                }
                
                # Add token_data if provided
                if token_data:
                    self.hour_tokens[current_hour][token_address].update(token_data)
                
                logging.info(f"Created new token entry for {token_name} with chain={chain}")
            else:
                # Update existing token
                token_entry = self.hour_tokens[current_hour][token_address]
                
                # ALWAYS set source to cielo for cielo trades
                token_entry['source'] = 'cielo'
                
                # Update user if not unknown
                if user and user != "unknown":
                    token_entry['user'] = user
                
                # Set chain if provided and current value is unknown
                if chain and chain != 'unknown' and (not token_entry.get('chain') or token_entry['chain'] == 'unknown'):
                    token_entry['chain'] = chain
                    logging.info(f"Updated chain for {token_name} to {chain}")
                
                # Ensure chart_url exists
                if not token_entry.get('chart_url'):
                    token_entry['chart_url'] = dexscreener_url
            
            # Update trade tracking - SIMPLIFIED VERSION
            if token_address not in self.hourly_trades:
                self.hourly_trades[token_address] = {'users': {}}
            
            trade_data = self.hourly_trades[token_address]
            
            # Initialize or update user data
            if user not in trade_data['users']:
                trade_data['users'][user] = {
                    'message_link': message_link,
                    'actions': set(),
                    'is_first_trade': is_first_trade,
                    'buys': 0.0,
                    'sells': 0.0
                }
            
            # Update the specific user's amounts and actions
            if trade_type == 'buy':
                trade_data['users'][user]['buys'] += amount
                trade_data['users'][user]['actions'].add('buy')
            else:  # sell
                trade_data['users'][user]['sells'] += amount
                trade_data['users'][user]['actions'].add('sell')
            
            # Update message link if newer
            if message_link and trade_data['users'][user]['message_link']:
                try:
                    current_msg_id = int(trade_data['users'][user]['message_link'].split('/')[-1])
                    new_msg_id = int(message_link.split('/')[-1])
                    if new_msg_id > current_msg_id:
                        trade_data['users'][user]['message_link'] = message_link
                except (ValueError, IndexError) as e:
                    logging.warning(f"Error comparing message IDs, using new link: {e}")
                    trade_data['users'][user]['message_link'] = message_link
            else:
                trade_data['users'][user]['message_link'] = message_link or trade_data['users'][user]['message_link']
            
            logging.info(f"Tracked {trade_type}: {user} {trade_type} {token_name} for ${amount} on {chain}")
            logging.info(f"User {user} message link: {trade_data['users'][user]['message_link']}")
            
        except Exception as e:
            logging.error(f"Error tracking trade: {e}", exc_info=True)

    def _format_trade_info(self, trade_data):
        """Format trade information for a token"""
        # Group users by their trades
        user_trades = []
        
        for user, user_data in trade_data['users'].items():
            # Create user link if we have a message_link
            user_link = f"[{user}]({user_data['message_link']})" if user_data.get('message_link') else user
            buy_amount = user_data.get('buys', 0)
            sell_amount = user_data.get('sells', 0)
            is_first = user_data.get('is_first_trade', False)
            
            # Format amounts
            trade_parts = []
            if buy_amount > 0:
                formatted_buy = format_large_number(buy_amount)
                trade_parts.append(f"${formatted_buy} buy")
            if sell_amount > 0:
                formatted_sell = format_large_number(sell_amount)
                trade_parts.append(f"${formatted_sell} sell")
            
            if trade_parts:
                star = " ⭐" if is_first else ""
                user_trades.append(f"{user_link} {', '.join(trade_parts)}{star}")
        
        return "\n".join(user_trades) if user_trades else ""
