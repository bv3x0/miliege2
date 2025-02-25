import discord # type: ignore
from discord.ext import commands
import re
import logging
import asyncio
from utils import format_large_number, get_age_string, safe_api_call
from db.models import Token, Alert, MarketCapSnapshot

class TokenGrabber(commands.Cog):
    def __init__(self, bot, token_tracker, monitor, session, digest_cog=None):
        self.bot = bot
        self.token_tracker = token_tracker
        self.monitor = monitor
        self.session = session
        self.digest_cog = digest_cog
        self.db = bot.db_session  # Get the database session from the bot

    @commands.Cog.listener()
    async def on_message(self, message):
        try:
            # Only do detailed logging for Cielo messages
            if message.author.bot and message.author.name == "Cielo":
                logging.info("""
=== Cielo Message Detected ===
Content: %s
Has Embeds: %s
Embed Count: %d
""", message.content, bool(message.embeds), len(message.embeds) if message.embeds else 0)
                
                # Detailed embed field logging
                if message.embeds:
                    for i, embed in enumerate(message.embeds):
                        logging.info(f"\nEmbed {i} Details:")
                        if embed.author:
                            logging.info(f"Author: {embed.author.name}")
                        logging.info(f"Title: {embed.title}")
                        logging.info(f"Description: {embed.description}")
                        # Log the raw embed data to see the tag field
                        logging.info(f"Raw embed data: {embed.to_dict()}")
                        
                        for j, field in enumerate(embed.fields):
                            logging.info(f"Field {j}:")
                            logging.info(f"  Name: '{field.name}'")
                            logging.info(f"  Value: '{field.value}'")
                            logging.info(f"  Inline: {field.inline}")
                
                # Extract credit from embed title
                credit_user = None
                if message.embeds:
                    for embed in message.embeds:
                        if embed.title and '🏷' in embed.title:
                            # Remove the tag emoji and strip whitespace
                            credit_user = embed.title.replace('🏷', '').strip()
                            logging.info(f"Found credit user in embed title: {credit_user}")
                            break
                
                if not credit_user:
                    logging.warning("Could not find credit user in embed title")

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
                                    await self._process_token(contract_address, message, credit_user)
                                    return
                else:
                    logging.warning("Cielo message had no embeds")
            else:
                # Basic debug level logging for non-Cielo messages
                logging.debug(f"Message from {message.author.name}")
                    
        except Exception as e:
            logging.error(f"Error in message processing: {e}", exc_info=True)
            self.monitor.record_error()

    async def _process_token(self, contract_address, message, credit_user=None):
        """Process a token from the message, get market cap data, and add to tracker"""
        try:
            # Check if the contract address is valid (simplified check)
            if not re.match(r'^0x[a-fA-F0-9]{40}$', contract_address):
                logging.warning(f"Invalid contract address format: {contract_address}")
                return False
            
            async with self.session.get(f"https://api.dexscreener.com/latest/dex/tokens/{contract_address}") as response:
                if response.status != 200:
                    logging.error(f"Error fetching token data. Status: {response.status}")
                    return False
                
                data = await response.json()
                if not data.get('pairs') or len(data['pairs']) == 0:
                    logging.warning(f"No pairs found for contract {contract_address}")
                    return False
                
                # Use the first pair's data
                pair = data['pairs'][0]
                base_token = pair['baseToken']
                
                # Create a chart URL (use DEXScreener URL)
                chart_url = f"https://dexscreener.com/ethereum/{contract_address}"
                if 'url' in pair:
                    chart_url = pair['url']
                
                # Extract and format market cap if available
                market_cap = "Unknown"
                market_cap_value = None
                if 'fdv' in pair:
                    market_cap_value = float(pair['fdv'])
                    market_cap = f"${format_large_number(market_cap_value)}"
                
                token_data = {
                    'name': base_token['name'],
                    'symbol': base_token['symbol'],
                    'chart_url': chart_url,
                    'market_cap': market_cap,
                    'market_cap_value': market_cap_value,
                    'chain': 'ethereum',  # Default to Ethereum
                    'initial_market_cap': market_cap_value,
                    'initial_market_cap_formatted': market_cap,
                    'timestamp': message.created_at,
                    'message_id': message.id,
                    'channel_id': message.channel.id,
                    'guild_id': message.guild.id if message.guild else None
                }
                
                # Log to our in-memory tracker and database
                self.token_tracker.log_token(contract_address, token_data, 'cielo', credit_user)
                
                # Also log to hour-specific tracker in DigestCog if available
                if self.digest_cog:
                    self.digest_cog.process_new_token(contract_address, token_data)
                
                logging.info(f"Successfully processed token: {base_token['name']} ({contract_address})")
                return True
                
        except Exception as e:
            logging.error(f"Error processing token {contract_address}: {e}")
            return False