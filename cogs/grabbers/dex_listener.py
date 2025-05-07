import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import discord
import websockets
from discord.ext import commands, tasks

from cogs.utils import (
    format_large_number,
    format_age,
    DexScreenerAPI,
)
from cogs.utils.format import Colors

# WebSocket URL for trending pairs
WS_URL = "wss://io.dexscreener.com/dex/screener/v5/pairs/h24/1?rankBy[key]=trendingScoreH1&rankBy[order]=desc&filters[chainIds][0]=solana&filters[chainIds][1]=ethereum&filters[chainIds][2]=base&filters[liquidity][min]=15000&filters[pairAge][min]=3&filters[pairAge][max]=240&filters[volume][h1][min]=50000"

# Default timeout for WebSocket connection
WS_TIMEOUT = 60  # seconds

class DexListener(commands.Cog):
    """
    Listens to DexScreener WebSocket for trending pairs on Solana, Ethereum, and Base.
    Provides !trending command and posts hourly updates to a designated channel.
    """
    def __init__(self, bot, output_channel_id=None):
        self.bot = bot
        self.output_channel_id = output_channel_id
        self.trending_pairs = []
        self.last_update = None
        self.session = bot.session  # Use bot's shared aiohttp session
        self.reconnect_delay = 5  # Initial reconnect delay in seconds
        self.max_reconnect_delay = 300  # Maximum reconnect delay (5 minutes)
        
        # Start the background tasks
        self.dex_screener_task.start()
        self.hourly_post_task.start()
        
        logging.info("DexListener cog initialized")

    def cog_unload(self):
        """Clean up tasks when cog is unloaded"""
        self.dex_screener_task.cancel()
        self.hourly_post_task.cancel()
        logging.info("DexListener tasks cancelled")

    @tasks.loop(minutes=5)
    async def dex_screener_task(self):
        """Background task to connect to WebSocket and keep data updated"""
        while True:
            try:
                logging.info("🔌 Connecting to DexScreener WebSocket...")
                
                # Connect to WebSocket using standard parameters
                async with websockets.connect(
                    WS_URL,
                    origin="https://dexscreener.com",
                    timeout=WS_TIMEOUT
                ) as ws:
                    logging.info("✅ Connected to DexScreener WebSocket")
                    self.reconnect_delay = 5  # Reset reconnect delay on successful connection
                    
                    while True:
                        try:
                            # Receive data with timeout
                            message = await asyncio.wait_for(ws.recv(), timeout=WS_TIMEOUT)
                            data = json.loads(message)
                            
                            # Process new data
                            await self._process_dex_data(data)
                            
                            # Store update time
                            self.last_update = datetime.now(timezone.utc)
                            
                            # Wait before next update
                            await asyncio.sleep(300)  # 5 minutes
                            
                        except asyncio.TimeoutError:
                            logging.warning("WebSocket timeout, sending ping to keep connection alive")
                            pong_waiter = await ws.ping()
                            try:
                                await asyncio.wait_for(pong_waiter, timeout=10)
                                logging.info("Received pong from WebSocket")
                            except asyncio.TimeoutError:
                                logging.error("WebSocket ping timeout, reconnecting...")
                                break
                        
                        except websockets.exceptions.ConnectionClosed as e:
                            logging.error(f"WebSocket connection closed: {e}")
                            break
                            
                        except Exception as e:
                            logging.error(f"Error processing WebSocket data: {e}")
                            break
            
            except Exception as e:
                logging.error(f"Failed to connect to WebSocket: {e}")
                
                # Exponential backoff for reconnect
                await asyncio.sleep(self.reconnect_delay)
                self.reconnect_delay = min(self.reconnect_delay * 2, self.max_reconnect_delay)
                logging.info(f"Reconnecting in {self.reconnect_delay} seconds...")

    @dex_screener_task.before_loop
    async def before_dex_screener_task(self):
        """Wait until bot is ready before starting the task"""
        await self.bot.wait_until_ready()
        logging.info("Bot ready, starting DexScreener task")

    @tasks.loop(hours=1)
    async def hourly_post_task(self):
        """Send hourly updates of trending pairs to designated channel"""
        if not self.output_channel_id:
            logging.error("No output channel ID set for hourly posts")
            return
            
        channel = self.bot.get_channel(self.output_channel_id)
        if not channel:
            logging.error(f"Channel not found: {self.output_channel_id}")
            return
            
        if not self.trending_pairs:
            logging.warning("No trending pairs available for hourly post")
            return
            
        try:
            logging.info(f"Sending hourly trending update to channel {channel.name}")
            embeds = await self._create_trending_embeds()
            for embed in embeds:
                await channel.send(embed=embed)
        except Exception as e:
            logging.error(f"Error posting hourly update: {e}")

    @hourly_post_task.before_loop
    async def before_hourly_post_task(self):
        """Wait until bot is ready and align to the hour"""
        await self.bot.wait_until_ready()
        
        # Wait until we have data
        while not self.trending_pairs:
            await asyncio.sleep(30)
            
        # Align to start of next hour
        now = datetime.now(timezone.utc)
        next_hour = now.replace(minute=0, second=0, microsecond=0)
        if now.minute != 0 or now.second != 0:
            next_hour = next_hour.replace(hour=next_hour.hour + 1)
            
        wait_seconds = (next_hour - now).total_seconds()
        logging.info(f"Hourly task will start in {wait_seconds} seconds")
        await asyncio.sleep(wait_seconds)

    async def _process_dex_data(self, data: Dict[str, Any]) -> None:
        """Process incoming WebSocket data and update trending pairs"""
        if "pairs" not in data or not data["pairs"]:
            logging.warning("No pairs data in WebSocket response")
            return
            
        # Clear and reload with new data
        self.trending_pairs.clear()
        
        # Extract and process top 15 pairs
        for pair in data["pairs"][:15]:
            # Extract token data
            token_data = await self._extract_token_data(pair)
            if token_data:
                self.trending_pairs.append(token_data)
                
        logging.info(f"Updated trending pairs: {len(self.trending_pairs)} tokens")

    async def _extract_token_data(self, pair: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract and format token data from pair information"""
        try:
            # Basic token data
            base_token = pair.get("baseToken", {})
            quote_token = pair.get("quoteToken", {})
            
            # Token details
            token_address = base_token.get("address")
            symbol = base_token.get("symbol", "Unknown")
            name = base_token.get("name", symbol)
            chain_id = pair.get("chainId", "unknown")
            
            # Marketing data
            liquidity_usd = pair.get("liquidity", {}).get("usd", 0)
            market_cap = pair.get("marketCapUsd", pair.get("fdv", 0))
            volume_1h = pair.get("volume", {}).get("h1", 0)
            price_change_24h = pair.get("priceChange", {}).get("h24", "0")
            pair_created_at = pair.get("pairCreatedAt")
            
            # Format numbers
            formatted_mcap = f"${format_large_number(market_cap)}"
            formatted_change = f"{price_change_24h}%" if price_change_24h else "0%"
            
            # Get pair age
            age = format_age(pair_created_at) if pair_created_at else "?"
            
            # Get DexScreener URL
            pair_address = pair.get("pairAddress")
            dex_url = f"https://dexscreener.com/{chain_id.lower()}/{pair_address}"
            
            # Extract social info from pair.info
            social_info = {}
            
            # Get info from pair if available, otherwise fetch it
            if "info" in pair and pair["info"]:
                social_info = pair["info"]
            elif token_address:
                # Fetch additional token info from DexScreener API
                token_details = await DexScreenerAPI.get_token_info(self.session, token_address)
                if token_details and "pairs" in token_details and token_details["pairs"]:
                    if "info" in token_details["pairs"][0]:
                        social_info = token_details["pairs"][0]["info"]
            
            # Social links formatting
            formatted_socials = self._format_social_links(social_info)
            
            return {
                "name": name,
                "symbol": symbol,
                "address": token_address,
                "pair_address": pair_address,
                "chain": chain_id,
                "liquidity": liquidity_usd,
                "market_cap": market_cap,
                "formatted_mcap": formatted_mcap,
                "volume_1h": volume_1h,
                "price_change_24h": price_change_24h,
                "formatted_change": formatted_change,
                "pair_created_at": pair_created_at,
                "age": age,
                "dex_url": dex_url,
                "social_info": social_info,
                "formatted_socials": formatted_socials
            }
        except Exception as e:
            logging.error(f"Error extracting token data: {e}")
            return None

    def _format_social_links(self, social_info: Dict[str, Any]) -> List[str]:
        """Format social links for display in embeds"""
        social_parts = []
        
        # Add website if available
        websites = social_info.get("websites", [])
        if isinstance(websites, list) and websites:
            if isinstance(websites[0], dict) and "url" in websites[0]:
                social_parts.append(f"[web]({websites[0]['url']})")
            elif isinstance(websites[0], str):
                social_parts.append(f"[web]({websites[0]})")
        elif website := social_info.get("website"):  # Legacy format
            social_parts.append(f"[web]({website})")
            
        # Add X/Twitter
        socials_list = social_info.get("socials", [])
        if isinstance(socials_list, list):
            for social in socials_list:
                if isinstance(social, dict):
                    platform = social.get("platform", "").lower()
                    typ = social.get("type", "").lower()
                    
                    # Check for Twitter in multiple formats
                    if "twitter" in platform or "twitter" in typ or "x" in platform:
                        if "url" in social:
                            social_parts.append(f"[𝕏]({social['url']})")
                            break
        
        # Check legacy Twitter format as fallback
        if not any("𝕏" in part for part in social_parts):
            if twitter := social_info.get("twitter"):
                social_parts.append(f"[𝕏]({twitter})")
        
        return social_parts

    async def _create_trending_embeds(self) -> List[discord.Embed]:
        """Create Discord embeds for trending pairs in the 'Latest Alerts' style"""
        if not self.trending_pairs:
            return []
            
        embeds = []
        current_description_lines = []
        
        # Create embed with trending pairs
        for pair in self.trending_pairs:
            # Token name with link to DexScreener
            token_line = f"### [{pair['name']}]({pair['dex_url']})"
            
            # Market cap and 24h price change on one line
            stats_line = f"{pair['formatted_mcap']} mc ({pair['formatted_change']} 24h) ⋅ {pair['age']} ⋅ {pair['chain'].lower()}"
            
            # Add social links if available
            if pair['formatted_socials']:
                social_line = " ⋅ ".join(pair['formatted_socials'])
                # Add the social line only if it's not empty
                lines = [token_line, stats_line, social_line]
            else:
                lines = [token_line, stats_line]
            
            # Check if adding these lines would exceed Discord's limit
            potential_description = "\n".join(current_description_lines + lines)
            if len(potential_description) > 4000 and current_description_lines:
                # Create new embed with current lines
                embed = discord.Embed(color=Colors.EMBED_BORDER)
                embed.set_author(name="🔥 Trending Pairs")
                embed.description = "\n".join(current_description_lines)
                embeds.append(embed)
                
                # Start new collection of lines
                current_description_lines = lines
            else:
                current_description_lines.extend(lines)
                # Add a separator between tokens
                current_description_lines.append("")
        
        # Create final embed with any remaining lines
        if current_description_lines:
            embed = discord.Embed(color=Colors.EMBED_BORDER)
            embed.set_author(name="🔥 Trending Pairs")
            embed.description = "\n".join(current_description_lines)
            
            # Add timestamp
            embed.timestamp = datetime.now(timezone.utc)
            
            embeds.append(embed)
        
        return embeds

    @commands.command()
    async def trending(self, ctx):
        """Shows the top 15 trending pairs from Solana, Ethereum, and Base"""
        if not self.trending_pairs:
            await ctx.send("⚠️ Data not available yet, try again in a minute.")
            return
            
        try:
            embeds = await self._create_trending_embeds()
            for embed in embeds:
                await ctx.send(embed=embed)
        except Exception as e:
            logging.error(f"Error sending trending: {e}")
            await ctx.send("❌ Error generating trending pairs display.")

    @commands.command()
    async def trending_status(self, ctx):
        """Shows status of the DexScreener connection"""
        embed = discord.Embed(
            title="DexScreener Status",
            color=Colors.EMBED_BORDER
        )
        
        # Add status fields
        embed.add_field(
            name="Connection", 
            value="✅ Connected" if self.trending_pairs else "❌ Disconnected"
        )
        
        if self.last_update:
            time_diff = (datetime.now(timezone.utc) - self.last_update).total_seconds() / 60
            last_update = f"{int(time_diff)}m ago"
        else:
            last_update = "Never"
            
        embed.add_field(name="Last Update", value=last_update)
        embed.add_field(name="Pairs Tracked", value=str(len(self.trending_pairs)))
        
        await ctx.send(embed=embed)

def setup(bot):
    """Add the cog to the bot"""
    # Try to get output channel ID from settings
    output_channel_id = None
    try:
        from cogs.utils.config import settings
        if hasattr(settings, 'DAILY_DIGEST_CHANNEL_ID'):
            output_channel_id = settings.DAILY_DIGEST_CHANNEL_ID
            logging.info(f"Using output channel from settings: {output_channel_id}")
    except ImportError:
        pass
    
    bot.add_cog(DexListener(bot, output_channel_id))
    logging.info("DexListener cog loaded")