"""
Config Inspector Service
========================
שירות לסקירת קונפיגורציית האפליקציה.
מספק תמונת מצב של כל משתני הסביבה הפעילים
תוך הסתרת ערכים רגישים.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class ConfigStatus(str, Enum):
    """סטטוס של משתנה קונפיגורציה."""

    DEFAULT = "Default"  # משתמש בערך ברירת המחדל
    MODIFIED = "Modified"  # ערך שונה מברירת המחדל
    MISSING = "Missing"  # משתנה לא מוגדר וגם אין דיפולט


class ConfigSource(str, Enum):
    """מקור הערך של הקונפיגורציה."""

    ENVIRONMENT = "Environment"  # נלקח ממשתנה סביבה
    DEFAULT = "Default"  # נלקח מברירת המחדל


@dataclass
class ConfigDefinition:
    """הגדרת משתנה קונפיגורציה יחיד."""

    key: str
    default: Any = None
    description: str = ""
    category: str = "general"
    sensitive: bool = False  # האם להסתיר את הערך
    required: bool = False  # האם המשתנה הכרחי


@dataclass
class ConfigEntry:
    """ערך קונפיגורציה בודד עם מטא-דאטה."""

    key: str
    active_value: str
    default_value: str
    source: ConfigSource
    status: ConfigStatus
    description: str = ""
    category: str = "general"
    is_sensitive: bool = False


@dataclass
class ConfigOverview:
    """סקירת קונפיגורציה מלאה."""

    entries: List[ConfigEntry] = field(default_factory=list)
    generated_at: str = ""
    total_count: int = 0
    modified_count: int = 0
    missing_count: int = 0
    default_count: int = 0
    categories: List[str] = field(default_factory=list)


class ConfigService:
    """
    שירות לניהול וסקירת קונפיגורציית האפליקציה.

    שימוש:
        service = ConfigService()
        overview = service.get_config_overview()
    """

    # מילים רגישות בשמות משתנים - ערכים אלו יוסתרו
    SENSITIVE_PATTERNS: tuple[str, ...] = (
        "TOKEN",
        "KEY",
        "PASSWORD",
        "SECRET",
        "URI",
        "URL",
        "CREDENTIALS",
        "API_KEY",
        "AUTH",
        "PRIVATE",
        "CERT",
        "DSN",
        "CONNECTION_STRING",
    )

    # ערך ההסתרה לערכים רגישים
    MASKED_VALUE: str = "********"

    # הגדרות כל משתני הקונפיגורציה באפליקציה
    # הגדרות כל משתני הקונפיגורציה באפליקציה
    # NOTE: צומצם ל-Webapp בלבד (הוסר category=telegram כדי לא לדווח Missing על משתני בוט)
    CONFIG_DEFINITIONS: Dict[str, ConfigDefinition] = {
        "MONGODB_URL": ConfigDefinition(
            key="MONGODB_URL",
            default="",
            description="כתובת חיבור ל-MongoDB (חובה)",
            category="database",
            sensitive=True,
            required=True,
        ),
        "MONGODB_URI": ConfigDefinition(
            key="MONGODB_URI",
            default="",
            description="כתובת חיבור חלופית ל-MongoDB",
            category="database",
            sensitive=True,
        ),
        "MONGO_URI": ConfigDefinition(
            key="MONGO_URI",
            default="",
            description="כתובת חיבור חלופית ל-MongoDB (Legacy)",
            category="database",
            sensitive=True,
        ),
        "DATABASE_NAME": ConfigDefinition(
            key="DATABASE_NAME",
            default="code_keeper_bot",
            description="שם מסד הנתונים ב-MongoDB",
            category="database",
        ),
        "MONGO_DB_NAME": ConfigDefinition(
            key="MONGO_DB_NAME",
            default="code_keeper_bot",
            description="שם מסד נתונים חלופי (Legacy)",
            category="database",
        ),
        "MONGODB_MAX_POOL_SIZE": ConfigDefinition(
            key="MONGODB_MAX_POOL_SIZE",
            default="50",
            description="מספר חיבורים מקסימלי לפול MongoDB",
            category="database",
        ),
        "MONGODB_MIN_POOL_SIZE": ConfigDefinition(
            key="MONGODB_MIN_POOL_SIZE",
            default="5",
            description="מספר חיבורים מינימלי לפול MongoDB",
            category="database",
        ),
        "MONGODB_MAX_IDLE_TIME_MS": ConfigDefinition(
            key="MONGODB_MAX_IDLE_TIME_MS",
            default="30000",
            description="זמן סרק מקסימלי לחיבור MongoDB (מילישניות)",
            category="database",
        ),
        "MONGODB_WAIT_QUEUE_TIMEOUT_MS": ConfigDefinition(
            key="MONGODB_WAIT_QUEUE_TIMEOUT_MS",
            default="8000",
            description="זמן המתנה בתור לחיבור MongoDB (מילישניות)",
            category="database",
        ),
        "MONGODB_SERVER_SELECTION_TIMEOUT_MS": ConfigDefinition(
            key="MONGODB_SERVER_SELECTION_TIMEOUT_MS",
            default="5000",
            description="זמן בחירת שרת MongoDB (מילישניות)",
            category="database",
        ),
        "MONGODB_SOCKET_TIMEOUT_MS": ConfigDefinition(
            key="MONGODB_SOCKET_TIMEOUT_MS",
            default="45000",
            description="טיימאאוט סוקט MongoDB (מילישניות)",
            category="database",
        ),
        "MONGODB_CONNECT_TIMEOUT_MS": ConfigDefinition(
            key="MONGODB_CONNECT_TIMEOUT_MS",
            default="5000",
            description="טיימאאוט התחברות ל-MongoDB (מילישניות)",
            category="database",
        ),
        "MONGODB_RETRY_WRITES": ConfigDefinition(
            key="MONGODB_RETRY_WRITES",
            default="true",
            description="הפעלת ניסיונות כתיבה חוזרים ב-MongoDB",
            category="database",
        ),
        "MONGODB_RETRY_READS": ConfigDefinition(
            key="MONGODB_RETRY_READS",
            default="true",
            description="הפעלת ניסיונות קריאה חוזרים ב-MongoDB",
            category="database",
        ),
        "MONGODB_APPNAME": ConfigDefinition(
            key="MONGODB_APPNAME",
            default="",
            description="שם האפליקציה למטא-דאטה MongoDB",
            category="database",
        ),
        "MONGODB_COMPRESSORS": ConfigDefinition(
            key="MONGODB_COMPRESSORS",
            default="",
            description="דחיסנים נתמכים (zstd,snappy,zlib)",
            category="database",
        ),
        "MONGODB_HEARTBEAT_FREQUENCY_MS": ConfigDefinition(
            key="MONGODB_HEARTBEAT_FREQUENCY_MS",
            default="10000",
            description="תדירות בדיקת חיים של MongoDB (מילישניות)",
            category="database",
        ),
        "DB_HEALTH_TOKEN": ConfigDefinition(
            key="DB_HEALTH_TOKEN",
            default="",
            description="טוקן אימות לבדיקות בריאות DB",
            category="database",
            sensitive=True,
        ),
        "DB_HEALTH_SLOW_THRESHOLD_MS": ConfigDefinition(
            key="DB_HEALTH_SLOW_THRESHOLD_MS",
            default="1000",
            description="סף לזיהוי שאילתות איטיות (מילישניות)",
            category="database",
        ),
        "DB_HEALTH_COLLECTIONS_COOLDOWN_SEC": ConfigDefinition(
            key="DB_HEALTH_COLLECTIONS_COOLDOWN_SEC",
            default="30",
            description="זמן קירור בין בדיקות בריאות (שניות)",
            category="database",
        ),
        "ALERT_TELEGRAM_BOT_TOKEN": ConfigDefinition(
            key="ALERT_TELEGRAM_BOT_TOKEN",
            default="",
            description="טוקן בוט התראות טלגרם",
            category="alerts",
            sensitive=True,
        ),
        "ALERT_TELEGRAM_CHAT_ID": ConfigDefinition(
            key="ALERT_TELEGRAM_CHAT_ID",
            default="",
            description="מזהה צ'אט להתראות טלגרם",
            category="alerts",
            sensitive=True,
        ),
        "ALERT_TELEGRAM_MIN_SEVERITY": ConfigDefinition(
            key="ALERT_TELEGRAM_MIN_SEVERITY",
            default="info",
            description="רמת חומרה מינימלית להתראות טלגרם",
            category="alerts",
        ),
        "REDIS_URL": ConfigDefinition(
            key="REDIS_URL",
            default="",
            description="כתובת Redis לקאשינג",
            category="cache",
            sensitive=True,
        ),
        "REDIS_MAX_CONNECTIONS": ConfigDefinition(
            key="REDIS_MAX_CONNECTIONS",
            default="50",
            description="מספר חיבורים מקסימלי ל-Redis",
            category="cache",
        ),
        "REDIS_CONNECT_TIMEOUT": ConfigDefinition(
            key="REDIS_CONNECT_TIMEOUT",
            default="5",
            description="טיימאאוט התחברות ל-Redis (שניות)",
            category="cache",
        ),
        "REDIS_SOCKET_TIMEOUT": ConfigDefinition(
            key="REDIS_SOCKET_TIMEOUT",
            default="5",
            description="טיימאאוט סוקט Redis (שניות)",
            category="cache",
        ),
        "CACHE_ENABLED": ConfigDefinition(
            key="CACHE_ENABLED",
            default="false",
            description="הפעלת קאשינג גלובלי",
            category="cache",
        ),
        "CACHE_CLEAR_BUDGET_SECONDS": ConfigDefinition(
            key="CACHE_CLEAR_BUDGET_SECONDS",
            default="2",
            description="תקציב זמן לניקוי קאש (שניות)",
            category="cache",
        ),
        "DISABLE_CACHE_MAINTENANCE": ConfigDefinition(
            key="DISABLE_CACHE_MAINTENANCE",
            default="false",
            description="השבתת תחזוקת קאש אוטומטית",
            category="cache",
        ),
        "WEB_HOST": ConfigDefinition(
            key="WEB_HOST",
            default="0.0.0.0",
            description="כתובת ה-Host לשרת הווב",
            category="webserver",
        ),
        "WEB_PORT": ConfigDefinition(
            key="WEB_PORT",
            default="10000",
            description="פורט השרת",
            category="webserver",
        ),
        "PORT": ConfigDefinition(
            key="PORT",
            default="5000",
            description="פורט השרת (Render/Heroku)",
            category="webserver",
        ),
        "HOST": ConfigDefinition(
            key="HOST",
            default="0.0.0.0",
            description="כתובת Host חלופית",
            category="webserver",
        ),
        "SECRET_KEY": ConfigDefinition(
            key="SECRET_KEY",
            default="dev-secret-key-change-in-production",
            description="מפתח סודי לסשנים ו-CSRF",
            category="webserver",
            sensitive=True,
            required=True,
        ),
        "WEBAPP_LOGIN_SECRET": ConfigDefinition(
            key="WEBAPP_LOGIN_SECRET",
            default="",
            description="מפתח סודי נוסף ל-login",
            category="webserver",
            sensitive=True,
        ),
        "DEBUG": ConfigDefinition(
            key="DEBUG",
            default="false",
            description="מצב דיבאג (true/false)",
            category="webserver",
        ),
        "PUBLIC_BASE_URL": ConfigDefinition(
            key="PUBLIC_BASE_URL",
            default="",
            description="כתובת URL בסיסית לשיתוף קישורים",
            category="webserver",
        ),
        "WEBAPP_URL": ConfigDefinition(
            key="WEBAPP_URL",
            default="",
            description="כתובת WebApp (אם שונה מ-public)",
            category="webserver",
        ),
        "WEBAPP_ENABLE_WARMUP": ConfigDefinition(
            key="WEBAPP_ENABLE_WARMUP",
            default="1",
            description="הפעלת שלב warmup אוטומטי אחרי עליית Gunicorn (1/0)",
            category="warmup",
        ),
        "WEBAPP_WARMUP_URL": ConfigDefinition(
            key="WEBAPP_WARMUP_URL",
            default="http://127.0.0.1:$PORT/healthz",
            description="יעד curl לבדיקת הבריאות הראשונית",
            category="warmup",
        ),
        "WEBAPP_WARMUP_MAX_ATTEMPTS": ConfigDefinition(
            key="WEBAPP_WARMUP_MAX_ATTEMPTS",
            default="15",
            description="מספר ניסיונות curl עבור בדיקת הבריאות",
            category="warmup",
        ),
        "WEBAPP_WARMUP_DELAY_SECONDS": ConfigDefinition(
            key="WEBAPP_WARMUP_DELAY_SECONDS",
            default="2",
            description="השהיה בין ניסיונות ה-warmup הראשיים (שניות)",
            category="warmup",
        ),
        "WEBAPP_WARMUP_PATHS": ConfigDefinition(
            key="WEBAPP_WARMUP_PATHS",
            default="",
            description="רשימת מסלולי Frontend (CSV) לחימום לאחר שה-Healthz הצליח",
            category="warmup",
        ),
        "WEBAPP_WARMUP_BASE_URL": ConfigDefinition(
            key="WEBAPP_WARMUP_BASE_URL",
            default="http://127.0.0.1:$PORT",
            description="בסיס ה-URL לבקשות ה-Frontend Warmup",
            category="warmup",
        ),
        "WEBAPP_WARMUP_REQUEST_TIMEOUT": ConfigDefinition(
            key="WEBAPP_WARMUP_REQUEST_TIMEOUT",
            default="2",
            description="Timeout בשניות לכל בקשת Frontend Warmup",
            category="warmup",
        ),
        "WEBAPP_WSGI_APP": ConfigDefinition(
            key="WEBAPP_WSGI_APP",
            default="app:app",
            description="מודול ה-WSGI של Flask עבור Gunicorn",
            category="warmup",
        ),
        "WEB_CONCURRENCY": ConfigDefinition(
            key="WEB_CONCURRENCY",
            default="2",
            description="מספר ה-workers של Gunicorn ב-WebApp; אם מוגדר, גובר על ברירת המחדל ומקטין queue_delay תחת עומס",
            category="gunicorn",
        ),
        "WEBAPP_GUNICORN_WORKERS": ConfigDefinition(
            key="WEBAPP_GUNICORN_WORKERS",
            default="2",
            description="מספר ה-workers של Gunicorn (חלופה ל-WEB_CONCURRENCY)",
            category="gunicorn",
        ),
        "WEBAPP_GUNICORN_THREADS": ConfigDefinition(
            key="WEBAPP_GUNICORN_THREADS",
            default="2",
            description="מספר Threads לכל worker כאשר משתמשים ב-gthread (משפר מקביליות לבקשות I/O)",
            category="gunicorn",
        ),
        "WEBAPP_GUNICORN_WORKER_CLASS": ConfigDefinition(
            key="WEBAPP_GUNICORN_WORKER_CLASS",
            default="gthread",
            description="Worker class של Gunicorn",
            category="gunicorn",
        ),
        "WEBAPP_GUNICORN_TIMEOUT": ConfigDefinition(
            key="WEBAPP_GUNICORN_TIMEOUT",
            default="60",
            description="Timeout (שניות) לבקשה ב-Gunicorn",
            category="gunicorn",
        ),
        "WEBAPP_GUNICORN_KEEPALIVE": ConfigDefinition(
            key="WEBAPP_GUNICORN_KEEPALIVE",
            default="2",
            description="keep-alive (שניות) לחיבורים ב-Gunicorn",
            category="gunicorn",
        ),
        "AIOHTTP_POOL_LIMIT": ConfigDefinition(
            key="AIOHTTP_POOL_LIMIT",
            default="50",
            description="מגבלת חיבורים ב-TCPConnector של aiohttp",
            category="http",
        ),
        "AIOHTTP_TIMEOUT_TOTAL": ConfigDefinition(
            key="AIOHTTP_TIMEOUT_TOTAL",
            default="10",
            description="טיימאאוט כולל ל-aiohttp (שניות)",
            category="http",
        ),
        "AIOHTTP_LIMIT_PER_HOST": ConfigDefinition(
            key="AIOHTTP_LIMIT_PER_HOST",
            default="25",
            description="מגבלת חיבורים לכל host",
            category="http",
        ),
        "REQUESTS_POOL_CONNECTIONS": ConfigDefinition(
            key="REQUESTS_POOL_CONNECTIONS",
            default="20",
            description="חיבורי פול עבור requests",
            category="http",
        ),
        "REQUESTS_POOL_MAXSIZE": ConfigDefinition(
            key="REQUESTS_POOL_MAXSIZE",
            default="100",
            description="גודל מקסימלי לפול requests",
            category="http",
        ),
        "REQUESTS_TIMEOUT": ConfigDefinition(
            key="REQUESTS_TIMEOUT",
            default="8.0",
            description="טיימאאוט ברירת מחדל ל-requests (שניות)",
            category="http",
        ),
        "REQUESTS_RETRIES": ConfigDefinition(
            key="REQUESTS_RETRIES",
            default="2",
            description="מספר ניסיונות חוזרים ב-requests",
            category="http",
        ),
        "REQUESTS_RETRY_BACKOFF": ConfigDefinition(
            key="REQUESTS_RETRY_BACKOFF",
            default="0.2",
            description="פקטור backoff בין ניסיונות",
            category="http",
        ),
        "PUSH_NOTIFICATIONS_ENABLED": ConfigDefinition(
            key="PUSH_NOTIFICATIONS_ENABLED",
            default="true",
            description="הפעלת התראות Push",
            category="push",
        ),
        "VAPID_PUBLIC_KEY": ConfigDefinition(
            key="VAPID_PUBLIC_KEY",
            default="",
            description="מפתח VAPID ציבורי ל-Push",
            category="push",
            sensitive=True,
        ),
        "VAPID_PRIVATE_KEY": ConfigDefinition(
            key="VAPID_PRIVATE_KEY",
            default="",
            description="מפתח VAPID פרטי ל-Push",
            category="push",
            sensitive=True,
        ),
        "VAPID_SUB_EMAIL": ConfigDefinition(
            key="VAPID_SUB_EMAIL",
            default="",
            description="כתובת אימייל ל-VAPID",
            category="push",
        ),
        "SUPPORT_EMAIL": ConfigDefinition(
            key="SUPPORT_EMAIL",
            default="",
            description="כתובת אימייל תמיכה",
            category="push",
        ),
        "PUSH_REMOTE_DELIVERY_ENABLED": ConfigDefinition(
            key="PUSH_REMOTE_DELIVERY_ENABLED",
            default="false",
            description="הפעלת משלוח Push מרוחק",
            category="push",
        ),
        "PUSH_DELIVERY_URL": ConfigDefinition(
            key="PUSH_DELIVERY_URL",
            default="",
            description="כתובת URL למשלוח Push",
            category="push",
            sensitive=True,
        ),
        "PUSH_DELIVERY_TOKEN": ConfigDefinition(
            key="PUSH_DELIVERY_TOKEN",
            default="",
            description="טוקן אימות למשלוח Push",
            category="push",
            sensitive=True,
        ),
        "PUSH_DELIVERY_TIMEOUT_SECONDS": ConfigDefinition(
            key="PUSH_DELIVERY_TIMEOUT_SECONDS",
            default="3",
            description="טיימאאוט למשלוח Push (שניות)",
            category="push",
        ),
        "PUSH_DELIVERY_URGENCY": ConfigDefinition(
            key="PUSH_DELIVERY_URGENCY",
            default="high",
            description="רמת דחיפות ברירת מחדל ל-Push",
            category="push",
        ),
        "PUSH_SEND_INTERVAL_SECONDS": ConfigDefinition(
            key="PUSH_SEND_INTERVAL_SECONDS",
            default="60",
            description="מרווח שליחת Push (שניות)",
            category="push",
        ),
        "PUSH_CLAIM_TTL_SECONDS": ConfigDefinition(
            key="PUSH_CLAIM_TTL_SECONDS",
            default="60",
            description="TTL להחזקת Push (שניות)",
            category="push",
        ),
        "GITHUB_TOKEN": ConfigDefinition(
            key="GITHUB_TOKEN",
            default="",
            description="טוקן גישה ל-GitHub",
            category="external",
            sensitive=True,
        ),
        "GITHUB_API_BASE_DELAY": ConfigDefinition(
            key="GITHUB_API_BASE_DELAY",
            default="2.0",
            description="דילי בסיסי בין בקשות GitHub כדי להישאר מתחת לרף rate-limit (שניות)",
            category="external",
        ),
        "GITHUB_BACKOFF_DELAY": ConfigDefinition(
            key="GITHUB_BACKOFF_DELAY",
            default="5.0",
            description="מקדם backoff (שניות) שמתווסף בכל ניסיון כושל לקריאות GitHub",
            category="external",
        ),
        "PASTEBIN_API_KEY": ConfigDefinition(
            key="PASTEBIN_API_KEY",
            default="",
            description="מפתח API ל-Pastebin",
            category="external",
            sensitive=True,
        ),
        "GOOGLE_CLIENT_ID": ConfigDefinition(
            key="GOOGLE_CLIENT_ID",
            default="",
            description="Client ID ל-Google OAuth",
            category="external",
            sensitive=True,
        ),
        "GOOGLE_CLIENT_SECRET": ConfigDefinition(
            key="GOOGLE_CLIENT_SECRET",
            default="",
            description="Client Secret ל-Google OAuth",
            category="external",
            sensitive=True,
        ),
        "GOOGLE_OAUTH_SCOPES": ConfigDefinition(
            key="GOOGLE_OAUTH_SCOPES",
            default="https://www.googleapis.com/auth/drive.file",
            description="OAuth Scopes עבור Google Drive",
            category="external",
        ),
        "GOOGLE_TOKEN_REFRESH_MARGIN_SECS": ConfigDefinition(
            key="GOOGLE_TOKEN_REFRESH_MARGIN_SECS",
            default="120",
            description="שוליים לרענון טוקן Google (שניות)",
            category="external",
        ),
        "SENTRY_DSN": ConfigDefinition(
            key="SENTRY_DSN",
            default="",
            description="DSN ל-Sentry לניטור שגיאות",
            category="monitoring",
            sensitive=True,
        ),
        "SENTRY_ORG": ConfigDefinition(
            key="SENTRY_ORG",
            default="",
            description="שם הארגון ב-Sentry",
            category="monitoring",
        ),
        "SENTRY_ORG_SLUG": ConfigDefinition(
            key="SENTRY_ORG_SLUG",
            default="",
            description="Slug הארגון ב-Sentry",
            category="monitoring",
        ),
        "SENTRY_DASHBOARD_URL": ConfigDefinition(
            key="SENTRY_DASHBOARD_URL",
            default="",
            description="כתובת לוח הבקרה של Sentry",
            category="monitoring",
        ),
        "SENTRY_AUTH_TOKEN": ConfigDefinition(
            key="SENTRY_AUTH_TOKEN",
            default="",
            description="טוקן אימות ל-Sentry API",
            category="monitoring",
            sensitive=True,
        ),
        "SENTRY_TRACES_SAMPLE_RATE": ConfigDefinition(
            key="SENTRY_TRACES_SAMPLE_RATE",
            default="0.1",
            description="שיעור דגימת Traces ב-Sentry",
            category="monitoring",
        ),
        "SENTRY_PROFILES_SAMPLE_RATE": ConfigDefinition(
            key="SENTRY_PROFILES_SAMPLE_RATE",
            default="0.1",
            description="שיעור דגימת Profiles ב-Sentry",
            category="monitoring",
        ),
        "SENTRY_WEBHOOK_SECRET": ConfigDefinition(
            key="SENTRY_WEBHOOK_SECRET",
            default="",
            description="סוד ל-Sentry Webhook",
            category="monitoring",
            sensitive=True,
        ),
        "SENTRY_WEBHOOK_DEDUP_WINDOW_SECONDS": ConfigDefinition(
            key="SENTRY_WEBHOOK_DEDUP_WINDOW_SECONDS",
            default="300",
            description="חלון dedup ל-Sentry Webhooks (שניות)",
            category="monitoring",
        ),
        "SENTRY_TEST_BUTTON_ENABLED": ConfigDefinition(
            key="SENTRY_TEST_BUTTON_ENABLED",
            default="false",
            description="הפעלת כפתור בדיקת Sentry",
            category="monitoring",
        ),
        "GRAFANA_URL": ConfigDefinition(
            key="GRAFANA_URL",
            default="",
            description="כתובת URL של Grafana",
            category="monitoring",
        ),
        "GRAFANA_API_TOKEN": ConfigDefinition(
            key="GRAFANA_API_TOKEN",
            default="",
            description="טוקן API ל-Grafana",
            category="monitoring",
            sensitive=True,
        ),
        "OTEL_EXPORTER_OTLP_ENDPOINT": ConfigDefinition(
            key="OTEL_EXPORTER_OTLP_ENDPOINT",
            default="",
            description="Endpoint ל-OTLP Exporter",
            category="monitoring",
        ),
        "OTEL_EXPORTER_INSECURE": ConfigDefinition(
            key="OTEL_EXPORTER_INSECURE",
            default="false",
            description="שימוש בחיבור לא מאובטח ל-OTLP",
            category="monitoring",
        ),
        "ANTHROPIC_API_URL": ConfigDefinition(
            key="ANTHROPIC_API_URL",
            default="https://api.anthropic.com/v1/messages",
            description="כתובת API של Anthropic",
            category="ai",
        ),
        "ANTHROPIC_API_KEY": ConfigDefinition(
            key="ANTHROPIC_API_KEY",
            default="",
            description="מפתח API ל-Anthropic Claude",
            category="ai",
            sensitive=True,
        ),
        "CLAUDE_API_KEY": ConfigDefinition(
            key="CLAUDE_API_KEY",
            default="",
            description="מפתח API חלופי ל-Claude",
            category="ai",
            sensitive=True,
        ),
        "CLAUDE_MODEL": ConfigDefinition(
            key="CLAUDE_MODEL",
            default="claude-sonnet-4-20250514",
            description="מודל Claude לשימוש",
            category="ai",
        ),
        "OBS_AI_EXPLAIN_MODEL": ConfigDefinition(
            key="OBS_AI_EXPLAIN_MODEL",
            default="claude-sonnet-4-20250514",
            description="מודל AI להסברים באבחון",
            category="ai",
        ),
        "OBS_AI_EXPLAIN_MODEL_FALLBACKS": ConfigDefinition(
            key="OBS_AI_EXPLAIN_MODEL_FALLBACKS",
            default="",
            description="מודלי fallback להסברי AI (מופרדים בפסיקים)",
            category="ai",
        ),
        "OBS_AI_PROVIDER_LABEL": ConfigDefinition(
            key="OBS_AI_PROVIDER_LABEL",
            default="claude-sonnet-4.5",
            description="תווית ספק AI בממשק",
            category="ai",
        ),
        "OBS_AI_EXPLAIN_MAX_TOKENS": ConfigDefinition(
            key="OBS_AI_EXPLAIN_MAX_TOKENS",
            default="800",
            description="מקסימום טוקנים לתשובת AI",
            category="ai",
        ),
        "OBS_AI_EXPLAIN_TEMPERATURE": ConfigDefinition(
            key="OBS_AI_EXPLAIN_TEMPERATURE",
            default="0.2",
            description="טמפרטורה ליצירת טקסט AI",
            category="ai",
        ),
        "OBS_AI_EXPLAIN_TIMEOUT": ConfigDefinition(
            key="OBS_AI_EXPLAIN_TIMEOUT",
            default="10",
            description="טיימאאוט לבקשות AI (שניות)",
            category="ai",
        ),
        "OBS_AI_EXPLAIN_CACHE_TTL": ConfigDefinition(
            key="OBS_AI_EXPLAIN_CACHE_TTL",
            default="600",
            description="TTL לקאש הסברי AI (שניות)",
            category="ai",
        ),
        "AI_EXPLAIN_URL": ConfigDefinition(
            key="AI_EXPLAIN_URL",
            default="",
            description="כתובת שירות AI Explain חיצוני",
            category="ai",
        ),
        "AI_EXPLAIN_TOKEN": ConfigDefinition(
            key="AI_EXPLAIN_TOKEN",
            default="",
            description="טוקן אימות לשירות AI Explain",
            category="ai",
            sensitive=True,
        ),
        "LOG_LEVEL": ConfigDefinition(
            key="LOG_LEVEL",
            default="INFO",
            description="רמת הלוגים (DEBUG/INFO/WARNING/ERROR)",
            category="logging",
        ),
        "LOG_FORMAT": ConfigDefinition(
            key="LOG_FORMAT",
            default="json",
            description="פורמט הלוגים (json/console)",
            category="logging",
        ),
        "LOG_INFO_SAMPLE_RATE": ConfigDefinition(
            key="LOG_INFO_SAMPLE_RATE",
            default="1.0",
            description="שיעור דגימת לוגים ברמת INFO",
            category="logging",
        ),
        "LOG_INFO_SAMPLE_ALLOWLIST": ConfigDefinition(
            key="LOG_INFO_SAMPLE_ALLOWLIST",
            default="",
            description="רשימת אירועים שלא יידגמו (מופרדים בפסיקים)",
            category="logging",
        ),
        "RECENT_ERRORS_BUFFER": ConfigDefinition(
            key="RECENT_ERRORS_BUFFER",
            default="200",
            description="גודל באפר השגיאות האחרונות",
            category="logging",
        ),
        "LOG_AGGREGATOR_ENABLED": ConfigDefinition(
            key="LOG_AGGREGATOR_ENABLED",
            default="false",
            description="הפעלת Log Aggregator",
            category="logging",
        ),
        "LOG_AGGREGATOR_SHADOW": ConfigDefinition(
            key="LOG_AGGREGATOR_SHADOW",
            default="false",
            description="מצב צל ל-Log Aggregator",
            category="logging",
        ),
        "LOG_AGG_RELOAD_SECONDS": ConfigDefinition(
            key="LOG_AGG_RELOAD_SECONDS",
            default="60",
            description="מרווח טעינה מחדש של הגדרות Log Agg",
            category="logging",
        ),
        "LOG_AGG_ECHO": ConfigDefinition(
            key="LOG_AGG_ECHO",
            default="0",
            description="הדפסת לוגים למסוף (debug)",
            category="logging",
        ),
        "ERROR_SIGNATURES_PATH": ConfigDefinition(
            key="ERROR_SIGNATURES_PATH",
            default="config/error_signatures.yml",
            description="נתיב לקובץ חתימות שגיאות",
            category="logging",
        ),
        "ALERTS_GROUPING_CONFIG": ConfigDefinition(
            key="ALERTS_GROUPING_CONFIG",
            default="config/alerts.yml",
            description="נתיב לקובץ קיבוץ התראות",
            category="logging",
        ),
        "ALERT_COOLDOWN_SEC": ConfigDefinition(
            key="ALERT_COOLDOWN_SEC",
            default="300",
            description="זמן קירור בין התראות מאותו סוג (שניות)",
            category="alerts",
        ),
        "ALERT_THRESHOLD_SCALE": ConfigDefinition(
            key="ALERT_THRESHOLD_SCALE",
            default="1.0",
            description="מכפיל סף התראות כללי",
            category="alerts",
        ),
        "ALERT_ERROR_THRESHOLD_SCALE": ConfigDefinition(
            key="ALERT_ERROR_THRESHOLD_SCALE",
            default="1.0",
            description="מכפיל סף התראות שגיאות",
            category="alerts",
        ),
        "ALERT_LATENCY_THRESHOLD_SCALE": ConfigDefinition(
            key="ALERT_LATENCY_THRESHOLD_SCALE",
            default="1.0",
            description="מכפיל סף התראות חביון",
            category="alerts",
        ),
        "ALERT_MIN_ERROR_RATE_PERCENT": ConfigDefinition(
            key="ALERT_MIN_ERROR_RATE_PERCENT",
            default="5.0",
            description="רצפת אחוז שגיאות מינימלי להתראה",
            category="alerts",
        ),
        "ALERT_MIN_LATENCY_SECONDS": ConfigDefinition(
            key="ALERT_MIN_LATENCY_SECONDS",
            default="1.0",
            description="רצפת חביון מינימלי להתראה (שניות)",
            category="alerts",
        ),
        "ALERT_MIN_SAMPLE_COUNT": ConfigDefinition(
            key="ALERT_MIN_SAMPLE_COUNT",
            default="15",
            description="מספר דגימות מינימלי להתראה",
            category="alerts",
        ),
        "ALERT_ERROR_MIN_SAMPLE_COUNT": ConfigDefinition(
            key="ALERT_ERROR_MIN_SAMPLE_COUNT",
            default="15",
            description="דגימות מינימלי להתראת שגיאות",
            category="alerts",
        ),
        "ALERT_LATENCY_MIN_SAMPLE_COUNT": ConfigDefinition(
            key="ALERT_LATENCY_MIN_SAMPLE_COUNT",
            default="15",
            description="דגימות מינימלי להתראת חביון",
            category="alerts",
        ),
        "ALERT_EACH_ERROR": ConfigDefinition(
            key="ALERT_EACH_ERROR",
            default="false",
            description="התראה על כל שגיאה בודדת",
            category="alerts",
        ),
        "ALERT_EACH_ERROR_COOLDOWN_SECONDS": ConfigDefinition(
            key="ALERT_EACH_ERROR_COOLDOWN_SECONDS",
            default="120",
            description="קירור בין התראות שגיאה בודדת",
            category="alerts",
        ),
        "ALERT_EACH_ERROR_TTL_SECONDS": ConfigDefinition(
            key="ALERT_EACH_ERROR_TTL_SECONDS",
            default="3600",
            description="TTL למעקב שגיאות בודדות",
            category="alerts",
        ),
        "ALERT_EACH_ERROR_MAX_KEYS": ConfigDefinition(
            key="ALERT_EACH_ERROR_MAX_KEYS",
            default="1000",
            description="מקסימום מפתחות מעקב שגיאות",
            category="alerts",
        ),
        "ALERT_EACH_ERROR_INCLUDE": ConfigDefinition(
            key="ALERT_EACH_ERROR_INCLUDE",
            default="",
            description="פילטר include לשגיאות בודדות",
            category="alerts",
        ),
        "ALERT_EACH_ERROR_EXCLUDE": ConfigDefinition(
            key="ALERT_EACH_ERROR_EXCLUDE",
            default="",
            description="פילטר exclude לשגיאות בודדות",
            category="alerts",
        ),
        "ALERT_DISPATCH_LOG_MAX": ConfigDefinition(
            key="ALERT_DISPATCH_LOG_MAX",
            default="500",
            description="גודל לוג שליחת התראות",
            category="alerts",
        ),
        "ALERT_QUICK_FIX_PATH": ConfigDefinition(
            key="ALERT_QUICK_FIX_PATH",
            default="config/alert_quick_fixes.json",
            description="נתיב לקובץ תיקונים מהירים",
            category="alerts",
        ),
        "ALERT_GRAPH_SOURCES_PATH": ConfigDefinition(
            key="ALERT_GRAPH_SOURCES_PATH",
            default="config/alert_graph_sources.json",
            description="נתיב למקורות גרפים להתראות",
            category="alerts",
        ),
        "ALERTS_SILENCES_COLLECTION": ConfigDefinition(
            key="ALERTS_SILENCES_COLLECTION",
            default="alerts_silences",
            description="שם אוסף השתקות התראות ב-DB",
            category="alerts",
        ),
        "INTERNAL_ALERTS_BUFFER": ConfigDefinition(
            key="INTERNAL_ALERTS_BUFFER",
            default="200",
            description="גודל באפר התראות פנימיות",
            category="alerts",
        ),
        "ALERTMANAGER_WEBHOOK_SECRET": ConfigDefinition(
            key="ALERTMANAGER_WEBHOOK_SECRET",
            default="",
            description="סוד Webhook ל-Alertmanager",
            category="alerts",
            sensitive=True,
        ),
        "ALERTMANAGER_IP_ALLOWLIST": ConfigDefinition(
            key="ALERTMANAGER_IP_ALLOWLIST",
            default="",
            description="רשימת IP מותרים ל-Alertmanager",
            category="alerts",
        ),
        "OBSERVABILITY_RUNBOOK_PATH": ConfigDefinition(
            key="OBSERVABILITY_RUNBOOK_PATH",
            default="config/observability_runbooks.yml",
            description="נתיב לקובץ Runbooks",
            category="observability",
        ),
        "OBS_RUNBOOK_STATE_TTL": ConfigDefinition(
            key="OBS_RUNBOOK_STATE_TTL",
            default="14400",
            description="TTL למצב Runbook (שניות)",
            category="observability",
        ),
        "OBS_RUNBOOK_EVENT_TTL": ConfigDefinition(
            key="OBS_RUNBOOK_EVENT_TTL",
            default="900",
            description="TTL לאירועי Runbook (שניות)",
            category="observability",
        ),
        "OBSERVABILITY_WARMUP_RANGES": ConfigDefinition(
            key="OBSERVABILITY_WARMUP_RANGES",
            default="24h,7d,30d",
            description="רשימת טווחי זמן (CSV) לחימום /api/observability/aggregations",
            category="observability",
        ),
        "OBSERVABILITY_WARMUP_AUTOSTART": ConfigDefinition(
            key="OBSERVABILITY_WARMUP_AUTOSTART",
            default="false",
            description="התחלת חימום אוטומטית",
            category="observability",
        ),
        "OBSERVABILITY_WARMUP_ENABLED": ConfigDefinition(
            key="OBSERVABILITY_WARMUP_ENABLED",
            default="true",
            description="הפעלה/כיבוי של Warmup כבד לדוחות Observability ברקע אחרי עליית התהליך",
            category="observability",
        ),
        "OBSERVABILITY_WARMUP_DELAY_SECONDS": ConfigDefinition(
            key="OBSERVABILITY_WARMUP_DELAY_SECONDS",
            default="5",
            description="השהייה (שניות) לפני תחילת Warmup הדוחות כדי לא להעמיס בזמן העלייה",
            category="observability",
        ),
        "OBSERVABILITY_WARMUP_BUDGET_SECONDS": ConfigDefinition(
            key="OBSERVABILITY_WARMUP_BUDGET_SECONDS",
            default="20",
            description="תקציב זמן מקסימלי (שניות) ל-Warmup הדוחות ברקע; מעבר לתקציב נעצור מוקדם",
            category="observability",
        ),
        "OBSERVABILITY_WARMUP_SLOW_LIMIT": ConfigDefinition(
            key="OBSERVABILITY_WARMUP_SLOW_LIMIT",
            default="5",
            description="ערך slow_endpoints_limit עבור החימום (ברירת מחדל כמו ב-API)",
            category="observability",
        ),
        "PREDICTIVE_HORIZON_SECONDS": ConfigDefinition(
            key="PREDICTIVE_HORIZON_SECONDS",
            default="900",
            description="אופק חיזוי (שניות)",
            category="predictive",
        ),
        "MEMORY_USAGE_THRESHOLD_PERCENT": ConfigDefinition(
            key="MEMORY_USAGE_THRESHOLD_PERCENT",
            default="85",
            description="סף אחוז שימוש בזיכרון להתראה",
            category="predictive",
        ),
        "PREDICTIVE_MODEL": ConfigDefinition(
            key="PREDICTIVE_MODEL",
            default="exp_smoothing",
            description="מודל חיזוי (exp_smoothing/linear)",
            category="predictive",
        ),
        "PREDICTIVE_HALFLIFE_MINUTES": ConfigDefinition(
            key="PREDICTIVE_HALFLIFE_MINUTES",
            default="30",
            description="זמן מחצית חיים לחיזוי (דקות)",
            category="predictive",
        ),
        "PREDICTIVE_FEEDBACK_INTERVAL_SEC": ConfigDefinition(
            key="PREDICTIVE_FEEDBACK_INTERVAL_SEC",
            default="300",
            description="מרווח משוב חיזוי (שניות)",
            category="predictive",
        ),
        "PREDICTIVE_CLEANUP_INTERVAL_SEC": ConfigDefinition(
            key="PREDICTIVE_CLEANUP_INTERVAL_SEC",
            default="3600",
            description="מרווח ניקוי חיזויים (שניות)",
            category="predictive",
        ),
        "PREDICTION_MAX_AGE_SECONDS": ConfigDefinition(
            key="PREDICTION_MAX_AGE_SECONDS",
            default="86400",
            description="גיל מקסימלי לחיזוי (שניות)",
            category="predictive",
        ),
        "SAFE_MODE": ConfigDefinition(
            key="SAFE_MODE",
            default="false",
            description="מצב בטוח - משבית פעולות מסוכנות",
            category="predictive",
        ),
        "DISABLE_PREEMPTIVE_ACTIONS": ConfigDefinition(
            key="DISABLE_PREEMPTIVE_ACTIONS",
            default="false",
            description="השבתת פעולות מנע אוטומטיות",
            category="predictive",
        ),
        "RATE_LIMIT_ENABLED": ConfigDefinition(
            key="RATE_LIMIT_ENABLED",
            default="true",
            description="הפעלת הגבלת קצב",
            category="rate_limit",
        ),
        "RATE_LIMIT_SHADOW_MODE": ConfigDefinition(
            key="RATE_LIMIT_SHADOW_MODE",
            default="false",
            description="מצב צל - ספירה בלבד ללא חסימה",
            category="rate_limit",
        ),
        "RATE_LIMIT_STRATEGY": ConfigDefinition(
            key="RATE_LIMIT_STRATEGY",
            default="moving-window",
            description="אסטרטגיית הגבלה (fixed-window/moving-window)",
            category="rate_limit",
        ),
        "RATE_LIMIT_PER_MINUTE": ConfigDefinition(
            key="RATE_LIMIT_PER_MINUTE",
            default="30",
            description="מגבלת בקשות לדקה",
            category="rate_limit",
        ),
        "ENABLE_METRICS": ConfigDefinition(
            key="ENABLE_METRICS",
            default="true",
            description="הפעלת מטריקות Prometheus",
            category="metrics",
        ),
        "METRICS_DB_ENABLED": ConfigDefinition(
            key="METRICS_DB_ENABLED",
            default="false",
            description="שמירת מטריקות ל-DB",
            category="metrics",
        ),
        "METRICS_COLLECTION": ConfigDefinition(
            key="METRICS_COLLECTION",
            default="service_metrics",
            description="שם אוסף מטריקות ב-DB",
            category="metrics",
        ),
        "METRICS_BATCH_SIZE": ConfigDefinition(
            key="METRICS_BATCH_SIZE",
            default="50",
            description="גודל אצווה לשמירת מטריקות",
            category="metrics",
        ),
        "METRICS_FLUSH_INTERVAL_SEC": ConfigDefinition(
            key="METRICS_FLUSH_INTERVAL_SEC",
            default="5",
            description="מרווח שמירת מטריקות (שניות)",
            category="metrics",
        ),
        "METRICS_EWMA_ALPHA": ConfigDefinition(
            key="METRICS_EWMA_ALPHA",
            default="0.2",
            description="מקדם אלפא ל-EWMA",
            category="metrics",
        ),
        "HTTP_SAMPLE_BUFFER": ConfigDefinition(
            key="HTTP_SAMPLE_BUFFER",
            default="2000",
            description="גודל באפר דגימות HTTP",
            category="metrics",
        ),
        "REQUEST_CONTEXT_WINDOW_SECONDS": ConfigDefinition(
            key="REQUEST_CONTEXT_WINDOW_SECONDS",
            default="900",
            description="חלון שמירת קונטקסט בקשות (שניות)",
            category="metrics",
        ),
        "QUEUE_DELAY_WARN_MS": ConfigDefinition(
            key="QUEUE_DELAY_WARN_MS",
            default="500",
            description="סף אזהרת עיכוב תור (מילישניות)",
            category="performance",
        ),
        "SLOW_MS": ConfigDefinition(
            key="SLOW_MS",
            default="0",
            description="סף לוגינג בקשות איטיות (מילישניות)",
            category="performance",
        ),
        "COLLECTIONS_API_ITEMS_SLOW_MS": ConfigDefinition(
            key="COLLECTIONS_API_ITEMS_SLOW_MS",
            default="",
            description="סף איטיות ל-Collections API",
            category="performance",
        ),
        "COLLECTIONS_GET_ITEMS_SLOW_MS": ConfigDefinition(
            key="COLLECTIONS_GET_ITEMS_SLOW_MS",
            default="",
            description="סף איטיות לשליפת פריטי Collections",
            category="performance",
        ),
        "ANOMALY_IGNORE_ENDPOINTS": ConfigDefinition(
            key="ANOMALY_IGNORE_ENDPOINTS",
            default="",
            description="נקודות קצה להתעלמות בזיהוי אנומליות",
            category="performance",
        ),
        "FEATURE_MY_COLLECTIONS": ConfigDefinition(
            key="FEATURE_MY_COLLECTIONS",
            default="true",
            description="הפעלת פיצ'ר My Collections",
            category="features",
        ),
        "COMMUNITY_LIBRARY_ENABLED": ConfigDefinition(
            key="COMMUNITY_LIBRARY_ENABLED",
            default="true",
            description="הפעלת ספריית הקהילה",
            category="features",
        ),
        "DRIVE_MENU_V2": ConfigDefinition(
            key="DRIVE_MENU_V2",
            default="true",
            description="הפעלת תפריט Drive v2",
            category="features",
        ),
        "CHATOPS_ALLOW_ALL_IF_NO_ADMINS": ConfigDefinition(
            key="CHATOPS_ALLOW_ALL_IF_NO_ADMINS",
            default="false",
            description="אפשר ChatOps לכולם כשאין אדמינים",
            category="features",
        ),
        "REFACTOR_LAYERED_MODE": ConfigDefinition(
            key="REFACTOR_LAYERED_MODE",
            default="false",
            description="מצב Refactoring מרובד",
            category="features",
        ),
        "MAX_CODE_SIZE": ConfigDefinition(
            key="MAX_CODE_SIZE",
            default="100000",
            description="גודל קוד מקסימלי (בייטים)",
            category="limits",
        ),
        "MAX_FILES_PER_USER": ConfigDefinition(
            key="MAX_FILES_PER_USER",
            default="1000",
            description="מספר קבצים מקסימלי למשתמש",
            category="limits",
        ),
        "RECYCLE_TTL_DAYS": ConfigDefinition(
            key="RECYCLE_TTL_DAYS",
            default="7",
            description="ימים לשמירת פריטים בסל המיחזור",
            category="limits",
        ),
        "PUBLIC_SHARE_TTL_DAYS": ConfigDefinition(
            key="PUBLIC_SHARE_TTL_DAYS",
            default="7",
            description="ימים לתוקף שיתוף ציבורי",
            category="limits",
        ),
        "PERSISTENT_LOGIN_DAYS": ConfigDefinition(
            key="PERSISTENT_LOGIN_DAYS",
            default="180",
            description="ימים לשמירת התחברות קבועה",
            category="limits",
        ),
        "SEARCH_PAGE_SIZE": ConfigDefinition(
            key="SEARCH_PAGE_SIZE",
            default="200",
            description="גודל עמוד חיפוש",
            category="limits",
        ),
        "UI_PAGE_SIZE": ConfigDefinition(
            key="UI_PAGE_SIZE",
            default="10",
            description="גודל עמוד בממשק משתמש",
            category="limits",
        ),
        "UPTIME_PROVIDER": ConfigDefinition(
            key="UPTIME_PROVIDER",
            default="",
            description="ספק Uptime (betteruptime וכו')",
            category="uptime",
        ),
        "UPTIME_API_KEY": ConfigDefinition(
            key="UPTIME_API_KEY",
            default="",
            description="מפתח API ל-Uptime",
            category="uptime",
            sensitive=True,
        ),
        "UPTIME_MONITOR_ID": ConfigDefinition(
            key="UPTIME_MONITOR_ID",
            default="",
            description="מזהה Monitor ב-Uptime",
            category="uptime",
        ),
        "UPTIME_STATUS_URL": ConfigDefinition(
            key="UPTIME_STATUS_URL",
            default="",
            description="כתובת דף סטטוס Uptime",
            category="uptime",
        ),
        "UPTIME_WIDGET_SCRIPT_URL": ConfigDefinition(
            key="UPTIME_WIDGET_SCRIPT_URL",
            default="https://uptime.betterstack.com/widgets/announcement.js",
            description="כתובת סקריפט Widget",
            category="uptime",
        ),
        "UPTIME_WIDGET_ID": ConfigDefinition(
            key="UPTIME_WIDGET_ID",
            default="",
            description="מזהה Widget ב-Uptime",
            category="uptime",
        ),
        "UPTIME_CACHE_TTL_SECONDS": ConfigDefinition(
            key="UPTIME_CACHE_TTL_SECONDS",
            default="120",
            description="TTL לקאש Uptime (שניות)",
            category="uptime",
        ),
        "ENVIRONMENT": ConfigDefinition(
            key="ENVIRONMENT",
            default="production",
            description="שם הסביבה (production/staging/dev)",
            category="environment",
        ),
        "ENV": ConfigDefinition(
            key="ENV",
            default="production",
            description="שם סביבה מקוצר",
            category="environment",
        ),
        "DEPLOYMENT_TYPE": ConfigDefinition(
            key="DEPLOYMENT_TYPE",
            default="render",
            description="סוג הפריסה (render/heroku/k8s)",
            category="environment",
        ),
        "SERVICE_ID": ConfigDefinition(
            key="SERVICE_ID",
            default="codebot-prod",
            description="מזהה השירות",
            category="environment",
        ),
        "RENDER_INSTANCE_ID": ConfigDefinition(
            key="RENDER_INSTANCE_ID",
            default="local",
            description="מזהה Instance ב-Render",
            category="environment",
        ),
        "HOSTNAME": ConfigDefinition(
            key="HOSTNAME",
            default="",
            description="שם ה-Host הנוכחי",
            category="environment",
        ),
        "APP_VERSION": ConfigDefinition(
            key="APP_VERSION",
            default="",
            description="גרסת האפליקציה",
            category="versioning",
        ),
        "ASSET_VERSION": ConfigDefinition(
            key="ASSET_VERSION",
            default="",
            description="גרסת הנכסים הסטטיים",
            category="versioning",
        ),
        "RENDER_GIT_COMMIT": ConfigDefinition(
            key="RENDER_GIT_COMMIT",
            default="",
            description="Git Commit ב-Render",
            category="versioning",
        ),
        "SOURCE_VERSION": ConfigDefinition(
            key="SOURCE_VERSION",
            default="",
            description="גרסת קוד המקור",
            category="versioning",
        ),
        "GIT_COMMIT": ConfigDefinition(
            key="GIT_COMMIT",
            default="",
            description="Git Commit Hash",
            category="versioning",
        ),
        "HEROKU_SLUG_COMMIT": ConfigDefinition(
            key="HEROKU_SLUG_COMMIT",
            default="",
            description="Git Commit ב-Heroku",
            category="versioning",
        ),
        "FA_SRI_HASH": ConfigDefinition(
            key="FA_SRI_HASH",
            default="",
            description="Hash SRI של FontAwesome",
            category="versioning",
        ),
        "MAINTENANCE_MODE": ConfigDefinition(
            key="MAINTENANCE_MODE",
            default="false",
            description="מצב תחזוקה פעיל",
            category="maintenance",
        ),
        "MAINTENANCE_MESSAGE": ConfigDefinition(
            key="MAINTENANCE_MESSAGE",
            default="🚀 אנחנו מעלים עדכון חדש!\nהבוט יחזור לפעול ממש בקרוב",
            description="הודעת תחזוקה למשתמשים",
            category="maintenance",
        ),
        "MAINTENANCE_AUTO_WARMUP_SECS": ConfigDefinition(
            key="MAINTENANCE_AUTO_WARMUP_SECS",
            default="30",
            description="שניות חימום אחרי תחזוקה",
            category="maintenance",
        ),
        "MAINTENANCE_WARMUP_GRACE_SECS": ConfigDefinition(
            key="MAINTENANCE_WARMUP_GRACE_SECS",
            default="0.75",
            description="שניות גרייס נוספות לחימום",
            category="maintenance",
        ),
        "BACKUPS_STORAGE": ConfigDefinition(
            key="BACKUPS_STORAGE",
            default="mongo",
            description="בחירת מנגנון גיבוי: mongo (GridFS) או fs (מערכת קבצים מקומית)",
            category="backups",
        ),
        "BACKUPS_RETENTION_DAYS": ConfigDefinition(
            key="BACKUPS_RETENTION_DAYS",
            default="30",
            description="ימי שמירת ארכיבי גיבוי בדיסק/GridFS לפני מחיקה (מינימום 1)",
            category="backups",
        ),
        "BACKUPS_CLEANUP_ENABLED": ConfigDefinition(
            key="BACKUPS_CLEANUP_ENABLED",
            default="false",
            description="הפעלת ניקוי גיבויי ZIP ברקע (כבוי כברירת מחדל)",
            category="backups",
        ),
        "BACKUPS_CLEANUP_INTERVAL_SECS": ConfigDefinition(
            key="BACKUPS_CLEANUP_INTERVAL_SECS",
            default="86400",
            description="מרווח בין ריצות ניקוי גיבויים (שניות, מינימום 3600)",
            category="backups",
        ),
        "BACKUPS_CLEANUP_FIRST_SECS": ConfigDefinition(
            key="BACKUPS_CLEANUP_FIRST_SECS",
            default="180",
            description="דיליי לפני ריצת ניקוי גיבויים הראשונה (שניות)",
            category="backups",
        ),
        "BACKUPS_MAX_PER_USER": ConfigDefinition(
            key="BACKUPS_MAX_PER_USER",
            default="",
            description="מספר גיבויים מקסימלי לשמירה לכל משתמש (ריק = ללא מגבלה)",
            category="backups",
        ),
        "BACKUPS_CLEANUP_BUDGET_SECONDS": ConfigDefinition(
            key="BACKUPS_CLEANUP_BUDGET_SECONDS",
            default="3",
            description="תקציב זמן לניקוי גיבויים (מונע עומס)",
            category="backups",
        ),
        "BACKUPS_DISK_MIN_FREE_BYTES": ConfigDefinition(
            key="BACKUPS_DISK_MIN_FREE_BYTES",
            default="209715200",
            description="סף (ב-bytes) להתראת 'דיסק כמעט מלא' לפני שמירת ZIP (200MB)",
            category="backups",
        ),
        "BACKUPS_DIR": ConfigDefinition(
            key="BACKUPS_DIR",
            default="/app/backups",
            description="נתיב גיבויים בלוקאל (אם BACKUPS_STORAGE=fs)",
            category="backups",
        ),
        "BACKUPS_SHOW_ALL_IF_EMPTY": ConfigDefinition(
            key="BACKUPS_SHOW_ALL_IF_EMPTY",
            default="false",
            description="כאשר true מאפשר לממשק להציג את כל הקבצים גם כשאין פילטר",
            category="backups",
        ),
        "TOKEN_ENC_KEY": ConfigDefinition(
            key="TOKEN_ENC_KEY",
            default="",
            description="מפתח הצפנת טוקנים (Base64)",
            category="security",
            sensitive=True,
        ),
        "WEBHOOK_SECRET": ConfigDefinition(
            key="WEBHOOK_SECRET",
            default="",
            description="סוד אימות Webhook",
            category="security",
            sensitive=True,
        ),
        "ENCRYPTION_KEY": ConfigDefinition(
            key="ENCRYPTION_KEY",
            default="",
            description="מפתח הצפנה לנתונים רגישים (32 בתים)",
            category="security",
            sensitive=True,
        ),
        "PYTEST_CURRENT_TEST": ConfigDefinition(
            key="PYTEST_CURRENT_TEST",
            default="",
            description="משתנה pytest - לזיהוי ריצת טסטים",
            category="testing",
        ),
        "PYTEST": ConfigDefinition(
            key="PYTEST",
            default="",
            description="דגל pytest פעיל",
            category="testing",
        ),
        "PYTEST_RUNNING": ConfigDefinition(
            key="PYTEST_RUNNING",
            default="",
            description="סימון ריצת pytest",
            category="testing",
        ),
        "DISABLE_DB": ConfigDefinition(
            key="DISABLE_DB",
            default="",
            description="השבתת DB בטסטים",
            category="testing",
        ),
        "DISABLE_ACTIVITY_REPORTER": ConfigDefinition(
            key="DISABLE_ACTIVITY_REPORTER",
            default="",
            description="השבתת דיווח פעילות",
            category="testing",
        ),
        "RUN_DB_HEALTH_INTEGRATION": ConfigDefinition(
            key="RUN_DB_HEALTH_INTEGRATION",
            default="",
            description="הרצת טסטי אינטגרציה DB Health",
            category="testing",
        ),
        "RUN_PERF": ConfigDefinition(
            key="RUN_PERF",
            default="",
            description="הרצת טסטי ביצועים",
            category="testing",
        ),
        "ALLOW_SEED_NON_LOCAL": ConfigDefinition(
            key="ALLOW_SEED_NON_LOCAL",
            default="",
            description="אפשר seed על DB לא מקומי",
            category="testing",
        ),
        "LOCK_LEASE_SECONDS": ConfigDefinition(
            key="LOCK_LEASE_SECONDS",
            default="60",
            description="משך נעילה מבוזרת (שניות)",
            category="distributed",
        ),
        "LOCK_RETRY_SECONDS": ConfigDefinition(
            key="LOCK_RETRY_SECONDS",
            default="20",
            description="מרווח ניסיון חוזר לנעילה (שניות)",
            category="distributed",
        ),
        "HIGHLIGHT_THEME": ConfigDefinition(
            key="HIGHLIGHT_THEME",
            default="github-dark",
            description="ערכת נושא להדגשת תחביר",
            category="display",
        ),
        "GIT_CHECKPOINT_PREFIX": ConfigDefinition(
            key="GIT_CHECKPOINT_PREFIX",
            default="checkpoint",
            description="תחילית לנקודות בקרה Git",
            category="display",
        ),
        "NORMALIZE_CODE_ON_SAVE": ConfigDefinition(
            key="NORMALIZE_CODE_ON_SAVE",
            default="true",
            description="נרמול תווים נסתרים בשמירה",
            category="display",
        ),
        "DRIVE_ADD_HASH": ConfigDefinition(
            key="DRIVE_ADD_HASH",
            default="false",
            description="הוספת hash לשמות קבצים ב-Drive",
            category="display",
        ),
        "DOCUMENTATION_URL": ConfigDefinition(
            key="DOCUMENTATION_URL",
            default="https://amirbiron.github.io/CodeBot/",
            description="כתובת אתר התיעוד",
            category="display",
        ),
        "BOT_LABEL": ConfigDefinition(
            key="BOT_LABEL",
            default="CodeBot",
            description="תווית הבוט בממשק",
            category="display",
        ),
    }

    def __init__(self) -> None:
        """אתחול השירות."""

        self._sensitive_regex = self._compile_sensitive_pattern()

    def _compile_sensitive_pattern(self) -> re.Pattern:
        """יצירת Regex לזיהוי משתנים רגישים."""

        patterns = "|".join(re.escape(p) for p in self.SENSITIVE_PATTERNS)
        return re.compile(patterns, re.IGNORECASE)

    def is_sensitive_key(self, key: str) -> bool:
        """
        בדיקה האם מפתח מכיל מידע רגיש.

        Args:
            key: שם המפתח לבדיקה

        Returns:
            True אם המפתח רגיש
        """

        # בדיקת ההגדרה הראשית
        definition = self.CONFIG_DEFINITIONS.get(key)
        if definition and definition.sensitive:
            return True

        # בדיקה לפי תבניות
        return bool(self._sensitive_regex.search(key))

    def mask_value(self, value: str, key: str) -> str:
        """
        הסתרת ערך רגיש.

        Args:
            value: הערך להסתרה
            key: שם המפתח (לבדיקת רגישות)

        Returns:
            ערך מוסתר או המקורי
        """

        if not value:
            return value

        if self.is_sensitive_key(key):
            return self.MASKED_VALUE

        return value

    def get_env_value(self, key: str, default: Any = None) -> Optional[str]:
        """
        שליפת ערך ממשתנה סביבה.

        Args:
            key: שם המשתנה
            default: ערך ברירת מחדל

        Returns:
            הערך מהסביבה או ברירת המחדל
        """

        return os.getenv(key, default)

    def _is_empty_value(self, value: Optional[str]) -> bool:
        """
        בדיקה האם ערך נחשב ריק.
        None או מחרוזת ריקה/רווחים בלבד = ריק.

        Args:
            value: הערך לבדיקה

        Returns:
            True אם הערך ריק
        """

        return value is None or not str(value).strip()

    def determine_status(
        self,
        env_value: Optional[str],
        default_value: Any,
        is_required: bool = False,
    ) -> ConfigStatus:
        """
        קביעת סטטוס הקונפיגורציה.

        Args:
            env_value: ערך מהסביבה
            default_value: ערך ברירת המחדל
            is_required: האם המשתנה הכרחי

        Returns:
            סטטוס המשתנה
        """

        env_is_empty = self._is_empty_value(env_value)
        default_is_empty = self._is_empty_value(str(default_value) if default_value is not None else None)

        # אם אין ערך בסביבה (None או מחרוזת ריקה)
        if env_is_empty:
            # אם גם אין דיפולט והמשתנה הכרחי - Missing
            if default_is_empty and is_required:
                return ConfigStatus.MISSING
            # אם יש דיפולט - משתמשים בו
            if not default_is_empty:
                return ConfigStatus.DEFAULT
            # אין דיפולט אבל לא הכרחי - נחשב Default (ריק)
            return ConfigStatus.DEFAULT

        # יש ערך בסביבה - השוואה לדיפולט
        default_str = str(default_value) if default_value is not None else ""
        if env_value == default_str:
            return ConfigStatus.DEFAULT

        return ConfigStatus.MODIFIED

    def determine_source(self, env_value: Optional[str]) -> ConfigSource:
        """
        קביעת מקור הערך.

        Args:
            env_value: ערך מהסביבה

        Returns:
            מקור הערך
        """

        if env_value is not None:
            return ConfigSource.ENVIRONMENT
        return ConfigSource.DEFAULT

    def get_config_entry(self, definition: ConfigDefinition) -> ConfigEntry:
        """
        יצירת רשומת קונפיגורציה יחידה.

        Args:
            definition: הגדרת המשתנה

        Returns:
            רשומת הקונפיגורציה
        """

        key = definition.key
        default = definition.default

        # שליפת הערך מהסביבה
        env_value = self.get_env_value(key)

        # קביעת מקור וסטטוס
        source = self.determine_source(env_value)
        status = self.determine_status(env_value, default, definition.required)

        # הערך הפעיל (מהסביבה או דיפולט)
        # חשוב: לא להשתמש ב-`default or ""` כי זה שובר דיפולטים "Falsy" (0/False)
        active_value = env_value if env_value is not None else (str(default) if default is not None else "")

        # הסתרת ערכים רגישים - גם active וגם default!
        is_sensitive = self.is_sensitive_key(key) or definition.sensitive
        display_value = self.mask_value(active_value, key) if is_sensitive else active_value

        # הסתרת ערך ברירת מחדל אם רגיש (למניעת חשיפת credentials בדיפולטים)
        default_str = str(default) if default is not None else ""
        display_default = self.mask_value(default_str, key) if is_sensitive else default_str

        return ConfigEntry(
            key=key,
            active_value=display_value,
            default_value=display_default,
            source=source,
            status=status,
            description=definition.description,
            category=definition.category,
            is_sensitive=is_sensitive,
        )

    def get_config_overview(
        self,
        category_filter: Optional[str] = None,
        status_filter: Optional[ConfigStatus] = None,
    ) -> ConfigOverview:
        """
        קבלת סקירת קונפיגורציה מלאה.

        Args:
            category_filter: סינון לפי קטגוריה
            status_filter: סינון לפי סטטוס

        Returns:
            סקירה מלאה של כל הקונפיגורציות
        """

        entries: List[ConfigEntry] = []
        categories_set: set[str] = set()

        for definition in self.CONFIG_DEFINITIONS.values():
            entry = self.get_config_entry(definition)
            categories_set.add(entry.category)

            # סינון
            if category_filter and entry.category != category_filter:
                continue
            if status_filter and entry.status != status_filter:
                continue

            entries.append(entry)

        # מיון לפי קטגוריה ואז לפי שם
        entries.sort(key=lambda e: (e.category, e.key))

        # חישוב סטטיסטיקות
        modified_count = sum(1 for e in entries if e.status == ConfigStatus.MODIFIED)
        missing_count = sum(1 for e in entries if e.status == ConfigStatus.MISSING)
        default_count = sum(1 for e in entries if e.status == ConfigStatus.DEFAULT)

        return ConfigOverview(
            entries=entries,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            total_count=len(entries),
            modified_count=modified_count,
            missing_count=missing_count,
            default_count=default_count,
            categories=sorted(categories_set),
        )

    def get_category_summary(self) -> Dict[str, Dict[str, int]]:
        """
        קבלת סיכום לפי קטגוריות.

        Returns:
            מילון עם ספירה לכל קטגוריה
        """

        overview = self.get_config_overview()
        summary: Dict[str, Dict[str, int]] = {}

        for entry in overview.entries:
            cat = entry.category
            if cat not in summary:
                summary[cat] = {"total": 0, "modified": 0, "missing": 0, "default": 0}

            summary[cat]["total"] += 1
            if entry.status == ConfigStatus.MODIFIED:
                summary[cat]["modified"] += 1
            elif entry.status == ConfigStatus.MISSING:
                summary[cat]["missing"] += 1
            else:
                summary[cat]["default"] += 1

        return summary

    def validate_required(self) -> List[str]:
        """
        בדיקת משתנים הכרחיים חסרים.

        Returns:
            רשימת שמות משתנים חסרים
        """

        missing = []
        for definition in self.CONFIG_DEFINITIONS.values():
            if not definition.required:
                continue

            env_value = self.get_env_value(definition.key)
            default_str = str(definition.default) if definition.default is not None else None

            # שימוש באותה לוגיקה כמו determine_status
            env_is_empty = self._is_empty_value(env_value)
            default_is_empty = self._is_empty_value(default_str)

            # חסר = אין ערך בסביבה וגם אין דיפולט תקף
            if env_is_empty and default_is_empty:
                missing.append(definition.key)

        return missing


# Singleton instance
_config_service: Optional[ConfigService] = None


def get_config_service() -> ConfigService:
    """קבלת instance יחיד של השירות."""

    global _config_service
    if _config_service is None:
        _config_service = ConfigService()
    return _config_service

