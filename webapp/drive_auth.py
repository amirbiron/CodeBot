"""
Google Drive OAuth — חיבור Drive מהוובאפ.

Endpoints:
- GET  /api/drive/auth       — מפנה ל-Google OAuth consent screen
- GET  /api/drive/callback   — Google מחזיר authorization code
- GET  /api/drive/status     — סטטוס חיבור Drive
- POST /api/drive/disconnect — ניתוק Drive

**החיבור כאן הוא של הוובאפ בלבד** (``drive_owner.WEBAPP``): טוקנים והעדפות בשדות משלו, נפרדים מהחיבור של הבוט. חיבור, ניתוק ומצב שמוצג כאן לא נוגעים בבוט — ראו drive_owner.py.

**קוד ה-state נשמר בשרת, לא ב-session.** ה-session של הוובאפ הוא cookie חתום, וב-session קבוע (``session.permanent``) Flask שולח אותו מחדש בכל תשובה — ``SessionInterface.should_set_cookie`` מחזיר ``session.modified or (session.permanent and SESSION_REFRESH_EACH_REQUEST)`` (Flask 3.1.2, ``flask/sessions.py``). בקשה שיוצאת במקביל ללחיצה על "חבר" — שמירת מצב העבודה ב-``beforeunload`` ב-``base.html`` — נושאת את ה-cookie שלפני הלחיצה, ואם התשובה שלה מגיעה אחרי ההפניה לגוגל, הדפדפן שומר אותה ומה שנכתב ל-session נמחק. זה הסדר שנראה בלוגים של ניסיון החיבור מחדש ב-4.10.2026 (21:47 UTC): ‏``POST /api/ui_prefs`` התחילה לפני ההפניה של ``/api/drive/auth`` והסתיימה כ-100ms אחריה, והחיבור לא נקלט. לכן ה-state נשמר במסמך המשתמש (``_OAUTH_STATE_FIELD``): רק ה-hash שלו, לשימוש אחד, עם תוקף (``_OAUTH_STATE_TTL``). ``tests/test_webapp_drive_oauth_state.py`` משחזר את המרוץ מול Flask האמיתי.

**כל דחייה בחזרה מגוגל נרשמת** באירוע ``webapp_drive_callback_rejected`` עם ``reason``. ‏state, ‏code, טוקנים וגוף התשובה של גוגל לא נרשמים — ``tests/test_webapp_drive_oauth_state.py`` בודק את זה אחרי כל טסט בקובץ.
"""
from __future__ import annotations

import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Optional

from flask import Blueprint, Response, jsonify, redirect, request, session
from pymongo.errors import PyMongoError

from drive_owner import WEBAPP as DRIVE_OWNER, drive_fields
from mcp_server.token_store import hash_token

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

# docs:drive-oauth-state:start — הקטע מוטמע בתיעוד (docs/services/google_drive_service.rst); אל תסיר את הסימון
# השדה במסמך המשתמש שמחזיק את ה-state של חיבור שבתהליך: {"state_hash", "expires_at"}.
# כותב אחד (``drive_auth``) וקורא אחד (``drive_callback``), שניהם כאן.
_OAUTH_STATE_FIELD = "webapp_drive_oauth"
_OAUTH_STATE_TTL = timedelta(minutes=10)
# docs:drive-oauth-state:end

_REJECTED_EVENT = "webapp_drive_callback_rejected"

# קוד שגיאה של OAuth לפי RFC 6749 (סעיפים 4.1.2.1 ו-5.2) הוא מילה באותיות קטנות עם קו תחתון.
# הארוך שמוגדר שם, ``unsupported_response_type``, באורך 25 תווים; התקרה היא פי 2 ממנו.
_OAUTH_ERROR_CODE_RE = re.compile(r"[a-z_]{1,50}")


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


