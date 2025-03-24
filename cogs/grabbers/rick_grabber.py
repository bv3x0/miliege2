import discord
from discord.ext import commands
import logging
import re
from cogs.utils import (
    format_large_number,
    format_age as get_age_string,
    UI,
    safe_api_call,
    DexScreenerAPI,
    Colors
)
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
                                    dex_link_pattern = r'\[DEX\]\((https?://(?:www\.)?dexscreener\.com/[^)]+)\)'
                                    
                                    # First check in the embed description for DEX link
                                    if embed.description:
                                        dex_matches = re.search(dex_link_pattern, embed.description)
                                        if dex_matches:
                                            chart_url = dex_matches.group(1)
                                            logging.info(f"Found chart URL in description: {chart_url}")
                                    
                                    # If not found in description, check fields
                                    if not chart_url:
                                        for field in embed.fields:
                                            if field.name == "Chart":
                                                # Try both DEX link formats
                                                dex_matches = re.search(dex_link_pattern, field.value)
                                                if dex_matches:
                                                    chart_url = dex_matches.group(1)
                                                    logging.info(f"Found chart URL in Chart field: {chart_url}")
                                                    break
                                                
                                                # Try alternative format with dexscreener.com
                                                alt_matches = re.search(r'dexscreener\.com/([^/]+)/([^)\s]+)', field.value)
                                                if alt_matches:
                                                    chain = alt_matches.group(1)
                                                    pair = alt_matches.group(2)
                                                    chart_url = f"https://dexscreener.com/{chain}/{pair}"
                                                    logging.info(f"Found chart URL in Chart field (alt format): {chart_url}")
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
            # Convert initial_mcap to a numeric value if it's a string with K, M, B suffix
            initial_mcap_value = None
            try:
                # Parse the market cap string (e.g., "2.1M")
                if isinstance(initial_mcap, str):
                    clean_mcap = initial_mcap.replace('$', '')
                    if 'M' in clean_mcap or 'm' in clean_mcap:
                        clean_mcap = clean_mcap.replace('M', '').replace('m', '')
                        initial_mcap_value = float(clean_mcap) * 1000000
                    elif 'K' in clean_mcap or 'k' in clean_mcap:
                        clean_mcap = clean_mcap.replace('K', '').replace('k', '')
                        initial_mcap_value = float(clean_mcap) * 1000
                    elif 'B' in clean_mcap or 'b' in clean_mcap:
                        clean_mcap = clean_mcap.replace('B', '').replace('b', '')
                        initial_mcap_value = float(clean_mcap) * 1000000000
                    else:
                        initial_mcap_value = float(clean_mcap)
                else:
                    initial_mcap_value = float(initial_mcap)
                
                # Format the initial market cap
                formatted_mcap = f"${format_large_number(initial_mcap_value)}"
            except (ValueError, TypeError) as e:
                logging.warning(f"Could not parse market cap value '{initial_mcap}': {e}")
                initial_mcap_value = None
                formatted_mcap = f"${initial_mcap}" if not initial_mcap.startswith('$') else initial_mcap
            
            # Extra token data from Rick's embed
            token_data = {
                'name': token_name,
                'chart_url': chart_url,
                'initial_market_cap': initial_mcap_value,
                'initial_market_cap_formatted': formatted_mcap,
                'message_id': str(message.id),
                'channel_id': str(message.channel.id),
                'guild_id': str(message.guild.id) if message.guild else None,
                'user': trigger_user,
                'source': 'rick',
                'chain': chain
            }
            
            # Attempt to get chain information if available
            chain = "unknown"
            chain_match = re.search(r'https://(?:www\.)?dexscreener\.com/([^/]+)/', chart_url)
            if chain_match:
                chain = chain_match.group(1)
                logging.info(f"Extracted chain from chart URL: {chain}")
            
            # If we couldn't extract from URL or it's "search", try to extract from embed description
            if (chain == "unknown" or chain == "search") and message.embeds and message.embeds[0].description:
                # Look for chain indicators in the description
                desc = message.embeds[0].description
                
                # Look for DEX link in description which contains the chain
                dex_match = re.search(r'dexscreener\.com/([^/]+)/([^)\s]+)', desc)
                if dex_match:
                    chain = dex_match.group(1)
                    # Update chart URL if we found a better one
                    if chain != "search":
                        chart_url = f"https://dexscreener.com/{chain}/{dex_match.group(2)}"
                        logging.info(f"Updated chart URL from description: {chart_url}")
                
                # If still not found, try other indicators
                if chain == "unknown" or chain == "search":
                    if "<:sonic:" in desc or "Sonic @" in desc:
                        chain = "sonic"
                    elif "Solana" in desc or "SOL" in desc:
                        chain = "solana"
                    elif "Ethereum" in desc or "ETH" in desc:
                        chain = "ethereum"
                    elif "BSC" in desc or "BNB" in desc:
                        chain = "bsc"
                    elif "Arbitrum" in desc or "ARB" in desc:
                        chain = "arbitrum"
                    elif "Base" in desc:
                        chain = "base"
                
                logging.info(f"Extracted chain from description: {chain}")
            
            token_data['chain'] = chain
            
            # Make sure we have a valid user
            if not trigger_user or trigger_user == "":
                trigger_user = "unknown"
            
            # Log token in both trackers
            self.token_tracker.log_token(contract_address, token_data, 'rick', trigger_user)
            
            # Also log to hour-specific tracker in DigestCog if available
            if self.digest_cog:
                self.digest_cog.process_new_token(contract_address, token_data)
            
            # Create embed with Buy Alert title
            new_embed = discord.Embed(color=Colors.EMBED_BORDER)
            new_embed.set_author(name="Buy Alert", icon_url="https://cdn.discordapp.com/emojis/1304234350371541012.webp")
            
            return True
            
        except Exception as e:
            logging.error(f"Error processing token {contract_address}: {e}")
            return False

    @commands.Cog.listener()
    async def on_ready(self):
        logging.info("RickGrabber is ready and listening for messages") 