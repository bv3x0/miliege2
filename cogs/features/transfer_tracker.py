import discord
from discord import app_commands
from discord.ext import commands
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
    """Tracks transfers to/from unknown wallets and generates CSV reports on demand."""

    def __init__(self, bot, output_channel_id: Optional[int] = None):
        self.bot = bot
        self.output_channel_id = output_channel_id
        self.ny_tz = pytz.timezone('America/New_York')
        self.data_dir = "data"
        self.data_file = os.path.join(self.data_dir, "unknown_transfers.json")

        # Safety caps to prevent unbounded growth
        self.retention_days = 90  # Max age of records
        self.max_records = 5000   # Max number of records

        # Ensure data directory exists
        os.makedirs(self.data_dir, exist_ok=True)

        # Load existing data
        self.data = self._load_data()

        # Run cleanup on startup
        self._cleanup_old_data()

        logging.info(f"TransferTracker initialized with {len(self.data.get('transfers', []))} stored transfers")

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
                return {"transfers": []}
        return {"transfers": []}

    def _save_data(self):
        """Save transfers to JSON file."""
        try:
            with open(self.data_file, 'w') as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            logging.error(f"Error saving transfers: {e}")

    def _cleanup_old_data(self):
        """Remove transfers older than retention period or exceeding max records."""
        original_count = len(self.data.get("transfers", []))

        # Remove old records (by date)
        cutoff_date = (datetime.now(self.ny_tz) - timedelta(days=self.retention_days)).strftime("%Y-%m-%d")
        self.data["transfers"] = [
            t for t in self.data.get("transfers", [])
            if t.get("date", "") >= cutoff_date
        ]

        # Trim to max records (keep newest)
        if len(self.data["transfers"]) > self.max_records:
            self.data["transfers"] = self.data["transfers"][-self.max_records:]

        removed = original_count - len(self.data["transfers"])
        if removed > 0:
            logging.info(f"Cleaned up {removed} transfers (retention: {self.retention_days} days, max: {self.max_records})")
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

            # Run cleanup periodically (every 100 transfers)
            if len(self.data["transfers"]) % 100 == 0:
                self._cleanup_old_data()

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

    def _clear_transfers(self):
        """Clear all stored transfers."""
        count = len(self.data.get("transfers", []))
        self.data["transfers"] = []
        self._save_data()
        logging.info(f"Cleared {count} transfers from storage")
        return count

    @app_commands.command(name="transfers", description="Get unknown wallet transfers CSV")
    @app_commands.describe(
        mode="'peek' to view without clearing, 'export' to get and clear data"
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="peek - view without clearing", value="peek"),
        app_commands.Choice(name="export - get and clear data", value="export"),
    ])
    @app_commands.default_permissions(manage_messages=True)
    async def transfers_csv(self, interaction: discord.Interaction, mode: str = "peek"):
        """Get unknown wallet transfers CSV.

        - peek: View current data without clearing (default)
        - export: Get all data and clear storage for next batch
        """
        await interaction.response.defer(ephemeral=True)

        try:
            transfers = self.data.get("transfers", [])

            if not transfers:
                await interaction.followup.send(
                    "No unknown wallet transfers stored.",
                    ephemeral=True
                )
                return

            # Generate CSV
            csv_buffer = self._generate_csv(transfers)
            wallet_count = len(set(t.get('known_wallet', '') for t in transfers))

            # Date range for display
            dates = sorted(set(t.get('date', '') for t in transfers))
            if len(dates) == 1:
                date_range = dates[0]
            else:
                date_range = f"{dates[0]} to {dates[-1]}"

            # Create embed
            embed = discord.Embed(color=0x5b594f)
            embed.set_author(name="Unknown Wallet Transfers")

            if mode == "export":
                embed.description = f"### Export (Clearing Data)\n{len(transfers)} transfers from {wallet_count} tracked wallets\nDate range: {date_range}"
            else:
                embed.description = f"### Preview (Data Retained)\n{len(transfers)} transfers from {wallet_count} tracked wallets\nDate range: {date_range}"

            # Send to channel
            channel = interaction.channel
            timestamp = datetime.now(self.ny_tz).strftime("%Y%m%d_%H%M%S")
            filename = f"unknown_transfers_{timestamp}.csv"
            csv_bytes = io.BytesIO(csv_buffer.getvalue().encode('utf-8'))
            file = discord.File(csv_bytes, filename=filename)

            await channel.send(embed=embed, file=file)

            # Clear data if mode is 'export'
            if mode == "export":
                self._clear_transfers()
                await interaction.followup.send(
                    f"CSV generated with {len(transfers)} transfers. Data cleared.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"CSV generated with {len(transfers)} transfers. Data retained (use 'export' to clear).",
                    ephemeral=True
                )

        except Exception as e:
            logging.error(f"Error generating CSV: {e}", exc_info=True)
            await interaction.followup.send(
                "Error generating CSV. Check logs for details.",
                ephemeral=True
            )

    @app_commands.command(name="transfers_count", description="Check how many unknown wallet transfers are stored")
    @app_commands.default_permissions(manage_messages=True)
    async def transfers_count(self, interaction: discord.Interaction):
        """Quick check of stored transfer count without generating CSV."""
        transfers = self.data.get("transfers", [])
        count = len(transfers)

        if count == 0:
            await interaction.response.send_message(
                "No unknown wallet transfers stored.",
                ephemeral=True
            )
        else:
            wallet_count = len(set(t.get('known_wallet', '') for t in transfers))
            dates = sorted(set(t.get('date', '') for t in transfers))
            date_range = f"{dates[0]} to {dates[-1]}" if len(dates) > 1 else dates[0]

            await interaction.response.send_message(
                f"**{count}** transfers from **{wallet_count}** wallets stored\n"
                f"Date range: {date_range}\n"
                f"Use `/transfers peek` to preview or `/transfers export` to export and clear.",
                ephemeral=True
            )