def _store_oauth_state(db, user_id: int, state: str) -> bool:
    """שומר את ה-state של החיבור שמתחיל עכשיו, ומחליף state קודם אם היה.

    נשמר רק ``hash_token(state)`` — אותו hash שמשמש את טוקני ה-MCP, ומאותה סיבה: ``secrets.token_urlsafe(32)`` נושא 256 ביט, ולכן SHA-256 יחיד מספיק. גם מי שקורא את המסד לא יכול להשתמש ב-state שמור.

    מחזיר ``True`` רק כשהכתיבה באמת נכתבה (נמצא מסמך או נוצר אחד). שגיאת מסד עולה כ-``PyMongoError``.
    """
    record = {
        "state_hash": hash_token(state),
        "expires_at": datetime.now(timezone.utc) + _OAUTH_STATE_TTL,
    }
    res = db.db.users.update_one(
        {"user_id": user_id},
        {"$set": {_OAUTH_STATE_FIELD: record}},
        upsert=True,
    )
    # ‏matched_count זורק על כתיבה שלא אושרה (w=0) — ולכן acknowledged נבדק ראשון (pymongo 4.15.3, results.py)
    return bool(res.acknowledged) and (res.matched_count == 1 or res.upserted_id is not None)


def _consume_oauth_state(db, user_id: int, state: str) -> bool:
    """צורך את ה-state שחזר מגוגל: ``True`` אם הוא של המשתמש הזה ועדיין בתוקף.

    הבדיקה והמחיקה הן פעולה אחת (``find_one_and_update`` עם ``$unset``), ולכן כל state עובד פעם אחת בלבד — גם כששתי חזרות מגיעות יחד, רק אחת מוצאת אותו. ``find_one_and_update`` מחזיר ``None`` כשאף מסמך לא תאם (pymongo 4.15.3, ``synchronous/collection.py``).

    ה-state נבדק מול המשתמש שב-session: מי שמתחיל חיבור לעצמו לא יכול לשלוח למישהו אחר קישור שיחבר את הדרייב שלו לחשבון של המתחיל (RFC 6749, סעיף 10.12).

    שגיאת מסד עולה כ-``PyMongoError``.
    """
    doc = db.db.users.find_one_and_update(
        {
            "user_id": user_id,
            f"{_OAUTH_STATE_FIELD}.state_hash": hash_token(state),
            f"{_OAUTH_STATE_FIELD}.expires_at": {"$gt": datetime.now(timezone.utc)},
        },
        {"$unset": {_OAUTH_STATE_FIELD: ""}},
        projection={"_id": 1},
    )
    return doc is not None


def _oauth_error_code(value: Any) -> Optional[str]:
    """קוד שגיאה שהגיע מגוגל, מוכן לרישום: הקוד עצמו אם הוא בצורה של קוד OAuth, ``"unrecognized"`` אחרת.

    הערך הגיע מבחוץ, ולכן הוא לא נרשם כמו שהוא אם הוא ארוך, מכיל תווים אחרים או אינו מחרוזת — הוא מסורב, לא מקוצץ ולא מנוקה (בניגוד ל-``resilience.sanitize_label``, שמנקה ערך שאנחנו יצרנו).
    """
    if value is None:
        return None
    if isinstance(value, str) and _OAUTH_ERROR_CODE_RE.fullmatch(value):
        return value
    return "unrecognized"


def _reject(
    reason: str,
    *,
    user_id: Optional[int] = None,
    google_error: Optional[str] = None,
    http_status: Optional[int] = None,
    error_type: Optional[str] = None,
) -> None:
    """רושם דחייה של חזרה מגוגל.

    רשימת השדות סגורה בכוונה, ורק עם מה שבטוח לרישום: מזהה המשתמש, קוד שגיאה של גוגל אחרי ``_oauth_error_code``, סטטוס HTTP ושם של סוג חריגה. אין פרמטר שדרכו אפשר להעביר state, code, טוקן או גוף תשובה. שדה בלי ערך לא נכנס לאירוע.

    המטען נבנה כאן עם מפתחות קבועים, כי ``emit_event`` מקבל גם פרמטרים משלו (``event``, ``severity``) — ``tests/test_event_alert_dispatch.py`` אוסר להעביר אליו ב-``**`` מטען שאי אפשר לקרוא את המפתחות שלו בנקודת הקריאה.
    """
    payload: dict[str, Any] = {"reason": reason}
    if user_id is not None:
        payload["user_id"] = user_id
    if google_error is not None:
        payload["google_error"] = google_error
    if http_status is not None:
        payload["http_status"] = http_status
    if error_type is not None:
        payload["error_type"] = error_type
    emit_event(_REJECTED_EVENT, severity="warn", **payload)


