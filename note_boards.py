"""
Note Boards — לוחות פתקים, ולוח ברירת המחדל שאי אפשר לאבד.

לוח הוא משטח שעליו יושבים פתקים שאינם שייכים לשום קובץ. המודול הזה מחזיק את
המנגנון של לוח ברירת המחדל ואת ריפוי הפתקים היתומים, ומקבל ``db`` כפרמטר —
בדיוק כמו ``sticky_notes_scope.sync_sticky_notes_on_rename`` — כדי שיהיה
ניתן לבדיקה מול stub בלי להרים אפליקציה.

**במה זה נבדל מ"שולחן עבודה" באוספים, ולמה במכוון.** ב-``collections_manager``
אין שדה ``is_default`` בכלל: הזיהוי הוא השוואת המחרוזת ``"שולחן עבודה"``
בשישה קבצים, אין שום חסימת מחיקה, וכשהאוסף נמחק נוצר בטעינה הבאה אוסף
**חדש וריק**. באוספים זה נסבל, כי הקבצים עצמם חיים ב-``code_snippets``
ושורדים — מוחקים אוסף ומאבדים את הסידור, לא את התוכן.

בלוח זה לא נסבל: הלוח **הוא** המקום היחיד של הפתק. לוח ברירת מחדל שנמחק
והוחלף בלוח חדש וריק היה משאיר את הפתקים במסד עם ``board_id`` שמצביע ללוח
מת — בלתי נראים בממשק ובלתי ניתנים לשחזור בלי גישה ישירה למונגו. ובנוסף,
זיהוי לפי שם נשבר ברגע שהמשתמש משנה את שם הלוח, וזה מותר במפורש.

לכן: ``is_default`` אמיתי, אינדקס ייחודי שמונע שני לוחות ברירת מחדל, וריפוי
שמתקן את ה**קישור** של פתק יתום במקום לייצר לוח פנטום.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: שם לוח ברירת המחדל. ניתן לשינוי על ידי המשתמש — הזיהוי הוא ``is_default``
#: ולא השם, ולכן שינוי שם אינו שובר כלום.
DEFAULT_BOARD_NAME = "לוח עבודה"

#: אורך מרבי לשם לוח.
MAX_BOARD_NAME = 120


def _boards_coll(db: Any):
    return getattr(db, "note_boards", None)


def _notes_coll(db: Any):
    return getattr(db, "sticky_notes", None)


def normalize_board_name(value: Any) -> str:
    """שם לוח מנורמל. ריק ⇒ שם ברירת המחדל, כדי שלא ייווצר לוח בלי שם."""
    name = " ".join(str(value or "").split())[:MAX_BOARD_NAME]
    return name or DEFAULT_BOARD_NAME


def ensure_default_board(db: Any, user_id: int) -> Optional[str]:
    """מזהה לוח ברירת המחדל של המשתמש, ויוצר אותו אם אינו קיים.

    אידמפוטנטית. מחזירה את מזהה הלוח כמחרוזת, או ``None`` אם אין אוסף.

    **על המרוץ:** שתי בקשות מקבילות של אותו משתמש יכולות שתיהן לגלות שאין
    לוח ולנסות ליצור. הגנת הקוד לבדה אינה מספיקה כאן, ולכן האינדקס
    ``one_default_per_user`` הוא ייחודי-חלקי (``is_default: True``) והמסד
    דוחה את השני. הכשל הזה צפוי ולא חריג, ולכן אחריו קוראים שוב — ומחזירים
    את הלוח שהמנצח יצר.
    """
    coll = _boards_coll(db)
    if coll is None:
        return None
    uid = int(user_id)

    existing = coll.find_one({"user_id": uid, "is_default": True})
    if existing:
        return str(existing.get("_id") or "") or None

    now = datetime.now(timezone.utc)
    doc: Dict[str, Any] = {
        "user_id": uid,
        "name": DEFAULT_BOARD_NAME,
        "is_default": True,
        "order": 0,
        "created_at": now,
        "updated_at": now,
    }
    try:
        coll.insert_one(doc)
    except Exception as exc:
        # מרוץ, או כל כשל אחר — לא מסיקים דבר מהחריגה עצמה.
        logger.info("default board insert did not complete: %s", exc)

    # אימות בקריאה חוזרת, ולא הסתמכות על ערך ההחזרה של הכתיבה: ``insert_one``
    # שהחזיר ``inserted_id`` אינו מוכיח שהמסמך נמצא, והמרוץ מייצר בדיוק את
    # המצב שבו הכתיבה שלנו נדחתה אבל הלוח כן קיים.
    confirmed = coll.find_one({"user_id": uid, "is_default": True})
    if not confirmed:
        logger.warning("default board missing after ensure", extra={"user_id": uid})
        return None
    return str(confirmed.get("_id") or "") or None


def list_boards(db: Any, user_id: int) -> List[Dict[str, Any]]:
    """לוחות המשתמש לפי סדר תצוגה. ברירת המחדל תמיד ראשונה."""
    coll = _boards_coll(db)
    if coll is None:
        return []
    cursor = coll.find({"user_id": int(user_id)})
    docs = [d for d in (list(cursor) if cursor is not None else []) if isinstance(d, dict)]
    docs.sort(key=lambda d: (0 if d.get("is_default") else 1, int(d.get("order") or 0), str(d.get("name") or "")))
    return docs


def reattach_orphan_notes(db: Any, user_id: int, known_board_ids: List[str], default_board_id: str) -> int:
    """מחזיר פתקים שמצביעים ללוח שאינו קיים אל לוח ברירת המחדל.

    מחזירה כמה פתקים אכן הועברו — נספר ב**קריאה חוזרת** ולא מ-
    ``modified_count``, שמדווח בחסר כשמסמך כבר היה בערך היעד.

    זהו ריפוי-עצמי מהסוג הנכון: הוא מתקן את הקישור של פתק קיים. ההפך
    מ-``collections_api``, שבמצב מקביל יוצר אוסף חדש וריק ומשאיר את הפריטים
    הישנים מאחור.
    """
    coll = _notes_coll(db)
    if coll is None or not default_board_id:
        return 0
    uid = int(user_id)
    valid = [str(b) for b in (known_board_ids or []) if str(b)]
    orphan_query = {
        "user_id": uid,
        "board_id": {"$nin": valid, "$exists": True, "$ne": None},
    }
    try:
        before = coll.count_documents(orphan_query)
    except Exception:
        return 0
    if not before:
        return 0
    try:
        coll.update_many(
            orphan_query,
            {"$set": {"board_id": str(default_board_id), "updated_at": datetime.now(timezone.utc)}},
        )
    except Exception as exc:
        logger.warning("orphan notes reattach failed: %s", exc)
    try:
        after = coll.count_documents(orphan_query)
    except Exception:
        return 0
    return max(0, before - after)
