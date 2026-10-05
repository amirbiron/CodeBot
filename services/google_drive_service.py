from __future__ import annotations

import io
import json
import time
from datetime import datetime, timedelta, timezone
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List
import zipfile as _zipfile
from types import SimpleNamespace as _SimpleNamespace

from http_sync import request as http_request
import requests  # for precise exception handling
try:
    from googleapiclient.discovery import build  # type: ignore
    from googleapiclient.errors import HttpError  # type: ignore
    from googleapiclient.http import MediaIoBaseUpload, MediaFileUpload  # type: ignore
    from google.oauth2.credentials import Credentials  # type: ignore
    from google.auth.transport.requests import Request  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    build = None  # type: ignore[assignment]

    class _HttpErrorStub(Exception):
        """Fallback HttpError replacement when googleapiclient is unavailable."""

        def __init__(self, resp=None, content=None, *args, **kwargs):
            msg = ""
            try:
                status = getattr(resp, "status", "")
                reason = getattr(resp, "reason", "")
                msg = f"HTTP {status} {reason}".strip()
            except Exception:
                msg = ""
            super().__init__(msg or "HttpError")
            self.resp = resp
            self.content = content

    HttpError = _HttpErrorStub  # type: ignore[assignment]
    MediaIoBaseUpload = None  # type: ignore[assignment]
    MediaFileUpload = None  # type: ignore[assignment]
    Credentials = None  # type: ignore[assignment]
    Request = None  # type: ignore[assignment]

from config import config
from database import db
import hashlib
from file_manager import backup_manager
import logging
import random


DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
# ברירת מחדל בהיעדר קונפיג מלא (למשל בטסטים שמזריקים Stub לקונפיג)
DEFAULT_GOOGLE_OAUTH_SCOPES = "https://www.googleapis.com/auth/drive.file"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# קוד שגיאה של Drive בגוף התשובה (``errors[0].reason`` או ``error.status``) הוא מילה אחת — ``storageQuotaExceeded``, ``PERMISSION_DENIED``. טקסט חופשי (``error.message``) לא נרשם.
_DRIVE_ERROR_CODE_RE = re.compile(r"[A-Za-z_]{1,64}")


def _log_drive_call_failed(op: str, user_id: int, *, owner: str, error: Optional[Exception] = None) -> None:
    """רושם פעולת Drive שנכשלה ומחזירה ``None`` בלי לזרוק, כדי שהסיבה לא תיעלם יחד עם החריגה שנבלעה.

    נרשמים שם הפעולה, השירות, המשתמש, סוג החריגה, סטטוס ה-HTTP וקוד השגיאה של גוגל — ולא הטקסט של החריגה: הטקסט של ``HttpError`` הוא כתובת הבקשה והודעת השגיאה של גוגל כמו שהיא (``HttpError.__repr__``, google-api-python-client 2.185.0). קוד שגיאה שאינו מילה אחת נרשם כ-``unrecognized``.
    """
    status: Optional[int] = None
    reason: Optional[str] = None
    if error is not None:
        status, raw_reason = _parse_http_error_status_reason(error)
        if raw_reason is not None:
            reason = raw_reason if _DRIVE_ERROR_CODE_RE.fullmatch(raw_reason) else "unrecognized"
    logging.getLogger(__name__).warning(
        "drive_call_failed op=%s owner=%s user_id=%s error_type=%s http_status=%s drive_reason=%s",
        op,
        owner,
        user_id,
        type(error).__name__ if error is not None else None,
        status,
        reason,
    )


def start_device_authorization(user_id: int) -> Dict[str, Any]:
    """Starts OAuth Device Authorization flow for Google Drive.

    Returns a dict with: verification_url, user_code, device_code, interval, expires_in.
    """
    client_id = getattr(config, "GOOGLE_CLIENT_ID", None)
    if not client_id:
        raise RuntimeError("GOOGLE_CLIENT_ID is not set")
    scopes = getattr(config, "GOOGLE_OAUTH_SCOPES", DEFAULT_GOOGLE_OAUTH_SCOPES) or DEFAULT_GOOGLE_OAUTH_SCOPES
    if isinstance(scopes, (list, tuple, set)):
        cleaned_scopes = []
        for scope in scopes:
            if scope is None:
                continue
            scope_text = str(scope).strip()
            if scope_text:
                cleaned_scopes.append(scope_text)
        scope_str = " ".join(cleaned_scopes) or DEFAULT_GOOGLE_OAUTH_SCOPES
    else:
        scope_str = str(scopes).strip() or DEFAULT_GOOGLE_OAUTH_SCOPES
    payload = {
        "client_id": client_id,
        "scope": scope_str,
    }
    # Some Google OAuth client types (e.g., Web) require client_secret
    if getattr(config, "GOOGLE_CLIENT_SECRET", None):
        payload["client_secret"] = config.GOOGLE_CLIENT_SECRET  # type: ignore[index]
    try:
        response = http_request('POST', DEVICE_CODE_URL, data=payload, timeout=15)
        # If unauthorized/invalid_client, surface clearer message
        if response.status_code >= 400:
            try:
                err = response.json()
            except Exception:
                err = {"error": f"HTTP {response.status_code}"}
            msg = err.get("error_description") or err.get("error") or f"HTTP {response.status_code}"
            raise RuntimeError(f"Device auth start failed: {msg}")
        data = response.json()
    except requests.RequestException as e:
        # Network/HTTP-layer errors only; אל תמסך שגיאות JSON/קוד
        raise RuntimeError("Device auth request error") from e
    # Persist device flow state in memory is handled by caller; tokens saved on success.
    return {
        "verification_url": data.get("verification_url") or data.get("verification_uri"),
        "user_code": data.get("user_code"),
        "device_code": data.get("device_code"),
        "interval": int(data.get("interval", 5)),
        "expires_in": int(data.get("expires_in", 1800)),
    }


