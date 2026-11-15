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

import logging
import secrets
from datetime import datetime, timedelta, UTC
from typing import Any

from pymongo.errors import ConnectionFailure, PyMongoError

from .token_store import hash_token

logger = logging.getLogger(__name__)

# Distinct, greppable prefixes so raw values are self-describing in logs/debug.
CODE_PREFIX = "ckoc_"
ACCESS_PREFIX = "ckoat_"
REFRESH_PREFIX = "ckort_"

CODE_TTL_SECONDS = 300  # 5 min
ACCESS_TTL_SECONDS = 3600  # 1 hour
REFRESH_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days
TXN_TTL_SECONDS = 600  # 10 min

#: The collection that holds issued access + refresh tokens — read by the store and by
#: :func:`subject_has_live_token`, so the name is written once.
TOKENS_COLLECTION = "mcp_oauth_tokens"


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
        self._tokens = db[TOKENS_COLLECTION]
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        """Declare the store's indexes, **each one on its own**.

        The ``expires_at`` TTL indexes are what the privacy policy at ``/privacy``
        (``webapp/templates/privacy.html``, the ``mcp`` section) means by "Expired token
        records are deleted automatically" — every reader here also checks ``_expired``,
        so for correctness they are hygiene, but for that promise they are the mechanism.
        Until now one ``try`` held all eight calls, so a failure on any of them (a
        ``unique`` index that existing duplicates block, say) skipped every call after it,
        the TTL indexes included.

        A failure stays non-fatal — the store works without indexes, and an index
        failure must not stop the server from booting — but it is no longer a single
        WARNING for the lot. Two kinds of failure, told apart by pymongo's own hierarchy
        (``pymongo/errors.py``, pymongo 4.15.3):

        * **The server answered and refused this index** — ``OperationFailure`` and the
          rest of ``PyMongoError`` outside ``ConnectionFailure`` (existing duplicates that
          block a ``unique``, an ``IndexOptionsConflict``). The next index may well
          succeed, so the loop moves on. A ``unique`` or TTL index that is missing is a
          promise that quietly stopped holding (``amir-bug-patterns``,
          ``BY-STACK/mongodb.md`` pattern 9), so it is logged at ERROR with the
          collection, the keys and the options; ``subject``, the one performance index,
          at WARNING.
        * **The database did not answer** — ``ConnectionFailure``, whose subclasses
          include ``ServerSelectionTimeoutError``, ``AutoReconnect`` and
          ``NetworkTimeout``. Every remaining call would wait out the same
          server-selection timeout (``serverSelectionTimeoutMS``, from
          ``MONGODB_SERVER_SELECTION_TIMEOUT_MS`` in ``config.py``), turning one wait at
          boot into one per index. So the loop stops, with one ERROR line that names
          every index it did not get to. They are asked for again the next time an ``OAuthStore`` is built —
          the next boot of the service.

        Anything that is not a ``PyMongoError`` is a bug, and it propagates.

        **Every write to these four collections is a method of this class** —
        ``save_client`` (an upsert), ``create_txn``, ``save_code`` and ``save_token``
        (inserts), ``revoke_token`` (an update), ``delete_txn`` and ``delete_code``
        (deletes) — so each one runs on an instance whose constructor has already asked
        for the indexes. Nothing outside this module names the collections:
        :func:`subject_has_live_token`, the one reader outside the class, lives here too.
        ``test_nothing_outside_the_store_names_its_collections``
        (``tests/test_mcp_oauth_store.py``) keeps it that way.
        """
        declared = (
            ("mcp_oauth_clients", self._clients, "client_id", {"unique": True}),
            ("mcp_oauth_txns", self._txns, "txn_id", {"unique": True}),
            ("mcp_oauth_codes", self._codes, "code_hash", {"unique": True}),
            (TOKENS_COLLECTION, self._tokens, "token_hash", {"unique": True}),
            (TOKENS_COLLECTION, self._tokens, "subject", {}),
            # TTL: Mongo deletes a row once its ``expires_at`` is in the past.
            ("mcp_oauth_txns", self._txns, "expires_at", {"expireAfterSeconds": 0}),
            ("mcp_oauth_codes", self._codes, "expires_at", {"expireAfterSeconds": 0}),
            (TOKENS_COLLECTION, self._tokens, "expires_at", {"expireAfterSeconds": 0}),
        )
        for position, (name, collection, keys, options) in enumerate(declared):
            try:
                collection.create_index(keys, **options)
            except ConnectionFailure:
                not_attempted = ", ".join(f"{n} {k} {o}" for n, _, k, o in declared[position:])
                logger.error(
                    "oauth_index_failed: database unreachable — not attempted: %s; "
                    "the store keeps working without them, and the next boot asks again",
                    not_attempted,
                    exc_info=True,
                )
                return
            except PyMongoError:
                is_schema = "unique" in options or "expireAfterSeconds" in options
                logger.log(
                    logging.ERROR if is_schema else logging.WARNING,
                    "oauth_index_failed: %s %s %s — not created; the store keeps working without it",
                    name,
                    keys,
                    options,
                    exc_info=True,
                )

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

    def delete_code(self, code: str) -> bool:
        """Consume an authorization code (single-use).

        Returns ``True`` only if *this* call removed the row. Callers rely on
        that to make the exchange atomic: a replayed code deletes nothing and
        must be rejected.
        """
        try:
            res = self._codes.delete_one({"code_hash": hash_token(code)})
            return bool(getattr(res, "deleted_count", 0))
        except Exception:
            return False

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

    def revoke_token(self, token: str) -> bool:
        """Revoke a token. Returns ``True`` only if a *live* row was flipped.

        The ``revoked != True`` filter makes this idempotency-safe: revoking an
        already-revoked (or missing) token matches nothing, so refresh-token
        rotation can detect replay by checking the return value.
        """
        try:
            res = self._tokens.update_one(
                {"token_hash": hash_token(token), "revoked": {"$ne": True}},
                {"$set": {"revoked": True}},
            )
            return bool(getattr(res, "modified_count", 0))
        except Exception:
            return False


