import discord
from discord.ext import commands
import logging
import random
import os

class FunCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Create a data directory if it doesn't exist
        self.data_dir = 'data'
        os.makedirs(self.data_dir, exist_ok=True)
        self.goon_file = os.path.join(self.data_dir, 'goon_database.json')
        
        # Test write permissions
        try:
            # Try to write to the file
            if not os.path.exists(self.goon_file):
                with open(self.goon_file, 'w') as f:
                    f.write('[]')
            logging.info(f"Successfully verified write permissions for {self.goon_file}")
        except Exception as e:
            logging.error(f"Permission error: Cannot write to {self.goon_file}: {e}")
            raise
        
        self.goon_options = [
            "https://cdn.discordapp.com/attachments/1180965924459778151/1342230338172096573/Gi9JK-rXEAAaaqv.png?ex=67b8e0ea&is=67b78f6a&hm=429e57cc369fa4cc5212971aa26ce7b63826e5b4e91511f37e050b63dae6129e&",
            "https://media.discordapp.net/attachments/1183105518194151464/1342183366711054387/78851_SFA_156500152520copia.png?ex=67b8b52b&is=67b763ab&hm=47518292a5c8fce06778fdfbb71e6e2ee90bd63bcdca11b016a798e1b29a9502&=&format=webp&quality=lossless&width=607&height=920",
            "https://cdn.discordapp.com/attachments/1149697700418306158/1336409558070857780/IMG_8675.png?ex=67b8cbe3&is=67b77a63&hm=6158b7417112d03f9e05f9204b2140726b1acb48c903bb388b711e837a8f5a2b&",
            "https://cdn.discordapp.com/attachments/1180965924459778151/1342230712648204451/fu.mp4?ex=67b8e143&is=67b78fc3&hm=2117aa4a6b9f46f3c70d29142d8275c74825b74ecba5b816c366e368574dd047&",
            "https://cdn.discordapp.com/attachments/1180965924459778151/1342517319007731803/GkUhUj3WYAEKY7k.png?ex=67b9ec2f&is=67b89aaf&hm=1285c26753cd4952899467c2c15b4589d8826a2a6d55012f4831ee1c03ec7797&",
            "https://pbs.twimg.com/media/GjmzxzfbwAA5bsK?format=jpg&name=large",
            "https://fxtwitter.com/levi_pendragon/status/1816825726840250620",
            "https://fxtwitter.com/watchingspirals/status/1703036454841000234",
            "https://pbs.twimg.com/media/Gdx0pZxaEAA7b4L?format=jpg&name=large"
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