def poll_device_token(device_code: str) -> Optional[Dict[str, Any]]:
    """Attempts a single token exchange for a device_code.

    Returns:
        - dict with tokens on success
        - None if authorization is still pending or needs to slow down
        - dict with {"error": <code>, "error_description": <str>} on user-facing errors
    """
    client_id = getattr(config, "GOOGLE_CLIENT_ID", None)
    if not client_id:
        raise RuntimeError("GOOGLE_CLIENT_ID is not set")
    payload = {
        "client_id": client_id,
        "device_code": device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    }
    # Include client_secret if configured to satisfy clients that require it
    if getattr(config, "GOOGLE_CLIENT_SECRET", None):
        payload["client_secret"] = config.GOOGLE_CLIENT_SECRET  # type: ignore[index]
    # Use pooled HTTP client (http_sync); tests can monkeypatch gds.http_request
    resp = http_request('POST', TOKEN_URL, data=payload, timeout=20)
    if resp.status_code >= 400:
        # Try to parse structured OAuth error
        try:
            data = resp.json()
            err = (data or {}).get("error")
            desc = (data or {}).get("error_description")
        except Exception:
            err, desc = None, None
        # Pending/slowdown are not errors for the UI
        if err in {"authorization_pending", "slow_down"}:
            logging.getLogger(__name__).debug("Drive auth pending/slow_down")
            return None
        # Access denied / expired / invalid_grant are user-facing errors
        if err in {"access_denied", "expired_token", "invalid_grant",
                    "invalid_request", "invalid_client"}:
            return {"error": err or "bad_request", "error_description": desc}
        # Unknown 400 – return a generic error record
        logging.getLogger(__name__).warning(
            f"Drive auth error: {err} {desc}"
        )
        return {"error": err or f"http_{resp.status_code}", "error_description": desc or "token endpoint error"}
    # Success
    tokens = resp.json()
    tokens["expiry"] = (_now_utc() + timedelta(seconds=int(tokens.get("expires_in", 3600)))).isoformat()
    return tokens


def save_tokens(user_id: int, tokens: Dict[str, Any], *, owner: str) -> bool:
    """Save OAuth tokens, preserving existing refresh_token if missing.

    Some OAuth exchanges (and refreshes) do not return refresh_token again.
    We merge with existing tokens to avoid wiping the refresh_token.

    ``owner`` הוא השירות שהחיבור שלו (``drive_owner.BOT`` / ``drive_owner.WEBAPP``): המיזוג נעשה רק מול הטוקנים של אותו שירות, ולכן refresh_token של שירות אחד לא נכנס לחיבור של השני (נבדק בשני הכיוונים ב-``tests/test_drive_connection_separation.py``).
    """
    existing = _load_tokens(user_id, owner=owner) or {}
    merged: Dict[str, Any] = dict(existing)
    merged.update(tokens or {})
    if not merged.get("refresh_token") and existing.get("refresh_token"):
        merged["refresh_token"] = existing["refresh_token"]
    return db.save_drive_tokens(user_id, merged, owner=owner)


def _load_tokens(user_id: int, *, owner: str) -> Optional[Dict[str, Any]]:
    return db.get_drive_tokens(user_id, owner=owner)


def _credentials_from_tokens(tokens: Dict[str, Any]) -> Credentials:
    if Credentials is None:
        raise RuntimeError("Google libraries are not installed")
    client_id = getattr(config, "GOOGLE_CLIENT_ID", None)
    client_secret = getattr(config, "GOOGLE_CLIENT_SECRET", None)
    scopes_cfg = tokens.get("scope") or getattr(config, "GOOGLE_OAUTH_SCOPES", DEFAULT_GOOGLE_OAUTH_SCOPES)
    if isinstance(scopes_cfg, (list, tuple, set)):
        scopes_list = [str(s).strip() for s in scopes_cfg if str(s).strip()]
    else:
        scopes_list = str(scopes_cfg or "").split()
    if not scopes_list:
        scopes_list = DEFAULT_GOOGLE_OAUTH_SCOPES.split()
    return Credentials(
        token=tokens.get("access_token"),
        refresh_token=tokens.get("refresh_token"),
        token_uri=TOKEN_URL,
        client_id=client_id,
        client_secret=client_secret or None,
        scopes=scopes_list,
    )


def _ensure_valid_credentials(user_id: int, *, owner: str) -> Optional[Credentials]:
    tokens = _load_tokens(user_id, owner=owner)
    if not tokens:
        logging.getLogger(__name__).warning("Drive creds missing for user; need login")
        return None
    try:
        creds = _credentials_from_tokens(tokens)
    except Exception as e:
        _log_drive_call_failed("credentials", user_id, owner=owner, error=e)
        return None
    if creds.expired and creds.refresh_token:
        if Request is None:
            return None
        # Retry a few times on transient refresh failures
        attempts = 0
        while attempts < 3:
            try:
                creds.refresh(Request())  # type: ignore[misc]
                # Persist updated access token and expiry
                updated = {
                    "access_token": creds.token,
                    "refresh_token": creds.refresh_token,
                    "token_type": "Bearer",
                    "scope": " ".join(creds.scopes or []),
                    "expires_in": int((creds.expiry - _now_utc()).total_seconds()) if creds.expiry else 3600,
                    "expiry": creds.expiry.isoformat() if creds.expiry else (_now_utc() + timedelta(hours=1)).isoformat(),
                }
                save_tokens(user_id, updated, owner=owner)
                break
            except Exception as e:
                attempts += 1
                # invalid_grant and similar permanent errors — stop early
                text = str(e).lower()
                if "invalid_grant" in text or "access_denied" in text:
                    logging.getLogger(__name__).warning("Drive token refresh invalid_grant; user re-auth required")
                    return None
                # transient — short jittered backoff
                try:
                    time.sleep(0.3 * attempts)
                except Exception:
                    pass
        else:
            logging.getLogger(__name__).exception("Drive token refresh failed after retries")
            return None
    return creds


# המפתח הוא (שירות, משתמש): לכל שירות חיבור משלו, ושירות Drive שנבנה מהטוקנים של אחד אסור שיוחזר לשני.
# הערך הוא (שירות, זמן בנייה, טביעת האישורים שהוא נבנה מהם) — ראו ``_credentials_fingerprint``.
_SERVICE_CACHE: Dict[Tuple[str, int], Tuple[Any, float, str]] = {}


def _service_cache_key(user_id: int, *, owner: str) -> Tuple[str, int]:
    """המפתח היחיד של ``_SERVICE_CACHE`` — גם הכתיבה וגם הביטול עוברים כאן, כדי שביטול לא יחטיא את המפתח שנכתב."""
    return (owner, int(user_id))


