"""
ניהול קונפיגורציה למודל Embedding בצורה דינמית.

מטרות:
- להימנע מ-hardcoding של שם מודל.
- לאפשר החלפה אוטומטית (fallback) כשמודל מוחזר 404.
- לשמור על תאימות לאחור: מסמכים ישנים ללא metadata ייחשבו כ"legacy key".

הקונפיגורציה נשמרת ב-MongoDB בקולקציה `system_config` במסמך:
  _id = "semantic_embedding"
"""

from __future__ import annotations

import os
import time
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

SYSTEM_CONFIG_COLLECTION = "system_config"
SYSTEM_CONFIG_ID = "semantic_embedding"

_CACHE_TTL_SECONDS = float(os.getenv("EMBEDDING_SETTINGS_CACHE_TTL_SECONDS", "30") or 30)
_cached_value: Optional["EmbeddingSettings"] = None
_cached_at_monotonic: float = 0.0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_api_version(value: Optional[str]) -> str:
    v = str(value or "").strip().lower()
    if not v:
        return "v1beta"
    # accept both "v1" and "/v1"
    v = v.lstrip("/")
    if v in {"v1", "v1beta"}:
        return v
    # fail-safe: keep legacy default
    return "v1beta"


def normalize_model_name(model: str) -> str:
    """
    Normalize model identifiers.
    Accepts: "text-embedding-004" / "models/text-embedding-004"
    Returns: "text-embedding-004"
    """
    m = str(model or "").strip()
    if not m:
        return ""
    if m.startswith("models/"):
        return m[len("models/") :].strip()
    return m


def make_embedding_key(*, api_version: str, model: str, dimensions: int) -> str:
    """
    מפתח "גרסת embeddings" לנתונים.

    חשוב:
    - המפתח נועד למנוע ערבוב embeddings בין *מודלים שונים* או *מימדים שונים*.
    - גרסת API (v1beta/v1) היא "transport" ולא בהכרח מחייבת reindex אם המודל זהה.
      לכן, כדי להיות יציבים תפעולית, אנחנו *לא* כוללים את api_version במפתח.
    """
    _ = _normalize_api_version(api_version)  # kept for forward-compat / validation
    mn = normalize_model_name(model)
    try:
        dim = int(dimensions)
    except Exception:
        dim = 768
    return f"{mn}/{dim}"


@dataclass(frozen=True)
class EmbeddingSettings:
    api_version: str
    model: str
    dimensions: int
    allowlist: List[str]
    active_key: str
    legacy_key: str
    updated_at: Optional[datetime] = None

    @staticmethod
    def from_env() -> "EmbeddingSettings":
        # Prefer Pydantic settings if available; fall back to ENV
        try:
            from config import config as cfg  # type: ignore
        except Exception:  # pragma: no cover
            cfg = None

        api_version = _normalize_api_version(os.getenv("GEMINI_API_VERSION") or os.getenv("GEMINI_EMBEDDING_API_VERSION"))

        model = normalize_model_name(
            os.getenv("GEMINI_EMBEDDING_MODEL")
            or os.getenv("GEMINI_MODEL_EMBEDDING")
            or "text-embedding-004"
        )

        try:
            dimensions = int(getattr(cfg, "EMBEDDING_DIMENSIONS", None) or os.getenv("EMBEDDING_DIMENSIONS") or 768)
        except Exception:
            dimensions = 768

        allow_raw = (
            os.getenv("GEMINI_EMBEDDING_MODEL_ALLOWLIST")
            or os.getenv("SEMANTIC_EMBEDDING_MODEL_ALLOWLIST")
            or ""
        )
        allowlist = [normalize_model_name(x) for x in str(allow_raw).split(",") if str(x).strip()]
        if not allowlist:
            # שמרני: רק מודלים ידועים/מקובלים - אפשר להרחיב ב-ENV או ב-DB
            allowlist = ["text-embedding-006", "text-embedding-005", "text-embedding-004"]

        active_key = make_embedding_key(api_version=api_version, model=model, dimensions=dimensions)
        # בהיעדר DB - legacy=active כדי לשמר תאימות למסמכים ישנים (ללא metadata)
        legacy_key = active_key
        return EmbeddingSettings(
            api_version=api_version,
            model=model,
            dimensions=dimensions,
            allowlist=allowlist,
            active_key=active_key,
            legacy_key=legacy_key,
            updated_at=None,
        )


def get_raw_db_best_effort():
    """
    Best-effort raw DB accessor (PyMongo Database).
    Fail-open: returns None when DB is disabled/unavailable.
    """
    # חשוב: אל תייבא `database` אם אין בכלל חיבור DB (אחרת DatabaseManager עלול לזרוק בזמן import).
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

    # Prefer the standalone provider to avoid heavy imports / circular deps.
    try:
        from services.db_provider import get_db as _get_db  # type: ignore

        return _get_db()
    except Exception:
        return None


