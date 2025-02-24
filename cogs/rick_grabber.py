import discord
from discord.ext import commands
import logging
import re
from utils import format_large_number, get_age_string, safe_api_call
from aiohttp import ClientSession
import asyncio

class RickGrabber(commands.Cog):
    def __init__(self, bot, token_tracker, monitor):
        self.bot = bot
        self.token_tracker = token_tracker
        self.monitor = monitor
        self.session = None
        self.last_api_call = None
        self.rate_limit = 1.0  # seconds between API calls
        self.bot.loop.create_task(self.initialize_session())

    async def initialize_session(self):
        self.session = ClientSession()
        logging.info("RickGrabber session initialized")

    async def cog_unload(self):
        if self.session:
            await self.session.close()
            logging.info("RickGrabber session closed")

    @commands.Cog.listener()
    async def on_message(self, message):
        try:
            # Only process Rick bot messages
            if message.author.bot and message.author.name == "Rick":
                logging.info("""
=== Rick Message Detected ===
Content: %s
Has Embeds: %s
Embed Count: %d
""", message.content, bool(message.embeds), len(message.embeds) if message.embeds else 0)

                # Extract token info from message content
                content_match = re.search(r'💊\s+(\w+)\s+\[([0-9.]+[KMB]?)/', message.content)
                if content_match:
                    token_name = content_match.group(1)
                    initial_mcap = content_match.group(2)
                    
                    # Get contract address from embed
                    if message.embeds:
                        for embed in message.embeds:
                            if embed.description:
                                # Find contract address (plain text in description)
                                contract_match = re.search(r'([A-Za-z0-9]{32,})', embed.description)
                                if contract_match:
                                    contract_address = contract_match.group(1)
                                    
                                    # Get the user who triggered the Rick alert
                                    trigger_user = None
                                    if message.reference and message.reference.resolved:
                                        trigger_user = message.reference.resolved.author.name
                                    
                                    # Extract chart URL from DEX link
                                    chart_url = None
                                    for field in embed.fields:
                                        if field.name == "Chart":
                                            chart_links = re.findall(r'\[DEX\]\((.*?)\)', field.value)
                                            if chart_links:
                                                chart_url = chart_links[0]
                                                break
                                    
                                    logging.info(f"Processing Rick token: {token_name} ({contract_address})")
                                    await self._process_token(
                                        contract_address, 
                                        message, 
                                        trigger_user,
                                        token_name,
                                        initial_mcap,
                                        chart_url
                                    )
                                    return

        except Exception as e:
            logging.error(f"Error in Rick message processing: {e}", exc_info=True)
            self.monitor.record_error()

    async def _process_token(self, contract_address, message, trigger_user, token_name, initial_mcap, chart_url):
        try:
            dex_api_url = f"https://api.dexscreener.com/latest/dex/tokens/{contract_address}"
            async with safe_api_call(self.session, dex_api_url) as dex_data:
                if not dex_data or 'pairs' not in dex_data or not dex_data['pairs']:
                    logging.warning(f"No valid data returned for token {token_name} ({contract_address})")
                    return
                
                # Format initial market cap
                initial_mcap_formatted = initial_mcap
                if not initial_mcap.startswith('$'):
                    initial_mcap_formatted = f"${initial_mcap}"
                
                token_data = {
                    'name': token_name,
                    'chart_url': chart_url,
                    'initial_market_cap_formatted': initial_mcap_formatted,
                }
                
                # Log token with 'rick' source and trigger user
                self.token_tracker.log_token(contract_address, token_data, 'rick', trigger_user)
                
        except Exception as e:
            logging.error(f"Error processing Rick token {contract_address}: {e}", exc_info=True) 

    @commands.Cog.listener()
    async def on_ready(self):
        logging.info("RickGrabber is ready and listening for messages") 