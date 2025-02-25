from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()

class Token(Base):
    """Model for storing token information."""
    __tablename__ = 'tokens'
    
    id = Column(Integer, primary_key=True)
    contract_address = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    chain = Column(String(50))
    chart_url = Column(String(255))
    initial_market_cap = Column(Float)
    initial_market_cap_formatted = Column(String(50))
    current_market_cap = Column(Float)
    current_market_cap_formatted = Column(String(50))
    message_id = Column(String(50))
    channel_id = Column(String(50))
    guild_id = Column(String(50))
    source = Column(String(50))  # 'cielo', 'rick', etc.
    credited_user = Column(String(100))
    first_seen = Column(DateTime, default=datetime.now)
    last_updated = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    market_cap_updates = relationship("MarketCapUpdate", back_populates="token", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Token(name='{self.name}', contract='{self.contract_address}')>"


class MarketCapUpdate(Base):
    """Model for tracking market cap updates over time."""
    __tablename__ = 'market_cap_updates'
    
    id = Column(Integer, primary_key=True)
    token_id = Column(Integer, ForeignKey('tokens.id'), nullable=False)
    market_cap = Column(Float)
    market_cap_formatted = Column(String(50))
    timestamp = Column(DateTime, default=datetime.now)
    
    # Relationship
    token = relationship("Token", back_populates="market_cap_updates")
    
    def __repr__(self):
        return f"<MarketCapUpdate(token_id={self.token_id}, market_cap={self.market_cap_formatted})>"
