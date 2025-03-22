import discord
from discord.ext import commands
import logging
from cogs.utils import (
    format_large_number,
    format_age as get_age_string,
    format_currency as format_buy_amount,
    DexScreenerAPI
)
from cogs.utils.format import Colors
import asyncio
import datetime
from discord.ext import tasks
import re

class NewCoinCog(commands.Cog):
    def __init__(self, bot, session, output_channel_id=None):
        self.bot = bot
        self.session = session
        self.output_channel_id = output_channel_id
        self.last_alert = {}  # Initialize the dictionary
        self.rate_limit = 300  # 5 minutes
        self.cleanup.start()
        logging.info(f"NewCoinCog initialized with output_channel_id: {output_channel_id}")
        if output_channel_id is None:
            logging.warning("NewCoinCog: No output channel ID provided!")

    @tasks.loop(hours=1)
    async def cleanup(self):
        """Clean up old rate limit entries"""
        now = datetime.datetime.now().timestamp()
        self.last_alert = {
            addr: ts for addr, ts in self.last_alert.items()
            if now - ts < self.rate_limit * 2
        }

    async def process_new_coin(self, token_address, message, user, swap_info, dexscreener_url, chain):
        """Handle first-buy alerts with detailed token info"""
        max_retries = 3
        retry_delay = 1  # seconds
        
        logging.info(f"NewCoinCog.process_new_coin starting:")
        logging.info(f"- Token: {token_address}")
        logging.info(f"- User: {user}")
        logging.info(f"- Chain: {chain}")
        logging.info(f"- Output Channel ID: {self.output_channel_id}")
        
        if not self.output_channel_id:
            logging.error("No output channel ID configured for NewCoinCog")
            return
        
        channel = self.bot.get_channel(self.output_channel_id)
        if not channel:
            logging.error(f"Could not find channel with ID {self.output_channel_id}")
            return
        
        logging.info(f"Found output channel: {channel.name} ({channel.id})")
        
        for attempt in range(max_retries):
            try:
                logging.info(f"Attempt {attempt + 1} to process new coin")
                
                # Get token data from DexScreener
                dex_data = await DexScreenerAPI.get_token_info(self.session, token_address)
                logging.info(f"DexScreener API response received: {bool(dex_data)}")
                
                if not dex_data or 'pairs' not in dex_data or not dex_data['pairs']:
                    logging.warning(f"No valid data from DexScreener for {token_address}")
                    await self._handle_no_data(channel, token_address, user, swap_info, chain, dexscreener_url)
                    return

                # Process token data and create embed
                await self._create_and_send_embed(
                    channel, dex_data['pairs'][0], token_address, user, 
                    swap_info, dexscreener_url, chain
                )
                logging.info("Successfully created and sent embed")
                break
            except Exception as e:
                logging.error(f"Attempt {attempt + 1} failed: {e}", exc_info=True)
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                continue

    async def _create_and_send_embed(self, channel, pair_data, token_address, user, 
                                   swap_info, dexscreener_url, chain):
        """Create and send the new coin embed with full token information"""
        try:
            # Create embed with standard color
            embed = discord.Embed(color=Colors.EMBED_BORDER)
            
            # Set author without icon
            embed.set_author(name="New Trade Alert")
            
            # Extract and format token data
            token_data = self._extract_token_data(pair_data)
            token_data['url'] = dexscreener_url  # Add the chart URL from Cielo
            
            # Create embed description
            embed.description = self._create_description(token_data, chain)
            
            # Set banner image if available
            if banner_url := pair_data.get('info', {}).get('header'):
                embed.set_image(url=banner_url)
            
            # Set footer with user and amount
            self._set_footer(embed, user, swap_info)
            
            # Send messages
            await channel.send(embed=embed)
            await channel.send(f"`{token_address}`")
            
        except Exception as e:
            logging.error(f"Error creating embed: {e}", exc_info=True)
            raise

    def _parse_market_cap(self, market_cap):
        """Parse market cap value from various formats"""
        if isinstance(market_cap, (int, float)):
            return market_cap
        elif isinstance(market_cap, str):
            try:
                cleaned_str = ''.join(c for c in market_cap if c.isdigit() or c == '.')
                return float(cleaned_str)
            except (ValueError, TypeError):
                return None
        return None

    def _extract_token_data(self, pair):
        """Extract relevant token data from pair information"""
        return {
            'name': pair.get('baseToken', {}).get('name', 'Unknown Token'),
            'symbol': pair.get('baseToken', {}).get('symbol', ''),
            'chain': pair.get('chainId', 'Unknown Chain'),
            'market_cap': pair.get('fdv', 'N/A'),
            'price_change_24h': pair.get('priceChange', {}).get('h24', 'N/A'),
            'pair_created_at': pair.get('pairCreatedAt'),
            'socials': pair.get('info', {})
        }

    def _create_description(self, data, chain):
        """Create formatted description for embed"""
        # Format market cap
        market_cap_value = self._parse_market_cap(data['market_cap'])
        formatted_mcap = (
            format_large_number(market_cap_value)
            if market_cap_value is not None else "N/A"
        )
        
        # Add fire emoji for low mcap tokens
        if market_cap_value and market_cap_value < 1_000_000:
            formatted_mcap = f"${formatted_mcap} 🔥"
        else:
            formatted_mcap = f"${formatted_mcap}"

        # Format age
        age_string = get_age_string(data['pair_created_at'])
        simplified_age = self._simplify_age_string(age_string)

        # Format social links
        social_parts = self._format_social_links(data['socials'])
        
        # Create token name/symbol part with optional URL
        if data.get('url'):
            token_header = f"### [{data['name']} ({data['symbol']})]({data['url']})"
        else:
            token_header = f"### {data['name']} ({data['symbol']})"
        
        # Create description parts
        description_parts = [
            token_header,
            f"{formatted_mcap} mc ⋅ {simplified_age} ⋅ {chain.lower()}",
            " ⋅ ".join(social_parts) if social_parts else "no socials"
        ]
        
        return "\n".join(description_parts)

    def _simplify_age_string(self, age_string):
        """Simplify age string format"""
        if not age_string:
            return ""
        
        replacements = [
            (" days old", "d old"),
            (" day old", "d old"),
            (" hours old", "h old"),
            (" hour old", "h old"),
            (" minutes old", "min old"),
            (" minute old", "min old"),
            (" months old", "mo old"),
            (" month old", "mo old")
        ]
        
        for old, new in replacements:
            age_string = age_string.replace(old, new)
        
        return age_string

    def _format_social_links(self, socials):
        """Format social media links for display"""
        social_parts = []
        
        # Map of social media keys to display text
        social_map = {
            'twitter': 'X',
            'telegram': 'TG',
            'website': 'web'
        }
        
        for platform, url in socials.items():
            if platform in social_map and url:
                display_name = social_map[platform]
                social_parts.append(f"[{display_name}]({url})")
        
        return social_parts

    async def _handle_no_data(self, channel, token_address, user, swap_info, chain, dexscreener_url):
        """Handle case when no data is available from DexScreener"""
        embed = discord.Embed(color=Colors.EMBED_BORDER)
        embed.set_author(
            name="New Trade Alert"
        )
        
        # Extract basic info from swap_info
        token_info = self._extract_swap_info(swap_info)
        
        description_parts = [
            f"### [{token_info['name']} ({token_info['name']})]({dexscreener_url})",
            f"New token, no data • {chain}"
        ]
        
        if token_info['formatted_buy']:
            description_parts.append(f"{token_info['formatted_buy']} buy")
        
        embed.description = "\n".join(description_parts)
        
        if user:
            footer_text = user
            if token_info['dollar_amount']:
                amount = float(token_info['dollar_amount'])
                if amount < 250:
                    footer_text = "🤏 " + footer_text
                elif amount >= 10000:
                    footer_text = "🤑 " + footer_text
                footer_text += f" ⋅ ${format(int(amount), ',')} buy"
            embed.set_footer(text=footer_text)
        
        await channel.send(embed=embed)
        await channel.send(f"`{token_address}`")

    def _set_footer(self, embed, user, swap_info):
        """Set footer text with user and amount information"""
        if not user:
            return
            
        footer_text = user
            
        # Extract amount from swap info if available
        if swap_info:
            # Parse the dollar amount from the swap info string
            dollar_match = re.search(r'\(\$([0-9,.]+)\)', swap_info)
            if dollar_match:
                amount = float(dollar_match.group(1).replace(',', ''))
                if amount < 250:
                    footer_text = "🤏 " + footer_text
                elif amount >= 10000:
                    footer_text = "🤑 " + footer_text
                footer_text += f" ⋅ ${format(int(amount), ',')} buy"
            
        embed.set_footer(text=footer_text)

    def _extract_swap_info(self, swap_info):
        """Extract basic token info from swap info string"""
        token_info = {
            'name': 'Unknown',
            'formatted_buy': '',
            'dollar_amount': None
        }
        
        if not swap_info:
            return token_info
        
        # Try to extract token name and amount from swap info
        try:
            # Look for dollar amount in parentheses
            dollar_match = re.search(r'\(\$([0-9,.]+)\)', swap_info)
            if dollar_match:
                amount_str = dollar_match.group(1)
                token_info['dollar_amount'] = amount_str.replace(',', '')
                token_info['formatted_buy'] = f"${amount_str}"
            
            # Extract token name between **** markers
            parts = swap_info.split('****')
            if len(parts) >= 4:
                token_info['name'] = parts[3].strip()
                
        except Exception as e:
            logging.error(f"Error extracting swap info: {e}")
        
        return token_info

    def cog_unload(self):
        """Cleanup when cog is unloaded"""
        self.cleanup.cancel()  # Cancel the task when the cog is unloaded
