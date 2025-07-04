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
        # Feature states are now managed by the main bot class
        
    # Hyperliquid commands disabled
    # @app_commands.command(name="list", description="List all tracked Hyperliquid wallets")
    # async def list_wallets(self, interaction: discord.Interaction):
    #     """List all tracked Hyperliquid wallets"""
    #     try:
    #         logging.info("List wallets command called")
    #         # Get the HyperliquidWalletGrabber cog
    #         wallet_grabber = self.bot.get_cog('HyperliquidWalletGrabber')
    #         logging.info(f"Got wallet grabber: {wallet_grabber is not None}")
    #         
    #         if not wallet_grabber:
    #             await interaction.response.send_message("❌ Wallet tracking system not available.", ephemeral=True)
    #             return

    #         # Get wallets directly from the cog's memory
    #         wallets = wallet_grabber.wallets
    #         logging.info(f"Found {len(wallets)} wallets")
    #         
    #         if not wallets:
    #             await interaction.response.send_message("No wallets are currently being tracked.", ephemeral=True)
    #             return
    #             
    #         # Create embed with wallet information
    #         embed = discord.Embed(
    #             title="Tracked Hyperliquid Wallets",
    #             description=f"Currently tracking {len(wallets)} wallets",
    #             color=0x5b594f
    #         )
    #         
    #         # Add each wallet to the embed
    #         for wallet in wallets:
    #             status = "🟢 Active" if wallet.is_active else "🔴 Inactive"
    #             embed.add_field(
    #                 name=f"{wallet.name} ({status})",
    #                 value=f"`{wallet.address}`",
    #                 inline=False
    #             )
    #             
    #         await interaction.response.send_message(embed=embed, ephemeral=True)
    #         
    #     except Exception as e:
    #         logging.error(f"Error listing wallets via slash command: {e}", exc_info=True)
    #         await interaction.response.send_message("❌ An error occurred while retrieving the wallet list.", ephemeral=True)
        
    # Hyperliquid wallet commands disabled
    # @app_commands.command(name="add", description="Track a new Hyperliquid wallet")
    # @app_commands.describe(
    #     wallet="Wallet address (0x...)",
    #     name="Optional nickname"
    # )
    # async def add_wallet(self, interaction: discord.Interaction, wallet: str, name: str = None):
    #     try:
    #         # Get the HyperliquidWalletGrabber cog
    #         wallet_grabber = self.bot.get_cog('HyperliquidWalletGrabber')
    #         if not wallet_grabber:
    #             await interaction.response.send_message("❌ Wallet tracking system not available.", ephemeral=True)
    #             return
    #
    #         # Add the wallet using the new method
    #         tracked_wallet = await wallet_grabber.add_wallet(wallet, name)
    #         if tracked_wallet:
    #             await interaction.response.send_message(f"✅ Successfully added wallet: `{wallet}`", ephemeral=True)
    #         else:
    #             await interaction.response.send_message("❌ Failed to add wallet. Please check the address and try again.", ephemeral=True)
    #     except Exception as e:
    #         logging.error(f"Error adding wallet: {e}", exc_info=True)
    #         await interaction.response.send_message("❌ An error occurred while adding the wallet.", ephemeral=True)
        
    # Hyperliquid wallet commands disabled
    # @app_commands.command(name="delete", description="Stop tracking a wallet")
    # @app_commands.describe(
    #     wallet="Wallet address to remove"
    # )
    # async def delete_wallet(self, interaction: discord.Interaction, wallet: str):
    #     try:
    #         # Get the HyperliquidWalletGrabber cog
    #         wallet_grabber = self.bot.get_cog('HyperliquidWalletGrabber')
    #         if not wallet_grabber:
    #             await interaction.response.send_message("❌ Wallet tracking system not available.", ephemeral=True)
    #             return
    # 
    #         # Remove the wallet using the new method
    #         success = await wallet_grabber.remove_wallet(wallet)
    #         if success:
    #             await interaction.response.send_message(f"✅ Successfully removed wallet: `{wallet}`", ephemeral=True)
    #         else:
    #             await interaction.response.send_message("❌ Wallet not found. Please check the address and try again.", ephemeral=True)
    #     except Exception as e:
    #         logging.error(f"Error removing wallet: {e}", exc_info=True)
    #         await interaction.response.send_message("❌ An error occurred while removing the wallet.", ephemeral=True)
    
    # Control group commands remain the same
    control_group = app_commands.Group(name="control", description="Bot controls")
    
    @control_group.command(name="pause", description="Pause a feature")
    @app_commands.describe(
        feature="Feature to pause"
    )
    @app_commands.choices(feature=[
        app_commands.Choice(name="Hourly New Coins", value="hourly_digest"),
        # app_commands.Choice(name="Hyperliquid Bot", value="hyperliquid_bot"),  # Hyperliquid disabled
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
        # app_commands.Choice(name="Hyperliquid Bot", value="hyperliquid_bot"),  # Hyperliquid disabled
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

    @app_commands.command(name="channels", description="Show current channel configuration")
    async def channels(self, interaction: discord.Interaction):
        """Show current channel configuration"""
        cielo_grabber = self.bot.get_cog("CieloGrabber")
        if cielo_grabber:
            input_channel = None
            output_channel = None
            
            if cielo_grabber.input_channel_id:
                input_channel = self.bot.get_channel(cielo_grabber.input_channel_id)
            
            if cielo_grabber.output_channel_id:
                output_channel = self.bot.get_channel(cielo_grabber.output_channel_id)
            
            embed = discord.Embed(title="Channel Configuration", color=0x5b594f)
            
            if input_channel:
                embed.add_field(
                    name="Watching",
                    value=f"{input_channel.mention}",
                    inline=False
                )
            else:
                embed.add_field(
                    name="Watching",
                    value="No channel set (use `/watch` to set)",
                    inline=False
                )
            
            if output_channel:
                embed.add_field(
                    name="Posting to",
                    value=f"{output_channel.mention}",
                    inline=False
                )
            else:
                embed.add_field(
                    name="Posting to",
                    value="No channel set (use `/post` to set)",
                    inline=False
                )
            
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("❌ CieloGrabber cog not found")

    @commands.command()
    @commands.is_owner()
    async def sync(self, ctx):
        """Sync application commands"""
        try:
            synced = await self.bot.tree.sync()
            await ctx.send(f"✅ Synced {len(synced)} command(s)")
        except Exception as e:
            await ctx.send(f"❌ Failed to sync commands: {e}")
