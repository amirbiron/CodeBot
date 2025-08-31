from __future__ import annotations

import io
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple, List

import requests
try:
    from googleapiclient.discovery import build  # type: ignore
    from googleapiclient.errors import HttpError  # type: ignore
    from googleapiclient.http import MediaIoBaseUpload  # type: ignore
    from google.oauth2.credentials import Credentials  # type: ignore
    from google.auth.transport.requests import Request  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    build = None  # type: ignore[assignment]
    HttpError = Exception  # type: ignore[assignment]
    MediaIoBaseUpload = None  # type: ignore[assignment]
    Credentials = None  # type: ignore[assignment]
    Request = None  # type: ignore[assignment]

from config import config
from database import db
from file_manager import backup_manager


DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def start_device_authorization(user_id: int) -> Dict[str, Any]:
    """Starts OAuth Device Authorization flow for Google Drive.

    Returns a dict with: verification_url, user_code, device_code, interval, expires_in.
    """
    payload = {
        "client_id": config.GOOGLE_CLIENT_ID,
        "scope": config.GOOGLE_OAUTH_SCOPES,
    }
    response = requests.post(DEVICE_CODE_URL, data=payload, timeout=15)
    response.raise_for_status()
    data = response.json()
    # Persist device flow state in memory is handled by caller; tokens saved on success.
    return {
        "verification_url": data.get("verification_url") or data.get("verification_uri"),
        "user_code": data.get("user_code"),
        "device_code": data.get("device_code"),
        "interval": int(data.get("interval", 5)),
        "expires_in": int(data.get("expires_in", 1800)),
    }


def poll_device_token(device_code: str) -> Optional[Dict[str, Any]]:
    """Attempts a single token exchange for a device_code. Returns token dict or None if authorization_pending.
    Raises on fatal errors.
    """
    payload = {
        "client_id": config.GOOGLE_CLIENT_ID,
        "client_secret": config.GOOGLE_CLIENT_SECRET or "",
        "device_code": device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    }
    resp = requests.post(TOKEN_URL, data=payload, timeout=20)
    if resp.status_code == 428 or resp.status_code == 400:
        try:
            err = resp.json().get("error")
        except Exception:
            err = None
        if err in {"authorization_pending", "slow_down"}:
            return None
    resp.raise_for_status()
    tokens = resp.json()
    # Normalize fields
    tokens["expiry"] = (_now_utc() + timedelta(seconds=int(tokens.get("expires_in", 3600)))).isoformat()
    return tokens


def save_tokens(user_id: int, tokens: Dict[str, Any]) -> bool:
    # Ensure we persist refresh_token if available
    return db.save_drive_tokens(user_id, tokens)


def _load_tokens(user_id: int) -> Optional[Dict[str, Any]]:
    return db.get_drive_tokens(user_id)


def _credentials_from_tokens(tokens: Dict[str, Any]) -> Credentials:
    if Credentials is None:
        raise RuntimeError("Google libraries are not installed")
    return Credentials(
        token=tokens.get("access_token"),
        refresh_token=tokens.get("refresh_token"),
        token_uri=TOKEN_URL,
        client_id=config.GOOGLE_CLIENT_ID,
        client_secret=config.GOOGLE_CLIENT_SECRET or None,
        scopes=(tokens.get("scope") or config.GOOGLE_OAUTH_SCOPES).split(),
    )


def _ensure_valid_credentials(user_id: int) -> Optional[Credentials]:
    tokens = _load_tokens(user_id)
    if not tokens:
        return None
    try:
        creds = _credentials_from_tokens(tokens)
    except Exception:
        return None
    if creds.expired and creds.refresh_token:
        try:
            if Request is None:
                return None
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
            save_tokens(user_id, updated)
        except Exception:
            return None
    return creds


def get_drive_service(user_id: int):
    if build is None:
        return None
    creds = _ensure_valid_credentials(user_id)
    if not creds:
        return None
    try:
        return build("drive", "v3", credentials=creds, cache_discovery=False)
    except Exception:
        return None


def ensure_folder(user_id: int, name: str, parent_id: Optional[str] = None) -> Optional[str]:
    service = get_drive_service(user_id)
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
    except HttpError:
        return None


def get_or_create_default_folder(user_id: int) -> Optional[str]:
    prefs = db.get_drive_prefs(user_id) or {}
    folder_id = prefs.get("target_folder_id")
    if folder_id:
        return folder_id
    # Create "CodeKeeper Backups" at root
    fid = ensure_folder(user_id, "CodeKeeper Backups", None)
    if fid:
        db.save_drive_prefs(user_id, {"target_folder_id": fid})
    return fid


def ensure_path(user_id: int, path: str) -> Optional[str]:
    """Ensure nested folders path like "Parent/Sub1/Sub2" exists; returns last folder id."""
    if not path:
        return get_or_create_default_folder(user_id)
    parts = [p.strip() for p in path.split('/') if p.strip()]
    parent: Optional[str] = None
    for part in parts:
        parent = ensure_folder(user_id, part, parent)
        if not parent:
            return None
    # Save as target folder
    db.save_drive_prefs(user_id, {"target_folder_id": parent})
    return parent


def upload_bytes(user_id: int, filename: str, data: bytes, folder_id: Optional[str] = None) -> Optional[str]:
    service = get_drive_service(user_id)
    if not service:
        return None
    if not folder_id:
        folder_id = get_or_create_default_folder(user_id)
    if not folder_id:
        return None
    if MediaIoBaseUpload is None:
        return None
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype="application/zip", resumable=False)
    body: Dict[str, Any] = {"name": filename}
    if folder_id:
        body["parents"] = [folder_id]
    try:
        file = service.files().create(body=body, media_body=media, fields="id").execute()
        return file.get("id")
    except HttpError:
        return None


def upload_all_saved_zip_backups(user_id: int) -> Tuple[int, List[str]]:
    backups = backup_manager.list_backups(user_id)
    uploaded = 0
    ids: List[str] = []
    for b in backups:
        try:
            path = getattr(b, "file_path", None)
            if not path or not str(path).endswith(".zip"):
                continue
            with open(path, "rb") as f:
                data = f.read()
            fid = upload_bytes(user_id, filename=f"{getattr(b, 'backup_id', 'backup')}.zip", data=data)
            if fid:
                uploaded += 1
                ids.append(fid)
        except Exception:
            continue
    return uploaded, ids


def create_full_backup_zip_bytes(user_id: int, category: str = "all") -> Tuple[str, bytes]:
    """Creates a ZIP of user data by category and returns (filename, bytes)."""
    # Collect content according to category
    from database import db as _db
    import zipfile

    backup_id = f"backup_{user_id}_{int(time.time())}_{category}"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        files = _db.get_user_files(user_id, limit=10000) or []
        if category == "by_repo":
            files = [d for d in files if any((t or '').startswith('repo:') for t in (d.get('tags') or []))]
        elif category == "large":
            large_files, _ = _db.get_user_large_files(user_id, page=1, per_page=10000)
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


def perform_scheduled_backup(user_id: int) -> bool:
    """Runs a scheduled full backup to Drive."""
    fn, data = create_full_backup_zip_bytes(user_id, category="all")
    fid = upload_bytes(user_id, fn, data)
    return bool(fid)

