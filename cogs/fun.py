import discord
from discord.ext import commands
import logging
import random

class FunCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.goon_options = [
            "https://cdn.discordapp.com/attachments/1180965924459778151/1342230338172096573/Gi9JK-rXEAAaaqv.png?ex=67b8e0ea&is=67b78f6a&hm=429e57cc369fa4cc5212971aa26ce7b63826e5b4e91511f37e050b63dae6129e&",
            "https://media.discordapp.net/attachments/1183105518194151464/1342183366711054387/78851_SFA_156500152520copia.png?ex=67b8b52b&is=67b763ab&hm=47518292a5c8fce06778fdfbb71e6e2ee90bd63bcdca11b016a798e1b29a9502&=&format=webp&quality=lossless&width=607&height=920",
            "https://cdn.discordapp.com/attachments/1149697700418306158/1336409558070857780/IMG_8675.png?ex=67b8cbe3&is=67b77a63&hm=6158b7417112d03f9e05f9204b2140726b1acb48c903bb388b711e837a8f5a2b&",
            "https://cdn.discordapp.com/attachments/1180965924459778151/1342230712648204451/fu.mp4?ex=67b8e143&is=67b78fc3&hm=2117aa4a6b9f46f3c70d29142d8275c74825b74ecba5b816c366e368574dd047&"
        ]

    @commands.command()
    async def goon(self, ctx):
        """Post a random goon image/video"""
        try:
            random_goon = random.choice(self.goon_options)
            await ctx.send(random_goon)
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