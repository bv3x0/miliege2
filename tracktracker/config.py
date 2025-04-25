"""
Configuration module for tracktracker.

This module provides a centralized configuration system using Pydantic models
for validation and type checking. It loads configuration from environment variables
and provides default values where appropriate.
"""

import os
import pathlib
from typing import Dict, List, Optional, Union

from pydantic import BaseModel, Field, computed_field, validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

# Try to load environment variables from .env file if it exists
load_dotenv()

# Current user's home directory - used for default paths
HOME_DIR = pathlib.Path.home()
# Project root directory - try to determine it dynamically
try:
    # Start with the current file's directory and go up one level to find the project root
    PROJECT_ROOT = pathlib.Path(__file__).parent.parent.absolute()
except Exception:
    # Fallback to current working directory
    PROJECT_ROOT = pathlib.Path.cwd()


class SpotifySettings(BaseModel):
    """Spotify API settings."""
    client_id: str = Field(default_factory=lambda: os.environ.get("SPOTIFY_CLIENT_ID", ""))
    client_secret: str = Field(default_factory=lambda: os.environ.get("SPOTIFY_CLIENT_SECRET", ""))
    redirect_uri: str = Field(default_factory=lambda: os.environ.get("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback"))
    
    @validator("client_id", "client_secret")
    def validate_credentials(cls, v, values, **kwargs):
        """Validate that credentials are not empty."""
        if not v:
            field_name = kwargs["field"].name
            raise ValueError(f"Spotify {field_name} is required. Set the SPOTIFY_{field_name.upper()} environment variable.")
        return v


class PathSettings(BaseModel):
    """Path configuration for the application."""
    cache_dir: pathlib.Path = Field(default_factory=lambda: HOME_DIR / ".tracktracker")
    data_dir: pathlib.Path = Field(default_factory=lambda: PROJECT_ROOT / "website" / "src" / "data")
    show_images_dir: pathlib.Path = Field(default_factory=lambda: PROJECT_ROOT / "website" / "public" / "show-images")
    
    @computed_field
    @property
    def spotify_token_path(self) -> pathlib.Path:
        """Path to Spotify token cache file."""
        return self.cache_dir / "spotify_token.json"
    
    @computed_field
    @property
    def track_cache_path(self) -> pathlib.Path:
        """Path to track search cache file."""
        return self.cache_dir / "track_cache.json"
    
    @computed_field
    @property
    def shows_data_path(self) -> pathlib.Path:
        """Path to shows data file."""
        return self.data_dir / "shows.json"


class APISettings(BaseModel):
    """API request settings."""
    user_agent: str = "tracktracker/1.0"
    timeout: int = 30
    max_retries: int = 3
    retry_backoff: float = 2.0
    base_delay: float = 1.0
    max_delay: float = 60.0


class Settings(BaseSettings):
    """Main settings class for the application."""
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    
    # Application info
    app_name: str = "TrackTracker"
    app_version: str = "1.0.0"
    
    # API configuration
    spotify: SpotifySettings = Field(default_factory=SpotifySettings)
    api: APISettings = Field(default_factory=APISettings)
    
    # Paths
    paths: PathSettings = Field(default_factory=PathSettings)
    
    # Log level
    log_level: str = Field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO"))
    
    def ensure_directories(self) -> None:
        """Ensure that all required directories exist."""
        self.paths.cache_dir.mkdir(parents=True, exist_ok=True)
        self.paths.data_dir.mkdir(parents=True, exist_ok=True)
        self.paths.show_images_dir.mkdir(parents=True, exist_ok=True)


# Create a global settings instance
settings = Settings()

# Make sure directories exist
settings.ensure_directories()


def get_settings() -> Settings:
    """
    Get the application settings instance.
    
    Returns:
        Settings instance.
    """
    return settings