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

# כתובת URL עם credentials מוטמעים: scheme://user:pass@host — סוד גם אם שם המשתנה אינו רגיש
_CREDENTIAL_URL_RE = re.compile(r"://[^/\s:@]+:[^/\s:@]+@")


class ConfigStatus(str, Enum):
    """סטטוס של משתנה קונפיגורציה."""

    DEFAULT = "Default"  # משתמש בערך ברירת המחדל
    MODIFIED = "Modified"  # ערך שונה מברירת מחדל שקיימת בקוד
    SET = "Set"  # הוגדר בסביבה (למשל ברנדר) כשאין ברירת מחדל בקוד — לא "שונה"
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
    # לאילו שירותי Render המשתנה שייך (משתנה יכול להיות מוגדר בכמה שירותים במקביל).
    # "webapp" ⇒ מוצג בעמוד הראשי עם Status/Active Value (ה-inspector רץ בתהליך ה-webapp).
    # כל שירות אחר ("bot"/"mcp"/"webserver"/"scripts") ⇒ השורה מופיעה גם בעמוד
    # "שירותים אחרים" עם ציון השירותים — בלי Status/Active Value, כי הערכים שם חיים
    # בתהליכים נפרדים. הערה: ה-webserver הוא שירות Render נפרד (לא חלק מתהליך הבוט).
    services: tuple[str, ...] = ("webapp",)


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
    set_count: int = 0
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
    # הערה: "URL" הוסר בכוונה — כתובת ציבורית (MCP_SERVER_URL, WEBAPP_URL, PROMETHEUS_URL...)
    # אינה סוד ומיסוכה מטעה. URL שמכיל credentials (כמו MONGODB_URL) מסומן sensitive=True
    # מפורשות בהגדרתו. "URI" נשאר כי URI-חיבור בדרך כלל מגלם סיסמה.
    SENSITIVE_PATTERNS: tuple[str, ...] = (
        "TOKEN",
        "KEY",
        "PASSWORD",
        "SECRET",
        "URI",
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
            services=("webapp", "bot", "mcp", "webserver"),
            default="",
            description="כתובת חיבור ל-MongoDB (חובה)",
            category="database",
            sensitive=True,
            required=True,
        ),
        "DATABASE_NAME": ConfigDefinition(
            key="DATABASE_NAME",
            services=("webapp", "bot", "mcp", "webserver"),
            default="code_keeper_bot",
            description="שם מסד הנתונים ב-MongoDB",
            category="database",
        ),
        "MONGODB_MAX_POOL_SIZE": ConfigDefinition(
            key="MONGODB_MAX_POOL_SIZE",
            services=("webapp", "bot", "mcp", "webserver"),
            default="50",
            description="מספר חיבורים מקסימלי לפול MongoDB",
            category="database",
        ),
        "MONGODB_MIN_POOL_SIZE": ConfigDefinition(
            key="MONGODB_MIN_POOL_SIZE",
            services=("webapp", "bot", "mcp", "webserver"),
            default="5",
            description="מספר חיבורים מינימלי לפול MongoDB",
            category="database",
        ),
        "MONGODB_MAX_IDLE_TIME_MS": ConfigDefinition(
            key="MONGODB_MAX_IDLE_TIME_MS",
            services=("webapp", "bot", "mcp", "webserver"),
            default="30000",
            description="זמן סרק מקסימלי לחיבור MongoDB (מילישניות)",
            category="database",
        ),
        "MONGODB_WAIT_QUEUE_TIMEOUT_MS": ConfigDefinition(
            key="MONGODB_WAIT_QUEUE_TIMEOUT_MS",
            services=("webapp", "bot", "mcp", "webserver"),
            default="8000",
            description="זמן המתנה בתור לחיבור MongoDB (מילישניות)",
            category="database",
        ),
        "MONGODB_SERVER_SELECTION_TIMEOUT_MS": ConfigDefinition(
            key="MONGODB_SERVER_SELECTION_TIMEOUT_MS",
            services=("webapp", "bot", "mcp", "webserver"),
            default="5000",
            description="זמן בחירת שרת MongoDB (מילישניות)",
            category="database",
        ),
        "MONGODB_SOCKET_TIMEOUT_MS": ConfigDefinition(
            key="MONGODB_SOCKET_TIMEOUT_MS",
            services=("webapp", "bot", "mcp", "webserver"),
            default="45000",
            description="טיימאאוט סוקט MongoDB (מילישניות)",
            category="database",
        ),
        "MONGODB_CONNECT_TIMEOUT_MS": ConfigDefinition(
            key="MONGODB_CONNECT_TIMEOUT_MS",
            services=("webapp", "bot", "mcp", "webserver"),
            default="5000",
            description="טיימאאוט התחברות ל-MongoDB (מילישניות)",
            category="database",
        ),
        "MONGODB_RETRY_WRITES": ConfigDefinition(
            key="MONGODB_RETRY_WRITES",
            services=("webapp", "bot", "mcp", "webserver"),
            default="true",
            description="הפעלת ניסיונות כתיבה חוזרים ב-MongoDB",
            category="database",
        ),
        "MONGODB_RETRY_READS": ConfigDefinition(
            key="MONGODB_RETRY_READS",
            services=("webapp", "bot", "mcp", "webserver"),
            default="true",
            description="הפעלת ניסיונות קריאה חוזרים ב-MongoDB",
            category="database",
        ),
        "MONGODB_APPNAME": ConfigDefinition(
            key="MONGODB_APPNAME",
            services=("webapp", "bot", "mcp", "webserver"),
            default="",
            description="שם האפליקציה למטא-דאטה MongoDB",
            category="database",
        ),
        "MONGODB_COMPRESSORS": ConfigDefinition(
            key="MONGODB_COMPRESSORS",
            services=("webapp", "bot", "mcp", "webserver"),
            default="",
            description="דחיסנים נתמכים (zstd,snappy,zlib)",
            category="database",
        ),
        "DB_HEALTH_TOKEN": ConfigDefinition(
            key="DB_HEALTH_TOKEN",
            services=("webapp", "bot", "webserver"),
            default="",
            description="טוקן אימות לבדיקות בריאות DB",
            category="database",
            sensitive=True,
        ),
        "DB_RECONNECT_WAIT_BEFORE_POLL": ConfigDefinition(
            key="DB_RECONNECT_WAIT_BEFORE_POLL",
            services=("bot",),
            default="120",
            description="זמן המתנה ראשוני (שניות) להתחברות מחדש ל-DB בעלייה לפני מעבר ל-poll פסיבי",
            category="database",
        ),
        "DB_RECONNECT_POLL_INTERVAL": ConfigDefinition(
            key="DB_RECONNECT_POLL_INTERVAL",
            services=("bot",),
            default="30",
            description="מרווח (שניות) בין בדיקות חיבור ב-poll פסיבי לאחר שחלון ההמתנה הראשוני פג",
            category="database",
        ),
        "DB_HEALTH_SLOW_THRESHOLD_MS": ConfigDefinition(
            key="DB_HEALTH_SLOW_THRESHOLD_MS",
            services=("webapp", "bot", "webserver"),
            default="1000",
            description="סף לזיהוי שאילתות איטיות (מילישניות)",
            category="database",
        ),
        "DB_HEALTH_COLLECTIONS_COOLDOWN_SEC": ConfigDefinition(
            key="DB_HEALTH_COLLECTIONS_COOLDOWN_SEC",
            services=("webapp", "bot"),
            default="30",
            description="זמן קירור בין בדיקות בריאות (שניות)",
            category="database",
        ),
        "BOT_TOKEN": ConfigDefinition(
            key="BOT_TOKEN",
            services=("webapp", "bot"),
            default="",
            description="טוקן הבוט מ-BotFather. נדרש גם בשירות ה-webapp (אימות Telegram Login ב-auth_routes).",
            category="telegram",
            sensitive=True,
            required=True,
        ),
        "BOT_USERNAME": ConfigDefinition(
            key="BOT_USERNAME",
            services=("webapp", "bot"),
            default="my_code_keeper_bot",
            description="שם המשתמש של הבוט בטלגרם",
            category="telegram",
        ),
        # --- Telegram Polling / Network timeouts (stability against getUpdates conflicts) ---
        "TELEGRAM_CONNECT_TIMEOUT_SECS": ConfigDefinition(
            key="TELEGRAM_CONNECT_TIMEOUT_SECS",
            services=("bot",),
            default="10.0",
            description="טיימאאוט התחברות ל-Telegram Bot API (שניות).",
            category="telegram",
        ),
        "TELEGRAM_POOL_TIMEOUT_SECS": ConfigDefinition(
            key="TELEGRAM_POOL_TIMEOUT_SECS",
            services=("bot",),
            default="10.0",
            description="טיימאאוט המתנה ל-connection מה-pool (שניות) בעת קריאה ל-Telegram Bot API.",
            category="telegram",
        ),
        "TELEGRAM_READ_TIMEOUT_SECS": ConfigDefinition(
            key="TELEGRAM_READ_TIMEOUT_SECS",
            services=("bot",),
            default="30.0",
            description="טיימאאוט קריאה ל-Telegram Bot API (שניות). מומלץ להיות גבוה מ-TELEGRAM_LONG_POLL_TIMEOUT_SECS.",
            category="telegram",
        ),
        "TELEGRAM_WRITE_TIMEOUT_SECS": ConfigDefinition(
            key="TELEGRAM_WRITE_TIMEOUT_SECS",
            services=("bot",),
            default="30.0",
            description="טיימאאוט כתיבה ל-Telegram Bot API (שניות).",
            category="telegram",
        ),
        "TELEGRAM_LONG_POLL_TIMEOUT_SECS": ConfigDefinition(
            key="TELEGRAM_LONG_POLL_TIMEOUT_SECS",
            services=("bot",),
            default="20",
            description="timeout של long-polling עבור getUpdates (שניות).",
            category="telegram",
        ),
        "TELEGRAM_POLL_INTERVAL_SECS": ConfigDefinition(
            key="TELEGRAM_POLL_INTERVAL_SECS",
            services=("bot",),
            default="0.0",
            description="poll_interval בין סבבי polling (שניות). 0 = ברירת מחדל של PTB.",
            category="telegram",
        ),
        "TELEGRAM_CONFLICT_BACKOFF_SECS": ConfigDefinition(
            key="TELEGRAM_CONFLICT_BACKOFF_SECS",
            services=("bot",),
            default="30",
            description="זמן המתנה (שניות) לפני retry כאשר מתקבלת שגיאת 409 Conflict ב-getUpdates.",
            category="telegram",
        ),
        "TELEGRAM_CONFLICT_MAX_RETRIES": ConfigDefinition(
            key="TELEGRAM_CONFLICT_MAX_RETRIES",
            services=("bot",),
            default="5",
            description="כמה פעמים לנסות שוב (retry) אחרי 409 Conflict ב-getUpdates לפני יציאה מהתהליך כדי לשחרר lock ולאפשר recovery. 0/שלילי = ללא הגבלה (לא מומלץ).",
            category="telegram",
        ),
        "TELEGRAM_CONFLICT_MAX_SECONDS": ConfigDefinition(
            key="TELEGRAM_CONFLICT_MAX_SECONDS",
            services=("bot",),
            default="300",
            description="חלון זמן מקסימלי (שניות) לרצף conflicts לפני יציאה מהתהליך כדי לשחרר lock ולאפשר recovery. 0/שלילי = ללא הגבלה (לא מומלץ).",
            category="telegram",
        ),
        # --- Distributed Lock (Mongo Lease + Heartbeat) ---
        "SERVICE_ID": ConfigDefinition(
            key="SERVICE_ID",
            services=("bot",),
            default="",
            description="מזהה ייחודי לשירות/סביבה עבור נעילה מבוזרת (key של מסמך הלוק). אם ריק, נופל ל-LOCK_ID המובנה.",
            category="locking",
        ),
        "RENDER_INSTANCE_ID": ConfigDefinition(
            key="RENDER_INSTANCE_ID",
            services=("bot",),
            default="",
            description="מזהה אינסטנס ב-Render (נשמר במסמך הלוק לצורכי תחקור). ה-owner בפועל הוא מזהה תהליך ייחודי (RENDER_INSTANCE_ID:pid). אם ריק, owner נופל ל-hostname:pid.",
            category="locking",
        ),
        "RENDER_SERVICE_NAME": ConfigDefinition(
            key="RENDER_SERVICE_NAME",
            services=("bot",),
            default="",
            description="שם השירות (label) לצורכי תחקור בלוק (host). אם ריק, נופל ל-HOSTNAME/hostname.",
            category="locking",
        ),
        "LOCK_LEASE_SECONDS": ConfigDefinition(
            key="LOCK_LEASE_SECONDS",
            services=("bot",),
            default="10",
            description="משך ה-lease של הלוק (שניות).",
            category="locking",
        ),
        "LOCK_HEARTBEAT_INTERVAL": ConfigDefinition(
            key="LOCK_HEARTBEAT_INTERVAL",
            services=("bot",),
            default="3",
            description="תדירות heartbeat (שניות) לרענון ה-lease. ברירת מחדל: 3 (מינימום 3).",
            category="locking",
        ),
        "LOCK_WAIT_FOR_ACQUIRE": ConfigDefinition(
            key="LOCK_WAIT_FOR_ACQUIRE",
            services=("bot",),
            default="false",
            description="אם true: המתנה אקטיבית ללוק עם retries קצרים. אם false: המתנה פסיבית עם jitter (ברירת מחדל).",
            category="locking",
        ),
        "LOCK_ACQUIRE_MAX_WAIT": ConfigDefinition(
            key="LOCK_ACQUIRE_MAX_WAIT",
            services=("bot",),
            default="0",
            description="מגבלת זמן (שניות) במצב המתנה אקטיבית. 0 = ללא מגבלה. (אליאס תאימות: LOCK_MAX_WAIT_SECONDS).",
            category="locking",
        ),
        "LOCK_WAIT_MIN_SECONDS": ConfigDefinition(
            key="LOCK_WAIT_MIN_SECONDS",
            services=("bot",),
            default="15",
            description="מינימום זמן המתנה פסיבית עם jitter (שניות).",
            category="locking",
        ),
        "LOCK_WAIT_MAX_SECONDS": ConfigDefinition(
            key="LOCK_WAIT_MAX_SECONDS",
            services=("bot",),
            default="45",
            description="מקסימום זמן המתנה פסיבית עם jitter (שניות).",
            category="locking",
        ),
        "LOCK_RETRY_INTERVAL_SECONDS": ConfigDefinition(
            key="LOCK_RETRY_INTERVAL_SECONDS",
            services=("bot",),
            default="1",
            description="זמן המתנה בין ניסיונות במצב המתנה אקטיבית. (Legacy/תאימות לאחור: שימש גם קודם).",
            category="locking",
        ),
        "LOCK_FAIL_OPEN": ConfigDefinition(
            key="LOCK_FAIL_OPEN",
            services=("bot",),
            default="false",
            description="אם true: במקרה חריגות ברכישת לוק, מאפשר עלייה 'ללא לוק' (לא מומלץ). ברירת מחדל false (fail-closed).",
            category="locking",
        ),
        "LOCK_WAIT_HEALTH_SERVER_ENABLED": ConfigDefinition(
            key="LOCK_WAIT_HEALTH_SERVER_ENABLED",
            services=("bot",),
            default="true",
            description="אם true: בעת המתנה ללוק ותוך קיום PORT, מפעיל שרת HTTP מינימלי ל-/health כדי לעבור health checks.",
            category="locking",
        ),
        "LOCK_PORT_GUARD_ENABLED": ConfigDefinition(
            key="LOCK_PORT_GUARD_ENABLED",
            services=("bot",),
            default="false",
            description="אם true: תופס פורט לוקאלי כדי למנוע שני תהליכים באותו worker. אם הפורט תפוס → יציאה.",
            category="locking",
        ),
        "LOCK_PORT_GUARD_PORT": ConfigDefinition(
            key="LOCK_PORT_GUARD_PORT",
            services=("bot",),
            default="9999",
            description="פורט לוקאלי לשמירה על בלעדיות תהליך (נדרש רק אם LOCK_PORT_GUARD_ENABLED=true).",
            category="locking",
        ),
        "LOCK_COLLECTION": ConfigDefinition(
            key="LOCK_COLLECTION",
            services=("bot",),
            default="locks",
            description="שם קולקציית הלוקים ב-MongoDB (ברירת מחדל legacy: locks).",
            category="locking",
        ),
        "ADMIN_USER_IDS": ConfigDefinition(
            key="ADMIN_USER_IDS",
            services=("webapp", "bot", "mcp", "webserver"),
            default="",
            description="רשימת מזהי אדמינים (מופרדים בפסיקים)",
            category="telegram",
            sensitive=True,
        ),
        "BLOCKED_USER_IDS": ConfigDefinition(
            key="BLOCKED_USER_IDS",
            services=("bot",),
            default="",
            description=(
                "רשימת מזהי משתמשים חסומים (מופרדים בפסיקים). "
                "רשת ביטחון שלא ניתן לשחרר ממנה דרך /unban"
            ),
            category="telegram",
            sensitive=True,
        ),
        "PREMIUM_USER_IDS": ConfigDefinition(
            key="PREMIUM_USER_IDS",
            services=("webapp", "bot"),
            default="",
            description="רשימת מזהי משתמשי פרימיום",
            category="telegram",
        ),
        "ALERT_TELEGRAM_BOT_TOKEN": ConfigDefinition(
            key="ALERT_TELEGRAM_BOT_TOKEN",
            services=("webapp", "bot", "mcp", "webserver"),
            default="",
            description="טוקן בוט התראות טלגרם",
            category="alerts",
            sensitive=True,
        ),
        "ALERT_TELEGRAM_CHAT_ID": ConfigDefinition(
            key="ALERT_TELEGRAM_CHAT_ID",
            services=("webapp", "bot", "mcp", "webserver"),
            default="",
            description="מזהה צ'אט להתראות טלגרם",
            category="alerts",
            sensitive=True,
        ),
        "ALERT_TELEGRAM_MIN_SEVERITY": ConfigDefinition(
            key="ALERT_TELEGRAM_MIN_SEVERITY",
            services=("webapp", "bot", "mcp", "webserver"),
            default="info",
            description="רמת חומרה מינימלית להתראות טלגרם",
            category="alerts",
        ),
        "ALERT_TELEGRAM_SUPPRESS_ALERTS": ConfigDefinition(
            key="ALERT_TELEGRAM_SUPPRESS_ALERTS",
            services=("webapp", "bot", "mcp", "webserver"),
            default="AppLatencyEWMARegression",
            description=(
                "שמות alerts (מופרדים בפסיקים) שלא יישלחו לטלגרם. "
                "השאר ריק כדי לאפשר את כולם."
            ),
            category="alerts",
        ),
        "ALERT_STARTUP_GRACE_PERIOD_SECONDS": ConfigDefinition(
            key="ALERT_STARTUP_GRACE_PERIOD_SECONDS",
            services=("webapp", "bot", "mcp", "webserver"),
            default="1200",
            description="חלון חסד (שניות) לאחר אתחול שבו מושתקים רק alerts רועשים מתוך allowlist (Mongo/Latency/EWMA)",
            category="alerts",
        ),
        "ALERTS_TEXT_INCLUDE_DASHBOARD_LINK_TELEGRAM": ConfigDefinition(
            key="ALERTS_TEXT_INCLUDE_DASHBOARD_LINK_TELEGRAM",
            services=("webapp", "bot"),
            default="false",
            description="אם true מוסיף שורת 📊 Dashboard לגוף ההודעה בטלגרם (ברירת מחדל כבוי כי יש כפתור Inline)",
            category="alerts",
        ),
        "ALERTS_TEXT_INCLUDE_DASHBOARD_LINK_SLACK": ConfigDefinition(
            key="ALERTS_TEXT_INCLUDE_DASHBOARD_LINK_SLACK",
            services=("webapp", "bot"),
            default="true",
            description="אם true מוסיף שורת 📊 Dashboard לגוף ההודעה ב-Slack (ברירת מחדל פעיל)",
            category="alerts",
        ),
        "REDIS_URL": ConfigDefinition(
            key="REDIS_URL",
            services=("webapp", "bot", "mcp", "webserver"),
            default="",
            description=(
                "כתובת Redis. **שני צרכנים נפרדים, משתנה אחד.** (1) הקאש: "
                "בלעדיה הוא מושבת לגמרי בשירות, ושאר הגדרות ה-Redis "
                "וה-Cache לא משפיעות על כלום. (2) ב-WebApp בלבד — גם "
                "אחסון ה-rate limiter; בלעדיה הוא נופל ל-memory://, "
                "כלומר המונים נספרים לכל gunicorn worker בנפרד "
                "ומתאפסים בכל דיפלוי"
            ),
            category="cache",
            sensitive=True,
        ),
        "REDIS_MAX_CONNECTIONS": ConfigDefinition(
            key="REDIS_MAX_CONNECTIONS",
            services=("webapp", "bot", "mcp", "webserver"),
            default="50",
            description="מספר חיבורים מקסימלי ל-Redis",
            category="cache",
        ),
        "REDIS_CONNECT_TIMEOUT": ConfigDefinition(
            key="REDIS_CONNECT_TIMEOUT",
            services=("webapp", "bot", "mcp", "webserver"),
            default="3",
            description="טיימאאוט התחברות ל-Redis (שניות)",
            category="cache",
        ),
        "REDIS_SOCKET_TIMEOUT": ConfigDefinition(
            key="REDIS_SOCKET_TIMEOUT",
            services=("webapp", "bot", "mcp", "webserver"),
            default="5",
            description="טיימאאוט סוקט Redis (שניות)",
            category="cache",
        ),
        "CACHE_ENABLED": ConfigDefinition(
            key="CACHE_ENABLED",
            services=("webapp", "bot", "mcp", "webserver"),
            default="true",
            description=(
                "הפעלת קאשינג גלובלי. דורש REDIS_URL; false מכבה את הקאש "
                "בלי למחוק את הכתובת"
            ),
            category="cache",
        ),
        "CACHE_CLEAR_BUDGET_SECONDS": ConfigDefinition(
            key="CACHE_CLEAR_BUDGET_SECONDS",
            services=("webapp", "bot", "mcp", "webserver"),
            default="5",
            description="תקציב זמן לניקוי קאש (שניות)",
            category="cache",
        ),
        "CACHE_DELETE_PATTERN_BUDGET_SECONDS": ConfigDefinition(
            key="CACHE_DELETE_PATTERN_BUDGET_SECONDS",
            services=("webapp", "bot", "mcp", "webserver"),
            default="5",
            description="תקציב זמן למחיקת תבנית מפתחות בקאש (שניות) – SCAN+DEL, למניעת תקיעה ב-Redis גדול",
            category="cache",
        ),
        "DISABLE_CACHE_MAINTENANCE": ConfigDefinition(
            key="DISABLE_CACHE_MAINTENANCE",
            services=("webapp", "bot", "mcp", "webserver"),
            default="false",
            description="השבתת תחזוקת קאש אוטומטית",
            category="cache",
        ),
        "PORT": ConfigDefinition(
            key="PORT",
            services=("webapp", "bot", "mcp", "webserver"),
            default="5000",
            description="פורט השרת (Render/Heroku)",
            category="webserver",
        ),
        "SECRET_KEY": ConfigDefinition(
            key="SECRET_KEY",
            services=("webapp", "bot", "mcp", "webserver"),
            default="dev-secret-key-change-in-production",
            description=(
                "מפתח סודי לסשנים ו-CSRF. במצב OAuth של ה-MCP: חותם את זהות המשתמש בין "
                "הוובאפ ל-MCP — חייב ערך אקראי חזק וזהה בשני השירותים (לא ברירת המחדל)."
            ),
            category="webserver",
            sensitive=True,
            required=True,
        ),
        "WEBAPP_LOGIN_SECRET": ConfigDefinition(
            key="WEBAPP_LOGIN_SECRET",
            services=("webapp", "bot", "webserver"),
            default="",
            description="מפתח סודי נוסף ל-login",
            category="webserver",
            sensitive=True,
        ),
        "DEBUG": ConfigDefinition(
            key="DEBUG",
            services=("webapp", "bot", "mcp", "webserver"),
            default="false",
            description="מצב דיבאג (true/false)",
            category="webserver",
        ),
        "PUBLIC_BASE_URL": ConfigDefinition(
            key="PUBLIC_BASE_URL",
            services=("webapp", "bot", "webserver"),
            default="",
            description="כתובת URL בסיסית לשיתוף קישורים",
            category="webserver",
        ),
        "PUBLIC_URL": ConfigDefinition(
            key="PUBLIC_URL",
            services=("webapp", "bot", "mcp", "webserver"),
            default="https://code-keeper-webapp.onrender.com",
            description="כתובת בסיס ציבורית של ה-WebApp (משמשת ליצירת קישור ציבורי ל-Observability Dashboard בהתראות)",
            category="webserver",
        ),
        "WEBAPP_URL": ConfigDefinition(
            key="WEBAPP_URL",
            services=("webapp", "bot", "mcp", "webserver"),
            default="",
            description="כתובת WebApp (אם שונה מ-public)",
            category="webserver",
        ),

        # --- MCP Server (Claude integration) ---
        "MCP_SERVER_URL": ConfigDefinition(
            key="MCP_SERVER_URL",
            services=("webapp", "bot", "mcp"),
            default="",
            description=(
                "ה-URL הציבורי (https) של שירות ה-MCP. בבוט: בניית פקודת /connect_claude. "
                "בשירות ה-MCP: issuer של OAuth (מדליק מצב OAuth יחד עם WEBAPP_URL). "
                "בוובאפ: שער open-redirect ב-/oauth/identify."
            ),
            category="mcp",
        ),
        "MCP_SERVER_NAME": ConfigDefinition(
            key="MCP_SERVER_NAME",
            services=("mcp",),
            default="CodeKeeper",
            description="שם התצוגה של שרת ה-MCP (שם ה-Connector שמוצג ללקוח).",
            category="mcp",
        ),
        "MCP_DOCS_REPO": ConfigDefinition(
            key="MCP_DOCS_REPO",
            default="CodeBot",
            description=(
                "רשימת הריפואים המותרים (CSV allowlist) שכלי codekeeper_docs_get_section הציבורי "
                "רשאי לקרוא מהם קבצי RST. גבול אבטחה — repo שאינו ברשימה נדחה. ברירת מחדל: CodeBot."
            ),
            category="mcp",
            services=("mcp",),
        ),
        "MCP_ALLOWED_HOSTS": ConfigDefinition(
            key="MCP_ALLOWED_HOSTS",
            services=("mcp",),
            default="",
            description="Host מותרים לשרת ה-MCP (CSV, תומך wildcard). ריק = הגנת DNS-rebinding כבויה (מתאים לשרת ציבורי מוגן-טוקן).",
            category="mcp",
        ),
        "MCP_ALLOWED_ORIGINS": ConfigDefinition(
            key="MCP_ALLOWED_ORIGINS",
            services=("mcp",),
            default="",
            description="Origin מותרים לשרת ה-MCP (CSV). רלוונטי רק כשמפעילים הגנה דרך MCP_ALLOWED_HOSTS.",
            category="mcp",
        ),
        "MCP_REPO_DENYLIST_EXTRA": ConfigDefinition(
            key="MCP_REPO_DENYLIST_EXTRA",
            services=("mcp",),
            default="",
            description=(
                "תבניות glob נוספות (CSV) ל-denylist הסודות של כלי דפדפן הריפו ב-MCP, "
                "מעל רשימת הבסיס המובנית (.env*, *.pem, id_rsa* וכו')."
            ),
            category="mcp",
        ),
        "MCP_REPO_AUTOSYNC": ConfigDefinition(
            key="MCP_REPO_AUTOSYNC",
            services=("mcp",),
            default="1",
            description=(
                "רענון אוטומטי של ה-mirrors המקומיים בשירות ה-MCP (thread רקע): "
                "שכפול ריפו חסר מ-repo_metadata.repo_url ו-fetch כשה-SHA ב-Mongo שונה מהמקומי. 0 מכבה."
            ),
            category="mcp",
        ),
        "MCP_REPO_AUTOSYNC_INTERVAL": ConfigDefinition(
            key="MCP_REPO_AUTOSYNC_INTERVAL",
            services=("mcp",),
            default="300",
            description="מרווח בשניות בין מעברי ה-autosync של דפדפן הריפו ב-MCP (מינימום 30).",
            category="mcp",
        ),
        "POSTHOG_PROJECT_TOKEN": ConfigDefinition(
            key="POSTHOG_PROJECT_TOKEN",
            services=("mcp",),
            default="",
            description=(
                "טוקן הפרויקט ב-PostHog (phc_...) למדידת השימוש בשרת ה-MCP. ריק — "
                "המדידה כבויה והשרת עולה רגיל (בסביבת פיתוח העלייה נכשלת ברעש)."
            ),
            category="mcp",
            sensitive=True,
        ),
        "POSTHOG_HOST": ConfigDefinition(
            key="POSTHOG_HOST",
            services=("mcp", "webapp"),
            default="",
            description=(
                "כתובת PostHog. הערך שונה בין השירותים ואינו ניתן להעתקה ביניהם: "
                "ב-MCP זו כתובת שליחת האירועים (https://us.i.posthog.com ל-US Cloud, "
                "https://eu.i.posthog.com ל-EU), ובוובאפ זו כתובת קריאת הנתונים "
                "(https://us.posthog.com) עבור /admin/mcp. הערך המוצג כאן הוא של "
                "הוובאפ בלבד. חסר בוובאפ — העמוד מציג שגיאת קונפיגורציה ואינו נופל "
                "לברירת מחדל."
            ),
            category="mcp",
        ),
        "POSTHOG_PERSONAL_API_KEY": ConfigDefinition(
            key="POSTHOG_PERSONAL_API_KEY",
            services=("webapp",),
            default="",
            description=(
                "מפתח אישי של PostHog (phx_...) לקריאת נתוני ה-MCP analytics במסך "
                "/admin/mcp. דורש את ה-scope endpoint:read. ריק — העמוד מציג הודעה "
                "שהמדידה אינה מוגדרת. אינו מחליף את POSTHOG_PROJECT_TOKEN, שהוא "
                "מפתח כתיבה של שירות אחר."
            ),
            category="mcp",
            sensitive=True,
        ),
        "POSTHOG_PROJECT_ID": ConfigDefinition(
            key="POSTHOG_PROJECT_ID",
            services=("webapp",),
            default="",
            description=(
                "מזהה הפרויקט המספרי ב-PostHog, לבניית נתיב ה-API של /admin/mcp. "
                "מופיע בכתובת של הפרויקט בממשק PostHog. ספרות בלבד — ערך אחר "
                "נדחה לפני שנשלחת בקשה, כי הוא נכנס לנתיב הכתובת שנרשמת ל-span."
            ),
            category="mcp",
        ),

        # --- Repo Sync Engine (Git Mirror) ---
        "REPO_NAME": ConfigDefinition(
            key="REPO_NAME",
            services=("webapp", "bot"),
            default="CodeBot",
            description="שם ריפו לוגי לשימוש ב-Repo Sync (מפתח ל-mirror בדיסק ול-metadata ב-DB).",
            category="repo_sync",
        ),
        "REPO_MIRROR_PATH": ConfigDefinition(
            key="REPO_MIRROR_PATH",
            services=("webapp", "bot", "mcp", "webserver"),
            default="/var/data/repos",
            description="נתיב בסיסי בדיסק לשמירת Bare Mirror של הריפו (Repo Sync Engine).",
            category="repo_sync",
        ),
        "GITHUB_WEBHOOK_SECRET": ConfigDefinition(
            key="GITHUB_WEBHOOK_SECRET",
            services=("webapp", "bot"),
            default="",
            description="סוד לאימות GitHub Webhook (HMAC SHA256) עבור POST /api/webhooks/github (Repo Sync).",
            category="repo_sync",
            sensitive=True,
        ),
        "GITHUB_TOKEN": ConfigDefinition(
            key="GITHUB_TOKEN",
            services=("webapp", "bot", "mcp", "webserver"),
            default="",
            description="טוקן GitHub לשימוש בפעולות API וגם לאימות clone/fetch של Repo Sync בריפו פרטי (אם רלוונטי).",
            category="repo_sync",
            sensitive=True,
        ),
        "GITHUB_TOKENS": ConfigDefinition(
            key="GITHUB_TOKENS",
            services=("webapp", "bot", "mcp", "webserver"),
            default="",
            description=(
                "מיפוי בעלים(owner/org)→טוקן לסנכרון ריפואים ממספר ארגונים, כשטוקן יחיד לא מכסה את כולם. "
                "פורמט JSON: {\"Org\": \"ghp_...\"} או פשוט: Org1=ghp_...,Org2=github_pat_.... "
                "נבחר לפי הבעלים של הריפו; אם אין התאמה נופלים ל-GITHUB_TOKEN."
            ),
            category="repo_sync",
            sensitive=True,
        ),
        "BOT_JOBS_API_BASE_URL": ConfigDefinition(
            key="BOT_JOBS_API_BASE_URL",
            services=("webapp", "bot"),
            default="",
            description="בסיס URL ל-API הפנימי של הבוט עבור Trigger של Jobs ממסך המוניטור (WebApp -> Bot).",
            category="jobs_monitor",
        ),
        "BOT_API_BASE_URL": ConfigDefinition(
            key="BOT_API_BASE_URL",
            services=("webapp", "bot"),
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
        "WEBAPP_WARMUP_BASE_URL": ConfigDefinition(
            key="WEBAPP_WARMUP_BASE_URL",
            default="http://127.0.0.1:$PORT",
            description="בסיס ה-URL לבקשות ה-Frontend Warmup",
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
            services=("webapp", "bot"),
            default="1",
            description="מספר ה-workers של Gunicorn ב-WebApp; אם מוגדר, גובר על ברירת המחדל ומקטין queue_delay תחת עומס",
            category="gunicorn",
        ),
        "WEBAPP_GUNICORN_WORKERS": ConfigDefinition(
            key="WEBAPP_GUNICORN_WORKERS",
            default="1",
            description="מספר ה-workers של Gunicorn (חלופה ל-WEB_CONCURRENCY)",
            category="gunicorn",
        ),
        "WEBAPP_GUNICORN_THREADS": ConfigDefinition(
            key="WEBAPP_GUNICORN_THREADS",
            default="4",
            description="מספר Threads לכל worker כאשר משתמשים ב-gthread (לא רלוונטי ל-gevent)",
            category="gunicorn",
        ),
        "WEBAPP_GUNICORN_WORKER_CLASS": ConfigDefinition(
            key="WEBAPP_GUNICORN_WORKER_CLASS",
            default="gevent",
            description="Worker class של Gunicorn",
            category="gunicorn",
        ),
        "WEBAPP_GUNICORN_WORKER_CONNECTIONS": ConfigDefinition(
            key="WEBAPP_GUNICORN_WORKER_CONNECTIONS",
            default="100",
            description="מספר חיבורים מקסימלי ל-worker כאשר משתמשים ב-gevent",
            category="gunicorn",
        ),
        "WEBAPP_GUNICORN_TIMEOUT": ConfigDefinition(
            key="WEBAPP_GUNICORN_TIMEOUT",
            default="180",
            description="Timeout (שניות) לבקשה ב-Gunicorn",
            category="gunicorn",
        ),
        "WEBAPP_GUNICORN_GRACEFUL_TIMEOUT": ConfigDefinition(
            key="WEBAPP_GUNICORN_GRACEFUL_TIMEOUT",
            default="180",
            description="graceful-timeout (שניות) לסגירה נקייה של worker ב-Gunicorn",
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
            services=("webapp", "bot", "mcp", "webserver"),
            default="50",
            description="מגבלת חיבורים ב-TCPConnector של aiohttp",
            category="http",
        ),
        "AIOHTTP_TIMEOUT_TOTAL": ConfigDefinition(
            key="AIOHTTP_TIMEOUT_TOTAL",
            services=("webapp", "bot", "mcp", "webserver"),
            default="10",
            description="טיימאאוט כולל ל-aiohttp (שניות)",
            category="http",
        ),
        "AIOHTTP_LIMIT_PER_HOST": ConfigDefinition(
            key="AIOHTTP_LIMIT_PER_HOST",
            services=("webapp", "bot", "mcp", "webserver"),
            default="25",
            description="מגבלת חיבורים לכל host",
            category="http",
        ),
        "REQUESTS_POOL_CONNECTIONS": ConfigDefinition(
            key="REQUESTS_POOL_CONNECTIONS",
            services=("webapp", "bot", "mcp", "webserver"),
            default="20",
            description="חיבורי פול עבור requests",
            category="http",
        ),
        "REQUESTS_POOL_MAXSIZE": ConfigDefinition(
            key="REQUESTS_POOL_MAXSIZE",
            services=("webapp", "bot", "mcp", "webserver"),
            default="100",
            description="גודל מקסימלי לפול requests",
            category="http",
        ),
        "REQUESTS_TIMEOUT": ConfigDefinition(
            key="REQUESTS_TIMEOUT",
            services=("webapp", "bot", "mcp", "webserver"),
            default="8.0",
            description="טיימאאוט ברירת מחדל ל-requests (שניות)",
            category="http",
        ),
        "REQUESTS_RETRIES": ConfigDefinition(
            key="REQUESTS_RETRIES",
            services=("webapp", "bot", "mcp", "webserver"),
            default="2",
            description="מספר ניסיונות חוזרים ב-requests",
            category="http",
        ),
        "REQUESTS_RETRY_BACKOFF": ConfigDefinition(
            key="REQUESTS_RETRY_BACKOFF",
            services=("webapp", "bot", "mcp", "webserver"),
            default="0.2",
            description="פקטור backoff בין ניסיונות",
            category="http",
        ),
        "PUSH_NOTIFICATIONS_ENABLED": ConfigDefinition(
            key="PUSH_NOTIFICATIONS_ENABLED",
            services=("webapp", "bot"),
            default="true",
            description="הפעלת התראות Push",
            category="push",
        ),
        "VAPID_PUBLIC_KEY": ConfigDefinition(
            key="VAPID_PUBLIC_KEY",
            services=("webapp", "bot"),
            default="",
            description="מפתח VAPID ציבורי ל-Push",
            category="push",
            sensitive=True,
        ),
        "VAPID_PRIVATE_KEY": ConfigDefinition(
            key="VAPID_PRIVATE_KEY",
            services=("webapp", "bot"),
            default="",
            description="מפתח VAPID פרטי ל-Push",
            category="push",
            sensitive=True,
        ),
        "VAPID_SUB_EMAIL": ConfigDefinition(
            key="VAPID_SUB_EMAIL",
            services=("webapp", "bot"),
            default="",
            description="כתובת אימייל ל-VAPID",
            category="push",
        ),
        "SUPPORT_EMAIL": ConfigDefinition(
            key="SUPPORT_EMAIL",
            services=("webapp", "bot"),
            default="",
            description="כתובת אימייל תמיכה",
            category="push",
        ),
        "PUSH_REMOTE_DELIVERY_ENABLED": ConfigDefinition(
            key="PUSH_REMOTE_DELIVERY_ENABLED",
            services=("webapp", "bot"),
            default="false",
            description="הפעלת משלוח Push מרוחק",
            category="push",
        ),
        "PUSH_DELIVERY_URL": ConfigDefinition(
            key="PUSH_DELIVERY_URL",
            services=("webapp", "bot"),
            default="",
            description="כתובת URL למשלוח Push",
            category="push",
            sensitive=True,
        ),
        "PUSH_DELIVERY_TOKEN": ConfigDefinition(
            key="PUSH_DELIVERY_TOKEN",
            services=("webapp", "bot"),
            default="",
            description="טוקן אימות למשלוח Push",
            category="push",
            sensitive=True,
        ),
        "PUSH_DELIVERY_TIMEOUT_SECONDS": ConfigDefinition(
            key="PUSH_DELIVERY_TIMEOUT_SECONDS",
            services=("webapp", "bot"),
            default="3",
            description="טיימאאוט למשלוח Push (שניות)",
            category="push",
        ),
        "PUSH_DELIVERY_URGENCY": ConfigDefinition(
            key="PUSH_DELIVERY_URGENCY",
            services=("webapp", "bot"),
            default="high",
            description="רמת דחיפות ברירת מחדל ל-Push",
            category="push",
        ),
        "PUSH_SEND_INTERVAL_SECONDS": ConfigDefinition(
            key="PUSH_SEND_INTERVAL_SECONDS",
            services=("webapp", "bot"),
            default="60",
            description="מרווח שליחת Push (שניות)",
            category="push",
        ),
        "PUSH_CLAIM_TTL_SECONDS": ConfigDefinition(
            key="PUSH_CLAIM_TTL_SECONDS",
            services=("webapp", "bot"),
            default="60",
            description="TTL להחזקת Push (שניות)",
            category="push",
        ),
        "PASTEBIN_API_KEY": ConfigDefinition(
            key="PASTEBIN_API_KEY",
            services=("webapp", "bot", "webserver"),
            default="",
            description="מפתח API ל-Pastebin",
            category="external",
            sensitive=True,
        ),
        "SENTRY_DSN": ConfigDefinition(
            key="SENTRY_DSN",
            services=("webapp", "bot", "mcp", "webserver"),
            default="",
            description="DSN ל-Sentry לניטור שגיאות",
            category="monitoring",
            sensitive=True,
        ),
        "SENTRY_DASHBOARD_URL": ConfigDefinition(
            key="SENTRY_DASHBOARD_URL",
            services=("webapp", "bot", "mcp", "webserver"),
            default="",
            description="כתובת לוח הבקרה של Sentry",
            category="monitoring",
        ),
        "SENTRY_TRACES_SAMPLE_RATE": ConfigDefinition(
            key="SENTRY_TRACES_SAMPLE_RATE",
            services=("webapp", "bot", "mcp", "webserver"),
            default="0.1",
            description="שיעור דגימת Traces ב-Sentry",
            category="monitoring",
        ),
        "SENTRY_PROFILES_SAMPLE_RATE": ConfigDefinition(
            key="SENTRY_PROFILES_SAMPLE_RATE",
            services=("webapp", "bot", "mcp", "webserver"),
            default="0.1",
            description="שיעור דגימת Profiles ב-Sentry",
            category="monitoring",
        ),
        "SENTRY_WEBHOOK_SECRET": ConfigDefinition(
            key="SENTRY_WEBHOOK_SECRET",
            services=("webserver",),
            default="",
            description="סוד ל-Sentry Webhook",
            category="monitoring",
            sensitive=True,
        ),
        "SENTRY_WEBHOOK_DEDUP_WINDOW_SECONDS": ConfigDefinition(
            key="SENTRY_WEBHOOK_DEDUP_WINDOW_SECONDS",
            services=("webserver",),
            default="300",
            description="חלון dedup ל-Sentry Webhooks (שניות)",
            category="monitoring",
        ),
        # ── Sentry API + Polling ──
        # התיאורים מועתקים מ-docs/environment-variables.rst, שבו כולם כבר
        # מתועדים; ה-services נגזרו מסגור ה-import של כל נקודת כניסה.
        "SENTRY_AUTH_TOKEN": ConfigDefinition(
            key="SENTRY_AUTH_TOKEN",
            services=("bot",),
            default="",
            description="אסימון Bearer לקריאות API של Sentry (נדרש ל-ChatOps ולאינטגרציות)",
            category="monitoring",
        ),
        "SENTRY_API_URL": ConfigDefinition(
            key="SENTRY_API_URL",
            services=("bot",),
            default="https://sentry.io/api/0",
            description="בסיס ה-API של Sentry (רלוונטי ל-self-hosted)",
            category="monitoring",
        ),
        "SENTRY_ORG": ConfigDefinition(
            key="SENTRY_ORG",
            services=("webapp", "bot"),
            default="",
            description="ה-slug של הארגון ב-Sentry; משמש לבניית URLs ולקריאות API",
            category="monitoring",
        ),
        "SENTRY_ORG_SLUG": ConfigDefinition(
            key="SENTRY_ORG_SLUG",
            services=("webapp", "bot"),
            default="",
            description="חלופה ל-SENTRY_ORG — נקרא רק אם SENTRY_ORG ריק",
            category="monitoring",
        ),
        "SENTRY_PROJECT": ConfigDefinition(
            key="SENTRY_PROJECT",
            services=("bot",),
            default="",
            description="פרויקט ברירת מחדל לסינון Issues/Events",
            category="monitoring",
        ),
        "SENTRY_PROJECT_SLUG": ConfigDefinition(
            key="SENTRY_PROJECT_SLUG",
            services=("bot",),
            default="",
            description="חלופה ל-SENTRY_PROJECT — נקרא רק אם SENTRY_PROJECT ריק",
            category="monitoring",
        ),
        "SENTRY_PROJECT_URL": ConfigDefinition(
            key="SENTRY_PROJECT_URL",
            services=("webapp", "bot"),
            default="",
            description=(
                "URL ישיר לפרויקט ב-Sentry, כשאין Dashboard ארגוני. נקרא רק אם "
                "SENTRY_DASHBOARD_URL ריק"
            ),
            category="monitoring",
        ),
        "SENTRY_POLL_ENABLED": ConfigDefinition(
            key="SENTRY_POLL_ENABLED",
            services=("bot",),
            default="false",
            description=(
                "מפעיל Polling תקופתי ל-Sentry, כחלופה כשאין Webhook. הבוט מושך "
                "Issues אחרונים ומייצר internal_alerts מסוג sentry_issue"
            ),
            category="monitoring",
        ),
        "SENTRY_POLL_INTERVAL_SECS": ConfigDefinition(
            key="SENTRY_POLL_INTERVAL_SECS",
            services=("bot",),
            default="300",
            description="כל כמה שניות לבצע Polling ל-Sentry (מינימום 30)",
            category="monitoring",
        ),
        "SENTRY_POLL_FIRST_SECS": ConfigDefinition(
            key="SENTRY_POLL_FIRST_SECS",
            services=("bot",),
            default="20",
            description="השהיה בשניות לפני ריצת ה-Poll הראשונה אחרי עליית הבוט",
            category="monitoring",
        ),
        "SENTRY_POLL_LIMIT": ConfigDefinition(
            key="SENTRY_POLL_LIMIT",
            services=("bot",),
            default="10",
            description="כמה Issues למשוך בכל Poll (מינימום 1, מקסימום 100)",
            category="monitoring",
        ),
        "SENTRY_POLL_SEVERITY": ConfigDefinition(
            key="SENTRY_POLL_SEVERITY",
            services=("bot",),
            default="error",
            description=(
                "דרגת החומרה שתישלח כ-internal_alerts עבור Sentry Poll "
                "(info/warning/error/critical)"
            ),
            category="monitoring",
        ),
        "SENTRY_POLL_SEED_SILENT": ConfigDefinition(
            key="SENTRY_POLL_SEED_SILENT",
            services=("bot",),
            default="true",
            description=(
                "אם true — ההרצה הראשונה רק זורעת מצב ואינה שולחת התראות על Issues "
                "קיימים; רק פעילות חדשה בהמשך תייצר התראה"
            ),
            category="monitoring",
        ),
        "SENTRY_POLL_DEDUP_SECONDS": ConfigDefinition(
            key="SENTRY_POLL_DEDUP_SECONDS",
            services=("bot",),
            default="900",
            description="חלון דה-דופליקציה בשניות לכל Issue, כדי למנוע הצפה (0 מנטרל)",
            category="monitoring",
        ),
        "OTEL_EXPORTER_OTLP_ENDPOINT": ConfigDefinition(
            key="OTEL_EXPORTER_OTLP_ENDPOINT",
            services=("webapp", "bot", "webserver"),
            default="",
            description="Endpoint ל-OTLP Exporter",
            category="monitoring",
        ),
        "OTEL_EXPORTER_INSECURE": ConfigDefinition(
            key="OTEL_EXPORTER_INSECURE",
            services=("webapp", "bot", "webserver"),
            default="false",
            description="שימוש בחיבור לא מאובטח ל-OTLP",
            category="monitoring",
        ),
        "OBS_AI_EXPLAIN_TIMEOUT": ConfigDefinition(
            key="OBS_AI_EXPLAIN_TIMEOUT",
            services=("webapp", "bot", "mcp", "webserver"),
            default="10",
            description="טיימאאוט לבקשות AI (שניות)",
            category="ai",
        ),
        "OBS_AI_EXPLAIN_CACHE_TTL": ConfigDefinition(
            key="OBS_AI_EXPLAIN_CACHE_TTL",
            services=("webapp", "bot", "mcp", "webserver"),
            default="600",
            description="TTL לקאש הסברי AI (שניות)",
            category="ai",
        ),
        "LOG_LEVEL": ConfigDefinition(
            key="LOG_LEVEL",
            services=("webapp", "bot", "mcp", "webserver"),
            default="INFO",
            description="רמת הלוגים (DEBUG/INFO/WARNING/ERROR/CRITICAL או ערך מספרי כמו 10/20/30)",
            category="logging",
        ),
        "LOG_FORMAT": ConfigDefinition(
            key="LOG_FORMAT",
            services=("webapp", "bot", "mcp", "webserver"),
            default="json",
            description="פורמט הלוגים (json/console)",
            category="logging",
        ),
        "LOG_INFO_SAMPLE_RATE": ConfigDefinition(
            key="LOG_INFO_SAMPLE_RATE",
            services=("webapp", "bot", "mcp", "webserver"),
            default="1.0",
            description="שיעור דגימת לוגים ברמת INFO",
            category="logging",
        ),
        "LOG_INFO_SAMPLE_ALLOWLIST": ConfigDefinition(
            key="LOG_INFO_SAMPLE_ALLOWLIST",
            services=("webapp", "bot", "mcp", "webserver"),
            default="",
            description="רשימת אירועים שלא יידגמו (מופרדים בפסיקים)",
            category="logging",
        ),
        "ALERT_QUICK_FIX_PATH": ConfigDefinition(
            key="ALERT_QUICK_FIX_PATH",
            services=("webapp", "bot", "mcp", "webserver"),
            default="config/alert_quick_fixes.json",
            description="נתיב לקובץ תיקונים מהירים",
            category="alerts",
        ),
        "ALERTMANAGER_WEBHOOK_SECRET": ConfigDefinition(
            key="ALERTMANAGER_WEBHOOK_SECRET",
            services=("webapp", "bot"),
            default="",
            description="סוד Webhook ל-Alertmanager",
            category="alerts",
            sensitive=True,
        ),
        "ALERTMANAGER_IP_ALLOWLIST": ConfigDefinition(
            key="ALERTMANAGER_IP_ALLOWLIST",
            services=("webapp", "bot"),
            default="",
            description="רשימת IP מותרים ל-Alertmanager",
            category="alerts",
        ),
        "ALLOWED_WEBHOOK_HOSTS": ConfigDefinition(
            key="ALLOWED_WEBHOOK_HOSTS",
            services=("webapp", "bot", "mcp", "webserver"),
            default="",
            description="Allowlist אופציונלי ליעדי webhook (Visual Rule Engine) לפי hostnames (CSV)",
            category="alerts",
        ),
        "ALLOWED_WEBHOOK_SUFFIXES": ConfigDefinition(
            key="ALLOWED_WEBHOOK_SUFFIXES",
            services=("webapp", "bot", "mcp", "webserver"),
            default="",
            description="Allowlist אופציונלי ליעדי webhook (Visual Rule Engine) לפי סיומות דומיין (CSV, למשל .example.com)",
            category="alerts",
        ),
        "OBSERVABILITY_RUNBOOK_PATH": ConfigDefinition(
            key="OBSERVABILITY_RUNBOOK_PATH",
            services=("webapp", "bot", "mcp", "webserver"),
            default="config/observability_runbooks.yml",
            description="נתיב לקובץ Runbooks",
            category="observability",
        ),
        "ALERT_TAGS_COLLECTION": ConfigDefinition(
            key="ALERT_TAGS_COLLECTION",
            services=("webapp", "bot", "mcp", "webserver"),
            default="alert_tags",
            description="שם ה-Collection לתגיות התראות (Manual Alert Tagging) ב-Observability",
            category="observability",
        ),
        "ALERT_TAGS_DB_DISABLED": ConfigDefinition(
            key="ALERT_TAGS_DB_DISABLED",
            services=("webapp", "bot", "mcp", "webserver"),
            default="false",
            description="אם true מכבה שמירה/שליפה של תגיות להתראות (Manual Alert Tagging) מה-DB",
            category="observability",
        ),
        "OBS_RUNBOOK_STATE_TTL": ConfigDefinition(
            key="OBS_RUNBOOK_STATE_TTL",
            services=("webapp", "bot", "mcp", "webserver"),
            default="14400",
            description="TTL למצב Runbook (שניות)",
            category="observability",
        ),
        "OBS_RUNBOOK_EVENT_TTL": ConfigDefinition(
            key="OBS_RUNBOOK_EVENT_TTL",
            services=("webapp", "bot", "mcp", "webserver"),
            default="900",
            description="TTL לאירועי Runbook (שניות)",
            category="observability",
        ),
        "OBSERVABILITY_WARMUP_RANGES": ConfigDefinition(
            key="OBSERVABILITY_WARMUP_RANGES",
            services=("webapp", "bot"),
            default="24h,7d,30d",
            description="רשימת טווחי זמן (CSV) לחימום /api/observability/aggregations",
            category="observability",
        ),
        "OBSERVABILITY_WARMUP_ENABLED": ConfigDefinition(
            key="OBSERVABILITY_WARMUP_ENABLED",
            services=("webapp", "bot"),
            default="true",
            description="הפעלה/כיבוי של Warmup כבד לדוחות Observability ברקע אחרי עליית התהליך",
            category="observability",
        ),
        "OBSERVABILITY_WARMUP_DELAY_SECONDS": ConfigDefinition(
            key="OBSERVABILITY_WARMUP_DELAY_SECONDS",
            services=("webapp", "bot"),
            default="5",
            description="השהייה (שניות) לפני תחילת Warmup הדוחות כדי לא להעמיס בזמן העלייה",
            category="observability",
        ),
        "OBSERVABILITY_WARMUP_BUDGET_SECONDS": ConfigDefinition(
            key="OBSERVABILITY_WARMUP_BUDGET_SECONDS",
            services=("webapp", "bot"),
            default="20",
            description="תקציב זמן מקסימלי (שניות) ל-Warmup הדוחות ברקע; מעבר לתקציב נעצור מוקדם",
            category="observability",
        ),
        "OBSERVABILITY_WARMUP_SLOW_LIMIT": ConfigDefinition(
            key="OBSERVABILITY_WARMUP_SLOW_LIMIT",
            services=("webapp", "bot"),
            default="5",
            description="ערך slow_endpoints_limit עבור החימום (ברירת מחדל כמו ב-API)",
            category="observability",
        ),
        "SAFE_MODE": ConfigDefinition(
            key="SAFE_MODE",
            services=("webapp", "bot", "mcp", "webserver"),
            default="false",
            description="מצב בטוח - משבית פעולות מסוכנות",
            category="predictive",
        ),
        "DISABLE_PREEMPTIVE_ACTIONS": ConfigDefinition(
            key="DISABLE_PREEMPTIVE_ACTIONS",
            services=("webapp", "bot", "mcp", "webserver"),
            default="false",
            description="השבתת פעולות מנע אוטומטיות",
            category="predictive",
        ),
        "RATE_LIMIT_SHADOW_MODE": ConfigDefinition(
            key="RATE_LIMIT_SHADOW_MODE",
            services=("webapp", "bot"),
            default="false",
            description="מצב צל - ספירה בלבד ללא חסימה",
            category="rate_limit",
        ),
        "RATE_LIMIT_PER_MINUTE": ConfigDefinition(
            key="RATE_LIMIT_PER_MINUTE",
            services=("webapp", "bot"),
            default="30",
            description="מגבלת בקשות לדקה",
            category="rate_limit",
        ),
        "ENABLE_METRICS": ConfigDefinition(
            key="ENABLE_METRICS",
            services=("webapp", "bot", "webserver"),
            default="false",
            description="הפעלת יצוא Metrics דרך OTLP (OpenTelemetry Metrics). כדי לפעול בפועל צריך גם OTEL_EXPORTER_OTLP_ENDPOINT.",
            category="metrics",
        ),
        "ENABLE_PROMETHEUS_METRICS": ConfigDefinition(
            key="ENABLE_PROMETHEUS_METRICS",
            services=("webapp", "bot", "webserver"),
            default="false",
            description="הפעלת OpenTelemetry Prometheus exporter (scrape דרך /metrics).",
            category="metrics",
        ),
        "ENABLE_PROMETHEUS_OTEL_METRICS": ConfigDefinition(
            key="ENABLE_PROMETHEUS_OTEL_METRICS",
            services=("webapp", "bot", "webserver"),
            default="false",
            description="Alias ל-ENABLE_PROMETHEUS_METRICS (תאימות לאחור).",
            category="metrics",
        ),
        "PROMETHEUS_URL": ConfigDefinition(
            key="PROMETHEUS_URL",
            services=("webapp", "bot", "mcp", "webserver"),
            default="",
            description="בסיס URL ל-Prometheus HTTP API. כשמוגדר, דשבורד Observability יקרא timeseries מ-Prometheus במקום מה-DB.",
            category="observability",
        ),
        "PROMETHEUS_RATE_WINDOW": ConfigDefinition(
            key="PROMETHEUS_RATE_WINDOW",
            services=("webapp", "bot", "mcp", "webserver"),
            default="5m",
            description="חלון ברירת מחדל ל-rate()/histogram_quantile() ב-PromQL (למשל 5m).",
            category="observability",
        ),
        "HTTP_SAMPLE_BUFFER": ConfigDefinition(
            key="HTTP_SAMPLE_BUFFER",
            services=("webapp", "bot", "mcp", "webserver"),
            default="2000",
            description="גודל באפר דגימות HTTP",
            category="metrics",
        ),
        "QUEUE_DELAY_WARN_MS": ConfigDefinition(
            key="QUEUE_DELAY_WARN_MS",
            services=("webapp", "bot", "webserver"),
            default="500",
            description="סף אזהרת עיכוב תור (מילישניות)",
            category="performance",
        ),
        "SLOW_MS": ConfigDefinition(
            key="SLOW_MS",
            services=("webapp", "bot"),
            default="0",
            description="סף לוגינג בקשות איטיות (מילישניות)",
            category="performance",
        ),
        "COLLECTIONS_API_ITEMS_SLOW_MS": ConfigDefinition(
            key="COLLECTIONS_API_ITEMS_SLOW_MS",
            services=("webapp", "bot"),
            default="",
            description="סף איטיות ל-Collections API",
            category="performance",
        ),
        "ANOMALY_IGNORE_ENDPOINTS": ConfigDefinition(
            key="ANOMALY_IGNORE_ENDPOINTS",
            services=("webapp", "bot", "mcp", "webserver"),
            default="",
            description="נקודות קצה להתעלמות בזיהוי אנומליות",
            category="performance",
        ),
        "DRIVE_MENU_V2": ConfigDefinition(
            key="DRIVE_MENU_V2",
            services=("webapp", "bot"),
            default="true",
            description="הפעלת תפריט Drive v2",
            category="features",
        ),
        "RECYCLE_TTL_DAYS": ConfigDefinition(
            key="RECYCLE_TTL_DAYS",
            services=("webapp", "bot", "mcp", "webserver"),
            default="7",
            description="ימים לשמירת פריטים בסל המיחזור",
            category="limits",
        ),
        "PUBLIC_SHARE_TTL_DAYS": ConfigDefinition(
            key="PUBLIC_SHARE_TTL_DAYS",
            services=("webapp", "bot"),
            default="7",
            description="ימים לתוקף שיתוף ציבורי",
            category="limits",
        ),
        "PERSISTENT_LOGIN_DAYS": ConfigDefinition(
            key="PERSISTENT_LOGIN_DAYS",
            services=("webapp", "bot"),
            default="180",
            description="ימים לשמירת התחברות קבועה",
            category="limits",
        ),
        "SEARCH_PAGE_SIZE": ConfigDefinition(
            key="SEARCH_PAGE_SIZE",
            services=("webapp", "bot", "webserver"),
            default="200",
            description="גודל עמוד חיפוש",
            category="limits",
        ),
        "UI_PAGE_SIZE": ConfigDefinition(
            key="UI_PAGE_SIZE",
            services=("webapp", "bot"),
            default="10",
            description="גודל עמוד בממשק משתמש",
            category="limits",
        ),
        "UPTIME_PROVIDER": ConfigDefinition(
            key="UPTIME_PROVIDER",
            services=("webapp", "bot"),
            default="",
            description="ספק Uptime (betteruptime וכו')",
            category="uptime",
        ),
        "UPTIME_API_KEY": ConfigDefinition(
            key="UPTIME_API_KEY",
            services=("webapp", "bot"),
            default="",
            description="מפתח API ל-Uptime",
            category="uptime",
            sensitive=True,
        ),
        "UPTIME_MONITOR_ID": ConfigDefinition(
            key="UPTIME_MONITOR_ID",
            services=("webapp", "bot"),
            default="",
            description="מזהה Monitor ב-Uptime",
            category="uptime",
        ),
        "UPTIME_STATUS_URL": ConfigDefinition(
            key="UPTIME_STATUS_URL",
            services=("webapp", "bot"),
            default="",
            description="כתובת דף סטטוס Uptime",
            category="uptime",
        ),
        "UPTIME_WIDGET_SCRIPT_URL": ConfigDefinition(
            key="UPTIME_WIDGET_SCRIPT_URL",
            services=("webapp", "bot"),
            default="https://uptime.betterstack.com/widgets/announcement.js",
            description="כתובת סקריפט Widget",
            category="uptime",
        ),
        "UPTIME_WIDGET_ID": ConfigDefinition(
            key="UPTIME_WIDGET_ID",
            services=("webapp", "bot"),
            default="",
            description="מזהה Widget ב-Uptime",
            category="uptime",
        ),
        "UPTIME_CACHE_TTL_SECONDS": ConfigDefinition(
            key="UPTIME_CACHE_TTL_SECONDS",
            services=("webapp", "bot"),
            default="120",
            description="TTL לקאש Uptime (שניות)",
            category="uptime",
        ),
        "ENVIRONMENT": ConfigDefinition(
            key="ENVIRONMENT",
            services=("webapp", "bot", "mcp", "webserver"),
            default="production",
            description="שם הסביבה (production/staging/dev)",
            category="environment",
        ),
        "ENV": ConfigDefinition(
            key="ENV",
            services=("webapp", "bot", "mcp", "webserver"),
            default="production",
            description="שם סביבה מקוצר",
            category="environment",
        ),
        "DEPLOYMENT_TYPE": ConfigDefinition(
            key="DEPLOYMENT_TYPE",
            services=("webapp", "bot", "webserver"),
            default="render",
            description="סוג הפריסה (render/heroku/k8s)",
            category="environment",
        ),
        "HOSTNAME": ConfigDefinition(
            key="HOSTNAME",
            services=("webapp", "bot"),
            default="",
            description="שם ה-Host הנוכחי",
            category="environment",
        ),
        "APP_VERSION": ConfigDefinition(
            key="APP_VERSION",
            services=("webapp", "bot"),
            default="",
            description="גרסת האפליקציה",
            category="versioning",
        ),
        "ASSET_VERSION": ConfigDefinition(
            key="ASSET_VERSION",
            services=("webapp", "bot"),
            default="",
            description="גרסת הנכסים הסטטיים",
            category="versioning",
        ),
        "GIT_COMMIT": ConfigDefinition(
            key="GIT_COMMIT",
            services=("webapp", "bot"),
            default="",
            description="Git Commit Hash",
            category="versioning",
        ),
        "FA_SRI_HASH": ConfigDefinition(
            key="FA_SRI_HASH",
            services=("webapp", "bot"),
            default="",
            description="Hash SRI של FontAwesome",
            category="versioning",
        ),
        "MAINTENANCE_MODE": ConfigDefinition(
            key="MAINTENANCE_MODE",
            services=("webapp", "bot"),
            default="false",
            description="מצב תחזוקה פעיל",
            category="maintenance",
        ),
        "MAINTENANCE_MESSAGE": ConfigDefinition(
            key="MAINTENANCE_MESSAGE",
            services=("webapp", "bot"),
            default="🚀 אנחנו מעלים עדכון חדש!\nהבוט יחזור לפעול ממש בקרוב",
            description="הודעת תחזוקה למשתמשים",
            category="maintenance",
        ),
        "MAINTENANCE_AUTO_WARMUP_SECS": ConfigDefinition(
            key="MAINTENANCE_AUTO_WARMUP_SECS",
            services=("webapp", "bot"),
            default="30",
            description="שניות חימום אחרי תחזוקה",
            category="maintenance",
        ),
        "MAINTENANCE_WARMUP_GRACE_SECS": ConfigDefinition(
            key="MAINTENANCE_WARMUP_GRACE_SECS",
            services=("webapp", "bot"),
            default="0.75",
            description="שניות גרייס נוספות לחימום",
            category="maintenance",
        ),
        "BACKUPS_STORAGE": ConfigDefinition(
            key="BACKUPS_STORAGE",
            services=("bot",),
            default="mongo",
            description="בחירת מנגנון גיבוי: mongo (GridFS) או fs (מערכת קבצים מקומית)",
            category="backups",
        ),
        "BACKUPS_DIR": ConfigDefinition(
            key="BACKUPS_DIR",
            services=("bot",),
            default="/app/backups",
            description="נתיב גיבויים בלוקאל (אם BACKUPS_STORAGE=fs)",
            category="backups",
        ),
        "SKILLS_MAX_PER_USER": ConfigDefinition(
            key="SKILLS_MAX_PER_USER",
            services=("bot",),
            default="100",
            description="מכסת מספר סקילים מרבי למשתמש (0 = בלי מגבלה); לסקילים אין retention",
            category="limits",
        ),
        "SKILLS_MAX_TOTAL_BYTES": ConfigDefinition(
            key="SKILLS_MAX_TOTAL_BYTES",
            services=("bot",),
            default="1073741824",
            description="מכסת נפח סקילים כוללת למשתמש בבייטים (0 = בלי מגבלה); ברירת מחדל 1GB",
            category="limits",
        ),
        "ENCRYPTION_KEY": ConfigDefinition(
            key="ENCRYPTION_KEY",
            services=("webapp", "bot"),
            default="",
            description="מפתח הצפנה לנתונים רגישים (32 בתים)",
            category="security",
            sensitive=True,
        ),
        "PYTEST": ConfigDefinition(
            key="PYTEST",
            services=("webapp", "bot"),
            default="",
            description="דגל pytest פעיל",
            category="testing",
        ),
        "DISABLE_DB": ConfigDefinition(
            key="DISABLE_DB",
            services=("webapp", "bot", "mcp", "webserver"),
            default="",
            description="השבתת DB בטסטים",
            category="testing",
        ),
        "HIGHLIGHT_THEME": ConfigDefinition(
            key="HIGHLIGHT_THEME",
            services=("webapp", "bot", "mcp", "webserver"),
            default="github-dark",
            description="ערכת נושא להדגשת תחביר",
            category="display",
        ),
        "DEFAULT_UI_THEME": ConfigDefinition(
            key="DEFAULT_UI_THEME",
            services=("webapp", "bot"),
            default="classic",
            description="ערכת ברירת מחדל ל-UI ב-WebApp. תומך בערכת builtin או בערכה ציבורית בפורמט shared:<slug> (ללא רווחים).",
            category="display",
        ),
        "DOCUMENTATION_URL": ConfigDefinition(
            key="DOCUMENTATION_URL",
            services=("webapp", "bot"),
            default="https://amirbiron.github.io/CodeBot/",
            description="כתובת אתר התיעוד",
            category="display",
        ),
        "BOT_LABEL": ConfigDefinition(
            key="BOT_LABEL",
            services=("webapp", "bot", "webserver"),
            default="CodeBot",
            description="תווית הבוט בממשק",
            category="display",
        ),
        "CUSTOM_EMOJI_ZIP_ID": ConfigDefinition(
            key="CUSTOM_EMOJI_ZIP_ID",
            services=("bot",),
            default="",
            description="Custom emoji ID לאייקון ZIP בהודעות הבוט (טלגרם פרימיום); ריק = אימוג'י רגיל",
            category="display",
        ),
        "ALERT_EXTERNAL_SERVICES": ConfigDefinition(
            key="ALERT_EXTERNAL_SERVICES",
            services=("webapp", "bot", "mcp", "webserver"),
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
            services=("webapp", "bot", "mcp", "webserver"),
            default="0",
            description="סף מילישניות ללוג \"slow_mongo\" (MongoDB CommandListener)",
            category="database",
        ),
        # --- Query Performance Profiler ---
        "PROFILER_ENABLED": ConfigDefinition(
            key="PROFILER_ENABLED",
            services=("webapp", "bot", "mcp", "webserver"),
            default="true",
            description="הפעלת Query Performance Profiler (true/false). ניתן לנטרול קשיח בקוד דרך DatabaseManager.ENABLE_PROFILING, שערכו כיום True — כלומר ה-ENV הוא שקובע.",
            category="profiler",
        ),
        "PROFILER_SLOW_THRESHOLD_MS": ConfigDefinition(
            key="PROFILER_SLOW_THRESHOLD_MS",
            services=("webapp", "bot", "mcp", "webserver"),
            default="1000",
            description="סף זמן לשאילתה איטית בפרופיילר (מילישניות)",
            category="profiler",
        ),
        "PROFILER_EXPLAIN_MAX_TIME_MS": ConfigDefinition(
            key="PROFILER_EXPLAIN_MAX_TIME_MS",
            services=("webapp", "bot", "mcp", "webserver"),
            default="5000",
            description=(
                "תקרת זמן ל-explain בפרופיילר (מילישניות). רלוונטי בעיקר ל-executionStats "
                "ו-allPlansExecution, שמריצים את השאילתה בפועל"
            ),
            category="profiler",
        ),
        "PROFILER_MAX_BUFFER_SIZE": ConfigDefinition(
            key="PROFILER_MAX_BUFFER_SIZE",
            services=("webapp", "bot", "mcp", "webserver"),
            default="1000",
            description="מספר מקסימלי של רשומות slow queries שנשמרות בזיכרון",
            category="profiler",
        ),
        "PROFILER_UNREDACTED_USER_IDS": ConfigDefinition(
            key="PROFILER_UNREDACTED_USER_IDS",
            services=("webapp", "bot", "mcp", "webserver"),
            default="",
            description=(
                "מזהי משתמשים (CSV) שהשאילתות האיטיות שלהם נשמרות ב-slow_queries_log גם עם "
                "הערכים האמיתיים (query_raw), לצד השלד המנורמל. ריק = כבוי. חל רק על שאילתה "
                "שמצהירה על user_id יחיד מהרשימה ומכילה שדות מוכרים בלבד; כל דחייה נרשמת "
                "ב-raw_withheld_reason"
            ),
            category="profiler",
        ),
        "PROFILER_UNREDACTED_MAX_BYTES": ConfigDefinition(
            key="PROFILER_UNREDACTED_MAX_BYTES",
            services=("webapp", "bot", "mcp", "webserver"),
            default="8192",
            description="תקרת גודל (בייטים, JSON) לשאילתה שנשמרת עם ערכים אמיתיים; מעבר לה נשמר רק השלד",
            category="profiler",
        ),
        "PROFILER_AUTH_TOKEN": ConfigDefinition(
            key="PROFILER_AUTH_TOKEN",
            services=("webapp", "bot", "webserver"),
            default="",
            description="טוקן גישה ל-API של הפרופיילר (X-Profiler-Token)",
            category="profiler",
            sensitive=True,
        ),
        "PROFILER_ALLOWED_IPS": ConfigDefinition(
            key="PROFILER_ALLOWED_IPS",
            services=("webapp", "bot", "webserver"),
            default="",
            description="Allowlist של כתובות IP מורשות ל-API של הפרופיילר (CSV)",
            category="profiler",
        ),
        "PROFILER_RATE_LIMIT": ConfigDefinition(
            key="PROFILER_RATE_LIMIT",
            services=("webapp", "bot", "webserver"),
            default="60",
            description="מגבלת בקשות לדקה ל-endpoints של הפרופיילר (Rate Limiting)",
            category="profiler",
        ),
        "PROFILER_METRICS_ENABLED": ConfigDefinition(
            key="PROFILER_METRICS_ENABLED",
            services=("webapp", "bot", "mcp", "webserver"),
            default="true",
            description="הפעלת מטריקות Prometheus לפרופיילר",
            category="profiler",
        ),
        # --- Diagnostics / sanity checks ---
        "SANITY_USER_ID": ConfigDefinition(
            key="SANITY_USER_ID",
            services=("scripts",),
            default="123",
            description="משתנה עזר לסקריפט scripts/db_manager_sanity_check.py (לא משפיע על ריצה רגילה)",
            category="dev",
        ),
        "DRILLS_COLLECTION": ConfigDefinition(
            key="DRILLS_COLLECTION",
            services=("webapp", "bot", "webserver"),
            default="drill_history",
            description="שם הקולקשן שבו נשמרת היסטוריית Drill Mode (תרגולים).",
            category="drills",
        ),
        "DRILLS_DB_ENABLED": ConfigDefinition(
            key="DRILLS_DB_ENABLED",
            services=("webapp", "bot", "webserver"),
            default="",
            description="מפעיל שמירת היסטוריית Drill ב-MongoDB (ברירת מחדל נסמכת על ``ALERTS_DB_ENABLED``/``METRICS_DB_ENABLED``).",
            category="drills",
        ),
        "DRILLS_TTL_DAYS": ConfigDefinition(
            key="DRILLS_TTL_DAYS",
            services=("webapp", "bot", "webserver"),
            default="90",
            description="כמה ימים נשמרת היסטוריית Drill לפני מחיקה אוטומטית (TTL index).",
            category="drills",
        ),
        "DRILL_MODE_ENABLED": ConfigDefinition(
            key="DRILL_MODE_ENABLED",
            services=("webapp", "bot", "webserver"),
            default="false",
            description="מפעיל Drill Mode (תרגולים) ב-WebApp/API. כאשר כבוי, ``/api/observability/drills/run`` יחזיר ``drill_disabled``.",
            category="drills",
        ),
        "DUMMY_BOT_TOKEN": ConfigDefinition(
            key="DUMMY_BOT_TOKEN",
            services=("bot",),
            default="dummy_token",
            description="טוקן בדיקה שמשמש סביבות שבהן אין צורך להתחבר לטלגרם (למשל docs build).",
            category="general",
            sensitive=True,
        ),
        "ENABLE_INTERNAL_SHARE_WEB": ConfigDefinition(
            key="ENABLE_INTERNAL_SHARE_WEB",
            services=("bot",),
            default="false",
            description="הפעלת שירות שיתוף פנימי",
            category="features",
        ),
        "HTTP_SAMPLE_RETENTION_SECONDS": ConfigDefinition(
            key="HTTP_SAMPLE_RETENTION_SECONDS",
            services=("webapp", "bot", "mcp", "webserver"),
            default="600",
            description="זמן שמירת הדגימות (שניות) לפני שמנקים אותן.",
            category="http",
        ),
        "HTTP_SLOW_MS": ConfigDefinition(
            key="HTTP_SLOW_MS",
            services=("webapp", "bot", "mcp", "webserver"),
            default="0",
            description="סף מילישניות ללוג \"slow_http\" ב‑http_sync (requests)",
            category="http",
        ),
        "OBS_AI_EXPLAIN_TOKEN": ConfigDefinition(
            key="OBS_AI_EXPLAIN_TOKEN",
            services=("webapp", "bot", "mcp", "webserver"),
            default="",
            description="אסימון Bearer שנשלח ב-Header ``Authorization`` כאשר השירות מוגן (אופציונלי).",
            category="observability",
            sensitive=True,
        ),
        "OBS_AI_EXPLAIN_URL": ConfigDefinition(
            key="OBS_AI_EXPLAIN_URL",
            services=("webapp", "bot", "mcp", "webserver"),
            default="",
            description="Endpoint לשירות ההסבר החכם של הדשבורד (מקבל ``POST`` עם ``context`` ומחזיר ``root_cause``/``actions``/``signals``). בפריסה מאוחדת (WebApp + AI Explain באותו קונטיינר) זה לרוב ``http://127.0.0.1:11000/api/ai/explain``.",
            category="observability",
            sensitive=True,
        ),
        "OBS_AI_EXPLAIN_INTERNAL_PORT": ConfigDefinition(
            key="OBS_AI_EXPLAIN_INTERNAL_PORT",
            default="11000",
            description="פורט פנימי לשירות ה-AI Explain כאשר הוא רץ באותו קונטיינר עם ה-WebApp (למשל דרך ``scripts/run_all.sh``).",
            category="observability",
        ),
        "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": ConfigDefinition(
            key="OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
            services=("webapp", "bot"),
            default="",
            description="כתובת ייעודית למטריקות OTLP (אם שונה מה-endpoint הראשי).",
            category="monitoring",
        ),
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": ConfigDefinition(
            key="OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
            services=("webapp", "bot"),
            default="",
            description="כתובת ייעודית ל-traces OTLP.",
            category="monitoring",
        ),
        "JOBS_STUCK_THRESHOLD_MINUTES": ConfigDefinition(
            key="JOBS_STUCK_THRESHOLD_MINUTES",
            services=("bot",),
            default="20",
            description="סף (בדקות) לזיהוי הרצות Jobs תקועות והפקת אירוע job_stuck.",
            category="jobs_monitor",
        ),
        "JOBS_STUCK_MONITOR_INTERVAL_SECS": ConfigDefinition(
            key="JOBS_STUCK_MONITOR_INTERVAL_SECS",
            services=("webapp", "bot", "webserver"),
            default="60",
            description="תדירות (שניות) של מוניטור Jobs תקועות (job_stuck).",
            category="jobs_monitor",
        ),
        "JOB_TRIGGERS_POLL_INTERVAL_SECS": ConfigDefinition(
            key="JOB_TRIGGERS_POLL_INTERVAL_SECS",
            services=("webapp", "bot", "webserver"),
            default="60",
            description="תדירות polling (שניות) של processor בבוט שמטפל בבקשות trigger שנוצרו מה-WebApp (job_trigger_requests). מינימום 60.",
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
            services=("webapp", "bot"),
            default="true",
            description="מתג כללי להצגת רכיב ההכרזות (on/off)",
            category="features",
        ),
        "FEATURE_CODE_EXECUTION": ConfigDefinition(
            key="FEATURE_CODE_EXECUTION",
            services=("webapp", "bot"),
            default="false",
            description="הפעלת הרצת קוד (Playground) ב-WebApp: /api/code/run",
            category="features",
        ),
        "FEATURE_COLLECTIONS_TAGS": ConfigDefinition(
            key="FEATURE_COLLECTIONS_TAGS",
            services=("webapp", "bot"),
            default="true",
            description="הפעלת תגיות לפריטים ב'אוספים שלי' (API/UI)",
            category="features",
        ),
        "CODE_EXEC_USE_DOCKER": ConfigDefinition(
            key="CODE_EXEC_USE_DOCKER",
            services=("webapp", "bot", "webserver"),
            default="true",
            description="האם להריץ קוד בתוך Docker sandbox (מומלץ/חובה בפרודקשן)",
            category="code_execution",
        ),
        "CODE_EXEC_ALLOW_FALLBACK": ConfigDefinition(
            key="CODE_EXEC_ALLOW_FALLBACK",
            services=("webapp", "bot", "webserver"),
            default="false",
            description="אם true מאפשר fallback ל-subprocess (לפיתוח בלבד; בפרודקשן מומלץ false=fail-closed)",
            category="code_execution",
        ),
        "CODE_EXEC_MAX_TIMEOUT": ConfigDefinition(
            key="CODE_EXEC_MAX_TIMEOUT",
            services=("webapp", "bot", "webserver"),
            default="30",
            description="timeout מקסימלי להרצת קוד (שניות)",
            category="code_execution",
        ),
        "CODE_EXEC_MAX_MEMORY_MB": ConfigDefinition(
            key="CODE_EXEC_MAX_MEMORY_MB",
            services=("webapp", "bot", "webserver"),
            default="128",
            description="זיכרון מקסימלי להרצת קוד (MB)",
            category="code_execution",
        ),
        "CODE_EXEC_MAX_OUTPUT_BYTES": ConfigDefinition(
            key="CODE_EXEC_MAX_OUTPUT_BYTES",
            services=("webapp", "bot", "webserver"),
            default="102400",
            description="כמות מקסימלית של stdout/stderr (bytes) לפני עצירה/קיצוץ",
            category="code_execution",
        ),
        "CODE_EXEC_MAX_CODE_LENGTH": ConfigDefinition(
            key="CODE_EXEC_MAX_CODE_LENGTH",
            services=("webapp", "bot", "webserver"),
            default="51200",
            description="אורך קוד מקסימלי (bytes) שמותר לשלוח להרצה",
            category="code_execution",
        ),
        "CODE_EXEC_DOCKER_IMAGE": ConfigDefinition(
            key="CODE_EXEC_DOCKER_IMAGE",
            services=("webapp", "bot", "webserver"),
            default="python:3.11-slim",
            description="Docker image להרצת קוד (למשל python:3.11-slim)",
            category="code_execution",
        ),
        "EMBEDDING_MIN_INTERVAL_SECONDS": ConfigDefinition(
            key="EMBEDDING_MIN_INTERVAL_SECONDS",
            services=("webapp", "bot", "webserver"),
            default="1.2",
            description="מרווח מינימלי (שניות) בין קריאות ל-Gemini Embeddings (שער גלובלי)",
            category="ai",
        ),
        "EMBEDDING_RATE_LIMIT_COOLDOWN_SECONDS": ConfigDefinition(
            key="EMBEDDING_RATE_LIMIT_COOLDOWN_SECONDS",
            services=("webapp", "bot", "webserver"),
            default="30",
            description="Cooldown גלובלי (שניות) שמוחל על כל הקוראים לאחר HTTP 429",
            category="ai",
        ),
        "EMBEDDING_WORKER_BATCH_SIZE": ConfigDefinition(
            key="EMBEDDING_WORKER_BATCH_SIZE",
            services=("bot",),
            default="5",
            description="כמות snippets שה-embedding worker מעבד בכל סבב",
            category="ai",
        ),
        "EMBEDDING_WORKER_POLL_INTERVAL": ConfigDefinition(
            key="EMBEDDING_WORKER_POLL_INTERVAL",
            services=("bot",),
            default="300",
            description="זמן המתנה (שניות) בין סריקות של ה-embedding worker כשהתור ריק",
            category="ai",
        ),
        "EMBEDDING_WORKER_BATCH_COOLDOWN": ConfigDefinition(
            key="EMBEDDING_WORKER_BATCH_COOLDOWN",
            services=("bot",),
            default="30",
            description="זמן המתנה (שניות) בין באצ'ים שעובדו בהצלחה",
            category="ai",
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

        # מיסוך מבוסס-ערך: URL עם credentials מוטמעים (user:pass@) הוא סוד גם אם השם אינו רגיש
        if _CREDENTIAL_URL_RE.search(value):
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

    def _normalize_value(self, value: Any) -> str:
        """המרת ערך "ריק לכל דבר" למחרוזת ריקה, לקראת תצוגה.

        קיים כדי שהכלל "מה נחשב ריק" יחיה במקום אחד. determine_status כבר
        מתייחס לרווחים בלבד כאל ריק דרך _is_empty_value, ובלי הנרמול הזה
        התצוגה סותרת את הסטטוס: שדה שסומן כריק נראה כאילו יש בו ערך —
        ובמשתנה רגיש, כאילו יש בו סוד.

        Args:
            value: הערך לנרמול

        Returns:
            הערך כמחרוזת, או "" אם הוא ריק
        """

        return "" if self._is_empty_value(value) else str(value)

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

        # יש ערך בסביבה כשאין ברירת מחדל בקוד — המשתנה "הוגדר" (למשל ברנדר),
        # לא "שונה": אין דיפולט שממנו אפשר לסטות (למשל GITHUB_TOKENS, MCP_SERVER_URL)
        if default_is_empty:
            return ConfigStatus.SET

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
        active_value = self._normalize_value(
            env_value if env_value is not None else default
        )

        # הסתרת ערכים רגישים - גם active וגם default!
        is_sensitive = self.is_sensitive_key(key) or definition.sensitive
        display_value = self.mask_value(active_value, key) if is_sensitive else active_value

        # הסתרת ערך ברירת מחדל אם רגיש (למניעת חשיפת credentials בדיפולטים)
        default_str = self._normalize_value(default)
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
            # עמוד ראשי: רק משתנים ששייכים (גם) לשירות ה-webapp — ה-inspector רץ
            # בתהליך ה-webapp ולכן Status/Active Value של שירותים אחרים יהיו מטעים
            if "webapp" not in definition.services:
                continue
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
        set_count = sum(1 for e in entries if e.status == ConfigStatus.SET)
        missing_count = sum(1 for e in entries if e.status == ConfigStatus.MISSING)
        default_count = sum(1 for e in entries if e.status == ConfigStatus.DEFAULT)

        return ConfigOverview(
            entries=entries,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            total_count=len(entries),
            modified_count=modified_count,
            set_count=set_count,
            missing_count=missing_count,
            default_count=default_count,
            categories=sorted(categories_set),
        )

    def get_other_services_entries(self) -> List[Dict[str, Any]]:
        """משתנים ששייכים לשירותים שאינם webapp (bot/mcp/webserver/scripts) — עמוד 2.

        כולל גם משתנים משותפים (שמופיעים בנוסף בעמוד ה-webapp) — כל שורה מציינת
        לאילו שירותים היא מתייחסת. בלי Status ובלי Active Value: הערכים חיים
        בתהליכים אחרים (שירותי Render נפרדים) ואינם נגישים מכאן.
        """
        rows: List[Dict[str, Any]] = []
        for definition in self.CONFIG_DEFINITIONS.values():
            other = [s for s in definition.services if s != "webapp"]
            if not other:
                continue
            default_str = self._normalize_value(definition.default)
            is_sensitive = self.is_sensitive_key(definition.key) or definition.sensitive
            rows.append({
                "key": definition.key,
                "service": " + ".join(other),
                "also_webapp": "webapp" in definition.services,
                "category": definition.category,
                "default_value": self.mask_value(default_str, definition.key) if is_sensitive else default_str,
                "description": definition.description,
                "is_sensitive": is_sensitive,
            })
        rows.sort(key=lambda r: (r["service"], r["category"], r["key"]))
        return rows

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
                summary[cat] = {"total": 0, "modified": 0, "set": 0, "missing": 0, "default": 0}

            summary[cat]["total"] += 1
            if entry.status == ConfigStatus.MODIFIED:
                summary[cat]["modified"] += 1
            elif entry.status == ConfigStatus.SET:
                summary[cat]["set"] += 1
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
            # משתנה שלא שייך ל-webapp לא נבדק כאן — הערך שלו לא בסביבת ה-webapp
            if "webapp" not in definition.services:
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

