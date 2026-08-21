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
    """חריגה מתקרת הפתקים, או ספירה שלא הצליחה.

    שני המקרים מיוצגים כתת-מחלקות, ו**זהות השגיאה חיה בסוג ולא בטקסט**.
    ``except NoteQuotaError`` ממשיך לתפוס את שניהם, אבל מי שצריך להחזיר קוד
    ללקוח תופס את התת-מחלקה ומחזיר ליטרל — ולא ``str(exc)``.

    הסיבה: ``str`` על חריגה הוא הבטחה שאיש לא אוכף. ``raise`` אחד עתידי
    שמשרשר נתיב או שאילתה מוצא אותם ללקוח, ו-CodeQL מסמן בדיוק את הזרימה
    הזו. סוג של חריגה לא נושא טקסט שאפשר לדלוף.
    """


class NoteQuotaUnknown(NoteQuotaError):
    """הספירה נכשלה, ולכן אי אפשר לדעת אם יש מקום."""


class NoteQuotaExceeded(NoteQuotaError):
    """התקרה מלאה."""


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

#: תקרת אורך התוכן של פתק, בתווים.
#:
#: **מקור האמת היחיד.** המספר הזה היה מוקלד ידנית ב-15 מקומות — 12 פעמים
#: ב-``webapp/sticky_notes_api.py``, פעם ב-``mcp_server/handlers.py``, פעם
#: ב-JS ופעמיים בתיעוד. משמעות הפיזור הזו היא שכל שינוי ערך משאיר מאחור
#: מסלול אחד שאוכף מספר אחר, ומי שנתקל בו רואה חיתוך בלי הסבר.
#:
#: **למה דווקא 20,000:** זו הנקודה שבה תקרת ההעברה (``max_b64_len=120000``
#: ב-``_decode_content_b64``) מפסיקה להיות תקרה שנייה נסתרת. 20,000 תווים
#: של אימוג'י — המקרה הכבד ביותר, ארבעה בתים לתו — נותנים 106,668 תווי
#: base64, כלומר עדיין מתחת ל-120,000. מעל זה צריך לשנות גם אותה, ואז אין
#: נקודת עצירה טבעית.
MAX_NOTE_CHARS = 20_000

#: תקרת פתקים ללוח יחיד.
MAX_NOTES_PER_BOARD = 200

#: תקרת פתקים לכל המשתמש, על פני קבצים ולוחות כאחד.
#:
#: שתיהן כאן ולא ב-``webapp`` מאותה סיבה שהביאה את :data:`MAX_NOTE_CHARS`
#: הנה: ``mcp_server`` אינו יכול לייבא מהוובאפ (מודול Flask כבד), ולכן כל
#: תקרה שיושבת שם נאלצת להיות מוקלדת שוב בצד השני. שני מספרים שמסונכרנים
#: בתקווה הם מספר אחד שגוי שמחכה.
MAX_NOTES_PER_USER = 1000

#: אורך מרבי לשם פתק. שם הוא תווית קצרה בשורת הכפתורים, לא כותרת.
MAX_NOTE_TITLE = 80


def normalize_note_title(value: Any) -> str:
    """שם פתק מנורמל, או מחרוזת ריקה.

    **מחרוזת ריקה משמעותה "אין שם", והשדה נמחק מהמסמך** ולא נשמר כ-``""``.
    זה לא קוסמטי: האינדקס הייחודי משתמש ב-``partialFilterExpression`` עם
    ``$exists``, ולכן שני פתקים עם ``title: ""`` היו מתנגשים זה בזה. פתק
    בלי השדה כלל פשוט אינו באינדקס.

    (``$ne`` אינו נתמך ב-``partialFilterExpression`` — נבדק מול מונגו
    7.0 ונדחה ב-``Error in specification``. ``$exists`` נתמך.)

    **רק מחרוזת היא שם.** ``str(value)`` על גוף JSON שרירותי הופך
    ``["a", "b"]`` ל-``"['a', 'b']"`` ו-``{"x": 1}`` ל-``"{'x': 1}"`` —
    כלומר ייצוג פייתון פנימי נשמר במסד ומוצג למשתמש כשם הפתק. כל טיפוס
    שאינו ``str`` נחשב "אין שם", בדיוק כמו מחרוזת ריקה.
    """
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text:
        return ""
    # שורה אחת: שם שנשפך לשתי שורות שובר את שורת הכפתורים
    text = " ".join(text.split())
    return text[:MAX_NOTE_TITLE]


