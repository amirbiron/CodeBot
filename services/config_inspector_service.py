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
    # NOTE: מסונן לפי docs/environment-variables.rst (עמודת "רכיב" כוללת WebApp)
    CONFIG_DEFINITIONS: Dict[str, ConfigDefinition] = {
        "MONGODB_URL": ConfigDefinition(
            key="MONGODB_URL",
            default="",
            description="כתובת חיבור ל-MongoDB (חובה)",
            category="database",
            sensitive=True,
            required=True,
        ),
        "DATABASE_NAME": ConfigDefinition(
            key="DATABASE_NAME",
            default="code_keeper_bot",
            description="שם מסד הנתונים ב-MongoDB",
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
        "BOT_USERNAME": ConfigDefinition(
            key="BOT_USERNAME",
            default="my_code_keeper_bot",
            description="שם המשתמש של הבוט בטלגרם",
            category="telegram",
        ),
        "ADMIN_USER_IDS": ConfigDefinition(
            key="ADMIN_USER_IDS",
            default="",
            description="רשימת מזהי אדמינים (מופרדים בפסיקים)",
            category="telegram",
            sensitive=True,
        ),
        "PREMIUM_USER_IDS": ConfigDefinition(
            key="PREMIUM_USER_IDS",
            default="",
            description="רשימת מזהי משתמשי פרימיום",
            category="telegram",
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
        "ALERT_STARTUP_GRACE_PERIOD_SECONDS": ConfigDefinition(
            key="ALERT_STARTUP_GRACE_PERIOD_SECONDS",
            default="1200",
            description="חלון חסד (שניות) לאחר אתחול שבו מושתקים רק alerts רועשים מתוך allowlist (Mongo/Latency/EWMA)",
            category="alerts",
        ),
        "ALERTS_TEXT_INCLUDE_DASHBOARD_LINK_TELEGRAM": ConfigDefinition(
            key="ALERTS_TEXT_INCLUDE_DASHBOARD_LINK_TELEGRAM",
            default="false",
            description="אם true מוסיף שורת 📊 Dashboard לגוף ההודעה בטלגרם (ברירת מחדל כבוי כי יש כפתור Inline)",
            category="alerts",
        ),
        "ALERTS_TEXT_INCLUDE_DASHBOARD_LINK_SLACK": ConfigDefinition(
            key="ALERTS_TEXT_INCLUDE_DASHBOARD_LINK_SLACK",
            default="true",
            description="אם true מוסיף שורת 📊 Dashboard לגוף ההודעה ב-Slack (ברירת מחדל פעיל)",
            category="alerts",
        ),
        "REDIS_MAX_CONNECTIONS": ConfigDefinition(
            key="REDIS_MAX_CONNECTIONS",
            default="50",
            description="מספר חיבורים מקסימלי ל-Redis",
            category="cache",
        ),
        "REDIS_CONNECT_TIMEOUT": ConfigDefinition(
            key="REDIS_CONNECT_TIMEOUT",
            default="3",
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
            default="5",
            description="תקציב זמן לניקוי קאש (שניות)",
            category="cache",
        ),
        "CACHE_DELETE_PATTERN_BUDGET_SECONDS": ConfigDefinition(
            key="CACHE_DELETE_PATTERN_BUDGET_SECONDS",
            default="5",
            description="תקציב זמן למחיקת תבנית מפתחות בקאש (שניות) – SCAN+DEL, למניעת תקיעה ב-Redis גדול",
            category="cache",
        ),
        "DISABLE_CACHE_MAINTENANCE": ConfigDefinition(
            key="DISABLE_CACHE_MAINTENANCE",
            default="false",
            description="השבתת תחזוקת קאש אוטומטית",
            category="cache",
        ),
        "PORT": ConfigDefinition(
            key="PORT",
            default="5000",
            description="פורט השרת (Render/Heroku)",
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
        "PUBLIC_URL": ConfigDefinition(
            key="PUBLIC_URL",
            default="https://code-keeper-webapp.onrender.com",
            description="כתובת בסיס ציבורית של ה-WebApp (משמשת ליצירת קישור ציבורי ל-Observability Dashboard בהתראות)",
            category="webserver",
        ),
        "WEBAPP_URL": ConfigDefinition(
            key="WEBAPP_URL",
            default="",
            description="כתובת WebApp (אם שונה מ-public)",
            category="webserver",
        ),
        "BOT_JOBS_API_BASE_URL": ConfigDefinition(
            key="BOT_JOBS_API_BASE_URL",
            default="",
            description="בסיס URL ל-API הפנימי של הבוט עבור Trigger של Jobs ממסך המוניטור (WebApp -> Bot).",
            category="jobs_monitor",
        ),
        "BOT_API_BASE_URL": ConfigDefinition(
            key="BOT_API_BASE_URL",
            default="",
            description="Alias/תאימות לאחור ל-BOT_JOBS_API_BASE_URL (נבדק רק אם BOT_JOBS_API_BASE_URL ריק).",
            category="jobs_monitor",
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
        "PASTEBIN_API_KEY": ConfigDefinition(
            key="PASTEBIN_API_KEY",
            default="",
            description="מפתח API ל-Pastebin",
            category="external",
            sensitive=True,
        ),
        "SENTRY_DSN": ConfigDefinition(
            key="SENTRY_DSN",
            default="",
            description="DSN ל-Sentry לניטור שגיאות",
            category="monitoring",
            sensitive=True,
        ),
        "SENTRY_DASHBOARD_URL": ConfigDefinition(
            key="SENTRY_DASHBOARD_URL",
            default="",
            description="כתובת לוח הבקרה של Sentry",
            category="monitoring",
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
        "LOG_LEVEL": ConfigDefinition(
            key="LOG_LEVEL",
            default="INFO",
            description="רמת הלוגים (DEBUG/INFO/WARNING/ERROR/CRITICAL או ערך מספרי כמו 10/20/30)",
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
        "ALERT_QUICK_FIX_PATH": ConfigDefinition(
            key="ALERT_QUICK_FIX_PATH",
            default="config/alert_quick_fixes.json",
            description="נתיב לקובץ תיקונים מהירים",
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
        "ALLOWED_WEBHOOK_HOSTS": ConfigDefinition(
            key="ALLOWED_WEBHOOK_HOSTS",
            default="",
            description="Allowlist אופציונלי ליעדי webhook (Visual Rule Engine) לפי hostnames (CSV)",
            category="alerts",
        ),
        "ALLOWED_WEBHOOK_SUFFIXES": ConfigDefinition(
            key="ALLOWED_WEBHOOK_SUFFIXES",
            default="",
            description="Allowlist אופציונלי ליעדי webhook (Visual Rule Engine) לפי סיומות דומיין (CSV, למשל .example.com)",
            category="alerts",
        ),
        "OBSERVABILITY_RUNBOOK_PATH": ConfigDefinition(
            key="OBSERVABILITY_RUNBOOK_PATH",
            default="config/observability_runbooks.yml",
            description="נתיב לקובץ Runbooks",
            category="observability",
        ),
        "ALERT_TAGS_COLLECTION": ConfigDefinition(
            key="ALERT_TAGS_COLLECTION",
            default="alert_tags",
            description="שם ה-Collection לתגיות התראות (Manual Alert Tagging) ב-Observability",
            category="observability",
        ),
        "ALERT_TAGS_DB_DISABLED": ConfigDefinition(
            key="ALERT_TAGS_DB_DISABLED",
            default="false",
            description="אם true מכבה שמירה/שליפה של תגיות להתראות (Manual Alert Tagging) מה-DB",
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
        "RATE_LIMIT_SHADOW_MODE": ConfigDefinition(
            key="RATE_LIMIT_SHADOW_MODE",
            default="false",
            description="מצב צל - ספירה בלבד ללא חסימה",
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
        "HTTP_SAMPLE_BUFFER": ConfigDefinition(
            key="HTTP_SAMPLE_BUFFER",
            default="2000",
            description="גודל באפר דגימות HTTP",
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
        "ANOMALY_IGNORE_ENDPOINTS": ConfigDefinition(
            key="ANOMALY_IGNORE_ENDPOINTS",
            default="",
            description="נקודות קצה להתעלמות בזיהוי אנומליות",
            category="performance",
        ),
        "DRIVE_MENU_V2": ConfigDefinition(
            key="DRIVE_MENU_V2",
            default="true",
            description="הפעלת תפריט Drive v2",
            category="features",
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
        "GIT_COMMIT": ConfigDefinition(
            key="GIT_COMMIT",
            default="",
            description="Git Commit Hash",
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
        "BACKUPS_DIR": ConfigDefinition(
            key="BACKUPS_DIR",
            default="/app/backups",
            description="נתיב גיבויים בלוקאל (אם BACKUPS_STORAGE=fs)",
            category="backups",
        ),
        "ENCRYPTION_KEY": ConfigDefinition(
            key="ENCRYPTION_KEY",
            default="",
            description="מפתח הצפנה לנתונים רגישים (32 בתים)",
            category="security",
            sensitive=True,
        ),
        "PYTEST": ConfigDefinition(
            key="PYTEST",
            default="",
            description="דגל pytest פעיל",
            category="testing",
        ),
        "DISABLE_DB": ConfigDefinition(
            key="DISABLE_DB",
            default="",
            description="השבתת DB בטסטים",
            category="testing",
        ),
        "HIGHLIGHT_THEME": ConfigDefinition(
            key="HIGHLIGHT_THEME",
            default="github-dark",
            description="ערכת נושא להדגשת תחביר",
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
        "ALERT_EXTERNAL_SERVICES": ConfigDefinition(
            key="ALERT_EXTERNAL_SERVICES",
            default="uptime,uptimerobot,uptime_robot,betteruptime,statuscake,pingdom,external_monitor,github api,github_api",
            description="רשימת מחרוזות (CSV) של שירותים חיצוניים שיזוהו כ-``external`` במדד High Error Rate (למשל ``uptimerobot``/``github api``); שגיאות מהמקורות האלה ייצרו רק התרעת Warning ולא יריצו Auto-Remediation.",
            category="alerts",
        ),
        "DB_HEALTH_OPS_REFRESH_SEC": ConfigDefinition(
            key="DB_HEALTH_OPS_REFRESH_SEC",
            default="10",
            description="תדירות רענון מומלצת (שניות) לרשימת slow queries בדשבורד. (משתנה תיעודי/קונפיגורציה כללית)",
            category="database",
        ),
        "DB_HEALTH_POOL_REFRESH_SEC": ConfigDefinition(
            key="DB_HEALTH_POOL_REFRESH_SEC",
            default="5",
            description="תדירות רענון מומלצת (שניות) לסטטוס ה-pool בדשבורד. (משתנה תיעודי/קונפיגורציה כללית)",
            category="database",
        ),
        "DB_SLOW_MS": ConfigDefinition(
            key="DB_SLOW_MS",
            default="0",
            description="סף מילישניות ללוג \"slow_mongo\" (MongoDB CommandListener)",
            category="database",
        ),
        # --- Query Performance Profiler ---
        "PROFILER_ENABLED": ConfigDefinition(
            key="PROFILER_ENABLED",
            default="true",
            description="הפעלת Query Performance Profiler (true/false)",
            category="profiler",
        ),
        "PROFILER_SLOW_THRESHOLD_MS": ConfigDefinition(
            key="PROFILER_SLOW_THRESHOLD_MS",
            default="100",
            description="סף זמן לשאילתה איטית בפרופיילר (מילישניות)",
            category="profiler",
        ),
        "PROFILER_MAX_BUFFER_SIZE": ConfigDefinition(
            key="PROFILER_MAX_BUFFER_SIZE",
            default="1000",
            description="מספר מקסימלי של רשומות slow queries שנשמרות בזיכרון",
            category="profiler",
        ),
        "PROFILER_AUTH_TOKEN": ConfigDefinition(
            key="PROFILER_AUTH_TOKEN",
            default="",
            description="טוקן גישה ל-API של הפרופיילר (X-Profiler-Token)",
            category="profiler",
            sensitive=True,
        ),
        "PROFILER_ALLOWED_IPS": ConfigDefinition(
            key="PROFILER_ALLOWED_IPS",
            default="",
            description="Allowlist של כתובות IP מורשות ל-API של הפרופיילר (CSV)",
            category="profiler",
        ),
        "PROFILER_RATE_LIMIT": ConfigDefinition(
            key="PROFILER_RATE_LIMIT",
            default="60",
            description="מגבלת בקשות לדקה ל-endpoints של הפרופיילר (Rate Limiting)",
            category="profiler",
        ),
        "PROFILER_METRICS_ENABLED": ConfigDefinition(
            key="PROFILER_METRICS_ENABLED",
            default="true",
            description="הפעלת מטריקות Prometheus לפרופיילר",
            category="profiler",
        ),
        "DRILLS_COLLECTION": ConfigDefinition(
            key="DRILLS_COLLECTION",
            default="drill_history",
            description="שם הקולקשן שבו נשמרת היסטוריית Drill Mode (תרגולים).",
            category="drills",
        ),
        "DRILLS_DB_ENABLED": ConfigDefinition(
            key="DRILLS_DB_ENABLED",
            default="",
            description="מפעיל שמירת היסטוריית Drill ב-MongoDB (ברירת מחדל נסמכת על ``ALERTS_DB_ENABLED``/``METRICS_DB_ENABLED``).",
            category="drills",
        ),
        "DRILLS_TTL_DAYS": ConfigDefinition(
            key="DRILLS_TTL_DAYS",
            default="90",
            description="כמה ימים נשמרת היסטוריית Drill לפני מחיקה אוטומטית (TTL index).",
            category="drills",
        ),
        "DRILL_MODE_ENABLED": ConfigDefinition(
            key="DRILL_MODE_ENABLED",
            default="false",
            description="מפעיל Drill Mode (תרגולים) ב-WebApp/API. כאשר כבוי, ``/api/observability/drills/run`` יחזיר ``drill_disabled``.",
            category="drills",
        ),
        "DUMMY_BOT_TOKEN": ConfigDefinition(
            key="DUMMY_BOT_TOKEN",
            default="dummy_token",
            description="טוקן בדיקה שמשמש סביבות שבהן אין צורך להתחבר לטלגרם (למשל docs build).",
            category="general",
            sensitive=True,
        ),
        "ENABLE_INTERNAL_SHARE_WEB": ConfigDefinition(
            key="ENABLE_INTERNAL_SHARE_WEB",
            default="false",
            description="הפעלת שירות שיתוף פנימי",
            category="features",
        ),
        "HTTP_SAMPLE_RETENTION_SECONDS": ConfigDefinition(
            key="HTTP_SAMPLE_RETENTION_SECONDS",
            default="600",
            description="זמן שמירת הדגימות (שניות) לפני שמנקים אותן.",
            category="http",
        ),
        "HTTP_SLOW_MS": ConfigDefinition(
            key="HTTP_SLOW_MS",
            default="0",
            description="סף מילישניות ללוג \"slow_http\" ב‑http_sync (requests)",
            category="http",
        ),
        "OBS_AI_EXPLAIN_TOKEN": ConfigDefinition(
            key="OBS_AI_EXPLAIN_TOKEN",
            default="",
            description="אסימון Bearer שנשלח ב-Header ``Authorization`` כאשר השירות מוגן (אופציונלי).",
            category="observability",
            sensitive=True,
        ),
        "OBS_AI_EXPLAIN_URL": ConfigDefinition(
            key="OBS_AI_EXPLAIN_URL",
            default="",
            description="Endpoint לשירות ההסבר החכם של הדשבורד (מקבל ``POST`` עם ``context`` ומחזיר ``root_cause``/``actions``/``signals``).",
            category="observability",
            sensitive=True,
        ),
        "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": ConfigDefinition(
            key="OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
            default="",
            description="כתובת ייעודית למטריקות OTLP (אם שונה מה-endpoint הראשי).",
            category="monitoring",
        ),
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": ConfigDefinition(
            key="OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
            default="",
            description="כתובת ייעודית ל-traces OTLP.",
            category="monitoring",
        ),
        "JOBS_STUCK_THRESHOLD_MINUTES": ConfigDefinition(
            key="JOBS_STUCK_THRESHOLD_MINUTES",
            default="20",
            description="סף (בדקות) לזיהוי הרצות Jobs תקועות והפקת אירוע job_stuck.",
            category="jobs_monitor",
        ),
        "JOBS_STUCK_MONITOR_INTERVAL_SECS": ConfigDefinition(
            key="JOBS_STUCK_MONITOR_INTERVAL_SECS",
            default="60",
            description="תדירות (שניות) של מוניטור Jobs תקועות (job_stuck).",
            category="jobs_monitor",
        ),
        "PUSH_WORKER_PORT": ConfigDefinition(
            key="PUSH_WORKER_PORT",
            default="18080",
            description="פורט פנימי ל‑Sidecar Worker (localhost בלבד)",
            category="push",
        ),
        "WEEKLY_TIP_ENABLED": ConfigDefinition(
            key="WEEKLY_TIP_ENABLED",
            default="true",
            description="מתג כללי להצגת רכיב ההכרזות (on/off)",
            category="features",
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

