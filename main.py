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
from cogs.fun import FunCommands
from cogs.rick_grabber import RickGrabber
from cogs.analytics import Analytics
import aiohttp
from db.engine import Database
from db.models import Token

# Enhanced logging setup
def setup_logging():
    # Create logger and set to DEBUG level to capture everything
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    
    # Create file handler - captures everything (DEBUG and up)
    handler = RotatingFileHandler(
        'bot.log',
        maxBytes=1024*1024,
        backupCount=5,
        mode='a'
    )
    handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
    ))
    handler.setLevel(logging.DEBUG)  # Capture all logs in file
    
    # Create console handler - only show WARNING and above
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'  # Simpler format for console
    ))
    console_handler.setLevel(logging.WARNING)  # Only show warnings and errors in console
    
    # Clear any existing handlers
    logger.handlers = []
    
    # Add handlers
    logger.addHandler(handler)
    logger.addHandler(console_handler)
    
    # Configure discord.py's logger
    discord_logger = logging.getLogger('discord')
    discord_logger.setLevel(logging.INFO)
    
    return logger

# Initialize logger
logger = setup_logging()

# Load environment variables
load_dotenv()
token = os.getenv('DISCORD_BOT_TOKEN')
daily_digest_channel_id = os.getenv('DAILY_DIGEST_CHANNEL_ID')
database_url = os.getenv('DATABASE_URL')  # Optional, will use default if not set

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
        
        # Initialize database
        self.db = Database(database_url)
        self.db.create_tables()
        
        # Create a session for the token tracker
        self.db_session = self.db.get_session()
        
        self.monitor = BotMonitor()
        self.token_tracker = TokenTracker(db_session=self.db_session)
        self.session = None  # Will be initialized in setup_hook

    async def on_message(self, message):
        if message.author.name == "Cielo":
            # Detailed logging for Cielo
            log_data = {
                'author': message.author.name,
                'content': message.content,
                'has_embeds': bool(message.embeds),
                'embed_count': len(message.embeds) if message.embeds else 0
            }
            logging.info(f"Message Details: {log_data}")
            
            if message.embeds:
                for idx, embed in enumerate(message.embeds):
                    logging.info(f"Embed {idx} fields: {[field.name for field in embed.fields]}")
        else:
            # Truncated logging for other messages
            logging.debug(f"Message: {message.author.name}: {message.content[:10]}...")
        
        await self.process_commands(message)

    async def setup_hook(self):
        # Create a shared aiohttp session
        self.session = aiohttp.ClientSession()
        logger.info("Created shared aiohttp session")
        
        # Add cogs with shared session
        await self.add_cog(TokenGrabber(self, self.token_tracker, self.monitor, self.session))
        await self.add_cog(RickGrabber(self, self.token_tracker, self.monitor, self.session))
        await self.add_cog(DigestCog(self, self.token_tracker, daily_digest_channel_id))
        await self.add_cog(HealthMonitor(self, self.monitor))
        await self.add_cog(FunCommands(self))
        await self.add_cog(Analytics(self))
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
            embed = discord.Embed(title="Bot Status", color=0x5b594f)
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
            
            # Add token tracking stats
            token_count = len(self.token_tracker.tokens)
            embed.add_field(name="Tracked Tokens", value=str(token_count))
            
            # Add database stats if available
            if hasattr(self, 'db_session'):
                try:
                    db_token_count = self.db_session.query(Token).count()
                    embed.add_field(name="Database Tokens", value=str(db_token_count))
                except Exception as e:
                    logger.error(f"Error getting database stats: {e}")
            
            await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f"Error in status command: {e}")
            await ctx.send("❌ **Error:** Unable to fetch bot status.")

    async def close(self):
        # Close the database connection
        if hasattr(self, 'db'):
            self.db.close()
            logger.info("Closed database connection")
            
        # Close the shared session when the bot shuts down
        if self.session:
            await self.session.close()
            logger.info("Closed shared aiohttp session")
            
        await super().close()

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