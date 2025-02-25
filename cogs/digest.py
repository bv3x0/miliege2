import discord
from discord.ext import commands, tasks
import logging
from collections import deque, OrderedDict
import aiohttp
from utils import safe_api_call, format_large_number
from datetime import datetime, timedelta
import pytz
import asyncio

class DigestCog(commands.Cog):
    def __init__(self, bot, token_tracker, channel_id):
        self.bot = bot
        self.token_tracker = token_tracker
        self.channel_id = channel_id
        self.ny_tz = pytz.timezone('America/New_York')
        # Store tokens by hour for better separation
        self.hour_tokens = OrderedDict()
        self.current_hour_key = self._get_current_hour_key()
        self.hourly_digest.start()  # Start the hourly task

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
            title="Hourly Digest" if is_hourly else "Latest Alerts"
        )
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
                dex_api_url = f"https://api.dexscreener.com/latest/dex/tokens/{contract}"
                async with safe_api_call(session, dex_api_url) as dex_data:
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
                        
                        # Handle suffixes properly
                        if 'M' in clean_str:
                            return float(clean_str.replace('M', '')) * 1000000
                        elif 'K' in clean_str:
                            return float(clean_str.replace('K', '')) * 1000
                        elif 'B' in clean_str:
                            return float(clean_str.replace('B', '')) * 1000000000
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
                            status_emoji = " 😯"  # hushed emoji for 33%+ up
                        elif percent_change <= -33:
                            status_emoji = " <:ggggg:1149703938153664633>"  # custom emoji for 33%+ down
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
                
                token_line = f"## [{name}]({token['chart_url']}){status_emoji}"
                stats_line = f"{current_mcap} mc (was {initial_mcap}) ⋅ {chain.lower()}"
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

            # Process tokens from the hour that just ended
            hour_key = self.current_hour_key
            self._update_token_hour()  # Updates to the new hour
            
            tokens_to_report = self.hour_tokens.get(hour_key, OrderedDict())
            
            if tokens_to_report:
                logging.info(f"Found {len(tokens_to_report)} tokens for digest in hour {hour_key}")
                embed = await self.create_digest_embed(tokens_to_report, is_hourly=True)
                if embed:
                    await channel.send(embed=embed)
                    logging.info("Hourly digest posted successfully")
                
                # Clear the hour that just ended
                if hour_key in self.hour_tokens:
                    del self.hour_tokens[hour_key]
                logging.info(f"Tokens for hour {hour_key} cleared after digest")
                
                # Also clear the global token tracker if there are tokens from this hour
                if self.token_tracker.tokens:
                    self.token_tracker.tokens.clear()
                    logging.info("Global token tracker cleared")
            else:
                logging.info("No tokens to report in hourly digest")
                await channel.send("<:fedora:1151138750768894003> nothing to report")

        except Exception as e:
            logging.error(f"Error in hourly digest: {e}", exc_info=True)

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
        if 'source' not in token_data:
            token_data['source'] = 'unknown'
        if 'user' not in token_data:
            token_data['user'] = 'unknown'
        if 'chain' not in token_data:
            token_data['chain'] = 'unknown'
            
        # Log the token data for debugging
        logging.info(f"Adding token to digest hour {self.current_hour_key}: {token_data.get('name')} - source: {token_data.get('source')}, user: {token_data.get('user')}, chain: {token_data.get('chain')}")
        
        # Add to hour-specific tracker
        self.hour_tokens[self.current_hour_key][contract] = token_data
        logging.info(f"Token {token_data.get('name', contract)} added to hour {self.current_hour_key}")

    @commands.command()
    async def digest(self, ctx):
        """Show the current hour's token digest on demand"""
        try:
            # Update the current hour key
            self._update_token_hour()
            
            # Get tokens only from the current hour
            current_hour_tokens = self.hour_tokens.get(self.current_hour_key, OrderedDict())
            
            if not current_hour_tokens:
                await ctx.send("<:dwbb:1321571679109124126>")
                return

            embed = await self.create_digest_embed(current_hour_tokens, is_hourly=False)
            if embed:
                await ctx.send(embed=embed)
                
        except Exception as e:
            logging.error(f"Error sending digest: {e}")
            await ctx.send("❌ **Error:** Unable to generate the digest.")

    @commands.Cog.listener()
    async def on_ready(self):
        """Set up token_tracker hook when cog is ready"""
        # Replace the token_tracker's log_token method with our wrapped version
        original_log_token = self.token_tracker.log_token
        
        def wrapped_log_token(contract, data, source, user=None):
            # Call the original method
            result = original_log_token(contract, data, source, user)
            
            # Create a copy of the data with source and user explicitly included
            digest_data = data.copy()
            digest_data['source'] = source
            digest_data['user'] = user if user else 'unknown'
            
            # Also add to our hour tracking
            self.process_new_token(contract, digest_data)
            
            logging.info(f"DigestCog: Processed token {data.get('name', contract)} from {source} via {user}")
            
            return result
            
        # Replace the method
        self.token_tracker.log_token = wrapped_log_token
        logging.info("DigestCog: Added hook to token_tracker.log_token")
