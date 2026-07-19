"""Personal Access Token (PAT) store for the MCP server.

A PAT lets a non-browser client (an MCP client such as Claude Code) authenticate
as a specific Telegram user without a session cookie. This mirrors the existing
one-time ``webapp_tokens`` bridge (see ``conversation_handlers.py``), but the
tokens here are long-lived, reusable, scoped, and revocable.

Security choices:
- We store only a SHA-256 **hash** of each token, never the raw value. The raw
  token is shown to the user exactly once (at issue time).
- Tokens carry 256 bits of entropy (``secrets.token_urlsafe(32)``), so a single
  SHA-256 is sufficient here — unlike low-entropy passwords, no slow KDF needed.
- ``user_id`` is always authoritative and server-derived from the stored token.

The store depends only on a duck-typed pymongo collection handle, so it can be
unit-tested with a tiny fake collection and adds no import-time dependencies.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

TOKEN_PREFIX = "ckmcp_"  # human-recognizable, greppable prefix
_RAW_ENTROPY_BYTES = 32  # 256-bit
DEFAULT_SCOPES = ("read",)
COLLECTION_NAME = "mcp_tokens"


def _now() -> datetime:
    return datetime.now(UTC)


def _as_aware(dt: Any) -> datetime | None:
    """Coerce a possibly tz-naive datetime (as Mongo may return) to aware UTC."""
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _iso(dt: Any) -> str | None:
    aware = _as_aware(dt)
    return aware.isoformat() if aware else None


def hash_token(raw_token: str) -> str:
    """Return the stable lookup hash for a raw token."""
    return hashlib.sha256((raw_token or "").encode("utf-8")).hexdigest()


class MCPTokenStore:
    """CRUD-lite store over the ``mcp_tokens`` collection."""

    def __init__(self, db: Any, *, collection_name: str = COLLECTION_NAME) -> None:
        # ``db`` is a pymongo Database handle (or a compatible fake).
        self._coll = db[collection_name]
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        # Best-effort; token operations must never fail because indexing did.
        try:
            self._coll.create_index("token_hash", unique=True)
            self._coll.create_index("user_id")
        except Exception:
            pass

    # -- write -------------------------------------------------------------
    def issue(
        self,
        user_id: int,
        *,
        label: str | None = None,
        scopes: Iterable[str] = DEFAULT_SCOPES,
        ttl_days: int | None = None,
    ) -> str:
        """Create a new token and return the RAW value (shown once)."""
        raw = TOKEN_PREFIX + secrets.token_urlsafe(_RAW_ENTROPY_BYTES)
        expires_at = _now() + timedelta(days=ttl_days) if ttl_days else None
        doc = {
            "token_hash": hash_token(raw),
            # first few chars only, for display in a "connections" list
            "token_prefix": raw[: len(TOKEN_PREFIX) + 6],
            "user_id": int(user_id),
            "scopes": list(scopes) or list(DEFAULT_SCOPES),
            "label": (label or "").strip() or "Claude",
            "created_at": _now(),
            "last_used_at": None,
            "expires_at": expires_at,
            "revoked": False,
        }
        self._coll.insert_one(doc)
        return raw

    def revoke(self, user_id: int, token_id: Any) -> bool:
        """Revoke a token owned by ``user_id`` (by its string id)."""
        query_id: Any = token_id
        try:  # ids are ObjectId in real Mongo, plain values in fakes
            from bson import ObjectId

            query_id = ObjectId(str(token_id))
        except Exception:
            query_id = token_id
        res = self._coll.update_one(
            {"_id": query_id, "user_id": int(user_id)},
            {"$set": {"revoked": True, "revoked_at": _now()}},
        )
        return bool(getattr(res, "modified_count", 0))

    # -- read --------------------------------------------------------------
    def verify(self, raw_token: str) -> dict[str, Any] | None:
        """Return ``{"user_id", "scopes"}`` for a valid token, else ``None``.

        A token is valid iff it exists, is not revoked, and is not expired.
        """
        if not raw_token:
            return None
        doc = self._coll.find_one({"token_hash": hash_token(raw_token), "revoked": {"$ne": True}})
        if not doc:
            return None
        expires_at = _as_aware(doc.get("expires_at"))
        if expires_at is not None and expires_at < _now():
            return None
        try:  # best-effort "last used" touch; never block auth on it
            self._coll.update_one({"_id": doc["_id"]}, {"$set": {"last_used_at": _now()}})
        except Exception:
            pass
        return {
            "user_id": int(doc["user_id"]),
            "scopes": list(doc.get("scopes") or DEFAULT_SCOPES),
        }

    def list_for_user(self, user_id: int) -> list[dict[str, Any]]:
        """List a user's tokens (metadata only — never the hash or raw value)."""
        out: list[dict[str, Any]] = []
        for d in self._coll.find({"user_id": int(user_id)}):
            out.append(
                {
                    "id": str(d.get("_id")),
                    "token_prefix": d.get("token_prefix"),
                    "label": d.get("label"),
                    "scopes": list(d.get("scopes") or []),
                    "created_at": _iso(d.get("created_at")),
                    "last_used_at": _iso(d.get("last_used_at")),
                    "expires_at": _iso(d.get("expires_at")),
                    "revoked": bool(d.get("revoked", False)),
                }
            )
        return out