def _credentials_fingerprint(creds: Any) -> str:
    """טביעה של האישורים שמהם נבנה שירות: SHA-256 של ה-access token וה-refresh token, ולא הטוקנים עצמם.

    ``get_drive_service`` משווה אותה לאישורים שנטענו עכשיו מהמסד, ולכן שירות שנבנה מטוקנים שהוחלפו — חיבור מחדש, או רענון שנשמר — לא מוחזר מהמטמון. ההשוואה נעשית בזמן הקריאה ולא בביטול בזמן הכתיבה: ביטול ב-``save_tokens`` היה מחטיא קריאה שטענה את הטוקנים הישנים לפני הכתיבה ושמרה את השירות שלה אחריה.

    ``creds`` הוא ``google.oauth2.credentials.Credentials``: ``token`` ו-``refresh_token`` מוגדרים בו תמיד (google-auth 2.41.1, ``google/auth/_credentials_base.py`` ו-``google/oauth2/credentials.py``).
    """
    material = f"{creds.token or ''}\0{creds.refresh_token or ''}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def get_drive_service(user_id: int, *, owner: str):
    if build is None:
        return None
    creds = _ensure_valid_credentials(user_id, owner=owner)
    if not creds:
        return None
    # נסה להשתמש בשירות קיים עד 5 דקות כדי למנוע יצירה חוזרת ושקעים פתוחים — רק אם נבנה מאותם אישורים
    now_ts = time.time()
    cache_key = _service_cache_key(user_id, owner=owner)
    fingerprint = _credentials_fingerprint(creds)
    try:
        cached = _SERVICE_CACHE.get(cache_key)
        if cached and cached[2] == fingerprint and (now_ts - float(cached[1])) < 300:
            return cached[0]
    except Exception:
        # רשומה פגומה במטמון היא החטאה: בונים שירות חדש ודורסים אותה
        pass
    try:
        svc = build("drive", "v3", credentials=creds, cache_discovery=False)
        try:
            _SERVICE_CACHE[cache_key] = (svc, now_ts, fingerprint)
        except Exception:
            # בלי מטמון השירות נבנה מחדש בקריאה הבאה — איטי יותר, לא שגוי
            pass
        return svc
    except Exception as e:
        _log_drive_call_failed("build_service", user_id, owner=owner, error=e)
        return None


def _get_file_metadata(service, file_id: str, fields: str = "id, name, trashed, mimeType, parents") -> Optional[Dict[str, Any]]:
    """Return file metadata or None if not found/inaccessible."""
    try:
        return service.files().get(fileId=file_id, fields=fields).execute()
    except Exception:
        return None


def ensure_folder(user_id: int, name: str, parent_id: Optional[str] = None, *, owner: str) -> Optional[str]:
    for auth_attempt in range(0, 2):
        service = get_drive_service(user_id, owner=owner)
        if not service:
            return None
        try:
            safe_name = name.replace("'", "\\'")
            q = "name = '{0}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false".format(safe_name)
            if parent_id:
                safe_parent = str(parent_id).replace("'", "\\'")
                q += f" and '{safe_parent}' in parents"
            results = service.files().list(q=q, fields="files(id, name)").execute()
            files = results.get("files", [])
            if files:
                return files[0]["id"]
            metadata = {
                "name": name,
                "mimeType": "application/vnd.google-apps.folder",
            }
            if parent_id:
                metadata["parents"] = [parent_id]
            folder = service.files().create(body=metadata, fields="id").execute()
            return folder.get("id")
        except HttpError as e:
            if auth_attempt == 0 and _is_auth_http_error(e) and _force_refresh_credentials(user_id, owner=owner):
                continue
            _log_drive_call_failed("ensure_folder", user_id, owner=owner, error=e)
            return None
        except Exception as e:
            _log_drive_call_failed("ensure_folder", user_id, owner=owner, error=e)
            return None
    return None


def get_or_create_default_folder(user_id: int, *, owner: str) -> Optional[str]:
    prefs = db.get_drive_prefs(user_id, owner=owner) or {}
    folder_id = prefs.get("target_folder_id")
    # Validate existing folder id is not trashed/deleted
    try:
        service = get_drive_service(user_id, owner=owner)
    except Exception:
        service = None
    if service and folder_id:
        meta = _get_file_metadata(service, folder_id, fields="id, trashed, mimeType")
        if meta and not bool(meta.get("trashed")) and str(meta.get("mimeType")) == "application/vnd.google-apps.folder":
            return folder_id
        # stale/trashed id — ignore and recreate below
        folder_id = None
    if folder_id:
        # No service to validate — optimistically return; upload will validate again
        return folder_id
    # Create or find non-trashed default root folder at Drive
    fid = ensure_folder(user_id, "גיבויי_קודלי", None, owner=owner)
    if fid:
        db.save_drive_prefs(user_id, {"target_folder_id": fid}, owner=owner)
    return fid


def ensure_path(user_id: int, path: str, *, owner: str) -> Optional[str]:
    """Ensure nested folders path like "Parent/Sub1/Sub2" exists; returns last folder id."""
    if not path:
        return get_or_create_default_folder(user_id, owner=owner)
    parts = [p.strip() for p in path.split('/') if p.strip()]
    parent: Optional[str] = None
    for part in parts:
        parent = ensure_folder(user_id, part, parent, owner=owner)
        if not parent:
            return None
    # Save as target folder
    db.save_drive_prefs(user_id, {"target_folder_id": parent}, owner=owner)
    return parent


def _get_root_folder(user_id: int, *, owner: str) -> Optional[str]:
    """Return user's target root folder id, validating it's active; create default if needed."""
    return get_or_create_default_folder(user_id, owner=owner)


def ensure_subpath(user_id: int, sub_path: str, *, owner: str) -> Optional[str]:
    """Ensure nested subfolders under the user's root. Does not change prefs."""
    root_id = _get_root_folder(user_id, owner=owner)
    if not root_id:
        return None
    if not sub_path:
        return root_id
    parts = [p.strip() for p in sub_path.split('/') if p.strip()]
    parent = root_id
    for part in parts:
        parent = ensure_folder(user_id, part, parent, owner=owner)
        if not parent:
            return None
    return parent


