"""
Settings Routes - User settings endpoints for WebApp.

This module implements settings endpoints migrated to the new layered architecture:
Route -> Facade/Container -> Service/Domain -> Repository -> DB

Issue: #2871 (Step 3 - The Great Split)

Endpoints:
- GET /settings - Main settings page
- GET /settings/push-debug - Push notifications debug page (admin only)
- POST /settings/push-test - Test push notification
- GET /settings/theme-builder - Theme customization builder
- GET /settings/theme-gallery - Theme gallery and import
- PUT /api/settings/attention - Update attention widget settings
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

logger = logging.getLogger(__name__)

settings_bp = Blueprint("settings", __name__)


def _get_app_helpers():
    """
    Lazy import of helper functions from app.py.
    Returns a namespace with: is_admin, is_premium, is_impersonating_safe,
    _check_persistent_login_cached, login_required, get_db, PERSISTENT_LOGIN_DAYS, _STATIC_VERSION
    """
    from webapp.app import (
        _check_persistent_login_cached,
        _STATIC_VERSION,
        get_db,
        is_admin,
        is_impersonating_safe,
        is_premium,
        login_required,
        PERSISTENT_LOGIN_DAYS,
    )
    from types import SimpleNamespace

    return SimpleNamespace(
        is_admin=is_admin,
        is_premium=is_premium,
        is_impersonating_safe=is_impersonating_safe,
        _check_persistent_login_cached=_check_persistent_login_cached,
        login_required=login_required,
        get_db=get_db,
        PERSISTENT_LOGIN_DAYS=PERSISTENT_LOGIN_DAYS,
        _STATIC_VERSION=_STATIC_VERSION,
    )


@settings_bp.route("/settings")
def settings():
    """Main settings page - optimized with legacy session support."""
    helpers = _get_app_helpers()

    # Apply login_required
    if "user_id" not in session:
        next_url = request.full_path if request.query_string else request.path
        return redirect(url_for("auth.login", next=next_url))

    user_id = session["user_id"]
    user_data = session.get("user_data") or {}
    if not isinstance(user_data, dict):
        user_data = {}
    session["user_data"] = user_data

    # Fallback to check if not in session (legacy sessions)
    user_is_admin = user_data.get("is_admin")
    if user_is_admin is None:
        user_is_admin = helpers.is_admin(user_id)
        user_data["is_admin"] = user_is_admin
        session.modified = True

    user_is_premium = user_data.get("is_premium")
    if user_is_premium is None:
        user_is_premium = helpers.is_premium(user_id)
        user_data["is_premium"] = user_is_premium
        session.modified = True

    if helpers.is_impersonating_safe():
        effective_is_admin = False
        effective_is_premium = False
    else:
        effective_is_admin = bool(user_is_admin)
        effective_is_premium = bool(user_is_premium)

    # Check persistent token with cache
    has_persistent = helpers._check_persistent_login_cached(user_id)

    # Push flag
    push_enabled = os.getenv("PUSH_NOTIFICATIONS_ENABLED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    return render_template(
        "settings.html",
        user=user_data,
        is_admin=effective_is_admin,
        is_premium=effective_is_premium,
        persistent_login_enabled=has_persistent,
        persistent_days=helpers.PERSISTENT_LOGIN_DAYS,
        push_enabled=push_enabled,
    )


@settings_bp.route("/settings/push-debug")
def settings_push_debug():
    """Push debug page (admin only)."""
    helpers = _get_app_helpers()

    if "user_id" not in session:
        next_url = request.full_path if request.query_string else request.path
        return redirect(url_for("auth.login", next=next_url))

    user_id = session.get("user_id")
    user_data = session.get("user_data") or {}
    if not isinstance(user_data, dict):
        user_data = {}

    try:
        if not helpers.is_admin(user_id):
            return redirect("/settings#push")
    except Exception:
        return redirect("/settings#push")

    push_enabled = os.getenv("PUSH_NOTIFICATIONS_ENABLED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    # Server config signals (do not expose secrets)
    vapid_public = (os.getenv("VAPID_PUBLIC_KEY") or "").strip()
    vapid_private = (os.getenv("VAPID_PRIVATE_KEY") or "").strip()
    remote_enabled_env = (os.getenv("PUSH_REMOTE_DELIVERY_ENABLED") or "").strip()
    remote_url = (os.getenv("PUSH_DELIVERY_URL") or "").strip()
    remote_token_set = bool((os.getenv("PUSH_DELIVERY_TOKEN") or "").strip())

    # Runtime package versions
    def _dist_version(*names: str) -> str:
        try:
            from importlib import metadata

            for n in names:
                try:
                    v = metadata.version(n)
                    if v:
                        return str(v)
                except metadata.PackageNotFoundError:
                    continue
                except Exception:
                    continue
        except Exception:
            pass
        return "unknown"

    py_vapid_version = _dist_version("py-vapid", "py_vapid")
    pywebpush_version = _dist_version("pywebpush")
    cryptography_version = _dist_version("cryptography")

    subs_count = None
    subs_error = ""
    try:
        db = helpers.get_db()
        variants: set = set()
        try:
            variants.add(user_id)
        except Exception:
            pass
        try:
            variants.add(int(user_id))
        except Exception:
            pass
        try:
            variants.add(str(user_id or ""))
        except Exception:
            pass
        variants_list = [v for v in variants if v not in (None, "")]
        if not variants_list:
            variants_list = [user_id]
        subs_count = int(
            db.push_subscriptions.count_documents({"user_id": {"$in": variants_list}})
        )
    except Exception as e:
        subs_error = str(e)

    ua = ""
    try:
        ua = str(request.headers.get("User-Agent") or "")
    except Exception:
        ua = ""

    actual_is_admin = bool(user_data.get("is_admin", False))
    actual_is_premium = bool(user_data.get("is_premium", False))
    if helpers.is_impersonating_safe():
        effective_is_admin = False
        effective_is_premium = False
    else:
        effective_is_admin = actual_is_admin
        effective_is_premium = actual_is_premium

    return render_template(
        "settings_push_debug.html",
        user=user_data,
        is_admin=effective_is_admin,
        is_premium=effective_is_premium,
        push_enabled=push_enabled,
        vapid_public_set=bool(vapid_public),
        vapid_private_set=bool(vapid_private),
        remote_enabled_env=remote_enabled_env,
        remote_url=remote_url,
        remote_token_set=remote_token_set,
        py_vapid_version=py_vapid_version,
        pywebpush_version=pywebpush_version,
        cryptography_version=cryptography_version,
        subs_count=subs_count,
        subs_error=subs_error,
        user_agent=ua,
        static_version=helpers._STATIC_VERSION,
    )


@settings_bp.route("/settings/push-test", methods=["POST"])
def settings_push_test():
    """POST that returns JSON from /api/push/test."""
    if "user_id" not in session:
        return jsonify({"error": "נדרש להתחבר"}), 401

    try:
        from webapp.push_api import test_push as _test_push

        return _test_push()
    except Exception:
        return jsonify({"ok": False, "error": "internal_error"}), 500


@settings_bp.route("/settings/theme-builder")
def theme_builder():
    """Theme customization builder page."""
    helpers = _get_app_helpers()

    if "user_id" not in session:
        next_url = request.full_path if request.query_string else request.path
        return redirect(url_for("auth.login", next=next_url))

    user_id = session["user_id"]
    actual_is_admin = False
    actual_is_premium = False
    try:
        uid_int = int(user_id)
        actual_is_admin = bool(helpers.is_admin(uid_int))
        actual_is_premium = bool(helpers.is_premium(uid_int))
    except Exception:
        actual_is_admin = False
        actual_is_premium = False

    if helpers.is_impersonating_safe():
        user_is_admin = False
        user_is_premium = False
    else:
        user_is_admin = actual_is_admin
        user_is_premium = actual_is_premium

    return render_template(
        "settings/theme_builder.html",
        user=session.get("user_data", {}),
        is_admin=user_is_admin,
        is_premium=user_is_premium,
        saved_theme=None,
    )


@settings_bp.route("/settings/theme-gallery")
def theme_gallery():
    """Theme gallery and VS Code/JSON import page."""
    helpers = _get_app_helpers()

    if "user_id" not in session:
        next_url = request.full_path if request.query_string else request.path
        return redirect(url_for("auth.login", next=next_url))

    user_id = session["user_id"]
    actual_is_admin = False
    actual_is_premium = False
    try:
        uid_int = int(user_id)
        actual_is_admin = bool(helpers.is_admin(uid_int))
        actual_is_premium = bool(helpers.is_premium(uid_int))
    except Exception:
        actual_is_admin = False
        actual_is_premium = False

    if helpers.is_impersonating_safe():
        user_is_admin = False
        user_is_premium = False
    else:
        user_is_admin = actual_is_admin
        user_is_premium = actual_is_premium

    return render_template(
        "settings/theme_gallery.html",
        user=session.get("user_data", {}),
        is_admin=user_is_admin,
        is_premium=user_is_premium,
    )


# תקרת האחסון של "הוראות לסוכן". גבוהה מתקרת ההגשה בכוונה: החיתוך הוא החלטה
# של ההגשה ולא של האחסון, כדי שהמשתמש לא יאבד טקסט שכתב.
AGENT_INSTRUCTIONS_MAX_CHARS = 48 * 1024

# תקרת הגוף שהפריימר מגיש בפועל וסף האזהרה ב-UI. מקור האמת הוא
# ``mcp_server.primer`` (MAX_BYTES / WARN_BYTES); הערכים משוכפלים לכאן כי
# הוובאפ ושירות ה-MCP הם שני שירותים נפרדים ואין ביניהם ייבוא.
# ``tests/test_mcp_primer.py`` נכשל אם הזוגות מתפצלים.
AGENT_PRIMER_MAX_BYTES = 24 * 1024
AGENT_INSTRUCTIONS_WARN_BYTES = 21 * 1024


def _agent_instructions_user_id():
    """מזהה המשתמש כ-int, כפי ששרת ה-MCP מחפש אותו. None ⇒ אין סשן תקין.

    חשוב שיהיה int: ``MCPTokenStore`` שומר ``user_id`` כמספר, ולכן מסמך
    ``user_preferences`` שנכתב עם מחרוזת פשוט לא יימצא בקריאה מהפריימר.
    """
    raw = session.get("user_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


@settings_bp.route("/api/settings/agent-instructions", methods=["GET"])
def api_get_agent_instructions():
    """הטקסט הנוכחי של "הוראות לסוכן" (לטעינת השדה בעמוד ההגדרות)."""
    user_id = _agent_instructions_user_id()
    if user_id is None:
        return jsonify({"ok": False, "error": "נדרש להתחבר"}), 401

    helpers = _get_app_helpers()
    text = ""
    try:
        db = helpers.get_db()
        doc = db.user_preferences.find_one(
            {"user_id": user_id}, {"agent_instructions": 1, "_id": 0}
        )
        value = (doc or {}).get("agent_instructions")
        if isinstance(value, str):
            text = value
    except Exception:
        logger.warning("failed to read agent instructions", exc_info=True)
        return jsonify({"ok": False, "error": "שגיאה בטעינת ההוראות"}), 500

    return jsonify(
        {
            "ok": True,
            "text": text,
            "bytes": len(text.encode("utf-8")),
            "max_chars": AGENT_INSTRUCTIONS_MAX_CHARS,
            "primer_max_bytes": AGENT_PRIMER_MAX_BYTES,
            "warn_bytes": AGENT_INSTRUCTIONS_WARN_BYTES,
        }
    )


@settings_bp.route("/api/settings/agent-instructions", methods=["PUT"])
def api_update_agent_instructions():
    """שמירת "הוראות לסוכן" — טקסט חופשי שמוגש כפריימר לסוכני AI.

    הטקסט נשמר כפי שהוא. הסינון של סודות מתבצע בהגשה (``mcp_server.primer``)
    ולא כאן במכוון: משתמש שהדביק מפתח בטעות עדיין רואה בשדה מה שהוא הדביק
    ויכול למחוק אותו, במקום שהערך יוחלף בשקט ב-``***REDACTED***`` ויימחק לו.
    """
    user_id = _agent_instructions_user_id()
    if user_id is None:
        return jsonify({"ok": False, "error": "נדרש להתחבר"}), 401

    data = request.get_json(silent=True) or {}
    if "text" not in data:
        return jsonify({"ok": False, "error": "חסר שדה text"}), 400

    text = data.get("text")
    if text is None:
        text = ""
    if not isinstance(text, str):
        return jsonify({"ok": False, "error": "text חייב להיות מחרוזת"}), 400

    # נרמול סופי שורה: \r\n מדפדפן מנפח את הגודל ומזייף את מונה הבייטים ב-UI.
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()

    if len(text) > AGENT_INSTRUCTIONS_MAX_CHARS:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": (
                        f"ההוראות ארוכות מדי ({len(text):,} תווים). "
                        f"המקסימום הוא {AGENT_INSTRUCTIONS_MAX_CHARS:,} תווים."
                    ),
                }
            ),
            400,
        )

    helpers = _get_app_helpers()
    try:
        db = helpers.get_db()
        db.user_preferences.update_one(
            {"user_id": user_id},
            {"$set": {"agent_instructions": text}},
            upsert=True,
        )
    except Exception:
        logger.warning("failed to save agent instructions", exc_info=True)
        return jsonify({"ok": False, "error": "שגיאה בשמירת ההוראות"}), 500

    size = len(text.encode("utf-8"))
    return jsonify(
        {
            "ok": True,
            "bytes": size,
            # ההגשה חותכת ב-24KB. מחזירים את הדגל כדי שה-UI יוכל להתריע מיד
            # אחרי שמירה, ולא רק דרך שורה שרק הסוכן רואה.
            "will_truncate": size > AGENT_PRIMER_MAX_BYTES,
        }
    )


@settings_bp.route("/api/settings/attention", methods=["PUT"])
def api_update_attention_settings():
    """Update attention widget settings."""
    if "user_id" not in session:
        return jsonify({"error": "נדרש להתחבר"}), 401

    helpers = _get_app_helpers()
    user_id = session["user_id"]
    data = request.get_json() or {}

    allowed_fields = {
        "enabled",
        "stale_days",
        "max_items_per_group",
        "show_missing_description",
        "show_missing_tags",
        "show_stale_files",
    }

    updates = {}
    for field in allowed_fields:
        if field in data:
            value = data[field]
            try:
                if field == "stale_days":
                    value = min(max(int(value), 7), 365)
                elif field == "max_items_per_group":
                    value = min(max(int(value), 3), 50)
                elif field in (
                    "enabled",
                    "show_missing_description",
                    "show_missing_tags",
                    "show_stale_files",
                ):
                    # Proper boolean parsing - handle both JSON booleans and string values
                    if isinstance(value, bool):
                        pass  # Already a boolean
                    elif isinstance(value, str):
                        if value.lower() in ("true", "1", "yes", "on"):
                            value = True
                        elif value.lower() in ("false", "0", "no", "off", ""):
                            value = False
                        else:
                            raise ValueError(f"Invalid boolean string: {value}")
                    else:
                        value = bool(value)
            except (ValueError, TypeError):
                return jsonify({"ok": False, "error": f"Invalid value for {field}"}), 400
            updates[f"attention_settings.{field}"] = value

    if updates:
        db = helpers.get_db()
        db.user_preferences.update_one(
            {"user_id": user_id}, {"$set": updates}, upsert=True
        )

    return jsonify({"ok": True})
