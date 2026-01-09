#!/usr/bin/env python3
"""
מיגרציה: עדכון error_signatures.signature לפורמט hash חדש (sha256 hex באורך 64).

למה צריך?
- בעבר שמרנו signature מקוצר (לרוב 16 hex).
- שינויי אבטחה/סניטיזציה יכולים לגרום לכך שהמערכת תשתמש בחתימה "חדשה" (64 hex),
  ואז דידופליקציה "תשכח" היסטוריה קיימת.

מה הסקריפט עושה?
- מוצא מסמכים ב-collection `error_signatures` שהשדה signature שלהם נראה "ישן" (16 hex).
- מחשב new_signature = sha256(old_signature).hexdigest() (64 hex).
- אם כבר קיים מסמך עם new_signature:
  - מבצע merge:
    - count: סכימה
    - first_seen: מינימום
    - last_seen: מקסימום
  - ומוחק את המסמך הישן.
- אחרת: מעדכן את המסמך הישן in-place לשדה signature החדש.

הרצה:
  python3 scripts/migrate_error_signatures_hash_v2.py --dry-run
  python3 scripts/migrate_error_signatures_hash_v2.py --batch-size 2000

דרישות ENV:
  MONGODB_URL (חובה), DATABASE_NAME (אופציונלי; ברירת מחדל code_keeper_bot)

הערה:
  הסקריפט משתמש ב-services.db_provider.get_db() כדי להשתמש ב-pool הגלובלי.
"""

from __future__ import annotations

import argparse
import hashlib
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple


_OLD_SIG_RE = re.compile(r"^[0-9a-fA-F]{16}$")


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _dt(value: Any) -> Optional[datetime]:
    return value if isinstance(value, datetime) else None


