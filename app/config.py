"""
Configuration module — loads settings from environment variables / .env file.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings backed by environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # OAuth Keys
    github_client_id: str = ""
    github_client_secret: str = ""
    session_secret_key: str = "super_secret_default_key_change_in_production"

    inactivity_months: int = 6
    hibp_api_key: str | None = None

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    
    # Reddit API Credentials
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    reddit_username: str | None = None
    reddit_password: str | None = None


# Singleton instance — import this wherever settings are needed.
settings = Settings()
