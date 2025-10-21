from __future__ import annotations

from typing import List, Optional

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


class BotConfig(BaseSettings):
    """
    קונפיגורציה עיקרית של הבוט המבוססת על Pydantic Settings.

    - קורא אוטומטית משתני סביבה ו-`.env`.
    - מבצע המרות טיפוסים ו-Validation ברור.
    """

    # שדות חובה
    BOT_TOKEN: str = Field(..., description="Telegram bot token")
    MONGODB_URL: str = Field(..., description="MongoDB connection string")

    # בסיסי DB
    DATABASE_NAME: str = Field(
        default="code_keeper_bot", description="MongoDB database name"
    )

    # Cache/Redis
    REDIS_URL: Optional[str] = Field(default=None, description="Redis URL")
    CACHE_ENABLED: bool = Field(
        default=False, description="Enable in-memory/Redis caching where applicable"
    )

    # אינטגרציות
    GITHUB_TOKEN: Optional[str] = Field(default=None, description="GitHub token")
    PASTEBIN_API_KEY: Optional[str] = Field(default=None, description="Pastebin API key")

    # מגבלות ושדות כלליים
    MAX_CODE_SIZE: int = Field(
        default=100_000,
        ge=1_000,
        le=10_000_000,
        description="Maximum code size in bytes",
    )
    MAX_FILES_PER_USER: int = Field(
        default=1_000, ge=1, le=100_000, description="Maximum files per user"
    )
    SUPPORTED_LANGUAGES: List[str] = Field(
        default_factory=lambda: [
            "python",
            "javascript",
            "html",
            "css",
            "java",
            "cpp",
            "c",
            "php",
            "ruby",
            "go",
            "rust",
            "typescript",
            "sql",
            "bash",
            "json",
            "xml",
            "yaml",
            "markdown",
            "dockerfile",
            "nginx",
        ],
        description="Supported languages for code highlighting and features",
    )

    # סל מיחזור
    RECYCLE_TTL_DAYS: int = Field(
        default=7, ge=1, description="Days to keep items in recycle bin"
    )

    # URL-ים
    PUBLIC_BASE_URL: Optional[str] = Field(
        default=None, description="Public base URL for sharing links"
    )
    WEBAPP_URL: Optional[str] = Field(
        default=None, description="WebApp base URL (if different from public)"
    )

    # תחזוקה
    MAINTENANCE_MODE: bool = Field(default=False, description="Maintenance gate")
    MAINTENANCE_MESSAGE: str = Field(
        default="🚀 אנחנו מעלים עדכון חדש!\nהבוט יחזור לפעול ממש בקרוב (1 - 3 דקות)",
        description="User-facing maintenance message",
    )
    MAINTENANCE_AUTO_WARMUP_SECS: int = Field(
        default=30, ge=1, le=600, description="Warmup seconds after maintenance"
    )

    # קצב
    RATE_LIMIT_PER_MINUTE: int = Field(
        default=30, ge=1, description="Default rate limit per minute"
    )

    # עיצוב
    HIGHLIGHT_THEME: str = Field(default="github-dark", description="Pygments theme")

    # Git
    GIT_CHECKPOINT_PREFIX: str = Field(
        default="checkpoint", description="Prefix for git checkpoints"
    )

    # Google Drive OAuth
    GOOGLE_CLIENT_ID: Optional[str] = Field(default=None, description="OAuth client id")
    GOOGLE_CLIENT_SECRET: Optional[str] = Field(
        default=None, description="OAuth client secret"
    )
    GOOGLE_OAUTH_SCOPES: str = Field(
        default="https://www.googleapis.com/auth/drive.file",
        description="OAuth scopes for Google Drive",
    )
    GOOGLE_TOKEN_REFRESH_MARGIN_SECS: int = Field(
        default=120, ge=30, le=3600, description="Refresh token margin (seconds)"
    )

    # דגלים ותיעוד
    DRIVE_MENU_V2: bool = Field(default=True, description="Enable Drive menu v2")
    DOCUMENTATION_URL: str = Field(
        default="https://amirbiron.github.io/CodeBot/", description="Docs URL"
    )
    BOT_LABEL: str = Field(default="CodeBot", description="Bot label for UI")
    DRIVE_ADD_HASH: bool = Field(
        default=False, description="Append hash to filenames to avoid collisions"
    )
    NORMALIZE_CODE_ON_SAVE: bool = Field(
        default=True, description="Normalize hidden characters before save"
    )

    # Observability / Sentry
    SENTRY_DSN: Optional[str] = Field(
        default=None, description="Sentry DSN for error reporting"
    )

    # Metrics DB
    METRICS_DB_ENABLED: bool = Field(
        default=False, description="Enable metrics dual-write to DB"
    )
    METRICS_COLLECTION: str = Field(
        default="service_metrics", description="Metrics collection name"
    )
    METRICS_BATCH_SIZE: int = Field(
        default=50, ge=1, le=10_000, description="Metrics batch size"
    )
    METRICS_FLUSH_INTERVAL_SEC: int = Field(
        default=5, ge=1, le=300, description="Metrics flush interval in seconds"
    )

    # הגדרות קריאה מ-.env ומשתני סביבה
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """אפשר שרשרת קבצי .env: קודם .env.local ואז .env, בנוסף למשתני סביבה."""
        return (
            init_settings,
            env_settings,
            # local overrides
            DotEnvSettingsSource(settings_cls, env_file=".env.local", case_sensitive=True),
            # default .env
            DotEnvSettingsSource(settings_cls, env_file=".env", case_sensitive=True),
            file_secret_settings,
        )

    @field_validator("MONGODB_URL")
    @classmethod
    def _validate_mongodb_url(cls, v: str) -> str:
        if not v or not v.startswith(("mongodb://", "mongodb+srv://")):
            raise ValueError(
                "MONGODB_URL must start with mongodb:// or mongodb+srv://"
            )
        return v


def load_config() -> BotConfig:
    """
    טוען את הקונפיגורציה ומחזיר מופע של BotConfig.

    נשמרת תאימות לאחור עבור טסטים/קריאות קיימות.
    """
    return BotConfig()


# יצירת אינסטנס גלובלי של הקונפיגורציה בזמן import — נשמרת תאימות לטסטים
try:
    config = load_config()
except ValidationError as exc:  # תאימות לטסט שמצפה ValueError בזמן import
    # המרה ל-ValueError כדי לשמר התנהגות היסטורית
    raise ValueError(str(exc)) from exc
