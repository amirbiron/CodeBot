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
    CONFIG_DEFINITIONS: Dict[str, ConfigDefinition] = {
        # ========== Database ==========
        "MONGODB_URI": ConfigDefinition(
            key="MONGODB_URI",
            default="mongodb://localhost:27017/codebot",
            description="כתובת חיבור למסד הנתונים MongoDB",
            category="database",
            sensitive=True,
            required=True,
        ),
        "MONGODB_MIN_POOL_SIZE": ConfigDefinition(
            key="MONGODB_MIN_POOL_SIZE",
            default="5",
            description="מספר חיבורים מינימלי לפול",
            category="database",
        ),
        "MONGODB_MAX_POOL_SIZE": ConfigDefinition(
            key="MONGODB_MAX_POOL_SIZE",
            default="20",
            description="מספר חיבורים מקסימלי לפול",
            category="database",
        ),
        "DB_TIMEOUT_MS": ConfigDefinition(
            key="DB_TIMEOUT_MS",
            default="5000",
            description="זמן המתנה מקסימלי לפעולות DB (מילישניות)",
            category="database",
        ),
        # ========== API Settings ==========
        "API_TIMEOUT": ConfigDefinition(
            key="API_TIMEOUT",
            default="30",
            description="זמן מקסימלי לבקשות API (שניות)",
            category="api",
        ),
        "API_RATE_LIMIT": ConfigDefinition(
            key="API_RATE_LIMIT",
            default="100",
            description="מספר בקשות מקסימלי לדקה",
            category="api",
        ),
        "API_MAX_RETRIES": ConfigDefinition(
            key="API_MAX_RETRIES",
            default="3",
            description="מספר ניסיונות חוזרים בכישלון",
            category="api",
        ),
        # ========== Telegram Bot ==========
        "TELEGRAM_BOT_TOKEN": ConfigDefinition(
            key="TELEGRAM_BOT_TOKEN",
            default="",
            description="טוקן הבוט של טלגרם",
            category="telegram",
            sensitive=True,
            required=True,
        ),
        "TELEGRAM_ADMIN_CHAT_ID": ConfigDefinition(
            key="TELEGRAM_ADMIN_CHAT_ID",
            default="",
            description="מזהה הצ'אט של האדמין",
            category="telegram",
            sensitive=True,
        ),
        "TELEGRAM_WEBHOOK_URL": ConfigDefinition(
            key="TELEGRAM_WEBHOOK_URL",
            default="",
            description="כתובת ה-Webhook לטלגרם",
            category="telegram",
        ),
        # ========== External Services ==========
        "OPENAI_API_KEY": ConfigDefinition(
            key="OPENAI_API_KEY",
            default="",
            description="מפתח API ל-OpenAI",
            category="external",
            sensitive=True,
        ),
        "SENTRY_DSN": ConfigDefinition(
            key="SENTRY_DSN",
            default="",
            description="DSN ל-Sentry לניטור שגיאות",
            category="external",
            sensitive=True,
        ),
        "GITHUB_TOKEN": ConfigDefinition(
            key="GITHUB_TOKEN",
            default="",
            description="טוקן גישה ל-GitHub",
            category="external",
            sensitive=True,
        ),
        "GOOGLE_DRIVE_CREDENTIALS": ConfigDefinition(
            key="GOOGLE_DRIVE_CREDENTIALS",
            default="",
            description="נתיב לקובץ credentials של Google Drive",
            category="external",
            sensitive=True,
        ),
        # ========== Web Server ==========
        "WEB_HOST": ConfigDefinition(
            key="WEB_HOST",
            default="0.0.0.0",
            description="כתובת ה-Host לשרת הווב",
            category="webserver",
        ),
        "WEB_PORT": ConfigDefinition(
            key="WEB_PORT",
            default="8080",
            description="פורט השרת",
            category="webserver",
        ),
        "WEB_SECRET_KEY": ConfigDefinition(
            key="WEB_SECRET_KEY",
            default="",
            description="מפתח סודי לסשנים",
            category="webserver",
            sensitive=True,
            required=True,
        ),
        "WEB_DEBUG": ConfigDefinition(
            key="WEB_DEBUG",
            default="false",
            description="מצב דיבאג (true/false)",
            category="webserver",
        ),
        "WEB_WORKERS": ConfigDefinition(
            key="WEB_WORKERS",
            default="4",
            description="מספר Worker processes",
            category="webserver",
        ),
        # ========== Caching ==========
        "REDIS_URL": ConfigDefinition(
            key="REDIS_URL",
            default="",
            description="כתובת Redis לקאש",
            category="cache",
            sensitive=True,
        ),
        "CACHE_TTL_SECONDS": ConfigDefinition(
            key="CACHE_TTL_SECONDS",
            default="3600",
            description="זמן חיים לקאש (שניות)",
            category="cache",
        ),
        "CACHE_MAX_SIZE": ConfigDefinition(
            key="CACHE_MAX_SIZE",
            default="1000",
            description="גודל מקסימלי של הקאש",
            category="cache",
        ),
        # ========== Logging & Monitoring ==========
        "LOG_LEVEL": ConfigDefinition(
            key="LOG_LEVEL",
            default="INFO",
            description="רמת הלוגים (DEBUG/INFO/WARNING/ERROR)",
            category="logging",
        ),
        "LOG_FORMAT": ConfigDefinition(
            key="LOG_FORMAT",
            default="json",
            description="פורמט הלוגים (json/text)",
            category="logging",
        ),
        "ENABLE_METRICS": ConfigDefinition(
            key="ENABLE_METRICS",
            default="true",
            description="הפעלת מטריקות Prometheus",
            category="logging",
        ),
        # ========== Features ==========
        "FEATURE_AI_EXPLAIN": ConfigDefinition(
            key="FEATURE_AI_EXPLAIN",
            default="true",
            description="הפעלת הסברי AI",
            category="features",
        ),
        "FEATURE_CODE_SHARING": ConfigDefinition(
            key="FEATURE_CODE_SHARING",
            default="true",
            description="הפעלת שיתוף קוד",
            category="features",
        ),
        "FEATURE_IMAGE_GENERATION": ConfigDefinition(
            key="FEATURE_IMAGE_GENERATION",
            default="true",
            description="הפעלת יצירת תמונות קוד",
            category="features",
        ),
        # ========== Limits ==========
        "MAX_FILE_SIZE_MB": ConfigDefinition(
            key="MAX_FILE_SIZE_MB",
            default="10",
            description="גודל קובץ מקסימלי (MB)",
            category="limits",
        ),
        "MAX_CODE_LINES": ConfigDefinition(
            key="MAX_CODE_LINES",
            default="5000",
            description="מספר שורות קוד מקסימלי",
            category="limits",
        ),
        "MAX_SNIPPETS_PER_USER": ConfigDefinition(
            key="MAX_SNIPPETS_PER_USER",
            default="500",
            description="מספר סניפטים מקסימלי למשתמש",
            category="limits",
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

