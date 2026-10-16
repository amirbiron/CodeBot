"""עזרים משותפים לטסטים של שרשורי התגובות מול מונגו אמיתי.

פונקציות ולא fixtures (T3): fixture מיובא נרשם מחדש במודול שמייבא אותו. כל קובץ טסט
מגדיר fixture דק מעל :func:`temp_database`.

**מדלגים רק על "אין שרת"** (``testing.md`` §7): :func:`mongo_reachable` מחזיר ``False``
רק על ``ServerSelectionTimeoutError`` / ``ConnectionFailure``; כל חריגה אחרת — כתובת
שגויה, אימות — עולה ומפילה, כי היא תקלת תצורה ולא היעדר שירות.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

MONGO_URL = os.environ.get("MONGODB_URL", "").strip()
_EPOCH = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


def mongo_reachable(url: str = MONGO_URL) -> bool:
    if not url:
        return False
    import pymongo
    from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

    client = pymongo.MongoClient(url, serverSelectionTimeoutMS=2000)
    try:
        client.admin.command("ping")
        return True
    except (ServerSelectionTimeoutError, ConnectionFailure):
        return False
    finally:
        client.close()


@contextlib.contextmanager
def temp_database(prefix: str) -> Iterator[Any]:
    """מסד חד-פעמי בשם ``<prefix><hex>``, ``tz_aware=True`` כמו בייצור — ונמחק בסוף, רק אם
    השם מתחיל בתחילית (סורג בטיחות: מסד שלא נוצר כאן לא נמחק כאן)."""
    import pymongo

    name = f"{prefix}{uuid.uuid4().hex[:12]}"
    client = pymongo.MongoClient(MONGO_URL, tz_aware=True, tzinfo=timezone.utc)
    try:
        yield client[name]
    finally:
        assert name.startswith(prefix), f"סירוב למחוק מסד שאינו של הבדיקות: {name}"
        try:
            client.drop_database(name)
        finally:
            client.close()


def insert_board(db: Any, user_id: int, name: str = "CodeBot") -> str:
    from bson import ObjectId

    oid = ObjectId()
    db.note_boards.insert_one({"_id": oid, "user_id": user_id, "name": name, "is_default": False,
                               "order": 0})
    return str(oid)


def insert_note(db: Any, user_id: int, *, content: str = "גוף הפתק", title: str | None = None,
                minutes: int = 0, **target: Any) -> str:
    """פתק בצורת הוובאפ על יעד אחד (``board_id`` / ``file_id`` / ``repo_name``+``repo_path``)."""
    from bson import ObjectId

    oid = ObjectId()
    when = _EPOCH + timedelta(minutes=minutes)
    doc = {"_id": oid, "user_id": user_id, "content": content, "color": "yellow",
           "created_at": when, "updated_at": when, **target}
    if title is not None:
        doc["title"] = title
    db.sticky_notes.insert_one(doc)
    return str(oid)


def insert_file(db: Any, user_id: int, file_name: str) -> str:
    """גרסה פעילה של קובץ — מה ש-``recent_files`` ו-``_backfill_file_names`` קוראים."""
    from bson import ObjectId

    oid = ObjectId()
    db.code_snippets.insert_one({"_id": oid, "user_id": user_id, "file_name": file_name,
                                 "code": "x", "is_active": True, "created_at": _EPOCH})
    return str(oid)