def _chunked(seq: List[Any], size: int) -> Iterable[List[Any]]:
    for i in range(0, len(seq), max(1, int(size))):
        yield seq[i : i + size]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate error_signatures.signature to sha256(64) format")
    parser.add_argument("--dry-run", action="store_true", help="לא מבצע כתיבה, רק מדפיס כמה היה משתנה")
    parser.add_argument("--batch-size", type=int, default=1000, help="גודל באטש ל-bulk_write")
    args = parser.parse_args(argv)

    try:
        from services.db_provider import get_db
    except Exception as e:
        print(f"❌ לא הצלחתי לייבא get_db(): {e}")
        return 2

    db = get_db()
    try:
        if getattr(db, "name", "") == "noop_db":
            print("❌ לא התחברתי ל-MongoDB (קיבלתי noop DB). ודא ש-MONGODB_URL מוגדר וש-DISABLE_DB לא פעיל.")
            return 2
    except Exception:
        pass

    try:
        from pymongo import UpdateOne, DeleteOne  # type: ignore
    except Exception as e:
        print(f"❌ חסרה תלות pymongo: {e}")
        print("   התקן: pip install pymongo")
        return 2

    coll = db["error_signatures"]

    query: Dict[str, Any] = {
        "signature": {"$type": "string", "$regex": r"^[0-9a-fA-F]{16}$"},
    }

    total_scanned = 0
    total_old = 0
    total_renamed = 0
    total_merged = 0
    total_deleted = 0
    total_noop = 0

    # משתמשים ב-projection מינימלי כדי לצמצם payload
    projection = {"signature": 1, "count": 1, "first_seen": 1, "last_seen": 1}

    try:
        cursor = coll.find(query, projection)  # type: ignore[attr-defined]
    except Exception as e:
        print(f"❌ שגיאה בשאילתת find: {e}")
        return 1

    buffer: List[Dict[str, Any]] = []

    def _flush(batch: List[Dict[str, Any]]) -> Tuple[int, int, int, int]:
        nonlocal total_renamed, total_merged, total_deleted, total_noop
        if not batch:
            return (0, 0, 0, 0)

        # 1) חשב new_sigs בבאטש ובדוק קיימים בשאילתה אחת
        old_to_new: Dict[Any, str] = {}
        new_sigs: List[str] = []
        for doc in batch:
            sig = doc.get("signature")
            if not isinstance(sig, str) or not _OLD_SIG_RE.fullmatch(sig):
                continue
            new_sig = _sha256_hex(sig)
            old_to_new[doc.get("_id")] = new_sig
            new_sigs.append(new_sig)

        existing_map: Dict[str, Any] = {}
        try:
            # שים לב: זו שאילתה אחת שמביאה "את כל מה שצריך" לבאטש
            for row in coll.find({"signature": {"$in": list(set(new_sigs))}}, {"_id": 1, "signature": 1}):  # type: ignore[attr-defined]
                if isinstance(row, dict) and isinstance(row.get("signature"), str):
                    existing_map[row["signature"]] = row.get("_id")
        except Exception:
            existing_map = {}

        ops: List[Any] = []
        renamed = 0
        merged = 0
        deleted = 0
        noop = 0

        for doc in batch:
            total_id = doc.get("_id")
            old_sig = doc.get("signature")
            if not isinstance(old_sig, str) or not _OLD_SIG_RE.fullmatch(old_sig):
                noop += 1
                continue

            new_sig = old_to_new.get(total_id) or _sha256_hex(old_sig)
            if not new_sig:
                noop += 1
                continue

            existing_id = existing_map.get(new_sig)
            if existing_id is not None and existing_id != total_id:
                # merge into existing doc, then delete old doc
                inc_count = max(0, _as_int(doc.get("count"), default=0))
                if inc_count <= 0:
                    inc_count = 1
                update: Dict[str, Any] = {"$inc": {"count": inc_count}}
                fs = _dt(doc.get("first_seen"))
                ls = _dt(doc.get("last_seen"))
                if fs is not None:
                    update.setdefault("$min", {})["first_seen"] = fs
                if ls is not None:
                    update.setdefault("$max", {})["last_seen"] = ls
                ops.append(UpdateOne({"_id": existing_id}, update))
                ops.append(DeleteOne({"_id": total_id}))
                merged += 1
                deleted += 1
                continue

            # rename in-place
            ops.append(UpdateOne({"_id": total_id, "signature": old_sig}, {"$set": {"signature": new_sig}}))
            renamed += 1

        if args.dry_run:
            # לא מבצע כתיבה; מחזיר סטטיסטיקות
            total_renamed += renamed
            total_merged += merged
            total_deleted += deleted
            total_noop += noop
            return (renamed, merged, deleted, noop)

        if ops:
            try:
                coll.bulk_write(ops, ordered=False)  # type: ignore[attr-defined]
            except Exception as e:
                print(f"⚠️ bulk_write נכשל (best-effort): {e}")

        total_renamed += renamed
        total_merged += merged
        total_deleted += deleted
        total_noop += noop
        return (renamed, merged, deleted, noop)

    batch_size = max(1, int(args.batch_size or 1000))

    for doc in cursor:
        total_scanned += 1
        if isinstance(doc, dict) and isinstance(doc.get("signature"), str) and _OLD_SIG_RE.fullmatch(doc["signature"]):
            total_old += 1
        buffer.append(doc if isinstance(doc, dict) else {})
        if len(buffer) >= batch_size:
            _flush(buffer)
            buffer = []

    if buffer:
        _flush(buffer)

    print("✅ סיכום מיגרציה:")
    print(f"- scanned: {total_scanned}")
    print(f"- old_format_matched: {total_old}")
    print(f"- renamed: {total_renamed}")
    print(f"- merged: {total_merged}")
    print(f"- deleted_old_after_merge: {total_deleted}")
    print(f"- noop_skipped: {total_noop}")
    if args.dry_run:
        print("ℹ️ מצב dry-run: לא בוצעו כתיבות למסד")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

