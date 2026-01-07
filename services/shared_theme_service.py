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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from services.theme_parser_service import (
    ALLOWED_VARIABLES_WHITELIST,
    is_valid_color,
    normalize_color_to_rgba,
    sanitize_codemirror_css,
)

logger = logging.getLogger(__name__)

# Regex לבדיקת slug תקין (אותיות קטנות, מספרים, קו תחתון)
VALID_SLUG_REGEX = re.compile(r"^[a-z][a-z0-9_]{2,29}$")

# blur יכול להיות ערך px (כמו בקוד הקיים של Themes API)
_VALID_PX_REGEX = re.compile(r"^\d{1,3}(\.\d{1,2})?px$")

MAX_NAME_LENGTH = 50
MAX_DESCRIPTION_LENGTH = 200
MAX_SYNTAX_CSS_LENGTH = 200_000


def _relative_luminance_srgb(r: int, g: int, b: int) -> float:
    """Relative luminance per WCAG (sRGB). r/g/b are 0..255."""

    def _to_linear(c_255: float) -> float:
        c = c_255 / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r_lin = _to_linear(float(r))
    g_lin = _to_linear(float(g))
    b_lin = _to_linear(float(b))
    return 0.2126 * r_lin + 0.7152 * g_lin + 0.0722 * b_lin


def _contrast_ratio(bg: str, fg: str) -> float | None:
    """
    Contrast ratio for opaque colors (WCAG).
    Returns None when color can't be parsed or is significantly transparent.
    """
    bg_rgba = normalize_color_to_rgba(str(bg))
    fg_rgba = normalize_color_to_rgba(str(fg))
    if not bg_rgba or not fg_rgba:
        return None

    br, bgc, bb, ba = bg_rgba
    fr, fgc, fb, fa = fg_rgba

    # Can't compute reliably without knowing the backdrop
    if ba < 0.98 or fa < 0.98:
        return None

    l1 = _relative_luminance_srgb(br, bgc, bb)
    l2 = _relative_luminance_srgb(fr, fgc, fb)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _maybe_fix_button_text_contrast(colors: Dict[str, str]) -> Dict[str, str]:
    """
    UX guard: prevent unreadable primary button text in Shared Themes.

    Common case: imported VS Code themes define a light button background but omit button.foreground,
    leading to low-contrast (often white-on-white) after publish.
    """
    if not isinstance(colors, dict) or not colors:
        return colors

    out = dict(colors)

    btn_bg = out.get("--btn-primary-bg")
    btn_fg = out.get("--btn-primary-color")
    primary = out.get("--primary") or out.get("--text-primary")

    if btn_bg and btn_fg and primary:
        ratio = _contrast_ratio(btn_bg, btn_fg)
        if ratio is not None and ratio < 2.2:
            ratio_primary = _contrast_ratio(btn_bg, primary)
            if ratio_primary is not None and ratio_primary >= 3.0:
                out["--btn-primary-color"] = primary

    hover_bg = out.get("--btn-primary-hover-bg")
    hover_fg = out.get("--btn-primary-hover-color")
    if hover_bg and hover_fg and primary:
        ratio = _contrast_ratio(hover_bg, hover_fg)
        if ratio is not None and ratio < 2.2:
            ratio_primary = _contrast_ratio(hover_bg, primary)
            if ratio_primary is not None and ratio_primary >= 3.0:
                out["--btn-primary-hover-color"] = primary

    return out


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


