"""
services/shared_theme_service.py
שירות לניהול ערכות נושא ציבוריות (Shared Theme Library)

מימוש לפי GUIDES/SHARED_THEME_LIBRARY_GUIDE.md
עם התאמה לקוד הקיים (Theme Builder / VS Code Import):
- תמיכה ב-syntax_css (CSS לצביעת קוד)
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from services.theme_parser_service import (
    ALLOWED_VARIABLES_WHITELIST,
    SanitizedSyntaxCss,
    is_valid_color,
    sanitize_syntax_css,
)

logger = logging.getLogger(__name__)

# Regex לבדיקת slug תקין (אותיות קטנות, מספרים, קו תחתון)
VALID_SLUG_REGEX = re.compile(r"^[a-z][a-z0-9_]{2,29}$")

# blur יכול להיות ערך px (כמו בקוד הקיים של Themes API)
_VALID_PX_REGEX = re.compile(r"^\d{1,3}(\.\d{1,2})?px$")

MAX_NAME_LENGTH = 50
MAX_DESCRIPTION_LENGTH = 200

#: התקרה על ``syntax_css`` שנשלח לפרסום או לעדכון, בתווים. מעליה הבקשה נדחית ב-``syntax_css_too_long`` — לא נחתכת:
#: חיתוך באמצע היה משאיר כלל קטוע ונשמר כאילו הצליח. המספר הוא פעמיים ה-``syntax_css`` ש-``parse_vscode_theme``
#: מייצר היום לערכה שנותנת לכל scope שבשלוש מפות המחוללים צבע ``rgba`` באורך 26 תווים (ארוך מכל צבע hex של VS Code)
#: ואת כל הסגנונות: 18,359 תווים ב-9.11.2026. ``test_max_syntax_css_length_is_twice_the_largest_generated_css``
#: (``tests/services/test_sanitize_syntax_css.py``) מחשב אותו מחדש ונכשל כשהמחוללים גדלים מעבר למחצית התקרה.
MAX_SYNTAX_CSS_LENGTH = 36_718


class SharedThemeWriteResult(NamedTuple):
    """התוצאה של ``create`` / ``update``.

    ``result`` — ה-slug בהצלחה של ``create``, ``"ok"`` בהצלחה של ``update``, או קוד השגיאה. ``syntax_rules_dropped`` —
    כמה כללים ב-``syntax_css`` שנשלח לא עברו את ``sanitize_syntax_css`` (אפס כשלא נשלח ``syntax_css``).
    """

    ok: bool
    result: str
    syntax_rules_dropped: int = 0


# ערכות מובנות (Built-in) – קבועות בקוד (זהות למדריך)
BUILTIN_THEMES: List[Dict[str, str]] = [
    {"id": "classic", "name": "קלאסי", "type": "builtin"},
    {"id": "ocean", "name": "אוקיינוס", "type": "builtin"},
    {"id": "nebula", "name": "Nebula", "type": "builtin"},
    {"id": "dark", "name": "כהה", "type": "builtin"},
    {"id": "dim", "name": "עמום", "type": "builtin"},
    {"id": "rose-pine-dawn", "name": "Rose Pine Dawn", "type": "builtin"},
    {"id": "high-contrast", "name": "ניגודיות גבוהה", "type": "builtin"},
]

_PREVIEW_COLOR_KEYS: Tuple[str, ...] = (
    "--bg-primary",
    "--bg-secondary",
    "--primary",
    "--secondary",
    "--text-primary",
    "--card-bg",
)
_PREVIEW_FALLBACK = ["#1a1b26", "#7aa2f7", "#bb9af7", "#f7768e"]


def _extract_preview_colors(variables: Dict[str, Any]) -> List[str]:
    if not isinstance(variables, dict):
        return list(_PREVIEW_FALLBACK)
    colors: List[str] = []
    for key in _PREVIEW_COLOR_KEYS:
        raw = variables.get(key)
        if raw is None:
            continue
        try:
            value = str(raw).strip()
        except Exception:
            continue
        if not value or not is_valid_color(value):
            continue
        colors.append(value)
        if len(colors) >= 4:
            break
    if len(colors) < 4:
        for fallback in _PREVIEW_FALLBACK:
            if len(colors) >= 4:
                break
            if fallback not in colors:
                colors.append(fallback)
    return colors[:4]


class SharedThemeService:
    """שירות לניהול ערכות נושא ציבוריות."""

    def __init__(self, db):
        """
        Args:
            db: אובייקט DB בסגנון PyMongo (חייב להכיל shared_themes collection)
        """
        self.db = db
        self.collection = getattr(db, "shared_themes", None)
        # ==========================
        # In-memory cache (active themes list)
        # ==========================
        self._active_themes_cache: Optional[List[Dict[str, Any]]] = None
        self._active_themes_expires_at: Optional[datetime] = None
        self._cache_ttl_seconds = 300  # 5 minutes
        # מונה "גרסה" כדי למנוע דריסת invalidate ע"י כתיבה מאוחרת מ-thread אחר
        self._active_themes_cache_version = 0

        # Optional: best-effort index creation (safe if unsupported)
        self.ensure_indexes()

    def invalidate_cache(self) -> None:
        """איפוס cache (יש לקרוא אחרי create/update/delete)."""
        # קודם מעלים גרסה כדי שכל fetch שמתקדם במקביל לא יכתוב cache "ישן"
        self._active_themes_cache_version += 1
        self._active_themes_cache = None
        self._active_themes_expires_at = None

    def ensure_indexes(self) -> None:
        """יוצר אינדקסים בסיסיים לשיפור ביצועים (best-effort)."""
        if self.collection is None:
            return
        try:
            create_index = getattr(self.collection, "create_index", None)
            if not callable(create_index):
                return
            # Compound index for is_active + order + created_at
            create_index([("is_active", 1), ("order", 1), ("created_at", -1)])
        except Exception as e:
            # לא שוברים את האפליקציה/טסטים בגלל אינדקסים
            logger.debug("SharedThemeService.ensure_indexes failed: %s", e)

    # ============= Validation =============

    def _validate_slug(self, slug: str) -> bool:
        if not slug or not isinstance(slug, str):
            return False
        return bool(VALID_SLUG_REGEX.match(slug.strip()))

    def _validate_theme_value(self, var_name: str, value: str) -> bool:
        """ולידציה בטוחה לערכי CSS variables (כמו Themes API הקיים)."""
        if not var_name or not isinstance(var_name, str):
            return False
        if value is None or not isinstance(value, str):
            return False
        v = value.strip()
        if not v:
            return False
        if var_name == "--glass-blur":
            return bool(_VALID_PX_REGEX.match(v.lower()))
        return is_valid_color(v)

    def _filter_and_validate_colors(self, colors: Dict[str, Any]) -> Tuple[bool, Dict[str, str], Optional[str]]:
        """
        מסנן רק משתנים מותרים + בודק ערכים.

        Returns:
            (ok, filtered, error_field)
        """
        if not isinstance(colors, dict):
            return False, {}, "colors_not_dict"

        filtered: Dict[str, str] = {}
        for var_name, var_value in colors.items():
            if not isinstance(var_name, str):
                continue
            if var_name not in ALLOWED_VARIABLES_WHITELIST:
                continue
            val = str(var_value).strip()
            if not self._validate_theme_value(var_name, val):
                return False, {}, var_name
            filtered[var_name] = val

        return True, filtered, None

    def _normalize_syntax_css(
        self, syntax_css: Any
    ) -> Tuple[Optional[SanitizedSyntaxCss], Optional[str]]:
        """``syntax_css`` מהבקשה, מנוקה לשמירה: ``(תוצאה, None)``, או ``(None, קוד שגיאה)``.

        ``None`` — לא נשלח CSS, ונשמר ריק. סוג שאינו מחרוזת ← ``invalid_syntax_css``, ומעל ``MAX_SYNTAX_CSS_LENGTH`` ←
        ``syntax_css_too_long``: שניהם נדחים ולא נשמרים כ-CSS ריק או קטוע. הניקוי עצמו (``sanitize_syntax_css``) הוא
        עיבוד מחרוזת בלבד, ולכן אינו עטוף: חריגה ממנו היא באג, והיא עולה.
        """
        if syntax_css is None:
            return SanitizedSyntaxCss("", 0), None
        if not isinstance(syntax_css, str):
            return None, "invalid_syntax_css"
        css = syntax_css.strip()
        if len(css) > MAX_SYNTAX_CSS_LENGTH:
            return None, "syntax_css_too_long"
        return sanitize_syntax_css(css), None

    @staticmethod
    def _log_dropped_syntax_rules(theme_id: str, dropped: int) -> None:
        if dropped:
            logger.warning(
                "Shared theme %s: %d syntax_css rules did not pass sanitize_syntax_css and were not saved",
                theme_id,
                dropped,
            )

    # ============= CRUD Operations =============

    def get_all_active(self) -> List[Dict[str, Any]]:
        """קבלת כל הערכות הפעילות (מטא-דאטה בלבד)."""
        if self.collection is None:
            return []
        now = datetime.now(timezone.utc)
        # העתקה למשתנים מקומיים כדי להימנע מקריסה אם invalidate מתרחש באמצע (race)
        cached_themes = self._active_themes_cache
        cached_expires_at = self._active_themes_expires_at

        # Cache hit
        if (
            cached_themes is not None
            and cached_expires_at is not None
            and cached_expires_at > now
        ):
            # מחזירים עותק כדי למנוע "השחתה" של ה-cache ע"י קוראים שמשנים את הרשימה/מילונים
            return [t.copy() for t in cached_themes]

        # Cache miss: זוכרים את הגרסה הנוכחית כדי לא לדרוס invalidate שהתרחש בזמן ה-fetch
        version_at_start = self._active_themes_cache_version
        try:
            cursor = self.collection.find(
                {"is_active": True},
                {
                    "_id": 1,
                    "name": 1,
                    "description": 1,
                    "is_featured": 1,
                    "created_at": 1,
                    "order": 1,
                    "colors": 1,
                },
            ).sort([("order", 1), ("created_at", -1)])

            themes: List[Dict[str, Any]] = []
            for doc in cursor:
                created_at = doc.get("created_at")
                theme_id = doc.get("_id")
                colors = doc.get("colors", {})
                if not isinstance(colors, dict):
                    colors = {}
                preview_colors = _extract_preview_colors(colors)
                themes.append(
                    {
                        # ⚠️ JSON safety: ObjectId לא תמיד סיריאליזבילי, אז ממירים ל-str
                        "id": str(theme_id) if theme_id is not None else None,
                        "name": doc.get("name"),
                        "description": doc.get("description", ""),
                        "is_featured": bool(doc.get("is_featured", False)),
                        "created_at": created_at.isoformat() if isinstance(created_at, datetime) else None,
                        "type": "shared",
                        "preview_colors": preview_colors,
                    }
                )
            # Save to cache
            if version_at_start == self._active_themes_cache_version:
                self._active_themes_cache = themes
                self._active_themes_expires_at = now + timedelta(seconds=self._cache_ttl_seconds)
            # מחזירים עותק כדי לשמור על התנהגות עקבית (גם ב-cache miss)
            return [t.copy() for t in themes]
        except Exception as e:
            logger.exception("SharedThemeService.get_all_active failed: %s", e)
            return []

    def get_by_id(self, theme_id: str) -> Optional[Dict[str, Any]]:
        """קבלת ערכה ספציפית לפי ID (כולל colors + syntax_css)."""
        if not theme_id or self.collection is None:
            return None
        try:
            doc = self.collection.find_one({"_id": str(theme_id), "is_active": True})
            if not doc:
                return None

            colors = doc.get("colors", {})
            if not isinstance(colors, dict):
                colors = {}
            syntax_css = doc.get("syntax_css", "")
            if not isinstance(syntax_css, str):
                syntax_css = ""
            syntax_colors = doc.get("syntax_colors", {})
            if not isinstance(syntax_colors, dict):
                syntax_colors = {}

            created_at = doc.get("created_at")
            return {
                "id": doc.get("_id"),
                "name": doc.get("name"),
                "description": doc.get("description", ""),
                "colors": colors,
                "syntax_css": syntax_css,
                "syntax_colors": syntax_colors,
                "is_featured": bool(doc.get("is_featured", False)),
                "created_by": doc.get("created_by"),
                "created_at": created_at.isoformat() if isinstance(created_at, datetime) else None,
                "type": "shared",
            }
        except Exception as e:
            logger.exception("SharedThemeService.get_by_id failed: %s", e)
            return None

    def create(
        self,
        *,
        slug: str,
        name: str,
        colors: Dict[str, Any],
        created_by: int,
        description: str = "",
        is_featured: bool = False,
        syntax_css: Optional[str] = None,
        syntax_colors: Optional[Dict[str, Any]] = None,
    ) -> SharedThemeWriteResult:
        """יצירת ערכה ציבורית חדשה."""
        if self.collection is None:
            return SharedThemeWriteResult(False, "database_unavailable")

        slug = (slug or "").strip().lower()
        if not self._validate_slug(slug):
            return SharedThemeWriteResult(False, "invalid_slug")

        name = (name or "").strip()
        if not name:
            return SharedThemeWriteResult(False, "missing_name")
        if len(name) > MAX_NAME_LENGTH:
            return SharedThemeWriteResult(False, "name_too_long")

        ok, filtered_colors, error_field = self._filter_and_validate_colors(colors)
        if not ok:
            if error_field and error_field != "colors_not_dict":
                return SharedThemeWriteResult(False, f"invalid_color:{error_field}")
            return SharedThemeWriteResult(False, "invalid_colors")

        clean_syntax, syntax_error = self._normalize_syntax_css(syntax_css)
        if clean_syntax is None:
            return SharedThemeWriteResult(False, syntax_error or "invalid_syntax_css")

        # בדיקת slug תפוס
        try:
            existing = self.collection.find_one({"_id": slug})
            if existing:
                return SharedThemeWriteResult(False, "slug_exists")
        except Exception as e:
            logger.exception("SharedThemeService.create existing check failed: %s", e)
            return SharedThemeWriteResult(False, "database_error")

        now = datetime.now(timezone.utc)
        doc: Dict[str, Any] = {
            "_id": slug,
            "name": name,
            "description": (description or "").strip()[:MAX_DESCRIPTION_LENGTH],
            "colors": filtered_colors,
            "syntax_css": clean_syntax.css,
            "syntax_colors": syntax_colors if isinstance(syntax_colors, dict) else {},
            "created_by": int(created_by),
            "created_at": now,
            "updated_at": now,
            "is_active": True,
            "is_featured": bool(is_featured),
            "order": 0,
        }

        try:
            self.collection.insert_one(doc)
            self.invalidate_cache()
            logger.info("Created shared theme %s by user %s", slug, created_by)
        except Exception as e:
            logger.exception("SharedThemeService.create failed: %s", e)
            return SharedThemeWriteResult(False, "database_error")
        self._log_dropped_syntax_rules(slug, clean_syntax.dropped)
        return SharedThemeWriteResult(True, slug, clean_syntax.dropped)

    def update(
        self,
        theme_id: str,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        colors: Optional[Dict[str, Any]] = None,
        is_featured: Optional[bool] = None,
        is_active: Optional[bool] = None,
        syntax_css: Optional[str] = None,
        syntax_colors: Optional[Dict[str, Any]] = None,
    ) -> SharedThemeWriteResult:
        """עדכון ערכה קיימת. ``syntax_css=None`` משאיר את ה-CSS השמור כמו שהוא."""
        if not theme_id or self.collection is None:
            return SharedThemeWriteResult(False, "theme_not_found")

        # בדיקה קיימת
        try:
            existing = self.collection.find_one({"_id": str(theme_id)})
            if not existing:
                return SharedThemeWriteResult(False, "theme_not_found")
        except Exception as e:
            logger.exception("SharedThemeService.update existing check failed: %s", e)
            return SharedThemeWriteResult(False, "database_error")

        update_fields: Dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}

        if name is not None:
            nm = (name or "").strip()
            if not nm:
                return SharedThemeWriteResult(False, "missing_name")
            if len(nm) > MAX_NAME_LENGTH:
                return SharedThemeWriteResult(False, "name_too_long")
            update_fields["name"] = nm

        if description is not None:
            update_fields["description"] = (description or "").strip()[:MAX_DESCRIPTION_LENGTH]

        if colors is not None:
            ok, filtered, error_field = self._filter_and_validate_colors(colors)
            if not ok:
                if error_field and error_field != "colors_not_dict":
                    return SharedThemeWriteResult(False, f"invalid_color:{error_field}")
                return SharedThemeWriteResult(False, "invalid_colors")
            update_fields["colors"] = filtered

        syntax_rules_dropped = 0
        if syntax_css is not None:
            clean_syntax, syntax_error = self._normalize_syntax_css(syntax_css)
            if clean_syntax is None:
                return SharedThemeWriteResult(False, syntax_error or "invalid_syntax_css")
            update_fields["syntax_css"] = clean_syntax.css
            syntax_rules_dropped = clean_syntax.dropped

        if syntax_colors is not None:
            update_fields["syntax_colors"] = syntax_colors if isinstance(syntax_colors, dict) else {}

        if is_featured is not None:
            update_fields["is_featured"] = bool(is_featured)

        if is_active is not None:
            update_fields["is_active"] = bool(is_active)

        try:
            result = self.collection.update_one({"_id": str(theme_id)}, {"$set": update_fields})
            if getattr(result, "modified_count", 0) == 0:
                return SharedThemeWriteResult(False, "no_changes")
            self.invalidate_cache()
        except Exception as e:
            logger.exception("SharedThemeService.update failed: %s", e)
            return SharedThemeWriteResult(False, "database_error")
        self._log_dropped_syntax_rules(str(theme_id), syntax_rules_dropped)
        return SharedThemeWriteResult(True, "ok", syntax_rules_dropped)

    def delete(self, theme_id: str) -> Tuple[bool, str]:
        """מחיקה קשה של ערכה."""
        if not theme_id or self.collection is None:
            return False, "theme_not_found"
        try:
            result = self.collection.delete_one({"_id": str(theme_id)})
            if getattr(result, "deleted_count", 0) == 0:
                return False, "theme_not_found"
            self.invalidate_cache()
            return True, "ok"
        except Exception as e:
            logger.exception("SharedThemeService.delete failed: %s", e)
            return False, "database_error"

    # ============= Merged List =============

    def get_all_themes_merged(self, user_custom_themes: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []

        # 1) Built-in
        merged.extend(BUILTIN_THEMES)

        # 2) Shared (public)
        merged.extend(self.get_all_active())

        # 3) Custom (user)
        if user_custom_themes:
            for t in user_custom_themes:
                if not isinstance(t, dict):
                    continue
                variables = t.get("variables")
                if not isinstance(variables, dict):
                    variables = {}
                preview_colors = _extract_preview_colors(variables)
                merged.append(
                    {
                        "id": t.get("id"),
                        "name": t.get("name"),
                        "is_active": bool(t.get("is_active", False)),
                        "type": "custom",
                        "preview_colors": preview_colors,
                    }
                )
        return merged


_shared_theme_service: Optional[SharedThemeService] = None


def get_shared_theme_service() -> SharedThemeService:
    """
    Returns singleton instance of SharedThemeService.
    Cached across all requests for performance.
    """
    global _shared_theme_service

    from database.db_manager import get_db

    db = get_db()

    if _shared_theme_service is None:
        _shared_theme_service = SharedThemeService(db)
    else:
        # בדיקות/pytest עשויות להחליף את get_db (monkeypatch) בין טסטים.
        # כדי לא "לנעול" service על DB ישן, נרענן אם ה-DB השתנה.
        try:
            if getattr(_shared_theme_service, "db", None) is not db:
                _shared_theme_service = SharedThemeService(db)
        except Exception:
            _shared_theme_service = SharedThemeService(db)

    return _shared_theme_service

