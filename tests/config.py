"""Stub config module לטסטים שמדמה קריאה מה-ENV ללא תלות ב-pydantic."""

from __future__ import annotations

import os


_DEFAULT_MAINTENANCE_MESSAGE = (
    "🚀 אנחנו מעלים עדכון חדש!\nהבוט יחזור לפעול ממש בקרוב (1 - 3 דקות)"
)


def _coerce_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _coerce_int(value: str | None, default: int) -> int:
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except Exception:
        return default


class _Cfg:
    def __init__(self) -> None:
        self.SENTRY_DSN = ""
        self.ENVIRONMENT = os.getenv("ENVIRONMENT", "test")
        self.RECYCLE_TTL_DAYS = _coerce_int(os.getenv("RECYCLE_TTL_DAYS"), 7)
        self.MAX_CODE_SIZE = _coerce_int(os.getenv("MAX_CODE_SIZE"), 100_000)
        self.MAINTENANCE_MODE = _coerce_bool(os.getenv("MAINTENANCE_MODE"), False)
        self.MAINTENANCE_MESSAGE = os.getenv(
            "MAINTENANCE_MESSAGE", _DEFAULT_MAINTENANCE_MESSAGE
        )
        self.MAINTENANCE_AUTO_WARMUP_SECS = _coerce_int(
            os.getenv("MAINTENANCE_AUTO_WARMUP_SECS"), 30
        )
        self.PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL")
        self.WEBAPP_URL = os.getenv("WEBAPP_URL")


config = _Cfg()