def _get_system_config_collection(raw_db):
    try:
        return raw_db[SYSTEM_CONFIG_COLLECTION]
    except Exception:
        return getattr(raw_db, SYSTEM_CONFIG_COLLECTION, None)


def _coerce_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x) for x in value if str(x).strip()]
    # allow comma separated
    try:
        txt = str(value)
        return [x.strip() for x in txt.split(",") if x.strip()]
    except Exception:
        return []


def _settings_from_doc(doc: Dict[str, Any]) -> Optional[EmbeddingSettings]:
    if not isinstance(doc, dict):
        return None
    api_version = _normalize_api_version(doc.get("api_version"))
    model = normalize_model_name(doc.get("model") or "")
    if not model:
        return None
    try:
        dimensions = int(doc.get("dimensions") or 768)
    except Exception:
        dimensions = 768
    allowlist = [normalize_model_name(x) for x in _coerce_list(doc.get("allowlist"))]
    if not allowlist:
        allowlist = ["text-embedding-006", "text-embedding-005", "text-embedding-004"]

    active_key = str(doc.get("active_key") or "").strip() or make_embedding_key(
        api_version=api_version, model=model, dimensions=dimensions
    )
    legacy_key = str(doc.get("legacy_key") or "").strip() or active_key
    updated_at = doc.get("updatedAt") or doc.get("updated_at") or None
    if isinstance(updated_at, str):
        try:
            updated_at = datetime.fromisoformat(updated_at)
        except Exception:
            updated_at = None
    if isinstance(updated_at, datetime) and updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    return EmbeddingSettings(
        api_version=api_version,
        model=model,
        dimensions=dimensions,
        allowlist=allowlist,
        active_key=active_key,
        legacy_key=legacy_key,
        updated_at=updated_at if isinstance(updated_at, datetime) else None,
    )


def get_embedding_settings_cached(*, allow_db: bool = True) -> EmbeddingSettings:
    """
    Sync getter with in-memory cache (for hot paths).
    """
    global _cached_value, _cached_at_monotonic
    now_m = time.monotonic()
    if _cached_value is not None and (now_m - float(_cached_at_monotonic)) < float(_CACHE_TTL_SECONDS):
        return _cached_value

    settings = None
    if allow_db:
        try:
            raw_db = get_raw_db_best_effort()
            if raw_db is not None:
                coll = _get_system_config_collection(raw_db)
                if coll is not None and hasattr(coll, "find_one"):
                    doc = coll.find_one({"_id": SYSTEM_CONFIG_ID})
                    settings = _settings_from_doc(doc) if isinstance(doc, dict) else None
        except Exception:
            settings = None

    if settings is None:
        settings = EmbeddingSettings.from_env()

    _cached_value = settings
    _cached_at_monotonic = now_m
    return settings


def upsert_embedding_settings(
    *,
    api_version: str,
    model: str,
    dimensions: int,
    allowlist: Optional[List[str]] = None,
    legacy_key: Optional[str] = None,
    active_key: Optional[str] = None,
    reason: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
    create_only: bool = False,
) -> bool:
    """
    עדכון קונפיג ב-DB (best-effort). Sync.
    """
    raw_db = get_raw_db_best_effort()
    if raw_db is None:
        return False
    coll = _get_system_config_collection(raw_db)
    if coll is None or not hasattr(coll, "update_one"):
        return False

    api_version_n = _normalize_api_version(api_version)
    model_n = normalize_model_name(model)
    try:
        dim = int(dimensions)
    except Exception:
        dim = 768

    allow = [normalize_model_name(x) for x in (allowlist or []) if str(x).strip()]
    if not allow:
        allow = ["text-embedding-006", "text-embedding-005", "text-embedding-004"]

    ak = (str(active_key or "").strip()) or make_embedding_key(
        api_version=api_version_n, model=model_n, dimensions=dim
    )
    lk = (str(legacy_key or "").strip()) or ak

    now = _utcnow()
    update: Dict[str, Any] = {
        "api_version": api_version_n,
        "model": model_n,
        "dimensions": dim,
        "allowlist": allow,
        "active_key": ak,
        "legacy_key": lk,
        "updatedAt": now,
    }
    if reason:
        update["lastChangeReason"] = str(reason)
        update["lastChangeAt"] = now
    if extra and isinstance(extra, dict):
        update.update(extra)

    try:
        if create_only:
            # יצירה בלבד: לא לשנות מסמך קיים (כדי לא "לגעת" בקונפיג בכל startup)
            coll.update_one(
                {"_id": SYSTEM_CONFIG_ID},
                {"$setOnInsert": {**update, "createdAt": now}},
                upsert=True,
            )
        else:
            coll.update_one(
                {"_id": SYSTEM_CONFIG_ID},
                {"$set": update, "$setOnInsert": {"createdAt": now}},
                upsert=True,
            )
    except Exception:
        return False

    # invalidate cache
    global _cached_value, _cached_at_monotonic
    _cached_value = None
    _cached_at_monotonic = 0.0
    return True

