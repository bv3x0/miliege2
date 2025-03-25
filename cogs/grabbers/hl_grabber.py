import discord
from discord.ext import commands, tasks
import re
import logging
import asyncio
from datetime import datetime, timedelta
from cogs.utils import (
    format_large_number,
    safe_api_call,
    UI,
    Colors,
    HyperliquidAPI
)
from collections import defaultdict, OrderedDict

# Replace the SQLAlchemy model with a simple class
class TrackedWallet:
    """Simple class to store tracked wallet information"""
    def __init__(self, address, name=None, is_active=True):
        self.address = address
        self.name = name or address[:6]  # Use first 6 chars as name if not provided
        self.is_active = is_active
        self.added_at = datetime.now()
        self.last_checked = None

class HyperliquidWalletGrabber(commands.Cog):
    def __init__(self, bot, token_tracker, monitor, session, digest_cog=None, channel_id=None):
        # Add initialization logging
        logging.info(f"Initializing HyperliquidWalletGrabber with channel_id: {channel_id}")
        self.bot = bot
        self.token_tracker = token_tracker
        self.monitor = monitor
        self.session = session
        self.digest_cog = digest_cog
        self.channel_id = channel_id  # Channel to send alerts to
        
        # Store wallets in memory instead of database
        self.wallets = []
        
        # Add wallet lock for concurrent operations
        self.wallet_locks = {}  # Dictionary to store locks per wallet
        
        # Flag to enable/disable alerts
        self.is_enabled = True
        
        # Add a dictionary to track recent alerts by wallet and asset
        self.recent_alerts = {}
        
        # Store trades for digest
        self.pending_trades = defaultdict(list)  # Organized by coin
        self.last_digest_time = datetime.now()
        
        # Asset ID to name mapping
        self.asset_id_map = {
            # Default mappings for common assets
            # Spot IDs
            "107": "HYPE",
            "@107": "HYPE",
            
            # Common perpetual IDs
            "0": "BTC",
            "@0": "BTC",
            "1": "ETH",
            "@1": "ETH",
            "2": "SOL",
            "@2": "SOL",
            "3": "MATIC",
            "@3": "MATIC",
            "4": "DOGE",
            "@4": "DOGE",
            "5": "BNB",
            "@5": "BNB",
            "6": "XRP",
            "@6": "XRP",
            "7": "ARB",
            "@7": "ARB",
            "8": "OP",
            "@8": "OP",
            "9": "LINK",
            "@9": "LINK",
            "10": "AVAX",
            "@10": "AVAX",
            "10000": "USDC",
            "@10000": "USDC",
        }
        
        # Load tracked wallets from JSON file
        self._load_wallets()
        
        # Start the background tasks
        self.check_wallets.start()
        self.send_digest.start()
        
        # Initialize asset mappings
        self.bot.loop.create_task(self._init_asset_mappings())
    
    def _load_wallets(self):
        """Load tracked wallets from a JSON file"""
        import json
        import os
        try:
            # Create data directory if it doesn't exist
            os.makedirs('data', exist_ok=True)
            
            if os.path.exists('data/wallets.json'):
                with open('data/wallets.json', 'r') as f:
                    wallet_data = json.load(f)
                    for wallet in wallet_data:
                        self.wallets.append(TrackedWallet(
                            address=wallet['address'],
                            name=wallet.get('name'),
                            is_active=wallet.get('is_active', True)
                        ))
                logging.info(f"Loaded {len(self.wallets)} tracked wallets from file")
            else:
                logging.info("No wallet file found, starting with empty wallet list")
        except Exception as e:
            logging.error(f"Error loading wallets: {e}")
            
    def _save_wallets(self):
        """Save tracked wallets to a JSON file"""
        import json
        import os
        try:
            # Create data directory if it doesn't exist
            os.makedirs('data', exist_ok=True)
            
            wallet_data = [
                {
                    'address': w.address,
                    'name': w.name,
                    'is_active': w.is_active
                }
                for w in self.wallets
            ]
            
            with open('data/wallets.json', 'w') as f:
                json.dump(wallet_data, f)
            
            logging.info(f"Saved {len(self.wallets)} wallets to file")
        except Exception as e:
            logging.error(f"Error saving wallets: {e}")

    async def add_wallet(self, address, name=None):
        """Add a wallet to track"""
        # Check if wallet already exists
        for wallet in self.wallets:
            if wallet.address.lower() == address.lower():
                # Update existing wallet
                wallet.is_active = True
                if name:
                    wallet.name = name
                self._save_wallets()  # Save after updating
                return wallet
        
        # Create new wallet
        new_wallet = TrackedWallet(address, name)
        self.wallets.append(new_wallet)
        self._save_wallets()  # Save after adding
        return new_wallet

    async def remove_wallet(self, address):
        """Remove a wallet from tracking"""
        for i, wallet in enumerate(self.wallets):
            if wallet.address.lower() == address.lower():
                del self.wallets[i]
                self._save_wallets()  # Save after removing
                return True
        return False

    async def _init_asset_mappings(self):
        """Initialize asset ID to name mappings from the Hyperliquid API."""
        try:
            await self.bot.wait_until_ready()
            logging.info("Initializing Hyperliquid asset mappings...")
            
            # Use HyperliquidAPI wrapper for both perpetual and spot assets
            meta_data = await HyperliquidAPI.get_asset_info(self.session)
            if meta_data and "universe" in meta_data:
                for idx, asset in enumerate(meta_data["universe"]):
                    if "name" in asset:
                        # Handle both perpetual and spot assets
                        self.asset_id_map[str(idx)] = asset["name"]
                        self.asset_id_map[f"@{idx}"] = asset["name"]
                        logging.debug(f"Added asset mapping: {idx} -> {asset['name']}")
            
            logging.info(f"Initialized {len(self.asset_id_map)} Hyperliquid asset mappings")
            
        except Exception as e:
            logging.error(f"Error initializing asset mappings: {e}", exc_info=True)
            self.monitor.record_error()
    
    def cog_unload(self):
        # Stop the background tasks when the cog is unloaded
        self.check_wallets.cancel()
        self.cleanup_recent_alerts.cancel()
        self.send_digest.cancel()
        
        # Clear wallet locks
        self.wallet_locks.clear()
    
    @tasks.loop(seconds=60)  # Check every minute, adjust as needed
    async def check_wallets(self):
        """Check all tracked wallets for new trades."""
        try:
            # Add debug logging for wallet checks
            wallet_count = len(self.wallets)
            logging.info(f"Checking {wallet_count} Hyperliquid wallets for new trades")
            
            if wallet_count == 0:
                logging.debug("No wallets to check, skipping wallet check cycle")
                return
                
            for wallet in self.wallets:
                try:
                    await self._check_wallet_trades(wallet)
                    # Add a small delay between wallet checks to avoid rate limiting
                    await asyncio.sleep(1)
                except Exception as wallet_error:
                    # Log error but continue with other wallets
                    logging.error(f"Error checking individual wallet {wallet.address}: {wallet_error}", exc_info=True)
                    self.monitor.record_error()
                
        except Exception as e:
            logging.error(f"Error in Hyperliquid wallet check task: {e}", exc_info=True)
            self.monitor.record_error()
    
    @check_wallets.before_loop
    async def before_check_wallets(self):
        """Wait until the bot is ready before starting the task."""
        await self.bot.wait_until_ready()
        logging.info("Starting Hyperliquid wallet monitoring task")
    
    async def _check_wallet_trades(self, wallet):
        """Check a specific wallet for new trades and fetch position data."""
        # Get or create a lock for this wallet
        if wallet.address not in self.wallet_locks:
            self.wallet_locks[wallet.address] = asyncio.Lock()
        
        async with self.wallet_locks[wallet.address]:
            try:
                # Use HyperliquidAPI instead of SDK
                trades_data = await HyperliquidAPI.get_user_fills(self.session, wallet.address)
                positions_data = await HyperliquidAPI.get_user_state(self.session, wallet.address)
                
                # Initialize positions_by_asset here, before we use it
                positions_by_asset = {}
                if positions_data and "assetPositions" in positions_data:
                    for position in positions_data["assetPositions"]:
                        if "position" in position and "coin" in position["position"]:
                            coin = position["position"]["coin"]
                            positions_by_asset[coin] = position
                
                # Add debug logging for trade filtering
                if trades_data:
                    logging.debug(f"Processing {len(trades_data)} total trades for wallet {wallet.address}")
                    logging.debug(f"Last trade ID was: {wallet.last_checked}")
                
                # Filter out trades we've already seen
                new_trades = self._filter_new_trades(trades_data, wallet.last_checked)
                
                if new_trades:
                    logging.info(f"Found {len(new_trades)} new trades for wallet {wallet.address}")
                    
                    # Update the last seen trade ID (should be the most recent trade)
                    wallet.last_checked = str(new_trades[0]["tid"])
                    
                    # Group trades by coin to process them together
                    trades_by_coin = {}
                    for trade in new_trades:
                        coin = trade["coin"]
                        if coin not in trades_by_coin:
                            trades_by_coin[coin] = []
                        trades_by_coin[coin].append(trade)
                    
                    # Process trades by coin
                    for coin, coin_trades in trades_by_coin.items():
                        # Get position data for this asset if available
                        position_data = positions_by_asset.get(coin, {})
                        
                        # Add each trade to the digest
                        for trade in coin_trades:
                            self._add_trade_to_digest(wallet, trade, position_data)
                            
                        logging.debug(f"Processed {len(coin_trades)} trades for {coin} from wallet {wallet.address}")
                else:
                    pass  # Just update the last checked time
            except Exception as e:
                logging.error(f"Error checking wallet {wallet.address}: {e}", exc_info=True)
                self.monitor.record_error()
    
    def _filter_new_trades(self, trades, last_trade_id):
        """Filter out trades we've already seen based on the last trade ID."""
        if not trades:
            return []
        
        # Sort by time in descending order (newest first)
        sorted_trades = sorted(trades, key=lambda x: x["time"], reverse=True)
        
        # If this is the first time checking, only get the most recent trade
        if not last_trade_id:
            return sorted_trades[:1]
        
        # Find all trades newer than the last seen trade ID
        new_trades = []
        for trade in sorted_trades:
            if str(trade["tid"]) == last_trade_id:
                break
            new_trades.append(trade)
        
        # Add debug logging
        if new_trades:
            logging.debug(f"Found {len(new_trades)} new trades after last trade ID {last_trade_id}")
        
        return new_trades
    
    def _calculate_leverage(self, trade, position_data=None):
        """Calculate the leverage used in a trade based on available data."""
        try:
            # First try to get leverage directly from position data if available
            if position_data and "position" in position_data:
                pos = position_data["position"]
                if "leverage" in pos:
                    try:
                        lev = float(pos["leverage"])
                        return round(lev, 1)  # Round to 1 decimal place
                    except (ValueError, TypeError):
                        pass
            
            # If we have position information in the trade, calculate leverage
            if "startPosition" in trade and trade["startPosition"] != "0":
                start_position = float(trade["startPosition"])
                size = float(trade["sz"])
                if start_position > 0:
                    return round(size / start_position, 1)
            
            # If we have margin information, use that
            if "margin" in trade and trade["margin"] != "0":
                margin = float(trade["margin"])
                size = float(trade["sz"])
                price = float(trade["px"])
                if margin > 0:
                    notional_value = size * price
                    return round(notional_value / margin, 1)
            
            # Default to 7x which is common on Hyperliquid if we can't calculate
            return "7"
        except (ValueError, ZeroDivisionError, KeyError) as e:
            logging.debug(f"Error calculating leverage: {e}")
            return "7"  # Default to 7x as fallback
    
    def _get_coin_name(self, coin):
        """Convert numeric asset IDs to human-readable coin names."""
        # Check if we need to convert the coin name
        if isinstance(coin, str):
            # If it's a numeric ID or has @ prefix, try to convert it
            if coin.startswith('@') or coin.isdigit():
                # Remove @ if present for clean lookup
                clean_coin = coin.replace('@', '')
                
                # Try to get from map, fallback to original if not found
                if coin in self.asset_id_map:
                    return self.asset_id_map[coin]
                elif clean_coin in self.asset_id_map:
                    return self.asset_id_map[clean_coin]
                
                # If not found in our map, log it for future reference
                logging.warning(f"Unknown asset ID: {coin}, consider adding to mapping")
        
        # Return the original coin name if no conversion needed or not found
        return coin
    
    def _add_trade_to_digest(self, wallet, trade, position_data=None):
        """Add a trade to the pending digest."""
        try:
            # Skip if the grabber is disabled
            if not self.is_enabled:
                logging.debug("Skipping digest addition - Hyperliquid grabber is disabled")
                return
                
            # Extract trade details
            raw_coin = trade["coin"]
            coin = self._get_coin_name(raw_coin)  # Convert asset ID to readable name if needed
            direction = trade["dir"]  # e.g., "Open Long"
            size = float(trade["sz"])
            price = float(trade["px"])
            
            # Get position data for this coin if available
            position_info = position_data.get(raw_coin, {})
            
            # Extract position details if available
            position_size = size  # Default to trade size
            entry_price = price  # Default to trade price
            
            # Try to get the most accurate position data
            if position_info and "position" in position_info:
                pos = position_info["position"]
                
                # Get position size
                if "szi" in pos:
                    try:
                        position_size = abs(float(pos["szi"]))
                        logging.debug(f"Using position size from position data: {position_size}")
                    except (ValueError, TypeError):
                        logging.debug(f"Failed to parse position size, using trade size: {size}")
                
                # Get entry price
                if "entryPx" in pos:
                    try:
                        entry_price = float(pos["entryPx"])
                        logging.debug(f"Using entry price from position data: {entry_price}")
                    except (ValueError, TypeError):
                        logging.debug(f"Failed to parse entry price, using trade price: {price}")
            
            # Calculate position value using the most accurate data
            position_value = position_size * entry_price
            
            # Determine position type
            if "Open Long" in direction:
                position_type = "Long"
            elif "Close Long" in direction:
                position_type = "Close Long"
            elif "Open Short" in direction:
                position_type = "Short"
            elif "Close Short" in direction:
                position_type = "Close Short"
            else:
                position_type = direction
            
            # Create a trade entry for the digest
            trade_entry = {
                'wallet': wallet,
                'coin': coin,
                'direction': direction,
                'position_type': position_type,
                'size': size,  # Original trade size
                'price': price,  # Original trade price
                'position_size': position_size,  # Current position size from position data if available
                'position_value': position_value,
                'realized_pnl': 0,  # Only relevant for closing trades
                'time': datetime.now()
            }
            
            # Add to pending trades, organized by coin and position type
            digest_key = f"{coin}:{position_type}"
            self.pending_trades[digest_key].append(trade_entry)
            
            logging.debug(f"Added trade to digest: {coin} {position_type} for wallet {wallet.address}, size: {size}, position size: {position_size}")
            
        except Exception as e:
            logging.error(f"Error adding trade to digest: {e}", exc_info=True)
            self.monitor.record_error()
    
    @tasks.loop(minutes=15)
    async def send_digest(self):
        """Send a digest of trades every 15 minutes if there are any."""
        try:
            if not self.is_enabled or not self.pending_trades:
                logging.info("No trades to report in Hyperliquid digest or alerts disabled")
                return
                
            logging.info(f"Preparing Hyperliquid digest with {len(self.pending_trades)} trade groups")
            
            channel = self.bot.get_channel(self.channel_id)
            if not channel:
                logging.error(f"Could not find channel with ID {self.channel_id}")
                return
            
            # Create and send the digest embed
            embed = await self._create_digest_embed()
            if embed:
                await channel.send(embed=embed)
                logging.info("Hyperliquid digest posted successfully")
            
            # Clear pending trades after sending digest
            self.pending_trades.clear()
            self.last_digest_time = datetime.now()
            
        except Exception as e:
            logging.error(f"Error sending Hyperliquid digest: {e}", exc_info=True)
            self.monitor.record_error()
    
    @send_digest.before_loop
    async def before_send_digest(self):
        """Wait until the bot is ready before starting the digest loop."""
        await self.bot.wait_until_ready()
        logging.info("Starting Hyperliquid digest task")
    
    async def _create_digest_embed(self):
        """Create a digest embed with all pending trades."""
        if not self.pending_trades:
            return None
        
        # Define position type order for sorting
        position_type_order = {
            "Long": 0,
            "Short": 1,
            "Close Long": 2,
            "Close Short": 3
        }
        
        # Sort digest keys to group by position type first, then by coin
        sorted_keys = sorted(self.pending_trades.keys(), 
                            key=lambda k: (
                                position_type_order.get(k.split(':')[1], 99),  # Position type first
                                k.split(':')[0]  # Then by coin
                            ))
        
        # Use consistent border color for all embeds
        embed = discord.Embed(
            color=Colors.EMBED_BORDER
        )
        
        # Move title to author field with icon
        embed.set_author(name="Hyperliquid", icon_url="https://static1.tokenterminal.com//hyperliquid/logo.png")
        
        # Group trades by coin and position type
        for digest_key in sorted_keys:
            trades = self.pending_trades[digest_key]
            if not trades:
                continue
                
            coin, position_type = digest_key.split(":", 1)
            
            # Determine emoji based on position type
            if "Long" in position_type and "Close" not in position_type:
                position_emoji = "🟢"  # Green circle for long
            elif "Short" in position_type and "Close" not in position_type:
                position_emoji = "🔴"  # Red circle for short
            else:
                position_emoji = "⚪"  # White circle for closes
            
            # Get the average price (weighted by size)
            total_size = sum(trade['size'] for trade in trades)
            weighted_price = sum(trade['price'] * trade['size'] for trade in trades) / total_size if total_size > 0 else 0
            
            # Format the price with appropriate precision
            if weighted_price >= 1000:
                price_str = f"${weighted_price:,.0f}"
            elif weighted_price >= 100:
                price_str = f"${weighted_price:,.1f}"
            elif weighted_price >= 1:
                price_str = f"${weighted_price:,.2f}"
            else:
                price_str = f"${weighted_price:,.4f}"
            
            # Create a section for this coin and position type
            section_title = f"{position_emoji} {position_type} {coin}"
            
            # Format the section content differently based on position type
            if "Close" in position_type:
                # For closing positions, show realized PnL
                total_realized_pnl = sum(trade['realized_pnl'] for trade in trades)
                
                # Format PnL with sign
                if total_realized_pnl >= 0:
                    pnl_sign = "+"
                else:
                    pnl_sign = ""  # Negative sign will be included in the number
                    
                formatted_pnl = f"{pnl_sign}${format_large_number(abs(total_realized_pnl))}"
                price_info = f"{price_str} entry ({formatted_pnl} pnl)"
            else:
                # For opening positions, show only entry price
                price_info = f"{price_str} entry"
            
            # Add each wallet name on a separate line with price info
            section_content = []
            wallet_names = set()
            for trade in trades:
                wallet = trade['wallet']
                wallet_name = wallet.name if wallet.name else f"{wallet.address[:6]}...{wallet.address[-4:]}"
                wallet_names.add((wallet_name, wallet.address))
            
            # Add each wallet with price info to the section content
            for wallet_name, wallet_address in wallet_names:
                # Create a hyperlink to the wallet's Hyperdash profile
                wallet_link = f"[{wallet_name}](https://hyperdash.info/trader/{wallet_address})"
                
                # Simplified format without PnL information
                section_content.append(f"{wallet_link} @ {price_str}")
            
            # Add the section to the embed
            embed.add_field(
                name=section_title,
                value="\n".join(section_content),
                inline=False
            )
        
        return embed
    
    async def _send_trade_alert(self, wallet, trade, position_data=None):
        """
        Legacy method for individual trade alerts.
        Now redirects to add_trade_to_digest.
        """
        self._add_trade_to_digest(wallet, trade, position_data)
    
    @commands.command(
        name="add_wallet",
        brief="Add a wallet to track on Hyperliquid",
        description="Add a wallet address to track trades on Hyperliquid. Format: !add_wallet 0x123...abc [name]",
        help="Adds a wallet to the Hyperliquid tracking list. The address must be a 42-character hex string starting with 0x. You can optionally provide a name for the wallet.\n\nExample: !add_wallet 0x1234567890abcdef1234567890abcdef12345678 Trader1"
    )
    async def add_wallet_command(self, ctx, address: str, *, name: str = None):
        """Add a wallet to track on Hyperliquid."""
        try:
            # Validate address format
            if not re.match(r'^0x[a-fA-F0-9]{40}$', address):
                await ctx.send("❌ Invalid wallet address format. Must be a 42-character hex string starting with 0x.")
                return
            
            # Add to database
            wallet = await self.add_wallet(address, name)
            
            await ctx.send(f"✅ Now tracking Hyperliquid wallet {address}" + 
                          (f" as '{name}'" if name else ""))
        
        except Exception as e:
            logging.error(f"Error adding wallet: {e}", exc_info=True)
            await ctx.send("❌ An error occurred while adding the wallet.")
            self.monitor.record_error()
    
    @commands.command(
        name="remove_wallet",
        brief="Remove a wallet from tracking",
        description="Remove a wallet address from the Hyperliquid tracking list. Format: !remove_wallet 0x123...abc",
        help="Removes a wallet from the Hyperliquid tracking list.\n\nExample: !remove_wallet 0x1234567890abcdef1234567890abcdef12345678"
    )
    async def remove_wallet_command(self, ctx, address: str):
        """Remove a wallet from tracking."""
        try:
            # Remove the wallet
            removed = await self.remove_wallet(address)
            
            if removed:
                await ctx.send(f"✅ Stopped tracking Hyperliquid wallet {address}")
            else:
                await ctx.send("❌ Wallet not found in tracking list")
        
        except Exception as e:
            logging.error(f"Error removing wallet: {e}", exc_info=True)
            await ctx.send("❌ An error occurred while removing the wallet.")
            self.monitor.record_error()
    
    @commands.command(
        name="list_wallets",
        brief="List all tracked Hyperliquid wallets",
        description="Display a list of all wallets being tracked on Hyperliquid",
        help="Shows a list of all wallets currently being tracked on Hyperliquid, including their names (if provided), who added them, and when they were last checked."
    )
    async def list_wallets_command(self, ctx):
        """List all tracked Hyperliquid wallets."""
        try:
            if not self.wallets:
                await ctx.send("No Hyperliquid wallets are currently being tracked.")
                return
            
            embed = discord.Embed(title="Tracked Hyperliquid Wallets", color=Colors.EMBED_BORDER)
            for wallet in self.wallets:
                name = f"{wallet.name} " if wallet.name else ""
                embed.add_field(
                    name=f"{name}({wallet.address})",
                    value=f"Added at: {wallet.added_at.strftime('%Y-%m-%d %H:%M:%S')}",
                    inline=False
                )
            
            await ctx.send(embed=embed)
        
        except Exception as e:
            logging.error(f"Error listing wallets: {e}", exc_info=True)
            await ctx.send("❌ An error occurred while listing wallets.")
            self.monitor.record_error()

    @commands.command(name="help")
    async def help_command(self, ctx):
        """Display help information for commands"""
        embed = discord.Embed(
            title="Hyperliquid Wallet Commands",
            color=Colors.EMBED_BORDER
        )
        
        commands_text = (
            "`!add_wallet <address> [name]` - Add a wallet to track on Hyperliquid\n"
            "`!remove_wallet <address>` - Remove a wallet from tracking\n"
            "`!list_wallets` - List all tracked Hyperliquid wallets\n"
            "`!toggle_hl_alerts` - Toggle Hyperliquid position alerts on/off\n"
            "`!force_hl_digest` - Force send a Hyperliquid digest\n"
            "`!refresh_wallet_tracker` - Refresh the wallet tracker (admin only)\n"
            "`!refresh_asset_mappings` - Refresh asset name mappings (admin only)"
        )
        
        embed.description = commands_text
        await ctx.send(embed=embed)

    @commands.command(
        name="refresh_wallet_tracker",
        brief="Refresh the wallet tracker",
        description="Refresh the wallet tracker by restarting the background task and refreshing the database session",
        help="Admin command to refresh the wallet tracker if there are issues with wallet tracking."
    )
    async def refresh_wallet_tracker(self, ctx):
        """Refresh the wallet tracker by restarting the background task and refreshing the database session."""
        try:
            # Check if user has admin permissions
            if not ctx.author.guild_permissions.administrator:
                await ctx.send("❌ This command requires administrator permissions.")
                return
                
            # Restart the background task
            self.check_wallets.start()
            logging.info("Restarted wallet checking task after refresh")
            await ctx.send("✅ Successfully refreshed wallet tracker")
        
        except Exception as e:
            logging.error(f"Error refreshing wallet tracker: {e}", exc_info=True)
            await ctx.send("❌ An error occurred while refreshing the wallet tracker.")
            self.monitor.record_error()

    @commands.command(
        name="refresh_asset_mappings",
        brief="Refresh Hyperliquid asset mappings",
        description="Refresh the asset ID to name mappings from the Hyperliquid API",
        help="Admin command to refresh the asset mappings if there are new assets or issues with asset name display."
    )
    async def refresh_asset_mappings(self, ctx):
        """Refresh the asset ID to name mappings from the Hyperliquid API."""
        try:
            # Check if user has admin permissions
            if not ctx.author.guild_permissions.administrator:
                await ctx.send("❌ This command requires administrator permissions.")
                return
                
            # Clear existing mappings except for the default ones
            default_mappings = {
                # Spot IDs
                "107": "HYPE",
                "@107": "HYPE",
                "10000": "USDC",
                "@10000": "USDC",
                
                # Common perpetual IDs
                "0": "BTC",
                "@0": "BTC",
                "1": "ETH",
                "@1": "ETH",
                "2": "SOL",
                "@2": "SOL",
            }
            
            # Reset to default mappings
            self.asset_id_map = default_mappings.copy()
            
            # Run the initialization task
            await self._init_asset_mappings()
            
            await ctx.send(f"✅ Successfully refreshed Hyperliquid asset mappings. Now tracking {len(self.asset_id_map)} assets.")
        
        except Exception as e:
            logging.error(f"Error refreshing asset mappings: {e}", exc_info=True)
            await ctx.send("❌ An error occurred while refreshing asset mappings.")
            self.monitor.record_error()

    @commands.command(
        name="toggle_hl_alerts",
        brief="Toggle Hyperliquid alerts on/off",
        description="Toggle whether Hyperliquid position alerts are sent to the channel",
        help="Use this command to temporarily enable or disable Hyperliquid position alerts without removing tracked wallets."
    )
    async def toggle_hl_alerts(self, ctx):
        """Toggle Hyperliquid alerts on or off."""
        try:
            # Toggle the enabled state
            self.is_enabled = not self.is_enabled
            
            # Send confirmation message
            status = "enabled" if self.is_enabled else "disabled"
            emoji = "✅" if self.is_enabled else "🔕"
            
            await ctx.send(f"{emoji} Hyperliquid position alerts are now **{status}**.")
            logging.info(f"Hyperliquid alerts {status} by {ctx.author.name}")
            
        except Exception as e:
            logging.error(f"Error toggling Hyperliquid alerts: {e}", exc_info=True)
            await ctx.send("❌ An error occurred while toggling alerts.")
            self.monitor.record_error()

    # Add a method to clean up old alerts to prevent memory leaks
    @tasks.loop(minutes=5)
    async def cleanup_recent_alerts(self):
        """Clean up old alerts from the recent_alerts dictionary."""
        try:
            current_time = datetime.now()
            keys_to_remove = []
            
            for alert_key, alert_time in self.recent_alerts.items():
                # If it's been more than 5 minutes, remove the entry
                if (current_time - alert_time).total_seconds() > 300:
                    keys_to_remove.append(alert_key)
            
            for key in keys_to_remove:
                del self.recent_alerts[key]
                
            if keys_to_remove:
                logging.debug(f"Cleaned up {len(keys_to_remove)} old alert entries")
        
        except Exception as e:
            logging.error(f"Error cleaning up recent alerts: {e}", exc_info=True)
            self.monitor.record_error()
    
    @cleanup_recent_alerts.before_loop
    async def before_cleanup_recent_alerts(self):
        """Wait until the bot is ready before starting the task."""
        await self.bot.wait_until_ready()
        logging.info("Starting recent alerts cleanup task")

    @commands.command(
        name="force_hl_digest",
        brief="Force send a Hyperliquid digest",
        description="Manually trigger a Hyperliquid digest to be sent",
        help="Use this command to immediately send a digest of recent Hyperliquid trades without waiting for the scheduled time."
    )
    async def force_hl_digest(self, ctx):
        """Manually trigger a Hyperliquid digest."""
        try:
            if not self.pending_trades:
                await ctx.send("No pending Hyperliquid trades to report.")
                return
                
            embed = await self._create_digest_embed()
            if embed:
                await ctx.send("Sending Hyperliquid digest:", embed=embed)
                
                # Also send to the configured channel if different from the current channel
                if self.channel_id and ctx.channel.id != self.channel_id:
                    channel = self.bot.get_channel(self.channel_id)
                    if channel:
                        await channel.send(embed=embed)
                
                # Clear pending trades after sending digest
                self.pending_trades.clear()
                self.last_digest_time = datetime.now()
                
                logging.info("Manual Hyperliquid digest sent successfully")
            else:
                await ctx.send("Failed to create digest embed.")
        
        except Exception as e:
            logging.error(f"Error sending manual Hyperliquid digest: {e}", exc_info=True)
            await ctx.send("❌ An error occurred while sending the digest.")
            self.monitor.record_error()
