import discord
from discord.ext import commands
import logging
import random
import os
import json
import asyncio
from pathlib import Path
from cogs.utils import (
    UI,
    safe_api_call,
    DexScreenerAPI
)

class FunCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Create data directories if they don't exist
        self.data_dir = 'data'
        self.media_dir = os.path.join(self.data_dir, 'goon_media')
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.media_dir, exist_ok=True)
        self.goon_file = os.path.join(self.data_dir, 'goon_database.json')

        # Test write permissions
        try:
            if not os.path.exists(self.goon_file):
                with open(self.goon_file, 'w') as f:
                    f.write('[]')
            logging.info(f"Successfully verified write permissions for {self.goon_file}")
        except Exception as e:
            logging.error(f"Permission error: Cannot write to {self.goon_file}: {e}")
            raise

        # Load local media files and URL embeds
        self.goon_files = []  # Local file paths
        self.goon_urls = []   # URLs for embeds (fxtwitter, tenor, etc.)
        self._load_goon_media()

    def _load_goon_media(self):
        """Load local media files and embed URLs"""
        # Load local files from goon_media directory
        media_path = Path(self.media_dir)
        if media_path.exists():
            valid_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.mp4', '.mov', '.webp', '.webm'}
            for f in media_path.iterdir():
                if f.is_file() and f.suffix.lower() in valid_extensions:
                    self.goon_files.append(str(f))
            logging.info(f"Loaded {len(self.goon_files)} local goon media files")

        # Load embed URLs from goon_urls.json
        goon_urls_file = os.path.join(self.data_dir, 'goon_urls.json')
        try:
            if os.path.exists(goon_urls_file):
                with open(goon_urls_file, 'r') as f:
                    self.goon_urls = json.load(f)
            logging.info(f"Loaded {len(self.goon_urls)} goon embed URLs")
        except Exception as e:
            logging.error(f"Error loading goon URLs: {e}")

    def _get_random_goon(self) -> tuple[str | None, str | None]:
        """Get a random goon item. Returns (file_path, url) - one will be None."""
        total_files = len(self.goon_files)
        total_urls = len(self.goon_urls)
        total = total_files + total_urls

        if total == 0:
            return None, None

        idx = random.randint(0, total - 1)
        if idx < total_files:
            return self.goon_files[idx], None
        else:
            return None, self.goon_urls[idx - total_files]

    @commands.command()
    async def goon(self, ctx):
        """Post a random goon image/video"""
        try:
            file_path, url = self._get_random_goon()
            if file_path:
                await ctx.send(file=discord.File(file_path))
            elif url:
                await ctx.send(url)
            else:
                await ctx.send("No goon media available")
        except Exception as e:
            logging.error(f"Error in goon command: {e}")
            await ctx.send("Failed to post goon image")

    @commands.command()
    async def flickergoon(self, ctx):
        """Post a random goon image/video and delete it after 1 second"""
        try:
            file_path, url = self._get_random_goon()
            if file_path:
                message = await ctx.send(file=discord.File(file_path))
            elif url:
                message = await ctx.send(url)
            else:
                await ctx.send("No goon media available")
                return
            # Delete the message after 1 second
            await asyncio.sleep(1)
            await message.delete()
        except Exception as e:
            logging.error(f"Error in flickergoon command: {e}")
            await ctx.send("Failed to post flickergoon image")

    @commands.command()
    async def shotcaller(self, ctx):
        """Post the Shot Caller GIF followed by the quote"""
        try:
            # Send the GIF URL first - Discord will automatically embed it
            await ctx.send("https://tenor.com/view/burpees-shot-caller-2017-prison-gif-17889553258612147199")

            # Send the text as a separate message
            quote = ("The safety of these numbers comes with a price. There are no free rides here. "
                    "Everyone puts in work, whether cliqued up or not. I'm not talking about helping us "
                    "with our computer skills. You'll get your fucking hands dirty like the rest of us. "
                    "Or you can go back to seeing how that lone bullshit works out for you, money man.")

            await ctx.send(quote)
        except Exception as e:
            logging.error(f"Error in shotcaller command: {e}")
            await ctx.send("Failed to post shotcaller content")

    @commands.command()
    async def zone(self, ctx):
        """Display the trading zone mindset message"""
        try:
            embed = discord.Embed(
                title="Are you trading... _in the zone_ ??",
                color=UI.EMBED_BORDER
            )

            embed.add_field(
                name="Prepare with intention",
                value="- Define a valid setup using an edge.\n"
                      "- Be aware of emotions. Don't let them control you.\n"
                      "- Never exceed your set risk per trade.\n"
                      "- Anything can happen, and that's OK.",
                inline=False
            )

            embed.add_field(
                name="Observe and adjust",
                value="- Review mistakes without self-criticism.\n"
                      "- Ask what the trade taught you.\n"
                      "- Then let it go.",
                inline=False
            )

            await ctx.send(embed=embed)

            # Then send the GIF
            await ctx.send("https://media.discordapp.net/attachments/1185169573046124595/1271226724901720074/1597441693262.gif?ex=67e7c4e5&is=67e67365&hm=e5590fb22362ac9b10743a7d2f9c06b6bbcbb6f460e75e431d0eb74b6a7b842f&=")

        except Exception as e:
            logging.error(f"Error in zone command: {e}")
            await ctx.send("Failed to post zone message")

    @commands.command()
    async def bet(self, ctx):
        """Display the thinking in bets mindset message followed by betting GIF"""
        try:
            # First send the embed
            embed = discord.Embed(
                title="Are you thinking... _in bets_ ??",
                color=UI.EMBED_BORDER
            )

            embed.add_field(
                name="Before: Frame decisions as bets",
                value="- Focus on probabilities, not results.\n"
                      "- Watch for biases (confirmation, hindsight, self-serving).\n"
                      "- Run a premortem: What could go wrong, and how would you adjust?\n"
                      "- Use expected value: Is the upside worth the downside?",
                inline=False
            )

            embed.add_field(
                name="After: Update your beliefs",
                value="- Don't cling to old assumptions. Incorporate new information.\n"
                      "- Seek diverse perspectives to prevent blind spots.\n"
                      "- A bad outcome doesn't mean a bad decision—only bad process does.\n"
                      "- Aim to be less wrong over time, not always right.",
                inline=False
            )

            await ctx.send(embed=embed)

            # Then send the GIF
            await ctx.send("https://tenor.com/view/betmore-money-wasted-buy-gif-21033443")

        except Exception as e:
            logging.error(f"Error in bet command: {e}")
            await ctx.send("Failed to post bet message")


async def setup(bot):
    await bot.add_cog(FunCommands(bot))
