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
        
        # Initialize the Hyperliquid SDK Info client
        self.hl_info = Info(constants.MAINNET_API_URL, skip_ws=True)
        
        # Start the background task
        self.check_wallets.start()
    
    def cog_unload(self):
        # Stop the background task when the cog is unloaded
        self.check_wallets.cancel()
    
    @tasks.loop(seconds=60)  # Check every minute, adjust as needed
    async def check_wallets(self):
        """Check all tracked wallets for new trades."""
        try:
            wallets = self.db_session.query(TrackedWallet).all()
            logging.info(f"Checking {len(wallets)} Hyperliquid wallets for new trades")
            
            for wallet in wallets:
                await self._check_wallet_trades(wallet)
                # Add a small delay between wallet checks to avoid rate limiting
                await asyncio.sleep(1)
                
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
                self.db_session.commit()  # Just update the last checked time
                return
                
            # For newly added wallets, don't show old trades
            if not wallet.last_trade_id:
                # Store the most recent trade ID without sending alerts
                if trades_data:
                    # Sort by time in descending order (newest first)
                    sorted_trades = sorted(trades_data, key=lambda x: x["time"], reverse=True)
                    wallet.last_trade_id = str(sorted_trades[0]["tid"])
                    logging.info(f"Initialized wallet {wallet.address} with latest trade ID {wallet.last_trade_id}")
                self.db_session.commit()
                return
                
            new_trades = self._filter_new_trades(trades_data, wallet.last_trade_id)
            
            if new_trades:
                logging.info(f"Found {len(new_trades)} new trades for wallet {wallet.address}")
                
                # Update the last seen trade ID (assuming trades are sorted by time, newest first)
                wallet.last_trade_id = str(new_trades[0]["tid"])
                self.db_session.commit()
                
                # Send alerts for new trades (newest first)
                for trade in new_trades:
                    # Get position data for this asset if available
                    position_data = positions_by_asset.get(trade["coin"], {})
                    await self._send_trade_alert(wallet, trade, position_data)
            else:
                self.db_session.commit()  # Just update the last checked time
        
        except Exception as e:
            logging.error(f"Error checking wallet {wallet.address}: {e}", exc_info=True)
            self.monitor.record_error()
    
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
    
    def _calculate_leverage(self, trade):
        """Calculate the leverage used in a trade based on available data."""
        # This is a simplified calculation and may need adjustment based on actual data
        try:
            # If we have position information, we can calculate leverage
            if "startPosition" in trade:
                start_position = float(trade["startPosition"])
                size = float(trade["sz"])
                if start_position > 0:
                    return round(size / start_position, 1)
            
            # Default to a placeholder if we can't calculate
            return "?"
        except (ValueError, ZeroDivisionError):
            return "?"
    
    async def _send_trade_alert(self, wallet, trade, position_data=None):
        """Format and send a trade alert to Discord."""
        try:
            # Extract trade details
            coin = trade["coin"]
            direction = trade["dir"]  # e.g., "Open Long"
            size = float(trade["sz"])
            price = float(trade["px"])
            
            # Calculate total value of this trade
            trade_value = size * price
            formatted_trade_value = format_large_number(trade_value)
            
            # Extract position details if available
            position_size = size  # Default to trade size
            entry_price = price  # Default to trade price
            unrealized_pnl = 0
            leverage = self._calculate_leverage(trade)  # Use the fallback calculation
            
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
                
                # Get leverage if available in the position data
                if "leverage" in pos:
                    try:
                        leverage = float(pos["leverage"])
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
                position_type = "Long"
            elif "Close Long" in direction:
                title_direction = "Close Long"
                position_type = "Closed Long"
            elif "Open Short" in direction:
                title_direction = "Sell"
                position_type = "Short"
            elif "Close Short" in direction:
                title_direction = "Close Short"
                position_type = "Closed Short"
            else:
                title_direction = direction
                position_type = direction
            
            # Create embed with the new format
            embed = discord.Embed(
                title="New HL Position",
                description=f"## {title_direction}: {coin}\nFilled ${formatted_trade_value} at ${price}\n{position_type} ${formatted_position_value} from ${entry_price} (on {leverage}x lev)",
                color=0x00ff00 if "Long" in direction else 0xff0000
            )
            
            # Set footer with wallet name and PnL
            wallet_name = wallet.name if wallet.name else f"{wallet.address[:6]}...{wallet.address[-4:]}"
            embed.set_footer(text=f"{wallet_name} • unrealized PnL: {formatted_pnl}")
            
            # Add timestamp
            trade_time = datetime.fromtimestamp(trade["time"] / 1000)
            embed.timestamp = trade_time
            
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
            wallet = self.db_session.query(TrackedWallet).filter_by(address=address).first()
            if wallet:
                self.db_session.delete(wallet)
                self.db_session.commit()
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
                    name=f"{name}({wallet.address[:6]}...{wallet.address[-4:]})",
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
            "`!list_wallets` - List all tracked Hyperliquid wallets"
        )
        
        embed.description = commands_text
        await ctx.send(embed=embed)
