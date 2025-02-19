import discord
from discord.ext import commands
from datetime import datetime

class HealthMonitor(commands.Cog):
    def __init__(self, bot, monitor):
        self.bot = bot
        self.monitor = monitor

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.author.bot:
            self.monitor.record_message()

    @commands.command(name="health")
    async def check_health(self, ctx):
        """Check the bot's health metrics"""
        uptime = self.monitor.get_uptime()
        embed = discord.Embed(
            title="Bot Health Status",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        
        embed.add_field(
            name="Uptime",
            value=f"{uptime.days}d {uptime.seconds // 3600}h {(uptime.seconds // 60) % 60}m"
        )
        embed.add_field(
            name="Errors",
            value=f"{self.monitor.errors_since_restart} since last restart"
        )
        embed.add_field(
            name="Messages Processed",
            value=str(self.monitor.messages_processed)
        )
        
        await ctx.send(embed=embed) 