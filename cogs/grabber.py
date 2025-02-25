import discord # type: ignore
from discord.ext import commands
import re
import logging
import asyncio
from utils import format_large_number, get_age_string, safe_api_call
from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean, ForeignKey, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import Token, Alert, MarketCapSnapshot
from db.engine import AsyncSessionLocal, create_tables

class TokenGrabber(commands.Cog):
    def __init__(self, bot, token_tracker, monitor, session):
        self.bot = bot
        self.token_tracker = token_tracker
        self.monitor = monitor
        self.session = session

    @commands.Cog.listener()
    async def on_message(self, message):
        try:
            # Only do detailed logging for Cielo messages
            if message.author.bot and message.author.name == "Cielo":
                logging.info("""
=== Cielo Message Detected ===
Content: %s
Has Embeds: %s
Embed Count: %d
""", message.content, bool(message.embeds), len(message.embeds) if message.embeds else 0)
                
                # Detailed embed field logging
                if message.embeds:
                    for i, embed in enumerate(message.embeds):
                        logging.info(f"\nEmbed {i} Details:")
                        if embed.author:
                            logging.info(f"Author: {embed.author.name}")
                        logging.info(f"Title: {embed.title}")
                        logging.info(f"Description: {embed.description}")
                        # Log the raw embed data to see the tag field
                        logging.info(f"Raw embed data: {embed.to_dict()}")
                        
                        for j, field in enumerate(embed.fields):
                            logging.info(f"Field {j}:")
                            logging.info(f"  Name: '{field.name}'")
                            logging.info(f"  Value: '{field.value}'")
                            logging.info(f"  Inline: {field.inline}")
                
                # Extract credit from embed title
                credit_user = None
                if message.embeds:
                    for embed in message.embeds:
                        if embed.title and '🏷' in embed.title:
                            # Remove the tag emoji and strip whitespace
                            credit_user = embed.title.replace('🏷', '').strip()
                            logging.info(f"Found credit user in embed title: {credit_user}")
                            break
                
                if not credit_user:
                    logging.warning("Could not find credit user in embed title")

                if message.embeds:
                    for embed in message.embeds:
                        for field in embed.fields:
                            # Look for "Token:" within the field value
                            if "Token:" in field.value:
                                logging.info(f"Found Token field: {field.value}")
                                match = re.search(r'Token:\s*`([a-zA-Z0-9]+)`', field.value)
                                if match:
                                    contract_address = match.group(1)
                                    logging.info(f"Processing token: {contract_address}")
                                    await self._process_token(contract_address, message, credit_user)
                                    return
                else:
                    logging.warning("Cielo message had no embeds")
            else:
                # Basic debug level logging for non-Cielo messages
                logging.debug(f"Message from {message.author.name}")
                    
        except Exception as e:
            logging.error(f"Error in message processing: {e}", exc_info=True)
            self.monitor.record_error()

    async def _process_token(self, contract_address, message, credit_user=None):
        try:
            dex_api_url = f"https://api.dexscreener.com/latest/dex/tokens/{contract_address}"
            logging.info(f"Querying Dexscreener API: {dex_api_url}")
            
            async with safe_api_call(self.session, dex_api_url) as dex_data:
                if dex_data and 'pairs' in dex_data and dex_data['pairs']:
                    pair = dex_data['pairs'][0]
                    
                    # Extract data
                    chain = pair.get('chainId', 'Unknown Chain')
                    price_change_24h = pair.get('priceChange', {}).get('h24', 'N/A')
                    market_cap = pair.get('fdv', 'N/A')
                    token_name = pair.get('baseToken', {}).get('name', 'Unknown Token')
                    banner_image = pair.get('info', {}).get('header', None)
                    
                    # Get socials from pair info
                    socials = pair.get('info', {})
                    website = socials.get('website', '')
                    twitter = socials.get('twitter', '')
                    telegram = socials.get('telegram', '')
                    
                    # Store raw market cap value for comparison
                    market_cap_value = market_cap if isinstance(market_cap, (int, float)) else None
                    
                    # Format market cap
                    if market_cap_value is not None:
                        formatted_mcap = format_large_number(market_cap_value)
                    else:
                        formatted_mcap = "N/A"
                    
                    # Format price change with explicit +/- and "24h: " prefix
                    if isinstance(price_change_24h, (int, float)):
                        # Add + sign for positive changes, - is automatically included for negative
                        sign = '+' if float(price_change_24h) >= 0 else ''
                        price_change_formatted = f"24h: {sign}{price_change_24h}%"
                    else:
                        price_change_formatted = "24h: N/A"
                    
                    # Create chart URL
                    chart_url = f"https://dexscreener.com/{chain.lower()}/{contract_address}"
                    
                    # Extract pair creation time
                    pair_created_at = pair.get('pairCreatedAt')
                    age_string = get_age_string(pair_created_at)

                    # Extract social links (using the old format)
                    socials = pair.get('info', {}).get('socials', [])
                    tg_link = next((s['url'] for s in socials if s['type'] == 'telegram'), None)
                    twitter_link = next((s['url'] for s in socials if s['type'] == 'twitter'), None)

                    # Extract website link
                    websites = pair.get('info', {}).get('websites', [])
                    website_link = websites[0]['url'] if websites else None

                    # Format social links
                    social_parts = []
                    if website_link:
                        social_parts.append(f"[Web]({website_link})")
                    if twitter_link:
                        social_parts.append(f"[𝕏]({twitter_link})")
                    if tg_link:
                        social_parts.append(f"[TG]({tg_link})")
                    
                    # Create embed response
                    embed = discord.Embed(
                        color=0x5b594f
                    )
                    
                    # Add banner if available
                    if banner_image:
                        embed.set_image(url=banner_image)
                    
                    # Format market cap with dollar sign
                    if market_cap_value is not None:
                        formatted_mcap = f"${format_large_number(market_cap_value)}"
                    else:
                        formatted_mcap = "N/A"
                    
                    # Create multi-line format - using h2 header formatting for first line
                    title_line = f"## [{token_name} ({pair.get('baseToken', {}).get('symbol', 'Unknown')})]({chart_url})"
                    stats_line = f"{formatted_mcap} mc ⋅ {price_change_formatted} ⋅ {chain.lower()}"
                    
                    embed.description = f"{title_line}\n{stats_line}"
                    
                    # Add social links and age
                    links_text = []
                    if social_parts:
                        links_text.append(" ⋅ ".join(social_parts))
                    else:
                        links_text.append("No socials")
                    if age_string:
                        links_text.append(age_string)
                    embed.add_field(name="", value=" ⋅ ".join(links_text), inline=False)
                    
                    # Add note for market caps under $2M (without "Note:" prefix)
                    if market_cap_value and market_cap_value < 2_000_000:
                        embed.add_field(name="", value="_Under $2m !_ <:wow:1149703956746997871>", inline=False)
                    
                    # Store token data with raw market cap value
                    token_data = {
                        'name': token_name,
                        'chart_url': chart_url,
                        'initial_market_cap': market_cap_value,
                        'initial_market_cap_formatted': formatted_mcap,
                        'chain': chain,
                        'message_id': message.id,
                        'channel_id': message.channel.id,
                        'guild_id': message.guild.id if message.guild else None
                    }
                    self.token_tracker.log_token(contract_address, token_data, 'cielo', credit_user)
                    
                    await message.channel.send(embed=embed)
                else:
                    await message.channel.send("❌ **Error:** No trading pairs found for this token.")
                    
        except Exception as e:
            logging.error(f"Error processing token {contract_address}: {e}", exc_info=True)
            await message.channel.send("❌ **Error:** Failed to process token information.")

