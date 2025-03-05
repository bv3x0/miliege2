import discord
from discord.ext import commands, tasks
import logging
from collections import deque, OrderedDict
import aiohttp
from datetime import datetime, timedelta
import pytz
import asyncio
from sqlalchemy.exc import SQLAlchemyError # type: ignore
from sqlalchemy import desc # type: ignore
from db.models import Token
import re
from cogs.utils import (
    format_large_number,
    safe_api_call,
    DexScreenerAPI,
    Colors,
    UI
)

class DigestCog(commands.Cog):
    def __init__(self, bot, token_tracker, channel_id):
        self.bot = bot
        self.token_tracker = token_tracker
        self.channel_id = channel_id
        self.ny_tz = pytz.timezone('America/New_York')
        # Store tokens by hour for better separation
        self.hour_tokens = OrderedDict()
        self.current_hour_key = self._get_current_hour_key()
        
        # Get database session from bot
        self.db_session = bot.db_session
        if self.db_session:
            self._load_tokens_from_db()
        else:
            logging.warning("DigestCog: No database session available - token data will not persist across reboots")
        
        # Start the hourly task
        self.hourly_digest.start()
        
        # Flag to track if the hook is installed
        self.hook_installed = False

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
        """Create the digest embed - shared between auto and manual digests"""
        if not tokens:
            return None

        embed = discord.Embed(
            color=Colors.EMBED_BORDER  # Use consistent border color
        )
        
        # Move title to author field with icon
        title = "Hourly Digest" if is_hourly else "Latest Alerts"
        embed.set_author(name=title, icon_url="https://cdn.discordapp.com/emojis/1304234480742957137.webp")
        
        recent_tokens = list(tokens.items())[-10:]  # Last 10 tokens
        
        description_lines = []
        
        async with aiohttp.ClientSession() as session:
            for contract, token in recent_tokens:
                name = token['name']
                chain = token.get('chain', 'Unknown')
                initial_mcap = token.get('initial_market_cap_formatted', 'N/A')
                source = token.get('source', 'unknown')
                user = token.get('user', 'unknown')
                
                # Create Discord message link if we have the necessary info
                message_link = None
                if token.get('message_id') and token.get('channel_id') and token.get('guild_id'):
                    message_link = f"https://discord.com/channels/{token['guild_id']}/{token['channel_id']}/{token['message_id']}"
                
                # Fetch current market cap
                dex_data = await DexScreenerAPI.get_token_info(session, contract)
                current_mcap = 'N/A'
                if dex_data and dex_data.get('pairs'):
                    pair = dex_data['pairs'][0]
                    if 'fdv' in pair:
                        current_mcap = f"${format_large_number(float(pair['fdv']))}"

                # Format token information
                # Compare market caps and add emoji based on 33% threshold
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
                        
                        if percent_change >= 33:
                            status_emoji = " 🟢"  # green circle for 33%+ up
                        elif percent_change <= -33:
                            status_emoji = " 🔴"  # red circle for 33%+ down
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
                
                token_line = f"## [{name}]({token['chart_url']})"
                stats_line = f"{current_mcap} mc (was {initial_mcap}){status_emoji} ⋅ {chain.lower()}"
                source_line = f"{source} via [{user}]({message_link})" if message_link else f"{source} via {user}"
                
                description_lines.extend([token_line, stats_line, source_line])
        
        # Get current NY time for the footer
        ny_time = datetime.now(self.ny_tz)
        if is_hourly:
            # Get timestamps for current and previous hour, ensuring minutes/seconds are 0
            current_hour = ny_time.replace(minute=0, second=0, microsecond=0)
            previous_hour = current_hour - timedelta(hours=1)
            current_hour_ts = int(current_hour.timestamp())
            previous_hour_ts = int(previous_hour.timestamp())
            
            # Use Discord timestamps for both times
            time_text = f"<t:{previous_hour_ts}:t>-<t:{current_hour_ts}:t> <:fedora:1151138750768894003> "
        else:
            # For manual digests, just show "since X time"
            last_hour = ny_time.replace(minute=0, second=0, microsecond=0)
            unix_time = int(last_hour.timestamp())
            time_text = f"since <t:{unix_time}:t> <:fedora:1151138750768894003> "
        
        description_lines.extend(["", "", time_text])  # Add two empty strings for double spacing
        
        embed.description = "\n".join(description_lines)
        return embed

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
                        embed = await self.create_digest_embed(tokens_to_report, is_hourly=True)
                        if embed:
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
            self.monitor.record_error()  # Ensure errors are tracked

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
        
        # Initialize the hour if it doesn't exist
        if self.current_hour_key not in self.hour_tokens:
            self.hour_tokens[self.current_hour_key] = OrderedDict()
        
        # Ensure we have all required fields
        token_data_copy = token_data.copy()  # Create a copy to avoid modifying the original
        
        # Only set default values if they're not already present
        if 'source' not in token_data_copy:
            token_data_copy['source'] = 'unknown'
        if 'user' not in token_data_copy:
            token_data_copy['user'] = 'unknown'
        if 'chain' not in token_data_copy:
            token_data_copy['chain'] = 'unknown'
            
        # Log the token data for debugging
        logging.info(f"Adding token to digest hour {self.current_hour_key}: {token_data_copy.get('name')} - source: {token_data_copy.get('source')}, user: {token_data_copy.get('user')}, chain: {token_data_copy.get('chain')}")
        
        # Add to hour-specific tracker
        self.hour_tokens[self.current_hour_key][contract] = token_data_copy
        logging.info(f"Token {token_data_copy.get('name', contract)} added to hour {self.current_hour_key}")

    @commands.command()
    async def digest(self, ctx):
        """Show the current hour's token digest on demand"""
        try:
            # Ensure the hook is installed
            if not self.hook_installed:
                self._install_token_tracker_hook()
                await ctx.send("⚠️ Token tracking hook was not installed. Installing now...")
            
            # Update the current hour key
            self._update_token_hour()
            
            # Get tokens only from the current hour
            current_hour_tokens = self.hour_tokens.get(self.current_hour_key, OrderedDict())
            
            # Log the token count for debugging
            logging.info(f"DigestCog: !digest command - found {len(current_hour_tokens)} tokens for current hour {self.current_hour_key}")
            
            if not current_hour_tokens:
                await ctx.send("<:dwbb:1321571679109124126>")
                return

            embed = await self.create_digest_embed(current_hour_tokens, is_hourly=False)
            if embed:
                await ctx.send(embed=embed)
                
        except Exception as e:
            logging.error(f"Error sending digest: {e}")
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
