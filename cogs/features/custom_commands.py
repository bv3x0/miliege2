import discord
from discord.ext import commands
from discord import app_commands
import logging
import json
import os
import re
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class CustomCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.data_dir = 'data'
        os.makedirs(self.data_dir, exist_ok=True)
        
        # File for storing custom commands
        self.custom_commands_file = os.path.join(self.data_dir, 'custom_commands.json')
        self.goon_urls_file = os.path.join(self.data_dir, 'goon_urls.json')
        
        # Load existing custom commands
        self.custom_commands = self._load_custom_commands()
        self.goon_urls = self._load_goon_urls()
        
        # Protected commands that cannot be overwritten
        self.protected_commands = {
            'help', 'digest', 'digest_status', 'trending', 'trending_status',
            'add_monitored_wallet', 'remove_monitored_wallet', 'list_monitored_wallets',
            'wallet_status', 'test_wallet', 'save', 'delete', 'listcommands',
            'track', 'untrack', 'tracked', 'health', 'bot_stats', 'uptime',
            'goon', 'shotcaller', 'zone', 'bet', 'wagmi', 'ngmi'
        }
    
    def _load_custom_commands(self) -> Dict[str, str]:
        """Load custom commands from JSON file"""
        try:
            if os.path.exists(self.custom_commands_file):
                with open(self.custom_commands_file, 'r') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            logger.error(f"Error loading custom commands: {e}")
            return {}
    
    def _save_custom_commands(self):
        """Save custom commands to JSON file"""
        try:
            with open(self.custom_commands_file, 'w') as f:
                json.dump(self.custom_commands, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving custom commands: {e}")
    
    def _load_goon_urls(self) -> list:
        """Load additional goon URLs from JSON file"""
        try:
            if os.path.exists(self.goon_urls_file):
                with open(self.goon_urls_file, 'r') as f:
                    return json.load(f)
            return []
        except Exception as e:
            logger.error(f"Error loading goon URLs: {e}")
            return []
    
    def _save_goon_urls(self):
        """Save goon URLs to JSON file"""
        try:
            with open(self.goon_urls_file, 'w') as f:
                json.dump(self.goon_urls, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving goon URLs: {e}")
    
    def _parse_discord_link(self, link: str) -> Optional[tuple]:
        """Parse a Discord message link and return (guild_id, channel_id, message_id)"""
        pattern = r'https://discord\.com/channels/(\d+)/(\d+)/(\d+)'
        match = re.match(pattern, link)
        if match:
            return (int(match.group(1)), int(match.group(2)), int(match.group(3)))
        return None
    
    @app_commands.command(name="save", description="Save a custom command or add URL to !goon")
    @app_commands.describe(
        command_name="The command name (must start with !)",
        content="Discord message link for custom command, or URL for !goon"
    )
    @app_commands.default_permissions(manage_messages=True)
    async def save(self, interaction: discord.Interaction, command_name: str, content: str):
        """Save a custom command (moderators only)"""
        
        # Ensure command starts with !
        if not command_name.startswith('!'):
            await interaction.response.send_message("❌ Command name must start with !", ephemeral=True)
            return
        
        # Remove the ! prefix for storage
        cmd_name = command_name[1:]
        
        # Special handling for !goon command
        if cmd_name == 'goon':
            # Add URL to goon list
            if not content.startswith(('http://', 'https://')):
                await interaction.response.send_message("❌ Please provide a valid URL for the goon command", ephemeral=True)
                return
            
            if content not in self.goon_urls:
                self.goon_urls.append(content)
                self._save_goon_urls()
                
                # Update the goon command in fun.py
                fun_cog = self.bot.get_cog('FunCommands')
                if fun_cog and hasattr(fun_cog, 'goon_options'):
                    fun_cog.goon_options.append(content)
                
                await interaction.response.send_message(f"✅ Added new URL to !goon command")
                logger.info(f"User {interaction.user} added URL to goon command")
            else:
                await interaction.response.send_message("❌ This URL is already in the goon list", ephemeral=True)
            return
        
        # Check if command is protected
        if cmd_name in self.protected_commands:
            await interaction.response.send_message(f"❌ Cannot overwrite protected command: !{cmd_name}", ephemeral=True)
            return
        
        # Check if command already exists
        if cmd_name in self.custom_commands:
            await interaction.response.send_message(f"❌ Command !{cmd_name} already exists. Use /delete first to remove it.", ephemeral=True)
            return
        
        # Parse Discord message link
        parsed = self._parse_discord_link(content)
        if not parsed:
            await interaction.response.send_message("❌ Invalid Discord message link format", ephemeral=True)
            return
        
        guild_id, channel_id, message_id = parsed
        
        # Verify we're in the same guild
        if guild_id != interaction.guild.id:
            await interaction.response.send_message("❌ Message must be from this server", ephemeral=True)
            return
        
        try:
            # Fetch the message
            channel = self.bot.get_channel(channel_id)
            if not channel:
                await interaction.response.send_message("❌ Cannot access that channel", ephemeral=True)
                return
            
            message = await channel.fetch_message(message_id)
            
            # Save the message content
            self.custom_commands[cmd_name] = message.content
            self._save_custom_commands()
            
            await interaction.response.send_message(f"✅ Custom command !{cmd_name} has been saved")
            logger.info(f"User {interaction.user} created custom command: !{cmd_name}")
            
        except discord.NotFound:
            await interaction.response.send_message("❌ Message not found", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to read that message", ephemeral=True)
        except Exception as e:
            logger.error(f"Error saving custom command: {e}")
            await interaction.response.send_message("❌ Failed to save custom command", ephemeral=True)
    
    @app_commands.command(name="delete", description="Delete a custom command")
    @app_commands.describe(command_name="The command name to delete (must start with !)")
    @app_commands.default_permissions(manage_messages=True)
    async def delete(self, interaction: discord.Interaction, command_name: str):
        """Delete a custom command (moderators only)"""
        
        # Ensure command starts with !
        if not command_name.startswith('!'):
            await interaction.response.send_message("❌ Command name must start with !", ephemeral=True)
            return
        
        # Remove the ! prefix
        cmd_name = command_name[1:]
        
        # Check if it's a protected command
        if cmd_name in self.protected_commands:
            await interaction.response.send_message(f"❌ Cannot delete protected command: !{cmd_name}", ephemeral=True)
            return
        
        # Check if command exists
        if cmd_name not in self.custom_commands:
            await interaction.response.send_message(f"❌ Command !{cmd_name} does not exist", ephemeral=True)
            return
        
        # Delete the command
        del self.custom_commands[cmd_name]
        self._save_custom_commands()
        
        await interaction.response.send_message(f"✅ Custom command !{cmd_name} has been deleted")
        logger.info(f"User {interaction.user} deleted custom command: !{cmd_name}")
    
    @app_commands.command(name="listcommands", description="List all custom commands")
    async def listcommands(self, interaction: discord.Interaction):
        """List all custom commands (sent as ephemeral)"""
        if not self.custom_commands:
            await interaction.response.send_message("No custom commands have been created yet.", ephemeral=True)
            return
        
        # Create embed
        embed = discord.Embed(
            title="Custom Commands",
            description="Here are all the custom commands:",
            color=discord.Color.blue()
        )
        
        # Add commands to embed
        commands_list = [f"!{cmd}" for cmd in sorted(self.custom_commands.keys())]
        
        # Split into chunks if too many commands
        chunk_size = 20
        for i in range(0, len(commands_list), chunk_size):
            chunk = commands_list[i:i + chunk_size]
            embed.add_field(
                name=f"Commands {i+1}-{min(i+chunk_size, len(commands_list))}",
                value="\n".join(chunk),
                inline=True
            )
        
        # Add goon URLs count
        if self.goon_urls:
            embed.add_field(
                name="Additional !goon URLs",
                value=f"{len(self.goon_urls)} custom URLs added",
                inline=False
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def get_custom_command(self, name: str) -> Optional[str]:
        """Get a custom command by name"""
        return self.custom_commands.get(name)
    
    @commands.Cog.listener()
    async def on_message(self, message):
        """Check for custom commands in messages"""
        # Ignore bot messages
        if message.author.bot:
            return
        
        # Check if message starts with !
        if not message.content.startswith('!'):
            return
        
        # Extract command name
        parts = message.content.split()
        if not parts:
            return
        
        cmd_name = parts[0][1:]  # Remove the ! prefix
        
        # Check if it's a custom command BEFORE the bot processes it
        if cmd_name in self.custom_commands:
            # Check if it's also a built-in command
            if self.bot.get_command(cmd_name) is None:
                # It's only a custom command, send it
                await message.channel.send(self.custom_commands[cmd_name])
                logger.info(f"Executed custom command !{cmd_name} for user {message.author}")


async def setup(bot):
    await bot.add_cog(CustomCommands(bot))