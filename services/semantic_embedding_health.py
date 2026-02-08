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
    get_raw_db_best_effort,
    make_embedding_key,
    normalize_model_name,
    upsert_embedding_settings,
)

logger = logging.getLogger(__name__)

_LOCK_ID = "semantic_embedding_model_upgrade"
_LOCK_LEASE_SECONDS = int(os.getenv("EMBEDDING_MODEL_UPGRADE_LOCK_LEASE_SECONDS", "90") or 90)
_AUTO_DIMENSION_UPGRADE = str(os.getenv("EMBEDDING_AUTO_DIMENSION_UPGRADE", "") or "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


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
    raw_db = get_raw_db_best_effort()
    if raw_db is None:
        # no DB => run without lock (best-effort)
        return True, _owner_id()

    coll = _get_collection(raw_db, "bot_locks")
    if coll is None or not hasattr(coll, "insert_one"):
        return True, _owner_id()

    owner = _owner_id()
    now = _utcnow()
    exp = now + timedelta(seconds=max(10, int(lease_seconds)))

    # DuplicateKeyError may be unavailable in minimal environments.
    # Keep detection narrow so we don't accidentally treat all exceptions as "duplicate key".
    try:
        from pymongo.errors import DuplicateKeyError as _DuplicateKeyError  # type: ignore
    except Exception:  # pragma: no cover
        _DuplicateKeyError = None  # type: ignore

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
    except Exception as e:
        # Handle "duplicate key" (lock already exists) specially; otherwise fail-open.
        is_dup = False
        try:
            if _DuplicateKeyError is not None and isinstance(e, _DuplicateKeyError):
                is_dup = True
        except Exception:
            is_dup = False
        if not is_dup:
            # Heuristic: sometimes we don't have the exact exception type
            try:
                code = getattr(e, "code", None)
                if int(code or 0) == 11000:
                    is_dup = True
            except Exception:
                pass
        if not is_dup:
            try:
                msg = str(e or "").lower()
                if "duplicate key" in msg or "e11000" in msg:
                    is_dup = True
            except Exception:
                pass

        if not is_dup:
            return True, owner

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


def _release_short_lock(*, lock_id: str, owner: str) -> None:
    raw_db = get_raw_db_best_effort()
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
    raw_db = get_raw_db_best_effort()
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


def _pick_best_candidate(
    allowlist: List[str],
    available: List[str],
    *,
    fallback_to_allowlist_if_no_match: bool = True,
) -> List[str]:
    """
    Returns candidates in preferred order (latest first).
    We keep it simple: sort by numeric suffix if present, otherwise lexical.
    """
    allow = [normalize_model_name(x) for x in (allowlist or []) if str(x).strip()]
    avail = {normalize_model_name(x) for x in (available or []) if str(x).strip()}
    matched = [m for m in allow if m in avail]
    candidates = matched if matched else (allow if fallback_to_allowlist_if_no_match else [])

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


def _supports_embed_content(model_doc: Dict[str, Any]) -> bool:
    """
    True if model supports embedContent according to supportedGenerationMethods (when present).
    If field missing, return False (be conservative).
    """
    if not isinstance(model_doc, dict):
        return False
    methods = model_doc.get("supportedGenerationMethods")
    if not isinstance(methods, list):
        return False
    try:
        return any(str(m).strip() == "embedContent" for m in methods)
    except Exception:
        return False


def _auto_pick_from_provider(models: List[Dict[str, Any]]) -> List[str]:
    """
    Pick candidates directly from provider list (embedContent-capable), sorted by heuristic.
    """
    names: List[str] = []
    for m in models or []:
        if not _supports_embed_content(m):
            continue
        try:
            name = normalize_model_name(str(m.get("name") or ""))
        except Exception:
            name = ""
        if not name:
            continue
        # Prefer obvious embedding models
        if "embedding" not in name.lower():
            continue
        names.append(name)
    # de-dup
    seen = set()
    uniq: List[str] = []
    for n in names:
        if n in seen:
            continue
        seen.add(n)
        uniq.append(n)
    # reuse scoring from allowlist picker by treating provider list as "available"
    return _pick_best_candidate(allowlist=uniq, available=uniq, fallback_to_allowlist_if_no_match=False)
def _parse_dimension_mismatch(body: str) -> Optional[Tuple[int, int]]:
    """
    Parse internal diagnostic body like: "dimension_mismatch expected=768 actual=1536"
    """
    try:
        text = str(body or "").strip().lower()
    except Exception:
        return None
    if "dimension_mismatch" not in text:
        return None
    exp = None
    act = None
    for part in text.split():
        if part.startswith("expected="):
            try:
                exp = int(part.split("=", 1)[1])
            except Exception:
                exp = None
        if part.startswith("actual="):
            try:
                act = int(part.split("=", 1)[1])
            except Exception:
                act = None
    if exp and act:
        return int(exp), int(act)
    return None


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
                # אם לא הצלחנו לשמור קונפיג (DB תקול/הרשאות), אל נחזור כאן.
                # נמשיך לנסות מודלים חלופיים שעשויים להצליח להישמר.
                logger.warning(
                    "Embedding API version v1 seems to work, but failed to persist config; continuing with model fallback search."
                )

        # Otherwise: list available models and pick candidates.
        # We prefer allowlist∩available, but if it doesn't match reality we can auto-pick
        # embedContent-capable models directly from the provider list.
        models_docs = await service.list_models_detailed(api_version=settings.api_version) or []
        # If listing fails on v1beta, try v1
        if not models_docs and settings.api_version != "v1":
            models_docs = await service.list_models_detailed(api_version="v1") or []

        available_models: List[str] = []
        embed_capable: List[str] = []
        try:
            for m in models_docs:
                if not isinstance(m, dict):
                    continue
                name = normalize_model_name(str(m.get("name") or ""))
                if not name:
                    continue
                available_models.append(name)
                if _supports_embed_content(m):
                    embed_capable.append(name)
        except Exception:
            available_models = []
            embed_capable = []

        # 1) Prefer allowlist ∩ embedContent-capable models (when list_models succeeded)
        candidates = _pick_best_candidate(
            settings.allowlist,
            embed_capable or available_models,
            fallback_to_allowlist_if_no_match=False,
        )

        # 2) If allowlist doesn't match reality, auto-pick from provider list
        if not candidates:
            candidates = _auto_pick_from_provider(models_docs)

        # 3) Last resort: try any embedContent-capable model (even if name doesn't include "embedding")
        if not candidates and embed_capable:
            candidates = _pick_best_candidate(
                embed_capable,
                embed_capable,
                fallback_to_allowlist_if_no_match=False,
            )
        for candidate in candidates:
            for api_version in [settings.api_version, "v1"] if settings.api_version != "v1" else ["v1"]:
                emb_c, st_c, body_c = await service.generate_embedding_with_status(
                    test_text,
                    model=candidate,
                    api_version=api_version,
                    dimensions=settings.dimensions,
                )
                if not emb_c:
                    # Dimension mismatch: optionally retry without outputDimensionality and upgrade dims.
                    mm = _parse_dimension_mismatch(body_c)
                    if mm:
                        exp_dim, act_dim = mm
                        msg = (
                            f"Embedding dimension mismatch while probing candidate={candidate}: "
                            f"expected={exp_dim} actual={act_dim}. "
                            + ("Auto-upgrading dimensions." if _AUTO_DIMENSION_UPGRADE else "Skipping (set EMBEDDING_AUTO_DIMENSION_UPGRADE=1 to allow).")
                        )
                        logger.warning(msg)
                        try:
                            emit_event(
                                "embedding_dimension_mismatch_detected",
                                severity="warn",
                                candidate=str(candidate),
                                api_version=str(api_version),
                                expected=int(exp_dim),
                                actual=int(act_dim),
                                auto_upgrade=bool(_AUTO_DIMENSION_UPGRADE),
                            )
                        except Exception:
                            pass

                        if not _AUTO_DIMENSION_UPGRADE:
                            continue

                        # Retry without requesting a fixed dimensionality (provider default),
                        # then adopt returned dimension.
                        emb_free, st_free, _body_free = await service.generate_embedding_with_status(
                            test_text,
                            model=candidate,
                            api_version=api_version,
                            dimensions=0,
                        )
                        if not emb_free:
                            continue

                        new_dim = int(len(emb_free) or 0)
                        if new_dim <= 0:
                            continue

                        prev_key = settings.active_key
                        new_key = make_embedding_key(
                            api_version=api_version,
                            model=normalize_model_name(candidate),
                            dimensions=new_dim,
                        )

                        ok = upsert_embedding_settings(
                            api_version=api_version,
                            model=candidate,
                            dimensions=new_dim,
                            allowlist=list(settings.allowlist),
                            legacy_key=prev_key,
                            active_key=new_key,
                            reason="auto_upgrade_model_dim_change",
                            extra={
                                "lastValidatedAt": _utcnow(),
                                "lastUpgrade": {
                                    "from": {
                                        "api_version": settings.api_version,
                                        "model": settings.model,
                                        "key": prev_key,
                                        "dimensions": int(settings.dimensions),
                                    },
                                    "to": {
                                        "api_version": api_version,
                                        "model": candidate,
                                        "key": new_key,
                                        "dimensions": int(new_dim),
                                    },
                                    "note": "dimension_changed_requires_vector_index_update",
                                },
                            },
                        )
                        if not ok:
                            continue

                        marked = _mark_all_snippets_for_reindex(
                            target_key=new_key,
                            reason=f"auto_upgrade_model_dim_change:{settings.model}->{candidate}",
                        )
                        logger.warning(
                            "שדרוג מודל embeddings כלל שינוי מימד (%s→%s). "
                            "יתכן שצריך לעדכן את Mongo Atlas vector index (`vector_index`) כדי שהחיפוש הסמנטי יחזור לעבוד. "
                            "מסמן Re-index (marked=%s).",
                            int(settings.dimensions),
                            int(new_dim),
                            int(marked),
                        )
                        try:
                            emit_event(
                                "embedding_model_upgraded",
                                severity="warn",
                                kind="model_dim_change",
                                from_model=settings.model,
                                to_model=candidate,
                                from_key=prev_key,
                                to_key=new_key,
                                api_version=api_version,
                                from_dim=int(settings.dimensions),
                                to_dim=int(new_dim),
                                marked=int(marked),
                                requires_vector_index_update=True,
                            )
                        except Exception:
                            pass
                        return

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


def sync_probe_and_upgrade() -> None:
    """
    Sync version of the embedding health-check for contexts where asyncio
    is unavailable (e.g. Flask/gunicorn webapp thread).  Uses httpx.Client
    (sync) so no event loop is needed.
    """
    import httpx as _httpx

    logger.info("sync_probe_and_upgrade: starting webapp embedding health-check")

    acquired, owner = _acquire_short_lock(
        lock_id=_LOCK_ID, lease_seconds=_LOCK_LEASE_SECONDS,
    )
    if not acquired:
        logger.info("sync_probe_and_upgrade: lock not acquired, skipping")
        return

    try:
        api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
        if not api_key:
            logger.warning("sync_probe_and_upgrade: no GEMINI_API_KEY set, skipping")
            return

        settings = get_embedding_settings_cached(allow_db=True)
        model_n = normalize_model_name(settings.model)
        if not model_n:
            logger.warning("sync_probe_and_upgrade: empty model name, skipping")
            return

        logger.info(
            "sync_probe_and_upgrade: testing model=%s api=%s dim=%s",
            model_n, settings.api_version, settings.dimensions,
        )

        def _base(av: str) -> str:
            return f"https://generativelanguage.googleapis.com/{av}/models"

        def _probe(client, m: str, av: str, dim: int):
            url = f"{_base(av)}/{m}:embedContent"
            payload: Dict[str, Any] = {
                "model": f"models/{m}",
                "content": {"parts": [{"text": "healthcheck"}]},
            }
            if dim and int(dim) > 0:
                payload["outputDimensionality"] = int(dim)
            r = client.post(
                url, json=payload, params={"key": api_key},
                headers={"Content-Type": "application/json"},
            )
            if r.status_code == 200:
                try:
                    return r.json()["embedding"]["values"], 200
                except Exception:
                    return None, 200
            return None, int(r.status_code)

        with _httpx.Client(timeout=15) as client:
            # 1. Test current model
            emb, st = _probe(client, model_n, settings.api_version,
                             settings.dimensions)
            if emb:
                logger.info("sync_probe_and_upgrade: current model works OK")
                upsert_embedding_settings(
                    api_version=settings.api_version,
                    model=model_n,
                    dimensions=settings.dimensions,
                    allowlist=list(settings.allowlist),
                    legacy_key=settings.legacy_key,
                    active_key=settings.active_key,
                    reason="startup_validated_webapp",
                    extra={"lastValidatedAt": _utcnow()},
                )
                return

            if st != 404:
                logger.warning(
                    "sync_probe_and_upgrade: model %s returned status %s (not 404), skipping",
                    model_n, st,
                )
                return

            logger.warning(
                "sync_probe_and_upgrade: model %s returned 404, starting self-heal",
                model_n,
            )

            # 2. Same model, v1 fallback
            if settings.api_version != "v1":
                emb2, _ = _probe(client, model_n, "v1",
                                 settings.dimensions)
                if emb2:
                    ok = upsert_embedding_settings(
                        api_version="v1",
                        model=model_n,
                        dimensions=settings.dimensions,
                        allowlist=list(settings.allowlist),
                        legacy_key=settings.legacy_key,
                        active_key=settings.active_key,
                        reason="auto_upgrade_api_version_webapp",
                    )
                    if ok:
                        logger.warning(
                            "Webapp health-check: model %s switched to v1",
                            model_n,
                        )
                        return
                    # Persist failed – fall through to candidate search
                    logger.warning(
                        "Webapp health-check: v1 works for %s but "
                        "failed to persist config; trying candidates",
                        model_n,
                    )

            # 3. List models & pick candidates
            candidates: List[Tuple[str, str]] = []
            api_versions = (
                [settings.api_version, "v1"]
                if settings.api_version != "v1" else ["v1"]
            )
            for av in api_versions:
                r = client.get(
                    _base(av), params={"key": api_key},
                    headers={"Content-Type": "application/json"},
                )
                if r.status_code != 200:
                    continue
                for m in (r.json().get("models") or []):
                    name = normalize_model_name(str(m.get("name") or ""))
                    methods = m.get("supportedGenerationMethods") or []
                    if ("embedContent" in methods
                            and "embedding" in name.lower()):
                        candidates.append((name, av))
                if candidates:
                    break

            if not candidates:
                logger.warning("Webapp health-check: no candidates found")
                return

            # Sort: allowlist first, then by version suffix descending
            allow_set = set(settings.allowlist)

            def _score(item):
                n, _ = item
                in_allow = 1 if n in allow_set else 0
                ver = 0
                parts = n.split("-")
                if parts and parts[-1].isdigit():
                    ver = int(parts[-1])
                return (in_allow, ver)

            candidates.sort(key=_score, reverse=True)

            # 4. Probe candidates
            for cand_name, cand_av in candidates[:10]:
                emb_c, st_c = _probe(
                    client, cand_name, cand_av, settings.dimensions,
                )
                if not emb_c:
                    # Dimension mismatch: retry without fixed
                    # dimensionality if auto-upgrade is enabled.
                    if st_c == 400 or st_c == 422:
                        if _AUTO_DIMENSION_UPGRADE:
                            emb_free, st_free = _probe(
                                client, cand_name, cand_av, 0,
                            )
                            if emb_free:
                                emb_c = emb_free
                                logger.warning(
                                    "Webapp health-check: candidate "
                                    "%s succeeded without fixed dim "
                                    "(auto-dimension upgrade)",
                                    cand_name,
                                )
                            else:
                                continue
                        else:
                            logger.info(
                                "Webapp health-check: candidate %s "
                                "failed (status=%s), set "
                                "EMBEDDING_AUTO_DIMENSION_UPGRADE=1 "
                                "to retry without fixed dim",
                                cand_name, st_c,
                            )
                            continue
                    else:
                        continue
                new_dim = len(emb_c)
                new_key = make_embedding_key(
                    api_version=cand_av,
                    model=cand_name,
                    dimensions=new_dim,
                )
                ok = upsert_embedding_settings(
                    api_version=cand_av,
                    model=cand_name,
                    dimensions=new_dim,
                    allowlist=list(settings.allowlist),
                    legacy_key=settings.active_key,
                    active_key=new_key,
                    reason="auto_upgrade_model_404_webapp",
                    extra={"lastValidatedAt": _utcnow()},
                )
                if not ok:
                    continue
                _mark_all_snippets_for_reindex(
                    target_key=new_key,
                    reason=f"auto_upgrade_webapp:{model_n}->{cand_name}",
                )
                logger.warning(
                    "Webapp health-check: upgraded %s -> %s (api=%s)",
                    model_n, cand_name, cand_av,
                )
                return

            logger.warning(
                "Webapp health-check: no working model found"
            )
    finally:
        try:
            _release_short_lock(lock_id=_LOCK_ID, owner=owner)
        except Exception:
            pass
