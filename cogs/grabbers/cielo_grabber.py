import discord # type: ignore
from discord.ext import commands
import re
import logging
import asyncio
from cogs.utils import (
    format_large_number,
    format_age as get_age_string,
    format_currency as format_buy_amount,
    safe_api_call,
    DexScreenerAPI,
    UI
)
from cogs.utils.format import Colors, BotConstants, Messages

class CieloGrabber(commands.Cog):
    def __init__(self, bot, token_tracker, monitor, session, digest_cog=None, input_channel_id=None, output_channel_id=None):
        self.bot = bot
        self.token_tracker = token_tracker
        self.monitor = monitor
        self.session = session
        self.digest_cog = digest_cog
        
        # Convert channel IDs to int if they're strings
        if input_channel_id and isinstance(input_channel_id, str):
            try:
                self.input_channel_id = int(input_channel_id)
                logging.info(f"Initialized CieloGrabber with input channel ID: {self.input_channel_id}")
            except ValueError:
                logging.error(f"Invalid input channel ID: {input_channel_id}")
                self.input_channel_id = None
        else:
            self.input_channel_id = input_channel_id
            logging.info(f"Initialized CieloGrabber with input channel ID: {self.input_channel_id}")
        
        if output_channel_id and isinstance(output_channel_id, str):
            try:
                self.output_channel_id = int(output_channel_id)
                logging.info(f"Initialized CieloGrabber with output channel ID: {self.output_channel_id}")
            except ValueError:
                logging.error(f"Invalid output channel ID: {output_channel_id}")
                self.output_channel_id = None
        else:
            self.output_channel_id = output_channel_id
            logging.info(f"Initialized CieloGrabber with output channel ID: {self.output_channel_id}")

    @commands.Cog.listener()
    async def on_message(self, message):
        try:
            # Check if this message is in the input channel (if specified)
            if self.input_channel_id and message.channel.id != self.input_channel_id:
                # Skip messages not in the input channel
                return
            
            # Only do detailed logging for Cielo or Cielo Alerts
            if message.author.bot and (message.author.name == "Cielo" or message.author.name == "Cielo Alerts"):
                logging.info("""
=== Cielo Message Detected ===
From: %s
Content: %s
Has Embeds: %s
Embed Count: %d
""", message.author.name, message.content, bool(message.embeds), len(message.embeds) if message.embeds else 0)
                
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
                
                # Check if this message contains a star emoji in the content or any field
                has_star = False
                
                # First check the message content
                if message.content and '⭐' in message.content:
                    has_star = True
                    logging.info("Found star emoji in message content")
                
                # Then check embeds if no star in content
                if not has_star and message.embeds:
                    for embed in message.embeds:
                        # Check description
                        if embed.description and '⭐' in embed.description:
                            has_star = True
                            logging.info("Found star emoji in embed description")
                            break
                            
                        # Check fields
                        for field in embed.fields:
                            if field.value and ('⭐' in field.value or '⭐️' in field.value):
                                has_star = True
                                logging.info("Found star emoji in message field")
                                break
                        if has_star:
                            break
                
                # For Cielo Alerts, also check for star in the message content directly
                if not has_star and message.author.name == "Cielo Alerts" and message.content:
                    lines = message.content.split('\n')
                    for line in lines:
                        if '⭐' in line or '★' in line:
                            has_star = True
                            logging.info(f"Found star emoji in Cielo Alerts content line: {line}")
                            break
                
                # Skip processing if no star emoji found
                if not has_star:
                    logging.info("No star emoji found in message, skipping processing")
                    return
                
                # Extract credit from embed title or message content
                credit_user = None
                
                # First try to get from embed title (original method)
                if message.embeds:
                    for embed in message.embeds:
                        if embed.title and '🏷' in embed.title:
                            # Remove the tag emoji and strip whitespace
                            credit_user = embed.title.replace('🏷', '').strip()
                            logging.info(f"Found credit user in embed title: {credit_user}")
                            break
                
                # For Cielo Alerts, try to get from the first line with a tag emoji
                if not credit_user and message.author.name == "Cielo Alerts" and message.content:
                    lines = message.content.split('\n')
                    for line in lines:
                        if '🏷' in line or '📝' in line:
                            # Remove the tag emoji and strip whitespace
                            credit_user = line.replace('🏷', '').replace('📝', '').strip()
                            logging.info(f"Found credit user in message content: {credit_user}")
                            break
                
                if not credit_user:
                    logging.warning("Could not find credit user in embed title or message content")

                # Extract swap information and token address
                swap_info = None
                token_address = None
                dexscreener_maker_link = None
                tx_link = None
                chain_info = "unknown"
                
                # For Cielo Alerts format (from the screenshot)
                if message.author.name == "Cielo Alerts" and message.content:
                    lines = message.content.split('\n')
                    
                    # Process each line to extract information
                    for line in lines:
                        # Look for swap information in a line with star emoji
                        if ('⭐' in line or '★' in line) and 'Swapped' in line:
                            # Remove the star emoji
                            swap_info = line.replace('⭐', '').replace('★', '').strip()
                            logging.info(f"Found swap info in content: {swap_info}")
                        
                        # Look for token address in a line starting with "Token:"
                        if line.startswith('Token:'):
                            # Extract the token address
                            token_match = re.search(r'Token:\s*([a-zA-Z0-9]+)', line)
                            if token_match:
                                token_address = token_match.group(1)
                                logging.info(f"Processing token from content: {token_address}")
                        
                        # Look for chain information
                        if line.startswith('Chain'):
                            chain_parts = line.split()
                            if len(chain_parts) > 1:
                                chain_info = chain_parts[1].lower()
                                logging.info(f"Found chain info: {chain_info}")
                        
                        # Look for transaction link
                        if 'Transaction' in line and 'Details' in line:
                            tx_link = "Details"  # Just a placeholder, we'll need to extract the actual link
                        
                        # Look for chart link
                        if 'Chart' in line and 'Link' in line:
                            # We'll construct the dexscreener link later using the token address and chain
                            pass
                
                # Original embed processing for Cielo
                elif message.embeds:
                    for embed in message.embeds:
                        for j, field in enumerate(embed.fields):
                            # Look for swap information in field 0
                            if j == 0 and field.value and ('⭐️ Swapped' in field.value or '⭐ Swapped' in field.value):
                                # Remove the star emoji and the market cap part
                                swap_info = field.value.replace('⭐️ ', '').replace('⭐ ', '')
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
                    # Determine which channel to use for output
                    output_channel = None
                    if self.output_channel_id:
                        output_channel = self.bot.get_channel(self.output_channel_id)
                        logging.info(f"Using configured output channel: {self.output_channel_id}")
                    
                    if not output_channel:
                        # Fallback to the same channel as the input
                        output_channel = message.channel
                        logging.info("Using input channel for output (no output channel configured)")
                    
                    # Create a temporary message in the output channel
                    temp_message = await output_channel.send("Processing token...")
                    
                    # Process the token and send results to the output channel
                    await self._process_token(
                        token_address, 
                        temp_message, 
                        credit_user, 
                        swap_info, 
                        dexscreener_maker_link, 
                        tx_link, 
                        chain_info,
                        original_message_id=message.id,  # Pass the original Cielo message ID
                        original_channel_id=message.channel.id,  # Pass the original Cielo channel ID
                        original_guild_id=message.guild.id if message.guild else None  # Pass the original Cielo guild ID
                    )
                    
                    # Delete our temporary message
                    try:
                        await temp_message.delete()
                    except Exception as e:
                        logging.error(f"Error deleting temporary message: {e}")
                    
                    # Don't delete the original Cielo message
                    logging.info(f"Keeping original message from {message.author.name}: {message.id}")
                    return
                else:
                    logging.warning(f"No token address found in message from {message.author.name}")
            else:
                # Basic debug level logging for non-Cielo messages
                logging.debug(f"Message from {message.author.name}")
                    
        except Exception as e:
            logging.error(f"Error in message processing: {e}", exc_info=True)
            self.monitor.record_error()

    async def _process_token(self, contract_address, message, credit_user=None, swap_info=None, dexscreener_maker_link=None, tx_link=None, chain_info=None, original_message_id=None, original_channel_id=None, original_guild_id=None):
        try:
            logging.info(f"Querying Dexscreener API for token: {contract_address}")
            
            # Get the channel but don't create the embed yet
            channel = message.channel
            
            dex_data = await DexScreenerAPI.get_token_info(self.session, contract_address)
            
            # Add detailed logging of the API response
            logging.info(f"Dexscreener API response: {dex_data}")
            
            if dex_data and 'pairs' in dex_data and dex_data['pairs']:
                try:
                    pair = dex_data['pairs'][0]
                    logging.info(f"Found pair data: {pair.get('baseToken', {}).get('name', 'Unknown')}")
                    
                    # Create a new embed with the standard color
                    new_embed = discord.Embed(color=Colors.EMBED_BORDER)
                    
                    # Extract data first to determine icon URL
                    market_cap = pair.get('fdv', 'N/A')

                    # More robust market cap parsing
                    market_cap_value = None
                    if isinstance(market_cap, (int, float)):
                        market_cap_value = market_cap
                    elif isinstance(market_cap, str):
                        try:
                            # Try to convert string to float, removing any non-numeric characters
                            cleaned_str = ''.join(c for c in market_cap if c.isdigit() or c == '.')
                            market_cap_value = float(cleaned_str)
                        except (ValueError, TypeError):
                            market_cap_value = None

                    # Log the parsed market cap for debugging
                    logging.info(f"Parsed market cap value: {market_cap_value}")

                    # Set different icon URL based on market cap
                    if market_cap_value is not None and market_cap_value < 1_000_000:
                        # Under $1M - use the wow emoji
                        author_icon_url = "https://cdn.discordapp.com/emojis/1149703956746997871.webp"
                        logging.info(f"Using wow emoji for market cap: {market_cap_value}")
                    else:
                        # Over $1M or unknown - use the green circle
                        author_icon_url = "https://cdn.discordapp.com/emojis/1323480997873848371.webp"
                        logging.info(f"Using green circle for market cap: {market_cap_value}")
                        
                    new_embed.set_author(name="Buy Alert", icon_url=author_icon_url)
                    
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
                        price_change_formatted = f"{sign}{price_change_24h}%"
                    else:
                        price_change_formatted = "N/A"
                    
                    # Create chart URL
                    chart_url = f"https://dexscreener.com/{chain.lower()}/{contract_address}"
                    
                    # Extract pair creation time
                    pair_created_at = pair.get('pairCreatedAt')
                    age_string = get_age_string(pair_created_at)

                    # Extract social links from the new format in Dexscreener API
                    social_parts = []
                    
                    try:
                        # Check for websites in the new format first
                        websites = pair.get('info', {}).get('websites', [])
                        if websites and isinstance(websites, list):
                            for website in websites:
                                if isinstance(website, dict) and 'url' in website:
                                    social_parts.append(f"[web]({website['url']})")
                                    break  # Just get the first website
                        
                        # Then check for socials in the new format
                        socials_new = pair.get('info', {}).get('socials', [])
                        if socials_new and isinstance(socials_new, list):
                            for social in socials_new:
                                if isinstance(social, dict) and 'type' in social and 'url' in social:
                                    if social['type'] == 'twitter':
                                        social_parts.append(f"[𝕏]({social['url']})")
                                    elif social['type'] == 'telegram':
                                        social_parts.append(f"[tg]({social['url']})")
                                    elif social['type'] == 'discord' and not any('𝕏' in p for p in social_parts):
                                        # Only add Discord if we don't have Twitter already
                                        social_parts.append(f"[dc]({social['url']})")
                        
                        # Legacy social extraction as fallback
                        if not social_parts:
                            # Try to extract from the old format
                            socials_old = pair.get('info', {})
                            website_link = socials_old.get('website', '')
                            twitter_link = socials_old.get('twitter', '')
                            telegram_link = socials_old.get('telegram', '')
                            
                            if website_link:
                                social_parts.append(f"[web]({website_link})")
                            if twitter_link:
                                social_parts.append(f"[𝕏]({twitter_link})")
                            if telegram_link:
                                social_parts.append(f"[tg]({telegram_link})")
                    except Exception as e:
                        logging.error(f"Error extracting social links: {e}", exc_info=True)
                        # Continue with empty social_parts if there's an error
                    
                    # Extract the token used for buying (SOL, ETH, etc.)
                    buy_token = "Unknown"
                    
                    try:
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
                    except Exception as e:
                        logging.error(f"Error parsing swap info: {e}", exc_info=True)
                        # If we fail to parse swap info, we'll continue with default values
                    
                    # Extract the buy info from swap_info for use in stats_line
                    buy_info = ""
                    try:
                        if 'dollar_amount' in locals() and dollar_amount:
                            formatted_buy = format_buy_amount(dollar_amount)
                            if dexscreener_maker_link:
                                buy_info = f"{formatted_buy} [buy]({dexscreener_maker_link})"
                            else:
                                buy_info = f"{formatted_buy} buy"
                        elif 'amount' in locals() and buy_token != "Unknown":
                            if dexscreener_maker_link:
                                buy_info = f"{amount} {buy_token} [buy]({dexscreener_maker_link})"
                            else:
                                buy_info = f"{amount} {buy_token} buy"
                    except Exception as e:
                        logging.error(f"Error formatting buy info: {e}", exc_info=True)
                        buy_info = ""  # Default to empty string if there's an error
                    
                    # Format market cap with dollar sign and "mc" suffix
                    stats_line_1 = f"${formatted_mcap} mc"
                    
                    # Format age (keep "old" suffix but abbreviate time units)
                    simplified_age = ""
                    try:
                        if age_string:
                            simplified_age = age_string
                            simplified_age = simplified_age.replace(" days old", "d old")
                            simplified_age = simplified_age.replace(" day old", "d old")
                            simplified_age = simplified_age.replace(" hours old", "h old")
                            simplified_age = simplified_age.replace(" hour old", "h old")
                            simplified_age = simplified_age.replace(" minutes old", "min old")
                            simplified_age = simplified_age.replace(" minute old", "min old")
                            simplified_age = simplified_age.replace(" months old", "mo old")
                            simplified_age = simplified_age.replace(" month old", "mo old")
                    except Exception as e:
                        logging.error(f"Error formatting age: {e}", exc_info=True)
                    
                    # Format social links
                    socials_text = ""
                    try:
                        if social_parts:
                            socials_text = " ⋅ ".join(social_parts)
                        else:
                            socials_text = "no socials"
                    except Exception as e:
                        logging.error(f"Error formatting socials: {e}", exc_info=True)
                        socials_text = "no socials"
                    
                    # First stats line: No wow emoji, just market cap, age, and chain
                    stats_line_1 = f"{stats_line_1} ⋅ {simplified_age} ⋅ {chain.lower()}"
                    
                    # Second line: just social links
                    stats_line_2 = socials_text
                    
                    # Create title line with token name, symbol, and URL
                    title_line = f"### [{token_name} ({token_symbol})]({chart_url})"
                    
                    # Add the title line and stats lines to the description
                    description_parts = [title_line, stats_line_1]
                    
                    # Always add social links line, even if it's "no socials"
                    description_parts.append(stats_line_2)
                    
                    # Log the final description to help with debugging
                    final_description = "\n".join(description_parts)
                    logging.info(f"Final embed description: {final_description}")
                    
                    # Set the description
                    new_embed.description = final_description
                    
                    # Add banner image after the description
                    if banner_image:
                        try:
                            new_embed.set_image(url=banner_image)
                        except Exception as e:
                            logging.error(f"Error setting banner image {banner_image}: {e}", exc_info=True)
                            # Continue without banner if there's an error
                    
                    # Set footer with buy amount emoji and buyer (remove wow emoji from footer)
                    try:
                        footer_parts = []
                        
                        # Add buy amount emoji based on amount
                        if 'dollar_amount' in locals() and dollar_amount:
                            amount_float = float(dollar_amount.replace(',', '').replace('$', '')) if isinstance(dollar_amount, str) else dollar_amount
                            if amount_float < 250:
                                footer_parts.append("🤏")
                            elif amount_float >= 10000:
                                footer_parts.append("🤑")
                            # Middle range (250-10000) gets no emoji
                        
                        # Join emojis with spaces
                        footer_emojis = " ".join(footer_parts)
                        
                        # Add username at the end
                        footer_text = footer_emojis
                        if credit_user:
                            # Add a space between emojis and username if there are emojis
                            if footer_text:
                                footer_text += f" {credit_user}"
                            else:
                                footer_text = credit_user
                        
                        # Add buy amount in USD with middle circle separator and "buy" at the end
                        if 'dollar_amount' in locals() and dollar_amount:
                            # Format the dollar amount - remove $ if present and any decimal part
                            formatted_amount = dollar_amount
                            if isinstance(formatted_amount, str):
                                formatted_amount = formatted_amount.replace('$', '')
                                # Remove decimal part if present
                                if '.' in formatted_amount:
                                    formatted_amount = formatted_amount.split('.')[0]
                            else:
                                # If it's a number, convert to int to remove decimals
                                formatted_amount = int(formatted_amount)
                            
                            # Add commas for thousands separator
                            formatted_amount = f"${format(int(float(str(formatted_amount).replace(',', ''))), ',')}"
                            
                            # Add to footer text with middle circle separator
                            footer_text += f" ⋅ {formatted_amount} buy"
                        
                        if footer_text:
                            new_embed.set_footer(text=footer_text)
                    except Exception as e:
                        logging.error(f"Error setting footer: {e}", exc_info=True)
                        # Continue without footer if there's an error
                    
                    # Store token data with raw market cap value
                    token_data = {
                        'name': token_name,
                        'chart_url': chart_url,
                        'initial_market_cap': market_cap_value,
                        'initial_market_cap_formatted': formatted_mcap,
                        'chain': chain,
                        'message_id': message.id,
                        'channel_id': message.channel.id,
                        'guild_id': message.guild.id if message.guild else None,
                        'original_message_id': original_message_id,
                        'original_channel_id': original_channel_id,
                        'original_guild_id': original_guild_id
                    }
                    
                    try:
                        self.token_tracker.log_token(contract_address, token_data, 'cielo', credit_user)
                        
                        # Also log to hour-specific tracker in DigestCog if available
                        if self.digest_cog:
                            # Make sure the digest cog gets all the necessary information
                            self.digest_cog.process_new_token(contract_address, {
                                **token_data,
                                'source': 'cielo',
                                'user': credit_user if credit_user else 'unknown'
                            })
                    except Exception as e:
                        logging.error(f"Error logging token to database: {e}", exc_info=True)
                        # Continue even if database logging fails
                    
                    # Send messages with error handling
                    try:
                        # Send the main embed first - use the channel directly
                        await channel.send(embed=new_embed)
                        
                        # Send the token address as a plain text message immediately after
                        await channel.send(f"`{contract_address}`")
                    except discord.HTTPException as e:
                        logging.error(f"Discord HTTP error when sending message: {e}", exc_info=True)
                        # Try a simplified message if the original fails
                        try:
                            simplified_embed = discord.Embed(
                                title="Buy Alert", 
                                description=f"Token: {token_name}\nAddress: `{contract_address}`",
                                color=Colors.EMBED_BORDER
                            )
                            await channel.send(embed=simplified_embed)
                        except Exception as fallback_e:
                            logging.error(f"Failed to send fallback message: {fallback_e}", exc_info=True)
                            # Last resort plain text
                            try:
                                await channel.send(f"New token alert: `{contract_address}`")
                            except:
                                logging.error("All message sending attempts failed", exc_info=True)
                    except Exception as e:
                        logging.error(f"Unknown error when sending message: {e}", exc_info=True)
                        try:
                            await channel.send(f"Error displaying token info. Token address: `{contract_address}`")
                        except:
                            logging.error("Failed to send error message", exc_info=True)
                except Exception as inner_e:
                    logging.error(f"Error processing token data: {inner_e}", exc_info=True)
                    try:
                        await channel.send(f"❌ **Error:** Failed to process token data. Token address: `{contract_address}`")
                    except:
                        logging.error("Failed to send error message", exc_info=True)
            else:
                # Log the failure reason
                if not dex_data:
                    logging.error(f"No data returned from Dexscreener API for {contract_address}")
                elif 'pairs' not in dex_data:
                    logging.error(f"No 'pairs' field in Dexscreener response: {dex_data}")
                elif not dex_data['pairs']:
                    logging.error(f"Empty pairs array in Dexscreener response: {dex_data}")
                
                # Create a completely fresh embed for the error case
                new_embed = discord.Embed(color=Colors.EMBED_BORDER)
                
                # Extract token name and symbol from swap info
                token_name = "Unknown Token"
                token_symbol = ""
                
                if swap_info:
                    # Try to extract token name and amount from the swap info
                    swap_match = re.search(r'for\s+\*\*([0-9,.]+)\*\*\s+\*\*\*\*([^*]+)\*\*\*\*\s*@\s*\$([0-9.]+)', swap_info)
                    if swap_match:
                        token_amount = swap_match.group(1)
                        token_name = swap_match.group(2).strip()
                        token_price = swap_match.group(3)
                        token_symbol = token_name  # Use token name as symbol since they're often the same in new tokens
                        logging.info(f"Extracted from swap: amount={token_amount}, token={token_name}, price=${token_price}")

                # Create chart URL using the contract and chain
                chart_url = f"https://dexscreener.com/{chain_info.lower()}/{contract_address}"
                
                # Set author with Buy Alert - keep default icon for error case
                new_embed.set_author(name="Buy Alert", icon_url="https://cdn.discordapp.com/emojis/1323480997873848371.webp")
                
                # Create description parts
                description_parts = []
                
                # Title line with token name and symbol
                description_parts.append(f"### [{token_name} ({token_symbol})]({chart_url})")
                
                # Extract buy amount and token from swap info
                if swap_info:
                    buy_match = re.search(r'Swapped\s+\*\*([0-9,.]+)\*\*\s+\*\*\*\*([^*]+)\*\*\*\*\s*\(\$([0-9,.]+)\)', swap_info)
                    if buy_match:
                        amount = buy_match.group(1)
                        buy_token = buy_match.group(2)
                        dollar_amount = buy_match.group(3)
                        formatted_buy = format_buy_amount(dollar_amount)
                        
                        # Add stats line with chain - changed "New token" to "New token, no data"
                        description_parts.append(f"New token, no data • {chain_info}")
                        
                        # Add buy info line
                        if dexscreener_maker_link:
                            description_parts.append(f"{formatted_buy} [buy]({dexscreener_maker_link})")
                        else:
                            description_parts.append(f"{formatted_buy} buy")
                else:
                    # Fallback if no swap info - also changed here
                    description_parts.append(f"New token, no data • {chain_info}")
                
                # Set the description
                new_embed.description = "\n".join(description_parts)
                
                # Set footer with credit user if available
                if credit_user:
                    # Add buy amount emoji based on dollar amount if available
                    footer_text = credit_user
                    if 'dollar_amount' in locals() and dollar_amount:
                        amount_float = float(dollar_amount.replace(',', ''))
                        if amount_float < 250:
                            footer_text = "🤏 " + footer_text
                        elif amount_float >= 10000:
                            footer_text = "🤑 " + footer_text
                        # Middle range (250-10000) gets no emoji
                        footer_text += f" ⋅ ${format(int(float(dollar_amount)), ',')} buy"
                    new_embed.set_footer(text=footer_text)

                # Send embed with available info - use the channel directly
                await channel.send(embed=new_embed)
                
                # Send the token address separately
                # Now with backticks around it to format as code
                await channel.send(f"`{contract_address}`")
                
        except Exception as e:
            logging.error(f"Error processing token {contract_address}: {e}", exc_info=True)
            try:
                await message.channel.send("❌ **Error:** Failed to process token information.")
            except:
                logging.error("Failed to send error message", exc_info=True)