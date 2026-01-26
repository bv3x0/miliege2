import discord
from discord import app_commands
from discord.ext import commands
from cogs.utils.config import settings
import json
import os
import logging


class AdminCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config_path = "config.json"

    def _load_config(self) -> dict:
        """Load config.json and return contents."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    return json.load(f)
            except Exception as e:
                logging.error(f"Error loading config: {e}")
        return {}

    def _save_config(self, config: dict) -> bool:
        """Save config to config.json. Returns True on success."""
        try:
            with open(self.config_path, "w") as f:
                json.dump(config, f, indent=4)
            return True
        except Exception as e:
            logging.error(f"Error saving config: {e}")
            return False

    def _update_config(self, key: str, value: int) -> bool:
        """Load config, update a key, and save. Returns True on success."""
        config = self._load_config()
        config[key] = value
        return self._save_config(config)

    # ==================== /control commands ====================
    control_group = app_commands.Group(name="control", description="Bot feature controls")

    @control_group.command(name="pause", description="Pause a feature")
    @app_commands.describe(feature="Feature to pause")
    @app_commands.choices(feature=[
        app_commands.Choice(name="Hourly New Coins", value="hourly_digest"),
        app_commands.Choice(name="Cielo Grabber", value="cielo_grabber_bot")
    ])
    async def pause_feature(self, interaction: discord.Interaction, feature: str):
        if feature not in self.bot.feature_states:
            await interaction.response.send_message("Invalid feature", ephemeral=True)
            return

        self.bot.feature_states[feature] = False
        await interaction.response.send_message(f"✅ {feature} paused")

    @control_group.command(name="unpause", description="Resume a feature")
    @app_commands.describe(feature="Feature to resume")
    @app_commands.choices(feature=[
        app_commands.Choice(name="Hourly New Coins", value="hourly_digest"),
        app_commands.Choice(name="Cielo Grabber", value="cielo_grabber_bot")
    ])
    async def unpause_feature(self, interaction: discord.Interaction, feature: str):
        if feature not in self.bot.feature_states:
            await interaction.response.send_message("Invalid feature", ephemeral=True)
            return

        self.bot.feature_states[feature] = True
        await interaction.response.send_message(f"✅ {feature} resumed")

    @control_group.command(name="status", description="Show feature status")
    async def show_status(self, interaction: discord.Interaction):
        status_message = "**Bot Status:**\n"
        for feature, is_active in self.bot.feature_states.items():
            status = "🟢 Active" if is_active else "🔴 Paused"
            status_message += f"{feature}: {status}\n"

        await interaction.response.send_message(status_message)

    # ==================== /config commands ====================
    config_group = app_commands.Group(name="config", description="Channel configuration")

    @config_group.command(name="watch", description="Set which channel to monitor for Cielo messages")
    @app_commands.describe(channel="Channel to watch for Cielo messages")
    @app_commands.default_permissions(administrator=True)
    async def config_watch(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set which channel to monitor for Cielo messages."""
        cielo_grabber = self.bot.get_cog("CieloGrabber")
        if not cielo_grabber:
            await interaction.response.send_message("❌ CieloGrabber cog not found", ephemeral=True)
            return

        cielo_grabber.input_channel_id = channel.id

        if self._update_config("CIELO_INPUT_CHANNEL_ID", channel.id):
            await interaction.response.send_message(f"✅ Now watching for Cielo messages in {channel.mention}")
        else:
            await interaction.response.send_message("❌ Error saving config", ephemeral=True)

    @config_group.command(name="post", description="Set which channel to post processed Cielo messages to")
    @app_commands.describe(channel="Channel to post processed messages to")
    @app_commands.default_permissions(administrator=True)
    async def config_post(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set which channel to post processed messages to."""
        cielo_grabber = self.bot.get_cog("CieloGrabber")
        if not cielo_grabber:
            await interaction.response.send_message("❌ CieloGrabber cog not found", ephemeral=True)
            return

        cielo_grabber.output_channel_id = channel.id

        if self._update_config("OUTPUT_CHANNEL_ID", channel.id):
            await interaction.response.send_message(f"✅ Now posting processed messages to {channel.mention}")
        else:
            await interaction.response.send_message("❌ Error saving config", ephemeral=True)

    @config_group.command(name="digest", description="Set which channel to post hourly digest to")
    @app_commands.describe(channel="Channel to post hourly digest to")
    @app_commands.default_permissions(administrator=True)
    async def config_digest(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set which channel to post hourly digest to."""
        digest_cog = self.bot.get_cog("DigestCog")
        if not digest_cog:
            await interaction.response.send_message("❌ DigestCog not found", ephemeral=True)
            return

        digest_cog.channel_id = channel.id

        if self._update_config("HOURLY_DIGEST_CHANNEL_ID", channel.id):
            await interaction.response.send_message(f"✅ Now posting hourly digest to {channel.mention}")
        else:
            await interaction.response.send_message("❌ Error saving config", ephemeral=True)

    @config_group.command(name="newcoin", description="Set which channel to post new coin alerts to")
    @app_commands.describe(channel="Channel to post new coin alerts to")
    @app_commands.default_permissions(administrator=True)
    async def config_newcoin(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set which channel to post new coin alerts to."""
        newcoin_cog = self.bot.get_cog("NewCoinCog")
        if not newcoin_cog:
            await interaction.response.send_message("❌ NewCoinCog not found", ephemeral=True)
            return

        newcoin_cog.output_channel_id = channel.id

        if self._update_config("NEWCOIN_ALERT_CHANNEL_ID", channel.id):
            await interaction.response.send_message(f"✅ Now posting new coin alerts to {channel.mention}")
        else:
            await interaction.response.send_message("❌ Error saving config", ephemeral=True)

    @config_group.command(name="show", description="Show current channel configuration")
    async def config_show(self, interaction: discord.Interaction):
        """Show current channel configuration."""
        cielo_grabber = self.bot.get_cog("CieloGrabber")
        digest_cog = self.bot.get_cog("DigestCog")
        newcoin_cog = self.bot.get_cog("NewCoinCog")
        rss_monitor = self.bot.get_cog("RSSMonitor")

        embed = discord.Embed(title="Channel Configuration", color=0x5b594f)

        # Cielo grabber channels
        if cielo_grabber:
            input_ch = self.bot.get_channel(cielo_grabber.input_channel_id) if cielo_grabber.input_channel_id else None
            output_ch = self.bot.get_channel(cielo_grabber.output_channel_id) if cielo_grabber.output_channel_id else None

            embed.add_field(
                name="Cielo - Watching",
                value=input_ch.mention if input_ch else "Not set (`/config watch`)",
                inline=False
            )
            embed.add_field(
                name="Cielo - Posting to",
                value=output_ch.mention if output_ch else "Not set (`/config post`)",
                inline=False
            )

        # Hourly digest channel
        if digest_cog:
            digest_ch = self.bot.get_channel(digest_cog.channel_id) if digest_cog.channel_id else None
            embed.add_field(
                name="Hourly Digest",
                value=digest_ch.mention if digest_ch else "Not set (`/config digest`)",
                inline=False
            )

        # New coin alert channel
        if newcoin_cog:
            newcoin_ch = self.bot.get_channel(newcoin_cog.output_channel_id) if newcoin_cog.output_channel_id else None
            embed.add_field(
                name="New Coin Alerts",
                value=newcoin_ch.mention if newcoin_ch else "Not set (`/config newcoin`)",
                inline=False
            )

        # RSS feeds summary
        if rss_monitor:
            feeds = rss_monitor.data.get("feeds", [])
            if feeds:
                feed_lines = []
                for feed in feeds[:5]:  # Show max 5
                    ch = self.bot.get_channel(feed["channel_id"])
                    ch_name = ch.mention if ch else f"#{feed['channel_id']}"
                    feed_lines.append(f"• {feed['name']} → {ch_name}")
                if len(feeds) > 5:
                    feed_lines.append(f"... and {len(feeds) - 5} more")
                embed.add_field(
                    name=f"RSS Feeds ({len(feeds)})",
                    value="\n".join(feed_lines),
                    inline=False
                )
            else:
                embed.add_field(
                    name="RSS Feeds",
                    value="None configured (`/rss add`)",
                    inline=False
                )

        await interaction.response.send_message(embed=embed)

    @commands.command()
    @commands.is_owner()
    async def sync(self, ctx):
        """Sync application commands"""
        try:
            synced = await self.bot.tree.sync()
            await ctx.send(f"✅ Synced {len(synced)} command(s)")
        except Exception as e:
            await ctx.send(f"❌ Failed to sync commands: {e}")
