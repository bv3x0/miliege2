import discord # type: ignore
from discord.ext import commands
import re
import requests
import logging
import asyncio
from utils import format_large_number, get_age_string, safe_api_call
from aiohttp import ClientSession

class TokenGrabber(commands.Cog):
    def __init__(self, bot, token_tracker, monitor):
        self.bot = bot
        self.token_tracker = token_tracker
        self.monitor = monitor
        self.session = None  # Initialize as None
        # Create the session when the cog is added to the bot
        self.bot.loop.create_task(self.initialize_session())

    async def initialize_session(self):
        """Initialize the aiohttp session"""
        self.session = ClientSession()
        logging.info("TokenGrabber session initialized")

    async def cog_unload(self):
        """Cleanup when the cog is unloaded"""
        if self.session:
            await self.session.close()
            logging.info("TokenGrabber session closed")

    @commands.Cog.listener()
    async def on_message(self, message):
        try:
            self.monitor.record_message()
            
            # Log all messages for debugging
            logging.info(f"Message received from {message.author.name}")
            logging.info(f"Content: {message.content[:100]}")
            logging.info(f"Has embeds: {bool(message.embeds)}")
            
            if message.author.bot:
                if message.author.name == "Cielo":
                    logging.info("Cielo message detected")
                    
                    # Check for embedded message
                    if message.embeds:
                        embed = message.embeds[0]  # Cielo uses a single embed
                        
                        # Log embed fields for debugging
                        logging.info("Embed fields:")
                        for field in embed.fields:
                            logging.info(f"Field {field.name}: {field.value}")
                        
                        # Look for the Token field specifically
                        token_field = next(
                            (field for field in embed.fields 
                             if field.name == "Token"),
                            None
                        )
                        
                        if token_field:
                            token_address = token_field.value.strip()
                            logging.info(f"Found token address: {token_address}")
                            await self._process_token(token_address, message)
                        else:
                            logging.warning("No token field found in Cielo embed")
                    else:
                        logging.warning("Cielo message had no embeds")
                else:
                    logging.debug(f"Ignoring message from bot: {message.author.name}")
                        
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
        try:
            # Extract chain from the embed
            chain_field = next(
                (field for field in message.embeds[0].fields 
                 if field.name == "Chain"),
                None
            )
            
            if not chain_field:
                logging.error("No Chain field found in embed")
                return
                
            # Format chain name for URL (lowercase, no spaces)
            dex_chain = chain_field.value.lower().strip()
            
            # Create the chart URL with the chain
            chart_url = f"https://dexscreener.com/{dex_chain}/{contract_address}"
            
            # Extract maker address if present
            if "maker=" in message.content:
                maker_match = re.search(r'maker=([a-zA-Z0-9]+)', message.content, re.IGNORECASE)
                if maker_match:
                    maker_address = maker_match.group(1)
                    chart_url += f"?maker={maker_address}"
            
            logging.info(f"Processing token on {dex_chain} chain: {contract_address}")
            logging.info(f"Chart URL: {chart_url}")
            
            dex_api_url = f"https://api.dexscreener.com/latest/dex/tokens/{contract_address}"
            
            async with safe_api_call(self.session, dex_api_url) as dex_data:
                if dex_data:
                    dex_data['chain'] = chain_field.value
                    dex_data['chart_url'] = chart_url
                    await self._handle_dex_data(dex_data, contract_address, message)
                else:
                    await message.channel.send("❌ **Error:** Unable to fetch token data from API.")
                    
        except Exception as e:
            logging.error(f"Error processing token: {e}", exc_info=True)
            await message.channel.send("❌ **Error:** Failed to process token information.")

    async def _handle_dex_data(self, dex_data, contract_address, message):
        # Implementation of token data processing and message sending
        # This would be the same logic as in your current implementation
        pass
        pass