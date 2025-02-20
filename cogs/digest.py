import discord
from discord.ext import commands
import logging
from collections import deque
import aiohttp
from utils import safe_api_call
from utils import format_large_number

class DigestCog(commands.Cog):
    def __init__(self, bot, token_tracker, channel_id):
        self.bot = bot
        self.token_tracker = token_tracker
        self.channel_id = channel_id

    @commands.command()
    async def digest(self, ctx):
        """Show the 10 most recent tokens with market cap comparison."""
        try:
            if not self.token_tracker.tokens:
                await ctx.send("<:dwbb:1321571679109124126>")
                return

            # Create embed
            embed = discord.Embed(color=0x5b594f)
            
            # Get the 10 most recent tokens
            recent_tokens = list(self.token_tracker.tokens.items())[-10:]
            
            # Build description string
            description_lines = ["## Latest Cielo Buys", ""]
            
            # Update market caps before showing digest
            async with aiohttp.ClientSession() as session:
                for contract, token in recent_tokens:
                    name = token['name']
                    chain = token.get('chain', 'Unknown')
                    initial_mcap = token.get('initial_market_cap_formatted', 'N/A')
                    
                    # Fetch current market cap
                    dex_api_url = f"https://api.dexscreener.com/latest/dex/tokens/{contract}"
                    async with safe_api_call(session, dex_api_url) as dex_data:
                        current_mcap = 'N/A'
                        if dex_data and dex_data.get('pairs'):
                            pair = dex_data['pairs'][0]
                            if 'fdv' in pair:
                                current_mcap = f"${format_large_number(float(pair['fdv']))}"

                    token_line = f"**[{name}]({token['chart_url']})**"
                    stats_line = f"{current_mcap} mc (was {initial_mcap}) ⋅ {chain.lower()}"
                    
                    description_lines.extend([token_line, stats_line, ""])
            
            embed.description = "\n".join(description_lines)
            await ctx.send(embed=embed)
            
        except Exception as e:
            logging.error(f"Error sending digest: {e}")
            await ctx.send("❌ **Error:** Unable to generate the digest.")
