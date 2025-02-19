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
            embed = discord.Embed(color=discord.Color.blue())
            
            # Get the 10 most recent tokens (they're already ordered by insertion)
            recent_tokens = list(self.token_tracker.tokens.values())[-10:]
            
            # Build description string starting with the header
            description_lines = ["## Latest Cielo Buys", ""]  # Empty line after header
            
            for token in recent_tokens:
                name = token['name']
                mcap = token['market_cap']
                change = token.get('price_change', '')
                chain = token.get('chain', 'Unknown')  # Get chain from token data
                
                # Format price change with explicit +/- and "24h: " prefix
                if change and change != 'N/A':
                    # Remove any existing % symbol to clean the value
                    clean_change = change.replace('%', '').strip()
                    # Add + sign for positive changes, - is automatically included for negative
                    sign = '+' if float(clean_change) >= 0 else ''
                    change_formatted = f"24h: {sign}{clean_change}%"
                else:
                    change_formatted = "24h: N/A"

                token_line = f"**[{name}]({token['chart_url']})**"
                stats_line = f"{mcap} mc ⋅ {change_formatted} ⋅ {chain.lower()}"  # Use the chain from token data
                
                description_lines.extend([token_line, stats_line, ""])  # Empty string adds spacing between entries
            
            embed.description = "\n".join(description_lines)
            await ctx.send(embed=embed)
            
        except Exception as e:
            logging.error(f"Error sending digest: {e}")
            await ctx.send("❌ **Error:** Unable to generate the digest.")