class TokenTracker:
    def __init__(self, db_session):
        self.db = db_session
        self.update_lock = asyncio.Lock()
        # For backward compatibility, maintain in-memory cache
        self.tokens = {}  # This will mirror database but provide fast access
        
    async def log_token(self, contract: str, data: dict, source: str, user: str = None) -> None:
        """Log a token to the database while maintaining the existing interface"""
        # Update in-memory cache for backward compatibility
        if contract in self.tokens:
            self.tokens[contract].update({
                **data,
                'timestamp': datetime.now(),
                # Preserve original source and user if this is an update
                'source': self.tokens[contract]['source'],
                'user': self.tokens[contract]['user'],
            })
        else:
            self.tokens[contract] = {
                **data,
                'timestamp': datetime.now(),
                'source': source,
                'user': user
            }
        
        # Now update the database
        async with self.db.begin():
            # Check if token exists
            result = await self.db.execute(
                select(Token).where(Token.contract_address == contract)
            )
            token = result.scalars().first()
            
            if not token:
                # Create new token record
                token = Token(
                    contract_address=contract,
                    name=data.get('name', 'Unknown'),
                    chain=data.get('chain', 'Unknown'),
                    first_seen_at=datetime.now(),
                    initial_market_cap=data.get('market_cap'),
                    initial_market_cap_formatted=data.get('market_cap_formatted'),
                    source=source
                )
                self.db.add(token)
            
            # Create alert record
            alert = Alert(
                contract_address=contract,
                message_id=data.get('message_id'),
                channel_id=data.get('channel_id'),
                guild_id=data.get('guild_id'),
                timestamp=datetime.now(),
                credited_user=user
            )
            self.db.add(alert)
            
            # Add initial market cap snapshot if available
            if data.get('market_cap'):
                snapshot = MarketCapSnapshot(
                    contract_address=contract,
                    timestamp=datetime.now(),
                    market_cap=data.get('market_cap'),
                    market_cap_formatted=data.get('market_cap_formatted'),
                    price=data.get('price')
                )
                self.db.add(snapshot)
    
    async def update_market_caps(self, session, max_tokens: int = 20, rate_limit: float = 0.5):
        """Update market caps for tracked tokens"""
        async with self.update_lock:
            # Get tokens to update
            result = await self.db.execute(
                select(Token).order_by(Token.first_seen_at.desc()).limit(max_tokens)
            )
            tokens = result.scalars().all()
            
            update_count = 0
            for token in tokens:
                # Add rate limiting delay
                if update_count > 0:
                    await asyncio.sleep(rate_limit)
                
                try:
                    dex_api_url = f"https://api.dexscreener.com/latest/dex/tokens/{token.contract_address}"
                    async with safe_api_call(session, dex_api_url) as dex_data:
                        if dex_data and dex_data.get('pairs'):
                            pair = dex_data['pairs'][0]
                            
                            if 'fdv' in pair:
                                market_cap = float(pair['fdv'])
                                market_cap_formatted = format_large_number(market_cap)
                                
                                # Add new snapshot
                                snapshot = MarketCapSnapshot(
                                    contract_address=token.contract_address,
                                    timestamp=datetime.now(),
                                    market_cap=market_cap,
                                    market_cap_formatted=market_cap_formatted,
                                    price=float(pair.get('priceUsd', 0))
                                )
                                self.db.add(snapshot)
                                await self.db.commit()
                                
                                update_count += 1
                                logging.info(f"Updated market cap for {token.name}")
                
                except Exception as e:
                    logging.error(f"Error updating market cap for {token.contract_address}: {e}")
                    continue
            
            return update_count

    async def load_from_database(self):
        """Load tokens from database into memory cache on startup"""
        result = await self.db.execute(
            select(Token)
            .order_by(Token.first_seen_at.desc())
            .limit(self.max_tokens)  # Keep the max_tokens limit
        )
        tokens = result.scalars().all()
        
        # For each token, get its latest alert and market cap
        for token in tokens:
            # Get latest alert
            alert_result = await self.db.execute(
                select(Alert)
                .where(Alert.contract_address == token.contract_address)
                .order_by(Alert.timestamp.desc())
                .limit(1)
            )
            latest_alert = alert_result.scalars().first()
            
            # Get latest market cap
            mcap_result = await self.db.execute(
                select(MarketCapSnapshot)
                .where(MarketCapSnapshot.contract_address == token.contract_address)
                .order_by(MarketCapSnapshot.timestamp.desc())
                .limit(1)
            )
            latest_mcap = mcap_result.scalars().first()
            
            # Store in memory cache
            self.tokens[token.contract_address] = {
                'name': token.name,
                'chain': token.chain,
                'timestamp': latest_alert.timestamp if latest_alert else token.first_seen_at,
                'source': token.source,
                'user': latest_alert.credited_user if latest_alert else None,
                'market_cap': latest_mcap.market_cap if latest_mcap else None,
                'market_cap_formatted': latest_mcap.market_cap_formatted if latest_mcap else None,
                'initial_market_cap': token.initial_market_cap,
                'initial_market_cap_formatted': token.initial_market_cap_formatted,
                'message_id': latest_alert.message_id if latest_alert else None,
                'channel_id': latest_alert.channel_id if latest_alert else None,
                'guild_id': latest_alert.guild_id if latest_alert else None,
            }
        
        logging.info(f"Loaded {len(self.tokens)} tokens from database")

