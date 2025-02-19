import discord
from discord.ext import commands, tasks
from datetime import time
from pytz import timezone
import logging

class DigestCog(commands.Cog):
    def __init__(self, bot, token_tracker, channel_id):
        self.bot = bot
        self.token_tracker = token_tracker
        self.channel_id = channel_id
        self.est_tz = timezone('America/New_York')
        
        # Start the daily digest task
        self.daily_digest.start()

    def cog_unload(self):
        self.daily_digest.cancel()

    @tasks.loop(time=time(hour=7, tzinfo=timezone('America/New_York')))
    async def daily_digest(self):
        """Run the daily digest at 7 AM EST"""
        try:
            channel = self.bot.get_channel(self.channel_id)
            if not channel:
                logging.error("Could not find digest channel")
                return

            await self._send_digest(channel)
        except Exception as e:
            logging.error(f"Error in daily digest: {e}")
        finally:
            self.token_tracker.clear_daily()

    @commands.command()
    async def digest(self, ctx):
        """Manually trigger the daily digest."""
        await self._send_digest(ctx)

    async def _send_digest(self, destination):
        """Send the daily digest of tokens.
        
        Args:
            destination: The Discord channel or context to send the digest to
        """
        try:
            if not self.token_tracker.tokens:
                await destination.send("<:dwbb:1321571679109124126>")
                return

            embed = discord.Embed(title="**New Coins:**", color=discord.Color.blue())
            digest_message = ""
            current_length = 0
            MAX_FIELD_LENGTH = 1024  # Discord's limit

            for token in self.token_tracker.tokens.values():
                line = f"- [{token['name']}]({token['chart_url']}) [{token['market_cap']}]"
                if token.get('buy_count', 0) > 1:
                    line += " 👀"
                line += "\n"

                if current_length + len(line) > MAX_FIELD_LENGTH:
                    break

                digest_message += line
                current_length += len(line)

            if digest_message:
                embed.add_field(name="", value=digest_message, inline=False)
                await destination.send(embed=embed)
            else:
                await destination.send("No tokens to report.")
            
        except Exception as e:
            logging.error(f"Error sending digest: {e}")
            await destination.send("❌ An error occurred while generating the digest.")