#: מפרט האינדקס שאוכף "שם אחד לכל לוח" — **מקור האמת היחיד**.
#:
#: הוא כאן ולא ב-``webapp`` מאותה סיבה שהביאה הנה את התקרות: גם ה-webapp
#: וגם ``mcp_server`` כותבים פתקים עם שם, ושניהם מחזירים ``duplicate_title``
#: כשהמסד דוחה. אכיפה שקיימת רק בצד אחד היא הבטחה שהצד השני מפר בשקט.
#:
#: **למה גם ``board_id`` בפילטר:** בלעדיו פתקי **קבצים** נכנסים לאינדקס עם
#: ``board_id`` חסר, כלומר כולם חולקים את אותו ערך מפתח — ושני פתקים על
#: שני קבצים שונים עם אותו שם נדחים ב-E11000. נמדד מול מונגו 7.0.14:
#: עם הפילטר הישן ההוספה השנייה נדחתה, עם החדש היא עוברת, והייחודיות בתוך
#: לוח נשמרת. זו גם ההתנהגות שביקשנו — בקבצים אותו שם הוא גרסה נוספת, לא
#: התנגשות.
ONE_TITLE_PER_BOARD_INDEX: Dict[str, Any] = {
    "keys": [("user_id", 1), ("board_id", 1), ("title", 1)],
    "name": "one_title_per_board",
    "unique": True,
    "partialFilterExpression": {"title": {"$exists": True}, "board_id": {"$exists": True}},
}


def ensure_title_index(coll: Any) -> bool:
    """יוצר את :data:`ONE_TITLE_PER_BOARD_INDEX`, ומיישב גרסה ישנה שלו.

    ``coll`` הוא אוסף pymongo, אבל הטיפוס אינו מיובא כאן — המודול הזה נשאר
    טהור כדי ש-``mcp_server`` יוכל לייבא ממנו. הקריאות היחידות הן
    ``index_information`` / ``drop_index`` / ``create_index``.

    **למה יש כאן יישוב ולא רק יצירה:** אינדקס בשם קיים עם אפשרויות שונות
    נדחה ב-``code 86`` (נמדד מול מונגו 7.0.14) — כלומר בפרודקשן, שבה כבר
    יושב האינדקס עם הפילטר הישן, יצירה תמימה הייתה נכשלת, הכשל היה נבלע,
    והבאג היה נשאר בדיוק כפי שהוא. לכן: משווים, ואם שונה — מפילים ובונים.

    :returns: ``True`` רק אחרי **קריאה חוזרת** שמאשרת שהאינדקס במסד תואם
        למפרט. ערך החזרה של כתיבה אינו אימות.
    """
    want = ONE_TITLE_PER_BOARD_INDEX
    name = want["name"]
    try:
        info = coll.index_information()
    except Exception:
        info = {}

    existing = info.get(name) if isinstance(info, Mapping) else None
    if existing is not None and not _index_matches(existing, want):
        # אינדקס ישן עם פילטר אחר — הוא מה שחוסם את היצירה החדשה
        coll.drop_index(name)

    coll.create_index(
        want["keys"],
        name=name,
        unique=want["unique"],
        partialFilterExpression=want["partialFilterExpression"],
    )

    try:
        fresh = coll.index_information()
    except Exception:
        return False
    if not isinstance(fresh, Mapping):
        return False
    return _index_matches(fresh.get(name), want)


def _index_matches(spec: Any, want: Mapping[str, Any]) -> bool:
    """האם מפרט שנקרא מהמסד תואם למה שביקשנו.

    ``partialFilterExpression`` חוזר כ-``SON``, שהוא תת-מחלקה של ``dict``
    ולכן ההשוואה למילון רגיל תקפה ואינה תלוית סדר (נבדק).
    """
    if not isinstance(spec, Mapping):
        return False
    if spec.get("unique") is not True:
        return False
    if spec.get("partialFilterExpression") != want["partialFilterExpression"]:
        return False
    # ``index_information`` מחזיר את המפתחות כרשימת זוגות
    keys = [(str(f), v) for f, v in (spec.get("key") or [])]
    return keys == [(f, v) for f, v in want["keys"]]


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
        raise NoteQuotaUnknown("note_quota_unknown")
    if int(existing) >= int(cap):
        raise NoteQuotaExceeded("note_quota_exceeded")
