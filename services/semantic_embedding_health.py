"""
בדיקת בריאות למודל Embedding + החלפה אוטומטית (best-effort).

ההתנהגות:
- נטען את ה-EmbeddingSettings (DB אם קיים, אחרת ENV).
- נבצע "ping" קצר ל-embedContent.
- אם יש 404 על המודל: ננסה לבחור מודל חלופי מתוך allowlist לפי list_models().
- לאחר החלפה: נסמן reindex ע"י סימון snippets כ-needs_embedding/needs_chunking.

חשוב:
- הכל best-effort (fail-open). אם משהו נכשל – לא מפילים את השירות.
- משתמשים ב-distributed lock קצר בקולקציה `bot_locks` כדי לא להריץ שדרוג במקביל.
"""

from __future__ import annotations

import logging
import os
import socket
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

try:
    from observability import emit_event  # type: ignore
except Exception:  # pragma: no cover
    def emit_event(event: str, severity: str = "info", **fields):  # type: ignore
        return None

from services.embedding_service import EmbeddingService
from services.semantic_embedding_settings import (
    EmbeddingSettings,
    get_embedding_settings_cached,
    make_embedding_key,
    normalize_model_name,
    upsert_embedding_settings,
)

logger = logging.getLogger(__name__)

_LOCK_ID = "semantic_embedding_model_upgrade"
_LOCK_LEASE_SECONDS = int(os.getenv("EMBEDDING_MODEL_UPGRADE_LOCK_LEASE_SECONDS", "90") or 90)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _owner_id() -> str:
    try:
        host = socket.gethostname()
    except Exception:
        host = "unknown-host"
    try:
        pid = int(os.getpid())
    except Exception:
        pid = 0
    return f"{host}:{pid}:{uuid.uuid4().hex[:8]}"


def _get_raw_db_best_effort():
    try:
        if str(os.getenv("DISABLE_DB", "") or "").strip().lower() in {"1", "true", "yes", "on"}:
            return None
    except Exception:
        return None
    try:
        if not str(os.getenv("MONGODB_URL", "") or "").strip():
            return None
    except Exception:
        return None
    try:
        from services.db_provider import get_db as _get_db  # type: ignore

        return _get_db()
    except Exception:
        pass
    try:
        from database import db as _db_manager  # local import
    except Exception:
        _db_manager = None
    try:
        raw_db = getattr(_db_manager, "db", None) if _db_manager is not None else None
        if raw_db is not None:
            return raw_db
    except Exception:
        pass
    try:
        from services.db_provider import get_db as _get_db  # type: ignore

        return _get_db()
    except Exception:
        return None


def _get_collection(raw_db, name: str):
    try:
        return raw_db[name]
    except Exception:
        return getattr(raw_db, name, None)


def _acquire_short_lock(*, lock_id: str, lease_seconds: int) -> Tuple[bool, str]:
    """
    Acquire a short-lived distributed lock in `bot_locks`.
    Returns (acquired, owner_id).
    """
    raw_db = _get_raw_db_best_effort()
    if raw_db is None:
        # no DB => run without lock (best-effort)
        return True, _owner_id()

    coll = _get_collection(raw_db, "bot_locks")
    if coll is None or not hasattr(coll, "insert_one"):
        return True, _owner_id()

    owner = _owner_id()
    now = _utcnow()
    exp = now + timedelta(seconds=max(10, int(lease_seconds)))

    try:
        from pymongo.errors import DuplicateKeyError  # type: ignore
    except Exception:  # pragma: no cover
        DuplicateKeyError = Exception  # type: ignore

    try:
        coll.insert_one(
            {
                "_id": str(lock_id),
                "owner": owner,
                "createdAt": now,
                "updatedAt": now,
                "expiresAt": exp,
            }
        )
        return True, owner
    except DuplicateKeyError:
        # try takeover if expired
        try:
            try:
                from pymongo import ReturnDocument  # type: ignore

                _ret_after = ReturnDocument.AFTER
            except Exception:  # pragma: no cover
                _ret_after = True
            res = coll.find_one_and_update(
                {"_id": str(lock_id), "expiresAt": {"$lte": now}},
                {"$set": {"owner": owner, "updatedAt": now, "expiresAt": exp}},
                return_document=_ret_after,
            )
            if isinstance(res, dict) and res.get("owner") == owner:
                return True, owner
        except Exception:
            pass
        return False, owner
    except Exception:
        return True, owner


