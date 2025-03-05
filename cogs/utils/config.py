from pydantic import BaseSettings

class Settings(BaseSettings):
    DISCORD_BOT_TOKEN: str
    DAILY_DIGEST_CHANNEL_ID: int
    MAX_TOKENS: int = 1000
    CACHE_TIMEOUT: int = 3600
    
    class Config:
        env_file = ".env" 