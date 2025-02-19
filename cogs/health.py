import discord
from discord.ext import commands
import logging

class HealthMonitor(commands.Cog):
    def __init__(self, bot, monitor):
        self.bot = bot
        self.monitor = monitor

    @commands.Cog.listener()
    async def on_message(self, message):
        try:
            self.monitor.record_message()
        except Exception as e:
            logging.error(f"Error in health monitor: {e}")
            self.monitor.record_error()

    @commands.command()
    async def health(self, ctx):
        """Check the bot's health metrics"""
        try:
            uptime = self.monitor.get_uptime()
            embed = discord.Embed(
                title="Health Status",
                color=discord.Color.green()
            )
            
            embed.add_field(
                name="Uptime",
                value=f"{uptime.days}d {uptime.seconds // 3600}h {(uptime.seconds // 60) % 60}m"
            )
            embed.add_field(
                name="Errors",
                value=str(self.monitor.errors_since_restart)
            )
            embed.add_field(
                name="Messages Processed",
                value=str(self.monitor.messages_processed)
            )
            
            await ctx.send(embed=embed)
        except Exception as e:
            logging.error(f"Error in health command: {e}")
            await ctx.send("❌ Error fetching health metrics") 