def _fetch_google_email(req, access_token: str) -> Optional[str]:
    """המייל של חשבון Google, לתצוגה בלבד. כשל אינו מבטל את החיבור — הוא נרשם ומוחזר ``None``."""
    try:
        resp = req.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        info = resp.json()
    except req.RequestException as e:
        # כולל גוף שאינו JSON: requests.exceptions.JSONDecodeError יורש מ-RequestException (requests 2.32.5).
        # רק סוג החריגה — בלי ההודעה, כדי ששום דבר מהבקשה לא ייכנס ללוג
        logger.warning("webapp_drive_userinfo_failed error_type=%s", type(e).__name__)
        return None
    email = info.get("email") if isinstance(info, dict) else None
    return email if isinstance(email, str) and email else None


@drive_auth_bp.route("/api/drive/auth")
@_require_auth
def drive_auth():
    """מפנה את המשתמש ל-Google OAuth consent screen."""
    if not GOOGLE_CLIENT_ID:
        return jsonify({"ok": False, "error": "Google OAuth לא מוגדר"}), 500

    user_id = int(session["user_id"])
    # CSRF protection via state — נשמר בשרת לפני ההפניה (ראו docstring של המודול)
    state = secrets.token_urlsafe(32)
    try:
        stored = _store_oauth_state(_get_db(), user_id, state)
    except PyMongoError:
        logger.exception("webapp_drive_state_store_error")
        stored = False
    if not stored:
        # בלי state שמור החזרה מגוגל תידחה בוודאות — לא שולחים את המשתמש לשם בכלל
        emit_event("webapp_drive_auth_failed", severity="error", reason="state_store_failed", user_id=user_id)
        return jsonify({"ok": False, "error": "לא ניתן להתחיל חיבור ל-Drive כרגע, נסה שוב"}), 500

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


# GET בכוונה: לכאן גוגל מפנה את הדפדפן בחזרה (RFC 6749, סעיף 4.1.2). מה שמונע הפעלה בלי לחיצה
# (תצוגה מקדימה של קישור, prefetch) הוא ה-state החד-פעמי, שנבדק לפני כל פעולה.
@drive_auth_bp.route("/api/drive/callback")
def drive_callback():
    """Google מחזיר authorization code — מחליפים לטוקנים."""
    # redirect-based auth check — הדפדפן מגיע ישירות, לא AJAX
    if "user_id" not in session:
        _reject("session_missing")
        return _settings_redirect(f"drive_error={_url_encode('session_expired')}")
    user_id = int(session["user_id"])

    import requests as req

    # CSRF check — מול ה-state ששמור בשרת, לשימוש אחד
    state = request.args.get("state", "")
    if not state:
        _reject("state_missing", user_id=user_id)
        return _settings_redirect(f"drive_error={_url_encode('csrf')}")
    db = _get_db()
    try:
        consumed = _consume_oauth_state(db, user_id, state)
    except PyMongoError:
        logger.exception("webapp_drive_state_consume_error")
        _reject("state_check_failed", user_id=user_id)
        return _settings_redirect(f"drive_error={_url_encode('state_check_failed')}")
    if not consumed:
        _reject("state_not_found_or_expired", user_id=user_id)
        return _settings_redirect(f"drive_error={_url_encode('csrf')}")

    error = request.args.get("error")
    if error:
        _reject("google_error", user_id=user_id, google_error=_oauth_error_code(error))
        return _settings_redirect(f"drive_error={_url_encode(error)}")

    code = request.args.get("code")
    if not code:
        _reject("code_missing", user_id=user_id)
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
    except req.RequestException as e:
        _reject("token_exchange_failed", user_id=user_id, error_type=type(e).__name__)
        return _settings_redirect(f"drive_error={_url_encode('token_exchange')}")
    try:
        tokens = resp.json()
    except req.exceptions.JSONDecodeError:
        tokens = None
    google_error = _oauth_error_code(tokens.get("error")) if isinstance(tokens, dict) else None
    if resp.status_code >= 400:
        _reject("token_exchange_failed", user_id=user_id, http_status=resp.status_code, google_error=google_error)
        return _settings_redirect(f"drive_error={_url_encode('token_exchange')}")
    if not isinstance(tokens, dict):
        _reject("token_response_invalid", user_id=user_id, http_status=resp.status_code)
        return _settings_redirect(f"drive_error={_url_encode('token_exchange')}")
    access_token = tokens.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        _reject("no_access_token", user_id=user_id, google_error=google_error)
        return _settings_redirect(f"drive_error={_url_encode('no_token')}")

    # שמירת טוקנים — לחיבור של הוובאפ בלבד
    token_data = {
        "access_token": access_token,
        "refresh_token": tokens.get("refresh_token", ""),
        "token_type": tokens.get("token_type", "Bearer"),
        "expires_in": tokens.get("expires_in", 3600),
        "scope": tokens.get("scope", GOOGLE_OAUTH_SCOPES),
    }
    from services.google_drive_service import save_tokens
    # save_tokens אינו זורק בכשל מסד — הוא מחזיר False (Repository.save_drive_tokens), ולכן נבדק הערך
    if not save_tokens(user_id, token_data, owner=DRIVE_OWNER):
        _reject("save_failed", user_id=user_id)
        return _settings_redirect(f"drive_error={_url_encode('save_failed')}")

    # Get user email for display
    email = _fetch_google_email(req, access_token)
    if email:
        try:
            # $set ישיר — לא save_drive_prefs שעושה read-modify-write ויכול לדרוס sentinel
            db.db.users.update_one(
                {"user_id": user_id},
                {"$set": {f"{drive_fields(DRIVE_OWNER).prefs}.drive_email": email}},
            )
        except PyMongoError:
            # המייל הוא לתצוגה בלבד; החיבור עצמו כבר נשמר
            logger.warning("webapp_drive_email_save_failed", exc_info=True)

    emit_event("webapp_drive_connected", user_id=user_id)
    return _settings_redirect("drive_connected=1")