def subject_has_live_token(db: Any, subject: str) -> bool:
    """Whether ``subject`` (a CodeKeeper ``user_id`` as str) holds an OAuth token that still works.

    A token works when :meth:`OAuthStore.get_token` would hand it back: not revoked, and
    ``_expired`` says no. Access and refresh tokens both count — a client whose access
    token was revoked but whose refresh token lives can still mint a new one. Claude.ai and
    Gemini connect through this server with no PAT, so this is their only trace.

    **One document comes back: the non-revoked token that expires last.** If it still works,
    the subject has a live token; if it does not, none of the others does either, since none
    of them expires after it. So ``_expired`` on that one document is the whole answer, and
    the rule stays ``_expired``. ``expires_at >= now`` in the query only bounds the scan: it
    drops nothing ``_expired`` would keep, because :meth:`OAuthStore.save_token` gives every
    row a date, and it is ``>=`` and not ``>`` so the two agree on the instant itself.

    Why one document: refresh rotation revokes the token it was handed
    (``exchange_refresh_token`` in ``mcp_server/oauth_provider.py``), and a revoked row stays
    until its own ``expires_at`` (``REFRESH_TTL_SECONDS``), so a client that stays connected
    keeps adding rows under its subject. Pulling them to test here would make the server fill
    a whole first batch before anything came back — reading past every revoked row when few
    are live. ``tests/test_first_steps_mongo.py`` measures what the server reads.

    A function over the database and not a method, on purpose: ``OAuthStore()`` runs its
    ``create_index`` calls on every instantiation, and this is asked while a page renders
    (the "first steps" checklist on the webapp dashboard).
    """
    newest = db[TOKENS_COLLECTION].find_one(
        {"subject": str(subject), "revoked": {"$ne": True}, "expires_at": {"$gte": _now()}},
        {"expires_at": 1},
        sort=[("expires_at", -1)],
    )
    return newest is not None and not _expired(newest.get("expires_at"))
