from pydantic_settings import BaseSettings # type: ignore
from typing import Final, Optional

class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    DISCORD_BOT_TOKEN: str
    DAILY_DIGEST_CHANNEL_ID: int
    MAX_TOKENS: int = 1000
    CACHE_TIMEOUT: int = 3600
    
    # API Settings
    DEFAULT_API_TIMEOUT: int = 30
    DEFAULT_RATE_LIMIT: float = 1.0
    
    # Bot Settings
    MAX_ERRORS: int = 50
    UPDATE_INTERVAL: int = 300  # 5 minutes
    
    # Channel Settings
    CIELO_OUTPUT_CHANNEL_ID: Optional[int] = None  # New field for Cielo output channel

    # RSS Settings (RSS_CHANNEL_ID used for migration only, feeds now managed via /rss commands)
    RSS_CHANNEL_ID: Optional[int] = None

    class Config:
        env_file = ".env"

# UI Constants
class UI:
    """UI-related constants including colors and messages"""
    # Colors
    EMBED_BORDER: Final = 0x5b594f
    LONG_COLOR: Final = 0x00ff00
    SHORT_COLOR: Final = 0xff0000
    
    # Messages
    ERROR_GENERIC: Final = "❌ An unexpected error occurred"
    NO_RESULTS: Final = "<:dwbb:1321571679109124126>"
    SUCCESS: Final = "✅"

settings = Settings()  # Create a singleton instance