def _release_short_lock(*, lock_id: str, owner: str) -> None:
    raw_db = _get_raw_db_best_effort()
    if raw_db is None:
        return
    coll = _get_collection(raw_db, "bot_locks")
    if coll is None or not hasattr(coll, "delete_one"):
        return
    try:
        coll.delete_one({"_id": str(lock_id), "owner": str(owner)})
    except Exception:
        return


def _mark_all_snippets_for_reindex(*, target_key: str, reason: str) -> int:
    """
    Mark all active snippets for re-embedding. Returns modified_count (best-effort).
    """
    raw_db = _get_raw_db_best_effort()
    if raw_db is None:
        return 0
    files = _get_collection(raw_db, "code_snippets") or _get_collection(raw_db, "files")
    if files is None or not hasattr(files, "update_many"):
        return 0
    now = _utcnow()
    try:
        res = files.update_many(
            {"is_active": True},
            {
                "$set": {
                    "needs_embedding": True,
                    "needs_chunking": True,
                    "embeddingTargetKey": str(target_key),
                    "embeddingTargetUpdatedAt": now,
                    "updated_at": now,
                }
            },
        )
        return int(getattr(res, "modified_count", 0) or 0)
    except Exception:
        return 0


def _pick_best_candidate(allowlist: List[str], available: List[str]) -> List[str]:
    """
    Returns candidates in preferred order (latest first).
    We keep it simple: sort by numeric suffix if present, otherwise lexical.
    """
    allow = [normalize_model_name(x) for x in (allowlist or []) if str(x).strip()]
    avail = {normalize_model_name(x) for x in (available or []) if str(x).strip()}
    candidates = [m for m in allow if m in avail] or allow

    def _score(name: str) -> Tuple[int, str]:
        # text-embedding-006 => 6
        s = str(name)
        n = 0
        try:
            parts = s.split("-")
            if parts and parts[-1].isdigit():
                n = int(parts[-1])
        except Exception:
            n = 0
        return (n, s)

    candidates.sort(key=_score, reverse=True)
    return candidates