def _date_path() -> str:
    now = _now_utc()
    return f"{now.year:04d}/{now.month:02d}-{now.day:02d}"


def _date_str_ddmmyyyy() -> str:
    now = _now_utc()
    return f"{now.day:02d}-{now.month:02d}-{now.year:04d}"


def _next_version(user_id: int, key: str, *, owner: str) -> int:
    prefs = db.get_drive_prefs(user_id, owner=owner) or {}
    counters = dict(prefs.get("drive_version_counters") or {})
    current = int(counters.get(key, 0) or 0) + 1
    counters[key] = current
    db.save_drive_prefs(user_id, {"drive_version_counters": counters}, owner=owner)
    return current


def _category_label(category: str) -> str:
    mapping = {
        # For ZIP we use english label 'zip' for filename consistency
        "zip": "zip",
        "all": "הכל",
        "by_repo": "לפי_ריפו",
        "large": "קבצים_גדולים",
        "other": "שאר_קבצים",
    }
    return mapping.get(category, category)


def compute_subpath(category: str, repo_name: Optional[str] = None) -> str:
    """Return destination subpath under the user's root folder.

    Simplified structure without date-based nesting to avoid deep paths:
    - zip        -> "zip"
    - all        -> "הכל"
    - by_repo    -> "לפי_ריפו/<repo_name>"
    - large      -> "קבצים_גדולים"
    - other      -> "שאר_קבצים"
    """
    base = _category_label(category)
    if category == "by_repo" and repo_name:
        return f"{base}/{repo_name}"
    return base


def _rating_to_emoji(rating: Optional[str]) -> str:
    if not rating:
        return ""
    r = str(rating)
    if "🏆" in r:
        return "🏆"
    if "👍" in r:
        return "👍"
    if "🤷" in r:
        return "🤷"
    return ""


def _short_hash(data: Optional[bytes]) -> str:
    if not data:
        return ""
    try:
        import hashlib
        return hashlib.sha256(data).hexdigest()[:8]
    except Exception:
        return ""


def _sanitize_drive_filename_component(text: str) -> str:
    """Sanitize a filename component for Google Drive.

    Drive rejects '/' in names; we also defensively replace other common illegal
    characters across filesystems to avoid interop issues.
    """
    try:
        if not isinstance(text, str):
            text = str(text)
        # Replace forbidden/suspicious characters with underscore
        safe = re.sub(r'[\\/<>:"|?*\n\r\t]+', "_", text)
        # Collapse consecutive underscores and trim spaces
        safe = re.sub(r"_+", "_", safe).strip().strip("._ ")
        return safe or "file"
    except Exception:
        return "file"


def compute_friendly_name(user_id: int, category: str, entity_name: str, rating: Optional[str] = None, content_sample: Optional[bytes] = None, *, owner: str) -> str:
    """Return a friendly filename per spec using underscores.

    Pattern examples:
    - BKP_zip_CodeBot_v7_26-08-2025.zip
    - BKP_zip_CodeBot_v7_🏆_26-08-2025.zip

    מספר הגרסה נספר בהעדפות של ``owner`` (``drive_version_counters``), כלומר לכל שירות מונה משלו.
    """
    label = _category_label(category)
    date_str = _date_str_ddmmyyyy()
    key = f"{category}:{entity_name}"
    v = _next_version(user_id, key, owner=owner)
    emoji = _rating_to_emoji(rating)
    base = f"BKP_{label}_{entity_name}_v{v}"
    # Add short content hash if available to reduce collisions when many zips are generated in a row
    # Hash suffix only if enabled in config
    try:
        from config import config as _cfg
        use_hash = bool(getattr(_cfg, 'DRIVE_ADD_HASH', False))
    except Exception:
        use_hash = False
    h = _short_hash(content_sample) if use_hash else ""
    if emoji and h:
        return f"{base}_{emoji}_{h}_{date_str}.zip"
    if emoji:
        return f"{base}_{emoji}_{date_str}.zip"
    if h:
        return f"{base}_{h}_{date_str}.zip"
    return f"{base}_{date_str}.zip"

# ===== Upload retry helpers =====
def _parse_http_error_status_reason(err: Exception) -> Tuple[Optional[int], Optional[str]]:
    try:
        status = getattr(getattr(err, 'resp', None), 'status', None)
    except Exception:
        status = None
    reason: Optional[str] = None
    try:
        content = getattr(err, 'content', None)
        if isinstance(content, (bytes, bytearray)) and content:
            # content is usually JSON
            try:
                payload = json.loads(content.decode('utf-8', errors='ignore'))
                # Typical Drive error shape
                reason = (
                    (payload.get('error', {}) or {}).get('errors', [{}])[0].get('reason')
                    or (payload.get('error', {}) or {}).get('status')
                    or (payload.get('error', {}) or {}).get('message')
                )
            except Exception:
                reason = None
    except Exception:
        reason = None
    return (int(status) if status else None, reason if isinstance(reason, str) else None)


def _is_auth_http_error(err: Exception) -> bool:
    """Auth failure that may be resolved by refreshing tokens."""
    status, _reason = _parse_http_error_status_reason(err)
    # Only 401: 403 is often a permissions issue and refresh will not help.
    return bool(status == 401)


def _clear_service_cache(user_id: int, *, owner: str) -> None:
    try:
        _SERVICE_CACHE.pop(_service_cache_key(user_id, owner=owner), None)
    except Exception:
        pass


def _force_refresh_credentials(user_id: int, *, owner: str) -> bool:
    """Force-refresh access token using refresh_token.

    Used on mid-flight 401 failures where local expiry tracking may be stale.
    Returns True when refresh succeeded.
    """
    if Credentials is None or Request is None:
        return False
    tokens = _load_tokens(user_id, owner=owner) or {}
    if not tokens or not tokens.get("refresh_token"):
        return False
    try:
        creds = _credentials_from_tokens(tokens)
    except Exception:
        return False
    try:
        creds.refresh(Request())  # type: ignore[misc]
    except Exception as e:
        text = str(e).lower()
        if "invalid_grant" in text or "access_denied" in text:
            logging.getLogger(__name__).warning("Drive forced refresh invalid_grant; user re-auth required")
            return False
        logging.getLogger(__name__).warning("Drive forced refresh failed: %s", str(e))
        return False
    try:
        updated = {
            "access_token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_type": "Bearer",
            "scope": " ".join(creds.scopes or []),
            "expires_in": int((creds.expiry - _now_utc()).total_seconds()) if creds.expiry else 3600,
            "expiry": creds.expiry.isoformat() if creds.expiry else (_now_utc() + timedelta(hours=1)).isoformat(),
        }
        save_tokens(user_id, updated, owner=owner)
    except Exception:
        # Refresh succeeded even if persistence failed; try to proceed anyway
        pass
    _clear_service_cache(user_id, owner=owner)
    return True


