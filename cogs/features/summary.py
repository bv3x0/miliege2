import discord
from discord.ext import commands, tasks
import logging
from collections import OrderedDict
import datetime
import pytz
import asyncio

class TradeSummaryCog(commands.Cog):
    def __init__(self, bot, channel_id, monitor=None):
        try:
            self.bot = bot
            self.channel_id = channel_id
            self.monitor = monitor
            self.ny_tz = pytz.timezone('America/New_York')
            
            logging.info(f"Initializing TradeSummaryCog with channel_id: {channel_id}")
            
            # Define major tokens
            self.major_tokens = {
                'ETH', 'WETH',  # Ethereum
                'SOL', 'WSOL',  # Solana
                'USDC',         # Major stablecoins
                'USDT',
                'DAI',
                'BNB', 'WBNB',  # Binance
                'S',            # Base
                'MATIC',        # Polygon
                'AVAX',         # Avalanche
                'ARB'           # Arbitrum
            }
            
            # Add wrapped versions
            self.major_tokens.update({f'W{t}' for t in self.major_tokens})
            
            # Trade tracking
            self.hourly_trades = {}  # Format: {token_address: {'name': str, 'url': str, 'buys': float, 'sells': float, 'users': {user: {'message_link': str, 'actions': set()}}}}
            self.last_trade_digest = None
            self.failed_trades = {}
            
            # Start the hourly task
            self.hourly_summary.start()
            logging.info("Hourly summary task started")
        except Exception as e:
            logging.error(f"Error in TradeSummaryCog initialization: {e}", exc_info=True)

    def cog_unload(self):
        self.hourly_summary.cancel()

    @tasks.loop(hours=1)
    async def hourly_summary(self):
        """Send hourly trade summary"""
        try:
            logging.info("Starting hourly summary task")
            channel = self.bot.get_channel(self.channel_id)
            if not channel:
                logging.error(f"Could not find channel with ID {self.channel_id}")
                return
            
            logging.info(f"Found channel: {channel.name}")
            if self.hourly_trades:
                logging.info(f"Processing {len(self.hourly_trades)} trades")
                embeds = await self.create_summary_embed()
                if embeds:
                    for embed in embeds:
                        try:
                            await channel.send(embed=embed)
                            logging.info("Successfully sent trade summary embed")
                        except discord.HTTPException as e:
                            logging.error(f"Failed to send trade summary: {e}")
                    self.hourly_trades.clear()
                    logging.info("Cleared hourly trades after successful send")
            else:
                logging.info("No trades to process in hourly summary")
                    
        except Exception as e:
            logging.error(f"Error in hourly summary: {e}", exc_info=True)

    @hourly_summary.before_loop
    async def before_hourly_summary(self):
        await self.bot.wait_until_ready()
        now = datetime.datetime.utcnow()
        next_time = now.replace(minute=30, second=0, microsecond=0)
        if now.minute >= 30:
            next_time = next_time + datetime.timedelta(hours=1)
        
        wait_seconds = (next_time - now).total_seconds()
        logging.info(f"Trade summary scheduled to start in {wait_seconds} seconds (at {next_time})")
        await asyncio.sleep(wait_seconds)

    async def create_summary_embed(self):
        """Create the trade summary embed"""
        if not self.hourly_trades:
            return None
            
        embed = discord.Embed(
            color=discord.Color.blue()
        )
        
        embed.set_author(
            name="Hourly Trade Digest",
            icon_url="https://cdn.discordapp.com/emojis/1133962725094064168.webp"
        )
        
        total_chars = 0
        remaining_tokens = []
        
        for token_address, data in self.hourly_trades.items():
            # Format the entry - add back the ### prefix
            entry = f"### [{data['name']}]({data['url']})\n"
            
            # Group users by their actions
            action_groups = {
                'bought': [],
                'sold': [],
                'bought and sold': []
            }
            
            for user, user_data in data['users'].items():
                actions = user_data['actions']
                link = user_data['message_link']
                user_link = f"[{user}]({link})"
                
                if 'bought' in actions and 'sold' in actions:
                    action_groups['bought and sold'].append(user_link)
                elif 'bought' in actions:
                    action_groups['bought'].append(user_link)
                elif 'sold' in actions:
                    action_groups['sold'].append(user_link)
            
            # Build the activity description
            activity_parts = []
            
            if action_groups['bought']:
                users = ', '.join(action_groups['bought'])
                amount = format(int(data['buys']), ',')
                activity_parts.append(f"{users} bought ${amount}")
            
            if action_groups['sold']:
                users = ', '.join(action_groups['sold'])
                amount = format(int(data['sells']), ',')
                activity_parts.append(f"{users} sold ${amount}")
            
            if action_groups['bought and sold']:
                users = ', '.join(action_groups['bought and sold'])
                buy_amount = format(int(data['buys']), ',')
                sell_amount = format(int(data['sells']), ',')
                activity_parts.append(f"{users} bought ${buy_amount} and sold ${sell_amount}")
            
            entry += '\n'.join(activity_parts)
            
            # Check limits
            if len(embed.fields) < 25 and total_chars + len(entry) < 5500:
                embed.add_field(name="\u200b", value=entry, inline=False)
                total_chars += len(entry)
            else:
                remaining_tokens.append(token_address)
                logging.warning(f"Trade summary truncated. Remaining tokens: {len(remaining_tokens)}")
                embed.add_field(
                    name="\u200b",
                    value="*Additional trades omitted due to Discord limits*",
                    inline=False
                )
                break
        
        # If we had to truncate, create a second embed
        if remaining_tokens:
            try:
                second_embed = discord.Embed(
                    color=discord.Color.blue()
                )
                second_embed.set_author(
                    name="Hourly Trade Digest (Continued)",
                    icon_url="https://cdn.discordapp.com/emojis/1133962725094064168.webp"
                )
                
                for token_address in remaining_tokens:
                    # Format the entry - add back the ### prefix here too
                    entry = f"### [{data['name']}]({data['url']})\n"
                    
                    # Group users by their actions
                    action_groups = {
                        'bought': [],
                        'sold': [],
                        'bought and sold': []
                    }
                    
                    for user, user_data in data['users'].items():
                        actions = user_data['actions']
                        link = user_data['message_link']
                        user_link = f"[{user}]({link})"
                        
                        if 'bought' in actions and 'sold' in actions:
                            action_groups['bought and sold'].append(user_link)
                        elif 'bought' in actions:
                            action_groups['bought'].append(user_link)
                        elif 'sold' in actions:
                            action_groups['sold'].append(user_link)
                    
                    # Build the activity description
                    activity_parts = []
                    
                    if action_groups['bought']:
                        users = ', '.join(action_groups['bought'])
                        amount = format(int(data['buys']), ',')
                        activity_parts.append(f"{users} bought ${amount}")
                    
                    if action_groups['sold']:
                        users = ', '.join(action_groups['sold'])
                        amount = format(int(data['sells']), ',')
                        activity_parts.append(f"{users} sold ${amount}")
                    
                    if action_groups['bought and sold']:
                        users = ', '.join(action_groups['bought and sold'])
                        buy_amount = format(int(data['buys']), ',')
                        sell_amount = format(int(data['sells']), ',')
                        activity_parts.append(f"{users} bought ${buy_amount} and sold ${sell_amount}")
                    
                    entry += '\n'.join(activity_parts)
                    
                    # Check limits
                    if len(second_embed.fields) < 25 and total_chars + len(entry) < 5500:
                        second_embed.add_field(name="\u200b", value=entry, inline=False)
                        total_chars += len(entry)
                    else:
                        logging.warning(f"Trade summary truncated. Remaining tokens: {len(remaining_tokens) - (len(remaining_tokens) - len(second_embed.fields))}")
                        second_embed.add_field(
                            name="\u200b",
                            value="*Additional trades omitted due to Discord limits*",
                            inline=False
                        )
                        break
                
                return [embed, second_embed]  # Return both embeds
            except Exception as e:
                logging.error(f"Error creating continuation embed: {e}")
            
        return [embed]  # Return as list for consistency

    def track_trade(self, token_address, token_name, user, amount, trade_type, message_link, dexscreener_url):
        try:
            # Move the minimum trade check to the start
            MIN_TRADE_AMOUNT = 100  # $100
            if amount < MIN_TRADE_AMOUNT:
                logging.info(f"Skipping small trade: ${amount}")
                return
            
            logging.info(f"Tracking {trade_type} trade: {token_name} by {user} for ${amount}")
            if token_address not in self.hourly_trades:
                self.hourly_trades[token_address] = {
                    'name': token_name,
                    'url': dexscreener_url,
                    'buys': 0.0,
                    'sells': 0.0,
                    'users': {}
                }
            
            trade_data = self.hourly_trades[token_address]
            
            # Update amounts
            if trade_type == 'buy':
                trade_data['buys'] += amount
                action = 'bought'
            else:
                trade_data['sells'] += amount
                action = 'sold'
            
            # Update user info
            if user not in trade_data['users']:
                trade_data['users'][user] = {'message_link': message_link, 'actions': set()}
            trade_data['users'][user]['actions'].add(action)

            logging.info(f"Successfully tracked trade for {token_name}")
        except Exception as e:
            logging.error(f"Error tracking trade: {e}", exc_info=True)

    @commands.command()
    async def testsummary(self, ctx):
        """Test the trade summary functionality"""
        try:
            logging.info("Test summary command received")
            # Add a test trade
            self.track_trade(
                "test_address",
                "TEST_TOKEN",
                "TestUser",
                1000,
                "buy",
                "https://discord.com/test",
                "https://dexscreener.com/test"
            )
            await ctx.send("Added test trade. Summary should appear at next :30")
        except Exception as e:
            logging.error(f"Error in test summary: {e}", exc_info=True)
            await ctx.send(f"Error: {str(e)}")

    @commands.command()
    async def forcesummary(self, ctx):
        """Force a trade summary to generate now"""
        try:
            logging.info("Force summary command received")
            if self.hourly_trades:
                embeds = await self.create_summary_embed()
                if embeds:
                    for embed in embeds:
                        await ctx.send(embed=embed)
                self.hourly_trades.clear()
            else:
                await ctx.send("No trades to summarize")
        except Exception as e:
            logging.error(f"Error in force summary: {e}", exc_info=True)
            await ctx.send(f"Error: {str(e)}")