async def maybe_upgrade_embedding_model_on_startup() -> None:
    """
    Startup hook: validate current embedding model; if 404 -> auto-upgrade.
    """
    acquired, owner = _acquire_short_lock(lock_id=_LOCK_ID, lease_seconds=_LOCK_LEASE_SECONDS)
    if not acquired:
        return
    try:
        settings = get_embedding_settings_cached(allow_db=True)

        # ensure a baseline doc exists in DB (best-effort)
        try:
            upsert_embedding_settings(
                api_version=settings.api_version,
                model=settings.model,
                dimensions=settings.dimensions,
                allowlist=list(settings.allowlist),
                legacy_key=settings.legacy_key,
                active_key=settings.active_key,
                reason="startup_baseline",
                extra={"lastValidatedAt": None},
                create_only=True,
            )
        except Exception:
            pass

        service = EmbeddingService(api_key=(os.getenv("GEMINI_API_KEY") or None))
        if not service.is_available():
            return

        test_text = "healthcheck"
        emb, status, body = await service.generate_embedding_with_status(
            test_text,
            model=settings.model,
            api_version=settings.api_version,
            dimensions=settings.dimensions,
        )
        if emb:
            try:
                upsert_embedding_settings(
                    api_version=settings.api_version,
                    model=settings.model,
                    dimensions=settings.dimensions,
                    allowlist=list(settings.allowlist),
                    legacy_key=settings.legacy_key,
                    active_key=settings.active_key,
                    reason="startup_validated",
                    extra={"lastValidatedAt": _utcnow()},
                )
            except Exception:
                pass
            return

        # Only auto-upgrade on 404 (model not found). Anything else: don't churn.
        if int(status or 0) != 404:
            return

        # Try: same model but stable API version (v1) might exist.
        if settings.api_version != "v1":
            emb2, status2, _body2 = await service.generate_embedding_with_status(
                test_text,
                model=settings.model,
                api_version="v1",
                dimensions=settings.dimensions,
            )
            if emb2:
                ok = upsert_embedding_settings(
                    api_version="v1",
                    model=settings.model,
                    dimensions=settings.dimensions,
                    allowlist=list(settings.allowlist),
                    legacy_key=settings.legacy_key,
                    active_key=settings.active_key,  # key is model/dim; unchanged
                    reason="auto_upgrade_api_version",
                    extra={
                        "lastValidatedAt": _utcnow(),
                        "lastUpgrade": {
                            "from": {"api_version": settings.api_version, "model": settings.model},
                            "to": {"api_version": "v1", "model": settings.model},
                            "status": int(status2 or 0),
                        },
                    },
                )
                if ok:
                    msg = f"Detected deprecated embedding API version; switched to v1 for model={settings.model}"
                    logger.warning(msg)
                    try:
                        emit_event(
                            "embedding_model_upgraded",
                            severity="warn",
                            kind="api_version",
                            from_api_version=settings.api_version,
                            to_api_version="v1",
                            model=settings.model,
                        )
                    except Exception:
                        pass
                return

        # Otherwise: list available models and pick newest from allowlist
        available_models = await service.list_models(api_version=settings.api_version) or []
        # If listing fails on v1beta, try v1
        if not available_models and settings.api_version != "v1":
            available_models = await service.list_models(api_version="v1") or []

        candidates = _pick_best_candidate(settings.allowlist, available_models)
        for candidate in candidates:
            for api_version in [settings.api_version, "v1"] if settings.api_version != "v1" else ["v1"]:
                emb_c, st_c, _body_c = await service.generate_embedding_with_status(
                    test_text,
                    model=candidate,
                    api_version=api_version,
                    dimensions=settings.dimensions,
                )
                if not emb_c:
                    continue

                prev_key = settings.active_key
                new_key = make_embedding_key(
                    api_version=api_version,
                    model=normalize_model_name(candidate),
                    dimensions=int(settings.dimensions),
                )

                # Keep legacy_key as previous key so old docs (missing metadata) won't be treated as new.
                ok = upsert_embedding_settings(
                    api_version=api_version,
                    model=candidate,
                    dimensions=settings.dimensions,
                    allowlist=list(settings.allowlist),
                    legacy_key=prev_key,
                    active_key=new_key,
                    reason="auto_upgrade_model_404",
                    extra={
                        "lastValidatedAt": _utcnow(),
                        "lastUpgrade": {
                            "from": {
                                "api_version": settings.api_version,
                                "model": settings.model,
                                "key": prev_key,
                            },
                            "to": {"api_version": api_version, "model": candidate, "key": new_key},
                            "error": {"status": int(status or 0), "body": str(body or "")[:500]},
                        },
                    },
                )
                if not ok:
                    continue

                # Trigger reindex
                marked = _mark_all_snippets_for_reindex(
                    target_key=new_key,
                    reason=f"auto_upgrade_model_404:{settings.model}->{candidate}",
                )

                msg = (
                    f"זיהיתי מודל embedding מיושן (404). שדרגתי ל-{candidate} "
                    f"(api={api_version}) ומסמן Re-index לכל הקבצים (marked={marked})."
                )
                logger.warning(msg)
                try:
                    emit_event(
                        "embedding_model_upgraded",
                        severity="warn",
                        kind="model",
                        from_model=settings.model,
                        to_model=candidate,
                        from_key=prev_key,
                        to_key=new_key,
                        api_version=api_version,
                        marked=int(marked),
                    )
                except Exception:
                    pass
                return
    finally:
        try:
            _release_short_lock(lock_id=_LOCK_ID, owner=owner)
        except Exception:
            pass

