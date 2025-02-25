import discord
from discord.ext import commands
import logging
import re
from utils import format_large_number, get_age_string, safe_api_call
import asyncio

class RickGrabber(commands.Cog):
    def __init__(self, bot, token_tracker, monitor, session, digest_cog=None):
        self.bot = bot
        self.token_tracker = token_tracker
        self.monitor = monitor
        self.session = session
        self.digest_cog = digest_cog
        self.last_api_call = None
        self.rate_limit = 1.0  # seconds between API calls

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
                if not content_match:  # Try alternative format
                    content_match = re.search(r'\*\*([^[]+)\s*\[([0-9.]+[KMB]?)', message.content)
                if not content_match:  # Try format with markdown link
                    content_match = re.search(r'\*\*\[([^\]]+)\](?:\([^)]+\))?\s*\[([0-9.]+[KMB]?)', message.content)
                
                if content_match:
                    token_name = content_match.group(1).strip()
                    # Clean up token name - remove markdown links if present
                    token_name = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', token_name)
                    initial_mcap = content_match.group(2).strip()
                    
                    logging.info(f"Extracted token info - Name: {token_name}, Initial MCap: {initial_mcap}")
                    
                    # Get contract address from embed
                    if message.embeds:
                        for embed in message.embeds:
                            if embed.description:
                                # Log the full embed description for debugging
                                logging.info(f"Embed description: {embed.description}")
                                
                                # Find contract address using multiple patterns
                                contract_address = None
                                
                                # Pattern 1: Standalone line in backticks
                                contract_match = re.search(r'`([A-Za-z0-9]{32,})`\n(?:(?:\[|\|)[A-Z]+(?:\]|\|))', embed.description)
                                if contract_match:
                                    contract_address = contract_match.group(1)
                                
                                # Pattern 2: Plain text contract address
                                if not contract_address:
                                    contract_match = re.search(r'\n([A-Za-z0-9]{32,})\n', embed.description)
                                    if contract_match:
                                        contract_address = contract_match.group(1)
                                
                                # Pattern 3: Extract from pump.fun URL in message content
                                if not contract_address:
                                    pump_match = re.search(r'pump\.fun/([A-Za-z0-9]{32,})', message.content)
                                    if pump_match:
                                        contract_address = pump_match.group(1)
                                
                                if contract_address:
                                    logging.info(f"Found contract address: {contract_address}")
                                    
                                    # Get the user who triggered the Rick alert
                                    trigger_user = None
                                    if message.reference and message.reference.resolved:
                                        trigger_user = message.reference.resolved.author.display_name
                                        logging.info(f"Found trigger user display name: {trigger_user}")
                                    
                                    # Extract chart URL from DEX link
                                    chart_url = None
                                    for field in embed.fields:
                                        if field.name == "Chart":
                                            # Try both DEX link formats
                                            chart_links = re.findall(r'\[DEX\]\((.*?)\)', field.value)
                                            if not chart_links:
                                                # Try alternative format with dexscreener.com
                                                chart_links = re.findall(r'dexscreener\.com/[^)\s]+', field.value)
                                            if chart_links:
                                                chart_url = chart_links[0]
                                                if not chart_url.startswith('http'):
                                                    chart_url = f"https://{chart_url}"
                                                logging.info(f"Found chart URL: {chart_url}")
                                                break
                                    
                                    if not chart_url:
                                        # Fallback: Create dexscreener URL from contract
                                        chart_url = f"https://dexscreener.com/search/{contract_address}"
                                        logging.info(f"Using fallback chart URL: {chart_url}")
                                    
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
                                else:
                                    logging.warning("No contract address found in embed description")
                            else:
                                logging.warning("Embed has no description")

        except Exception as e:
            logging.error(f"Error in Rick message processing: {e}", exc_info=True)
            self.monitor.record_error()

    async def _process_token(self, contract_address, message, trigger_user, token_name, initial_mcap, chart_url):
        """Process detailed token information and store in tracker"""
        try:
            # Extra token data from Rick's embed
            token_data = {
                'name': token_name,
                'chart_url': chart_url,
                'initial_market_cap': initial_mcap,
                'initial_market_cap_formatted': f"${format_large_number(initial_mcap)}",
                'message_id': message.id,
                'channel_id': message.channel.id,
                'guild_id': message.guild.id if message.guild else None
            }
            
            # Attempt to get chain information if available
            chain_match = re.search(r'https://(?:www\.)?dexscreener\.com/([^/]+)/', chart_url)
            if chain_match:
                token_data['chain'] = chain_match.group(1)
            
            # Log token in both trackers
            self.token_tracker.log_token(contract_address, token_data, 'rick', trigger_user)
            
            # Also log to hour-specific tracker in DigestCog if available
            if self.digest_cog:
                self.digest_cog.process_new_token(contract_address, token_data)
                
            return True
            
        except Exception as e:
            logging.error(f"Error processing token {contract_address}: {e}")
            return False

    @commands.Cog.listener()
    async def on_ready(self):
        logging.info("RickGrabber is ready and listening for messages") 