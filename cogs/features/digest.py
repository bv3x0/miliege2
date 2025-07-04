import discord
from discord.ext import commands, tasks
import logging
from collections import OrderedDict
import aiohttp
from cogs.utils import format_large_number
from datetime import datetime, timedelta
import pytz
import asyncio
import re
from cogs.utils.format import Colors
from cogs.utils import DexScreenerAPI


class DigestCog(commands.Cog):
    def __init__(self, bot, token_tracker, channel_id, monitor=None):
        self.bot = bot
        self.token_tracker = token_tracker
        self.channel_id = channel_id
        self.ny_tz = pytz.timezone('America/New_York')
        # Store tokens by hour for better separation
        self.hour_tokens = OrderedDict()
        
        # Start the hourly task
        self.hourly_digest.start()
        
        # Flag to track if the hook is installed
        self.hook_installed = False
        
        # Use the monitor if provided, otherwise track errors locally
        self.monitor = monitor if monitor else None
        self.error_count = 0
        
        # Add trade tracking - organize by hour like tokens
        self.hourly_trades = OrderedDict()
        
        # Define major tokens
        self.major_tokens = token_tracker.major_tokens.copy()
        
        self.db_session = None

    def cog_unload(self):
        self.hourly_digest.cancel()  # Clean up task when cog is unloaded
        
    def _get_period_key(self, time_delta_minutes=0):
        """Get a period key for a specific time offset
        
        Args:
            time_delta_minutes: Minutes to subtract from current time (default 0)
        
        Returns:
            Period key string in format YYYY-MM-DD-HH-MM
        """
        ny_time = datetime.now(self.ny_tz) - timedelta(minutes=time_delta_minutes)
        # Round down to the nearest 30-minute mark
        if ny_time.minute >= 30:
            ny_time = ny_time.replace(minute=30, second=0, microsecond=0)
        else:
            ny_time = ny_time.replace(minute=0, second=0, microsecond=0)
        return ny_time.strftime("%Y-%m-%d-%H-%M")
    
    @property
    def current_hour_key(self):
        """Get the current 30-minute period key and ensure the period bucket exists"""
        key = self._get_period_key()
        logging.info(f"Getting current period key: {key}")
        if key not in self.hour_tokens:
            logging.info(f"Creating new period bucket for {key}")
            self.hour_tokens[key] = OrderedDict()
        return key

    def _get_token_age_hours(self, pair_created_at):
        """Calculate token age in hours from pairCreatedAt timestamp"""
        if not pair_created_at:
            return None
        try:
            if isinstance(pair_created_at, (int, str)):
                created_time = datetime.fromtimestamp(int(pair_created_at) / 1000)
                age_delta = datetime.now() - created_time
                return age_delta.total_seconds() / 3600  # Return age in hours
        except Exception as e:
            logging.error(f"Error calculating token age: {e}")
            return None


    async def create_digest_embed(self, tokens, is_hourly=True):
        """Create the digest embed(s) - shared between auto and manual digests"""
        if not tokens:
            return None

        # For manual digests (!digest command), keep the original single embed behavior
        if not is_hourly:
            return await self._create_single_digest_embed(tokens, is_hourly)
        
        # For hourly digests, create 4 separate embeds
        return await self._create_categorized_digest_embeds(tokens)
    
    async def _create_categorized_digest_embeds(self, tokens):
        """Create 4 separate digest embeds for different categories"""
        # Get the previous period key for trade data
        period_key = self._get_period_key(30)
        
        # Initialize categories
        categories = {
            'new_coins': OrderedDict(),
            'three_plus_buyers': OrderedDict(),
            'big_buys': OrderedDict(),
            'others': OrderedDict()
        }
        
        # Cache for DexScreener data to avoid duplicate API calls
        dex_cache = {}
        
        # Fetch token ages and categorize
        async with aiohttp.ClientSession() as session:
            for contract, token in tokens.items():
                # Get token age from DexScreener
                token_age_hours = None
                try:
                    dex_data = await DexScreenerAPI.get_token_info(session, contract)
                    if dex_data and dex_data.get('pairs'):
                        pair = dex_data['pairs'][0]
                        # Cache the data for later use
                        dex_cache[contract] = dex_data
                        if 'pairCreatedAt' in pair:
                            token_age_hours = self._get_token_age_hours(pair['pairCreatedAt'])
                except Exception as e:
                    logging.error(f"Error fetching token age for {contract}: {e}")
                
                # Check trade data for this period
                is_new_coin = token_age_hours is not None and token_age_hours < 1
                is_three_plus_buyers = False
                has_big_buy = False
                
                if period_key in self.hourly_trades and contract in self.hourly_trades[period_key]:
                    trade_data = self.hourly_trades[period_key][contract]
                    
                    # Count unique buyers
                    buyers = set()
                    max_user_buy = 0
                    
                    for user, user_data in trade_data['users'].items():
                        buy_amount = user_data.get('buys', 0)
                        if buy_amount > 0:
                            buyers.add(user)
                            max_user_buy = max(max_user_buy, buy_amount)
                    
                    is_three_plus_buyers = len(buyers) >= 3
                    has_big_buy = max_user_buy > 10000
                
                # Categorize token (can appear in multiple categories)
                if is_new_coin:
                    categories['new_coins'][contract] = token
                if is_three_plus_buyers:
                    categories['three_plus_buyers'][contract] = token
                if has_big_buy:
                    categories['big_buys'][contract] = token
                
                # If not in any special category, put in others
                if not (is_new_coin or is_three_plus_buyers or has_big_buy):
                    categories['others'][contract] = token
        
        # Create embeds for each category
        embeds = []
        
        # 1. New Coins (use Cielo color)
        if categories['new_coins']:
            embed = await self._create_category_embed(
                categories['new_coins'], 
                "New Coins", 
                Colors.EMBED_BORDER,  # Cielo color
                period_key,
                dex_cache
            )
            if embed:
                embeds.extend(embed)
        
        # 2. 3+ Buyers
        if categories['three_plus_buyers']:
            embed = await self._create_category_embed(
                categories['three_plus_buyers'], 
                "3+ Buyers", 
                Colors.EMBED_BORDER,
                period_key,
                dex_cache
            )
            if embed:
                embeds.extend(embed)
        
        # 3. Big Buys
        if categories['big_buys']:
            embed = await self._create_category_embed(
                categories['big_buys'], 
                "Big Buys", 
                Colors.EMBED_BORDER,
                period_key,
                dex_cache
            )
            if embed:
                embeds.extend(embed)
        
        # 4. Others
        if categories['others']:
            embed = await self._create_category_embed(
                categories['others'], 
                "Others", 
                Colors.EMBED_BORDER,
                period_key,
                dex_cache
            )
            if embed:
                embeds.extend(embed)
        
        return embeds if embeds else None
    
    async def _create_category_embed(self, tokens, category_name, color, period_key, dex_cache=None):
        """Create embed for a specific category of tokens"""
        # Take last 10 tokens
        recent_tokens = list(tokens.items())[-10:]
        
        # Create embeds with the sorted tokens
        embeds = []
        current_description_lines = []
        
        async with aiohttp.ClientSession() as session:
            for contract, token in recent_tokens:
                # Format token lines (reuse existing logic)
                new_lines = await self._format_token_lines(contract, token, session, period_key, dex_cache)
                
                # Check if adding these lines would exceed Discord's limit
                potential_description = "\n".join(current_description_lines + new_lines)
                if len(potential_description) > 4000 and current_description_lines:
                    # Create new embed with current lines
                    embed = discord.Embed(color=color)
                    embed.set_author(name=category_name)
                    embed.description = "\n".join(current_description_lines)
                    embeds.append(embed)
                    
                    # Start new collection of lines
                    current_description_lines = new_lines
                else:
                    current_description_lines.extend(new_lines)
        
        # Create final embed with any remaining lines
        if current_description_lines:
            embed = discord.Embed(color=color)
            embed.set_author(name=category_name)
            embed.description = "\n".join(current_description_lines)
            embeds.append(embed)
        
        return embeds
    
    async def _format_token_lines(self, contract, token, session, period_key, dex_cache=None):
        """Format the display lines for a single token"""
        name = token['name']
        chain = token.get('chain', 'Unknown')
        source = token.get('source', 'unknown')
        user = token.get('user', 'unknown')
        
        # Add this before trying to construct the token_line
        if 'chart_url' not in token or not token['chart_url']:
            # Set a default chart URL if missing
            token['chart_url'] = f"https://dexscreener.com/{chain.lower()}/{contract}"
            logging.warning(f"Missing chart_url for {name}, creating default")
        
        # Then construct token_line
        token_line = f"### [{name}]({token['chart_url']})"
        
        # Create Discord message link if we have the necessary info
        message_link = None
        original_message_link = None
        
        # Check for original message link first (Cielo message)
        if (token.get('original_message_id') and token.get('original_channel_id') and 
                token.get('original_guild_id')):
            original_message_link = (f"https://discord.com/channels/"
                                   f"{token['original_guild_id']}/"
                                   f"{token['original_channel_id']}/"
                                   f"{token['original_message_id']}")
        
        # Fall back to grabber message link if original not available
        if not original_message_link and token.get('message_id') and token.get('channel_id') and token.get('guild_id'):
            message_link = f"https://discord.com/channels/{token['guild_id']}/{token['channel_id']}/{token['message_id']}"
        
        # Fetch current market cap and age (use cache if available)
        if dex_cache and contract in dex_cache:
            dex_data = dex_cache[contract]
        else:
            dex_data = await DexScreenerAPI.get_token_info(session, contract)
        
        current_mcap = 'N/A'
        token_age = 'N/A'
        if dex_data and dex_data.get('pairs'):
            pair = dex_data['pairs'][0]
            if 'fdv' in pair:
                current_mcap = f"${format_large_number(float(pair['fdv']))}"
            # Get token age
            if 'pairCreatedAt' in pair:
                from cogs.utils import format_age
                token_age = format_age(pair['pairCreatedAt'])
                if not token_age:
                    token_age = 'N/A'
        
        # Format token information
        # Compare market caps and add emoji based on 40% threshold
        try:
            current_mcap_value = self.parse_market_cap(current_mcap)
            initial_mcap_value = token.get('initial_market_cap')  # Already parsed when stored
            
            status_emoji = ""
            if current_mcap_value and initial_mcap_value and initial_mcap_value > 0:
                percent_change = ((current_mcap_value - initial_mcap_value) / initial_mcap_value) * 100
                logging.info(f"Token {name} mcap change: {percent_change}% (from {initial_mcap_value} to {current_mcap_value})")
                
                if percent_change >= 40:
                    status_emoji = " :up:"
                elif percent_change <= -40:
                    status_emoji = " 🪦"
        except Exception as e:
            logging.error(f"Error calculating percent change for {name}: {e}")
            status_emoji = ""
        
        # Make sure we have valid values for display
        if not source or source == "":
            source = "unknown"
        if not user or user == "":
            user = "unknown"
        if not chain or chain == "":
            chain = "unknown"
        
        # Format the description lines
        token_line += status_emoji
        
        # Add red X to tokens with only sells
        if period_key in self.hourly_trades and contract in self.hourly_trades[period_key]:
            trade_data = self.hourly_trades[period_key][contract]
            total_buys = sum(user_data.get('buys', 0) for user_data in trade_data['users'].values())
            total_sells = sum(user_data.get('sells', 0) for user_data in trade_data['users'].values())
            if total_sells > 0 and total_buys == 0:
                token_line += " ❌"
        
        # Always use chain from token data, never default to unknown
        chain_display = chain.lower() if chain and chain != "Unknown" else "unknown"
        
        # Format social links
        social_parts = self._format_social_links(token)
        
        # Create the social string with proper formatting
        if social_parts:
            social_str = " ⋅ ".join(social_parts) + " ⋅ "
        else:
            social_str = ""
        
        # Format the stats line: $1.5m mc ⋅ 6h ⋅ web ⋅ 𝕏 ⋅ solana
        stats_line = f"{current_mcap} mc ⋅ {token_age} ⋅ {social_str}{chain_display}"
        
        new_lines = [token_line, stats_line]
        
        # Add trade info
        display_trade_data = False
        trade_data = None
        
        # Get trade data for this token from the appropriate period
        if period_key in self.hourly_trades and contract in self.hourly_trades.get(period_key, {}):
            trade_data = self.hourly_trades[period_key][contract]
            display_trade_data = True
        
        if display_trade_data and trade_data:
            has_trades = sum(user_data.get('buys', 0) > 0 or user_data.get('sells', 0) > 0 
                           for user_data in trade_data['users'].values()) > 0
            
            if has_trades:
                # First try the structured formatting
                trade_info = self._format_trade_info(trade_data, False)
                
                if trade_info and trade_info.strip():
                    new_lines.append(trade_info)
                else:
                    # Use source via user as fallback
                    source_line = f"{source} via [{user}]({original_message_link or message_link})" if (original_message_link or message_link) else f"{source} via {user}"
                    new_lines.append(source_line)
            else:
                # No trade amounts, use source via user
                source_line = f"{source} via [{user}]({original_message_link or message_link})" if (original_message_link or message_link) else f"{source} via {user}"
                new_lines.append(source_line)
        else:
            # We're not showing trade data for this token
            source_line = f"{source} via [{user}]({original_message_link or message_link})" if (original_message_link or message_link) else f"{source} via {user}"
            new_lines.append(source_line)
        
        return new_lines
    
    async def _create_single_digest_embed(self, tokens, is_hourly=True):
        """Create the original single digest embed - for manual digests"""
        # Convert tokens to list and calculate sorting metrics
        token_list = []
        current_hour_key = self.current_hour_key
        
        for contract, token in tokens.items():
            # Calculate status score (4=up, 3=normal, 2=x, 1=gravestone)
            status_score = 3  # Default score for normal tokens
            
            # Get current and initial mcap for percentage calculation
            try:
                async with aiohttp.ClientSession() as session:
                    dex_data = await DexScreenerAPI.get_token_info(session, contract)
                    current_mcap = 'N/A'
                    if dex_data and dex_data.get('pairs'):
                        pair = dex_data['pairs'][0]
                        if 'fdv' in pair:
                            current_mcap = f"${format_large_number(float(pair['fdv']))}"
            
                current_mcap_value = self.parse_market_cap(current_mcap)
                initial_mcap_value = token.get('initial_market_cap')
                
                if current_mcap_value and initial_mcap_value and initial_mcap_value > 0:
                    percent_change = ((current_mcap_value - initial_mcap_value) / initial_mcap_value) * 100
                    if percent_change >= 40:
                        status_score = 4  # :up:
                    elif percent_change <= -40:
                        status_score = 1  # 🪦
            except Exception as e:
                logging.error(f"Error calculating percent change: {e}")

            # Check for sell-only tokens - ONLY CONSIDER TRADES FROM TOKENS IN THE CURRENT PERIOD
            total_buys = 0
            total_sells = 0
            
            # For 30-minute digests, use the trade data from the previous period key
            # For manual digests, use the current period key
            if is_hourly:
                period_key = self._get_period_key(30)
            else:
                period_key = current_hour_key
            
            # Get trade data for the current contract in the specified period
            if period_key in self.hourly_trades and contract in self.hourly_trades.get(period_key, {}):
                trade_data = self.hourly_trades[period_key][contract]
                total_buys = sum(user_data.get('buys', 0) for user_data in trade_data['users'].values())
                total_sells = sum(user_data.get('sells', 0) for user_data in trade_data['users'].values())
                
                if total_sells > 0 and total_buys == 0:
                    status_score = 2  # ❌
            else:
                logging.info(f"No trade data found for {contract} in period {period_key}")

            token_list.append({
                'contract': contract,
                'token': token,
                'status_score': status_score,
                'total_buys': total_buys,
                'total_sells': total_sells  # Store the total sells as well
            })

        # Sort tokens by status_score (descending) and total_buys (descending)
        token_list.sort(key=lambda x: (-x['status_score'], -x['total_buys']))

        # Take last 10 tokens after sorting
        recent_tokens = [(t['contract'], t['token']) for t in token_list[-10:]]

        # Create embeds with the sorted tokens
        embeds = []
        current_description_lines = []
        
        async with aiohttp.ClientSession() as session:
            for contract, token in recent_tokens:
                name = token['name']
                chain = token.get('chain', 'Unknown')
                initial_mcap = token.get('initial_market_cap_formatted', 'N/A')
                source = token.get('source', 'unknown')
                user = token.get('user', 'unknown')
                
                # Add this before trying to construct the token_line
                if 'chart_url' not in token or not token['chart_url']:
                    # Set a default chart URL if missing
                    token['chart_url'] = f"https://dexscreener.com/{chain.lower()}/{contract}"
                    logging.warning(f"Missing chart_url for {name}, creating default")
                
                # Then construct token_line
                token_line = f"### [{name}]({token['chart_url']})"
                
                # Create Discord message link if we have the necessary info
                message_link = None
                original_message_link = None

                # Check for original message link first (Cielo message)
                if token.get('original_message_id') and token.get('original_channel_id') and token.get('original_guild_id'):
                    original_message_link = f"https://discord.com/channels/{token['original_guild_id']}/{token['original_channel_id']}/{token['original_message_id']}"

                # Fall back to grabber message link if original not available
                if not original_message_link and token.get('message_id') and token.get('channel_id') and token.get('guild_id'):
                    message_link = f"https://discord.com/channels/{token['guild_id']}/{token['channel_id']}/{token['message_id']}"

                # Fetch current market cap and age
                dex_data = await DexScreenerAPI.get_token_info(session, contract)
                current_mcap = 'N/A'
                token_age = 'N/A'
                if dex_data and dex_data.get('pairs'):
                    pair = dex_data['pairs'][0]
                    if 'fdv' in pair:
                        current_mcap = f"${format_large_number(float(pair['fdv']))}"
                    # Get token age
                    if 'pairCreatedAt' in pair:
                        from cogs.utils import format_age
                        token_age = format_age(pair['pairCreatedAt'])
                        if not token_age:
                            token_age = 'N/A'

                # Format token information
                # Compare market caps and add emoji based on 40% threshold
                try:
                    current_mcap_value = self.parse_market_cap(current_mcap)
                    initial_mcap_value = token.get('initial_market_cap')  # Already parsed when stored
                    
                    status_emoji = ""
                    if current_mcap_value and initial_mcap_value and initial_mcap_value > 0:
                        percent_change = ((current_mcap_value - initial_mcap_value) / initial_mcap_value) * 100
                        logging.info(f"Token {name} mcap change: {percent_change}% (from {initial_mcap_value} to {current_mcap_value})")
                        
                        if percent_change >= 40:
                            status_emoji = " :up:"
                        elif percent_change <= -40:
                            status_emoji = " 🪦"
                except Exception as e:
                    logging.error(f"Error calculating percent change for {name}: {e}")
                    status_emoji = ""
                
                # Make sure we have valid values for display
                if not source or source == "":
                    source = "unknown"
                if not user or user == "":
                    user = "unknown"
                if not chain or chain == "":
                    chain = "unknown"
                
                # Log the values for debugging
                logging.info(f"Digest display for {name}: chain={chain}, source={source}, user={user}")
                
                # If we have trade data, log details about it for debugging
                if contract in self.hourly_trades:
                    trade_data = self.hourly_trades[contract]
                    for user, user_data in trade_data['users'].items():
                        logging.info(f"Trade data for {user}: message_link={user_data.get('message_link', 'None')}")
                
                # Format the description lines
                token_line += status_emoji
                
                # IMPORTANT FIX #1: Add red X to tokens with only sells
                if contract in self.hourly_trades:
                    trade_data = self.hourly_trades[contract]
                    total_buys = sum(user_data.get('buys', 0) for user_data in trade_data['users'].values())
                    total_sells = sum(user_data.get('sells', 0) for user_data in trade_data['users'].values())
                    if total_sells > 0 and total_buys == 0:
                        token_line += " ❌"
                
                # IMPORTANT FIX #2: Always use chain from token data, never default to unknown
                chain_display = chain.lower() if chain and chain != "Unknown" else "unknown"
                
                # Format social links
                social_parts = self._format_social_links(token)
                
                # Log the social parts for debugging
                logging.info(f"Social parts for {name}: {social_parts}")
                
                # Create the social string with proper formatting
                if social_parts:
                    social_str = " ⋅ ".join(social_parts) + " ⋅ "
                else:
                    social_str = ""
                
                # Format the stats line: $1.5m mc ⋅ 6h ⋅ web ⋅ 𝕏 ⋅ solana
                stats_line = f"{current_mcap} mc ⋅ {token_age} ⋅ {social_str}{chain_display}"
                logging.info(f"Stats line for {name}: {stats_line}")
                
                # Calculate the length of new lines to be added
                new_lines = [token_line, stats_line]
                
                # IMPORTANT FIX #3: Always prioritize displaying trade info when available
                # And for manual digests, only consider current period trades
                display_trade_data = False
                trade_data = None
                
                # This method is only called from category embeds for hourly digests
                # so we don't need to check is_hourly here
                
                # Get trade data for this token from the appropriate period
                if period_key in self.hourly_trades and contract in self.hourly_trades.get(period_key, {}):
                    trade_data = self.hourly_trades[period_key][contract]
                    display_trade_data = True
                    logging.info(f"Found trade data for {name} in period {period_key}")
                
                if display_trade_data and trade_data:
                    has_trades = sum(user_data.get('buys', 0) > 0 or user_data.get('sells', 0) > 0 
                           for user_data in trade_data['users'].values()) > 0
                    
                    if has_trades:
                        # First try the structured formatting
                        trade_info = self._format_trade_info(trade_data, not is_hourly)
                        
                        if trade_info and trade_info.strip():
                            new_lines.append(trade_info)
                            logging.info(f"Added trade info for {name}: {trade_info}")
                        else:
                            # If that fails, directly create trade info for the main users
                            # CRITICAL FALLBACK - Create explicit trade info
                            if total_sells:
                                # Look for users who sold and show the first one
                                for user, user_data in trade_data['users'].items():
                                    if 'sell' in user_data['actions']:
                                        sell_amt = format_large_number(user_data.get('sells', 0))
                                        user_link = f"[{user}]({user_data['message_link']})" if user_data.get('message_link') else user
                                        new_lines.append(f"{user_link}: sell ${sell_amt}")
                                        break
                            elif total_buys:
                                # Look for users who bought and show the first one
                                for user, user_data in trade_data['users'].items():
                                    if 'buy' in user_data['actions']:
                                        buy_amt = format_large_number(user_data.get('buys', 0))
                                        user_link = f"[{user}]({user_data['message_link']})" if user_data.get('message_link') else user
                                        new_lines.append(f"{user_link}: buy ${buy_amt}")
                                        break
                            else:
                                # Last resort - just use the source via user
                                source_line = f"{source} via [{user}]({original_message_link or message_link})" if (original_message_link or message_link) else f"{source} via {user}"
                                new_lines.append(source_line)
                                logging.info(f"Ultimate fallback to source line for {name}: {source_line}")
                    else:
                        # No trade amounts, use source via user
                        source_line = f"{source} via [{user}]({original_message_link or message_link})" if (original_message_link or message_link) else f"{source} via {user}"
                        new_lines.append(source_line)
                else:
                    # We're not showing trade data for this token (likely not in current hour)
                    source_line = f"{source} via [{user}]({original_message_link or message_link})" if (original_message_link or message_link) else f"{source} via {user}"
                    new_lines.append(source_line)
                
                # Check if adding these lines would exceed Discord's limit
                potential_description = "\n".join(current_description_lines + new_lines)
                if len(potential_description) > 4000 and current_description_lines:  # Leave some buffer
                    # Create new embed with current lines
                    embed = discord.Embed(color=Colors.EMBED_BORDER)
                    embed.set_author(name="Latest Alerts")
                    embed.description = "\n".join(current_description_lines)
                    embeds.append(embed)
                    
                    # Start new collection of lines
                    current_description_lines = new_lines
                else:
                    current_description_lines.extend(new_lines)
        
        # Create final embed with any remaining lines
        if current_description_lines:
            embed = discord.Embed(color=Colors.EMBED_BORDER)
            embed.set_author(name="Latest Alerts")
            embed.description = "\n".join(current_description_lines)
            embeds.append(embed)
        
        return embeds

    @tasks.loop(minutes=30)
    async def hourly_digest(self):
        """Automatically post digest every 30 minutes"""
        try:
            # Check if hourly digest is paused
            if not self.bot.feature_states.get('hourly_digest', True):
                logging.debug("Hourly digest is paused, skipping digest")
                return
                
            logging.info("Starting 30-minute digest task")
            now = datetime.now(self.ny_tz)
            logging.info(f"Current NY time: {now}")

            channel = self.bot.get_channel(self.channel_id)
            if not channel:
                logging.error(f"Could not find channel {self.channel_id}")
                return

            # Get the previous 30-minute period's key since we want to digest what just finished
            previous_period = self._get_period_key(30)
            logging.info(f"Processing digest for period: {previous_period}")
            
            tokens_to_report = self.hour_tokens.get(previous_period, OrderedDict())
            logging.info(f"Found {len(tokens_to_report)} tokens to report for period {previous_period}")
            
            if tokens_to_report:
                embeds = await self.create_digest_embed(tokens_to_report, is_hourly=True)
                if embeds:
                    # Send each embed as a separate message
                    for embed in embeds:
                        await channel.send(embed=embed)
                    # Clear data only after successful send
                    self._clear_hour_data(previous_period)
                    logging.info(f"Successfully posted {len(embeds)} digest embeds and cleared data for period {previous_period}")
                else:
                    logging.warning(f"No embeds created for {len(tokens_to_report)} tokens")
            else:
                logging.info(f"No tokens to report for period {previous_period}")

        except Exception as e:
            logging.error(f"Critical error in 30-minute digest: {e}", exc_info=True)

    @hourly_digest.before_loop
    async def before_hourly_digest(self):
        """Wait until the start of the next 30-minute period before starting the digest loop"""
        await self.bot.wait_until_ready()
        logging.info("Waiting for bot to be ready before starting 30-minute digest")
        
        # Use NY timezone consistently
        now = datetime.now(self.ny_tz)
        
        # Calculate the next 30-minute mark
        current_minute = now.minute
        if current_minute < 30:
            next_period = now.replace(minute=30, second=0, microsecond=0)
        else:
            next_period = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        
        wait_seconds = (next_period - now).total_seconds()
        
        logging.info(f"Current NY time: {now}")
        logging.info(f"Next digest scheduled for NY time: {next_period}")
        logging.info(f"Waiting {wait_seconds} seconds until next digest")
        
        await asyncio.sleep(wait_seconds)
        
    def parse_market_cap(self, mcap_str):
        """Parse market cap string to float value"""
        try:
            if not mcap_str or mcap_str == 'N/A':
                return None
            
            # Remove $ and any commas
            clean_mcap = mcap_str.replace('$', '').replace(',', '')
            
            # Handle K/M/B suffixes
            multiplier = 1
            if 'K' in clean_mcap.upper():
                multiplier = 1000
                clean_mcap = clean_mcap.upper().replace('K', '')
            elif 'M' in clean_mcap.upper():
                multiplier = 1000000
                clean_mcap = clean_mcap.upper().replace('M', '')
            elif 'B' in clean_mcap.upper():
                multiplier = 1000000000
                clean_mcap = clean_mcap.upper().replace('B', '')
            
            return float(clean_mcap) * multiplier
        except (ValueError, TypeError):
            return None

    def process_new_token(self, contract, token_data):
        """Process a new token and add it to both the global tracker and period-specific tracker"""
        current_period = self.current_hour_key
        
        # Add logging to check social info
        logging.info(f"Processing token {token_data.get('name')} with social info: {token_data.get('social_info')}")
        
        # Extract initial market cap from message_embed if available
        if 'message_embed' in token_data:
            try:
                embed_data = token_data['message_embed']
                first_field = next((f['value'] for f in embed_data['fields'] if 'value' in f), None)
                if first_field:
                    mc_match = re.search(r'MC:\s*\$([0-9,.]+[KMB]?)', first_field)
                    if mc_match:
                        mcap_str = mc_match.group(1)
                        mcap_value = self.parse_market_cap(mcap_str)
                        if mcap_value is not None:
                            token_data['initial_market_cap'] = mcap_value
                            token_data['initial_market_cap_formatted'] = f"${mcap_str}"
                            logging.info(f"Extracted initial market cap: {mcap_str} for {token_data.get('name', 'Unknown')}")
            except Exception as e:
                logging.error(f"Error extracting initial market cap: {e}")
        
        # Preserve social info if it exists
        if 'info' in token_data:
            self.hour_tokens[current_period][contract] = {
                **token_data,
                'social_info': self.token_tracker.tokens.get(contract, {}).get('social_info', {})
            }
        else:
            self.hour_tokens[current_period][contract] = token_data
        
        # Track the trade data with per-user amounts - ORGANIZED BY PERIOD
        current_period = self.current_hour_key
        if current_period not in self.hourly_trades:
            self.hourly_trades[current_period] = {}
        
        if contract not in self.hourly_trades[current_period]:
            self.hourly_trades[current_period][contract] = {'users': {}}
        
        trade_data = self.hourly_trades[current_period][contract]
        
        # Update amounts and determine action
        action = None
        if 'buy' in token_data:
            amount = token_data['buy']
            action = 'bought'
        elif 'sell' in token_data:
            amount = token_data['sell']
            action = 'sold'
        
        # Update user info only if we have an action
        if action and 'user' in token_data:
            user = token_data['user']
            if user not in trade_data['users']:
                trade_data['users'][user] = {
                    'message_link': token_data.get('message_link', ''),
                    'actions': set(),
                    'is_first_trade': token_data.get('is_first_trade', False),
                    'buys': 0.0,
                    'sells': 0.0  # Add per-user amount tracking
                }
            
            # Update the specific user's amounts
            if action == 'bought':
                trade_data['users'][user]['buys'] += amount
            else:  # sold
                trade_data['users'][user]['sells'] += amount
            
            trade_data['users'][user]['actions'].add(action)

            logging.info(f"Tracked trade: {user} {action} {token_data['name']} for ${amount}")

    @commands.command()
    async def digest(self, ctx):
        """Show the current hour's token digest on demand"""
        try:
            # Add debug logging
            logging.info(f"Running digest command")
            logging.info(f"Current hour key: {self.current_hour_key}")
            logging.info(f"Available hours: {list(self.hour_tokens.keys())}")
            logging.info(f"Current hour trades: {self.hourly_trades}")
            
            # Get tokens only from the current hour
            current_hour_tokens = self.hour_tokens.get(self.current_hour_key, OrderedDict())
            
            logging.info(f"Found {len(current_hour_tokens)} tokens for current hour")
            for token_addr, token_data in current_hour_tokens.items():
                logging.info(f"Token: {token_addr}")
                logging.info(f"Trade data: {self.hourly_trades.get(token_addr)}")
            
            # Ensure the hook is installed
            if not self.hook_installed:
                self._install_token_tracker_hook()
                await ctx.send("⚠️ Token tracking hook was not installed. Installing now...")
            
            if not current_hour_tokens:
                await ctx.send("<:dwbb:1321571679109124126>")
                return

            embeds = await self.create_digest_embed(current_hour_tokens, is_hourly=False)
            if embeds:
                for embed in embeds:
                    await ctx.send(embed=embed)
                
        except Exception as e:
            logging.error(f"Error sending digest: {e}", exc_info=True)
            await ctx.send("❌ **Error:** Unable to generate the digest.")

    def _install_token_tracker_hook(self):
        """Install hook on token_tracker if not already installed"""
        if self.hook_installed:
            logging.info("DigestCog: Token tracker hook already installed")
            return
            
        # Add debug logging
        logging.info("DigestCog: Installing token tracker hook")
        
        # Replace the token_tracker's log_token method with our wrapped version
        original_log_token = self.token_tracker.log_token
        
        def wrapped_log_token(contract, data, source, user=None):
            logging.info(f"DigestCog hook: Processing token {data.get('name', contract)} from {source}")
            # Call the original method
            result = original_log_token(contract, data, source, user)
            
            # Create a copy of the data with source and user explicitly included
            digest_data = data.copy()
            
            # Only set these if they're not already in the data
            if 'source' not in digest_data:
                digest_data['source'] = source
            if 'user' not in digest_data:
                digest_data['user'] = user if user else 'unknown'
            
            # Also add to our hour tracking
            self.process_new_token(contract, digest_data)
            
            logging.info(f"DigestCog: Processed token {data.get('name', contract)} from {digest_data.get('source')} via {digest_data.get('user')}")
            
            return result
            
        # Replace the method
        self.token_tracker.log_token = wrapped_log_token
        self.hook_installed = True
        logging.info("DigestCog: Added hook to token_tracker.log_token")

    @commands.Cog.listener()
    async def on_ready(self):
        """Set up token_tracker hook when cog is ready"""
        self._install_token_tracker_hook()
        
    @commands.command()
    async def refresh_digest(self, ctx):
        """Manually reload tokens from database and refresh the hook"""
        try:
            # Reload tokens from database
            self._load_tokens_from_db()
            
            # Reinstall the hook
            self._install_token_tracker_hook()
            
            # Log the current state
            hour_counts = {hour: len(tokens) for hour, tokens in self.hour_tokens.items()}
            
            await ctx.send(f"✅ Digest refreshed! Loaded tokens from database into {len(self.hour_tokens)} hour buckets.")
            await ctx.send(f"Current hour: {self.current_hour_key} with {len(self.hour_tokens.get(self.current_hour_key, {}))} tokens.")
            
        except Exception as e:
            logging.error(f"Error refreshing digest: {e}", exc_info=True)
            await ctx.send("❌ **Error:** Failed to refresh digest system.")

    def _clear_hour_data(self, period_key):
        """Clear the token data for a specific period after it has been processed"""
        # Clear tokens from hour_tokens
        if period_key in self.hour_tokens:
            del self.hour_tokens[period_key]
            logging.info(f"Cleared token data for period: {period_key}")
        
        # Clear trades from hourly_trades (using the new period-organized structure)
        if period_key in self.hourly_trades:
            del self.hourly_trades[period_key]
            logging.info(f"Cleared trade data for period: {period_key}")
        
        # Also clean up old data (keep only last 4 hours / 8 periods)
        self._cleanup_old_periods()
    
    def _cleanup_old_periods(self):
        """Remove old period data to prevent memory growth"""
        # Keep only the last 8 periods (4 hours worth)
        max_periods_to_keep = 8
        
        # Get current time and calculate cutoff
        now = datetime.now(self.ny_tz)
        cutoff_time = now - timedelta(hours=4)
        
        # Clean hour_tokens
        periods_to_remove = []
        for period_key in self.hour_tokens.keys():
            try:
                # Parse the period key back to datetime
                period_time = datetime.strptime(period_key, "%Y-%m-%d-%H-%M")
                period_time = self.ny_tz.localize(period_time)
                if period_time < cutoff_time:
                    periods_to_remove.append(period_key)
            except Exception as e:
                logging.error(f"Error parsing period key {period_key}: {e}")
        
        for period_key in periods_to_remove:
            del self.hour_tokens[period_key]
            logging.debug(f"Cleaned up old token data for period: {period_key}")
        
        # Clean hourly_trades with same logic
        periods_to_remove = []
        for period_key in self.hourly_trades.keys():
            try:
                period_time = datetime.strptime(period_key, "%Y-%m-%d-%H-%M")
                period_time = self.ny_tz.localize(period_time)
                if period_time < cutoff_time:
                    periods_to_remove.append(period_key)
            except Exception as e:
                logging.error(f"Error parsing period key {period_key}: {e}")
        
        for period_key in periods_to_remove:
            del self.hourly_trades[period_key]
            logging.debug(f"Cleaned up old trade data for period: {period_key}")

    def track_trade(self, token_address, token_name, user, amount, trade_type, message_link, 
                    dexscreener_url, swap_info=None, message_embed=None, is_first_trade=False, 
                    chain=None, token_data=None):
        """Track a trade for the digest"""
        try:
            if not token_address or not token_name or not user:
                logging.warning(f"Missing required trade data: address={token_address}, name={token_name}, user={user}")
                return
            
            if amount <= 0:
                logging.warning(f"Invalid trade amount: ${amount}")
                return
            
            if trade_type not in ['buy', 'sell']:
                logging.warning(f"Invalid trade type: {trade_type}")
                return
            
            current_period = self.current_hour_key
            
            # Extract chain from message_embed if not explicitly provided
            if not chain and message_embed and 'fields' in message_embed:
                for field in message_embed['fields']:
                    # Case-insensitive check for chain field
                    if field.get('name', '').lower() == 'chain':
                        chain = field.get('value', 'unknown')
                        logging.info(f"Extracted chain from embed: {chain}")
                        break
            
            # If we still don't have a chain, try to extract from dexscreener_url
            if (not chain or chain == 'unknown') and dexscreener_url:
                chain_match = re.search(r'dexscreener\.com/([^/]+)/', dexscreener_url)
                if chain_match:
                    chain = chain_match.group(1)
                    logging.info(f"Extracted chain from dexscreener URL: {chain}")
            
            # Default to solana for Cielo trades if still unknown
            if (not chain or chain == 'unknown'):
                chain = "solana"  # Most Cielo tokens are on Solana
                logging.info(f"Defaulting to solana chain for Cielo trade")
            
            # Always normalize chain
            chain = chain.lower() if chain else 'unknown'
            
            # Process new token or update existing token
            if token_address not in self.hour_tokens.get(current_period, {}):
                # Get social information from token tracker if available
                social_info = {}
                if token_data and 'social_info' in token_data:
                    social_info = token_data['social_info']
                elif self.token_tracker.tokens.get(token_address, {}).get('social_info'):
                    social_info = self.token_tracker.tokens[token_address]['social_info']
                
                # Create new token entry with all required fields and social info
                self.hour_tokens[current_period][token_address] = {
                    'name': token_name,
                    'chart_url': dexscreener_url,
                    'source': 'cielo',
                    'user': user,
                    'chain': chain,
                    'social_info': social_info,
                    'original_message_id': message_embed.get('id') if message_embed else None,
                    'original_channel_id': message_link.split('/')[5] if message_link else None,
                    'original_guild_id': message_link.split('/')[4] if message_link else None
                }
                
                # Add token_data if provided
                if token_data:
                    self.hour_tokens[current_period][token_address].update(token_data)
                
                logging.info(f"Created new token entry for {token_name} with chain={chain} and social_info={social_info}")
            else:
                # Update existing token but preserve social info
                token_entry = self.hour_tokens[current_period][token_address]
                
                # Check for social info in token_data
                if token_data and 'social_info' in token_data and token_data['social_info']:
                    token_entry['social_info'] = token_data['social_info']
                    logging.info(f"Updated social info for {token_name}: {token_data['social_info']}")
                
                # Update user if not unknown
                if user and user != "unknown":
                    token_entry['user'] = user
                
                # Set chain if provided and current value is unknown
                if chain and chain != 'unknown' and (not token_entry.get('chain') or token_entry['chain'] == 'unknown'):
                    token_entry['chain'] = chain
                    logging.info(f"Updated chain for {token_name} to {chain}")
                
                # Ensure chart_url exists
                if not token_entry.get('chart_url'):
                    token_entry['chart_url'] = dexscreener_url
            
            # Update trade tracking - ORGANIZED BY PERIOD
            if current_period not in self.hourly_trades:
                self.hourly_trades[current_period] = {}
            
            if token_address not in self.hourly_trades[current_period]:
                self.hourly_trades[current_period][token_address] = {'users': {}}
            
            trade_data = self.hourly_trades[current_period][token_address]
            
            # Initialize or update user data
            if user not in trade_data['users']:
                trade_data['users'][user] = {
                    'message_link': message_link,
                    'actions': set(),
                    'is_first_trade': is_first_trade,
                    'buys': 0.0,
                    'sells': 0.0
                }
            
            # Update the specific user's amounts and actions
            if trade_type == 'buy':
                trade_data['users'][user]['buys'] += amount
                trade_data['users'][user]['actions'].add('buy')
            else:  # sell
                trade_data['users'][user]['sells'] += amount
                trade_data['users'][user]['actions'].add('sell')
            
            # Update message link if newer
            if message_link and trade_data['users'][user]['message_link']:
                try:
                    current_msg_id = int(trade_data['users'][user]['message_link'].split('/')[-1])
                    new_msg_id = int(message_link.split('/')[-1])
                    if new_msg_id > current_msg_id:
                        trade_data['users'][user]['message_link'] = message_link
                except (ValueError, IndexError) as e:
                    logging.warning(f"Error comparing message IDs, using new link: {e}")
                    trade_data['users'][user]['message_link'] = message_link
            else:
                trade_data['users'][user]['message_link'] = message_link or trade_data['users'][user]['message_link']
            
            logging.info(f"Tracked {trade_type}: {user} {trade_type} {token_name} for ${amount} on {chain}")
            logging.info(f"User {user} message link: {trade_data['users'][user]['message_link']}")
            
        except Exception as e:
            logging.error(f"Error tracking trade: {e}", exc_info=True)

    def _format_trade_info(self, trade_data, for_current_hour=True):
        """Format trade information for a token
        
        Args:
            trade_data: The trade data for the token
            for_current_hour: If True, only show trades from the current hour (unused - kept for API compatibility)
                             The trade data should already be filtered by hour before calling this function
        """
        # Group users by their trades
        user_trades = []
        
        for user, user_data in trade_data['users'].items():
            # Create user link if we have a message_link
            user_link = f"[{user}]({user_data['message_link']})" if user_data.get('message_link') else user
            buy_amount = user_data.get('buys', 0)
            sell_amount = user_data.get('sells', 0)
            is_first = user_data.get('is_first_trade', False)
            
            # Format amounts
            trade_parts = []
            if buy_amount > 0:
                formatted_buy = format_large_number(buy_amount)
                trade_parts.append(f"${formatted_buy} buy")
            if sell_amount > 0:
                formatted_sell = format_large_number(sell_amount)
                trade_parts.append(f"${formatted_sell} sell")
            
            if trade_parts:
                star = " ⭐" if is_first else ""
                user_trades.append(f"{user_link} {', '.join(trade_parts)}{star}")
        
        return "\n".join(user_trades) if user_trades else ""

    def _format_social_links(self, token_data):
        """Format social links for display in digest"""
        social_parts = []
        
        if 'social_info' in token_data:
            info = token_data['social_info']
            logging.info(f"Processing social info: {info}")
            
            # Add website if available
            websites = info.get('websites', [])
            if isinstance(websites, list) and websites:
                if isinstance(websites[0], dict) and 'url' in websites[0]:
                    social_parts.append(f"[web]({websites[0]['url']})")
                elif isinstance(websites[0], str):
                    social_parts.append(f"[web]({websites[0]})")
            elif websites := info.get('website'):  # Legacy format
                social_parts.append(f"[web]({websites})")
            
            # Add X/Twitter - check multiple potential formats
            socials_list = info.get('socials', [])
            if isinstance(socials_list, list):
                for social in socials_list:
                    # Handle different formats in the API response
                    if isinstance(social, dict):
                        # Check both 'platform' and 'type' fields for Twitter
                        platform = social.get('platform', '').lower()
                        typ = social.get('type', '').lower()
                        
                        if 'twitter' in platform or 'twitter' in typ:
                            if 'url' in social:
                                social_parts.append(f"[𝕏]({social['url']})")
                                logging.info(f"Found Twitter link: {social['url']}")
                                break
            
            # Check legacy Twitter format as fallback
            if not any('𝕏' in part for part in social_parts):
                if twitter := info.get('twitter'):
                    social_parts.append(f"[𝕏]({twitter})")
                    logging.info(f"Found legacy Twitter link: {twitter}")
        
        logging.info(f"Final social parts: {social_parts}")
        return social_parts  # Return empty list instead of ["no socials"]
