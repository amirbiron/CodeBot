#!/usr/bin/env python3
"""כמה מסמכים צינור שורות הסל נוגע בהם — ולמה ``$expr`` גורף עולה ביוקר.

``file_deletion.recycle_bin_rows_pipeline`` מצרף לכל שורה בסל שני שלבי
``$lookup`` שבודקים אם לשם הזה יש גרסה **פעילה**. הסקריפט הזה מודד את
אותו צינור בשתי צורות של אותו תנאי:

- **``expr_all``** — כל התנאים בתוך ``$expr`` אחד, כולל ``user_id``
  ו-``is_active``. זו הצורה הראשונה שנכתבה, והיא גם הצורה שמתבקשת
  כשצריך גם להשוות את מסמן הקולקציה (``$$src``).
- **``plain_eq``** — ``user_id`` ו-``is_active`` כשוויונות רגילים, ורק
  השם דרך ``$expr``. זו הצורה שבקוד.

ההבדל אינו סגנוני: ב-``expr_all`` אין תנאי שיכול לבחור את תחילית
האינדקס, ולכן מונגו סורק את כל המסמכים הפעילים של המשתמש **לכל שורה
בסל**. המספרים שה-docstring בקוד מצטט נמדדו בדיוק כאן.

הרצה::

    python scripts/measure_recycle_bin_pipeline.py                      # mongodb://127.0.0.1:27017
    python scripts/measure_recycle_bin_pipeline.py mongodb://host:27017

הכתובת היא **ארגומנט** ולא משתנה סביבה, כדי שלא ייווסף למערכת משתנה
תצורה שאף שירות אינו קורא.

הסקריפט כותב **רק** למסד שהוא יוצר לעצמו (``ckmeasure_recycle_bin``),
מוחק אותו בהתחלה ובסוף, ואינו נוגע בשום קולקציה אחרת. זה דורש עבודה, כי
``database.manager`` נטען דרך ``database/__init__.py``, שבונה בזמן הייבוא
``DatabaseManager()`` גלובלי — והוא מתחבר ויוצר את כל האינדקסים במסד של
ברירת המחדל, בשרת שבכתובת. ראו :func:`_isolate_from_bot_config`.

הכתובת עצמה אינה מודפסת ואינה נכנסת לסביבה: היא יכולה לשאת סיסמה.
``deleted_expires_at``
מוזרע **בעתיד** בכוונה: אינדקס ה-TTL של הסל מוחק מסמכים שעבר זמנם, והזרעה
עם תאריך שחלף רוקנה את מסד המדידה באמצע הריצה הראשונה.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_URI = "mongodb://127.0.0.1:27017"


def _uri() -> str:
    """הכתובת שנמדדת: הארגומנט הראשון, או מונגו מקומי."""
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    return args[0] if args else DEFAULT_URI


def _isolate_from_bot_config() -> None:
    """מה שחייב לקרות **לפני** ``from database.manager import ...``.

    אותה צורה של ``tests/conftest.py``, ומאותן סיבות:

    - ``DISABLE_DB`` — **השמה ולא** ``setdefault``: המופע הגלובלי שבונה
      ``database/__init__.py`` לא מתחבר (``DatabaseManager.connect``), ולכן
      לא יוצר אינדקסים במסד של ברירת המחדל בשרת הנמדד. האינדקסים שהמדידה
      צריכה נוצרים במפורש, על מסד המדידה בלבד.
    - ``BOT_TOKEN`` ו-``MONGODB_URL`` — ``config`` דורש את שניהם בטעינה, ובלי
      ``.env`` בתיקייה הייבוא קורס. ערכי דמה, ב-``setdefault``: אף אחד מהם
      לא משמש כאן. **הכתובת הנמדדת לא נכנסת לשם בכוונה** — כשל אימות של
      ``config`` מדפיס את ערכי השדות, וכתובת יכולה לשאת סיסמה.
    """
    os.environ["DISABLE_DB"] = "1"
    os.environ.setdefault("BOT_TOKEN", "measure-recycle-bin-pipeline")
    os.environ.setdefault("MONGODB_URL", DEFAULT_URI)


DB_NAME = "ckmeasure_recycle_bin"
USER_ID = 5
TRASHED_FILES = 60
TRASHED_VERSIONS = 3
LIVE_FILES = 100
LIVE_VERSIONS = 4
LARGE_FILES = 20
LARGE_COPIES = 2
#: עתידי בכוונה — ראו ה-docstring של המודול.
STAMP = datetime(2027, 2, 1, tzinfo=timezone.utc)


def _seed(db) -> None:
    from bson import ObjectId

    snippets: List[Dict[str, Any]] = []
    for index in range(TRASHED_FILES):
        for version in range(1, TRASHED_VERSIONS + 1):
            snippets.append({
                "_id": ObjectId(),
                "user_id": USER_ID,
                "file_name": f"trashed{index}.py",
                "code": "x" * 2000,
                "programming_language": "python",
                "version": version,
                "is_active": False,
                "deleted_at": STAMP + timedelta(minutes=index),
                "deleted_expires_at": STAMP + timedelta(days=30),
            })
    # הגרסאות הפעילות הן מה שה-``$lookup`` סורק כשאין לו אינדקס לבחור.
    for index in range(LIVE_FILES):
        for version in range(1, LIVE_VERSIONS + 1):
            snippets.append({
                "_id": ObjectId(),
                "user_id": USER_ID,
                "file_name": f"live{index}.py",
                "code": "x" * 2000,
                "programming_language": "python",
                "version": version,
                "is_active": True,
            })
    db.code_snippets.insert_many(snippets)

    larges: List[Dict[str, Any]] = []
    for index in range(LARGE_FILES):
        for copy in range(LARGE_COPIES):
            larges.append({
                "_id": ObjectId(),
                "user_id": USER_ID,
                "file_name": f"big{index}.md",
                "content": "z" * 5000,
                "is_active": False,
                "deleted_at": STAMP + timedelta(minutes=copy),
                "deleted_expires_at": STAMP + timedelta(days=30),
            })
    db.large_files.insert_many(larges)


def _expr_all_lookups(user_id: int) -> List[dict]:
    """הצורה שנמדדת כנגד: כל התנאים בתוך ``$expr``, כולל ``$$src``."""
    from file_deletion import RECYCLE_BIN_COLLECTIONS

    return [
        {
            "$lookup": {
                "from": name,
                "let": {"n": "$_id.name", "src": "$_id.src"},
                "pipeline": [
                    {"$match": {"$expr": {"$and": [
                        {"$eq": ["$user_id", user_id]},
                        {"$eq": ["$file_name", "$$n"]},
                        {"$eq": ["$is_active", True]},
                        {"$eq": ["$$src", name]},
                    ]}}},
                    {"$limit": 1},
                    {"$project": {"_id": 1}},
                ],
                "as": "_alive_" + name,
            }
        }
        for name in RECYCLE_BIN_COLLECTIONS
    ]


def _lookup_stats(plan: dict) -> List[Dict[str, Any]]:
    out = []
    for stage in plan.get("stages", []):
        if "$lookup" in stage:
            out.append({
                "as": stage["$lookup"].get("as"),
                "docs_examined": stage.get("totalDocsExamined"),
                "indexes": stage.get("indexesUsed"),
            })
    return out


def main() -> int:
    try:
        from pymongo import MongoClient
    except ImportError:
        print("pymongo אינו מותקן")
        return 2

    _isolate_from_bot_config()
    from database.manager import DatabaseManager
    from file_deletion import (
        recycle_bin_group_stages,
        recycle_bin_page_stages,
        recycle_bin_rows_pipeline,
        RECYCLE_BIN_COLLECTIONS,
    )

    uri = _uri()
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
    except Exception as exc:
        # סוג החריגה בלבד: הכתובת וגוף ההודעה יכולים לשאת סיסמה.
        print(f"אין חיבור למונגו בכתובת שנמסרה ({type(exc).__name__})")
        return 2

    client.drop_database(DB_NAME)
    db = client[DB_NAME]
    try:
        # האינדקסים של הפרודקשן, מקוד הייצור ולא מהעתק של ההגדרה.
        manager = DatabaseManager.__new__(DatabaseManager)
        manager.db = db
        manager.client = None
        DatabaseManager._create_indexes(manager)
        _seed(db)

        tail = recycle_bin_page_stages(page=1, per_page=20)
        shared = [
            *recycle_bin_group_stages(USER_ID, source=RECYCLE_BIN_COLLECTIONS[0]),
            {"$unionWith": {
                "coll": RECYCLE_BIN_COLLECTIONS[1],
                "pipeline": recycle_bin_group_stages(
                    USER_ID, source=RECYCLE_BIN_COLLECTIONS[1]),
            }},
        ]
        variants = {
            "expr_all": shared + _expr_all_lookups(USER_ID),
            "plain_eq (בקוד)": recycle_bin_rows_pipeline(USER_ID) + tail,
        }

        for label, pipeline in variants.items():
            plan = db.command({
                "explain": {"aggregate": "code_snippets", "cursor": {},
                            "pipeline": pipeline},
                "verbosity": "executionStats",
            })
            blob = json.dumps(plan, default=str)
            print(f"\n== {label}")
            for row in _lookup_stats(plan):
                print(f"   {row['as']}: totalDocsExamined={row['docs_examined']} "
                      f"indexesUsed={row['indexes']}")
            print(f"   COLLSCAN: {'COLLSCAN' in blob}")
            used_disk = set(re.findall(r'"usedDisk":\s*(\w+)', blob))
            print(f"   usedDisk: {used_disk}")

        rows = list(db.code_snippets.aggregate(
            recycle_bin_rows_pipeline(USER_ID) + tail))
        print(f"\nשורות בעמוד הראשון: {len(rows)} "
              f"(מתוך {TRASHED_FILES + LARGE_FILES} קבצים בסל)")
        print(f"מסמכים: code_snippets={db.code_snippets.count_documents({})} "
              f"large_files={db.large_files.count_documents({})}")
        return 0
    finally:
        client.drop_database(DB_NAME)
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
