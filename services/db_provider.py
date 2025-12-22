"""
DB Provider (standalone, lazy) - כדי להימנע מ-import מעגלי
===========================================================

למה קיים?
- יש מקומות (למשל מנוע כללים/התראות פנימיות) שיכולים לרוץ בזמן ש-`webapp/app.py`
  עדיין באמצע import. במקרה כזה `from webapp.app import get_db` עלול להיכשל עם:
  "cannot import name 'get_db' from partially initialized module".

הפתרון:
- ספק get_db() עצמאי שמסתמך רק על ENV (כמו modules אחרים ב-repo),
  עם Lazy init וחיבור best-effort.

הערה:
- אנחנו מחזירים No-Op DB במקרה שאין pymongo / אין MONGODB_URL / DISABLE_DB.
  זה מאפשר fail-open: מנוע הכללים פשוט "לא ימצא כללים" במקום להפיל תהליך.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import timezone
from types import SimpleNamespace
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    from pymongo import MongoClient  # type: ignore

    _PYMONGO_AVAILABLE = True
except Exception:  # pragma: no cover
    MongoClient = None  # type: ignore[assignment]
    _PYMONGO_AVAILABLE = False


class _NoOpCollection:
    """מימוש מינימלי של Collection כדי לא לשבור קוד שקורא ל-storage."""

    class _NoOpCursor:
        """Cursor ריק שתומך ב-method chaining כמו PyMongo."""

        def skip(self, *_a: Any, **_k: Any) -> "_NoOpCollection._NoOpCursor":
            return self

        def limit(self, *_a: Any, **_k: Any) -> "_NoOpCollection._NoOpCursor":
            return self

        def sort(self, *_a: Any, **_k: Any) -> "_NoOpCollection._NoOpCursor":
            return self

        def __iter__(self):
            return iter(())

    def find_one(self, *_a: Any, **_k: Any) -> Any:
        return None

    def find(self, *_a: Any, **_k: Any) -> Any:
        return self._NoOpCursor()

    def update_one(self, *_a: Any, **_k: Any) -> Any:
        return SimpleNamespace(acknowledged=True, matched_count=0, modified_count=0, upserted_id=None)

    def delete_one(self, *_a: Any, **_k: Any) -> Any:
        return SimpleNamespace(deleted_count=0)

    def create_index(self, *_a: Any, **_k: Any) -> Any:
        return None

    def count_documents(self, *_a: Any, **_k: Any) -> int:
        return 0


class _NoOpDB:
    """DB דמוי-PyMongo: מאפשר db.collection וגם db['collection']."""

    def __getitem__(self, _name: str) -> _NoOpCollection:
        return _NoOpCollection()

    def __getattr__(self, name: str) -> _NoOpCollection:
        if name.startswith("_"):
            raise AttributeError(name)
        return self.__getitem__(name)

    @property
    def name(self) -> str:  # pragma: no cover
        return "noop_db"


_CLIENT: Optional[Any] = None
_DB: Optional[Any] = None
_LOCK = threading.Lock()


def get_db() -> Any:
    """מחזיר אובייקט DB (PyMongo) עם lazy init, או No-Op DB."""
    global _CLIENT, _DB

    if _DB is not None:
        return _DB

    with _LOCK:
        if _DB is not None:
            return _DB

        # Fail-open modes
        disable_db = str(os.getenv("DISABLE_DB", "")).lower() in {"1", "true", "yes"}
        mongo_url = (os.getenv("MONGODB_URL") or "").strip()
        db_name = (os.getenv("DATABASE_NAME") or "code_keeper_bot").strip() or "code_keeper_bot"

        if disable_db or (not mongo_url) or (not _PYMONGO_AVAILABLE):
            _DB = _NoOpDB()
            return _DB

        try:
            # Minimal, safe defaults: no reliance on webapp/app.py globals.
            _CLIENT = MongoClient(  # type: ignore[misc]
                mongo_url,
                serverSelectionTimeoutMS=5000,
                tz_aware=True,
                tzinfo=timezone.utc,
            )
            # Best-effort ping
            try:
                _CLIENT.admin.command("ping")
            except Exception:
                pass
            _DB = _CLIENT[db_name]
            return _DB
        except Exception as e:
            try:
                logger.warning("services.db_provider: failed to init MongoDB, using noop DB: %s", e)
            except Exception:
                pass
            _DB = _NoOpDB()
            return _DB

