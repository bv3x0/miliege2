import discord
from discord import app_commands
from discord.ext import commands

class AdminCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Initialize feature states
        self.feature_states = {
            'hourly_digest': True,
            'hyperliquid_bot': True,
            'cielo_grabber_bot': True
        }
        
        # Add the control group to the bot's command tree
        self.bot.tree.add_command(self.control_group)
        
    # Slash command for adding wallets
    @app_commands.command(name="addwallet", description="Add a wallet for Hyperliquid tracking")
    @app_commands.describe(
        wallet="The wallet address to add",
        name="Optional nickname for this wallet"
    )
    async def add_wallet(self, interaction: discord.Interaction, wallet: str, name: str = None):
        # Add wallet logic here
        await interaction.response.send_message(f"Adding wallet {wallet} with name {name}")
        
    # Slash command for removing wallets    
    @app_commands.command(name="removewallet", description="Remove a wallet from Hyperliquid tracking")
    @app_commands.describe(
        wallet="The wallet address to remove"
    )
    async def remove_wallet(self, interaction: discord.Interaction, wallet: str):
        # Remove wallet logic here
        await interaction.response.send_message(f"Removing wallet {wallet}")
        
    # Rename bot_group to control_group or manage_group
    control_group = app_commands.Group(name="control", description="Bot control commands")
    
    @control_group.command(name="pause", description="Pause a specific bot feature")
    @app_commands.describe(
        feature="The feature to pause (hourly_digest, hyperliquid_bot, or cielo_grabber_bot)"
    )
    async def pause_feature(self, interaction: discord.Interaction, feature: str):
        if feature not in self.feature_states:
            await interaction.response.send_message(f"Invalid feature. Available features: {', '.join(self.feature_states.keys())}", ephemeral=True)
            return
            
        self.feature_states[feature] = False
        await interaction.response.send_message(f"✅ {feature} has been paused")
        
    @control_group.command(name="unpause", description="Unpause a specific bot feature")
    @app_commands.describe(
        feature="The feature to unpause (hourly_digest, hyperliquid_bot, or cielo_grabber_bot)"
    )
    async def unpause_feature(self, interaction: discord.Interaction, feature: str):
        if feature not in self.feature_states:
            await interaction.response.send_message(f"Invalid feature. Available features: {', '.join(self.feature_states.keys())}", ephemeral=True)
            return
            
        self.feature_states[feature] = True
        await interaction.response.send_message(f"✅ {feature} has been unpaused")
        
    @control_group.command(name="status", description="Show the status of all bot features")
    async def show_status(self, interaction: discord.Interaction):
        status_message = "**Bot Feature Status:**\n"
        for feature, is_active in self.feature_states.items():
            status = "🟢 Active" if is_active else "🔴 Paused"
            status_message += f"{feature}: {status}\n"
            
        await interaction.response.send_message(status_message)
