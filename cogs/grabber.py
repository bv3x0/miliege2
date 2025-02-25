import discord # type: ignore
from discord.ext import commands
import re
import logging
import asyncio
from utils import format_large_number, get_age_string, safe_api_call
from db.models import Token, Alert, MarketCapSnapshot

class TokenGrabber(commands.Cog):
    def __init__(self, bot, token_tracker, monitor, session):
        self.bot = bot
        self.token_tracker = token_tracker
        self.monitor = monitor
        self.session = session
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
                    token_name = pair.get('baseToken', {}).get('name', 'Unknown Token')
                    banner_image = pair.get('info', {}).get('header', None)
                    
                    # Get socials from pair info
                    socials = pair.get('info', {})
                    website = socials.get('website', '')
                    twitter = socials.get('twitter', '')
                    telegram = socials.get('telegram', '')
                    
                    # Store raw market cap value for comparison
                    market_cap_value = market_cap if isinstance(market_cap, (int, float)) else None
                    
                    # Format market cap
                    if market_cap_value is not None:
                        formatted_mcap = format_large_number(market_cap_value)
                    else:
                        formatted_mcap = "N/A"
                    
                    # Format price change with explicit +/- and "24h: " prefix
                    if isinstance(price_change_24h, (int, float)):
                        # Add + sign for positive changes, - is automatically included for negative
                        sign = '+' if float(price_change_24h) >= 0 else ''
                        price_change_formatted = f"24h: {sign}{price_change_24h}%"
                    else:
                        price_change_formatted = "24h: N/A"
                    
                    # Create chart URL
                    chart_url = f"https://dexscreener.com/{chain.lower()}/{contract_address}"
                    
                    # Extract pair creation time
                    pair_created_at = pair.get('pairCreatedAt')
                    age_string = get_age_string(pair_created_at)

                    # Extract social links (using the old format)
                    socials = pair.get('info', {}).get('socials', [])
                    tg_link = next((s['url'] for s in socials if s['type'] == 'telegram'), None)
                    twitter_link = next((s['url'] for s in socials if s['type'] == 'twitter'), None)

                    # Extract website link
                    websites = pair.get('info', {}).get('websites', [])
                    website_link = websites[0]['url'] if websites else None

                    # Format social links
                    social_parts = []
                    if website_link:
                        social_parts.append(f"[Web]({website_link})")
                    if twitter_link:
                        social_parts.append(f"[𝕏]({twitter_link})")
                    if tg_link:
                        social_parts.append(f"[TG]({tg_link})")
                    
                    # Create embed response
                    embed = discord.Embed(
                        color=0x5b594f
                    )
                    
                    # Add banner if available
                    if banner_image:
                        embed.set_image(url=banner_image)
                    
                    # Format market cap with dollar sign
                    if market_cap_value is not None:
                        formatted_mcap = f"${format_large_number(market_cap_value)}"
                    else:
                        formatted_mcap = "N/A"
                    
                    # Create multi-line format - using h2 header formatting for first line
                    title_line = f"## [{token_name} ({pair.get('baseToken', {}).get('symbol', 'Unknown')})]({chart_url})"
                    stats_line = f"{formatted_mcap} mc ⋅ {price_change_formatted} ⋅ {chain.lower()}"
                    
                    embed.description = f"{title_line}\n{stats_line}"
                    
                    # Add social links and age
                    links_text = []
                    if social_parts:
                        links_text.append(" ⋅ ".join(social_parts))
                    else:
                        links_text.append("No socials")
                    if age_string:
                        links_text.append(age_string)
                    embed.add_field(name="", value=" ⋅ ".join(links_text), inline=False)
                    
                    # Add note for market caps under $2M (without "Note:" prefix)
                    if market_cap_value and market_cap_value < 2_000_000:
                        embed.add_field(name="", value="_Under $2m !_ <:wow:1149703956746997871>", inline=False)
                    
                    # Store token data with raw market cap value
                    token_data = {
                        'name': token_name,
                        'chart_url': chart_url,
                        'initial_market_cap': market_cap_value,
                        'initial_market_cap_formatted': formatted_mcap,
                        'chain': chain,
                        'message_id': message.id,
                        'channel_id': message.channel.id,
                        'guild_id': message.guild.id if message.guild else None
                    }
                    self.token_tracker.log_token(contract_address, token_data, 'cielo', credit_user)
                    
                    await message.channel.send(embed=embed)
                else:
                    await message.channel.send("❌ **Error:** No trading pairs found for this token.")
                    
        except Exception as e:
            logging.error(f"Error processing token {contract_address}: {e}", exc_info=True)
            await message.channel.send("❌ **Error:** Failed to process token information.")