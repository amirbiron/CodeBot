#!/usr/bin/env python3
"""מיגרציה ובדיקת שפיות ללוחות פתקים.

הרצה::

    python scripts/migrate_note_boards.py           # דוח בלבד, לא כותב
    python scripts/migrate_note_boards.py --apply   # יוצר לוחות ברירת מחדל

הסקריפט בטוח להרצה חוזרת. הוא עושה שני דברים:

1. **דוח הפרות של האילוץ "בדיוק אחד".** אין בריפו תשתית migrations שתחזיק
   ``$jsonSchema`` validator ברמת מונגו, והוספת אחד בלעדיה תישבר בפריסה
   הבאה. ההרצה החוזרת של הסקריפט הזה היא הבדיקה: כמה פתקים נושאים גם
   ``file_id`` וגם ``board_id``, וכמה לא נושאים אף אחד.

2. **יצירת לוח ברירת מחדל** למשתמשים קיימים, ב-``--apply`` בלבד. בתבנית
   ``scripts/migrate_workspace_collections.py``.

ברירת המחדל היא **דוח בלבד**: סקריפט שכותב ברגע שמריצים אותו הוא סקריפט
שאי אפשר להריץ כדי פשוט לראות מה המצב.
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any, Optional

log = logging.getLogger(__name__)


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def audit_note_targets(db: Any) -> dict:
    """סופר הפרות של האילוץ. לא כותב דבר."""
    notes = db.sticky_notes
    empty = {"$in": [None, ""]}

    both = notes.count_documents({
        "file_id": {"$nin": [None, ""]},
        "board_id": {"$nin": [None, ""]},
    })
    neither = notes.count_documents({
        "$and": [
            {"$or": [{"file_id": {"$exists": False}}, {"file_id": empty}]},
            {"$or": [{"board_id": {"$exists": False}}, {"board_id": empty}]},
        ]
    })
    total = notes.count_documents({})
    board_notes = notes.count_documents({"board_id": {"$nin": [None, ""]}})

    return {
        "total": total,
        "board_notes": board_notes,
        "violations_both": both,
        "violations_neither": neither,
    }


def create_missing_default_boards(db: Any, *, apply: bool) -> dict:
    """לוח ברירת מחדל לכל משתמש שחסר לו."""
    from note_boards import ensure_default_board

    created = 0
    checked = 0
    failed = 0

    for raw_user in db.users.find({}, {"user_id": 1}):
        user_id = _safe_int((raw_user or {}).get("user_id"))
        if user_id is None:
            continue
        checked += 1
        existing = db.note_boards.find_one({"user_id": user_id, "is_default": True})
        if existing:
            continue
        if not apply:
            created += 1
            continue
        if ensure_default_board(db, user_id):
            created += 1
        else:
            failed += 1
            log.warning("failed to create default board for user %s", user_id)

    return {"checked": checked, "created": created, "failed": failed}


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="מיגרציה ובדיקה ללוחות פתקים")
    parser.add_argument("--apply", action="store_true", help="לכתוב בפועל, ולא רק לדווח")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        from webapp.app import get_db
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("לא ניתן לייבא את get_db מ-webapp.app") from exc

    db = get_db()

    audit = audit_note_targets(db)
    print("— בדיקת האילוץ 'בדיוק אחד' —")
    print(f"  סה\"כ פתקים:            {audit['total']}")
    print(f"  מהם פתקי לוח:          {audit['board_notes']}")
    print(f"  הפרות (שני היעדים):    {audit['violations_both']}")
    print(f"  הפרות (אף יעד):        {audit['violations_neither']}")

    boards = create_missing_default_boards(db, apply=args.apply)
    mode = "נוצרו" if args.apply else "חסרים (לא נכתב — הרץ עם --apply)"
    print("\n— לוחות ברירת מחדל —")
    print(f"  משתמשים שנבדקו:        {boards['checked']}")
    print(f"  {mode}: {boards['created']}")
    if boards["failed"]:
        print(f"  נכשלו:                 {boards['failed']}")

    violations = audit["violations_both"] + audit["violations_neither"]
    if violations:
        print(f"\n⚠️  {violations} פתקים מפרים את האילוץ. זו אינה תקלה שהסקריפט מתקן —")
        print("    היא מצביעה על מסלול כתיבה שעוקף את build_note_target.")
        return 1
    if boards["failed"]:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