def _is_retryable_http_error(err: Exception) -> Tuple[bool, Optional[float]]:
    """Return (should_retry, retry_after_seconds)."""
    status, reason = _parse_http_error_status_reason(err)
    # Respect Retry-After header if present
    retry_after_s: Optional[float] = None
    try:
        hdrs = getattr(err, 'resp', None)
        if hdrs is not None:
            ra = getattr(hdrs, 'get', None)
            if callable(ra):
                val = ra('retry-after') or ra('Retry-After')
                if val:
                    retry_after_s = float(val)
    except Exception:
        retry_after_s = None

    # HTTP status based
    if status in {429, 500, 502, 503, 504}:
        return True, retry_after_s

    # Reason based (Drive specific)
    retry_reasons = {
        'rateLimitExceeded',
        'userRateLimitExceeded',
        'backendError',
        'internalError',
        'downloadQuotaExceeded',
    }
    if reason and any(r in str(reason) for r in retry_reasons):
        return True, retry_after_s
    return False, None


def _sleep_backoff(attempt: int, retry_after_s: Optional[float] = None) -> None:
    # Jittered exponential backoff; cap at ~10s to avoid long blocking
    if isinstance(retry_after_s, (int, float)) and retry_after_s > 0:
        delay = float(retry_after_s)
    else:
        base = 0.5
        cap = 10.0
        delay = min(cap, base * (2 ** attempt))
        delay = delay * (0.7 + 0.6 * random.random())  # jitter ~±30%
    try:
        time.sleep(max(0.05, delay))
    except Exception:
        pass


def upload_bytes(user_id: int, filename: str, data: bytes, folder_id: Optional[str] = None, sub_path: Optional[str] = None, *, owner: str) -> Optional[str]:
    """מעלה ``data`` כקובץ ל-Drive של ``owner`` ומחזיר את המזהה שלו.

    העלאה שנכשלה מחזירה ``None``, וכל ``return None`` כאן נרשם (``_log_drive_call_failed``) — הקורא בודק את הערך, והסיבה נמצאת בלוג.
    """
    if MediaIoBaseUpload is None:
        _log_drive_call_failed("upload_bytes.unavailable", user_id, owner=owner)
        return None
    for auth_attempt in range(0, 2):
        service = get_drive_service(user_id, owner=owner)
        if not service:
            _log_drive_call_failed("upload_bytes.no_service", user_id, owner=owner)
            return None

        folder_id_eff = folder_id
        if sub_path:
            folder_id_eff = ensure_subpath(user_id, sub_path, owner=owner)
        if not folder_id_eff:
            folder_id_eff = _get_root_folder(user_id, owner=owner)
        if not folder_id_eff:
            _log_drive_call_failed("upload_bytes.no_folder", user_id, owner=owner)
            return None

        # Use resumable upload with chunks to improve reliability for larger files
        try:
            chunksize = 8 * 1024 * 1024  # 8MB
        except Exception:
            chunksize = None  # type: ignore[assignment]
        media = MediaIoBaseUpload(
            io.BytesIO(data),
            mimetype="application/zip",
            resumable=True,
            chunksize=chunksize if isinstance(chunksize, int) else None,  # type: ignore[arg-type]
        )
        body: Dict[str, Any] = {"name": filename}
        if folder_id_eff:
            body["parents"] = [folder_id_eff]
        try:
            request = service.files().create(body=body, media_body=media, fields="id")
        except HttpError as e:
            if auth_attempt == 0 and _is_auth_http_error(e) and _force_refresh_credentials(user_id, owner=owner):
                continue
            _log_drive_call_failed("upload_bytes.create", user_id, owner=owner, error=e)
            return None
        except Exception as e:
            _log_drive_call_failed("upload_bytes.create", user_id, owner=owner, error=e)
            return None

        response = None
        consecutive_failures = 0
        max_failures = 6
        auth_retry = False

        # Drive SDK: call next_chunk() until the upload completes
        while response is None:
            try:
                _status, response = request.next_chunk()
                consecutive_failures = 0  # reset on progress
            except HttpError as e:  # retryable Drive errors
                # Auth failure: force refresh and restart upload once
                if auth_attempt == 0 and _is_auth_http_error(e) and _force_refresh_credentials(user_id, owner=owner):
                    auth_retry = True
                    break
                should_retry, retry_after = _is_retryable_http_error(e)
                if should_retry and consecutive_failures < max_failures:
                    _sleep_backoff(consecutive_failures, retry_after)
                    consecutive_failures += 1
                    continue
                _log_drive_call_failed("upload_bytes.chunk", user_id, owner=owner, error=e)
                return None
            except Exception as e:
                # Network/transport hiccups — retry a couple of times
                if consecutive_failures < 3:
                    _sleep_backoff(consecutive_failures)
                    consecutive_failures += 1
                    continue
                _log_drive_call_failed("upload_bytes.chunk", user_id, owner=owner, error=e)
                return None

        if auth_retry:
            continue
        file_id = response.get("id") if isinstance(response, dict) else None
        if not file_id:
            _log_drive_call_failed("upload_bytes.response", user_id, owner=owner)
        return file_id
    return None


