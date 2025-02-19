import discord
from discord.ext import commands
import re
import requests
import logging
import asyncio  # Add this import
from utils import format_large_number, get_age_string, safe_api_call
from aiohttp import ClientSession

class TokenGrabber(commands.Cog):
    def __init__(self, bot, token_tracker, monitor):
        self.bot = bot
        self.token_tracker = token_tracker
        self.monitor = monitor
        self.session: ClientSession = None

    async def setup_hook(self):
        self.session = ClientSession()

    async def cog_unload(self):
        if self.session:
            await self.session.close()

    @commands.Cog.listener()
    async def on_message(self, message):
        try:
            self.monitor.record_message()
            
            # Add specific Cielo debugging
            logging.info(f"Message from: {message.author.name} (ID: {message.author.id})")
            if message.author.bot:
                logging.info(f"Bot properties - Name: {message.author.name}, Display Name: {message.author.display_name}")
                
                if message.author.name == "Cielo":
                    logging.info("Cielo message detected")
                    logging.info(f"Has embeds: {bool(message.embeds)}")
                    if message.embeds:
                        logging.info(f"Number of embeds: {len(message.embeds)}")
                        await self._process_embeds(message)
                else:
                    logging.info(f"Not Cielo - got {message.author.name} instead")
                    
        except Exception as e:
            logging.error(f"Error in message processing: {e}", exc_info=True)
            self.monitor.record_error()

    async def _process_embeds(self, message):
        for embed in message.embeds:
            for field in embed.fields:
                if "Token:" in field.value:
                    match = re.search(r'Token:\s*`([a-zA-Z0-9]+)`', field.value)
                    if match:
                        await self._process_token(match.group(1), message)

    async def _process_token(self, contract_address, message):
        dex_api_url = f"https://api.dexscreener.com/latest/dex/tokens/{contract_address}"
        
        async with safe_api_call(self.session, dex_api_url) as dex_data:
            if dex_data:
                await self._handle_dex_data(dex_data, contract_address, message)
            else:
                await message.channel.send("❌ **Error:** Unable to fetch token data from API.")

    async def _handle_dex_data(self, dex_data, contract_address, message):
        # Implementation of token data processing and message sending
        # This would be the same logic as in your current implementation
        pass