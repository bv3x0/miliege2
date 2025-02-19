import discord
from discord.ext import commands
import logging
from collections import deque

class DigestCog(commands.Cog):
    def __init__(self, bot, token_tracker, channel_id):
        self.bot = bot
        self.token_tracker = token_tracker
        self.channel_id = channel_id

    @commands.command()
    async def digest(self, ctx):
        """Show the 10 most recent tokens."""
        try:
            if not self.token_tracker.tokens:
                await ctx.send("<:dwbb:1321571679109124126>")
                return

            # Create embed
            embed = discord.Embed(
                title="10 Latest Cielo Alerts",
                color=discord.Color.blue()
            )

            # Get the 10 most recent tokens (they're already ordered by insertion)
            recent_tokens = list(self.token_tracker.tokens.values())[-10:]
            
            for token in recent_tokens:
                name = token['name']
                chain = token.get('chain', '')
                mcap = token['market_cap']
                change = token.get('price_change', '')
                
                # Format stats line with mc and 24h labels
                stats_line = f"{chain} / {mcap} mc / {change} 24h"
                
                embed.add_field(
                    name=f"[{name}]({token['chart_url']})\n{stats_line}",
                    value="",
                    inline=False
                )

            await ctx.send(embed=embed)
            
        except Exception as e:
            logging.error(f"Error sending digest: {e}")
            await ctx.send("❌ **Error:** Unable to generate the digest.")