Base = declarative_base()

class Token(Base):
    __tablename__ = 'tokens'
    
    contract_address = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    chain = Column(String, nullable=False)
    first_seen_at = Column(DateTime, nullable=False)
    initial_market_cap = Column(Float, nullable=True)
    initial_market_cap_formatted = Column(String, nullable=True)
    source = Column(String, nullable=False)  # 'cielo', 'rick', etc.
    
    # Relationships
    alerts = relationship("Alert", back_populates="token")
    market_caps = relationship("MarketCapSnapshot", back_populates="token")

class Alert(Base):
    __tablename__ = 'alerts'
    
    id = Column(Integer, primary_key=True)
    contract_address = Column(String, ForeignKey('tokens.contract_address'))
    message_id = Column(String, nullable=True)
    channel_id = Column(String, nullable=True)
    guild_id = Column(String, nullable=True)
    timestamp = Column(DateTime, nullable=False)
    credited_user = Column(String, nullable=True)
    
    # Relationships
    token = relationship("Token", back_populates="alerts")

class MarketCapSnapshot(Base):
    __tablename__ = 'market_cap_snapshots'
    
    id = Column(Integer, primary_key=True)
    contract_address = Column(String, ForeignKey('tokens.contract_address'))
    timestamp = Column(DateTime, nullable=False)
    market_cap = Column(Float, nullable=True)
    market_cap_formatted = Column(String, nullable=True)
    price = Column(Float, nullable=True)
    
    # Relationships
    token = relationship("Token", back_populates="market_caps")

class DiscordBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix='!', intents=intents, help_command=None)
        
        self.db_session = AsyncSessionLocal()
        self.monitor = BotMonitor()
        self.token_tracker = TokenTracker(self.db_session)
        self.session = None  # Will be initialized in setup_hook

    async def setup_hook(self):
        # Create a shared aiohttp session
        self.session = aiohttp.ClientSession()
        logger.info("Created shared aiohttp session")
        
        # Initialize database tables if they don't exist
        await create_tables()
        
        # Load tokens from database
        await self.token_tracker.load_from_database()
        
        # Add cogs with shared session
        await self.add_cog(TokenGrabber(self, self.token_tracker, self.monitor, self.session))
        await self.add_cog(RickGrabber(self, self.token_tracker, self.monitor, self.session))
        await self.add_cog(DigestCog(self, self.token_tracker, daily_digest_channel_id))
        await self.add_cog(HealthMonitor(self, self.monitor))
        await self.add_cog(FunCommands(self))
        logger.info("Cogs loaded successfully")

    async def close(self):
        # Close database session when bot shuts down
        await self.db_session.close()
        if self.session:
            await self.session.close()
        await super().close()