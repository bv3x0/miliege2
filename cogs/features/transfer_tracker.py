import discord
from discord import app_commands
from discord.ext import commands, tasks
import logging
import json
import os
import re
import csv
import io
from datetime import datetime, timedelta
from typing import Optional
import pytz


class TransferTracker(commands.Cog):
    """Tracks transfers to/from unknown wallets and generates daily CSV reports."""

    def __init__(self, bot, output_channel_id: Optional[int] = None):
        self.bot = bot
        self.output_channel_id = output_channel_id
        self.ny_tz = pytz.timezone('America/New_York')
        self.data_dir = "data"
        self.data_file = os.path.join(self.data_dir, "unknown_transfers.json")
        self.retention_days = 30

        # Ensure data directory exists
        os.makedirs(self.data_dir, exist_ok=True)

        # Load existing data
        self.data = self._load_data()

        # Start daily CSV task
        self.daily_csv.start()

        logging.info(f"TransferTracker initialized with output channel: {output_channel_id}")

    def cog_unload(self):
        self.daily_csv.cancel()

    def _load_data(self) -> dict:
        """Load transfers from JSON file."""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                logging.info(f"Loaded {len(data.get('transfers', []))} transfers from file")
                return data
            except Exception as e:
                logging.error(f"Error loading transfers file: {e}")
                return {"transfers": [], "last_csv_date": None}
        return {"transfers": [], "last_csv_date": None}

    def _save_data(self):
        """Save transfers to JSON file."""
        try:
            with open(self.data_file, 'w') as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            logging.error(f"Error saving transfers: {e}")

    def _cleanup_old_data(self):
        """Remove transfers older than retention period."""
        cutoff_date = (datetime.now(self.ny_tz) - timedelta(days=self.retention_days)).strftime("%Y-%m-%d")
        original_count = len(self.data.get("transfers", []))

        self.data["transfers"] = [
            t for t in self.data.get("transfers", [])
            if t.get("date", "") >= cutoff_date
        ]

        removed = original_count - len(self.data["transfers"])
        if removed > 0:
            logging.info(f"Cleaned up {removed} transfers older than {self.retention_days} days")
            self._save_data()

    def process_transfer(self, known_wallet: str, embed_data: dict):
        """Process a transfer from CieloGrabber.

        Args:
            known_wallet: The tracked wallet name (from embed title)
            embed_data: The raw embed dict containing transfer info
        """
        try:
            fields = embed_data.get('fields', [])
            if not fields:
                return

            # Parse the transfer info from first field
            transfer_text = fields[0].get('value', '')

            # Extract direction (Received or Transferred)
            if 'Received' in transfer_text:
                direction = 'in'
            elif 'Transferred' in transfer_text:
                direction = 'out'
            else:
                logging.debug(f"Not a transfer message: {transfer_text[:50]}")
                return

            # Pattern to extract: amount, token, dollar amount, counterparty name, counterparty URL
            # Format: "Received: **1,361.15** ****USDC**** ($1,361.15) from [Relay](https://solscan.io/address/...)"
            pattern = r'(Received|Transferred):\s*\*\*([0-9,.]+)\*\*\s*\*{4}(\w+)\*{4}\s*\(\$([0-9,.]+)\)\s*(from|to)\s*\[([^\]]+)\]\((https?://[^)]+/address/([^)]+))\)'

            match = re.search(pattern, transfer_text)
            if not match:
                logging.warning(f"Could not parse transfer text: {transfer_text}")
                return

            _, token_amount, token_symbol, dollar_amount, _, counterparty_name, address_url, full_address = match.groups()

            # Check if counterparty is unknown (has ellipsis pattern)
            if '...' not in counterparty_name:
                # Known wallet, skip
                logging.debug(f"Transfer with known wallet '{counterparty_name}', skipping")
                return

            # Extract transaction link from fields
            tx_link = None
            for field in fields:
                if field.get('name') == 'Transaction':
                    # Extract URL from markdown: [Details](url)
                    tx_match = re.search(r'\[Details\]\((https?://[^)]+)\)', field.get('value', ''))
                    if tx_match:
                        tx_link = tx_match.group(1)
                    break

            # Get timestamp
            timestamp = embed_data.get('timestamp', datetime.now(self.ny_tz).isoformat())
            now = datetime.now(self.ny_tz)
            date_str = now.strftime("%Y-%m-%d")

            # Create transfer record
            transfer = {
                "date": date_str,
                "timestamp": timestamp,
                "known_wallet": known_wallet,
                "unknown_wallet_truncated": counterparty_name,
                "unknown_wallet_full": full_address,
                "direction": direction,
                "dollar_amount": float(dollar_amount.replace(',', '')),
                "token_symbol": token_symbol,
                "token_amount": token_amount,
                "tx_link": tx_link
            }

            # Add to data
            self.data["transfers"].append(transfer)
            self._save_data()

            logging.info(f"Tracked unknown wallet transfer: {known_wallet} {'received from' if direction == 'in' else 'sent to'} {counterparty_name} (${dollar_amount})")

        except Exception as e:
            logging.error(f"Error processing transfer: {e}", exc_info=True)

    def _generate_csv(self, transfers: list) -> io.StringIO:
        """Generate CSV from transfers list."""
        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow([
            'timestamp',
            'known_wallet',
            'direction',
            'unknown_wallet',
            'dollar_amount',
            'token_symbol',
            'token_amount',
            'tx_link'
        ])

        # Data rows
        for t in transfers:
            writer.writerow([
                t.get('timestamp', ''),
                t.get('known_wallet', ''),
                t.get('direction', ''),
                t.get('unknown_wallet_full', ''),
                t.get('dollar_amount', ''),
                t.get('token_symbol', ''),
                t.get('token_amount', ''),
                t.get('tx_link', '')
            ])

        output.seek(0)
        return output

    def _get_transfers_for_date(self, date_str: str) -> list:
        """Get all transfers for a specific date."""
        return [t for t in self.data.get("transfers", []) if t.get("date") == date_str]

    @tasks.loop(hours=24)
    async def daily_csv(self):
        """Send daily CSV report at 6:00 AM NY time."""
        try:
            if not self.output_channel_id:
                logging.warning("No output channel configured for TransferTracker")
                return

            channel = self.bot.get_channel(self.output_channel_id)
            if not channel:
                logging.error(f"Could not find channel {self.output_channel_id}")
                return

            # Get yesterday's date
            yesterday = (datetime.now(self.ny_tz) - timedelta(days=1)).strftime("%Y-%m-%d")
            transfers = self._get_transfers_for_date(yesterday)

            if not transfers:
                logging.info(f"No unknown wallet transfers for {yesterday}")
                return

            # Generate CSV
            csv_buffer = self._generate_csv(transfers)

            # Count unique known wallets
            wallet_count = len(set(t.get('known_wallet', '') for t in transfers))

            # Format date for display
            display_date = datetime.strptime(yesterday, "%Y-%m-%d").strftime("%B %d, %Y")

            # Create embed
            embed = discord.Embed(color=0x5b594f)
            embed.set_author(name="Unknown Wallet Transfers")
            embed.description = f"### Daily Report\n{len(transfers)} transfers from {wallet_count} tracked wallets\nDate: {display_date}"

            # Send with CSV attachment
            csv_bytes = io.BytesIO(csv_buffer.getvalue().encode('utf-8'))
            file = discord.File(csv_bytes, filename=f"unknown_transfers_{yesterday}.csv")

            await channel.send(embed=embed, file=file)

            # Update last CSV date
            self.data["last_csv_date"] = yesterday
            self._save_data()

            logging.info(f"Sent daily transfers CSV for {yesterday}: {len(transfers)} transfers")

            # Cleanup old data
            self._cleanup_old_data()

        except Exception as e:
            logging.error(f"Error in daily CSV task: {e}", exc_info=True)

    @daily_csv.before_loop
    async def before_daily_csv(self):
        """Wait until 6:00 AM NY time before starting the loop."""
        await self.bot.wait_until_ready()

        now = datetime.now(self.ny_tz)
        target = now.replace(hour=6, minute=0, second=0, microsecond=0)

        # If it's already past 6 AM, schedule for tomorrow
        if now >= target:
            target += timedelta(days=1)

        wait_seconds = (target - now).total_seconds()
        logging.info(f"TransferTracker: Daily CSV scheduled for {target.strftime('%Y-%m-%d %H:%M')} NY time (waiting {wait_seconds/3600:.1f} hours)")

        await discord.utils.sleep_until(target.replace(tzinfo=None))

    @app_commands.command(name="transfers", description="Generate unknown wallet transfers CSV")
    @app_commands.describe(
        date="Optional: specific date (YYYY-MM-DD) or 'all' for full history, 'today' for today"
    )
    @app_commands.default_permissions(manage_messages=True)
    async def transfers_csv(self, interaction: discord.Interaction, date: Optional[str] = None):
        """Manually generate and send the transfers CSV."""
        await interaction.response.defer(ephemeral=True)

        try:
            if date == 'all':
                transfers = self.data.get("transfers", [])
                date_label = "all time"
                filename = "unknown_transfers_all.csv"
            elif date == 'today':
                today = datetime.now(self.ny_tz).strftime("%Y-%m-%d")
                transfers = self._get_transfers_for_date(today)
                date_label = today
                filename = f"unknown_transfers_{today}.csv"
            elif date:
                # Validate date format
                try:
                    datetime.strptime(date, "%Y-%m-%d")
                except ValueError:
                    await interaction.followup.send(
                        "Invalid date format. Use YYYY-MM-DD, 'today', or 'all'.",
                        ephemeral=True
                    )
                    return
                transfers = self._get_transfers_for_date(date)
                date_label = date
                filename = f"unknown_transfers_{date}.csv"
            else:
                # Default: yesterday
                yesterday = (datetime.now(self.ny_tz) - timedelta(days=1)).strftime("%Y-%m-%d")
                transfers = self._get_transfers_for_date(yesterday)
                date_label = yesterday
                filename = f"unknown_transfers_{yesterday}.csv"

            if not transfers:
                await interaction.followup.send(
                    f"No unknown wallet transfers found for {date_label}.",
                    ephemeral=True
                )
                return

            # Generate CSV
            csv_buffer = self._generate_csv(transfers)
            wallet_count = len(set(t.get('known_wallet', '') for t in transfers))

            # Create embed
            embed = discord.Embed(color=0x5b594f)
            embed.set_author(name="Unknown Wallet Transfers")
            embed.description = f"### Manual Report\n{len(transfers)} transfers from {wallet_count} tracked wallets\nDate: {date_label}"

            # Send to channel (not ephemeral so others can see)
            channel = interaction.channel
            csv_bytes = io.BytesIO(csv_buffer.getvalue().encode('utf-8'))
            file = discord.File(csv_bytes, filename=filename)

            await channel.send(embed=embed, file=file)
            await interaction.followup.send(f"CSV generated with {len(transfers)} transfers.", ephemeral=True)

        except Exception as e:
            logging.error(f"Error generating manual CSV: {e}", exc_info=True)
            await interaction.followup.send(
                "Error generating CSV. Check logs for details.",
                ephemeral=True
            )
