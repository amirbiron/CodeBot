"""Central settings for app modules.

Note: This repo historically uses a top-level `config.py` and Flask config.
This module exists to support code that expects a FastAPI-style `settings` object
under `app.core.config`.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    Values are read from environment variables.
    """

    model_config = SettingsConfigDict(
        env_file=(".env", "render.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # JWT
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    ALGORITHM: str = "HS256"

    # Expiration
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60


settings = Settings()
