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
import html
import logging
from typing import Any

logger = logging.getLogger(__name__)

_HEAVY_FIELDS = ("code", "content", "raw_data", "raw_content")

# שדות הפתק שנחשפים ל-MCP — רזה במכוון (בלי מיקום/גודל פיקסלים, שהם עניין ויזואלי)
_NOTE_FIELDS = ("content", "color", "line_start", "anchor_text", "is_minimized")


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


def _as_note(doc: dict[str, Any]) -> dict[str, Any]:
    """Serialize a sticky-note document for MCP output (lean, JSON-safe)."""
    doc = doc or {}
    out: dict[str, Any] = {"id": str(doc.get("_id") or "")}
    for key in _NOTE_FIELDS:
        out[key] = _json_safe(doc.get(key))
    # פתקי legacy נשמרו עם HTML entities — משחזרים טקסט כמו שהוובאפ עושה בקריאה
    if isinstance(out.get("content"), str):
        out["content"] = html.unescape(out["content"])
    out["created_at"] = _json_safe(doc.get("created_at"))
    out["updated_at"] = _json_safe(doc.get("updated_at"))
    return out


def _notes_scope_filter(
    user_id: int, scope_id: str | None, related_ids: list[str]
) -> dict[str, Any]:
    """The webapp-parity notes query: by scope_id, plus file_id for legacy notes.

    Module-level and pure so tests can assert the exact query shape.
    """
    clauses: list[dict[str, Any]] = []
    if scope_id:
        clauses.append({"scope_id": scope_id})
    if related_ids:
        clauses.append({"file_id": {"$in": list(related_ids)}})
    if not clauses:
        return {"user_id": int(user_id)}
    return {"user_id": int(user_id), "$or": clauses}


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
        self._notes_idx_done = False

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

    # -- write (save) ------------------------------------------------------
    def save_file(
        self,
        user_id: int,
        *,
        file_name: str,
        code: str,
        programming_language: str,
        description: str = "",
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new file or append a new version of an existing one.

        Reuses the same write path the bot/webapp use (``save_code_snippet`` →
        append-only versioning, auto-computed ``file_size``/``lines_count``), so
        an update never overwrites: prior versions remain visible via
        ``list_versions``. Returns metadata only — the heavy ``code`` is never
        echoed back (Smart Projection).
        """
        from database.models import CodeSnippet  # lazy heavy import (see _require_dbm)

        dbm = self._require_dbm()
        # Captured before the save so we can report create vs. update honestly.
        prev = dbm.get_latest_version(user_id, file_name)
        ok = bool(
            dbm.save_code_snippet(
                CodeSnippet(
                    user_id=int(user_id),
                    file_name=file_name,
                    code=code,
                    programming_language=programming_language,
                    description=description or "",
                    tags=list(tags or []),
                )
            )
        )
        if not ok:
            return {"ok": False, "error": "save_failed"}
        # Re-fetch so the returned version/size are the authoritative DB values.
        saved = dbm.get_latest_version(user_id, file_name) or {}
        return {"ok": True, "created": prev is None, "file": _clean(saved)}

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

    # -- sticky notes ------------------------------------------------------
    def _raw_mongo(self) -> Any:
        mongo = self._mongo if self._mongo is not None else getattr(self._require_dbm(), "db", None)
        if mongo is None:
            raise RuntimeError("MongoDB handle unavailable for sticky notes")
        return mongo

    def _notes_coll(self) -> Any:
        coll = self._raw_mongo()["sticky_notes"]
        # אינדקס שחסר היום לשאילתת ה-scope (משרת גם את הוובאפ); חד-פעמי, לא מפיל כלי
        if not self._notes_idx_done:
            self._notes_idx_done = True
            try:
                coll.create_index([("user_id", 1), ("scope_id", 1)], name="user_scope_idx")
            except Exception:
                logger.warning("sticky notes index creation failed (non-fatal)", exc_info=True)
        return coll

    def _related_file_ids(self, user_id: int, file_name: str) -> list[str]:
        """כל מזהי הגרסאות של השם הזה — לפריטת שאילתת הוובאפ (פתקי legacy בלי scope_id)."""
        try:
            rows = self._raw_mongo()["code_snippets"].find(
                {"user_id": int(user_id), "file_name": file_name}, {"_id": 1}
            )
            return [str(r["_id"]) for r in rows if r and r.get("_id") is not None]
        except Exception:
            logger.warning("related file ids lookup failed", exc_info=True)
            return []

    def list_notes(self, user_id: int, *, file_name: str) -> dict[str, Any]:
        """List notes for a file (pure read — no backfill, unlike the webapp GET)."""
        from sticky_notes_scope import make_scope_id  # מודול טהור בשורש הריפו

        scope_id = make_scope_id(int(user_id), file_name)
        related = self._related_file_ids(user_id, file_name)
        query = _notes_scope_filter(user_id, scope_id, related)
        rows = list(self._notes_coll().find(query).sort("created_at", 1).limit(500))
        return {
            "ok": True,
            "file_name": file_name,
            "count": len(rows),
            "notes": [_as_note(r) for r in rows],
        }

    def create_note(
        self,
        user_id: int,
        *,
        file_name: str,
        content: str,
        line: int | None,
        color: str,
        anchor_text: str | None,
        anchor_id: str | None,
    ) -> dict[str, Any]:
        """Insert a webapp-schema note attached to an existing file."""
        from .handlers import MAX_NOTES_PER_SCOPE
        from sticky_notes_scope import make_scope_id

        doc = self._require_dbm().get_latest_version(int(user_id), file_name)
        if not doc:
            return {
                "ok": False,
                "error": "file_not_found",
                "hint": "save the file first with codekeeper_save_file",
            }
        canonical_name = str(doc.get("file_name") or file_name)
        scope_id = make_scope_id(int(user_id), canonical_name)
        related = self._related_file_ids(user_id, canonical_name)

        coll = self._notes_coll()
        try:
            existing = int(coll.count_documents(_notes_scope_filter(user_id, scope_id, related)))
        except Exception:
            existing = 0  # המגן הוא soft-cap; כשל ספירה לא חוסם יצירה
        if existing >= MAX_NOTES_PER_SCOPE:
            return {
                "ok": False,
                "error": "too_many_notes",
                "max": MAX_NOTES_PER_SCOPE,
                "count": existing,
            }

        now = _dt.datetime.now(_dt.timezone.utc)
        note = {
            "user_id": int(user_id),
            "file_id": str(doc.get("_id") or ""),
            "content": content,
            # ברירות מחדל בפריטת הקליינט — פתק מה-MCP נראה כמו פתק שנוצר ביד
            "position_x": 120,
            "position_y": 120,
            "width": 260,
            "height": 200,
            "color": color,
            "is_minimized": False,
            "line_start": line,
            "line_end": None,
            "anchor_id": anchor_id,
            "anchor_text": anchor_text,
            "scope_id": scope_id,
            "file_name": canonical_name,
            "created_at": now,
            "updated_at": now,
        }
        res = coll.insert_one(note)
        note["_id"] = getattr(res, "inserted_id", None)
        return {"ok": True, "note": _as_note(note)}

    def update_note(self, user_id: int, *, note_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        """Partial in-place update by ObjectId, ownership enforced in the filter."""
        from bson import ObjectId  # lazy heavy import

        try:
            oid = ObjectId(str(note_id))
        except Exception:
            return {"ok": False, "error": "invalid_note_id"}

        coll = self._notes_coll()
        note = coll.find_one({"_id": oid, "user_id": int(user_id)})
        if not note:
            return {"ok": False, "error": "not_found"}

        updates = dict(fields)
        # backfill לפתק legacy בלי scope_id — רק במסלול הכתיבה (list נשאר קריאה טהורה)
        if not note.get("scope_id"):
            fname = note.get("file_name")
            if not fname and note.get("file_id"):
                try:
                    ref = self._raw_mongo()["code_snippets"].find_one(
                        {"_id": ObjectId(str(note["file_id"])), "user_id": int(user_id)},
                        {"file_name": 1},
                    )
                    fname = (ref or {}).get("file_name")
                except Exception:
                    fname = None
            if fname:
                from sticky_notes_scope import make_scope_id

                sid = make_scope_id(int(user_id), str(fname))
                if sid:
                    updates["scope_id"] = sid
                    updates["file_name"] = str(fname)

        updates["updated_at"] = _dt.datetime.now(_dt.timezone.utc)
        coll.update_one({"_id": oid, "user_id": int(user_id)}, {"$set": updates})
        return {"ok": True, "note": _as_note({**note, **updates})}
