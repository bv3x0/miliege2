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
            "https://i.poastcdn.org/bc/58/6f/bc586ffb8d29efd0ed8d4dbf0cf450fddd67f9e9e9090f3d0bc88fe3c3f70420.png",
            "https://media.discordapp.net/attachments/1149697700418306158/1339987703214637056/Gjwk9HbW8AAGiYt.png?ex=67b9f2cc&is=67b8a14c&hm=7af9b747846292f387806c510fe1fb39d083ce2a0ad42bbf5912b77cdc46856b&=&format=webp&quality=lossless",
            "https://pbs.twimg.com/media/Gdx0pZxaEAA7b4L?format=jpg&name=large",
            "https://pbs.twimg.com/media/F5At7etXMAEGZoj?format=jpg&name=medium",
            "https://pbs.twimg.com/media/GkRudWxWQAAeCL4?format=jpg&name=small",
            "https://pbs.twimg.com/media/GZzA4QiWsAAX25d?format=jpg&name=small",
            "https://pbs.twimg.com/media/Ga5XIPKXEAAJ_p9?format=jpg&name=900x900",
            "https://pbs.twimg.com/media/GNSoRakXMAApB80?format=jpg&name=900x900",
            "https://pbs.twimg.com/media/GTLzZt3WcAE45qw?format=jpg&name=small",
            "https://cdn.discordapp.com/attachments/1149879412100190248/1325873532948709518/hope_2.mp4?ex=67ba0473&is=67b8b2f3&hm=4a47ea3d374521192b4bec48a0afbeaef21ca8ba4fb227980248d285e10a3f4a&",
            "https://cdn.discordapp.com/attachments/1149697700418306158/1325899391000641536/hope_2.5.mp4?ex=67b973c8&is=67b82248&hm=dcfb2a92318664fc0021fe0ed37971a4eb511db67521ac764ed585e48b8cf8c9&",
            "https://media.discordapp.net/attachments/1149697700418306158/1342223139156791297/image0.jpg?ex=67b982f5&is=67b83175&hm=4aa4e4bf7736adbbf25456bf948bab7f284b8f7e390e40761837c3bb8d19d9c8&=&format=webp&width=662&height=919",
            "https://media.discordapp.net/attachments/1180965924459778151/1342936149693304973/IMG_0247.jpg?ex=67bb7240&is=67ba20c0&hm=f586af351ac6bc2719e6795a46a2491e4b148da83f508b3a16edbcd279ac9fcd&=&format=webp&width=607&height=920",
            "https://cdn.discordapp.com/attachments/1180965924459778151/1342944112856268940/Screenshot_2025-02-22_at_2.39.49_PM.png?ex=67bb79ab&is=67ba282b&hm=cbd6601fa219e014bf8360aacd503f960618f05650877a46bf80670a183dcfea&",
            "https://media.discordapp.net/attachments/1180965924459778151/1342944127712759829/Screenshot_2025-02-22_at_2.39.39_PM.png?ex=67bb79ae&is=67ba282e&hm=fb52e7bd1030ecfde77ef4d8c258140a5c2ffb596c05c079b6e50b3909a6df27&=&format=webp&quality=lossless",
        ]

    @commands.command()
    async def goon(self, ctx):
        """Post a random goon image/video"""
        try:
            random_goon = random.choice(self.goon_options)
            await ctx.send(f"||{random_goon}||")
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