#!/usr/bin/env python3
"""מה שני שלבי ה-``$lookup`` בצינור הסל עולים — ומה בדיוק מייקר אותם.

``file_deletion.recycle_bin_rows_pipeline`` מצרף לכל שורה בסל שני שלבי
``$lookup`` שבודקים אם לשם הזה יש גרסה **פעילה**. הסקריפט מודד את אותו
צינור בשלוש צורות של אותו תנאי:

- **``expr_all + $$src``** — כל התנאים בתוך ``$expr`` אחד, **ועוד** השוואה
  בין מסמן הקולקציה של השורה (``$$src``) לשם הקולקציה. זו הצורה הראשונה
  שנכתבה.
- **``expr_all, no $$src``** — אותם שלושה תנאים בתוך ``$expr``, בלי איבר
  ה-``$$src``.
- **``plain_eq (בקוד)``** — ``user_id`` ו-``is_active`` כשוויונות רגילים,
  ורק השם דרך ``$expr``. זו הצורה שבקוד.

**מה שמייקר הוא איבר ה-``$$src``, לא ה-``$expr``.** לפי התיעוד של
``$lookup``, ``$eq`` בתוך ``$expr`` **כן** משתמש באינדקס של אוסף ה-``from``
כשה-``let`` נפתר לקבוע (https://www.mongodb.com/docs/manual/reference/operator/aggregation/lookup/),
והמדידה כאן מראה את זה: שתי הצורות בלי ``$$src`` זהות. ``$$src`` הוא
השוואה בין שני קבועים, בלי שדה. בשורות שבהן הוא שקר — שורה של האוסף
האחר — כל ה-``$and`` שקר, ומונגו סורק את האוסף כולו לשורה הזו
(``collectionScans``). בשורות שבהן הוא אמת, האינדקס משמש כרגיל.

**מה קוראים בפלט:** ``totalKeysExamined`` הוא המדד המכריע — כשהשם בגבולות
האינדקס הוא שווה למספר ההתאמות, ובלי זה הוא היה כמספר המסמכים הפעילים של
המשתמש לכל שורה. ``collectionScans`` מראה סריקות שלמות שה-``indexesUsed``
מסתיר: האינדקס מופיע שם ברגע שהוא שימש **לחלק** מהשורות. לכן הזרע כולל
שמות בסל **שיש להם** גרסה פעילה — בלי התאמות, "אפס מסמכים" אינו מבדיל בין
"האינדקס תחם" ל"לא היה מה למצוא".

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
LIVE_LARGE_FILES = 50
#: כמה מהשמות שבסל **יש להם** גרסה פעילה באותו אוסף — רוויזיות של קובץ חי.
#: אלה השורות שה-``$lookup`` מוצא, ובלעדיהן המדידה לא מבדילה בין אינדקס
#: שתוחם את השם לבין כזה שלא.
MATCHED_TRASHED_FILES = 30
MATCHED_LARGE_FILES = 10
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
    # גרסאות פעילות בשמות אחרים — מה שסריקה בלי השם בגבולות הייתה קוראת.
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
    for index in range(MATCHED_TRASHED_FILES):
        snippets.append({
            "_id": ObjectId(),
            "user_id": USER_ID,
            "file_name": f"trashed{index}.py",
            "code": "x" * 2000,
            "programming_language": "python",
            "version": TRASHED_VERSIONS + 1,
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
    for index in range(LIVE_LARGE_FILES):
        larges.append({"_id": ObjectId(), "user_id": USER_ID,
                       "file_name": f"livebig{index}.md", "content": "z" * 5000,
                       "is_active": True})
    for index in range(MATCHED_LARGE_FILES):
        larges.append({"_id": ObjectId(), "user_id": USER_ID,
                       "file_name": f"big{index}.md", "content": "z" * 5000,
                       "is_active": True})
    db.large_files.insert_many(larges)


def _expr_all_lookups(user_id: int, *, with_src: bool) -> List[dict]:
    """הצורות שנמדדות כנגד: כל התנאים בתוך ``$expr`` — עם איבר ``$$src`` ובלעדיו."""
    from file_deletion import RECYCLE_BIN_COLLECTIONS

    lookups = []
    for name in RECYCLE_BIN_COLLECTIONS:
        conditions = [
            {"$eq": ["$user_id", user_id]},
            {"$eq": ["$file_name", "$$n"]},
            {"$eq": ["$is_active", True]},
        ]
        let = {"n": "$_id.name"}
        if with_src:
            conditions.append({"$eq": ["$$src", name]})
            let["src"] = "$_id.src"
        lookups.append({
            "$lookup": {
                "from": name,
                "let": let,
                "pipeline": [
                    {"$match": {"$expr": {"$and": conditions}}},
                    {"$limit": 1},
                    {"$project": {"_id": 1}},
                ],
                "as": "_alive_" + name,
            }
        })
    return lookups


def _lookup_stats(plan: dict) -> List[Dict[str, Any]]:
    out = []
    for stage in plan.get("stages", []):
        if "$lookup" in stage:
            out.append({
                "as": stage["$lookup"].get("as"),
                "keys_examined": stage.get("totalKeysExamined"),
                "docs_examined": stage.get("totalDocsExamined"),
                "collection_scans": stage.get("collectionScans"),
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
            "expr_all + $$src": shared + _expr_all_lookups(USER_ID, with_src=True),
            "expr_all, no $$src": shared + _expr_all_lookups(USER_ID, with_src=False),
            "plain_eq (בקוד)": recycle_bin_rows_pipeline(USER_ID) + tail,
        }
        print(f"שרת: mongod {client.admin.command('buildInfo').get('version')}")

        for label, pipeline in variants.items():
            plan = db.command({
                "explain": {"aggregate": "code_snippets", "cursor": {},
                            "pipeline": pipeline},
                "verbosity": "executionStats",
            })
            blob = json.dumps(plan, default=str)
            print(f"\n== {label}")
            for row in _lookup_stats(plan):
                print(f"   {row['as']}: totalKeysExamined={row['keys_examined']} "
                      f"totalDocsExamined={row['docs_examined']} "
                      f"collectionScans={row['collection_scans']} "
                      f"indexesUsed={row['indexes']}")
            print(f"   COLLSCAN: {'COLLSCAN' in blob}")
            used_disk = set(re.findall(r'"usedDisk":\s*(\w+)', blob))
            print(f"   usedDisk: {used_disk}")

        rows = list(db.code_snippets.aggregate(recycle_bin_rows_pipeline(USER_ID)))
        print(f"\nשורות בסל: {len(rows)} — {TRASHED_FILES + LARGE_FILES} קבצים, פחות "
              f"{MATCHED_TRASHED_FILES + MATCHED_LARGE_FILES} שיש להם גרסה פעילה ולכן מוסתרים")
        print(f"התאמות שה-$lookup אמור למצוא: code_snippets={MATCHED_TRASHED_FILES} "
              f"large_files={MATCHED_LARGE_FILES}")
        print(f"מסמכים: code_snippets={db.code_snippets.count_documents({})} "
              f"large_files={db.large_files.count_documents({})}")
        return 0
    finally:
        client.drop_database(DB_NAME)
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
