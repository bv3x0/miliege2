import discord # type: ignore
from discord.ext import commands
import re
import logging
import asyncio
from utils import format_large_number, get_age_string, safe_api_call
from db.models import Token, Alert, MarketCapSnapshot
from datetime import datetime

class TokenGrabber(commands.Cog):
    def __init__(self, bot, token_tracker, monitor, session, digest_cog=None):
        self.bot = bot
        self.token_tracker = token_tracker
        self.monitor = monitor
        self.session = session
        self.digest_cog = digest_cog
        self.db = bot.db_session  # Get the database session from the bot
        # Use the same channel as the digest cog for alerts
        self.alert_channel_id = digest_cog.channel_id if digest_cog else None

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
                market_cap = "N/A"
                market_cap_value = None
                try:
                    if 'fdv' in pair:
                        market_cap_value = float(pair['fdv'])
                        market_cap = f"${format_large_number(market_cap_value)}"
                except (ValueError, TypeError) as e:
                    logging.warning(f"Could not parse market cap value from API: {e}")
                    market_cap_value = None
                    market_cap = "N/A"
                
                # Extract chain information from the message embed
                chain = 'ethereum'  # Default to Ethereum
                for embed in message.embeds:
                    for field in embed.fields:
                        if field.name == 'Chain':
                            chain = field.value.lower()
                            logging.info(f"Found chain in embed: {chain}")
                            break
                
                # Also check if chart URL contains chain information
                chart_chain_match = re.search(r'dexscreener\.com/([^/]+)/', chart_url)
                if chart_chain_match and chart_chain_match.group(1) != 'ethereum':
                    chain = chart_chain_match.group(1)
                    logging.info(f"Updated chain from chart URL: {chain}")
                
                token_data = {
                    'name': base_token['name'],
                    'symbol': base_token['symbol'],
                    'chart_url': chart_url,
                    'market_cap': market_cap,
                    'market_cap_value': market_cap_value,
                    'chain': chain,  # Use extracted chain
                    'initial_market_cap': market_cap_value,
                    'initial_market_cap_formatted': market_cap,
                    'timestamp': message.created_at,
                    'message_id': message.id,
                    'channel_id': message.channel.id,
                    'guild_id': message.guild.id if message.guild else None,
                    'source': 'cielo',  # Explicitly set source
                    'user': credit_user if credit_user else 'unknown'  # Explicitly set user
                }
                
                # Log to our in-memory tracker and database
                self.token_tracker.log_token(contract_address, token_data, 'cielo', credit_user)
                
                # Also log to hour-specific tracker in DigestCog if available
                if self.digest_cog:
                    self.digest_cog.process_new_token(contract_address, token_data)
                
                # Post alert to the channel
                await self._post_token_alert(token_data, contract_address)
                
                logging.info(f"Successfully processed token: {base_token['name']} ({contract_address})")
                return True
                
        except Exception as e:
            logging.error(f"Error processing token {contract_address}: {e}")
            return False
            
    async def _post_token_alert(self, token_data, contract_address):
        """Post a token alert to the channel"""
        try:
            if not self.alert_channel_id:
                logging.warning("No alert channel ID configured, skipping alert post")
                return
                
            channel = self.bot.get_channel(self.alert_channel_id)
            if not channel:
                logging.error(f"Could not find channel with ID {self.alert_channel_id}")
                return
                
            # Create an embed for the token alert
            embed = discord.Embed(
                title=f"🚨 New Token Alert: {token_data['name']}",
                url=token_data['chart_url'],
                color=0x5b594f
            )
            
            # Add token information
            embed.add_field(name="Chain", value=token_data['chain'].capitalize(), inline=True)
            embed.add_field(name="Initial Market Cap", value=token_data['initial_market_cap_formatted'], inline=True)
            embed.add_field(name="Source", value=f"{token_data['source']} via {token_data['user']}", inline=True)
            
            # Add contract address with shortened display
            short_address = f"{contract_address[:6]}...{contract_address[-4:]}"
            embed.add_field(name="Contract", value=f"[{short_address}]({token_data['chart_url']})", inline=True)
            
            # Add timestamp
            embed.timestamp = datetime.now()
            
            # Send the embed
            await channel.send(embed=embed)
            logging.info(f"Posted token alert for {token_data['name']} to channel {self.alert_channel_id}")
            
        except Exception as e:
            logging.error(f"Error posting token alert: {e}")