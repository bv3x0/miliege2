import discord
from discord.ext import commands
import logging
import os
from dotenv import load_dotenv
from datetime import datetime
from cogs.grabber import TokenGrabber
from cogs.digest import DigestCog
from trackers import BotMonitor, TokenTracker

# Enhanced logging setup
logging.basicConfig(
    filename='bot.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Load environment variables
load_dotenv()
token = os.getenv('DISCORD_BOT_TOKEN')
daily_digest_channel_id = int(os.getenv('DAILY_DIGEST_CHANNEL_ID'))

# Bot setup
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# Initialize trackers
monitor = BotMonitor()
token_tracker = TokenTracker()

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    logging.info(f'Bot started as {bot.user}')

    # Add cogs
    await bot.add_cog(TokenGrabber(bot, token_tracker, monitor))
    await bot.add_cog(DigestCog(bot, token_tracker, daily_digest_channel_id))

    # Send startup notification
    channel = bot.get_channel(daily_digest_channel_id)
    if channel:
        await channel.send(f"🟢 Bot is online! Version: {datetime.now().strftime('%Y.%m.%d')}")

@bot.command()
async def status(ctx):
    """Check bot status and uptime"""
    uptime = monitor.get_uptime()
    embed = discord.Embed(title="Bot Status", color=discord.Color.green())
    embed.add_field(
        name="Uptime",
        value=f"{uptime.days}d {uptime.seconds // 3600}h {(uptime.seconds // 60) % 60}m"
    )
    embed.add_field(name="Errors", value=str(monitor.errors_since_restart))
    embed.add_field(
        name="Last Message",
        value=f"{(datetime.now() - monitor.last_message_time).seconds // 60}m ago"
    )
    await ctx.send(embed=embed)

if __name__ == "__main__":
    try:
        bot.run(token)
    except Exception as e:
        logging.critical(f"Bot crashed: {e}")
