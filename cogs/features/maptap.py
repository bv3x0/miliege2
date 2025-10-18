import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
import json
import os
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class MapTapLeaderboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.data_dir = 'data'
        os.makedirs(self.data_dir, exist_ok=True)
        
        # File for storing daily scores
        self.scores_file = os.path.join(self.data_dir, 'maptap_scores.json')
        
        # Load existing scores and yesterday's top 3
        self.daily_scores = self._load_scores()
        
        # Bot state
        self.is_paused = False
        
        # Start the daily reset task
        self.daily_reset_task.start()
        
        # Pattern to match "Final score: XXX" where XXX is a 3-digit number
        self.score_pattern = re.compile(r'Final score:\s*(\d{3})\b', re.IGNORECASE)
        
        logger.info("MapTap Leaderboard cog initialized")
    
    def _load_scores(self) -> Dict[str, Dict]:
        """Load daily scores from JSON file"""
        try:
            if os.path.exists(self.scores_file):
                with open(self.scores_file, 'r') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            logger.error(f"Error loading MapTap scores: {e}")
            return {}
    
    def _save_scores(self):
        """Save daily scores to JSON file"""
        try:
            with open(self.scores_file, 'w') as f:
                json.dump(self.daily_scores, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving MapTap scores: {e}")
    
    def _get_today_key(self) -> str:
        """Get today's date as a string key"""
        return datetime.now().strftime("%Y-%m-%d")
    
    def _is_today(self, date_key: str) -> bool:
        """Check if the date key is today"""
        return date_key == self._get_today_key()
    
    def _parse_score(self, content: str) -> Optional[int]:
        """Parse final score from message content"""
        match = self.score_pattern.search(content)
        if match:
            score = int(match.group(1))
            # Validate it's a 3-digit number (100-999)
            if 100 <= score <= 999:
                return score
        return None
    
    def _update_leaderboard(self, user_name: str, score: int) -> Dict:
        """Update the daily leaderboard with a new score"""
        today = self._get_today_key()
        
        if today not in self.daily_scores:
            self.daily_scores[today] = {}
        
        # Store the score (latest score for the day overwrites previous)
        self.daily_scores[today][user_name] = {
            'score': score,
            'timestamp': datetime.now().isoformat()
        }
        
        self._save_scores()
        
        # Return sorted leaderboard
        return self._get_sorted_leaderboard(today)
    
    def _get_sorted_leaderboard(self, date_key: str) -> Dict:
        """Get sorted leaderboard for a given date"""
        if date_key not in self.daily_scores:
            return {}
        
        # Sort by score (descending) and then by timestamp (ascending for tie-breaking)
        sorted_scores = sorted(
            self.daily_scores[date_key].items(),
            key=lambda x: (-x[1]['score'], x[1]['timestamp'])
        )
        
        return {
            'date': date_key,
            'scores': sorted_scores,
            'total_players': len(sorted_scores)
        }
    
    def _format_leaderboard(self, leaderboard: Dict, is_final: bool = False, newest_user: str = None) -> discord.Embed:
        """Format leaderboard as Discord embed"""
        if not leaderboard or not leaderboard['scores']:
            embed = discord.Embed(
                title="MapTap Leaderboard",
                description="No scores recorded today!",
                color=0x3498db,
                url="https://maptap.gg/"
            )
            return embed
        
        date_obj = datetime.strptime(leaderboard['date'], "%Y-%m-%d")
        date_str = date_obj.strftime("%B %d, %Y")
        
        title = f"MapTap Leaderboard - {date_str}"
        if is_final:
            title += " (Final)"
        
        # Create embed with clickable MapTap link
        embed = discord.Embed(
            title=title,
            color=0x3498db,
            url="https://maptap.gg/"
        )
        
        # Build leaderboard description
        leaderboard_text = []
        for i, (user_name, data) in enumerate(leaderboard['scores'], 1):
            # Add fire emoji for the newest addition
            fire_emoji = " 🔥" if user_name == newest_user else ""
            leaderboard_text.append(f"{i}. **{user_name}**: {data['score']}{fire_emoji}")
        
        embed.description = "\n".join(leaderboard_text)
        
        # Add yesterday's top 3 footer if data exists
        yesterday_footer = self._get_yesterday_footer()
        if yesterday_footer:
            embed.set_footer(text=yesterday_footer)
        
        return embed
    
    def _get_yesterday_key(self) -> str:
        """Get yesterday's date as a string key"""
        yesterday = datetime.now() - timedelta(days=1)
        return yesterday.strftime("%Y-%m-%d")
    
    def _get_yesterday_footer(self) -> Optional[str]:
        """Get yesterday's top 3 for footer display"""
        yesterday_key = self._get_yesterday_key()
        
        # Check if we have yesterday's top 3 stored
        if 'yesterday_top3' in self.daily_scores and yesterday_key in self.daily_scores['yesterday_top3']:
            top3 = self.daily_scores['yesterday_top3'][yesterday_key]
            if top3:
                # Format as "Yesterday: 1. username, 2. username, 3. username"
                names = []
                for i, user_name in enumerate(top3, 1):
                    names.append(f"{i}. {user_name}")
                return f"Yesterday: {', '.join(names)}"
        
        return None
    
    def _capture_yesterday_top3(self, today_key: str):
        """Capture yesterday's top 3 at daily reset"""
        yesterday_key = self._get_yesterday_key()
        
        # Get yesterday's leaderboard
        if yesterday_key in self.daily_scores:
            yesterday_scores = self.daily_scores[yesterday_key]
            if yesterday_scores:
                # Sort by score (descending) and take top 3
                sorted_scores = sorted(
                    yesterday_scores.items(),
                    key=lambda x: (-x[1]['score'], x[1]['timestamp'])
                )
                
                # Store top 3 usernames
                top3_names = [user_name for user_name, _ in sorted_scores[:3]]
                
                # Initialize yesterday_top3 structure if needed
                if 'yesterday_top3' not in self.daily_scores:
                    self.daily_scores['yesterday_top3'] = {}
                
                self.daily_scores['yesterday_top3'][yesterday_key] = top3_names
                self._save_scores()
                
                logger.info(f"Captured yesterday's top 3 for {yesterday_key}: {top3_names}")
    
    @commands.Cog.listener()
    async def on_message(self, message):
        """Monitor all channels for MapTap score posts"""
        # Skip if bot is paused
        if self.is_paused:
            return
        
        # Ignore bot messages
        if message.author.bot:
            return
        
        # Check for score in message
        score = self._parse_score(message.content)
        if score is None:
            return
        
        user_name = message.author.display_name or message.author.name
        logger.info(f"MapTap score detected: {user_name} scored {score}")
        
        # Update leaderboard
        leaderboard = self._update_leaderboard(user_name, score)
        
        # Post updated leaderboard with newest user highlighted
        embed = self._format_leaderboard(leaderboard, newest_user=user_name)
        await message.channel.send(embed=embed)
    
    @tasks.loop(time=datetime.strptime("23:59", "%H:%M").time())
    async def daily_reset_task(self):
        """Daily task to post final leaderboard and reset"""
        try:
            today = self._get_today_key()
            leaderboard = self._get_sorted_leaderboard(today)
            
            if leaderboard and leaderboard['scores']:
                # Post final leaderboard to all channels the bot can see
                for guild in self.bot.guilds:
                    for channel in guild.text_channels:
                        if channel.permissions_for(guild.me).send_messages:
                            try:
                                embed = self._format_leaderboard(leaderboard, is_final=True)
                                await channel.send(embed=embed)
                                break  # Only send to one channel per guild
                            except Exception as e:
                                logger.error(f"Error posting final leaderboard to {channel.name}: {e}")
                
                logger.info(f"Posted final MapTap leaderboard for {today}")
            
            # Capture yesterday's top 3 for tomorrow's footer
            self._capture_yesterday_top3(today)
            
            # Clear today's scores (they'll be cleared anyway when we start fresh tomorrow)
            # We keep them in the file for historical reference
            
        except Exception as e:
            logger.error(f"Error in daily reset task: {e}")
    
    @daily_reset_task.before_loop
    async def before_daily_reset_task(self):
        """Wait for bot to be ready before starting the task"""
        await self.bot.wait_until_ready()
    
    @commands.command(name="map")
    async def manual_leaderboard(self, ctx):
        """Manually display the current day's leaderboard"""
        today = self._get_today_key()
        leaderboard = self._get_sorted_leaderboard(today)
        
        embed = self._format_leaderboard(leaderboard)
        await ctx.send(embed=embed)
    
    @app_commands.command(name="pause_map", description="Pause MapTap leaderboard monitoring")
    @app_commands.default_permissions(manage_messages=True)
    async def pause_map(self, interaction: discord.Interaction):
        """Pause MapTap leaderboard monitoring (moderators only)"""
        self.is_paused = True
        await interaction.response.send_message("🛑 MapTap leaderboard monitoring is now **PAUSED**")
        logger.info(f"MapTap monitoring paused by {interaction.user}")
    
    @app_commands.command(name="unpause_map", description="Resume MapTap leaderboard monitoring")
    @app_commands.default_permissions(manage_messages=True)
    async def unpause_map(self, interaction: discord.Interaction):
        """Resume MapTap leaderboard monitoring (moderators only)"""
        self.is_paused = False
        await interaction.response.send_message("▶️ MapTap leaderboard monitoring is now **RESUMED**")
        logger.info(f"MapTap monitoring resumed by {interaction.user}")
    
    def cog_unload(self):
        """Cleanup when cog is unloaded"""
        self.daily_reset_task.cancel()
        logger.info("MapTap Leaderboard cog unloaded")


async def setup(bot):
    await bot.add_cog(MapTapLeaderboard(bot))
