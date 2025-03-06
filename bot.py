import discord
from discord.ext import commands
from discord import app_commands
import os
import logging

class Bot(commands.Bot):
    def __init__(self):
        # Set both traditional command prefix and enable slash commands
        super().__init__(
            command_prefix='!',
            intents=discord.Intents.all(),
            help_command=None
        )
        
    async def setup_hook(self):
        # This is called when the bot starts up
        # We'll sync slash commands here
        await self.tree.sync()
        
    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('------')

# When initializing the CieloGrabber cog
cielo_output_channel_id = os.getenv("CIELO_OUTPUT_CHANNEL_ID")
if cielo_output_channel_id:
    try:
        cielo_output_channel_id = int(cielo_output_channel_id)
    except ValueError:
        logging.error("Invalid CIELO_OUTPUT_CHANNEL_ID in .env file")
        cielo_output_channel_id = None

cielo_grabber = CieloGrabber(
    bot, 
    token_tracker, 
    monitor, 
    session, 
    digest_cog, 
    os.getenv('CIELO_OUTPUT_CHANNEL_ID'),  # This is the input channel where Cielo posts
    os.getenv('DAILY_DIGEST_CHANNEL_ID')   # This is the output channel where you want the processed messages
)
