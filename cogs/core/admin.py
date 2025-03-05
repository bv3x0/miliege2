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
        
    # Simplified wallet commands with shorter names
    @app_commands.command(name="add", description="Track a new Hyperliquid wallet")
    @app_commands.describe(
        wallet="Wallet address (0x...)",
        name="Optional nickname"
    )
    async def add_wallet(self, interaction: discord.Interaction, wallet: str, name: str = None):
        # Add wallet logic here
        await interaction.response.send_message(f"Adding wallet {wallet} with name {name}")
        
    @app_commands.command(name="delete", description="Stop tracking a wallet")
    @app_commands.describe(
        wallet="Wallet address to remove"
    )
    async def delete_wallet(self, interaction: discord.Interaction, wallet: str):
        # Remove wallet logic here
        await interaction.response.send_message(f"Removing wallet {wallet}")
    
    @app_commands.command(name="list", description="Show all tracked wallets")
    async def list_wallets(self, interaction: discord.Interaction):
        try:
            # Get the database session from the bot
            db_session = self.bot.db_session
            
            # Import the TrackedWallet model
            from cogs.grabbers.hl_grabber import TrackedWallet
            
            # Query all wallets
            wallets = db_session.query(TrackedWallet).all()
            
            if not wallets:
                await interaction.response.send_message("No wallets are currently being tracked.", ephemeral=True)
                return
            
            # Create an embed to display the wallets
            embed = discord.Embed(
                title="Tracked Wallets", 
                color=discord.Color.blue(),
                description=f"Total wallets: {len(wallets)}"
            )
            
            # Add each wallet to the embed
            for wallet in wallets:
                name_display = f"**{wallet.name}**" if wallet.name else "*No nickname*"
                last_checked = wallet.last_checked_time.strftime('%Y-%m-%d %H:%M:%S')
                
                embed.add_field(
                    name=f"{name_display}",
                    value=f"**Address:** `{wallet.address}`\n"
                          f"Added by: {wallet.added_by}\n"
                          f"Last checked: {last_checked}",
                    inline=False
                )
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            import logging
            logging.error(f"Error listing wallets via slash command: {e}", exc_info=True)
            await interaction.response.send_message("❌ An error occurred while listing wallets.", ephemeral=True)
        
    # Control group commands remain the same
    control_group = app_commands.Group(name="control", description="Bot controls")
    
    @control_group.command(name="pause", description="Pause a feature")
    @app_commands.describe(
        feature="Feature to pause"
    )
    @app_commands.choices(feature=[
        app_commands.Choice(name="Hourly Digest", value="hourly_digest"),
        app_commands.Choice(name="Hyperliquid Bot", value="hyperliquid_bot"),
        app_commands.Choice(name="Cielo Grabber", value="cielo_grabber_bot")
    ])
    async def pause_feature(self, interaction: discord.Interaction, feature: str):
        if feature not in self.feature_states:
            await interaction.response.send_message(f"Invalid feature", ephemeral=True)
            return
            
        self.feature_states[feature] = False
        await interaction.response.send_message(f"✅ {feature} paused")
        
    @control_group.command(name="unpause", description="Resume a feature")
    @app_commands.describe(
        feature="Feature to resume"
    )
    @app_commands.choices(feature=[
        app_commands.Choice(name="Hourly Digest", value="hourly_digest"),
        app_commands.Choice(name="Hyperliquid Bot", value="hyperliquid_bot"),
        app_commands.Choice(name="Cielo Grabber", value="cielo_grabber_bot")
    ])
    async def unpause_feature(self, interaction: discord.Interaction, feature: str):
        if feature not in self.feature_states:
            await interaction.response.send_message(f"Invalid feature", ephemeral=True)
            return
            
        self.feature_states[feature] = True
        await interaction.response.send_message(f"✅ {feature} resumed")
        
    @control_group.command(name="status", description="Show feature status")
    async def show_status(self, interaction: discord.Interaction):
        status_message = "**Bot Status:**\n"
        for feature, is_active in self.feature_states.items():
            status = "🟢 Active" if is_active else "🔴 Paused"
            status_message += f"{feature}: {status}\n"
            
        await interaction.response.send_message(status_message)
