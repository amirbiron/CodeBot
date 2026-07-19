"""MongoDB-backed storage for the OAuth 2.1 authorization server (Phase 1).

Four short-lived/long-lived record types, all in the shared MongoDB:
- ``mcp_oauth_clients``  — dynamically registered clients (DCR, RFC 7591).
- ``mcp_oauth_txns``     — pending /authorize requests, awaiting user identity+consent.
- ``mcp_oauth_codes``    — issued authorization codes (single-use, short TTL).
- ``mcp_oauth_tokens``   — issued access + refresh tokens.

Secrets (codes, tokens) are stored **hashed** (SHA-256); the raw value is only
ever held by the client. ``subject`` carries the CodeKeeper ``user_id`` (as str).

Depends only on a duck-typed pymongo handle, so it is unit-testable with a fake.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, UTC
from typing import Any

from .token_store import hash_token

# Distinct, greppable prefixes so raw values are self-describing in logs/debug.
CODE_PREFIX = "ckoc_"
ACCESS_PREFIX = "ckoat_"
REFRESH_PREFIX = "ckort_"

CODE_TTL_SECONDS = 300  # 5 min
ACCESS_TTL_SECONDS = 3600  # 1 hour
REFRESH_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days
TXN_TTL_SECONDS = 600  # 10 min


def _now() -> datetime:
    return datetime.now(UTC)


def _as_aware(dt: Any) -> datetime | None:
    if not isinstance(dt, datetime):
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def _expired(dt: Any) -> bool:
    aware = _as_aware(dt)
    return aware is not None and aware < _now()


def new_secret(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(32)


class OAuthStore:
    def __init__(self, db: Any) -> None:
        self._clients = db["mcp_oauth_clients"]
        self._txns = db["mcp_oauth_txns"]
        self._codes = db["mcp_oauth_codes"]
        self._tokens = db["mcp_oauth_tokens"]
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        try:
            self._clients.create_index("client_id", unique=True)
            self._txns.create_index("txn_id", unique=True)
            self._codes.create_index("code_hash", unique=True)
            self._tokens.create_index("token_hash", unique=True)
            self._tokens.create_index("subject")
        except Exception:
            pass

    # -- clients (Dynamic Client Registration) ----------------------------
    def save_client(self, client: dict) -> None:
        cid = client["client_id"]
        self._clients.update_one({"client_id": cid}, {"$set": dict(client)}, upsert=True)

    def get_client(self, client_id: str) -> dict | None:
        doc = self._clients.find_one({"client_id": client_id})
        if doc:
            doc.pop("_id", None)
        return doc

    # -- pending authorize transactions -----------------------------------
    def create_txn(self, data: dict) -> str:
        txn_id = secrets.token_urlsafe(24)
        doc = dict(data)
        doc["txn_id"] = txn_id
        doc["expires_at"] = _now() + timedelta(seconds=TXN_TTL_SECONDS)
        self._txns.insert_one(doc)
        return txn_id

    def get_txn(self, txn_id: str) -> dict | None:
        doc = self._txns.find_one({"txn_id": txn_id})
        if not doc or _expired(doc.get("expires_at")):
            return None
        doc.pop("_id", None)
        return doc

    def delete_txn(self, txn_id: str) -> None:
        try:
            self._txns.delete_one({"txn_id": txn_id})
        except Exception:
            pass

    # -- authorization codes (single-use) ---------------------------------
    def save_code(self, code: str, data: dict) -> None:
        doc = dict(data)
        doc["code_hash"] = hash_token(code)
        doc["expires_at"] = _now() + timedelta(seconds=CODE_TTL_SECONDS)
        self._codes.insert_one(doc)

    def get_code(self, code: str) -> dict | None:
        """Peek an authorization code (no consume). None if missing/expired."""
        doc = self._codes.find_one({"code_hash": hash_token(code)})
        if not doc or _expired(doc.get("expires_at")):
            return None
        doc.pop("_id", None)
        return doc

    def delete_code(self, code: str) -> None:
        """Consume an authorization code (single-use)."""
        try:
            self._codes.delete_one({"code_hash": hash_token(code)})
        except Exception:
            pass

    # -- access + refresh tokens ------------------------------------------
    def save_token(self, token: str, *, kind: str, data: dict) -> None:
        doc = dict(data)
        doc["token_hash"] = hash_token(token)
        doc["kind"] = kind
        ttl = ACCESS_TTL_SECONDS if kind == "access" else REFRESH_TTL_SECONDS
        doc["expires_at"] = _now() + timedelta(seconds=ttl)
        self._tokens.insert_one(doc)

    def get_token(self, token: str, *, kind: str) -> dict | None:
        doc = self._tokens.find_one(
            {"token_hash": hash_token(token), "kind": kind, "revoked": {"$ne": True}}
        )
        if not doc or _expired(doc.get("expires_at")):
            return None
        doc.pop("_id", None)
        return doc

    def revoke_token(self, token: str) -> None:
        try:
            self._tokens.update_one({"token_hash": hash_token(token)}, {"$set": {"revoked": True}})
        except Exception:
            pass
