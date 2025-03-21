import discord
from discord.ext import commands
import logging
from logging.handlers import RotatingFileHandler
import os
from dotenv import load_dotenv
from datetime import datetime
import asyncio
from cogs.grabbers.cielo_grabber import CieloGrabber
from cogs.features.digest import DigestCog, DexScreenerDigestCog
from cogs.core.trackers import BotMonitor, TokenTracker
from cogs.core.health import HealthMonitor
from functools import wraps
from cogs.features.fun import FunCommands
from cogs.grabbers.rick_grabber import RickGrabber
from cogs.core.admin import AdminCommands
import aiohttp
from db.engine import Database
from db.models import Token
from cogs.grabbers.hl_grabber import HyperliquidWalletGrabber, TrackedWallet
from discord import app_commands
from cogs.utils.config import settings
import json
from cogs.features.summary import TradeSummaryCog

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
hyperliquid_alerts_channel_id = os.getenv('HYPERLIQUID_ALERTS_CHANNEL_ID')
if hyperliquid_alerts_channel_id:
    hyperliquid_alerts_channel_id = int(hyperliquid_alerts_channel_id)

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
        intents.voice_states = False  # Disable voice states
        logging.debug(f"Intents configured: {intents.value}")
        super().__init__(command_prefix='!', intents=intents, help_command=None)
        
        # Initialize database
        self.db = Database(database_url)
        
        # Create tables if they don't exist
        self.db.create_tables()
        
        # Initialize session factory and create a session
        self.Session = self.db.session_factory
        self.db_session = self.Session()
        
        self.monitor = BotMonitor()
        self.token_tracker = TokenTracker(session_factory=self.db_session)
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
        
        # Create DigestCog first to share reference
        digest_cog = DigestCog(self, self.token_tracker, daily_digest_channel_id, self.monitor)
        await self.add_cog(digest_cog)
        
        # Create TradeSummaryCog
        summary_cog = TradeSummaryCog(self, daily_digest_channel_id, self.monitor)
        await self.add_cog(summary_cog)
        
        # DexScreener feature is currently disabled due to API issues
        # Uncomment the lines below to enable it when API issues are resolved
        # dex_digest_cog = DexScreenerDigestCog(self, daily_digest_channel_id, self.monitor)
        # await self.add_cog(dex_digest_cog)
        logging.info("DexScreener feature is currently disabled")
        
        # Load channel IDs from config
        config_path = "config.json"
        cielo_input_channel_id = None
        cielo_output_channel_id = None

        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    config = json.load(f)
                
                # Load channel IDs from config
                if "CIELO_INPUT_CHANNEL_ID" in config:
                    cielo_input_channel_id = config["CIELO_INPUT_CHANNEL_ID"]
                    logging.info(f"Loaded Cielo input channel from config: {cielo_input_channel_id}")
                
                if "OUTPUT_CHANNEL_ID" in config:
                    cielo_output_channel_id = config["OUTPUT_CHANNEL_ID"]
                    logging.info(f"Loaded output channel from config: {cielo_output_channel_id}")
            except Exception as e:
                logging.error(f"Error loading config: {e}")

        # Fall back to environment variables if not in config
        if cielo_input_channel_id is None and hasattr(settings, 'CIELO_OUTPUT_CHANNEL_ID') and settings.CIELO_OUTPUT_CHANNEL_ID:
            cielo_input_channel_id = settings.CIELO_OUTPUT_CHANNEL_ID
            logging.info(f"Using Cielo input channel from env: {cielo_input_channel_id}")

        if cielo_output_channel_id is None and hasattr(settings, 'DAILY_DIGEST_CHANNEL_ID') and settings.DAILY_DIGEST_CHANNEL_ID:
            cielo_output_channel_id = daily_digest_channel_id
            logging.info(f"Using output channel from env: {cielo_output_channel_id}")

        await self.add_cog(CieloGrabber(
            self, 
            self.token_tracker, 
            self.monitor, 
            self.session, 
            digest_cog=digest_cog,
            summary_cog=summary_cog,
            input_channel_id=cielo_input_channel_id,
            output_channel_id=cielo_output_channel_id
        ))
        await self.add_cog(RickGrabber(self, self.token_tracker, self.monitor, self.session, digest_cog))
        await self.add_cog(HealthMonitor(self, self.monitor))
        await self.add_cog(FunCommands(self))
        await self.add_cog(HyperliquidWalletGrabber(self, self.token_tracker, self.monitor, self.session, digest_cog, daily_digest_channel_id))
        await self.add_cog(AdminCommands(self))
        logger.info("Hyperliquid Wallet Grabber loaded successfully")
        logger.info("Cogs loaded successfully")

        # Sync slash commands with Discord
        try:
            logger.info("Syncing slash commands with Discord...")
            await self.tree.sync()
            logger.info("Successfully synced slash commands")
        except Exception as e:
            logger.error(f"Failed to sync slash commands: {e}")

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
            if hasattr(self, 'Session'):
                try:
                    db_token_count = self.Session().query(Token).count()
                    embed.add_field(name="Database Tokens", value=str(db_token_count))
                except Exception as e:
                    logger.error(f"Error getting database stats: {e}")
            
            await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f"Error in status command: {e}")
            await ctx.send("❌ **Error:** Unable to fetch bot status.")

    @commands.command(name="help")
    async def help_command(self, ctx, command_name=None):
        """Display help information for commands"""
        if command_name:
            # Help for a specific command
            command = self.get_command(command_name)
            if command:
                embed = discord.Embed(
                    title=f"Help: {command.name}",
                    description=command.help or command.description or "No description available.",
                    color=0x5b594f
                )
                
                # Add usage info if available
                if hasattr(command, 'brief'):
                    embed.add_field(name="Brief", value=command.brief, inline=False)
                
                # Add syntax
                params = []
                for param in command.clean_params.values():
                    if param.default == param.empty:
                        params.append(f"<{param.name}>")
                    else:
                        params.append(f"[{param.name}]")
                
                syntax = f"!{command.name} {' '.join(params)}"
                embed.add_field(name="Syntax", value=f"`{syntax}`", inline=False)
                
                await ctx.send(embed=embed)
            else:
                await ctx.send(f"Command '{command_name}' not found.")
        else:
            # General help - list all commands by category
            embed = discord.Embed(
                title="Bot Commands",
                description="Here are the available commands. Use `!help <command>` for more details on a specific command.",
                color=0x5b594f
            )
            
            # Group commands by cog
            cog_commands = {}
            for command in self.commands:
                cog_name = command.cog_name or "No Category"
                if cog_name not in cog_commands:
                    cog_commands[cog_name] = []
                cog_commands[cog_name].append(command)
            
            # Add fields for each category
            for cog_name, commands_list in cog_commands.items():
                # Skip hidden commands
                visible_commands = [cmd for cmd in commands_list if not cmd.hidden]
                if not visible_commands:
                    continue
                    
                # Format command list
                command_text = "\n".join([
                    f"`!{cmd.name}` - {cmd.brief or 'No description'}"
                    for cmd in visible_commands
                ])
                
                embed.add_field(name=cog_name, value=command_text, inline=False)
            
            # Add a special section for Hyperliquid wallet commands
            hyperliquid_commands = [
                "`!add_wallet <address> [name]` - Add a wallet to track on Hyperliquid",
                "`!remove_wallet <address>` - Remove a wallet from tracking",
                "`!list_wallets` - List all tracked Hyperliquid wallets"
            ]
            embed.add_field(name="Hyperliquid Wallet Commands", value="\n".join(hyperliquid_commands), inline=False)
            
            # Dexscreener commands temporarily disabled
            # dexscreener_commands = [
            #     "`!dex` - Generate a Dexscreener Digest with trending tokens"
            # ]
            # embed.add_field(name="Dexscreener Commands", value="\n".join(dexscreener_commands), inline=False)
            
            await ctx.send(embed=embed)

    async def close(self):
        """Cleanup when the bot is shutting down"""
        try:
            # Close the database session
            if hasattr(self, 'db_session'):
                self.db_session.close()
                logging.info("Closed database session")
            
            # Close the database connection
            if hasattr(self, 'db'):
                self.db.close()
                logging.info("Closed database connection")
            
            # Close the aiohttp session
            if self.session:
                await self.session.close()
                logging.info("Closed aiohttp session")
            
            # Call parent's close method
            await super().close()
            
        except Exception as e:
            logging.error(f"Error during shutdown: {e}")

    @app_commands.command()
    @app_commands.checks.has_role("Admin")  # Or use custom checks
    @app_commands.checks.cooldown(1, 60.0)  # Once per minute
    async def addwallet(self, interaction: discord.Interaction, wallet: str):
        """Add a wallet to track on Hyperliquid"""
        try:
            # Get the HyperliquidWalletGrabber cog
            wallet_grabber = self.get_cog('HyperliquidWalletGrabber')
            if not wallet_grabber:
                await interaction.response.send_message("❌ Wallet tracking system not available.", ephemeral=True)
                return

            # Add the wallet
            tracked_wallet = await wallet_grabber.add_wallet(wallet)
            if tracked_wallet:
                await interaction.response.send_message(f"✅ Successfully added wallet: `{wallet}`", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Failed to add wallet. Please check the address and try again.", ephemeral=True)
        except Exception as e:
            logger.error(f"Error adding wallet: {e}")
            await interaction.response.send_message("❌ An error occurred while adding the wallet.", ephemeral=True)

    @app_commands.command()
    @app_commands.checks.has_role("Admin")  # Or use custom checks
    @app_commands.checks.cooldown(1, 60.0)  # Once per minute
    async def removewallet(self, interaction: discord.Interaction, wallet: str):
        @wallet.autocomplete
        async def wallet_autocomplete(interaction: discord.Interaction, current: str):
            # Return list of matching wallets
            return [
                app_commands.Choice(name=w.name, value=w.address)
                for w in self.wallets if current.lower() in w.address.lower()
            ][:25]  # Discord limits to 25 choices

async def main():
    bot = DiscordBot()
    try:
        await bot.start(token)
    except KeyboardInterrupt:
        logging.info("Received keyboard interrupt, shutting down...")
    finally:
        await bot.close()
        logging.info("Bot shutdown complete")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Bot stopped by user")