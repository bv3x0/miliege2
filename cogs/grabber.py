import discord # type: ignore
from discord.ext import commands
import re
import logging
import asyncio
from utils import format_large_number, get_age_string, safe_api_call

class TokenGrabber(commands.Cog):
    def __init__(self, bot, token_tracker, monitor, session, digest_cog=None):
        self.bot = bot
        self.token_tracker = token_tracker
        self.monitor = monitor
        self.session = session
        self.digest_cog = digest_cog

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

                # Extract swap information and dexscreener maker link
                swap_info = None
                token_address = None
                dexscreener_maker_link = None
                if message.embeds:
                    for embed in message.embeds:
                        for j, field in enumerate(embed.fields):
                            # Look for swap information in field 0
                            if j == 0 and field.value and '⭐️ Swapped' in field.value:
                                # Remove the star emoji and the market cap part
                                swap_info = field.value.replace('⭐️ ', '')
                                # Remove the market cap part if it exists
                                if ' | MC:' in swap_info:
                                    swap_info = swap_info.split(' | MC:')[0]
                                logging.info(f"Found swap info: {swap_info}")
                                
                            # Look for token address in field 1
                            if "Token:" in field.value:
                                logging.info(f"Found Token field: {field.value}")
                                match = re.search(r'Token:\s*`([a-zA-Z0-9]+)`', field.value)
                                if match:
                                    token_address = match.group(1)
                                    logging.info(f"Processing token: {token_address}")
                            
                            # Look for dexscreener maker link in the Chart field
                            if field.name == 'Chart' and 'maker=' in field.value:
                                link_match = re.search(r'\[Link\]\((https://dexscreener\.com/.+?maker=.+?)\)', field.value)
                                if link_match:
                                    dexscreener_maker_link = link_match.group(1)
                                    logging.info(f"Found dexscreener maker link: {dexscreener_maker_link}")
                        
                        # If we found a token, process it
                        if token_address:
                            await self._process_token(token_address, message, credit_user, swap_info, dexscreener_maker_link)
                            
                            # Now try to delete the original message
                            try:
                                await message.delete()
                                logging.info(f"Deleted original Cielo message: {message.id}")
                            except discord.Forbidden:
                                logging.warning("Bot doesn't have permission to delete messages")
                            except Exception as e:
                                logging.error(f"Error deleting message: {e}")
                                
                            return
                else:
                    logging.warning("Cielo message had no embeds")
            else:
                # Basic debug level logging for non-Cielo messages
                logging.debug(f"Message from {message.author.name}")
                    
        except Exception as e:
            logging.error(f"Error in message processing: {e}", exc_info=True)
            self.monitor.record_error()

    async def _process_token(self, contract_address, message, credit_user=None, swap_info=None, dexscreener_maker_link=None):
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
                    
                    # Format market cap with dollar sign
                    if market_cap_value is not None:
                        formatted_mcap = f"${format_large_number(market_cap_value)}"
                    else:
                        formatted_mcap = "N/A"
                    
                    # Create multi-line description
                    
                    # Title line: Remove ticker symbol and add credited user right-aligned if available
                    if credit_user:
                        # Make the username a link if we have a dexscreener maker link
                        if dexscreener_maker_link:
                            title_line = f"## [{token_name}]({chart_url})                                          *via [{credit_user}]({dexscreener_maker_link})*"
                        else:
                            title_line = f"## [{token_name}]({chart_url})                                          *via {credit_user}*"
                    else:
                        title_line = f"## [{token_name}]({chart_url})"
                    
                    # Simplify the swap info and stats lines into a single consolidated line
                    description_parts = [title_line]
                    
                    # Extract the token used for buying (SOL, ETH, etc.)
                    buy_token = "Unknown"
                    if swap_info:
                        # Use regex to extract what token was used for the purchase
                        # Pattern needs to handle both bold and non-bold formatting from Cielo
                        buy_match = re.search(r'Swapped\s+(?:\*\*)?([0-9,.]+)(?:\*\*)?\s+(?:\*\*)?(\w+)(?:\*\*)?', swap_info)
                        if buy_match:
                            amount = buy_match.group(1)
                            buy_token = buy_match.group(2)
                            
                            # Combine into simplified format: "Bought XX.XX SOL at $XX.XM mc • chain"
                            simple_line = f"Bought {amount} {buy_token} at {formatted_mcap} mc ⋅ {chain.lower()}"
                            description_parts.append(simple_line)
                        else:
                            # Fallback if regex doesn't match
                            description_parts.append(f"{formatted_mcap} mc ⋅ {chain.lower()}")
                    else:
                        # Fallback if no swap info is available
                        description_parts.append(f"{formatted_mcap} mc ⋅ {chain.lower()}")
                    
                    # Format social links and age
                    links_text = []
                    if social_parts:
                        links_text.append(" ⋅ ".join(social_parts))
                    else:
                        links_text.append("No socials")
                    if age_string:
                        links_text.append(age_string)
                    
                    # Add social links and age before the banner image
                    description_parts.append(" ⋅ ".join(links_text))
                    
                    # Set the description
                    embed.description = "\n".join(description_parts)
                    
                    # Add banner image after the description
                    if banner_image:
                        embed.set_image(url=banner_image)
                    
                    # Add token address as plain text as the very last item
                    embed.add_field(name="", value=f"{contract_address}", inline=False)
                    
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
                    
                    # Also log to hour-specific tracker in DigestCog if available
                    if self.digest_cog:
                        # Make sure the digest cog gets all the necessary information
                        self.digest_cog.process_new_token(contract_address, {
                            **token_data,
                            'source': 'cielo',
                            'user': credit_user if credit_user else 'unknown'
                        })
                    
                    await message.channel.send(embed=embed)
                else:
                    await message.channel.send("❌ **Error:** No trading pairs found for this token.")
                    
        except Exception as e:
            logging.error(f"Error processing token {contract_address}: {e}", exc_info=True)
            await message.channel.send("❌ **Error:** Failed to process token information.")