def upload_file(
    user_id: int,
    filename: str,
    file_path: str,
    folder_id: Optional[str] = None,
    sub_path: Optional[str] = None,
    *,
    owner: str,
) -> Optional[str]:
    """Upload a local file to Drive using a resumable, chunked upload.

    העלאה שנכשלה מחזירה ``None`` — גם כשספריות ה-Drive אינן מותקנות — וכל ``return None`` כאן נרשם (``_log_drive_call_failed``).
    """
    if MediaFileUpload is None:
        _log_drive_call_failed("upload_file.unavailable", user_id, owner=owner)
        return None
    for auth_attempt in range(0, 2):
        service = get_drive_service(user_id, owner=owner)
        if not service:
            _log_drive_call_failed("upload_file.no_service", user_id, owner=owner)
            return None

        folder_id_eff = folder_id
        if sub_path:
            folder_id_eff = ensure_subpath(user_id, sub_path, owner=owner)
        if not folder_id_eff:
            folder_id_eff = _get_root_folder(user_id, owner=owner)
        if not folder_id_eff:
            _log_drive_call_failed("upload_file.no_folder", user_id, owner=owner)
            return None

        # Chunked, resumable upload
        try:
            media = MediaFileUpload(
                file_path,
                mimetype="application/zip",
                resumable=True,
                chunksize=8 * 1024 * 1024,  # 8MB
            )
            body: Dict[str, Any] = {"name": filename}
            if folder_id_eff:
                body["parents"] = [folder_id_eff]
            request = service.files().create(body=body, media_body=media, fields="id")
        except HttpError as e:
            if auth_attempt == 0 and _is_auth_http_error(e) and _force_refresh_credentials(user_id, owner=owner):
                continue
            _log_drive_call_failed("upload_file.create", user_id, owner=owner, error=e)
            return None
        except Exception as e:
            _log_drive_call_failed("upload_file.create", user_id, owner=owner, error=e)
            return None

        response = None
        consecutive_failures = 0
        max_failures = 6
        auth_retry = False
        while response is None:
            try:
                _status, response = request.next_chunk()
                consecutive_failures = 0
            except HttpError as e:
                if auth_attempt == 0 and _is_auth_http_error(e) and _force_refresh_credentials(user_id, owner=owner):
                    auth_retry = True
                    break
                should_retry, retry_after = _is_retryable_http_error(e)
                if should_retry and consecutive_failures < max_failures:
                    _sleep_backoff(consecutive_failures, retry_after)
                    consecutive_failures += 1
                    continue
                _log_drive_call_failed("upload_file.chunk", user_id, owner=owner, error=e)
                return None
            except Exception as e:
                if consecutive_failures < 3:
                    _sleep_backoff(consecutive_failures)
                    consecutive_failures += 1
                    continue
                _log_drive_call_failed("upload_file.chunk", user_id, owner=owner, error=e)
                return None

        if auth_retry:
            continue
        file_id = response.get("id") if isinstance(response, dict) else None
        if not file_id:
            _log_drive_call_failed("upload_file.response", user_id, owner=owner)
        return file_id
    return None


@dataclass(frozen=True)
class ScheduledBackupResult:
    """Result of a scheduled backup to Drive."""
    ok: bool
    uploaded: int = 0


@dataclass(frozen=True)
class UploadSavedZipResult:
    uploaded: int
    ids: List[str]
    attempted: int
    failed: int
    skipped_nonzip: int
    skipped_dedup: int


def _upload_all_saved_zip_backups_detailed(user_id: int, *, owner: str) -> UploadSavedZipResult:
    """Upload ZIP backups and return detailed stats (for scheduler semantics)."""
    backups = backup_manager.list_backups(user_id)
    uploaded = 0
    ids: List[str] = []
    attempted = 0
    failed = 0
    skipped_nonzip = 0
    skipped_dedup = 0

    # Load previously uploaded backup ids
    try:
        prefs = db.get_drive_prefs(user_id, owner=owner) or {}
        uploaded_set = set(prefs.get('uploaded_backup_ids') or [])
    except Exception:
        prefs = {}
        uploaded_set = set()

    # Resolve/validate root; if it changed, drop uploaded_set to allow re‑upload
    old_root_id = prefs.get('target_folder_id')
    try:
        current_root_id = _get_root_folder(user_id, owner=owner)
    except Exception:
        current_root_id = old_root_id
    if current_root_id and old_root_id and current_root_id != old_root_id:
        uploaded_set = set()
        try:
            db.save_drive_prefs(user_id, {"uploaded_backup_ids": []}, owner=owner)
        except Exception:
            pass

    # Also deduplicate by content hash against existing files in Drive (folder: zip)
    existing_md5: Optional[set[str]] = set()
    try:
        service = get_drive_service(user_id, owner=owner)
        if service is not None:
            sub_path = compute_subpath("zip")
            folder_id = ensure_subpath(user_id, sub_path, owner=owner)
            if folder_id:
                page_token: Optional[str] = None
                while True:
                    try:
                        resp = service.files().list(
                            q=f"'{folder_id}' in parents and trashed = false",
                            spaces='drive',
                            fields="nextPageToken, files(id, name, md5Checksum)",
                            pageToken=page_token
                        ).execute()
                    except Exception:
                        existing_md5 = None
                        break
                    for f in (resp.get('files') or []):
                        md5v = f.get('md5Checksum')
                        if isinstance(md5v, str) and md5v:
                            assert isinstance(existing_md5, set)
                            existing_md5.add(md5v)
                    page_token = resp.get('nextPageToken')
                    if not page_token:
                        break
    except Exception:
        existing_md5 = None

    new_uploaded: List[str] = []
    for b in backups:
        try:
            b_id = getattr(b, 'backup_id', None)
            path = getattr(b, "file_path", None)
            if not path or not str(path).endswith(".zip"):
                skipped_nonzip += 1
                continue

            # Compute MD5 without loading entire file into memory, and capture a small content sample
            md5_local: Optional[str] = None
            content_sample: Optional[bytes] = None
            try:
                h = hashlib.md5()
                with open(path, "rb") as f_md5:
                    for chunk in iter(lambda: f_md5.read(1024 * 1024), b""):
                        if content_sample is None and chunk:
                            content_sample = chunk[:1024]
                        h.update(chunk)
                md5_local = h.hexdigest()
            except Exception:
                md5_local = None

            # If a file with the same content already exists in Drive, mark as uploaded and skip
            try:
                if isinstance(existing_md5, set) and md5_local in existing_md5:
                    skipped_dedup += 1
                    if b_id:
                        new_uploaded.append(b_id)
                    continue
                # If we could not list Drive files (existing_md5 is None), fallback to uploaded_set guard
                if existing_md5 is None and b_id and b_id in uploaded_set:
                    skipped_dedup += 1
                    continue
            except Exception:
                pass

            from config import config as _cfg
            # Build entity name
            try:
                md = getattr(b, 'metadata', None) or {}
            except Exception:
                md = {}
            repo_full = None
            try:
                repo_full = md.get('repo')
            except Exception:
                repo_full = None
            if not repo_full:
                try:
                    repo_full = getattr(b, 'repo', None)
                except Exception:
                    repo_full = None
            if isinstance(repo_full, str) and repo_full:
                base_name = repo_full.split('/')[-1]
                path_hint = ''
                try:
                    path_hint = (md.get('path') or '').strip('/')
                except Exception:
                    path_hint = ''
                if not path_hint:
                    try:
                        path_hint = (getattr(b, 'path', None) or '').strip('/')
                    except Exception:
                        path_hint = ''
                entity = f"{base_name}_{path_hint.replace('/', '_')}" if path_hint else base_name
            else:
                entity = getattr(_cfg, 'BOT_LABEL', 'CodeBot') or 'CodeBot'

            # Derive rating emoji
            try:
                rating = db.get_backup_rating(user_id, b_id) if b_id else None
            except Exception:
                rating = None

            # Build friendly filename once (stable across fallbacks)
            fname = compute_friendly_name(user_id, "zip", entity, rating, content_sample=content_sample, owner=owner)
            sub_path = compute_subpath("zip")

            attempted += 1

            # Prefer streaming from file when possible; fall back to bytes if needed
            fid: Optional[str] = None
            try:
                fid = upload_file(user_id, filename=fname, file_path=path, sub_path=sub_path, owner=owner)
            except Exception:
                fid = None
            if not fid:
                try:
                    with open(path, "rb") as f_bytes:
                        data_bytes = f_bytes.read()
                    fid = upload_bytes(user_id, filename=fname, data=data_bytes, sub_path=sub_path, owner=owner)
                except Exception:
                    fid = None
            if fid:
                uploaded += 1
                ids.append(fid)
                if b_id:
                    new_uploaded.append(b_id)
            else:
                failed += 1
        except Exception:
            failed += 1
            continue

    # Persist uploaded ids and last backup time for next-run calc
    if new_uploaded:
        try:
            all_ids = list(uploaded_set.union(new_uploaded))
            now_iso = _now_utc().isoformat()
            db.save_drive_prefs(user_id, {"uploaded_backup_ids": all_ids, "last_backup_at": now_iso}, owner=owner)
        except Exception:
            pass

    return UploadSavedZipResult(
        uploaded=uploaded,
        ids=ids,
        attempted=attempted,
        failed=failed,
        skipped_nonzip=skipped_nonzip,
        skipped_dedup=skipped_dedup,
    )


