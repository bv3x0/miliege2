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
            # Only do detailed logging for Cielo messages
            if message.author.bot and message.author.name == "Cielo":
                logging.info("""
=== Cielo Message Detected ===
Has Embeds: %s
Embed Count: %d
""", bool(message.embeds), len(message.embeds) if message.embeds else 0)
                
                if message.embeds:
                    for embed in message.embeds:
                        for field in embed.fields:
                            # Look for "Token:" within the field value
                            if "Token:" in field.value:
                                logging.info(f"Found Token field: {field.value}")
                                match = re.search(r'Token:\s*`([a-zA-Z0-9]+)`', field.value)
                                if match:
                                    contract_address = match.group(1)
                                    logging.info(f"Processing token: {contract_address}")
                                    await self._process_token(contract_address, message)
                                    return
                else:
                    logging.warning("Cielo message had no embeds")
            else:
                # Basic debug level logging for non-Cielo messages
                logging.debug(f"Message from {message.author.name}")
                    
        except Exception as e:
            logging.error(f"Error in message processing: {e}", exc_info=True)
            self.monitor.record_error()

    async def _process_token(self, contract_address, message):
        try:
            dex_api_url = f"https://api.dexscreener.com/latest/dex/tokens/{contract_address}"
            logging.info(f"Querying Dexscreener API: {dex_api_url}")
            
            async with safe_api_call(self.session, dex_api_url) as dex_data:
                if dex_data and 'pairs' in dex_data and dex_data['pairs']:
                    pair = dex_data['pairs'][0]
                    
                    # Extract data
                    chain = pair.get('chainId', 'Unknown Chain')
                    price_change_24h = pair.get('priceChange', {}).get('h24', 'N/A')
                    market_cap = pair.get('fdv', 'N/A')
                    
                    # Format market cap
                    if isinstance(market_cap, (int, float)):
                        market_cap = format_large_number(market_cap)
                    
                    # Format price change
                    if isinstance(price_change_24h, (int, float)):
                        price_change_24h = format_large_number(price_change_24h) + "%"
                    
                    token_data = {
                        'name': pair.get('baseToken', {}).get('name', 'Unknown'),
                        'symbol': pair.get('baseToken', {}).get('symbol', 'Unknown'),
                        'chain': chain,
                        'market_cap': market_cap,
                        'price_change_24h': price_change_24h,
                        'chart_url': f"https://dexscreener.com/{chain.lower()}/{contract_address}"
                    }
                    
                    # Log the token
                    self.token_tracker.log_token(contract_address, token_data)
                    logging.info(f"Successfully processed token: {token_data['name']} on {chain}")
                else:
                    await message.channel.send("❌ **Error:** No trading pairs found for this token.")
                    
        except Exception as e:
            logging.error(f"Error processing token {contract_address}: {e}", exc_info=True)
            await message.channel.send("❌ **Error:** Failed to process token information.")