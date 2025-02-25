import discord
from discord.ext import commands
import logging
from datetime import datetime, timedelta
from sqlalchemy import func, desc, asc
from db.models import Token, MarketCapUpdate
import asyncio
from utils import format_large_number

class Analytics(commands.Cog):
    """Analytics module for token performance tracking."""
    
    def __init__(self, bot):
        self.bot = bot
        self.db_session = bot.db_session
        logging.info("Analytics module initialized")
    
    @commands.command(name="top")
    async def top_tokens(self, ctx, days: int = 1, limit: int = 5):
        """Show top performing tokens in the given time period.
        
        Args:
            days: Number of days to look back (default: 1)
            limit: Number of tokens to show (default: 5)
        """
        try:
            if not self.db_session:
                await ctx.send("❌ Database connection not available.")
                return
                
            if days < 1:
                await ctx.send("❌ Days must be at least 1.")
                return
                
            if limit < 1 or limit > 20:
                await ctx.send("❌ Limit must be between 1 and 20.")
                return
            
            # Get current datetime and the start of the period
            now = datetime.now()
            start_date = now - timedelta(days=days)
            
            # Create embed for response
            embed = discord.Embed(
                title=f"Top {limit} Tokens in Last {days} Day(s)",
                description=f"Based on market cap growth from {start_date.strftime('%Y-%m-%d')}",
                color=0x5b594f
            )
            
            # Get tokens with market cap updates in the given period
            tokens_with_updates = self.db_session.query(Token).join(
                MarketCapUpdate, Token.id == MarketCapUpdate.token_id
            ).filter(
                MarketCapUpdate.timestamp >= start_date
            ).distinct().all()
            
            # Process each token to calculate growth
            growth_data = []
            for token in tokens_with_updates:
                # Get earliest market cap in period
                earliest_update = self.db_session.query(MarketCapUpdate).filter(
                    MarketCapUpdate.token_id == token.id,
                    MarketCapUpdate.timestamp >= start_date
                ).order_by(asc(MarketCapUpdate.timestamp)).first()
                
                # Get latest market cap in period
                latest_update = self.db_session.query(MarketCapUpdate).filter(
                    MarketCapUpdate.token_id == token.id,
                    MarketCapUpdate.timestamp >= start_date
                ).order_by(desc(MarketCapUpdate.timestamp)).first()
                
                # Calculate growth if both updates exist and have valid market cap values
                if earliest_update and latest_update and earliest_update.market_cap and latest_update.market_cap:
                    growth_pct = ((latest_update.market_cap - earliest_update.market_cap) / earliest_update.market_cap) * 100
                    growth_data.append({
                        'token': token,
                        'growth_pct': growth_pct,
                        'initial_mcap': earliest_update.market_cap,
                        'final_mcap': latest_update.market_cap
                    })
            
            # Sort by growth percentage
            growth_data.sort(key=lambda x: x['growth_pct'], reverse=True)
            
            # Take top performers up to limit
            top_performers = growth_data[:limit]
            
            # Add to embed
            for i, data in enumerate(top_performers, 1):
                token = data['token']
                growth = data['growth_pct']
                initial_mcap = format_large_number(data['initial_mcap'])
                final_mcap = format_large_number(data['final_mcap'])
                
                # Format growth with sign and color
                growth_sign = "+" if growth >= 0 else ""
                growth_str = f"{growth_sign}{growth:.2f}%"
                
                embed.add_field(
                    name=f"{i}. {token.name} ({token.chain})",
                    value=f"Growth: **{growth_str}**\nMC: ${initial_mcap} → ${final_mcap}\nSource: {token.source}" + 
                          (f"\nCredited to: {token.credited_user}" if token.credited_user else ""),
                    inline=False
                )
            
            if not top_performers:
                embed.add_field(
                    name="No Data",
                    value="No tokens with sufficient data in this period.",
                    inline=False
                )
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            logging.error(f"Error in top_tokens command: {e}", exc_info=True)
            await ctx.send("❌ An error occurred while fetching analytics data.")

    @commands.command(name="caller")
    async def top_callers(self, ctx, days: int = 7):
        """Show top performing token callers in the given time period.
        
        Args:
            days: Number of days to look back (default: 7)
        """
        try:
            if not self.db_session:
                await ctx.send("❌ Database connection not available.")
                return
                
            if days < 1:
                await ctx.send("❌ Days must be at least 1.")
                return
            
            # Get current datetime and the start of the period
            now = datetime.now()
            start_date = now - timedelta(days=days)
            
            # Create embed for response
            embed = discord.Embed(
                title=f"Top Callers in Last {days} Day(s)",
                description=f"Based on number of tokens called and performance",
                color=0x5b594f
            )
            
            # Count token calls per user
            caller_tokens = {}  # {username: [token_ids]}
            callers = self.db_session.query(Token.credited_user, func.count(Token.id).label('count')).filter(
                Token.first_seen >= start_date,
                Token.credited_user != None
            ).group_by(Token.credited_user).order_by(desc('count')).limit(10).all()
            
            # Get tokens for each caller
            for caller, count in callers:
                # Skip if caller is None
                if not caller:
                    continue
                    
                # Get tokens called by this user
                tokens = self.db_session.query(Token).filter(
                    Token.first_seen >= start_date,
                    Token.credited_user == caller
                ).all()
                
                # Calculate average growth for tokens with sufficient data
                total_growth = 0
                tokens_with_growth = 0
                highest_growth = None
                best_token = None
                
                for token in tokens:
                    # Calculate growth since first called
                    initial_mcap = token.initial_market_cap
                    current_mcap = token.current_market_cap
                    
                    if initial_mcap and current_mcap and initial_mcap > 0:
                        growth_pct = ((current_mcap - initial_mcap) / initial_mcap) * 100
                        total_growth += growth_pct
                        tokens_with_growth += 1
                        
                        # Track highest growth token
                        if highest_growth is None or growth_pct > highest_growth:
                            highest_growth = growth_pct
                            best_token = token
                
                # Calculate average if we have valid data
                avg_growth = total_growth / tokens_with_growth if tokens_with_growth > 0 else 0
                
                # Format caller name and add data to embed
                formatted_caller = caller if caller else "Unknown"
                
                # Create field value with token count and growth data
                value = f"Tokens Called: **{count}**\n"
                value += f"Avg Growth: **{'+' if avg_growth >= 0 else ''}{avg_growth:.2f}%**\n"
                
                if best_token:
                    value += f"Best Token: {best_token.name} on {best_token.chain}\n"
                    value += f"Growth: **{'+' if highest_growth >= 0 else ''}{highest_growth:.2f}%**"
                
                embed.add_field(
                    name=f"{formatted_caller}",
                    value=value,
                    inline=False
                )
            
            if not callers:
                embed.add_field(
                    name="No Data",
                    value="No callers with sufficient data in this period.",
                    inline=False
                )
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            logging.error(f"Error in top_callers command: {e}", exc_info=True)
            await ctx.send("❌ An error occurred while fetching caller analytics.")

    @commands.command(name="recent")
    async def recent_tokens(self, ctx, limit: int = 5):
        """Show most recently tracked tokens.
        
        Args:
            limit: Number of tokens to show (default: 5)
        """
        try:
            if not self.db_session:
                await ctx.send("❌ Database connection not available.")
                return
                
            if limit < 1 or limit > 20:
                await ctx.send("❌ Limit must be between 1 and 20.")
                return
            
            # Create embed for response
            embed = discord.Embed(
                title=f"Most Recent Tokens",
                color=0x5b594f
            )
            
            # Get most recent tokens
            recent_tokens = self.db_session.query(Token).order_by(
                desc(Token.first_seen)
            ).limit(limit).all()
            
            # Add to embed
            for i, token in enumerate(recent_tokens, 1):
                time_since = (datetime.now() - token.first_seen).total_seconds() / 60
                time_str = f"{int(time_since)}m ago" if time_since < 60 else f"{int(time_since / 60)}h ago"
                
                # Format market cap with change if available
                mcap_str = f"${token.current_market_cap_formatted}" if token.current_market_cap_formatted else "N/A"
                
                # Add growth info if we have both initial and current market caps
                growth_str = ""
                if token.initial_market_cap and token.current_market_cap and token.initial_market_cap > 0:
                    growth_pct = ((token.current_market_cap - token.initial_market_cap) / token.initial_market_cap) * 100
                    growth_sign = "+" if growth_pct >= 0 else ""
                    growth_str = f" ({growth_sign}{growth_pct:.2f}%)"
                
                # Create field with token info
                embed.add_field(
                    name=f"{i}. {token.name} ({token.chain})",
                    value=f"Added: {time_str}\nMC: {mcap_str}{growth_str}\n" +
                          f"Source: {token.source}" +
                          (f"\nCaller: {token.credited_user}" if token.credited_user else ""),
                    inline=False
                )
            
            if not recent_tokens:
                embed.add_field(
                    name="No Data",
                    value="No tokens found in the database.",
                    inline=False
                )
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            logging.error(f"Error in recent_tokens command: {e}", exc_info=True)
            await ctx.send("❌ An error occurred while fetching recent tokens.") 