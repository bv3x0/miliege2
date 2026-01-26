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

    control_group = app_commands.Group(name="control", description="Bot controls")
    
    @control_group.command(name="pause", description="Pause a feature")
    @app_commands.describe(
        feature="Feature to pause"
    )
    @app_commands.choices(feature=[
        app_commands.Choice(name="Hourly New Coins", value="hourly_digest"),
        app_commands.Choice(name="Cielo Grabber", value="cielo_grabber_bot")
    ])
    async def pause_feature(self, interaction: discord.Interaction, feature: str):
        if feature not in self.bot.feature_states:
            await interaction.response.send_message(f"Invalid feature", ephemeral=True)
            return
            
        self.bot.feature_states[feature] = False
        await interaction.response.send_message(f"✅ {feature} paused")
        
    @control_group.command(name="unpause", description="Resume a feature")
    @app_commands.describe(
        feature="Feature to resume"
    )
    @app_commands.choices(feature=[
        app_commands.Choice(name="Hourly New Coins", value="hourly_digest"),
        app_commands.Choice(name="Cielo Grabber", value="cielo_grabber_bot")
    ])
    async def unpause_feature(self, interaction: discord.Interaction, feature: str):
        if feature not in self.bot.feature_states:
            await interaction.response.send_message(f"Invalid feature", ephemeral=True)
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

    @app_commands.command(name="watch", description="Set which channel to monitor for Cielo messages")
    @app_commands.default_permissions(administrator=True)
    async def watch(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set which channel to monitor for Cielo messages"""
        # Update the channel in memory
        cielo_grabber = self.bot.get_cog("CieloGrabber")
        if cielo_grabber:
            cielo_grabber.input_channel_id = channel.id
            
            # Save to persistent storage
            config_path = "config.json"
            config = {}
            
            # Load existing config if it exists
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r") as f:
                        config = json.load(f)
                except Exception as e:
                    await interaction.response.send_message(f"⚠️ Warning: Could not load existing config: {e}")
            
            # Update config
            config["CIELO_INPUT_CHANNEL_ID"] = channel.id
            
            # Save config
            try:
                with open(config_path, "w") as f:
                    json.dump(config, f, indent=4)
                
                await interaction.response.send_message(f"✅ Now watching for Cielo messages in {channel.mention}")
            except Exception as e:
                await interaction.response.send_message(f"❌ Error saving config: {e}")
        else:
            await interaction.response.send_message("❌ CieloGrabber cog not found")

    @app_commands.command(name="post", description="Set which channel to post processed messages to")
    @app_commands.default_permissions(administrator=True)
    async def post(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set which channel to post processed messages to"""
        # Update the channel in memory
        cielo_grabber = self.bot.get_cog("CieloGrabber")
        if cielo_grabber:
            cielo_grabber.output_channel_id = channel.id
            
            # Save to persistent storage
            config_path = "config.json"
            config = {}
            
            # Load existing config if it exists
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r") as f:
                        config = json.load(f)
                except Exception as e:
                    await interaction.response.send_message(f"⚠️ Warning: Could not load existing config: {e}")
            
            # Update config
            config["OUTPUT_CHANNEL_ID"] = channel.id
            
            # Save config
            try:
                with open(config_path, "w") as f:
                    json.dump(config, f, indent=4)
                
                await interaction.response.send_message(f"✅ Now posting processed messages to {channel.mention}")
            except Exception as e:
                await interaction.response.send_message(f"❌ Error saving config: {e}")
        else:
            await interaction.response.send_message("❌ CieloGrabber cog not found")

    @app_commands.command(name="digest", description="Set which channel to post hourly digest to")
    @app_commands.default_permissions(administrator=True)
    async def digest(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set which channel to post hourly digest to"""
        # Update the channel in memory
        digest_cog = self.bot.get_cog("DigestCog")
        if digest_cog:
            digest_cog.channel_id = channel.id
            
            # Save to persistent storage
            config_path = "config.json"
            config = {}
            
            # Load existing config if it exists
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r") as f:
                        config = json.load(f)
                except Exception as e:
                    await interaction.response.send_message(f"⚠️ Warning: Could not load existing config: {e}")
            
            # Update config
            config["HOURLY_DIGEST_CHANNEL_ID"] = channel.id
            
            # Save config
            try:
                with open(config_path, "w") as f:
                    json.dump(config, f, indent=4)
                
                await interaction.response.send_message(f"✅ Now posting hourly digest to {channel.mention}")
            except Exception as e:
                await interaction.response.send_message(f"❌ Error saving config: {e}")
        else:
            await interaction.response.send_message("❌ DigestCog not found")

    @app_commands.command(name="newcoin", description="Set which channel to post new coin alerts to")
    @app_commands.default_permissions(administrator=True)
    async def newcoin(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set which channel to post new coin alerts to"""
        # Update the channel in memory
        newcoin_cog = self.bot.get_cog("NewCoinCog")
        if newcoin_cog:
            newcoin_cog.output_channel_id = channel.id
            
            # Save to persistent storage
            config_path = "config.json"
            config = {}
            
            # Load existing config if it exists
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r") as f:
                        config = json.load(f)
                except Exception as e:
                    await interaction.response.send_message(f"⚠️ Warning: Could not load existing config: {e}")
            
            # Update config
            config["NEWCOIN_ALERT_CHANNEL_ID"] = channel.id
            
            # Save config
            try:
                with open(config_path, "w") as f:
                    json.dump(config, f, indent=4)
                
                await interaction.response.send_message(f"✅ Now posting new coin alerts to {channel.mention}")
            except Exception as e:
                await interaction.response.send_message(f"❌ Error saving config: {e}")
        else:
            await interaction.response.send_message("❌ NewCoinCog not found")

    @app_commands.command(name="channels", description="Show current channel configuration")
    async def channels(self, interaction: discord.Interaction):
        """Show current channel configuration"""
        cielo_grabber = self.bot.get_cog("CieloGrabber")
        digest_cog = self.bot.get_cog("DigestCog")
        newcoin_cog = self.bot.get_cog("NewCoinCog")

        embed = discord.Embed(title="Channel Configuration", color=0x5b594f)
        
        # Cielo grabber channels
        if cielo_grabber:
            input_channel = None
            output_channel = None
            
            if cielo_grabber.input_channel_id:
                input_channel = self.bot.get_channel(cielo_grabber.input_channel_id)
            
            if cielo_grabber.output_channel_id:
                output_channel = self.bot.get_channel(cielo_grabber.output_channel_id)
            
            if input_channel:
                embed.add_field(
                    name="Cielo - Watching",
                    value=f"{input_channel.mention}",
                    inline=False
                )
            else:
                embed.add_field(
                    name="Cielo - Watching",
                    value="No channel set (use `/watch` to set)",
                    inline=False
                )
            
            if output_channel:
                embed.add_field(
                    name="Cielo - Posting to",
                    value=f"{output_channel.mention}",
                    inline=False
                )
            else:
                embed.add_field(
                    name="Cielo - Posting to",
                    value="No channel set (use `/post` to set)",
                    inline=False
                )
        
        # Hourly digest channel
        if digest_cog:
            digest_channel = None
            
            if digest_cog.channel_id:
                digest_channel = self.bot.get_channel(digest_cog.channel_id)
            
            if digest_channel:
                embed.add_field(
                    name="Hourly Digest - Posting to",
                    value=f"{digest_channel.mention}",
                    inline=False
                )
            else:
                embed.add_field(
                    name="Hourly Digest - Posting to",
                    value="No channel set (use `/digest` to set)",
                    inline=False
                )
        
        # New coin alert channel
        if newcoin_cog:
            newcoin_channel = None
            
            if newcoin_cog.output_channel_id:
                newcoin_channel = self.bot.get_channel(newcoin_cog.output_channel_id)
            
            if newcoin_channel:
                embed.add_field(
                    name="New Coin Alerts - Posting to",
                    value=f"{newcoin_channel.mention}",
                    inline=False
                )
            else:
                embed.add_field(
                    name="New Coin Alerts - Posting to",
                    value="No channel set (use `/newcoin` to set)",
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