class SharedThemeService:
    """שירות לניהול ערכות נושא ציבוריות."""

    def __init__(self, db):
        """
        Args:
            db: אובייקט DB בסגנון PyMongo (חייב להכיל shared_themes collection)
        """
        self.db = db
        self.collection = getattr(db, "shared_themes", None)

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

    def _normalize_syntax_css(self, syntax_css: Optional[str]) -> str:
        if not syntax_css or not isinstance(syntax_css, str):
            return ""
        css = syntax_css.strip()
        if not css:
            return ""
        if len(css) > MAX_SYNTAX_CSS_LENGTH:
            css = css[:MAX_SYNTAX_CSS_LENGTH]
        try:
            return sanitize_codemirror_css(css)
        except Exception:
            # fallback בטוח: אם הניקוי נכשל, לא נשמור CSS
            return ""

    # ============= CRUD Operations =============

    def get_all_active(self) -> List[Dict[str, Any]]:
        """קבלת כל הערכות הפעילות (מטא-דאטה בלבד)."""
        if self.collection is None:
            return []
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
                },
            ).sort([("order", 1), ("created_at", -1)])

            themes: List[Dict[str, Any]] = []
            for doc in cursor:
                created_at = doc.get("created_at")
                themes.append(
                    {
                        "id": doc.get("_id"),
                        "name": doc.get("name"),
                        "description": doc.get("description", ""),
                        "is_featured": bool(doc.get("is_featured", False)),
                        "created_at": created_at.isoformat() if isinstance(created_at, datetime) else None,
                        "type": "shared",
                    }
                )
            return themes
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
    ) -> Tuple[bool, str]:
        """יצירת ערכה ציבורית חדשה."""
        if self.collection is None:
            return False, "database_unavailable"

        slug = (slug or "").strip().lower()
        if not self._validate_slug(slug):
            return False, "invalid_slug"

        name = (name or "").strip()
        if not name:
            return False, "missing_name"
        if len(name) > MAX_NAME_LENGTH:
            return False, "name_too_long"

        ok, filtered_colors, error_field = self._filter_and_validate_colors(colors)
        if not ok:
            if error_field and error_field != "colors_not_dict":
                return False, f"invalid_color:{error_field}"
            return False, "invalid_colors"

        # 🛡️ UX: מניעת "כפתור נעלם" בפרסום (ניגודיות נמוכה לטקסט כפתור).
        filtered_colors = _maybe_fix_button_text_contrast(filtered_colors)

        # בדיקת slug תפוס
        try:
            existing = self.collection.find_one({"_id": slug})
            if existing:
                return False, "slug_exists"
        except Exception as e:
            logger.exception("SharedThemeService.create existing check failed: %s", e)
            return False, "database_error"

        now = datetime.now(timezone.utc)
        doc: Dict[str, Any] = {
            "_id": slug,
            "name": name,
            "description": (description or "").strip()[:MAX_DESCRIPTION_LENGTH],
            "colors": filtered_colors,
            "syntax_css": self._normalize_syntax_css(syntax_css),
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
            logger.info("Created shared theme %s by user %s", slug, created_by)
            return True, slug
        except Exception as e:
            logger.exception("SharedThemeService.create failed: %s", e)
            return False, "database_error"

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
    ) -> Tuple[bool, str]:
        """עדכון ערכה קיימת."""
        if not theme_id or self.collection is None:
            return False, "theme_not_found"

        # בדיקה קיימת
        try:
            existing = self.collection.find_one({"_id": str(theme_id)})
            if not existing:
                return False, "theme_not_found"
        except Exception as e:
            logger.exception("SharedThemeService.update existing check failed: %s", e)
            return False, "database_error"

        update_fields: Dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}

        if name is not None:
            nm = (name or "").strip()
            if not nm:
                return False, "missing_name"
            if len(nm) > MAX_NAME_LENGTH:
                return False, "name_too_long"
            update_fields["name"] = nm

        if description is not None:
            update_fields["description"] = (description or "").strip()[:MAX_DESCRIPTION_LENGTH]

        if colors is not None:
            ok, filtered, error_field = self._filter_and_validate_colors(colors)
            if not ok:
                if error_field and error_field != "colors_not_dict":
                    return False, f"invalid_color:{error_field}"
                return False, "invalid_colors"
            update_fields["colors"] = _maybe_fix_button_text_contrast(filtered)

        if syntax_css is not None:
            update_fields["syntax_css"] = self._normalize_syntax_css(syntax_css)

        if syntax_colors is not None:
            update_fields["syntax_colors"] = syntax_colors if isinstance(syntax_colors, dict) else {}

        if is_featured is not None:
            update_fields["is_featured"] = bool(is_featured)

        if is_active is not None:
            update_fields["is_active"] = bool(is_active)

        try:
            result = self.collection.update_one({"_id": str(theme_id)}, {"$set": update_fields})
            if getattr(result, "modified_count", 0) == 0:
                return False, "no_changes"
            return True, "ok"
        except Exception as e:
            logger.exception("SharedThemeService.update failed: %s", e)
            return False, "database_error"

    def delete(self, theme_id: str) -> Tuple[bool, str]:
        """מחיקה קשה של ערכה."""
        if not theme_id or self.collection is None:
            return False, "theme_not_found"
        try:
            result = self.collection.delete_one({"_id": str(theme_id)})
            if getattr(result, "deleted_count", 0) == 0:
                return False, "theme_not_found"
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
                merged.append(
                    {
                        "id": t.get("id"),
                        "name": t.get("name"),
                        "is_active": bool(t.get("is_active", False)),
                        "type": "custom",
                    }
                )
        return merged


_shared_theme_service: Optional[SharedThemeService] = None


def get_shared_theme_service():
    """Singleton factory — בטוח גם לטסטים (מתאפס אם ה-DB object השתנה)."""
    global _shared_theme_service

    # import מאוחר כדי למנוע circular imports בזמן טעינת מודולים
    from webapp.app import get_db  # noqa: WPS433 (local import by design)

    db = get_db()
    current_coll = getattr(db, "shared_themes", None)
    if _shared_theme_service is None:
        _shared_theme_service = SharedThemeService(db)
        return _shared_theme_service

    # אם סביבת טסט החליפה DB (monkeypatch), נוודא שה-service מתיישר
    try:
        if getattr(_shared_theme_service, "collection", None) is not current_coll:
            _shared_theme_service = SharedThemeService(db)
    except Exception:
        _shared_theme_service = SharedThemeService(db)

    return _shared_theme_service

