import discord
from discord.ext import commands, tasks
import re
import logging
import asyncio
from datetime import datetime
from utils import format_large_number, safe_api_call
from db.models import Base, Token
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean, Text # type: ignore

# Import the Hyperliquid SDK
from hyperliquid.info import Info
from hyperliquid.utils import constants

# Define the new database model for tracked wallets
class TrackedWallet(Base):
    __tablename__ = 'tracked_wallets'
    
    id = Column(Integer, primary_key=True)
    address = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255))  # Optional nickname for the wallet
    last_checked_time = Column(DateTime, default=datetime.now)
    last_trade_id = Column(String(255))  # To track the last seen trade
    added_by = Column(String(100))
    added_at = Column(DateTime, default=datetime.now)
    
    def __repr__(self):
        return f"<TrackedWallet(address='{self.address}', name='{self.name}')>"

class HyperliquidWalletGrabber(commands.Cog):
    def __init__(self, bot, token_tracker, monitor, session, digest_cog=None, channel_id=None):
        self.bot = bot
        self.token_tracker = token_tracker
        self.monitor = monitor
        self.session = session
        self.digest_cog = digest_cog
        self.db_session = bot.db_session
        self.channel_id = channel_id  # Channel to send alerts to
        
        # Flag to enable/disable alerts
        self.is_enabled = True
        
        # Initialize the Hyperliquid SDK Info client
        self.hl_info = Info(constants.MAINNET_API_URL, skip_ws=True)
        
        # Add a dictionary to track recent alerts by wallet and asset
        self.recent_alerts = {}
        
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
        
        # Start the background task
        self.check_wallets.start()
        
        # Initialize asset mappings
        self.bot.loop.create_task(self._init_asset_mappings())
    
    async def _init_asset_mappings(self):
        """Initialize asset ID to name mappings from the Hyperliquid API."""
        try:
            # Wait for bot to be ready
            await self.bot.wait_until_ready()
            
            logging.info("Initializing Hyperliquid asset mappings...")
            
            # Fetch perpetual assets
            try:
                meta_data = await asyncio.to_thread(self.hl_info.meta)
                if meta_data and "universe" in meta_data:
                    for idx, asset in enumerate(meta_data["universe"]):
                        if "name" in asset:
                            # Add both with and without @ prefix
                            self.asset_id_map[str(idx)] = asset["name"]
                            self.asset_id_map[f"@{idx}"] = asset["name"]
                            logging.debug(f"Added perpetual mapping: {idx} -> {asset['name']}")
            except Exception as e:
                logging.error(f"Error fetching perpetual assets: {e}")
            
            # Fetch spot assets
            try:
                spot_meta_data = await asyncio.to_thread(self.hl_info.spot_meta)
                
                if spot_meta_data and "universe" in spot_meta_data:
                    for idx, asset in enumerate(spot_meta_data["universe"]):
                        if "base" in asset:
                            # Spot assets use 10000 + idx as their ID according to the docs
                            spot_id = 10000 + idx
                            self.asset_id_map[str(spot_id)] = asset["base"]
                            self.asset_id_map[f"@{spot_id}"] = asset["base"]
                            logging.debug(f"Added spot mapping: {spot_id} -> {asset['base']}")
            except Exception as e:
                logging.error(f"Error fetching spot assets: {e}")
            
            logging.info(f"Initialized {len(self.asset_id_map)} Hyperliquid asset mappings")
            
        except Exception as e:
            logging.error(f"Error initializing asset mappings: {e}", exc_info=True)
            self.monitor.record_error()
    
    def cog_unload(self):
        # Stop the background task when the cog is unloaded
        self.check_wallets.cancel()
        self.cleanup_recent_alerts.cancel()
    
    @tasks.loop(seconds=60)  # Check every minute, adjust as needed
    async def check_wallets(self):
        """Check all tracked wallets for new trades."""
        try:
            # Use a fresh query to get the current list of wallets
            wallets = self.db_session.query(TrackedWallet).all()
            wallet_count = len(wallets)
            logging.info(f"Checking {wallet_count} Hyperliquid wallets for new trades")
            
            if wallet_count == 0:
                logging.debug("No wallets to check, skipping wallet check cycle")
                return
                
            for wallet in wallets:
                try:
                    # Verify wallet still exists before checking
                    wallet_check = self.db_session.query(TrackedWallet).filter_by(id=wallet.id).first()
                    if not wallet_check:
                        logging.warning(f"Wallet {wallet.address} was deleted during check cycle, skipping")
                        continue
                        
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
        try:
            # Double-check that the wallet still exists in the database
            wallet_exists = self.db_session.query(TrackedWallet).filter_by(id=wallet.id).first()
            if not wallet_exists:
                logging.warning(f"Wallet {wallet.address} no longer exists in database, skipping trade check")
                return
                
            # Use the SDK to fetch user fills (trades)
            trades_data = await asyncio.to_thread(
                self.hl_info.user_fills,
                wallet.address
            )
            
            # Log the number of trades fetched
            logging.debug(f"Fetched {len(trades_data) if trades_data else 0} trades for wallet {wallet.address}")
            
            # Update the last checked time
            wallet.last_checked_time = datetime.now()
            
            # Use the SDK to fetch user state (positions)
            positions_data = await asyncio.to_thread(
                self.hl_info.user_state,
                wallet.address
            )
            
            logging.debug(f"Fetched positions for wallet {wallet.address}")
            
            # Store positions by asset for easy lookup
            positions_by_asset = {}
            if positions_data and "assetPositions" in positions_data:
                for position in positions_data["assetPositions"]:
                    if "position" in position and "coin" in position["position"]:
                        coin = position["position"]["coin"]
                        positions_by_asset[coin] = position
            
            # Filter out trades we've already seen
            if not trades_data:
                logging.debug(f"No trades found for wallet {wallet.address}")
                try:
                    self.db_session.commit()  # Just update the last checked time
                except Exception as db_error:
                    logging.error(f"Database error updating last checked time for wallet {wallet.address}: {db_error}")
                    self.db_session.rollback()  # Roll back on error
                return
                
            # For newly added wallets, don't show old trades
            if not wallet.last_trade_id:
                # Store the most recent trade ID without sending alerts
                if trades_data:
                    # Sort by time in descending order (newest first)
                    sorted_trades = sorted(trades_data, key=lambda x: x["time"], reverse=True)
                    wallet.last_trade_id = str(sorted_trades[0]["tid"])
                    logging.info(f"Initialized wallet {wallet.address} with latest trade ID {wallet.last_trade_id}")
                try:
                    self.db_session.commit()
                except Exception as db_error:
                    logging.error(f"Database error initializing trade ID for wallet {wallet.address}: {db_error}")
                    self.db_session.rollback()  # Roll back on error
                return
                
            new_trades = self._filter_new_trades(trades_data, wallet.last_trade_id)
            
            if new_trades:
                logging.info(f"Found {len(new_trades)} new trades for wallet {wallet.address}")
                
                # Update the last seen trade ID (assuming trades are sorted by time, newest first)
                wallet.last_trade_id = str(new_trades[0]["tid"])
                try:
                    self.db_session.commit()
                except Exception as db_error:
                    logging.error(f"Database error updating trade ID for wallet {wallet.address}: {db_error}")
                    self.db_session.rollback()  # Roll back on error
                    return  # Skip sending alerts if we can't update the database
                
                # Send alerts for new trades (newest first)
                for trade in new_trades:
                    # Get position data for this asset if available
                    position_data = positions_by_asset.get(trade["coin"], {})
                    await self._send_trade_alert(wallet, trade, position_data)
            else:
                try:
                    self.db_session.commit()  # Just update the last checked time
                except Exception as db_error:
                    logging.error(f"Database error updating last checked time for wallet {wallet.address}: {db_error}")
                    self.db_session.rollback()  # Roll back on error
        
        except Exception as e:
            logging.error(f"Error checking wallet {wallet.address}: {e}", exc_info=True)
            self.monitor.record_error()
            # Make sure to rollback the session on error
            try:
                self.db_session.rollback()
            except Exception as rollback_error:
                logging.error(f"Error rolling back session: {rollback_error}")
    
    def _filter_new_trades(self, trades, last_trade_id):
        """Filter out trades we've already seen based on the last trade ID."""
        if not last_trade_id:
            # If this is the first time checking, only get the most recent trade
            return trades[:1] if trades else []
        
        # Filter trades newer than the last seen trade ID
        # Sort by time in descending order (newest first)
        sorted_trades = sorted(trades, key=lambda x: x["time"], reverse=True)
        
        new_trades = []
        for trade in sorted_trades:
            if str(trade["tid"]) == last_trade_id:
                break
            new_trades.append(trade)
        
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
    
    async def _send_trade_alert(self, wallet, trade, position_data=None):
        """Format and send a trade alert to Discord."""
        try:
            # Skip sending alerts if the grabber is disabled
            if not self.is_enabled:
                logging.debug("Skipping alert - Hyperliquid grabber is disabled")
                return
                
            # Extract trade details
            raw_coin = trade["coin"]
            coin = self._get_coin_name(raw_coin)  # Convert asset ID to readable name if needed
            direction = trade["dir"]  # e.g., "Open Long"
            size = float(trade["sz"])
            price = float(trade["px"])
            
            # Check if we've recently sent an alert for this wallet+coin combination
            alert_key = f"{wallet.address}:{coin}"
            current_time = datetime.now()
            
            if alert_key in self.recent_alerts:
                last_alert_time = self.recent_alerts[alert_key]
                # If it's been less than 1 minute since the last alert, skip this one
                if (current_time - last_alert_time).total_seconds() < 60:
                    logging.debug(f"Skipping alert for {alert_key} - cooldown period active")
                    return
            
            # Update the last alert time for this wallet+coin
            self.recent_alerts[alert_key] = current_time
            
            # Extract position details if available
            position_size = size  # Default to trade size
            entry_price = price  # Default to trade price
            unrealized_pnl = 0
            
            if position_data and "position" in position_data:
                pos = position_data["position"]
                
                # Get position size
                if "szi" in pos:
                    try:
                        position_size = float(pos["szi"])
                    except (ValueError, TypeError):
                        pass
                
                # Get entry price
                if "entryPx" in pos:
                    try:
                        entry_price = float(pos["entryPx"])
                    except (ValueError, TypeError):
                        pass
                
                # Get unrealized PnL
                if "unrealizedPnl" in pos:
                    try:
                        unrealized_pnl = float(pos["unrealizedPnl"])
                    except (ValueError, TypeError):
                        pass
            
            # Calculate position value
            position_value = position_size * entry_price
            formatted_position_value = format_large_number(position_value)
            
            # Format PnL
            pnl_sign = "+" if unrealized_pnl >= 0 else ""
            formatted_pnl = f"{pnl_sign}${format_large_number(abs(unrealized_pnl))}"
            
            # Determine position type and format direction for title
            if "Open Long" in direction:
                title_direction = "Buy"
                position_type = "Long:"
            elif "Close Long" in direction:
                title_direction = "Close Long"
                position_type = "Closed Long:"
            elif "Open Short" in direction:
                title_direction = "Sell"
                position_type = "Short:"
            elif "Close Short" in direction:
                title_direction = "Close Short"
                position_type = "Closed Short:"
            else:
                title_direction = direction
                position_type = f"{direction}:"
            
            # Create embed with the simplified format (removed leverage) and added colon after position type
            embed = discord.Embed(
                title="New HL Position",
                description=f"## {title_direction}: {coin}\nPrice: ${price}\n{position_type} ${formatted_position_value}",
                color=0x00ff00 if "Long" in direction else 0xff0000
            )
            
            # Set simplified footer with wallet name and PnL
            wallet_name = wallet.name if wallet.name else f"{wallet.address[:6]}...{wallet.address[-4:]}"
            embed.set_footer(text=f"{wallet_name} {formatted_pnl} upnl")
            
            # Send to channel
            channel = self.bot.get_channel(self.channel_id)
            if channel:
                await channel.send(embed=embed)
            else:
                logging.error(f"Could not find channel with ID {self.channel_id}")
        
        except Exception as e:
            logging.error(f"Error sending trade alert: {e}", exc_info=True)
            self.monitor.record_error()
    
    @commands.command(
        name="add_wallet",
        brief="Add a wallet to track on Hyperliquid",
        description="Add a wallet address to track trades on Hyperliquid. Format: !add_wallet 0x123...abc [name]",
        help="Adds a wallet to the Hyperliquid tracking list. The address must be a 42-character hex string starting with 0x. You can optionally provide a name for the wallet.\n\nExample: !add_wallet 0x1234567890abcdef1234567890abcdef12345678 Trader1"
    )
    async def add_wallet(self, ctx, address: str, *, name: str = None):
        """Add a wallet to track on Hyperliquid."""
        try:
            # Validate address format
            if not re.match(r'^0x[a-fA-F0-9]{40}$', address):
                await ctx.send("❌ Invalid wallet address format. Must be a 42-character hex string starting with 0x.")
                return
            
            # Check if wallet is already tracked
            existing = self.db_session.query(TrackedWallet).filter_by(address=address).first()
            if existing:
                await ctx.send(f"❌ Wallet {address} is already being tracked" + 
                              (f" as '{existing.name}'" if existing.name else ""))
                return
            
            # Add to database
            wallet = TrackedWallet(
                address=address,
                name=name,
                added_by=ctx.author.name,
                added_at=datetime.now()
            )
            self.db_session.add(wallet)
            self.db_session.commit()
            
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
    async def remove_wallet(self, ctx, address: str):
        """Remove a wallet from tracking."""
        try:
            # Temporarily pause the background task if it's running
            was_running = False
            if self.check_wallets.is_running():
                was_running = True
                self.check_wallets.cancel()
                logging.info(f"Paused wallet checking task to remove wallet {address}")
                await asyncio.sleep(1)  # Give it a moment to stop
            
            # Find the wallet in the database
            wallet = self.db_session.query(TrackedWallet).filter_by(address=address).first()
            if wallet:
                wallet_id = wallet.id  # Store ID for verification
                wallet_address = wallet.address  # Store address for logging
                
                # Delete the wallet
                self.db_session.delete(wallet)
                self.db_session.commit()
                logging.info(f"Deleted wallet {wallet_address} (ID: {wallet_id}) from database")
                
                # Verify the wallet was actually deleted
                verification = self.db_session.query(TrackedWallet).filter_by(address=address).first()
                if verification:
                    logging.error(f"Failed to delete wallet {address} - still exists in database")
                    await ctx.send("❌ Failed to remove wallet. Please try again or restart the bot.")
                else:
                    logging.info(f"Successfully verified wallet {address} was removed from database")
                    await ctx.send(f"✅ Stopped tracking Hyperliquid wallet {address}")
            else:
                await ctx.send("❌ Wallet not found in tracking list")
            
            # Restart the background task if it was running
            if was_running:
                self.check_wallets.start()
                logging.info("Resumed wallet checking task")
        
        except Exception as e:
            logging.error(f"Error removing wallet: {e}", exc_info=True)
            await ctx.send("❌ An error occurred while removing the wallet.")
            self.monitor.record_error()
            
            # Make sure the task is restarted even if there was an error
            if 'was_running' in locals() and was_running and not self.check_wallets.is_running():
                try:
                    self.check_wallets.start()
                    logging.info("Resumed wallet checking task after error")
                except Exception as restart_error:
                    logging.error(f"Failed to restart wallet checking task: {restart_error}")
    
    @commands.command(
        name="list_wallets",
        brief="List all tracked Hyperliquid wallets",
        description="Display a list of all wallets being tracked on Hyperliquid",
        help="Shows a list of all wallets currently being tracked on Hyperliquid, including their names (if provided), who added them, and when they were last checked."
    )
    async def list_wallets(self, ctx):
        """List all tracked Hyperliquid wallets."""
        try:
            wallets = self.db_session.query(TrackedWallet).all()
            if not wallets:
                await ctx.send("No Hyperliquid wallets are currently being tracked.")
                return
            
            embed = discord.Embed(title="Tracked Hyperliquid Wallets", color=0x5b594f)
            for wallet in wallets:
                name = f"{wallet.name} " if wallet.name else ""
                embed.add_field(
                    name=f"{name}({wallet.address})",
                    value=f"Added by: {wallet.added_by}\nLast checked: {wallet.last_checked_time.strftime('%Y-%m-%d %H:%M:%S')}",
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
            color=0x5b594f
        )
        
        commands_text = (
            "`!add_wallet <address> [name]` - Add a wallet to track on Hyperliquid\n"
            "`!remove_wallet <address>` - Remove a wallet from tracking\n"
            "`!list_wallets` - List all tracked Hyperliquid wallets\n"
            "`!toggle_hl_alerts` - Toggle Hyperliquid position alerts on/off\n"
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
                
            # Stop the background task if it's running
            was_running = False
            if self.check_wallets.is_running():
                was_running = True
                self.check_wallets.cancel()
                logging.info("Stopped wallet checking task for refresh")
                await asyncio.sleep(1)  # Give it a moment to stop
            
            # Refresh the database session
            try:
                # Close the current session
                self.db_session.close()
                # Get a fresh session from the bot
                self.db_session = self.bot.db.get_session()
                logging.info("Refreshed database session for wallet tracker")
            except Exception as db_error:
                logging.error(f"Error refreshing database session: {db_error}", exc_info=True)
                await ctx.send("❌ Error refreshing database session. Check logs for details.")
                self.monitor.record_error()
                return
            
            # Restart the background task
            try:
                self.check_wallets.start()
                logging.info("Restarted wallet checking task after refresh")
                await ctx.send("✅ Successfully refreshed wallet tracker")
            except Exception as restart_error:
                logging.error(f"Error restarting wallet checking task: {restart_error}", exc_info=True)
                await ctx.send("❌ Error restarting wallet checking task. Check logs for details.")
                self.monitor.record_error()
        
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
