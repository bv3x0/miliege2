import discord
from discord.ext import commands, tasks
import feedparser
import logging
import os
from datetime import datetime

class RSSMonitor(commands.Cog):
    """Monitors RSS feeds and posts new items to a Discord channel."""

    def __init__(self, bot, channel_id: int, feed_url: str = "https://clone.fyi/rss.xml",
                 check_interval: int = 300):
        self.bot = bot
        self.channel_id = channel_id
        self.feed_url = feed_url
        self.check_interval_seconds = check_interval
        self.seen_items_file = "data/rss_seen_items.txt"
        self.seen_items = set()

        # Ensure data directory exists
        os.makedirs("data", exist_ok=True)

        # Load previously seen items
        self._load_seen_items()

        logging.info(f"RSSMonitor initialized - Channel: {channel_id}, Feed: {feed_url}, Interval: {check_interval}s")

    def _load_seen_items(self):
        """Load the set of already posted item IDs from file."""
        if os.path.exists(self.seen_items_file):
            try:
                with open(self.seen_items_file, 'r') as f:
                    self.seen_items = set(line.strip() for line in f if line.strip())
                logging.info(f"Loaded {len(self.seen_items)} seen RSS items from file")
            except Exception as e:
                logging.error(f"Error loading seen items file: {e}")
                self.seen_items = set()
        else:
            logging.info("No existing seen items file, starting fresh")

    def _save_seen_item(self, item_id: str):
        """Append a new item ID to the seen items file."""
        try:
            with open(self.seen_items_file, 'a') as f:
                f.write(f"{item_id}\n")
            self.seen_items.add(item_id)
        except Exception as e:
            logging.error(f"Error saving seen item: {e}")

    @commands.Cog.listener()
    async def on_ready(self):
        """Start the RSS check loop when the bot is ready."""
        if not self.check_rss_feed.is_running():
            self.check_rss_feed.start()
            logging.info(f"RSSMonitor started - checking every {self.check_interval_seconds} seconds")

    def cog_unload(self):
        """Stop the loop when the cog is unloaded."""
        self.check_rss_feed.cancel()
        logging.info("RSSMonitor stopped")

    @tasks.loop(seconds=300)  # Default, will be updated in __init__
    async def check_rss_feed(self):
        """Check the RSS feed for new items and post them."""
        try:
            logging.debug(f"Checking RSS feed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

            # Parse the RSS feed
            feed = feedparser.parse(self.feed_url)

            if feed.bozo:
                logging.warning(f"RSS feed warning: {feed.bozo_exception}")

            channel = self.bot.get_channel(self.channel_id)
            if not channel:
                logging.error(f"RSS channel not found: {self.channel_id}")
                return

            new_items_count = 0

            # Check each item (newest first typically)
            for entry in feed.entries:
                # Use link as unique identifier
                item_id = entry.link

                if item_id not in self.seen_items:
                    # Post just the link - Discord will auto-embed it
                    try:
                        await channel.send(entry.link)
                        self._save_seen_item(item_id)
                        new_items_count += 1
                        logging.info(f"Posted RSS item: {entry.title}")
                    except discord.HTTPException as e:
                        logging.error(f"Failed to post RSS item: {e}")

            if new_items_count > 0:
                logging.info(f"Posted {new_items_count} new RSS items")
            else:
                logging.debug("No new RSS items found")

        except Exception as e:
            logging.error(f"Error checking RSS feed: {e}", exc_info=True)

    @check_rss_feed.before_loop
    async def before_check_rss_feed(self):
        """Wait for bot to be ready before starting the loop."""
        await self.bot.wait_until_ready()
        # Update the loop interval based on config
        self.check_rss_feed.change_interval(seconds=self.check_interval_seconds)
