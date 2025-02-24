import discord
from discord.ext import commands, tasks
import logging
from collections import deque
import aiohttp
from utils import safe_api_call, format_large_number
from datetime import datetime, timedelta
import pytz

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
        
        description_lines = ["## Latest Token Alerts", ""]
        
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

                # Format token information
                token_line = f"**[{name}]({token['chart_url']})**"
                stats_line = f"{current_mcap} mc (was {initial_mcap}) ⋅ {chain.lower()}"
                source_line = f"{source} alert by {user}" if user else f"{source} alert"
                
                description_lines.extend([token_line, stats_line, source_line, ""])
        
        embed.description = "\n".join(description_lines)
        return embed

    @tasks.loop(hours=1)
    async def hourly_digest(self):
        """Automatically post digest every hour"""
        try:
            channel = self.bot.get_channel(self.channel_id)
            if not channel:
                logging.error(f"Could not find channel {self.channel_id}")
                return

            if self.token_tracker.tokens:
                embed = await self.create_digest_embed()
                if embed:
                    # Get current NY time
                    ny_time = datetime.now(self.ny_tz)
                    # Format for "3-4PM" style
                    current_hour = ny_time.strftime('%-I%p').lower()
                    previous_hour = (ny_time - timedelta(hours=1)).strftime('%-I%p').lower()
                    embed.title = f"## Hourly Digest: {previous_hour}-{current_hour}"
                    await channel.send(embed=embed)
                
                self.token_tracker.tokens.clear()
                logging.info("Hourly digest posted and tokens cleared")
            else:
                await channel.send("<:fedora:1151138750768894003> nothing to report")
                logging.info("Empty hourly digest reported")

        except Exception as e:
            logging.error(f"Error in hourly digest: {e}")

    @hourly_digest.before_loop
    async def before_hourly_digest(self):
        """Wait until the start of the next hour before starting the digest loop"""
        await self.bot.wait_until_ready()
        now = datetime.utcnow()
        next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        await discord.utils.sleep_until(next_hour)
        logging.info(f"Hourly digest scheduled to start at {next_hour}")

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