@drive_auth_bp.route("/api/drive/status")
@_require_auth
def drive_status():
    """מחזיר סטטוס חיבור Drive — של הוובאפ בלבד."""
    user_id = int(session["user_id"])
    db = _get_db()

    # שתי הקריאות לא זורקות: בכשל מסד הן רושמות אירוע (db_get_drive_*_error) ומחזירות None
    tokens = db.get_drive_tokens(user_id, owner=DRIVE_OWNER)
    connected = bool(tokens and tokens.get("access_token"))
    prefs = db.get_drive_prefs(user_id, owner=DRIVE_OWNER)
    if not isinstance(prefs, dict):
        prefs = {}

    return jsonify({
        "ok": True,
        "connected": connected,
        "email": prefs.get("drive_email"),
        "schedule": prefs.get("schedule_key"),
        "last_backup_at": prefs.get("last_backup_at"),
        "schedule_next_at": prefs.get("schedule_next_at"),
    })


@drive_auth_bp.route("/api/drive/disconnect", methods=["POST"])
@_require_auth
def drive_disconnect():
    """מנתק את חיבור ה-Drive של הוובאפ (החיבור של הבוט לא משתנה)."""
    user_id = int(session["user_id"])
    db = _get_db()
    prefs_field = drive_fields(DRIVE_OWNER).prefs

    # קודם מכבים את התזמון ורק אחר כך מוחקים את הטוקנים: כשל באמצע משאיר "מחובר בלי תזמון",
    # ולא "תזמון בלי חיבור" שהמתזמן ינסה להריץ שוב ושוב.
    try:
        db.db.users.update_one(
            {"user_id": user_id},
            {"$set": {
                f"{prefs_field}.schedule_key": "off",
                f"{prefs_field}.schedule_next_at": None,
                f"{prefs_field}.drive_email": None,
            }},
        )
    except PyMongoError:
        logger.exception("webapp_drive_disconnect_prefs_failed")
        return jsonify({"ok": False, "error": "שגיאה בניתוק Drive"}), 500
    # delete_drive_tokens אינו זורק בכשל מסד — הוא מחזיר False, ולכן נבדק הערך
    if not db.delete_drive_tokens(user_id, owner=DRIVE_OWNER):
        return jsonify({"ok": False, "error": "שגיאה בניתוק Drive"}), 500
    emit_event("webapp_drive_disconnected", user_id=user_id)
    return jsonify({"ok": True})


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
