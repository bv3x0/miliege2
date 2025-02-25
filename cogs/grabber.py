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
                tx_link = None
                chain_info = "unknown"
                
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
                                    
                            # Extract transaction link if available
                            if field.name == 'Transaction':
                                # Extract the URL from markdown link [Details](url)
                                tx_match = re.search(r'\[.+?\]\((https?://.+?)\)', field.value)
                                if tx_match:
                                    tx_link = tx_match.group(1)
                                    
                            # Extract chain info
                            if field.name == 'Chain':
                                chain_info = field.value.lower()
                        
                        # If we found a token, process it
                        if token_address:
                            # Create a new clean message without embed for processing
                            clean_message = await message.channel.send("Processing token...")
                            await self._process_token(token_address, clean_message, credit_user, swap_info, dexscreener_maker_link, tx_link, chain_info)
                            
                            # Delete our temporary message
                            try:
                                await clean_message.delete()
                            except Exception as e:
                                logging.error(f"Error deleting temporary message: {e}")
                            
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

    async def _process_token(self, contract_address, message, credit_user=None, swap_info=None, dexscreener_maker_link=None, tx_link=None, chain_info=None):
        try:
            dex_api_url = f"https://api.dexscreener.com/latest/dex/tokens/{contract_address}"
            logging.info(f"Querying Dexscreener API: {dex_api_url}")
            
            async with safe_api_call(self.session, dex_api_url) as dex_data:
                # Create a completely fresh embed with no inherited properties
                channel = message.channel
                
                if dex_data and 'pairs' in dex_data and dex_data['pairs']:
                    pair = dex_data['pairs'][0]
                    
                    # Extract data
                    chain = pair.get('chainId', 'Unknown Chain')
                    price_change_24h = pair.get('priceChange', {}).get('h24', 'N/A')
                    market_cap = pair.get('fdv', 'N/A')
                    token_name = pair.get('baseToken', {}).get('name', 'Unknown Token')
                    token_symbol = pair.get('baseToken', {}).get('symbol', '')
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
                    
                    # Create embed response - make sure it's a completely new embed
                    new_embed = discord.Embed(color=0x5b594f)
                    
                    # Format market cap with dollar sign
                    if market_cap_value is not None:
                        formatted_mcap = f"${format_large_number(market_cap_value)}"
                    else:
                        formatted_mcap = "N/A"
                    
                    # Create multi-line description
                    
                    # Title line with token name, symbol, and URL
                    title_line = ""
                    # Add wow emoji only if under $2M market cap
                    title_emoji = " <:wow:1149703956746997871>" if market_cap_value and market_cap_value < 2_000_000 else ""
                    
                    if token_symbol:
                        title_line = f"## [{token_name} ({token_symbol})]({chart_url}){title_emoji}"
                    else:
                        title_line = f"## [{token_name}]({chart_url}){title_emoji}"
                    
                    # Initialize description parts array
                    description_parts = [title_line]
                    
                    # Market cap line now comes first
                    stats_line = f"{formatted_mcap} mc • {price_change_formatted} • {chain.lower()}"
                    description_parts.append(stats_line)
                    
                    # Add blank line for spacing
                    description_parts.append("")
                    
                    # Format social links and age
                    links_text = []
                    if social_parts:
                        links_text.append(" • ".join(social_parts))
                    else:
                        links_text.append("No socials")
                    if age_string:
                        links_text.append(age_string)
                    
                    # Extract the token used for buying (SOL, ETH, etc.) and add user line below socials
                    buy_token = "Unknown"
                    user_line = ""
                    
                    if swap_info:
                        logging.info(f"Attempting to parse swap info: {swap_info}")
                        
                        # Try multiple patterns to match Cielo's various formatting styles
                        
                        # Pattern 1: Standard format with double asterisks for token (most common)
                        # Example: Swapped **0.0099** ****WETH**** ($23.81) for...
                        buy_match = re.search(r'Swapped\s+\*\*([0-9,.]+)\*\*\s+\*\*\*\*(\w+)\*\*\*\*\s*\(\$([0-9,.]+)\)', swap_info)
                        
                        if buy_match:
                            amount = buy_match.group(1)
                            buy_token = buy_match.group(2)
                            dollar_amount = buy_match.group(3)
                            logging.info(f"Matched pattern 1: amount={amount}, token={buy_token}, dollar_amount=${dollar_amount}")
                        else:
                            # Pattern 2: Alternative with single asterisks
                            # Example: Swapped **0.0099** **WETH** ($23.81) for...
                            alt_match = re.search(r'Swapped\s+\*\*([0-9,.]+)\*\*\s+\*\*(\w+)\*\*\s*\(\$([0-9,.]+)\)', swap_info)
                            
                            if alt_match:
                                amount = alt_match.group(1)
                                buy_token = alt_match.group(2)
                                dollar_amount = alt_match.group(3)
                                logging.info(f"Matched pattern 2: amount={amount}, token={buy_token}, dollar_amount=${dollar_amount}")
                            else:
                                # Pattern 3: More flexible pattern to try to catch other variations
                                flex_match = re.search(r'Swapped.*?([0-9,.]+).*?(\w{3,}).*?\(\$([0-9,.]+)', swap_info)
                                
                                if flex_match:
                                    amount = flex_match.group(1)
                                    buy_token = flex_match.group(2)
                                    dollar_amount = flex_match.group(3)
                                    logging.info(f"Matched pattern 3: amount={amount}, token={buy_token}, dollar_amount=${dollar_amount}")
                                else:
                                    logging.warning(f"Failed to parse swap info with any pattern: {swap_info}")
                        
                        # Format user line regardless of whether we found a match
                        # Get the links ready
                        dex_link = ""
                        if dexscreener_maker_link:
                            dex_link = f"[(dex)]({dexscreener_maker_link})"
                        
                        # Extract Cielo profile link from embed if available
                        cielo_link = ""
                        if message.embeds:
                            for embed in message.embeds:
                                for field in embed.fields:
                                    if field.name == 'Profile' and 'cielo.finance/profile' in field.value:
                                        cielo_match = re.search(r'\[.+?\]\((https://app\.cielo\.finance/profile/[A-Za-z0-9]+)\)', field.value)
                                        if cielo_match:
                                            cielo_link = f" [(cielo)]({cielo_match.group(1)})"
                                            logging.info(f"Found Cielo profile link: {cielo_match.group(1)}")
                        
                        # Create user line based on available info
                        if credit_user:
                            # Format the credit user as a link if we have dexscreener maker link
                            user_display = f"[{credit_user}]({dexscreener_maker_link})" if dexscreener_maker_link else credit_user
                            
                            if 'dollar_amount' in locals() and dollar_amount:
                                # Remove cents and format as whole dollar amount
                                try:
                                    # Convert to float, round to nearest dollar, convert to int, then format with commas
                                    clean_dollar = dollar_amount.replace(',', '')
                                    rounded_dollar = int(round(float(clean_dollar)))
                                    user_line = f"{user_display} bought ${rounded_dollar:,}"
                                except (ValueError, TypeError):
                                    # Fallback to displaying the original dollar amount string if conversion fails
                                    user_line = f"{user_display} bought ${dollar_amount}"
                                
                                if cielo_link:
                                    user_line += f" {cielo_link}"
                            elif 'amount' in locals() and buy_token != "Unknown":
                                # Fallback to token amount if no dollar value found
                                user_line = f"{user_display} bought {amount} {buy_token}"
                                if cielo_link:
                                    user_line += f" {cielo_link}"
                            else:
                                user_line = f"{user_display}"
                                if cielo_link:
                                    user_line += f" {cielo_link}"
                        else:
                            if 'dollar_amount' in locals() and dollar_amount:
                                # Remove cents and format as whole dollar amount
                                try:
                                    clean_dollar = dollar_amount.replace(',', '')
                                    rounded_dollar = int(round(float(clean_dollar)))
                                    user_line = f"Bought ${rounded_dollar:,}"
                                except (ValueError, TypeError):
                                    # Fallback to displaying the original dollar amount string
                                    user_line = f"Bought ${dollar_amount}"
                            elif 'amount' in locals() and buy_token != "Unknown":
                                # Fallback to token amount if no dollar value found
                                user_line = f"Bought {amount} {buy_token}"
                            else:
                                user_line = "New token"
                    else:
                        # No swap info available
                        if credit_user:
                            # Format the credit user as a link if we have dexscreener maker link
                            user_display = f"[{credit_user}]({dexscreener_maker_link})" if dexscreener_maker_link else credit_user
                            
                            # Extract Cielo profile link from embed if available
                            cielo_link = ""
                            if message.embeds:
                                for embed in message.embeds:
                                    for field in embed.fields:
                                        if field.name == 'Profile' and 'cielo.finance/profile' in field.value:
                                            cielo_match = re.search(r'\[.+?\]\((https://app\.cielo\.finance/profile/[A-Za-z0-9]+)\)', field.value)
                                            if cielo_match:
                                                cielo_link = f" [(cielo)]({cielo_match.group(1)})"
                                                logging.info(f"Found Cielo profile link: {cielo_match.group(1)}")
                            
                            user_line = f"{user_display}"
                            if cielo_link:
                                user_line += f" {cielo_link}"
                        else:
                            user_line = "New token"
                    
                    # Add the user line and social info on the same line if possible
                    if user_line:
                        # Combine user info and social links into one line with a separator
                        combined_line = f"{user_line} • {' • '.join(links_text)}"
                        description_parts.append(combined_line)
                    else:
                        # Just add the social links if no user info
                        description_parts.append(" • ".join(links_text))
                    
                    # Set the description
                    new_embed.description = "\n".join(description_parts)
                    
                    # Add banner image after the description
                    if banner_image:
                        new_embed.set_image(url=banner_image)
                    
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
                    
                    # Send the main embed first - use the channel directly
                    await channel.send(embed=new_embed)
                    
                    # Send the token address as a plain text message immediately after
                    # Now with backticks around it to format as code
                    await channel.send(f"`{contract_address}`")
                else:
                    # Improved error handling for tokens not found in Dexscreener
                    # Use the same format as our regular token alerts for consistency
                    
                    # Extract token name from swap info if possible
                    token_name = "Unknown Token"
                    token_symbol = ""
                    if swap_info:
                        # Try to extract the token name from the swap info
                        name_match = re.search(r'for\s+\*\*[\d,.]+\*\*\s+\*\*\*\*([^*]+)\*\*\*\*', swap_info)
                        if name_match:
                            token_name = name_match.group(1).strip()
                            
                        # Try to extract symbol from token name (common format is "Token Name (SYMBOL)")
                        symbol_match = re.search(r'(.+?)\s+\((\w+)\)$', token_name)
                        if symbol_match:
                            token_name = symbol_match.group(1).strip()
                            token_symbol = symbol_match.group(2).strip()
                    
                    # Use the chain_info that was passed to us instead of trying to extract it again
                    if chain_info is None or chain_info == "unknown":
                        chain_info = "unknown"
                    
                    # Create a placeholder chart URL using the contract and chain
                    chart_url = f"https://dexscreener.com/{chain_info.lower()}/{contract_address}"
                    
                    # Create embed response with same color as normal alerts - use a totally fresh embed
                    new_embed = discord.Embed(color=0x5b594f)
                    
                    # Build description lines to match our regular format
                    description_parts = []
                    
                    # Title line with the token name and chart URL
                    title_line = ""
                    if token_symbol:
                        title_line = f"## [{token_name} ({token_symbol})]({chart_url}) <:huh:1151138741197479996>"
                    else:
                        title_line = f"## [{token_name}]({chart_url}) <:huh:1151138741197479996>"
                    description_parts.append(title_line)
                    
                    # Add chain info line
                    description_parts.append(f"New token • {chain_info}")
                    
                    # Add social parts (transaction link and "Not on Dexscreener yet" message)
                    social_parts = []
                    
                    # Add transaction link if available - use the one passed to us
                    if tx_link:
                        social_parts.append(f"[TX]({tx_link})")
                        
                    # Always add this note
                    social_parts.append("Not on Dexscreener yet")
                    
                    # Add user line after basic info, more compact formatting
                    if credit_user:
                        # Format the credit user as a link if we have dexscreener maker link
                        user_display = f"[{credit_user}]({dexscreener_maker_link})" if dexscreener_maker_link else credit_user
                        
                        # Extract Cielo profile link from embed if available
                        cielo_link = ""
                        if message.embeds:
                            for embed in message.embeds:
                                for field in embed.fields:
                                    if field.name == 'Profile' and 'cielo.finance/profile' in field.value:
                                        cielo_match = re.search(r'\[.+?\]\((https://app\.cielo\.finance/profile/[A-Za-z0-9]+)\)', field.value)
                                        if cielo_match:
                                            cielo_link = f" [(cielo)]({cielo_match.group(1)})"
                                            logging.info(f"Found Cielo profile link: {cielo_match.group(1)}")
                        
                        # If we have swap info, try to extract the amount and token and combine with social parts
                        if swap_info:
                            # Try to get the amount and token from swap info
                            amount_match = re.search(r'Swapped\s+\*\*([0-9,.]+)\*\*\s+\*\*\*\*(\w+)\*\*\*\*\s*\(\$([0-9,.]+)\)', swap_info)
                            if amount_match:
                                amount = amount_match.group(1)
                                token = amount_match.group(2)
                                dollar_amount = amount_match.group(3)
                                
                                # Format dollar amount without cents
                                try:
                                    clean_dollar = dollar_amount.replace(',', '')
                                    rounded_dollar = int(round(float(clean_dollar)))
                                    description_parts.append("")  # Just one blank line
                                    description_parts.append(f"{user_display} bought ${rounded_dollar:,} • {' • '.join(social_parts)}")
                                except (ValueError, TypeError):
                                    # Fallback if conversion fails
                                    description_parts.append("")
                                    description_parts.append(f"{user_display} bought ${dollar_amount} • {' • '.join(social_parts)}")
                            else:
                                # Try alternative patterns if the first one doesn't match
                                alt_match = re.search(r'Swapped\s+\*\*([0-9,.]+)\*\*\s+\*\*(\w+)\*\*\s*\(\$([0-9,.]+)\)', swap_info)
                                if alt_match:
                                    amount = alt_match.group(1)
                                    token = alt_match.group(2)
                                    dollar_amount = alt_match.group(3)
                                    
                                    # Format dollar amount without cents
                                    try:
                                        clean_dollar = dollar_amount.replace(',', '')
                                        rounded_dollar = int(round(float(clean_dollar)))
                                        description_parts.append("")
                                        description_parts.append(f"{user_display} bought ${rounded_dollar:,} • {' • '.join(social_parts)}")
                                    except (ValueError, TypeError):
                                        # Fallback if conversion fails
                                        description_parts.append("")
                                        description_parts.append(f"{user_display} bought ${dollar_amount} • {' • '.join(social_parts)}")
                                else:
                                    # Fallback if we can't parse or find dollar amount
                                    description_parts.append("")  # Just one blank line
                                    description_parts.append(f"{user_display} • {' • '.join(social_parts)}")
                        else:
                            description_parts.append("")  # Just one blank line
                            description_parts.append(f"{user_display} • {' • '.join(social_parts)}")
                    else:
                        # No credit user, just add social parts
                        description_parts.append("")  # Just one blank line
                        description_parts.append(f"{' • '.join(social_parts)}")
                    
                    # Set the description
                    new_embed.description = "\n".join(description_parts)
                    
                    # Send embed with available info - use the channel directly
                    await channel.send(embed=new_embed)
                    
                    # Send the token address separately
                    # Now with backticks around it to format as code
                    await channel.send(f"`{contract_address}`")
                    
        except Exception as e:
            logging.error(f"Error processing token {contract_address}: {e}", exc_info=True)
            await message.channel.send("❌ **Error:** Failed to process token information.")