def upload_all_saved_zip_backups(user_id: int, *, owner: str) -> Tuple[int, List[str]]:
    """Upload only ZIP backups that were not uploaded before for this user.

    Uses uploaded_backup_ids in the Drive prefs of ``owner`` (set) to deduplicate uploads.
    """
    res = _upload_all_saved_zip_backups_detailed(user_id, owner=owner)
    return res.uploaded, list(res.ids)


# Expose a local proxy for zipfile so tests can safely monkeypatch
# without altering the global zipfile module (avoids recursion in wrappers)
zipfile = _SimpleNamespace(
    ZipFile=_zipfile.ZipFile,
    ZIP_DEFLATED=_zipfile.ZIP_DEFLATED,
    ZIP_STORED=getattr(_zipfile, "ZIP_STORED", 0),
)


def _db_runtime():
    """Resolve a DB accessor dynamically to support tests.

    Selection rules (to honor both monkeypatch styles):
    - If a runtime `database.db` exists and differs from module-level `gds.db`, prefer it
      (covers tests that monkeypatch `sys.modules['database']`).
    - Otherwise, if module-level `gds.db` exposes the APIs, use it
      (covers tests that monkeypatch `services.google_drive_service.db`).
    - Fallback to whichever of the two is available with the expected APIs.
    """
    module_db = None
    try:
        if 'db' in globals():  # type: ignore[name-defined]
            module_db = globals().get('db')  # type: ignore[assignment]
    except Exception:
        module_db = None

    runtime_db = None
    try:
        import sys as _sys, types as _types
        m = _sys.modules.get('database')
        runtime_db = getattr(m, 'db', None) if m is not None else None
        runtime_is_module = isinstance(m, _types.ModuleType)
    except Exception:
        runtime_db = None
        runtime_is_module = True

    # Selection:
    # 1) If sys.modules['database'] is not a real module (likely test stub), prefer its db
    if not runtime_is_module and hasattr(runtime_db, 'get_user_files'):
        return runtime_db

    # 2) If module-level db was explicitly overridden (different object than runtime_db), prefer it
    if module_db is not None and module_db is not runtime_db and hasattr(module_db, 'get_user_files'):
        return module_db

    # 3) Otherwise prefer runtime db if available, else module db
    if hasattr(runtime_db, 'get_user_files'):
        return runtime_db
    if hasattr(module_db, 'get_user_files'):
        return module_db
 

    return None


def create_repo_grouped_zip_bytes(user_id: int, *, owner: str) -> List[Tuple[str, str, bytes]]:
    """Return zips grouped by repo: (repo_name, suggested_name, zip_bytes).

    ``owner`` נדרש בשביל מונה הגרסה בשם הקובץ (``compute_friendly_name``), שנשמר בהעדפות של אותו שירות.
    """
    # נדרש גם tags ו-code לקיבוץ ולכתיבה ל־ZIP
    _db = _db_runtime()
    files = (_db.get_user_files(
        user_id,
        limit=1000,
        projection={"file_name": 1, "tags": 1, "code": 1, "_id": 1},
    ) if _db else []) or []
    repo_to_files: Dict[str, List[Dict[str, Any]]] = {}
    for doc in files:
        tags = doc.get('tags') or []
        repo_tag = None
        for t in tags:
            if isinstance(t, str) and t.startswith('repo:'):
                repo_tag = t.split(':', 1)[1]
                break
        if not repo_tag:
            continue
        repo_to_files.setdefault(repo_tag, []).append(doc)
    results: List[Tuple[str, str, bytes]] = []
    for repo, docs in repo_to_files.items():
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for d in docs:
                name = d.get('file_name') or f"file_{d.get('_id')}"
                code = d.get('code') or ''
                zf.writestr(name, code)
        buf.seek(0)
        data_bytes = buf.getvalue()
        try:
            friendly = compute_friendly_name(user_id, "by_repo", repo, content_sample=data_bytes[:1024], owner=owner)
        except Exception:
            # Fail-open: אם יש תלות ב-db להפקת שם ידידותי, חזור לשם פשוט
            safe_repo = _sanitize_drive_filename_component(repo)
            friendly = f"BKP_by_repo_{safe_repo}.zip"
        results.append((repo, friendly, data_bytes))
    return results


