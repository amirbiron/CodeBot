"""
DB Manager Sanity Check (Singleton + latency)
=============================================

מטרות:
- לוודא ש-DatabaseManager לא נוצר מחדש "בטעות" (למשל בכל request).
- למדוד זמן גישה ישירה ל-DB לעומת קריאה דרך DatabaseManager.

הרצה (בשרת/Render Console):
    python3 scripts/db_manager_sanity_check.py

הערות:
- הסקריפט משתמש ב-PyMongo (סינכרוני), בהתאם למימוש DatabaseManager.
- הוא לא מדפיס מחרוזת חיבור (MONGODB_URL) כדי לא להדליף מידע רגיש ללוגים.
"""

from __future__ import annotations

import os
import time
from typing import Any


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)) or default)
    except Exception:
        return int(default)


def _measure(label: str, fn) -> float:
    t0 = time.perf_counter()
    fn()
    dt = max(0.0, float(time.perf_counter() - t0))
    print(f"{label}: {dt:.4f}s")
    return dt


def main() -> None:
    # Importing database module initializes the global DatabaseManager (one per process).
    from database import db_manager
    from database.manager import DatabaseManager

    user_id: Any = _env_int("SANITY_USER_ID", 123)

    print("=== DatabaseManager Sanity Check ===")
    print(f"- instances_created: {DatabaseManager.instances_created()}")
    print(f"- manager_id: {id(db_manager)}")
    print(f"- client_id: {id(getattr(db_manager, 'client', None))}")
    print(f"- db_name: {getattr(getattr(db_manager, 'db', None), 'name', None)}")
    print(f"- profiling_enabled_by_code: {bool(getattr(db_manager, 'ENABLE_PROFILING', True))}")

    db = getattr(db_manager, "db", None)
    if db is None or getattr(db, "name", "") == "noop_db":
        print("DB is not available (noop_db). Skipping latency checks.")
        return

    def _direct_find_one() -> None:
        # Projection קטן כדי לא למשוך שדות כבדים.
        _ = db.users.find_one({"user_id": int(user_id)}, {"_id": 1})

    def _via_manager() -> None:
        _ = db_manager.get_user(user_id)

    print("\n=== Latency ===")
    _measure("Direct Time (db.users.find_one)", _direct_find_one)
    _measure("Manager Time (db_manager.get_user)", _via_manager)

    # Optional: detect accidental extra instantiation in same process (best-effort)
    print("\n=== Instance Counter (post) ===")
    print(f"- instances_created: {DatabaseManager.instances_created()}")


if __name__ == "__main__":
    main()

