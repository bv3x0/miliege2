import discord
from discord.ext import commands
import logging

class FunCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def goon(self, ctx):
        """Post the goon image"""
        try:
            # You can host the image somewhere reliable like imgur or discord CDN
            goon_image_url = "https://cdn.discordapp.com/attachments/1149697700418306158/1336409558070857780/IMG_8675.png?ex=67b8cbe3&is=67b77a63&hm=6158b7417112d03f9e05f9204b2140726b1acb48c903bb388b711e837a8f5a2b&"
            await ctx.send(goon_image_url)
        except Exception as e:
            logging.error(f"Error in goon command: {e}")
            await ctx.send("❌ Failed to post goon image")

    # Add more fun commands here
    @commands.command()
    async def wagmi(self, ctx):
        """Respond with WAGMI emoji"""
        await ctx.send("<:wagmi:YOUR_EMOJI_ID>")

    @commands.command()
    async def ngmi(self, ctx):
        """Respond with NGMI emoji"""
        await ctx.send("<:ngmi:YOUR_EMOJI_ID>") 