def create_full_backup_zip_bytes(user_id: int, category: str = "all") -> Tuple[str, bytes]:
    """Creates a ZIP of user data by category and returns (filename, bytes)."""
    # Collect content according to category

    backup_id = f"backup_{user_id}_{int(time.time())}_{category}"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        # נדרשים code ו-tags להמשך סינון וכתיבה ל־ZIP
        _db = _db_runtime()
        files = (_db.get_user_files(
            user_id,
            limit=1000,
            projection={"file_name": 1, "tags": 1, "code": 1, "_id": 1},
        ) if _db else []) or []
        if category == "by_repo":
            files = [d for d in files if any((t or '').startswith('repo:') for t in (d.get('tags') or []))]
        elif category == "large":
            try:
                large_files, _ = _db.get_user_large_files(user_id, page=1, per_page=10000) if _db else ([], None)
            except Exception:
                large_files = []
            for lf in large_files:
                name = lf.get('file_name') or f"large_{lf.get('_id')}"
                code = lf.get('code') or ''
                zf.writestr(name, code)
            # Also write metadata for large
            metadata = {
                "backup_id": backup_id,
                "user_id": user_id,
                "created_at": _now_utc().isoformat(),
                "backup_type": "drive_manual_large",
                "file_count": len(large_files),
            }
            zf.writestr('metadata.json', json.dumps(metadata, ensure_ascii=False, indent=2))
            buf.seek(0)
            return f"{backup_id}.zip", buf.getvalue()
        elif category == "other":
            files = [d for d in files if not any((t or '').startswith('repo:') for t in (d.get('tags') or []))]
        # default include files
        for doc in files:
            name = doc.get('file_name') or f"file_{doc.get('_id')}"
            code = doc.get('code') or ''
            zf.writestr(name, code)
        metadata = {
            "backup_id": backup_id,
            "user_id": user_id,
            "created_at": _now_utc().isoformat(),
            "backup_type": f"drive_manual_{category}",
            "file_count": len(files),
        }
        zf.writestr('metadata.json', json.dumps(metadata, ensure_ascii=False, indent=2))
    buf.seek(0)
    return f"{backup_id}.zip", buf.getvalue()


def perform_scheduled_backup(user_id: int, *, owner: str) -> ScheduledBackupResult:
    """Runs a scheduled backup to Drive according to user's selected category.

    Category resolution priority (in the Drive prefs of ``owner``):
    1) schedule_category (explicit)
    2) last_selected_category (UI selection)
    3) fallback to "all"

    Updates last_backup_at on any successful scheduled upload.
    Updates last_full_backup_at only if category == "all".

    Returns ScheduledBackupResult with ok=True/False and uploaded count.
    When there is nothing to back up, ok=True but uploaded=0.
    """
    try:
        prefs = db.get_drive_prefs(user_id, owner=owner) or {}
    except Exception:
        prefs = {}
    category = str(prefs.get("schedule_category") or prefs.get("last_selected_category") or "all").strip() or "all"
    allowed = {"zip", "all", "by_repo", "large", "other"}
    if category not in allowed:
        category = "all"

    ok = False
    uploaded = 0
    try:
        now_iso = _now_utc().isoformat()
        if category == "zip":
            # If there are no ZIP backups locally, treat as success (nothing to do).
            try:
                backups = backup_manager.list_backups(user_id) or []
                has_zip = any(str(getattr(b, 'file_path', '')).endswith('.zip') for b in backups)
            except Exception:
                has_zip = True
            if not has_zip:
                return ScheduledBackupResult(ok=True, uploaded=0)
            # Upload any saved ZIP backups that were not uploaded yet
            res = _upload_all_saved_zip_backups_detailed(user_id, owner=owner)
            ok = bool(res.failed == 0)
            uploaded = res.uploaded
            if ok and res.uploaded > 0:
                try:
                    db.save_drive_prefs(user_id, {"last_backup_at": now_iso}, owner=owner)
                except Exception:
                    pass
        elif category == "by_repo":
            grouped = create_repo_grouped_zip_bytes(user_id, owner=owner)
            ok_any = False
            for repo_name, suggested, data_bytes in grouped:
                # Use suggested friendly name and by_repo subpath
                sub_path = compute_subpath("by_repo", repo_name)
                fid = upload_bytes(user_id, suggested, data_bytes, sub_path=sub_path, owner=owner)
                if fid:
                    ok_any = True
                    uploaded += 1
            ok = ok_any
            if ok:
                try:
                    db.save_drive_prefs(user_id, {"last_backup_at": now_iso}, owner=owner)
                except Exception:
                    pass
        else:
            # all / large / other -> single ZIP according to category
            fn, data = create_full_backup_zip_bytes(user_id, category=category)
            from config import config as _cfg
            friendly = compute_friendly_name(user_id, category, getattr(_cfg, 'BOT_LABEL', 'CodeBot') or 'CodeBot', content_sample=data[:1024], owner=owner)
            sub_path = compute_subpath(category)
            fid = upload_bytes(user_id, friendly, data, sub_path=sub_path, owner=owner)
            ok = bool(fid)
            if ok:
                uploaded = 1
                update = {"last_backup_at": now_iso}
                if category == "all":
                    update["last_full_backup_at"] = now_iso
                try:
                    db.save_drive_prefs(user_id, update, owner=owner)
                except Exception:
                    pass
    except Exception:
        ok = False
    return ScheduledBackupResult(ok=ok, uploaded=uploaded)

