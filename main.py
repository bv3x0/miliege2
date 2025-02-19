import discord
from discord.ext import commands
import logging
from logging.handlers import RotatingFileHandler
import os
from dotenv import load_dotenv
from datetime import datetime
from cogs.grabber import TokenGrabber
from cogs.digest import DigestCog
from trackers import BotMonitor, TokenTracker
from cogs.health import HealthMonitor

# Enhanced logging setup
logger = logging.getLogger('discord_bot')
logger.setLevel(logging.INFO)
handler = RotatingFileHandler(
    'bot.log',
    maxBytes=1024*1024,  # 1MB
    backupCount=5
)
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)

# Load environment variables
load_dotenv()
token = os.getenv('DISCORD_BOT_TOKEN')
daily_digest_channel_id = os.getenv('DAILY_DIGEST_CHANNEL_ID')

# Validate configuration
if not token:
    raise ValueError("DISCORD_BOT_TOKEN not found in environment variables")
if not daily_digest_channel_id:
    raise ValueError("DAILY_DIGEST_CHANNEL_ID not found in environment variables")
daily_digest_channel_id = int(daily_digest_channel_id)

class DiscordBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.messages = True
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents, help_command=None)
        
        self.monitor = BotMonitor()
        self.token_tracker = TokenTracker()

    async def setup_hook(self):
        # Add cogs
        await self.add_cog(TokenGrabber(self, self.token_tracker, self.monitor))
        await self.add_cog(DigestCog(self, self.token_tracker, daily_digest_channel_id))
        await self.add_cog(HealthMonitor(self, self.monitor))
        logger.info("Cogs loaded successfully")

    async def on_ready(self):
        logger.info(f'Bot started as {self.user}')
        
        channel = self.get_channel(daily_digest_channel_id)
        if channel:
            await channel.send(
                f"🟢 Bot is online! Version: {datetime.now().strftime('%Y.%m.%d')}"
            )
        else:
            logger.error(f"Could not find channel with ID {daily_digest_channel_id}")

    async def on_error(self, event_method, *args, **kwargs):
        logger.exception(f"Error in {event_method}")
        if self.monitor:
            self.monitor.record_error()

    async def on_command_error(self, ctx, error):
        """Handle command-specific errors with appropriate responses"""
        if isinstance(error, commands.CommandNotFound):
            await ctx.send("❌ Command not found. Use `!help` to see available commands.")
        
        elif isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You don't have permission to use this command.")
        
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Missing required argument: {error.param.name}")
        
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"⏳ Please wait {error.retry_after:.1f}s before using this command again.")
        
        else:
            # Log unexpected errors and notify user
            logger.error(f"Command error: {error}", exc_info=error)
            self.monitor.record_error()
            await ctx.send("❌ An unexpected error occurred. The error has been logged.")

@bot.command()
async def status(ctx):
    """Check bot status and uptime"""
    try:
        uptime = bot.monitor.get_uptime()
        embed = discord.Embed(title="Bot Status", color=discord.Color.green())
        embed.add_field(
            name="Uptime",
            value=f"{uptime.days}d {uptime.seconds // 3600}h {(uptime.seconds // 60) % 60}m"
        )
        embed.add_field(name="Errors", value=str(bot.monitor.errors_since_restart))
        
        if bot.monitor.last_message_time:
            time_diff = (datetime.now() - bot.monitor.last_message_time).seconds // 60
            last_message = f"{time_diff}m ago"
        else:
            last_message = "No messages yet"
            
        embed.add_field(name="Last Message", value=last_message)
        await ctx.send(embed=embed)
    except Exception as e:
        logger.error(f"Error in status command: {e}")
        await ctx.send("An error occurred while fetching status")

if __name__ == "__main__":
    bot = DiscordBot()
    try:
        bot.run(token)
    except discord.LoginFailure:
        logger.critical("Failed to login. Check your token.")
    except discord.HTTPException as e:
        logger.critical(f"HTTP Exception: {e}")
    except Exception as e:
        logger.critical(f"Unexpected error: {e}")
    finally:
        logger.info("Bot shutdown")
