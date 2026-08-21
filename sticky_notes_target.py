"""
Sticky Notes Target — לאיזה משטח הפתק שייך, ומי אוכף שהוא שייך לאחד בדיוק.

פתק דביק שייך **או** לקובץ **או** ללוח — לעולם לא לשניהם ולעולם לא לאף אחד.
המודול הזה הוא המקום היחיד שיודע את הכלל הזה, והוא טהור בכוונה: בלי Flask,
בלי pymongo, בלי ``get_db``. כך גם ``webapp``, גם ``mcp_server`` וגם
``services`` יכולים לייבא אותו — בדיוק כמו ``sticky_notes_scope`` שכבר מיובא
משלושה מודולים.

למה מודול ולא בדיקה בראוט: שישה מודולים כותבים היום ישירות ל-``sticky_notes``
(``webapp/sticky_notes_api``, ``mcp_server/backend``, ``sticky_notes_scope``,
``services/personal_backup_service``, ``webapp/app``, ``webapp/push_api``).
"אילוץ בשכבת הוולידציה" הוא הצהרה ריקה כל עוד השכבה לא קיימת, ולכן
:func:`build_note_target` מקבלת **כוונה** ומחזירה את שדות היעד — ומריצה
ולידציה לפני ההחזרה. מי שקורא לה אינו יכול לייצר מסמך לא חוקי.

בעדכון אין צורך באכיפה נוספת: ``update_note`` ו-``batch`` בונים את השדות
מ-allowlist מפורש, ו-``file_id``/``board_id`` פשוט אינם ברשימה. זו הצורה
החזקה של האילוץ — לא בדיקה שאפשר לשכוח, אלא שדה שלא קיים בקלט.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional


class NoteTargetError(ValueError):
    """יעד הפתק אינו חוקי — שני משטחים, או אף אחד."""


class NoteQuotaError(ValueError):
    """חריגה מתקרת הפתקים, או ספירה שלא הצליחה."""


#: מצבי המיקום של פתק. ``surface`` = מעוגן למשטח שמתחתיו (הלוח), ``screen`` =
#: צמוד לחלון גם כשהמשטח זז. ``anchored`` שמור לפתקי קבצים, שבהם המיקום נגזר
#: משורת מקור — היום הם עדיין מקודדים את המצב בתוך ``anchor_id`` בעזרת
#: sentinels, ולכן הערך הזה אינו בשימוש עדיין. הוא ברשימה כדי שכשהם יעברו
#: לשדה אמיתי לא יידרש שינוי שם.
NOTE_MODES = ("surface", "screen", "anchored")

#: מה שפתק **לוח** רשאי להיות. ``anchored`` דורש שורות מקור, ובלוח אין
#: כאלה — ערך כזה שיגיע מה-API היה מייצר פתק שמחשב את מיקומו מול עוגן
#: שאינו קיים.
BOARD_NOTE_MODES = ("surface", "screen")
DEFAULT_BOARD_MODE = "surface"


def _clean(value: Any) -> str:
    """מזהה כמחרוזת מנורמלת. ``None``, ``''`` ומחרוזת רווחים — כולם ריקים."""
    return str(value or "").strip()


def validate_note_target(doc: Mapping[str, Any]) -> None:
    """מוודא שבמסמך מלא בדיוק אחד מבין ``file_id`` ו-``board_id``.

    :raises NoteTargetError: אם שניהם מלאים או ששניהם ריקים.
    """
    has_file = bool(_clean(doc.get("file_id")))
    has_board = bool(_clean(doc.get("board_id")))
    if has_file and has_board:
        raise NoteTargetError("note_target_ambiguous")
    if not has_file and not has_board:
        raise NoteTargetError("note_target_missing")


def build_note_target(
    *,
    file_id: Any = None,
    board_id: Any = None,
    scope_id: Optional[str] = None,
    file_name: Optional[str] = None,
) -> Dict[str, Any]:
    """שדות היעד למסמך פתק חדש — אחרי ולידציה, לא לפניה.

    ``scope_id`` ו-``file_name`` הם מושגים של קובץ בלבד. העברתם יחד עם
    ``board_id`` היא באג של הקורא ולא קלט שיש להשלים בשקט, ולכן היא נדחית.
    """
    fid = _clean(file_id)
    bid = _clean(board_id)

    if bid and (scope_id or file_name):
        raise NoteTargetError("board_note_cannot_carry_file_metadata")

    target: Dict[str, Any] = {}
    if fid:
        target["file_id"] = fid
        if scope_id:
            target["scope_id"] = scope_id
        if file_name:
            target["file_name"] = file_name
    if bid:
        target["board_id"] = bid

    validate_note_target(target)
    return target


def file_notes_filter(
    user_id: int,
    scope_id: Optional[str],
    related_ids: Optional[List[str]],
    file_id: Any = None,
) -> Dict[str, Any]:
    """שאילתת פתקים של קובץ — משקפת את הלוגיקה שהייתה בראוט.

    פתק לוח אינו יכול להיתפס כאן: אין לו ``scope_id`` ואין לו ``file_id``,
    ושלושת הענפים דורשים אחד מהם.
    """
    query: Dict[str, Any] = {"user_id": int(user_id)}
    criteria: List[Dict[str, Any]] = []
    if scope_id:
        criteria.append({"scope_id": scope_id})
    if related_ids:
        criteria.append({"file_id": {"$in": related_ids}})
    if criteria:
        query["$or"] = criteria
    else:
        query["file_id"] = _clean(file_id)
    return query


def board_notes_filter(user_id: int, board_id: Any) -> Dict[str, Any]:
    """שאילתת פתקים של לוח — ישירה, בלי ``$or`` ובלי מעבר דרך ``code_snippets``.

    ללוח יש ``_id`` יציב, ולכן אין צורך ב-``scope_id``: המנגנון ההוא הוא hash
    של **שם**, וכל קיומו של ``sync_sticky_notes_on_rename`` הוא כדי לרוץ אחרי
    שינויי שם ולתקן. לוח ניתן לשינוי שם בלי שהמזהה שלו יזוז.
    """
    return {"user_id": int(user_id), "board_id": _clean(board_id)}


def normalize_mode(value: Any, default: str = DEFAULT_BOARD_MODE) -> str:
    """מצב מיקום חוקי, או ברירת המחדל. לא זורק — ולכן מתאים לקלט משתמש."""
    candidate = _clean(value).lower()
    return candidate if candidate in NOTE_MODES else default


def is_valid_mode(value: Any) -> bool:
    """``True`` רק לערך שנמצא ב-:data:`NOTE_MODES`. לשימוש בוולידציה שדוחה 400."""
    return _clean(value).lower() in NOTE_MODES


def is_valid_board_mode(value: Any) -> bool:
    """``True`` רק למצב שפתק לוח רשאי להיות בו.

    נפרד מ-:func:`is_valid_mode` בכוונה: ``anchored`` חוקי לפתק קובץ אבל
    לא לפתק לוח. אימות עם הפונקציה הכללית היה מקבל ``anchored`` מה-API
    ומייצר פתק שמחשב ``top`` מול עוגן שאינו קיים — כלומר פתק שנעלם.
    """
    return _clean(value).lower() in BOARD_NOTE_MODES


def check_note_quota(existing: Optional[int], cap: int, *, is_admin: bool = False) -> None:
    """אכיפת תקרת פתקים. אדמין פטור.

    ``existing=None`` פירושו שהספירה נכשלה — ואז **דוחים**. זו הנקודה שבה
    ההתנהגות כאן נבדלת במכוון מ-``mcp_server/backend``, שמתייחס לכשל ספירה
    כאילו אין פתקים ומעביר את היצירה. תקרה שנפתחת לרווחה בדיוק כשהמסד
    מתקשה היא לא תקרה.

    :raises NoteQuotaError: בחריגה, או כשהספירה אינה ידועה.
    """
    if is_admin:
        return
    if existing is None:
        raise NoteQuotaError("note_quota_unknown")
    if int(existing) >= int(cap):
        raise NoteQuotaError("note_quota_exceeded")
