"""
Google Drive OAuth — חיבור Drive מהוובאפ.

Endpoints:
- GET  /api/drive/auth       — מפנה ל-Google OAuth consent screen
- GET  /api/drive/callback   — Google מחזיר authorization code
- GET  /api/drive/status     — סטטוס חיבור Drive
- POST /api/drive/disconnect — ניתוק Drive
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
from datetime import datetime, timezone
from functools import wraps

from flask import Blueprint, Response, jsonify, redirect, request, session, url_for

logger = logging.getLogger(__name__)

try:
    from observability import emit_event
except Exception:
    def emit_event(event: str, severity: str = "info", **fields):
        return None

drive_auth_bp = Blueprint("drive_auth", __name__)

# Google OAuth config
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_OAUTH_SCOPES = os.getenv("GOOGLE_OAUTH_SCOPES", "https://www.googleapis.com/auth/drive.file")
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v1/userinfo"


def _require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"ok": False, "error": "נדרש להתחבר"}), 401
        return f(*args, **kwargs)
    return decorated


def _get_db():
    from database import db as _db
    return _db


def _get_redirect_uri():
    """חישוב redirect URI דינמי."""
    base = os.getenv("WEBAPP_URL", "").rstrip("/")
    if not base:
        base = request.url_root.rstrip("/")
    return f"{base}/api/drive/callback"


@drive_auth_bp.route("/api/drive/auth")
@_require_auth
def drive_auth():
    """מפנה את המשתמש ל-Google OAuth consent screen."""
    if not GOOGLE_CLIENT_ID:
        return jsonify({"ok": False, "error": "Google OAuth לא מוגדר"}), 500

    # CSRF protection via state
    state = secrets.token_urlsafe(32)
    session["drive_oauth_state"] = state

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": _get_redirect_uri(),
        "response_type": "code",
        "scope": GOOGLE_OAUTH_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }

    auth_url = GOOGLE_AUTH_URL + "?" + "&".join(f"{k}={_url_encode(v)}" for k, v in params.items())
    return redirect(auth_url)


@drive_auth_bp.route("/api/drive/callback")
def drive_callback():
    """Google מחזיר authorization code — מחליפים לטוקנים."""
    # redirect-based auth check — הדפדפן מגיע ישירות, לא AJAX
    if "user_id" not in session:
        return _settings_redirect(f"drive_error={_url_encode('session_expired')}")

    import requests as req

    # CSRF check
    state = request.args.get("state", "")
    expected_state = session.pop("drive_oauth_state", "")
    if not state or not expected_state or state != expected_state:
        return _settings_redirect(f"drive_error={_url_encode('csrf')}")

    error = request.args.get("error")
    if error:
        logger.warning("Drive OAuth error: %s", error)
        return _settings_redirect(f"drive_error={_url_encode(error)}")

    code = request.args.get("code")
    if not code:
        return _settings_redirect(f"drive_error={_url_encode('no_code')}")

    # Exchange code for tokens
    try:
        resp = req.post(GOOGLE_TOKEN_URL, data={
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": _get_redirect_uri(),
        }, timeout=15)
        resp.raise_for_status()
        tokens = resp.json()
    except Exception as e:
        logger.exception("Drive token exchange failed")
        return _settings_redirect(f"drive_error={_url_encode('token_exchange')}")

    if "access_token" not in tokens:
        logger.error("No access_token in response: %s", tokens.get("error"))
        return _settings_redirect(f"drive_error={_url_encode('no_token')}")

    # שמירת טוקנים
    user_id = session["user_id"]
    db = _get_db()

    token_data = {
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token", ""),
        "token_type": tokens.get("token_type", "Bearer"),
        "expires_in": tokens.get("expires_in", 3600),
        "scope": tokens.get("scope", GOOGLE_OAUTH_SCOPES),
    }

    try:
        from services.google_drive_service import save_tokens
        save_tokens(int(user_id), token_data)
    except Exception:
        # fallback — שמירה ישירה
        try:
            db.save_drive_tokens(int(user_id), token_data)
        except Exception:
            logger.exception("Failed to save Drive tokens")
            return _settings_redirect(f"drive_error={_url_encode('save_failed')}")

    # Get user email for display
    try:
        user_info = req.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
            timeout=10,
        ).json()
        email = user_info.get("email", "")
        if email:
            try:
                # $set ישיר — לא save_drive_prefs שעושה read-modify-write ויכול לדרוס sentinel
                db.db.users.update_one(
                    {"user_id": int(user_id)},
                    {"$set": {"drive_prefs.drive_email": email}},
                )
            except Exception:
                pass
    except Exception:
        pass

    emit_event("webapp_drive_connected", user_id=int(user_id))
    return _settings_redirect("drive_connected=1")


@drive_auth_bp.route("/api/drive/status")
@_require_auth
def drive_status():
    """מחזיר סטטוס חיבור Drive."""
    user_id = session["user_id"]
    db = _get_db()

    connected = False
    email = None
    schedule = None
    last_backup = None
    schedule_next = None

    try:
        tokens = db.get_drive_tokens(int(user_id))
        connected = bool(tokens and tokens.get("access_token"))
    except Exception:
        pass

    try:
        prefs = db.get_drive_prefs(int(user_id)) or {}
        email = prefs.get("drive_email")
        schedule = prefs.get("schedule_key") or prefs.get("schedule")
        if isinstance(schedule, dict):
            schedule = schedule.get("key") or schedule.get("value")
        last_backup = prefs.get("last_backup_at")
        schedule_next = prefs.get("schedule_next_at")
    except Exception:
        pass

    return jsonify({
        "ok": True,
        "connected": connected,
        "email": email,
        "schedule": schedule,
        "last_backup_at": last_backup,
        "schedule_next_at": schedule_next,
    })


@drive_auth_bp.route("/api/drive/disconnect", methods=["POST"])
@_require_auth
def drive_disconnect():
    """מנתק חיבור Drive."""
    user_id = session["user_id"]
    db = _get_db()

    try:
        db.delete_drive_tokens(int(user_id))
        # מנקה גם schedule
        try:
            db.save_drive_prefs(int(user_id), {
                "schedule_key": "off",
                "schedule_next_at": None,
                "drive_email": None,
            })
        except Exception:
            pass
        emit_event("webapp_drive_disconnected", user_id=int(user_id))
        return jsonify({"ok": True})
    except Exception as e:
        logger.exception("Error disconnecting Drive")
        return jsonify({"ok": False, "error": "שגיאה בניתוק Drive"}), 500


# --- Helpers ---

def _url_encode(val: str) -> str:
    """URL-encode a string."""
    from urllib.parse import quote
    return quote(str(val), safe="")


def _settings_redirect(query: str) -> Response:
    """Redirect back to settings page with query params."""
    base = os.getenv("WEBAPP_URL", "").rstrip("/")
    if not base:
        base = request.url_root.rstrip("/")
    return redirect(f"{base}/settings?{query}#backup-section")
