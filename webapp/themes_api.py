"""
Themes API (Presets / Import / Export)
מימוש לפי GUIDES/custom_themes_guide.md
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from functools import wraps
from typing import Dict, Optional

from flask import Blueprint, Response, jsonify, request, session

from webapp.ui_theme_defaults import get_default_ui_theme_raw

from services.theme_parser_service import (
    export_theme_to_json,
    generate_codemirror_css_from_tokens,
    is_valid_color,
    parse_native_theme,
    parse_vscode_theme,
    sanitize_codemirror_css,
    strip_jsonc_comments,
    validate_and_sanitize_theme_variables,
    validate_theme_json,
)
from services.theme_presets_service import apply_preset_to_user, get_preset_by_id, list_presets
from services.shared_theme_service import get_shared_theme_service

logger = logging.getLogger(__name__)

THEME_SCOPE_GLOBAL = "global"
THEME_SCOPE_DEVICE = "device"
_THEME_SCOPE_VALUES = {THEME_SCOPE_GLOBAL, THEME_SCOPE_DEVICE}
_THEME_ID_SAFE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
_COOKIE_THEME_ID_RE = re.compile(r"^[a-z0-9_-]{1,64}$")


# ==========================================
# Rate Limiting for Theme Details
# ==========================================
# אדמינים מקבלים מגבלה גבוהה יותר (200/שעה) לעבודה רציפה בגלריה
# משתמשים רגילים: 50/שעה (ברירת מחדל)

_RATE_LIMIT_WINDOW_SECONDS = 3600  # שעה אחת
_RATE_LIMIT_REGULAR = 50
_RATE_LIMIT_ADMIN = 200
_RATE_LIMIT_EXEMPT_USER_IDS = {6865105071}  # החרגה לפיתוח (לא מוגבל בכלל)

# In-memory rate limit tracking per user
_theme_details_rate_log: Dict[int, list] = {}


def _is_admin(user_id: int) -> bool:
    """בודק אם משתמש הוא אדמין - import מאוחר למניעת circular imports"""
    try:
        from webapp.app import is_admin
        return is_admin(user_id)
    except Exception:
        return False


def _check_theme_details_rate_limit(user_id: int) -> tuple[bool, int]:
    """
    בודק rate limit עבור get_theme_details.
    מחזיר (allowed, retry_after_seconds).
    
    אדמינים: 200 בקשות/שעה
    משתמשים רגילים: 50 בקשות/שעה
    """
    # החרגה: אדמין או משתמש פיתוח ספציפי - ללא הגבלה בכלל
    if user_id in _RATE_LIMIT_EXEMPT_USER_IDS or _is_admin(user_id):
        return True, 0

    now = time.time()
    window_start = now - _RATE_LIMIT_WINDOW_SECONDS
    
    # קביעת מגבלה לפי סטטוס המשתמש
    max_requests = _RATE_LIMIT_ADMIN if _is_admin(user_id) else _RATE_LIMIT_REGULAR
    
    try:
        entries = _theme_details_rate_log.get(user_id, [])
        # נקה רשומות ישנות
        entries = [ts for ts in entries if ts > window_start]
        _theme_details_rate_log[user_id] = entries
        
        if len(entries) >= max_requests:
            # חישוב זמן המתנה - מתי הבקשה הישנה ביותר תצא מהחלון
            oldest = min(entries) if entries else now
            retry_after = max(1, int((oldest + _RATE_LIMIT_WINDOW_SECONDS) - now))
            return False, retry_after
        
        # הוסף את הבקשה הנוכחית
        entries.append(now)
        _theme_details_rate_log[user_id] = entries
        return True, 0
    except Exception:
        return True, 0  # בשגיאה - אפשר את הבקשה


def theme_details_rate_limit(f):
    """Decorator עבור rate limiting על get_theme_details"""
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            user_id = int(session.get("user_id") or 0)
        except Exception:
            user_id = 0
        
        if user_id:
            allowed, retry_after = _check_theme_details_rate_limit(user_id)
            if not allowed:
                is_admin = _is_admin(user_id)
                limit_info = f"{_RATE_LIMIT_ADMIN}/hour (admin)" if is_admin else f"{_RATE_LIMIT_REGULAR}/hour"
                logger.warning(
                    "themes.get_theme_details rate limited",
                    extra={
                        "user_id": user_id,
                        "is_admin": is_admin,
                        "limit": limit_info,
                        "retry_after": retry_after,
                    }
                )
                resp = jsonify({
                    "ok": False,
                    "error": "rate_limited",
                    "message": f"יותר מדי בקשות. ניתן לנסות שוב בעוד {retry_after} שניות.",
                    "retry_after": retry_after,
                })
                resp.status_code = 429
                resp.headers["Retry-After"] = str(retry_after)
                return resp
        
        return f(*args, **kwargs)
    return decorated

themes_bp = Blueprint("themes", __name__, url_prefix="/api/themes")

MAX_THEME_FILE_SIZE = 512 * 1024  # 512KB
MAX_THEMES_PER_USER = 10
MAX_THEME_NAME_LENGTH = 50
MAX_THEME_DESCRIPTION_LENGTH = 200
MAX_THEME_VALUE_LENGTH = 200


def get_db():
    from webapp.app import get_db as _get_db  # local import to avoid circular deps
    return _get_db()


def get_current_user_id() -> Optional[int]:
    try:
        uid = session.get("user_id")
        if uid is None:
            return None
        return int(uid)
    except Exception:
        return None


def _get_theme_scope_from_request() -> str:
    data = request.get_json(silent=True) or {}
    raw = (data.get("theme_scope") or data.get("scope") or request.args.get("scope") or "").strip().lower()
    return THEME_SCOPE_DEVICE if raw == THEME_SCOPE_DEVICE else THEME_SCOPE_GLOBAL


def _sanitize_theme_cookie_value(value: str) -> Optional[str]:
    raw = str(value or "").strip().lower()
    if raw.startswith("shared:"):
        theme_id = raw.split("shared:", 1)[1].strip()
        if theme_id and _COOKIE_THEME_ID_RE.fullmatch(theme_id):
            return f"shared:{theme_id}"
        return None
    if raw.startswith("custom:"):
        theme_id = raw.split("custom:", 1)[1].strip()
        if theme_id and _COOKIE_THEME_ID_RE.fullmatch(theme_id):
            return f"custom:{theme_id}"
        return None
    return None


def _set_theme_scope_cookies(resp: Response, theme_value: str, scope: str) -> None:
    safe_theme = _sanitize_theme_cookie_value(theme_value)
    if safe_theme:
        resp.set_cookie(
            "ui_theme",
            safe_theme,
            max_age=365 * 24 * 3600,
            samesite="Lax",
            secure=True,
            httponly=True,
        )
    scope_value = THEME_SCOPE_DEVICE if scope == THEME_SCOPE_DEVICE else THEME_SCOPE_GLOBAL
    resp.set_cookie(
        "ui_theme_scope",
        scope_value,
        max_age=365 * 24 * 3600,
        samesite="Lax",
        secure=True,
        httponly=True,
    )


def require_auth(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"success": False, "error": "נדרש להתחבר"}), 401
        return f(*args, **kwargs)

    return decorated_function


def _require_admin_user_id() -> tuple[Optional[int], Optional[tuple[Response, int]]]:
    """עוזר: החזר user_id או (Response, status_code)."""
    user_id = get_current_user_id()
    if not user_id:
        return None, (jsonify({"ok": False, "error": "unauthorized"}), 401)
    if not _is_admin(int(user_id)):
        return None, (jsonify({"ok": False, "error": "admin_required"}), 403)
    return int(user_id), None


# ============================================================
# Shared Themes API (Shared Theme Library)
# מימוש לפי GUIDES/SHARED_THEME_LIBRARY_GUIDE.md
# ============================================================


@themes_bp.route("/list", methods=["GET"])
def get_all_themes_list():
    """
    קבלת רשימה משולבת של כל הערכות:
    - Built-in (קבועות בקוד)
    - Shared (ציבוריות מה-DB)
    - Custom (אישיות של המשתמש)
    """
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    try:
        db_ref = get_db()
        user_doc = db_ref.users.find_one({"user_id": int(user_id)}, {"custom_themes": 1}) or {}
        user_themes = user_doc.get("custom_themes", []) if isinstance(user_doc, dict) else []
        if not isinstance(user_themes, list):
            user_themes = []

        service = get_shared_theme_service()
        merged = service.get_all_themes_merged(user_themes)
        return jsonify({"ok": True, "themes": merged, "count": len(merged)})
    except Exception as e:
        logger.exception("get_all_themes_list failed: %s", e)
        return jsonify({"ok": False, "error": "database_error"}), 500


@themes_bp.route("/shared/<theme_id>", methods=["GET"])
def get_shared_theme(theme_id: str):
    """קבלת פרטי ערכה ציבורית כולל colors + syntax_css."""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    try:
        service = get_shared_theme_service()
        theme = service.get_by_id(theme_id)
        if not theme:
            return jsonify({"ok": False, "error": "theme_not_found"}), 404
        return jsonify({"ok": True, "theme": theme})
    except Exception as e:
        logger.exception("get_shared_theme failed: %s", e)
        return jsonify({"ok": False, "error": "database_error"}), 500


@themes_bp.route("/publish", methods=["POST"])
def publish_shared_theme():
    """פרסום ערכה ציבורית חדשה (Admin בלבד)."""
    user_id, err_resp = _require_admin_user_id()
    if err_resp is not None:
        return err_resp

    data = request.get_json(silent=True) or {}
    slug = (data.get("slug") or "").strip().lower()
    name = (data.get("name") or "").strip()
    colors = data.get("colors") or {}
    description = data.get("description", "")
    is_featured = bool(data.get("is_featured", False))
    syntax_css = data.get("syntax_css")  # optional
    syntax_colors = data.get("syntax_colors")  # optional - dict for dynamic HighlightStyle

    if not slug:
        return jsonify({"ok": False, "error": "missing_slug"}), 400
    if not name:
        return jsonify({"ok": False, "error": "missing_name"}), 400
    if not colors:
        return jsonify({"ok": False, "error": "missing_colors"}), 400

    try:
        service = get_shared_theme_service()
        success, result = service.create(
            slug=slug,
            name=name,
            colors=colors,
            created_by=int(user_id),
            description=description,
            is_featured=is_featured,
            syntax_css=str(syntax_css) if isinstance(syntax_css, str) else None,
            syntax_colors=syntax_colors if isinstance(syntax_colors, dict) else None,
        )

        if not success:
            if result.startswith("invalid_color:"):
                field = result.split(":", 1)[1]
                return jsonify({"ok": False, "error": "invalid_color", "field": field}), 400

            error_map = {
                "invalid_slug": ("slug חייב להיות 3-30 תווים באנגלית קטנה", 400),
                "slug_exists": ("slug כבר קיים", 409),
                "missing_name": ("חסר שם לתצוגה", 400),
                "name_too_long": ("שם ארוך מדי (עד 50 תווים)", 400),
                "invalid_colors": ("colors לא תקין", 400),
            }
            msg, status = error_map.get(result, ("שגיאה לא ידועה", 500))
            return jsonify({"ok": False, "error": result, "message": msg}), status

        return jsonify({"ok": True, "theme_id": result, "message": "הערכה פורסמה בהצלחה!"})
    except Exception as e:
        logger.exception("publish_shared_theme failed: %s", e)
        return jsonify({"ok": False, "error": "database_error"}), 500


@themes_bp.route("/shared/<theme_id>", methods=["PUT"])
def update_shared_theme(theme_id: str):
    """עדכון ערכה ציבורית (Admin בלבד)."""
    user_id, err_resp = _require_admin_user_id()
    if err_resp is not None:
        return err_resp

    data = request.get_json(silent=True) or {}
    try:
        service = get_shared_theme_service()
        success, result = service.update(
            theme_id,
            name=data.get("name"),
            description=data.get("description"),
            colors=data.get("colors"),
            is_featured=data.get("is_featured"),
            is_active=data.get("is_active"),
            syntax_css=data.get("syntax_css"),
            syntax_colors=data.get("syntax_colors"),
        )
        if not success:
            if result == "theme_not_found":
                return jsonify({"ok": False, "error": result}), 404
            if result.startswith("invalid_color:"):
                field = result.split(":", 1)[1]
                return jsonify({"ok": False, "error": "invalid_color", "field": field}), 400
            return jsonify({"ok": False, "error": result}), 400
        return jsonify({"ok": True, "message": "הערכה עודכנה"})
    except Exception as e:
        logger.exception("update_shared_theme failed: %s", e)
        return jsonify({"ok": False, "error": "database_error"}), 500


@themes_bp.route("/shared/<theme_id>", methods=["DELETE"])
def delete_shared_theme(theme_id: str):
    """מחיקת ערכה ציבורית (Admin בלבד)."""
    user_id, err_resp = _require_admin_user_id()
    if err_resp is not None:
        return err_resp

    try:
        service = get_shared_theme_service()
        success, result = service.delete(theme_id)
        if not success:
            if result == "theme_not_found":
                return jsonify({"ok": False, "error": result}), 404
            return jsonify({"ok": False, "error": result}), 500
        return jsonify({"ok": True, "message": "הערכה נמחקה"})
    except Exception as e:
        logger.exception("delete_shared_theme failed: %s", e)
        return jsonify({"ok": False, "error": "database_error"}), 500


@themes_bp.route("/shared/<theme_id>/apply", methods=["POST"])
def apply_shared_theme(theme_id: str):
    """החלת ערכה ציבורית על המשתמש: ui_prefs.theme = 'shared:<id>'."""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    try:
        theme_scope = _get_theme_scope_from_request()
        service = get_shared_theme_service()
        theme = service.get_by_id(theme_id)
        if not theme:
            return jsonify({"ok": False, "error": "theme_not_found"}), 404

        theme_cookie_value = f"shared:{theme_id}"
        if theme_scope == THEME_SCOPE_DEVICE:
            resp = jsonify(
                {
                    "ok": True,
                    "message": "הערכה הוחלה למכשיר הנוכחי",
                    "applied_theme": theme_id,
                    "scope": theme_scope,
                }
            )
            _set_theme_scope_cookies(resp, theme_cookie_value, theme_scope)
            return resp

        db_ref = get_db()
        now_utc = datetime.now(timezone.utc)

        # בטל ערכות אישיות פעילות (custom_themes)
        try:
            db_ref.users.update_one(
                {"user_id": int(user_id), "custom_themes": {"$exists": True}},
                {"$set": {"custom_themes.$[].is_active": False, "updated_at": now_utc}},
            )
        except Exception:
            # best-effort
            pass

        # עדכן את ההעדפה
        db_ref.users.update_one(
            {"user_id": int(user_id)},
            {"$set": {"ui_prefs.theme": f"shared:{theme_id}", "updated_at": now_utc}},
            upsert=True,
        )

        resp = jsonify({"ok": True, "message": "הערכה הוחלה!", "applied_theme": theme_id})
        _set_theme_scope_cookies(resp, theme_cookie_value, theme_scope)
        return resp
    except Exception as e:
        logger.exception("apply_shared_theme failed: %s", e)
        return jsonify({"ok": False, "error": "database_error"}), 500

def _count_user_themes(db, user_id: int) -> int:
    try:
        user_doc = db.users.find_one({"user_id": int(user_id)}, {"custom_themes": 1}) or {}
        themes = user_doc.get("custom_themes") if isinstance(user_doc, dict) else None
        if isinstance(themes, list):
            return len(themes)
        return 0
    except Exception:
        return 0


def _get_user_max_themes_allowed(user_id: int) -> Optional[int]:
    """
    מחזיר את המגבלה למספר ערכות שמותר לשמור.

    - משתמש רגיל: MAX_THEMES_PER_USER
    - אדמין: ללא מגבלה (None)

    הערה: ב-API מחזירים None כדי שה-UI יוכל להציג ∞.
    """
    try:
        if _is_admin(int(user_id)):
            return None
    except Exception:
        # best-effort: אם לא הצלחנו לזהות אדמין - נחזור למגבלת ברירת מחדל
        pass
    return MAX_THEMES_PER_USER


def _is_over_theme_limit(db, user_id: int) -> bool:
    """בודק האם המשתמש עבר את המגבלה (אדמין תמיד False)."""
    max_allowed = _get_user_max_themes_allowed(user_id)
    if max_allowed is None:
        return False
    return _count_user_themes(db, user_id) >= int(max_allowed)


_VALID_PX_REGEX = re.compile(r"^\d{1,3}(\.\d{1,2})?px$")


def _validate_theme_value(var_name: str, value: str) -> bool:
    """בודק שהערך בטוח למשתנה:
    - לכל המשתנים: Hex/RGB/RGBA בלבד
    - חריג יחיד: --glass-blur יכול להיות px
    """
    if not var_name or not isinstance(var_name, str):
        return False
    if value is None or not isinstance(value, str):
        return False

    v = value.strip()
    if not v:
        return False
    if len(v) > MAX_THEME_VALUE_LENGTH:
        return False
    if var_name == "--glass-blur":
        return bool(_VALID_PX_REGEX.match(v.lower()))
    return is_valid_color(v)


def _create_theme_document(
    *,
    name: str,
    variables: dict[str, str],
    description: str = "",
    source: str = "manual",
    syntax_css: str = "",
    syntax_colors: dict | None = None,
    source_preset_id: str | None = None,
) -> dict:
    now = datetime.now(timezone.utc)
    doc: dict = {
        "id": str(uuid.uuid4()),
        "name": name,
        "description": (description or "").strip()[:MAX_THEME_DESCRIPTION_LENGTH],
        "is_active": False,
        "created_at": now,
        "updated_at": now,
        "variables": variables,
        "source": (source or "manual").strip().lower(),
        "syntax_css": syntax_css if isinstance(syntax_css, str) else "",
        "syntax_colors": syntax_colors if isinstance(syntax_colors, dict) else {},
    }
    if source_preset_id:
        doc["source_preset_id"] = str(source_preset_id)
    return doc


def _activate_theme_simple(db_ref, user_id: int, theme_id: str) -> bool:
    """הפעלה בטוחה יותר של ערכה (מעדיף פעולה אטומית; fallback לשתי שאילתות)."""
    if not user_id or not theme_id:
        return False
    now_utc = datetime.now(timezone.utc)

    # ניסיון 1: עדכון אטומי (MongoDB 4.2+ pipeline update)
    try:
        from pymongo.errors import PyMongoError  # local import (optional in docs/CI)

        result = db_ref.users.update_one(
            {"user_id": user_id, "custom_themes.id": theme_id},
            [
                {
                    "$set": {
                        "custom_themes": {
                            "$map": {
                                "input": "$custom_themes",
                                "as": "t",
                                "in": {
                                    "$mergeObjects": [
                                        "$$t",
                                        {"is_active": {"$eq": ["$$t.id", theme_id]}},
                                    ]
                                },
                            }
                        },
                        "ui_prefs.theme": "custom",
                        "updated_at": now_utc,
                    }
                }
            ],
        )
        return bool(getattr(result, "modified_count", 0) > 0)
    except Exception as e:
        # fallback לשתי שאילתות (למשל שרת ישן או סביבת בדיקות)
        try:
            from pymongo.errors import PyMongoError  # noqa: F401
        except Exception:
            PyMongoError = Exception  # type: ignore
        if isinstance(e, PyMongoError):
            logger.error("activate_theme_simple atomic update failed: %s", e)
        else:
            logger.error("activate_theme_simple unexpected error: %s", e)

    # ניסיון 2 (fallback): שתי שאילתות
    try:
        db_ref.users.update_one(
            {"user_id": user_id, "custom_themes": {"$exists": True}},
            {"$set": {"custom_themes.$[].is_active": False}},
        )
        result2 = db_ref.users.update_one(
            {"user_id": user_id, "custom_themes.id": theme_id},
            {"$set": {"custom_themes.$.is_active": True, "ui_prefs.theme": "custom", "updated_at": now_utc}},
        )
        return bool(getattr(result2, "modified_count", 0) > 0)
    except Exception as e:
        logger.error("activate_theme_simple fallback failed: %s", e)
        try:
            db_ref.users.update_one(
                {"user_id": user_id},
                {"$set": {"ui_prefs.theme": get_default_ui_theme_raw(), "updated_at": now_utc}},
            )
        except Exception:
            pass
        return False


# ============================================================
# Legacy Themes API (moved from webapp/app.py, kept stable)
# ============================================================


@themes_bp.route("", methods=["GET"])
def get_user_themes():
    """קבלת רשימת כל הערכות השמורות של המשתמש."""
    try:
        user_id = int(session.get("user_id"))
    except Exception:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    try:
        db_ref = get_db()
        user_doc = db_ref.users.find_one({"user_id": user_id}, {"custom_themes": 1}) or {}

        themes: list[dict] = []
        raw_themes = user_doc.get("custom_themes") if isinstance(user_doc, dict) else None
        if isinstance(raw_themes, list):
            for theme in raw_themes:
                if not isinstance(theme, dict):
                    continue
                created_at = theme.get("created_at")
                updated_at = theme.get("updated_at")
                themes.append(
                    {
                        "id": theme.get("id"),
                        "name": theme.get("name"),
                        "description": theme.get("description", ""),
                        "is_active": bool(theme.get("is_active", False)),
                        "created_at": created_at.isoformat() if isinstance(created_at, datetime) else None,
                        "updated_at": updated_at.isoformat() if isinstance(updated_at, datetime) else None,
                    }
                )

        return jsonify(
            {
                "ok": True,
                "themes": themes,
                "count": len(themes),
                "max_allowed": _get_user_max_themes_allowed(user_id),
            }
        )
    except Exception as e:
        logger.exception("get_user_themes failed: %s", e)
        return jsonify({"ok": False, "error": "database_error"}), 500


@themes_bp.route("/<theme_id>", methods=["GET"])
@theme_details_rate_limit
def get_theme_details(theme_id: str):
    """קבלת פרטי ערכה ספציפית כולל variables.
    
    Rate Limits:
    - משתמשים רגילים: 50 בקשות/שעה
    - אדמינים: 200 בקשות/שעה
    """
    try:
        user_id = int(session.get("user_id"))
    except Exception:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    try:
        db_ref = get_db()
        user_doc = db_ref.users.find_one({"user_id": user_id, "custom_themes.id": theme_id}, {"custom_themes.$": 1})
        if not user_doc or not user_doc.get("custom_themes"):
            return jsonify({"ok": False, "error": "theme_not_found"}), 404

        theme = (user_doc.get("custom_themes") or [None])[0]
        if not isinstance(theme, dict):
            return jsonify({"ok": False, "error": "theme_not_found"}), 404

        created_at = theme.get("created_at")
        updated_at = theme.get("updated_at")
        return jsonify(
            {
                "ok": True,
                "theme": {
                    "id": theme.get("id"),
                    "name": theme.get("name"),
                    "description": theme.get("description", ""),
                    "is_active": bool(theme.get("is_active", False)),
                    "created_at": created_at.isoformat() if isinstance(created_at, datetime) else None,
                    "updated_at": updated_at.isoformat() if isinstance(updated_at, datetime) else None,
                    "variables": theme.get("variables", {}) if isinstance(theme.get("variables"), dict) else {},
                    "syntax_css": theme.get("syntax_css", "") if isinstance(theme.get("syntax_css", ""), str) else "",
                    "syntax_colors": theme.get("syntax_colors", {}) if isinstance(theme.get("syntax_colors"), dict) else {},
                    "source": theme.get("source", "") if isinstance(theme.get("source", ""), str) else "",
                },
            }
        )
    except Exception as e:
        logger.exception("get_theme_details failed: %s", e)
        return jsonify({"ok": False, "error": "database_error"}), 500


@themes_bp.route("", methods=["POST"])
def create_theme():
    """יצירת ערכת נושא חדשה (במקום לדרוס)."""
    try:
        user_id = int(session.get("user_id"))
    except Exception:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}

    try:
        db_ref = get_db()
        if _is_over_theme_limit(db_ref, user_id):
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "max_themes_reached",
                        "message": f"ניתן לשמור עד {MAX_THEMES_PER_USER} ערכות",
                    }
                ),
                400,
            )
    except Exception as e:
        logger.exception("create_theme count check failed: %s", e)
        return jsonify({"ok": False, "error": "database_error"}), 500

    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "missing_name"}), 400
    if len(name) > MAX_THEME_NAME_LENGTH:
        return jsonify({"ok": False, "error": "name_too_long"}), 400

    variables = data.get("variables") or {}
    if not isinstance(variables, dict):
        return jsonify({"ok": False, "error": "invalid_variables"}), 400

    validated_vars: dict[str, str] = {}
    from services.theme_parser_service import ALLOWED_VARIABLES_WHITELIST as _WL  # local import
    for var_name, var_value in variables.items():
        if not isinstance(var_name, str):
            continue
        if var_name not in _WL:
            continue
        val = str(var_value).strip()
        if not _validate_theme_value(var_name, val):
            return jsonify({"ok": False, "error": "invalid_color", "field": var_name}), 400
        validated_vars[var_name] = val

    theme_doc = _create_theme_document(
        name=name,
        variables=validated_vars,
        description=(data.get("description") or ""),
        source="manual",
        syntax_css="",
    )

    theme_id = str(theme_doc.get("id") or "")
    try:
        db_ref = get_db()
        db_ref.users.update_one({"user_id": user_id}, {"$push": {"custom_themes": theme_doc}}, upsert=True)
        if data.get("activate", False) and theme_id:
            _activate_theme_simple(db_ref, user_id, theme_id)
        return jsonify({"ok": True, "theme_id": theme_id, "message": "הערכה נוצרה בהצלחה"})
    except Exception as e:
        logger.exception("create_theme failed: %s", e)
        return jsonify({"ok": False, "error": "database_error"}), 500


@themes_bp.route("/<theme_id>", methods=["PUT"])
def update_theme(theme_id: str):
    """עדכון ערכת נושא קיימת."""
    try:
        user_id = int(session.get("user_id"))
    except Exception:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    try:
        db_ref = get_db()
        user_doc = db_ref.users.find_one({"user_id": user_id, "custom_themes.id": theme_id}, {"custom_themes.$": 1})
        if not user_doc or not user_doc.get("custom_themes"):
            return jsonify({"ok": False, "error": "theme_not_found"}), 404

        existing_theme = (user_doc.get("custom_themes") or [None])[0]
        if not isinstance(existing_theme, dict):
            return jsonify({"ok": False, "error": "theme_not_found"}), 404

        update_fields: dict = {"custom_themes.$.updated_at": datetime.now(timezone.utc)}

        if "name" in data:
            name = (data.get("name") or "").strip()
            if not name:
                return jsonify({"ok": False, "error": "missing_name"}), 400
            if len(name) > MAX_THEME_NAME_LENGTH:
                return jsonify({"ok": False, "error": "name_too_long"}), 400
            update_fields["custom_themes.$.name"] = name

        if "description" in data:
            update_fields["custom_themes.$.description"] = (data.get("description") or "").strip()[:MAX_THEME_DESCRIPTION_LENGTH]

        if "variables" in data:
            variables = data.get("variables")
            if not isinstance(variables, dict):
                return jsonify({"ok": False, "error": "invalid_variables"}), 400

            from services.theme_parser_service import ALLOWED_VARIABLES_WHITELIST as _WL  # local import

            patch_vars: dict[str, str] = {}
            for var_name, var_value in variables.items():
                if not isinstance(var_name, str):
                    continue
                if var_name not in _WL:
                    continue
                val = str(var_value).strip()
                if not _validate_theme_value(var_name, val):
                    return jsonify({"ok": False, "error": "invalid_color", "field": var_name}), 400
                patch_vars[var_name] = val

            existing_vars = existing_theme.get("variables") or {}
            if not isinstance(existing_vars, dict):
                existing_vars = {}
            merged_vars = dict(existing_vars)
            merged_vars.update(patch_vars)
            update_fields["custom_themes.$.variables"] = merged_vars

        result = db_ref.users.update_one({"user_id": user_id, "custom_themes.id": theme_id}, {"$set": update_fields})
        if getattr(result, "modified_count", 0) == 0:
            return jsonify({"ok": False, "error": "no_changes"}), 400

        return jsonify({"ok": True, "message": "הערכה עודכנה בהצלחה"})
    except Exception as e:
        logger.exception("update_theme failed: %s", e)
        return jsonify({"ok": False, "error": "database_error"}), 500


@themes_bp.route("/<theme_id>/activate", methods=["POST"])
def activate_theme_endpoint(theme_id: str):
    """החלת ערכה ספציפית (הפיכתה לפעילה)."""
    try:
        user_id = int(session.get("user_id"))
    except Exception:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    try:
        theme_scope = _get_theme_scope_from_request()
        db_ref = get_db()
        user_doc = db_ref.users.find_one({"user_id": user_id, "custom_themes.id": theme_id}, {"custom_themes.$": 1})
        if not user_doc or not user_doc.get("custom_themes"):
            return jsonify({"ok": False, "error": "theme_not_found"}), 404

        theme_cookie_value = f"custom:{theme_id}"
        if theme_scope == THEME_SCOPE_DEVICE:
            resp = jsonify({"ok": True, "message": "הערכה הוחלה למכשיר הנוכחי", "active_theme_id": theme_id, "scope": theme_scope})
            _set_theme_scope_cookies(resp, theme_cookie_value, theme_scope)
            return resp

        success = _activate_theme_simple(db_ref, user_id, theme_id)
        if success:
            resp = jsonify({"ok": True, "message": "הערכה הופעלה בהצלחה", "active_theme_id": theme_id})
            _set_theme_scope_cookies(resp, theme_cookie_value, theme_scope)
            return resp
        return jsonify({"ok": False, "error": "activation_failed"}), 500
    except Exception as e:
        logger.exception("activate_theme_endpoint failed: %s", e)
        return jsonify({"ok": False, "error": "database_error"}), 500


@themes_bp.route("/deactivate", methods=["POST"])
def deactivate_all_themes():
    """ביטול כל הערכות המותאמות וחזרה לערכה רגילה."""
    try:
        user_id = int(session.get("user_id"))
    except Exception:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    try:
        db_ref = get_db()
        now_utc = datetime.now(timezone.utc)
        default_theme = get_default_ui_theme_raw()
        db_ref.users.update_one({"user_id": user_id}, {"$set": {"ui_prefs.theme": default_theme, "updated_at": now_utc}})
        db_ref.users.update_one(
            {"user_id": user_id, "custom_themes": {"$exists": True}},
            {"$set": {"custom_themes.$[].is_active": False, "updated_at": now_utc}},
        )
        return jsonify({"ok": True, "message": "הערכות המותאמות בוטלו", "reset_to": default_theme})
    except Exception as e:
        logger.exception("deactivate_all_themes failed: %s", e)
        return jsonify({"ok": False, "error": "database_error"}), 500


@themes_bp.route("/<theme_id>", methods=["DELETE"])
def delete_theme(theme_id: str):
    """מחיקת ערכה ספציפית."""
    try:
        user_id = int(session.get("user_id"))
    except Exception:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    try:
        db_ref = get_db()
        user_doc = db_ref.users.find_one({"user_id": user_id, "custom_themes.id": theme_id}, {"custom_themes.$": 1})
        if not user_doc or not user_doc.get("custom_themes"):
            return jsonify({"ok": False, "error": "theme_not_found"}), 404

        theme = (user_doc.get("custom_themes") or [None])[0]
        if not isinstance(theme, dict):
            return jsonify({"ok": False, "error": "theme_not_found"}), 404

        was_active = bool(theme.get("is_active", False))

        db_ref.users.update_one({"user_id": user_id}, {"$pull": {"custom_themes": {"id": theme_id}}})
        if was_active:
            db_ref.users.update_one({"user_id": user_id}, {"$set": {"ui_prefs.theme": get_default_ui_theme_raw()}})

        return jsonify(
            {
                "ok": True,
                "message": "הערכה נמחקה בהצלחה",
                "was_active": was_active,
                "reset_to": get_default_ui_theme_raw() if was_active else None,
            }
        )
    except Exception as e:
        logger.exception("delete_theme failed: %s", e)
        return jsonify({"ok": False, "error": "database_error"}), 500


@themes_bp.route("/save", methods=["POST"])
def save_custom_theme():
    """שמירת ערכת נושא מותאמת אישית (Legacy: custom_theme object)."""
    try:
        user_id = int(session.get("user_id"))
    except Exception:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "missing_name"}), 400
    if len(name) > MAX_THEME_NAME_LENGTH:
        return jsonify({"ok": False, "error": "name_too_long"}), 400

    variables = data.get("variables") or {}
    if not isinstance(variables, dict):
        return jsonify({"ok": False, "error": "invalid_variables"}), 400

    from services.theme_parser_service import ALLOWED_VARIABLES_WHITELIST as _WL  # local import

    validated_vars: dict[str, str] = {}
    for var_name, var_value in variables.items():
        if not isinstance(var_name, str):
            continue
        if var_name not in _WL:
            continue
        val = str(var_value).strip()
        if not _validate_theme_value(var_name, val):
            return jsonify({"ok": False, "error": "invalid_color", "field": var_name}), 400
        validated_vars[var_name] = val

    theme_doc = {
        "name": name,
        "description": (data.get("description") or "").strip()[:200],
        "is_active": bool(data.get("set_as_default", True)),
        "updated_at": datetime.now(timezone.utc),
        "variables": validated_vars,
    }

    try:
        db = get_db()
        now_utc = datetime.now(timezone.utc)
        db.users.update_one(
            {"user_id": user_id},
            {"$set": {"custom_theme": theme_doc, "updated_at": now_utc}, "$setOnInsert": {"created_at": now_utc}},
            upsert=True,
        )
        if theme_doc["is_active"]:
            now_utc2 = datetime.now(timezone.utc)
            db.users.update_one(
                {"user_id": user_id},
                {"$set": {"ui_prefs.theme": "custom", "updated_at": now_utc2}, "$setOnInsert": {"created_at": now_utc2}},
                upsert=True,
            )
        return jsonify({"ok": True})
    except Exception as e:
        logger.exception("save_custom_theme failed: %s", e)
        return jsonify({"ok": False, "error": "database_error"}), 500


@themes_bp.route("/custom", methods=["DELETE"])
def delete_custom_theme():
    """מחיקת ערכת נושא מותאמת אישית (Legacy: custom_theme)."""
    try:
        user_id = int(session.get("user_id"))
    except Exception:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    try:
        db = get_db()
        now_utc = datetime.now(timezone.utc)
        default_theme = get_default_ui_theme_raw()
        db.users.update_one(
            {"user_id": user_id},
            {
                "$unset": {"custom_theme": ""},
                "$set": {"ui_prefs.theme": default_theme, "updated_at": now_utc},
                "$setOnInsert": {"created_at": now_utc},
            },
            upsert=True,
        )
        return jsonify({"ok": True, "reset_to": default_theme})
    except Exception as e:
        logger.exception("delete_custom_theme failed: %s", e)
        return jsonify({"ok": False, "error": "database_error"}), 500

@themes_bp.route("/presets", methods=["GET"])
@require_auth
def presets_list():
    category = (request.args.get("category") or "").strip().lower() or None
    presets = list_presets(category=category)
    return jsonify({"success": True, "presets": presets})


@themes_bp.route("/presets/<preset_id>", methods=["GET"])
@require_auth
def preset_details(preset_id: str):
    preset = get_preset_by_id(preset_id)
    if not preset:
        return jsonify({"success": False, "error": "ערכה לא נמצאה"}), 404

    # מחזירים את כל המשתנים עבור Preview
    return jsonify(
        {
            "id": preset.get("id"),
            "name": preset.get("name"),
            "description": preset.get("description", ""),
            "category": preset.get("category", "dark"),
            "preview_colors": preset.get("preview_colors", []),
            "variables": preset.get("variables", {}),
            "syntax_css": preset.get("syntax_css", ""),
        }
    )


@themes_bp.route("/presets/<preset_id>/apply", methods=["POST"])
@require_auth
def preset_apply(preset_id: str):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    db = get_db()
    if _is_over_theme_limit(db, int(user_id)):
        return (
            jsonify({"success": False, "error": f"הגעת למגבלה של {MAX_THEMES_PER_USER} ערכות מותאמות אישית"}),
            400,
        )

    try:
        new_theme = apply_preset_to_user(user_id=user_id, preset_id=preset_id, db=db)
        return jsonify(
            {
                "success": True,
                "theme": {"id": new_theme["id"], "name": new_theme["name"], "source": "preset"},
                "message": "הערכה נוספה בהצלחה!",
            }
        )
    except ValueError:
        # 🔒 אבטחה: לא מחזירים הודעת חריגה גולמית ללקוח
        logger.exception("Apply preset validation error (preset_id=%s)", preset_id)
        return jsonify({"success": False, "error": "הערכה אינה זמינה או אינה תקינה"}), 404
    except Exception:
        logger.exception("Apply preset error")
        return jsonify({"success": False, "error": "שגיאה בהוספת הערכה"}), 500


@themes_bp.route("/import", methods=["POST"])
@require_auth
def import_theme():
    """
    ייבוא ערכת נושא מקובץ JSON.

    תומך בשני פורמטים:
    1) VS Code theme (עם colors)
    2) פורמט מקומי (עם variables)
    """
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    db = get_db()

    if _is_over_theme_limit(db, int(user_id)):
        return (
            jsonify({"success": False, "error": f"הגעת למגבלה של {MAX_THEMES_PER_USER} ערכות מותאמות אישית"}),
            400,
        )

    json_content: str | None = None

    try:
        if "file" in request.files:
            file = request.files["file"]
            if not file or not file.filename:
                return jsonify({"success": False, "error": "לא נבחר קובץ"}), 400
            if not str(file.filename).lower().endswith(".json"):
                return jsonify({"success": False, "error": "הקובץ חייב להיות בסיומת .json"}), 400

            # בדיקת גודל
            try:
                file.seek(0, 2)
                size = int(file.tell() or 0)
            finally:
                try:
                    file.seek(0)
                except Exception:
                    pass

            if size > MAX_THEME_FILE_SIZE:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"הקובץ גדול מדי (מקסימום {MAX_THEME_FILE_SIZE // 1024}KB)",
                        }
                    ),
                    400,
                )

            json_content = file.read().decode("utf-8", errors="replace")

        elif request.is_json:
            payload = request.get_json(silent=True) or {}
            json_content = payload.get("json_content", "")

        if not json_content:
            return jsonify({"success": False, "error": "לא התקבל תוכן"}), 400

        # הסרת הערות JSONC (/* */ או //) שנפוצות ב-VS Code themes
        cleaned_json = strip_jsonc_comments(json_content)

        is_valid, error_msg = validate_theme_json(cleaned_json)
        if not is_valid:
            return jsonify({"success": False, "error": error_msg}), 400

        data = json.loads(cleaned_json)

        syntax_css = ""
        syntax_colors: dict = {}
        if isinstance(data, dict) and "colors" in data:
            parsed = parse_vscode_theme(data)
            source = "vscode"
            # 🔑 שימוש ב-syntax_css ו-syntax_colors שמוחזרים מ-parse_vscode_theme
            # syntax_css: CodeMirror CSS (.tok-*) + Pygments CSS (.source .k, etc.) - fallback
            # syntax_colors: מילון צבעים לפי tag עבור HighlightStyle דינמי
            syntax_css = parsed.get("syntax_css", "") if isinstance(parsed, dict) else ""
            syntax_colors = parsed.get("syntax_colors", {}) if isinstance(parsed, dict) else {}
        else:
            parsed = parse_native_theme(data)
            source = "import"

        raw_vars = parsed.get("variables", {}) if isinstance(parsed, dict) else {}
        filtered_vars = validate_and_sanitize_theme_variables(raw_vars)

        # בלוק variables אופציונלי בקובץ VS Code: parse_vscode_theme קורא רק
        # colors ו-tokenColors, ול-VSCODE_TO_CSS_MAP אין מפתח שמוביל לטוקנים
        # שאין להם מקבילה ב-VS Code (למשל --collections-link-color). הבלוק הזה
        # נותן לערכה לדרוס טוקן כזה בעצמה, בלי לוותר על הדגשת התחביר שמגיעה
        # מ-tokenColors. הוא עובר את אותה ולידציה ורשימה לבנה כמו כל השאר,
        # ובמסלול הפורמט המקומי parse_native_theme כבר קרא אותו — ולכן רק כאן.
        if source == "vscode" and isinstance(data, dict):
            explicit_vars = data.get("variables")
            if isinstance(explicit_vars, dict):
                filtered_vars.update(validate_and_sanitize_theme_variables(explicit_vars))

        new_theme = {
            "id": str(uuid.uuid4()),
            "name": (parsed.get("name") if isinstance(parsed, dict) else None) or "Imported Theme",
            "description": (parsed.get("description") if isinstance(parsed, dict) else None)
            or f"Imported from {source}",
            "is_active": False,
            "source": source,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "variables": filtered_vars,
            "syntax_css": syntax_css,
            "syntax_colors": syntax_colors,  # 🆕 מילון צבעים ל-HighlightStyle דינמי
        }

        db.users.update_one(
            {"user_id": int(user_id)},
            {"$push": {"custom_themes": new_theme}},
            upsert=True,
        )

        return jsonify(
            {
                "success": True,
                "theme": {"id": new_theme["id"], "name": new_theme["name"], "source": source},
                "message": "הערכה יובאה בהצלחה!",
            }
        )

    except ValueError:
        # 🔒 אבטחה: לא מחזירים הודעת חריגה גולמית ללקוח
        logger.exception("Theme import validation error")
        return jsonify({"success": False, "error": "קובץ הערכה אינו תקין"}), 400
    except Exception:
        logger.exception("Theme import error")
        return jsonify({"success": False, "error": "שגיאה בייבוא הערכה"}), 500


@themes_bp.route("/<theme_id>/export", methods=["GET"])
@require_auth
def export_theme(theme_id: str):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    db = get_db()
    user_doc = db.users.find_one({"user_id": int(user_id), "custom_themes.id": theme_id}, {"custom_themes.$": 1})
    if not user_doc or not user_doc.get("custom_themes"):
        return jsonify({"success": False, "error": "ערכה לא נמצאה"}), 404

    theme = (user_doc.get("custom_themes") or [None])[0]
    if not isinstance(theme, dict):
        return jsonify({"success": False, "error": "ערכה לא נמצאה"}), 404

    json_content = export_theme_to_json(theme)

    # 🔒 אבטחה: ניקוי filename כדי למנוע תווי בקרה/תווים מיוחדים ששוברים Headers
    filename = str(theme.get("name") or "theme")
    filename = re.sub(r"\s+", " ", filename).strip()  # כולל \n/\r/\t
    filename = re.sub(r"[^\w\s-]", "", filename).strip()
    filename = re.sub(r"\s+", " ", filename).strip().replace(" ", "_")
    if not filename:
        filename = "theme"
    filename = filename[:80]

    return Response(
        json_content,
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}.json"'},
    )

