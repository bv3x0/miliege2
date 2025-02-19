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
from functools import wraps

# Enhanced logging setup
def setup_logging():
    # Clear any existing handlers
    logging.getLogger().handlers = []
    
    # Create logger and set to DEBUG level to capture everything
    logger = logging.getLogger('discord_bot')
    logger.setLevel(logging.DEBUG)
    
    # Remove any existing handlers
    logger.handlers = []
    
    # Create file handler
    handler = RotatingFileHandler(
        'bot.log',
        maxBytes=1024*1024,  # 1MB
        backupCount=5,
        mode='a'  # Append mode
    )
    
    # Create formatter with more detail
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
    )
    handler.setFormatter(formatter)
    handler.setLevel(logging.DEBUG)
    
    # Add handler
    logger.addHandler(handler)
    
    # Configure discord.py's logger to use our handler
    discord_logger = logging.getLogger('discord')
    discord_logger.setLevel(logging.INFO)
    discord_logger.addHandler(handler)
    
    # Prevent logs from propagating to the root logger
    logger.propagate = False
    discord_logger.propagate = False
    
    return logger

# Initialize logger
logger = setup_logging()

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

def rate_limit(seconds: int = 60):
    def decorator(func):
        cooldown = commands.Cooldown(1, seconds)
        @wraps(func)
        async def wrapper(*args, **kwargs):
            if cooldown.update_rate_limit():
                raise commands.CommandOnCooldown(cooldown, seconds)
            return await func(*args, **kwargs)
        return wrapper
    return decorator

class DiscordBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        logging.debug(f"Intents configured: {intents.value}")
        super().__init__(command_prefix='!', intents=intents, help_command=None)
        
        self.monitor = BotMonitor()
        self.token_tracker = TokenTracker()

    async def on_message(self, message):
        # Enhanced logging for message debugging
        log_data = {
            'author': message.author.name,
            'content': message.content,
            'has_embeds': bool(message.embeds),
            'embed_count': len(message.embeds) if message.embeds else 0
        }
        
        logging.info(f"Message Details: {log_data}")
        
        # If there are embeds, log their details
        if message.embeds:
            for idx, embed in enumerate(message.embeds):
                logging.info(f"Embed {idx} fields: {[field.name for field in embed.fields]}")
        
        await self.process_commands(message)

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
            await channel.send("<:awesome:1321865532307275877>")
        else:
            logger.error(f"Could not find channel with ID {daily_digest_channel_id}")

    async def on_error(self, event_method, *args, **kwargs):
        logger.exception(f"Error in {event_method}")
        if self.monitor:
            self.monitor.record_error()

    async def on_command_error(self, ctx, error):
        """Handle command-specific errors with appropriate responses"""
        if isinstance(error, commands.CommandNotFound):
            await ctx.send("<:ermh:1151138802404954143>")
        
        elif isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ **Permission Denied:** You don't have permission to use this command.")
        
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ **Missing Argument:** {error.param.name} is required.")
        
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"⏳ **Rate Limited:** Please wait {error.retry_after:.1f}s before trying again.")
        
        else:
            # Log unexpected errors and notify user
            logger.error(f"Command error: {error}", exc_info=error)
            self.monitor.record_error()
            await ctx.send("❌ **System Error:** An unexpected error occurred and has been logged.")

    @commands.command()
    async def status(self, ctx):
        """Check bot status and uptime"""
        try:
            uptime = self.monitor.get_uptime()
            embed = discord.Embed(title="Bot Status", color=discord.Color.green())
            embed.add_field(
                name="Uptime",
                value=f"{uptime.days}d {uptime.seconds // 3600}h {(uptime.seconds // 60) % 60}m"
            )
            embed.add_field(name="Errors", value=str(self.monitor.errors_since_restart))
            
            if self.monitor.last_message_time:
                time_diff = (datetime.now() - self.monitor.last_message_time).seconds // 60
                last_message = f"{time_diff}m ago"
            else:
                last_message = "No messages yet"
                
            embed.add_field(name="Last Message", value=last_message)
            await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f"Error in status command: {e}")
            await ctx.send("❌ **Error:** Unable to fetch bot status.")

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
        # Remove duplicate error logging and finally block