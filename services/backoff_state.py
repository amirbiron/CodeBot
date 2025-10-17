"""
Persistent GitHub backoff state management.

Backoff is a global switch to reduce GitHub API traffic when nearing
rate limits or during maintenance. State is persisted in the DB so it
survives restarts, with an in-memory cache for fast reads.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

try:
    from observability import emit_event  # type: ignore
except Exception:  # pragma: no cover
    def emit_event(event: str, severity: str = "info", **fields):  # type: ignore
        return None


_LOCK = threading.RLock()


@dataclass
class BackoffInfo:
    enabled: bool
    reason: str = ""
    updated_at: datetime = datetime.now(timezone.utc)
    expires_at: Optional[datetime] = None

    def is_active(self) -> bool:
        if not self.enabled:
            return False
        if self.expires_at is not None and datetime.now(timezone.utc) >= self.expires_at:
            return False
        return True


class BackoffState:
    """Backoff state persisted in DB with memory cache."""

    def __init__(self) -> None:
        self._cached: Optional[BackoffInfo] = None

    # --- DB helpers ---
    def _load_from_db(self) -> Optional[BackoffInfo]:
        try:
            from database import db  # lazy import to avoid cycles
            users = getattr(db, "db", None) and getattr(db.db, "users", None)
            if not users:
                return None
            doc = users.find_one({"_id": "__global_state__"})
            if not isinstance(doc, dict):
                return None
            gh = (doc.get("github") or {}).get("backoff") or {}
            enabled = bool(gh.get("enabled", False))
            reason = str(gh.get("reason", "") or "")
            updated_at = self._parse_dt(gh.get("updated_at")) or datetime.now(timezone.utc)
            expires_at = self._parse_dt(gh.get("expires_at"))
            return BackoffInfo(enabled=enabled, reason=reason, updated_at=updated_at, expires_at=expires_at)
        except Exception:
            return None

    def _save_to_db(self, info: BackoffInfo) -> None:
        try:
            from database import db  # lazy import
            users = getattr(db, "db", None) and getattr(db.db, "users", None)
            if not users:
                return
            payload = {
                "github": {
                    "backoff": {
                        "enabled": bool(info.enabled),
                        "reason": str(info.reason or ""),
                        "updated_at": info.updated_at,
                        "expires_at": info.expires_at,
                    }
                }
            }
            # Persist under the same key used by _load_from_db
            users.update_one({"_id": "__global_state__"}, {"$set": payload}, upsert=True)
        except Exception:
            # Non-fatal: remain with memory cache
            pass

    @staticmethod
    def _parse_dt(val: Any) -> Optional[datetime]:
        if val is None:
            return None
        if isinstance(val, datetime):
            return val
        try:
            return datetime.fromisoformat(str(val))
        except Exception:
            return None

    # --- Public API ---
    def get(self, refresh: bool = False) -> BackoffInfo:
        with _LOCK:
            if refresh or self._cached is None:
                loaded = self._load_from_db()
                if loaded is not None:
                    self._cached = loaded
                elif self._cached is None:
                    self._cached = BackoffInfo(enabled=False)
            # Auto-deactivate if expired
            if self._cached.expires_at and datetime.now(timezone.utc) >= self._cached.expires_at:
                self._cached.enabled = False
            return self._cached

    def enable(self, *, reason: str = "", ttl_minutes: Optional[int] = None) -> BackoffInfo:
        with _LOCK:
            expires_at = None
            if ttl_minutes is not None and ttl_minutes > 0:
                expires_at = datetime.now(timezone.utc) + timedelta(minutes=int(ttl_minutes))
            info = BackoffInfo(enabled=True, reason=reason or "manual", updated_at=datetime.now(timezone.utc), expires_at=expires_at)
            self._cached = info
            self._save_to_db(info)
            emit_event("github_backoff_enabled", severity="warn", reason=info.reason, ttl_minutes=int(ttl_minutes or 0))
            return info

    def disable(self, *, reason: str = "") -> BackoffInfo:
        with _LOCK:
            info = BackoffInfo(enabled=False, reason=reason or "manual", updated_at=datetime.now(timezone.utc), expires_at=None)
            self._cached = info
            self._save_to_db(info)
            emit_event("github_backoff_disabled", severity="info", reason=info.reason)
            return info

    def toggle(self, *, reason: str = "", ttl_minutes: Optional[int] = None) -> BackoffInfo:
        cur = self.get()
        return self.disable(reason=reason or "toggle") if cur.is_active() else self.enable(reason=reason or "toggle", ttl_minutes=ttl_minutes)


# Global singleton
state = BackoffState()
