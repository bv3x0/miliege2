import discord
from discord import app_commands
from discord.ext import commands, tasks
import feedparser
import logging
import json
import os
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urlparse


class RSSMonitor(commands.Cog):
    """Monitors multiple RSS feeds and posts new items to Discord channels."""

    def __init__(self, bot, default_channel_id: Optional[int] = None):
        self.bot = bot
        self.default_channel_id = default_channel_id
        self.data_dir = "data"
        self.feeds_file = os.path.join(self.data_dir, "rss_feeds.json")
        self.old_seen_file = os.path.join(self.data_dir, "rss_seen_items.txt")
        self.check_interval_seconds = 60  # Check every minute, but each feed has its own interval

        # Ensure data directory exists
        os.makedirs(self.data_dir, exist_ok=True)

        # Load feeds (handles migration from old format)
        self.data = self._load_feeds()

        feed_count = len(self.data.get("feeds", []))
        logging.info(f"RSSMonitor initialized with {feed_count} feed(s)")

    def _load_feeds(self) -> Dict:
        """Load feeds from JSON file, migrating from old format if needed."""
        # Check for existing JSON file
        if os.path.exists(self.feeds_file):
            try:
                with open(self.feeds_file, 'r') as f:
                    data = json.load(f)
                total_seen = sum(len(items) for items in data.get("seen_items", {}).values())
                logging.info(f"Loaded {len(data.get('feeds', []))} RSS feeds, {total_seen} seen items")
                return data
            except Exception as e:
                logging.error(f"Error loading RSS feeds file: {e}")
                return {"feeds": [], "seen_items": {}}

        # No JSON file - check for migration scenario
        if self.default_channel_id and os.path.exists(self.old_seen_file):
            logging.info("Migrating from old RSS format to multi-feed JSON")
            return self._migrate_from_old_format()

        # Fresh start
        logging.info("No existing RSS feeds, starting fresh")
        return {"feeds": [], "seen_items": {}}

    def _migrate_from_old_format(self) -> Dict:
        """Migrate from old single-feed text format to new JSON format."""
        seen_items = set()

        # Load old seen items
        try:
            with open(self.old_seen_file, 'r') as f:
                seen_items = set(line.strip() for line in f if line.strip())
            logging.info(f"Migrated {len(seen_items)} seen items from old format")
        except Exception as e:
            logging.error(f"Error reading old seen items: {e}")

        # Create initial feed entry
        data = {
            "feeds": [
                {
                    "name": "clone-fyi",
                    "url": "https://clone.fyi/rss.xml",
                    "channel_id": self.default_channel_id,
                    "check_interval": 300,
                    "enabled": True
                }
            ],
            "seen_items": {
                "clone-fyi": list(seen_items)
            }
        }

        # Save new format
        self._save_feeds(data)

        # Rename old file as backup
        try:
            os.rename(self.old_seen_file, self.old_seen_file + ".migrated")
            logging.info("Renamed old seen items file to .migrated")
        except Exception as e:
            logging.warning(f"Could not rename old seen items file: {e}")

        return data

    def _save_feeds(self, data: Optional[Dict] = None):
        """Save feeds to JSON file."""
        if data is None:
            data = self.data
        try:
            with open(self.feeds_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logging.error(f"Error saving RSS feeds: {e}")

    def _generate_feed_name(self, url: str) -> str:
        """Generate a feed name from URL."""
        parsed = urlparse(url)
        # Use domain without TLD, or full domain if short
        domain = parsed.netloc.replace("www.", "")
        name = domain.split('.')[0] if '.' in domain else domain

        # Ensure unique name
        existing_names = {f["name"] for f in self.data.get("feeds", [])}
        base_name = name
        counter = 1
        while name in existing_names:
            name = f"{base_name}-{counter}"
            counter += 1

        return name

    def _get_feed_by_name(self, name: str) -> Optional[Dict]:
        """Get a feed by its name."""
        for feed in self.data.get("feeds", []):
            if feed["name"].lower() == name.lower():
                return feed
        return None

    # Slash command group
    rss_group = app_commands.Group(name="rss", description="RSS feed management")

    @rss_group.command(name="add", description="Add a new RSS feed")
    @app_commands.describe(
        url="RSS feed URL",
        channel="Channel to post new items to",
        name="Optional name for the feed (auto-generated if not provided)",
        interval="Check interval in seconds (default: 300)"
    )
    @app_commands.default_permissions(manage_messages=True)
    async def add_feed(
        self,
        interaction: discord.Interaction,
        url: str,
        channel: discord.TextChannel,
        name: Optional[str] = None,
        interval: int = 300
    ):
        """Add a new RSS feed to monitor."""
        # Validate URL
        if not url.startswith(("http://", "https://")):
            await interaction.response.send_message(
                "Invalid URL. Must start with http:// or https://",
                ephemeral=True
            )
            return

        # Check if URL already exists
        for feed in self.data.get("feeds", []):
            if feed["url"] == url:
                await interaction.response.send_message(
                    f"This feed is already being monitored as `{feed['name']}`",
                    ephemeral=True
                )
                return

        # Generate name if not provided
        if not name:
            name = self._generate_feed_name(url)

        # Check if name is taken
        if self._get_feed_by_name(name):
            await interaction.response.send_message(
                f"A feed with name `{name}` already exists. Please choose a different name.",
                ephemeral=True
            )
            return

        # Validate the feed
        await interaction.response.defer(ephemeral=True)

        try:
            feed = feedparser.parse(url)
            if feed.bozo and not feed.entries:
                await interaction.followup.send(
                    f"Could not parse RSS feed. Error: {feed.bozo_exception}",
                    ephemeral=True
                )
                return
            entry_count = len(feed.entries)
        except Exception as e:
            await interaction.followup.send(
                f"Error fetching feed: {e}",
                ephemeral=True
            )
            return

        # Add the feed
        new_feed = {
            "name": name,
            "url": url,
            "channel_id": channel.id,
            "check_interval": max(60, interval),  # Minimum 60 seconds
            "enabled": True
        }

        if "feeds" not in self.data:
            self.data["feeds"] = []
        self.data["feeds"].append(new_feed)

        # Initialize seen items for this feed (mark current items as seen)
        if "seen_items" not in self.data:
            self.data["seen_items"] = {}
        self.data["seen_items"][name] = [entry.link for entry in feed.entries if hasattr(entry, 'link')]

        self._save_feeds()

        await interaction.followup.send(
            f"Added RSS feed `{name}` with {entry_count} existing items.\n"
            f"New items will be posted to {channel.mention} every {interval} seconds.",
            ephemeral=True
        )
        logging.info(f"Added RSS feed: {name} -> {channel.id}")

    @rss_group.command(name="remove", description="Remove an RSS feed")
    @app_commands.describe(name="Name of the feed to remove")
    @app_commands.default_permissions(manage_messages=True)
    async def remove_feed(self, interaction: discord.Interaction, name: str):
        """Remove an RSS feed."""
        feed = self._get_feed_by_name(name)
        if not feed:
            # Show available feeds
            feed_names = [f["name"] for f in self.data.get("feeds", [])]
            if feed_names:
                await interaction.response.send_message(
                    f"Feed `{name}` not found. Available feeds: {', '.join(feed_names)}",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "No feeds configured.",
                    ephemeral=True
                )
            return

        # Remove feed
        self.data["feeds"] = [f for f in self.data["feeds"] if f["name"].lower() != name.lower()]

        # Remove seen items
        if name in self.data.get("seen_items", {}):
            del self.data["seen_items"][name]

        self._save_feeds()

        await interaction.response.send_message(
            f"Removed RSS feed `{feed['name']}`",
            ephemeral=True
        )
        logging.info(f"Removed RSS feed: {feed['name']}")

    @rss_group.command(name="edit", description="Edit an RSS feed's channel or interval")
    @app_commands.describe(
        name="Name of the feed to edit",
        channel="New channel to post items to",
        interval="New check interval in seconds"
    )
    @app_commands.default_permissions(manage_messages=True)
    async def edit_feed(
        self,
        interaction: discord.Interaction,
        name: str,
        channel: Optional[discord.TextChannel] = None,
        interval: Optional[int] = None
    ):
        """Edit an existing RSS feed's settings."""
        feed = self._get_feed_by_name(name)
        if not feed:
            feed_names = [f["name"] for f in self.data.get("feeds", [])]
            if feed_names:
                await interaction.response.send_message(
                    f"Feed `{name}` not found. Available feeds: {', '.join(feed_names)}",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "No feeds configured.",
                    ephemeral=True
                )
            return

        if channel is None and interval is None:
            await interaction.response.send_message(
                "Please specify at least one setting to change (channel or interval).",
                ephemeral=True
            )
            return

        changes = []

        if channel is not None:
            old_channel = self.bot.get_channel(feed["channel_id"])
            feed["channel_id"] = channel.id
            changes.append(f"Channel: {old_channel.mention if old_channel else 'unknown'} → {channel.mention}")

        if interval is not None:
            old_interval = feed["check_interval"]
            feed["check_interval"] = max(60, interval)
            changes.append(f"Interval: {old_interval}s → {feed['check_interval']}s")

        self._save_feeds()

        await interaction.response.send_message(
            f"Updated feed `{feed['name']}`:\n" + "\n".join(changes),
            ephemeral=True
        )
        logging.info(f"Edited RSS feed {feed['name']}: {', '.join(changes)}")

    @edit_feed.autocomplete('name')
    async def edit_feed_name_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str
    ) -> List[app_commands.Choice[str]]:
        """Autocomplete for feed names in edit command."""
        feeds = self.data.get("feeds", [])
        return [
            app_commands.Choice(name=feed["name"], value=feed["name"])
            for feed in feeds
            if current.lower() in feed["name"].lower()
        ][:25]

    @rss_group.command(name="list", description="List all RSS feeds")
    async def list_feeds(self, interaction: discord.Interaction):
        """List all configured RSS feeds."""
        feeds = self.data.get("feeds", [])

        if not feeds:
            await interaction.response.send_message(
                "No RSS feeds configured. Use `/rss add` to add one.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="RSS Feeds",
            color=0x5b594f
        )

        for feed in feeds:
            channel = self.bot.get_channel(feed["channel_id"])
            channel_name = channel.mention if channel else f"#{feed['channel_id']}"
            seen_count = len(self.data.get("seen_items", {}).get(feed["name"], []))
            status = "Enabled" if feed.get("enabled", True) else "Disabled"

            embed.add_field(
                name=feed["name"],
                value=f"**URL:** {feed['url']}\n"
                      f"**Channel:** {channel_name}\n"
                      f"**Interval:** {feed['check_interval']}s\n"
                      f"**Seen items:** {seen_count}\n"
                      f"**Status:** {status}",
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @remove_feed.autocomplete('name')
    async def feed_name_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str
    ) -> List[app_commands.Choice[str]]:
        """Autocomplete for feed names."""
        feeds = self.data.get("feeds", [])
        return [
            app_commands.Choice(name=feed["name"], value=feed["name"])
            for feed in feeds
            if current.lower() in feed["name"].lower()
        ][:25]

    @commands.Cog.listener()
    async def on_ready(self):
        """Start the RSS check loop when the bot is ready."""
        if not self.check_rss_feeds.is_running():
            self.check_rss_feeds.start()
            logging.info(f"RSSMonitor started - checking feeds every {self.check_interval_seconds} seconds")

    def cog_unload(self):
        """Stop the loop when the cog is unloaded."""
        self.check_rss_feeds.cancel()
        logging.info("RSSMonitor stopped")

    @tasks.loop(seconds=60)
    async def check_rss_feeds(self):
        """Check all RSS feeds for new items."""
        feeds = self.data.get("feeds", [])
        if not feeds:
            return

        current_time = datetime.now()

        for feed in feeds:
            if not feed.get("enabled", True):
                continue

            # Check if enough time has passed for this feed
            last_check_key = f"_last_check_{feed['name']}"
            last_check = getattr(self, last_check_key, None)

            if last_check:
                elapsed = (current_time - last_check).total_seconds()
                if elapsed < feed.get("check_interval", 300):
                    continue

            setattr(self, last_check_key, current_time)

            try:
                await self._check_single_feed(feed)
            except Exception as e:
                logging.error(f"Error checking feed {feed['name']}: {e}", exc_info=True)

    async def _check_single_feed(self, feed: Dict):
        """Check a single RSS feed for new items."""
        feed_name = feed["name"]

        logging.debug(f"Checking RSS feed: {feed_name}")

        # Parse the feed
        parsed = feedparser.parse(feed["url"])

        if parsed.bozo and not parsed.entries:
            logging.warning(f"RSS feed {feed_name} warning: {parsed.bozo_exception}")
            return

        channel = self.bot.get_channel(feed["channel_id"])
        if not channel:
            logging.error(f"RSS channel not found for {feed_name}: {feed['channel_id']}")
            return

        # Get seen items for this feed
        seen_items = set(self.data.get("seen_items", {}).get(feed_name, []))
        new_items_count = 0

        # Check each item
        for entry in parsed.entries:
            if not hasattr(entry, 'link'):
                continue

            item_id = entry.link

            if item_id not in seen_items:
                try:
                    await channel.send(entry.link)
                    seen_items.add(item_id)
                    new_items_count += 1
                    logging.info(f"Posted RSS item from {feed_name}: {getattr(entry, 'title', item_id)}")
                except discord.HTTPException as e:
                    logging.error(f"Failed to post RSS item: {e}")

        # Update seen items
        if new_items_count > 0:
            self.data["seen_items"][feed_name] = list(seen_items)
            self._save_feeds()
            logging.info(f"Posted {new_items_count} new items from {feed_name}")

    @check_rss_feeds.before_loop
    async def before_check_rss_feeds(self):
        """Wait for bot to be ready before starting the loop."""
        await self.bot.wait_until_ready()
