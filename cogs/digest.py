import discord
from discord.ext import commands, tasks
import logging
from collections import deque
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
        self.hourly_digest.start()  # Start the hourly task

    def cog_unload(self):
        self.hourly_digest.cancel()  # Clean up task when cog is unloaded

    async def create_digest_embed(self):
        """Create the digest embed - shared between auto and manual digests"""
        if not self.token_tracker.tokens:
            return None

        embed = discord.Embed(color=0x5b594f)
        recent_tokens = list(self.token_tracker.tokens.items())[-10:]  # Last 10 tokens
        
        description_lines = []  # Remove the "Latest Token Alerts" header
        
        async with aiohttp.ClientSession() as session:
            for contract, token in recent_tokens:
                name = token['name']
                chain = token.get('chain', 'Unknown')
                initial_mcap = token.get('initial_market_cap_formatted', 'N/A')
                source = token.get('source', 'unknown')
                user = token.get('user', 'unknown')
                
                # Fetch current market cap
                dex_api_url = f"https://api.dexscreener.com/latest/dex/tokens/{contract}"
                async with safe_api_call(session, dex_api_url) as dex_data:
                    current_mcap = 'N/A'
                    if dex_data and dex_data.get('pairs'):
                        pair = dex_data['pairs'][0]
                        if 'fdv' in pair:
                            current_mcap = f"${format_large_number(float(pair['fdv']))}"

                # Format token information (without markdown headers)
                token_line = f"**[{name}]({token['chart_url']})**"
                stats_line = f"{current_mcap} mc (was {initial_mcap}) ⋅ {chain.lower()}"
                source_line = f"{source} via {user}" if user else source  # Simplified format with "via"
                
                description_lines.extend([token_line, stats_line, source_line, ""])
        
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

            if self.token_tracker.tokens:
                logging.info(f"Found {len(self.token_tracker.tokens)} tokens for digest")
                embed = await self.create_digest_embed()
                if embed:
                    # Get current NY time
                    ny_time = datetime.now(self.ny_tz)
                    # Format for "3-4PM" style (without markdown headers)
                    current_hour = ny_time.strftime('%-I%p').lower()
                    previous_hour = (ny_time - timedelta(hours=1)).strftime('%-I%p').lower()
                    embed.title = f"Hourly Digest: {previous_hour}-{current_hour}"  # Remove ##
                    await channel.send(embed=embed)
                    logging.info("Hourly digest posted successfully")
                
                self.token_tracker.tokens.clear()
                logging.info("Tokens cleared after digest")
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

    @commands.command()
    async def digest(self, ctx):
        """Show the current hour's token digest on demand"""
        try:
            if not self.token_tracker.tokens:
                await ctx.send("<:dwbb:1321571679109124126>")
                return

            embed = await self.create_digest_embed()
            if embed:
                # Get current NY time
                ny_time = datetime.now(self.ny_tz)
                # Format for "Since 3PM" style
                last_hour = ny_time.replace(minute=0, second=0, microsecond=0).strftime('%-I%p').lower()
                embed.title = f"## Hourly Digest: Since {last_hour}"
                await ctx.send(embed=embed)
                
        except Exception as e:
            logging.error(f"Error sending digest: {e}")
            await ctx.send("❌ **Error:** Unable to generate the digest.")
