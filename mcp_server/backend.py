"""Data-access layer for the MCP tools.

Tools/handlers depend on a duck-typed "backend" (any object exposing the read
methods below), so they can be unit-tested with a fake. ``ProductionBackend``
wraps the real in-process database layer (``database.db`` +
``CollectionsManager``) and is imported lazily so this module stays light.

All read paths are ``user_id``-scoped. The one method that touches a
non-user-scoped DB call (``get_file_by_id``) re-checks ownership here.

Per the project's "Smart Projection" rule, list/search results never carry the
heavy ``code``/``content`` fields — full content is returned only by
``get_file`` for an explicit single-file fetch.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

_HEAVY_FIELDS = ("code", "content", "raw_data", "raw_content")


def _json_safe(value: Any) -> Any:
    """Recursively convert Mongo/BSON types to JSON-friendly values."""
    if isinstance(value, (_dt.datetime, _dt.date)):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    if type(value).__name__ == "ObjectId":  # avoid importing bson
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _clean(doc: dict[str, Any], *, include_code: bool = False) -> dict[str, Any]:
    """Serialize a file document. Drops heavy fields unless ``include_code``."""
    out: dict[str, Any] = {}
    for key, val in (doc or {}).items():
        if key == "_id":
            out["id"] = str(val)
            continue
        if not include_code and key in _HEAVY_FIELDS:
            continue
        out[key] = _json_safe(val)
    # Friendlier alias without dropping the original field.
    if "programming_language" in out:
        out.setdefault("language", out["programming_language"])
    return out


def _full(doc: dict[str, Any]) -> dict[str, Any]:
    """Serialize a single file WITH content (regular ``code`` or large ``content``)."""
    out = _clean(doc, include_code=True)
    if not out.get("code") and out.get("content"):
        out["code"] = out["content"]
    return out


def _strip_heavy(value: Any) -> Any:
    """Recursively drop heavy content fields from an already-serialized value."""
    if isinstance(value, dict):
        return {k: _strip_heavy(v) for k, v in value.items() if k not in _HEAVY_FIELDS}
    if isinstance(value, list):
        return [_strip_heavy(v) for v in value]
    return value


class ProductionBackend:
    """Backend backed by the real in-process ``database`` layer.

    Heavy imports (``database``) happen lazily on first use so importing this
    module never drags in the whole application.
    """

    def __init__(
        self, db_manager: Any = None, mongo_db: Any = None, collections_manager: Any = None
    ) -> None:
        self._dbm = db_manager
        self._mongo = mongo_db
        self._cm = collections_manager

    # -- lazy wiring -------------------------------------------------------
    def _require_dbm(self) -> Any:
        if self._dbm is None:
            from database import db as _db  # lazy heavy import

            self._dbm = _db
        return self._dbm

    def _collections(self) -> Any:
        if self._cm is None:
            from database.collections_manager import CollectionsManager  # lazy

            mongo = (
                self._mongo if self._mongo is not None else getattr(self._require_dbm(), "db", None)
            )
            if mongo is None:
                raise RuntimeError("MongoDB handle unavailable for collections")
            self._cm = CollectionsManager(mongo)
        return self._cm

    # -- files -------------------------------------------------------------
    def list_files(self, user_id: int, *, page: int = 1, per_page: int = 50) -> dict[str, Any]:
        files, total = self._require_dbm().get_regular_files_paginated(user_id, page, per_page)
        return {
            "files": [_clean(f) for f in (files or [])],
            "total": int(total or 0),
            "page": page,
            "per_page": per_page,
        }

    def search_code(
        self, user_id: int, *, query: str, language: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        rows = self._require_dbm().search_code(
            user_id, query, programming_language=language, limit=limit
        )
        return [_clean(r) for r in (rows or [])]

    def get_file(
        self,
        user_id: int,
        *,
        file_name: str | None = None,
        file_id: str | None = None,
        version: int | None = None,
    ) -> dict[str, Any] | None:
        dbm = self._require_dbm()
        if file_id:
            doc = dbm.get_file_by_id(file_id)
            # get_file_by_id is NOT user-scoped -> enforce ownership explicitly.
            if not doc or int(doc.get("user_id", -1)) != int(user_id):
                return None
        elif file_name and version is not None:
            doc = dbm.get_version(user_id, file_name, int(version))
        elif file_name:
            doc = dbm.get_latest_version(user_id, file_name)
        else:
            return None
        return _full(doc) if doc else None

    def list_versions(self, user_id: int, *, file_name: str) -> list[dict[str, Any]]:
        return [_clean(v) for v in (self._require_dbm().get_all_versions(user_id, file_name) or [])]

    # -- collections -------------------------------------------------------
    def list_collections(self, user_id: int, *, limit: int = 100) -> dict[str, Any]:
        return self._collections().list_collections(user_id, limit=limit)

    def get_collection(self, user_id: int, *, collection_id: str) -> dict[str, Any]:
        return self._collections().get_collection(user_id, collection_id)

    def get_collection_items(
        self,
        user_id: int,
        *,
        collection_id: str,
        page: int = 1,
        per_page: int = 50,
        folder: str | None = None,
    ) -> dict[str, Any]:
        result = self._collections().get_collection_items(
            user_id, collection_id, page=page, per_page=per_page, folder_filter=folder
        )
        # Defense-in-depth: collection items are file *references* (no code today),
        # but never let a heavy content field slip through if the manager changes.
        if isinstance(result, dict) and isinstance(result.get("items"), list):
            result["items"] = [_strip_heavy(item) for item in result["items"]]
        return result
