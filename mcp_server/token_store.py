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


def _is_expired(expires_at: Any, now: datetime) -> bool:
    """The expiry half of the validity rule, as :meth:`MCPTokenStore.verify` applies it.

    A token without ``expires_at`` never expires (``issue`` without ``ttl_days``).
    :func:`_not_expired_condition` is the same rule written as a query — change both together.
    """
    aware = _as_aware(expires_at)
    return aware is not None and aware < now


def _not_expired_condition(now: datetime) -> dict[str, Any]:
    """:func:`_is_expired`, negated, as a query condition on ``expires_at``.

    For a question the server answers with one document (:func:`user_has_live_token`).
    ``$not`` matches a missing field and ``None`` too — a token that never expires — and
    ``expires_at == now`` is not expired in either form. They agree to the millisecond,
    the precision BSON stores. Python and a query are two languages, so this second copy of
    the rule is on purpose: ``test_the_personal_token_rule_agrees_with_verify`` holds the two
    to one answer, and ``tests/test_first_steps_mongo.py`` checks the condition on a real mongod.
    """
    return {"$not": {"$lt": now}}


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
        if _is_expired(doc.get("expires_at"), _now()):
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


def user_has_live_token(db: Any, user_id: int, *, collection_name: str = COLLECTION_NAME) -> bool:
    """Whether ``user_id`` holds at least one PAT that :meth:`MCPTokenStore.verify` would accept.

    Same rule as ``verify`` — not revoked, and not past ``expires_at`` — so a token that opens
    the server and a token that counts here cannot disagree. The server is asked for one
    document, with the expiry half as a query condition (:func:`_not_expired_condition`), so
    it stops at the first live token it reaches; every row the query matches is live, so
    which one comes back does not matter. Pulling the user's tokens to test them here would
    make the server fill a whole first batch before anything came back — reading past every
    revoked row (they stay in the collection) when few are live.

    A function over the collection and not a method, on purpose: the store's constructor runs
    ``create_index`` on every instantiation, and this question is asked while a page renders
    (the "first steps" checklist on the webapp dashboard).
    """
    found = db[collection_name].find_one(
        {"user_id": int(user_id), "revoked": {"$ne": True}, "expires_at": _not_expired_condition(_now())},
        {"_id": 1},
    )
    return found is not None
