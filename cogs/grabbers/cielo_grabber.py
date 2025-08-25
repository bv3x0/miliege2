import discord # type: ignore
from discord.ext import commands
import re
import logging
import asyncio
from cogs.utils import (
    format_large_number,
    format_age as get_age_string,
    format_currency as format_buy_amount,
    format_social_links,
    safe_api_call,
    DexScreenerAPI,
    UI
)
from cogs.utils.format import Colors, BotConstants, Messages
import datetime
import aiohttp

class CieloGrabber(commands.Cog):
    def __init__(self, bot, token_tracker, monitor, session, digest_cog=None,
                 summary_cog=None, newcoin_cog=None, input_channel_id=None, output_channel_id=None):
        self.bot = bot
        self.token_tracker = token_tracker
        self.monitor = monitor
        self.session = session
        self.digest_cog = digest_cog
        self.summary_cog = summary_cog
        self.newcoin_cog = newcoin_cog

        # Add at start of __init__
        logging.info(f"Initializing CieloGrabber with summary_cog: {summary_cog is not None}")

        # Convert channel ID if needed
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

        # Initialize output channel ID
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

        # Verify token_tracker has major_tokens
        if not hasattr(token_tracker, 'major_tokens'):
            raise AttributeError("TokenTracker must have major_tokens attribute")

    @commands.Cog.listener()
    async def on_ready(self):
        logging.info(f"CieloGrabber is ready. Monitoring channel: {self.input_channel_id}")

    @commands.Cog.listener()
    async def on_message(self, message):
        try:
            if message.channel.id != self.input_channel_id:
                return

            if message.author.bot and message.author.name == "Cielo Alerts":
                logging.debug("Processing Cielo Alerts message")

                if not message.embeds:
                    return

                embed = message.embeds[0]
                if not embed.fields:
                    return

                # Get the user from the title (remove the 🏷 emoji)
                user = embed.title.replace('🏷', '').strip()

                # Get the swap info from the first field's value
                swap_info = embed.fields[0].value

                # Get the token address from the second field
                token_address = None
                for field in embed.fields:
                    if field.value.startswith('Token:'):
                        token_address = field.value.replace('Token:', '').replace('`', '').strip()
                        break

                if token_address and ('Swapped' in swap_info):
                    # Create dexscreener URL based on the chain
                    chain = next((f.value for f in embed.fields if f.name == 'Chain'), 'unknown').lower()
                    dexscreener_url = f"https://dexscreener.com/{chain}/{token_address}"

                    logging.info(f"Processing trade - User: {user}, Token: {token_address}")
                    logging.info(f"Swap info: {swap_info}")

                    # Always track the trade for digest, regardless of pause state
                    await self._track_trade(message, token_address, user, swap_info, dexscreener_url)

        except Exception as e:
            logging.error(f"Error processing Cielo message: {e}", exc_info=True)

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
                        # Add fire emoji after "mc"
                        formatted_mcap = f"${format_large_number(market_cap_value)} mc 🔥"
                    else:
                        # Over $1M or unknown - use the green circle
                        author_icon_url = "https://cdn.discordapp.com/emojis/1323480997873848371.webp"
                        logging.info(f"Using green circle for market cap: {market_cap_value}")
                        # No fire emoji for higher market caps
                        formatted_mcap = f"${format_large_number(market_cap_value)} mc"

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

                    # Extract social links using centralized function
                    social_info = pair.get('info', {})
                    # Ensure pair_address is in social_info for Axiom link
                    if 'pairAddress' in pair:
                        social_info['pair_address'] = pair['pairAddress']
                    
                    social_parts = format_social_links(social_info, chain)


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
                        'name': pair.get('baseToken', {}).get('name', token_name),
                        'chart_url': chart_url,
                        'initial_market_cap': market_cap_value,
                        'initial_market_cap_formatted': f"${format_large_number(market_cap_value)}" if market_cap_value is not None else "N/A",
                        'chain': chain,
                        'message_id': message.id,
                        'channel_id': message.channel.id,
                        'guild_id': message.guild.id if message.guild else None,
                        'original_message_id': original_message_id,
                        'original_channel_id': original_channel_id,
                        'original_guild_id': original_guild_id,
                        'info': pair.get('info', {})
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

                # First try to get the full name from Dexscreener API
                async with aiohttp.ClientSession() as session:
                    dex_data = await DexScreenerAPI.get_token_info(session, contract_address)
                    if dex_data and dex_data.get('pairs'):
                        pair = dex_data['pairs'][0]
                        if 'baseToken' in pair and 'name' in pair['baseToken']:
                            token_name = pair['baseToken']['name']
                            token_symbol = pair['baseToken'].get('symbol', '')
                            logging.info(f"Got token name from Dexscreener: {token_name} ({token_symbol})")

                # Only fall back to swap info if we couldn't get the name from Dexscreener
                if token_name == "Unknown Token" and swap_info:
                    swap_match = re.search(r'for\s+\*\*([0-9,.]+)\*\*\s+\*\*\*\*([^*]+)\*\*\*\*\s*@\s*\$([0-9.]+)', swap_info)
                    if swap_match:
                        token_amount = swap_match.group(1)
                        symbol = swap_match.group(2).strip()
                        token_price = swap_match.group(3)
                        # Use the symbol as both name and symbol, but mark it as potentially incomplete
                        token_name = f"{symbol} (Symbol)"
                        token_symbol = symbol
                        logging.info(f"Using symbol as name (fallback): {token_name}")

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

    async def _track_trade(self, message, token_address, user, swap_info, dexscreener_url):
        try:
            # Extract initial market cap from swap info
            initial_mcap = None
            initial_mcap_formatted = 'N/A'
            mc_match = re.search(r'MC:\s*\$([0-9,.]+[KMBkmb]?)', swap_info)
            if mc_match:
                mcap_str = mc_match.group(1)
                logging.info(f"Found initial market cap in swap info: {mcap_str}")

                # Parse market cap with suffix handling
                try:
                    clean_mcap = mcap_str.replace(',', '')
                    multiplier = 1

                    if 'M' in clean_mcap.upper():
                        multiplier = 1000000
                        clean_mcap = clean_mcap.upper().replace('M', '')
                    elif 'K' in clean_mcap.upper():
                        multiplier = 1000
                        clean_mcap = clean_mcap.upper().replace('K', '')
                    elif 'B' in clean_mcap.upper():
                        multiplier = 1000000000
                        clean_mcap = clean_mcap.upper().replace('B', '')

                    initial_mcap = float(clean_mcap) * multiplier
                    initial_mcap_formatted = f"${mcap_str}"  # Keep original formatted string
                    logging.info(f"Parsed market cap value: {initial_mcap} from {mcap_str}")
                except ValueError as e:
                    logging.error(f"Error parsing market cap value '{mcap_str}': {e}")
                    initial_mcap = None
                    initial_mcap_formatted = 'N/A'

            # Add debug logging for raw embed data
            if message.embeds:
                embed = message.embeds[0]
                logging.info(f"Raw embed data: {embed.to_dict()}")

            # Parse swap info
            swap_pattern = r'(?:⭐️\s+)?Swapped\s+\*\*([0-9,.]+)\*\*\s+\*\*\*\*([^*]+)\*\*\*\*\s*\(\$([0-9,.]+)\)\s+for\s+\*\*([0-9,.]+)\*\*\s+\*\*\*\*([^*]+)\*\*\*\*'
            match = re.search(swap_pattern, swap_info)

            if not match:
                logging.warning(f"Could not parse swap info: {swap_info}")
                return

            from_amount, from_token, dollar_amount, to_amount, to_token = match.groups()
            dollar_amount = float(dollar_amount.replace(',', ''))

            # Check if this is a first-time trade
            is_first_trade = '⭐️' in swap_info

            # Create message link
            message_link = f"https://discord.com/channels/{message.guild.id}/{message.channel.id}/{message.id}"

            # Extract chain info from message embeds - IMPROVED EXTRACTION
            chain_info = None
            if message.embeds:
                embed = message.embeds[0]
                # Search for Chain field specifically
                for field in embed.fields:
                    if field.name.lower() == 'chain':
                        chain_info = field.value
                        logging.info(f"Extracted chain from embed field: {chain_info}")
                        break

            # If not found in fields, try other methods
            if not chain_info:
                # Try to extract from dexscreener_url
                chain_match = re.search(r'dexscreener\.com/([^/]+)/', dexscreener_url)
                if chain_match:
                    chain_info = chain_match.group(1)
                    logging.info(f"Extracted chain from dexscreener URL: {chain_info}")
                else:
                    # Default to solana if we can't determine chain (most Cielo alerts are Solana)
                    chain_info = "solana"
                    logging.info(f"Using default chain: {chain_info}")

            # If it's a first trade, trigger the new coin alert (only if not paused)
            logging.info(f"Checking new coin alert conditions:")
            logging.info(f"- is_first_trade: {is_first_trade}")
            logging.info(f"- self.newcoin_cog exists: {self.newcoin_cog is not None}")
            logging.info(f"- cielo_grabber_bot feature state: {self.bot.feature_states.get('cielo_grabber_bot', True)}")
            
            if is_first_trade and self.newcoin_cog:
                logging.info(f"Triggering new coin alert for {token_address}")
                await self.newcoin_cog.process_new_coin(
                    token_address, message, user, swap_info, dexscreener_url, chain_info
                )
            else:
                logging.info(f"New coin alert NOT triggered. Conditions not met.")

            # Check if it's a buy or sell based on token types
            from_is_major = from_token.upper() in self.token_tracker.major_tokens
            to_is_major = to_token.upper() in self.token_tracker.major_tokens

            # Debug logging
            logging.info(f"Trade detection - from_token: {from_token} (is_major: {from_is_major}), to_token: {to_token} (is_major: {to_is_major})")

            # Get token data from Dexscreener to extract social info
            async with aiohttp.ClientSession() as session:
                dex_data = await DexScreenerAPI.get_token_info(session, token_address)
                if dex_data and dex_data.get('pairs'):
                    pair = dex_data['pairs'][0]
                    # Extract social info - Enhanced version with better extraction for Twitter links
                    social_info = {}
                    logging.info(f"Extracting social info from DexScreener API response for {token_address}")

                    # Extract websites
                    websites = pair.get('info', {}).get('websites', [])
                    if websites and isinstance(websites, list):
                        social_info['websites'] = websites
                        logging.info(f"Extracted websites: {websites}")
                    elif website := pair.get('info', {}).get('website'):
                        social_info['website'] = website
                        logging.info(f"Extracted legacy website: {website}")

                    # Extract social links with better handling for Twitter
                    socials = []
                    raw_socials = pair.get('info', {}).get('socials', [])

                    if raw_socials and isinstance(raw_socials, list):
                        # Process each social to ensure proper format
                        for social in raw_socials:
                            if isinstance(social, dict):
                                # Check if it's a Twitter link
                                platform = social.get('platform', '').lower()
                                social_type = social.get('type', '').lower()

                                if 'twitter' in platform or 'twitter' in social_type or social.get('url', '').lower().startswith('https://twitter.com'):
                                    # Normalize the format to ensure compatibility
                                    normalized_social = {
                                        'platform': 'twitter',
                                        'type': 'twitter',
                                        'url': social.get('url')
                                    }
                                    socials.append(normalized_social)
                                    logging.info(f"Found Twitter link: {normalized_social['url']}")
                                else:
                                    # Keep other socials as they are
                                    socials.append(social)

                    # Only add socials if we found any
                    if socials:
                        social_info['socials'] = socials
                        logging.info(f"Extracted socials: {socials}")

                    # Legacy Twitter format fallback
                    if not any(s.get('platform') == 'twitter' or s.get('type') == 'twitter' for s in socials if isinstance(s, dict)):
                        if twitter := pair.get('info', {}).get('twitter'):
                            social_info['twitter'] = twitter
                            logging.info(f"Extracted legacy Twitter: {twitter}")

                    # Add pair address for Axiom link
                    if 'pairAddress' in pair:
                        social_info['pair_address'] = pair['pairAddress']
                        logging.info(f"Added pair address: {pair['pairAddress']}")

                    # Debug log the final social info
                    logging.info(f"Final social_info for {token_address}: {social_info}")

            if self.digest_cog:
                # Prepare token data for tracking
                token_data = {
                    'initial_market_cap': initial_mcap if mc_match else None,
                    'initial_market_cap_formatted': initial_mcap_formatted if mc_match else 'N/A',
                    'message_embed': message.embeds[0].to_dict() if message.embeds else None,
                    'original_message_id': message.id,
                    'original_channel_id': message.channel.id,
                    'original_guild_id': message.guild.id if message.guild else None,
                    'social_info': social_info if 'social_info' in locals() and social_info else {}  # Add social info here
                }

                if to_is_major:
                    # User is selling a token for a major token
                    token_data.update({
                        'name': from_token,
                        'sell': dollar_amount  # Changed from global to per-trade amount
                    })
                    self.digest_cog.track_trade(
                        token_address,
                        from_token,
                        user,
                        dollar_amount,
                        'sell',
                        message_link,
                        dexscreener_url,
                        token_data=token_data
                    )
                else:
                    # User is buying a non-major token
                    token_data.update({
                        'name': to_token,
                        'buy': dollar_amount  # Changed from global to per-trade amount
                    })
                    self.digest_cog.track_trade(
                        token_address,
                        to_token,
                        user,
                        dollar_amount,
                        'buy',
                        message_link,
                        dexscreener_url,
                        swap_info=swap_info,
                        message_embed=message.embeds[0].to_dict() if message.embeds else None,
                        is_first_trade=is_first_trade,
                        chain=chain_info,
                        token_data=token_data
                    )

        except Exception as e:
            logging.error(f"Error tracking trade: {e}", exc_info=True)
