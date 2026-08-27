"""
Sticky Notes Target — לאיזה משטח הפתק שייך, ומי אוכף שהוא שייך לאחד בדיוק.

פתק דביק שייך ל**יעד אחד בדיוק** — קובץ, לוח, או קובץ בריפו ממורר
(``repo_name`` + ``repo_path`` יחד). לעולם לא לשניים ולעולם לא לאף אחד.
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

import re
from typing import Any, Dict, List, Mapping, Optional, Tuple


#: ``IndexNotFound`` — מונגו מחזיר אותו כשמפילים אינדקס שכבר אינו שם.
_INDEX_NOT_FOUND = 27


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

#: תקרת פתקים לקובץ ריפו יחיד.
#:
#: אותה מוסכמה כמו :data:`MAX_NOTES_PER_BOARD`, אבל נמוכה בכוונה: פתק על
#: קובץ הוא הערה, לא מסמך. עשרים פתקים על קובץ אחד הם סימן שהתוכן שייך
#: לעמוד תיעוד. **בניגוד לתקרת המשתמש, זו נאכפת גם על אדמין** — דפדפן
#: הריפו חסום לאדמינים, אז אם היא הייתה פטורה-לאדמין (כמו
#: :data:`MAX_NOTES_PER_USER`) היא לא הייתה נאכפת על אף אחד. מטרתה שמירת
#: צורת-תוכן, לא הגנת-משאבים, ולכן הקורא מעביר לה ``is_admin=False`` תמיד.
MAX_NOTES_PER_REPO_FILE = 20

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
    return canonical_title_text(value)[:MAX_NOTE_TITLE]


def canonical_title_text(value: Any) -> str:
    """אותה קנוניזציה של שם פתק — **בלי הקיצוץ**.

    הפיצול אינו סגנוני. ל-:func:`normalize_note_title` שתי עבודות נפרדות:
    קנוניזציה (טיפוס, ``strip``, כיווץ לשורה אחת) וקיצוץ לתקרה. מי שרוצה
    לדעת אם הקלט **חרג** מהתקרה אינו יכול לשאול את הפלט שלה — הוא כבר
    קוצץ, ולכן ``len(...) > MAX_NOTE_TITLE`` שם הוא תמיד ``False``.

    זה נצרך בחיפוש: שאילתה ארוכה מכל שם אפשרי לעולם לא תתפוס דבר, וקיצוץ
    שקט שלה מחזיר תוצאות עבור **קידומת** — כלומר תשובה לשאלה אחרת מזו
    שנשאלה, בלי שום סימן. הקנוניזציה עצמה נשארת מוגדרת פעם אחת, כאן.
    """
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text:
        return ""
    # שורה אחת: שם שנשפך לשתי שורות שובר את שורת הכפתורים
    return " ".join(text.split())


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
#: **למה השם נושא גרסה:** מונגו אינו יודע לשנות שם של אינדקס, ואינדקס
#: קיים עם אפשרויות שונות נדחה ב-``code 86``. כלומר עדכון "במקום" מחייב
#: להפיל ואז לבנות — וברגעים שבין השניים אין ייחודיות כלל, ושתי בקשות
#: מקבילות יכולות להכניס שני שמות זהים לאותו לוח. אז הבנייה החדשה נכשלת,
#: והאכיפה נשארת מושבתת.
#:
#: עם שם ממוספר הסדר מתהפך: **בונים את החדש, ורק אז מפילים את הישן.**
#: בכל רגע נתון יש לפחות אינדקס ייחודי אחד. נמדד מול מונגו 7.0.14 — שני
#: אינדקסים על אותם מפתחות עם ``partialFilterExpression`` שונה **מותרים**
#: לחיות זה לצד זה, ובכל אחד מארבעת הצעדים הייחודיות נאכפה.
#:
#: שינוי עתידי במפרט ← להעלות ל-``_v3`` ולהוסיף את ``_v2`` לרשימה שמתחת.
ONE_TITLE_PER_BOARD_INDEX: Dict[str, Any] = {
    "keys": [("user_id", 1), ("board_id", 1), ("title", 1)],
    "name": "one_title_per_board_v2",
    "unique": True,
    "partialFilterExpression": {"title": {"$exists": True}, "board_id": {"$exists": True}},
}

#: שמות של גרסאות קודמות. מופלים **רק אחרי** שהאינדקס הנוכחי אומת במסד.
SUPERSEDED_TITLE_INDEX_NAMES: Tuple[str, ...] = ("one_title_per_board",)


#: אינדקס מקביל לפתקי ריפו — "שם אחד לכל קובץ בריפו".
#:
#: פתק ריפו אין לו ``board_id``, ולכן הוא נופל **מחוץ** ל-
#: :data:`ONE_TITLE_PER_BOARD_INDEX` (שהפילטר שלו דורש ``board_id`` קיים) —
#: כלומר בלי אינדקס משלו הוא מקבל אפס ייחודיות שם, בשקט. הפילטר כאן דורש
#: ``repo_path`` קיים, בדיוק כמו שהאח שלו דורש ``board_id``, ומאותה סיבה:
#: פתקי קובץ/לוח (בלי ``repo_path``) נופלים מחוץ לאינדקס ואינם מתנגשים בו.
#:
#: הנורמליזציה של :func:`normalize_repo_path` חלה **גם על המפתח הזה** — היא
#: רצה בכתיבה, ולכן ``docs/x.rst`` ו-``/docs/x.rst`` נשמרים כאותו ערך
#: ומתנגשים כראוי, במקום להיות שני מפתחות שונים שהייחודיות מחמיצה ביניהם.
#:
#: שינוי עתידי במפרט ← להעלות ל-``_v2`` ולהוסיף את ``_v1`` לרשימה שמתחת.
ONE_TITLE_PER_REPO_FILE_INDEX: Dict[str, Any] = {
    "keys": [("user_id", 1), ("repo_name", 1), ("repo_path", 1), ("title", 1)],
    "name": "one_title_per_repo_file_v1",
    "unique": True,
    # **שני חצאי היעד נדרשים בפילטר**, לא רק ``repo_path``. מסמך פגום
    # שנושא ``repo_path`` בלי ``repo_name`` (מסלול כתיבה עוקף, או נתון ישן)
    # אינו יעד ריפו חוקי; בלי ``repo_name`` בפילטר הוא בכל זאת נכנס
    # לאינדקס תחת ``repo_name`` חסר, ושניים כאלה עם אותו שם היו מתנגשים
    # — או מפילים את בניית האינדקס. הדרישה לשני החצאים מצמצמת את האינדקס
    # בדיוק ליעדי ריפו שלמים, בדיוק כפי ש-``build_note_target`` מייצר.
    "partialFilterExpression": {
        "title": {"$exists": True},
        "repo_name": {"$exists": True},
        "repo_path": {"$exists": True},
    },
}

#: שמות גרסאות קודמות של אינדקס הריפו. ריק — זו הגרסה הראשונה.
SUPERSEDED_REPO_TITLE_INDEX_NAMES: Tuple[str, ...] = ()


def ensure_title_index(coll: Any) -> bool:
    """יוצר את :data:`ONE_TITLE_PER_BOARD_INDEX`, ומיישב גרסה ישנה שלו.

    ``coll`` הוא אוסף pymongo, אבל הטיפוס אינו מיובא כאן — המודול הזה נשאר
    טהור כדי ש-``mcp_server`` יוכל לייבא ממנו. הקריאות היחידות הן
    ``index_information`` / ``drop_index`` / ``create_index``.

    **הסדר הוא כל העניין: בונים את החדש, ורק אז מפילים את הישן.** מונגו
    אינו יודע לשנות שם של אינדקס, ולכן עדכון "במקום" מחייב את הסדר ההפוך
    — ובין ההפלה לבנייה אין ייחודיות כלל, ושתי בקשות מקבילות יכולות
    להכניס שני שמות זהים לאותו לוח. אז הבנייה החדשה נכשלת, והאכיפה
    נשארת מושבתת לחלוטין. השם הממוספר הוא מה שמאפשר את הסדר הנכון: שני
    אינדקסים על אותם מפתחות עם ``partialFilterExpression`` שונה **מותרים**
    לחיות זה לצד זה (נמדד מול מונגו 7.0.14).

    שני קודי השגיאה שמעצבים את הפונקציה, שניהם נמדדו:
    ``code 85`` — אינדקס עם אותו מפרט בדיוק כבר קיים בשם אחר;
    ``code 86`` — אינדקס באותו שם כבר קיים עם מפרט אחר.

    ומכאן גם הכלל השני: **אינדקס שנושא את המפרט הנכון תחת שם ישן נשאר
    כמו שהוא.** ראו :func:`_enforcing_index_name`.

    :returns: ``True`` רק אחרי **קריאה חוזרת** שמאשרת שהאינדקס במסד תואם
        למפרט. ערך החזרה של כתיבה אינו אימות.
    """
    return _ensure_versioned_unique_index(
        coll, ONE_TITLE_PER_BOARD_INDEX, SUPERSEDED_TITLE_INDEX_NAMES
    )


def ensure_repo_title_index(coll: Any) -> bool:
    """יוצר את :data:`ONE_TITLE_PER_REPO_FILE_INDEX`, באותה משמעת בדיוק.

    אח תאום ל-:func:`ensure_title_index`: אותו רצף "בונה → מאמת בקריאה
    חוזרת → מפיל ישן", אותה החזרה של ``True`` רק אחרי אימות במסד. ראו שם.
    """
    return _ensure_versioned_unique_index(
        coll, ONE_TITLE_PER_REPO_FILE_INDEX, SUPERSEDED_REPO_TITLE_INDEX_NAMES
    )


def _ensure_versioned_unique_index(
    coll: Any, want: Mapping[str, Any], superseded: Tuple[str, ...]
) -> bool:
    """המנוע המשותף מאחורי :func:`ensure_title_index` ו-:func:`ensure_repo_title_index`.

    כל ההיגיון של "בונים את החדש ורק אז מפילים את הישן" חי כאן פעם אחת,
    ושתי הפונקציות הציבוריות רק מזריקות את המפרט ואת רשימת השמות הישנים.
    """
    name = want["name"]
    try:
        info = coll.index_information()
    except Exception:
        info = {}
    if not isinstance(info, Mapping):
        info = {}

    live = _enforcing_index_name(info, want, superseded)
    if live is None:
        # השם הנוכחי תפוס במפרט אחר. זה קורה **רק** אם מישהו שינה את
        # המפרט בלי להעלות את מספר הגרסה בשם — כלומר בדיוק מה שהמספור בא
        # למנוע. כאן אין מוצא: מונגו דוחה ב-``code 86``, ובלי ההפלה
        # האינדקס לעולם לא יתכנס. זה המקום היחיד שנשאר בו חלון בלי
        # ייחודיות, והדרך להימנע ממנו היא להעלות ל-``_v3`` ולא לערוך את
        # ``_v2`` במקום.
        if name in info:
            _drop_index_if_present(coll, name)

        coll.create_index(
            want["keys"],
            name=name,
            unique=want["unique"],
            partialFilterExpression=want["partialFilterExpression"],
        )
        try:
            info = coll.index_information()
        except Exception:
            return False
        if not isinstance(info, Mapping):
            return False
        live = _enforcing_index_name(info, want, superseded)
        if live is None:
            return False

    # **רק עכשיו** — יש אינדקס חי ומאומת, ולכן הפלת השאר אינה פותחת חלון
    # בלי ייחודיות. ``live`` עצמו לעולם אינו מופל.
    for stale in superseded:
        if stale != live and stale in info:
            _drop_index_if_present(coll, stale)
    return True


def _enforcing_index_name(
    info: Mapping[str, Any], want: Mapping[str, Any], superseded: Tuple[str, ...]
) -> Optional[str]:
    """שם האינדקס שאוכף כרגע **בדיוק** את המפרט המבוקש, אם קיים כזה.

    **למה השם אינו חשוב והמפרט כן:** אינדקס שנושא את המפרט הנכון תחת שם
    ישן כבר אוכף את האילוץ במלואו. הפלתו כדי "לסדר" את השם הייתה מפילה
    את האינדקס **היחיד** שאוכף, ורק אז בונה — כלומר פותחת בדיוק את החלון
    שכל המספור בא לסגור, ובלי שום תמורה. לכן הוא נחשב תקין כמו שהוא.

    השם הקנוני נבדק ראשון, כדי שאחרי מיגרציה מלאה לא נשאר תלויים בישן.
    """
    if _index_matches(info.get(want["name"]), want):
        return str(want["name"])
    for stale in superseded:
        if _index_matches(info.get(stale), want):
            return stale
    return None


def title_is_taken(
    coll: Any,
    *,
    user_id: Any,
    board_id: Any,
    title: str,
    exclude_id: Any = None,
) -> bool:
    """האם השם כבר תפוס בלוח — בדיקת **קוד**, לא של המסד.

    **זו אינה החלפה לאינדקס והיא לא נועדה לרוץ בדרך כלל.** האינדקס הוא מה
    שסוגר את המרוץ; שאילתה כאן יכולה תמיד להפסיד לכותב מקביל שנכנס בין
    הבדיקה לכתיבה. היא קיימת בשביל מצב אחד בלבד: כש-:func:`ensure_title_index`
    לא הצליחה לאמת שהאינדקס במסד, ואז הברירה היא בין אכיפה חלקית לבין אפס
    אכיפה — בעוד שהקריאה לשירות **מבטיחה** ``duplicate_title``. הבטחה שאין
    מאחוריה כלום היא הדבר היחיד שגרוע יותר מהתנגשות.

    לכן היא נקראת מאחורי דגל, ובמצב התקין אינה עולה אף שאילתה.
    """
    if not title:
        return False
    query: Dict[str, Any] = {"user_id": user_id, "board_id": board_id, "title": title}
    if exclude_id is not None:
        # ההחרגה שייכת ל**שאילתה**, לא לסינון התוצאה שחזרה. ``find_one``
        # מחזיר מסמך אחד שרירותי, ולכן סינון בדיעבד היה יכול לקבל דווקא
        # את הפתק שאנחנו מעדכנים ולהחזיר "פנוי" — בעוד שפתק אחר עם אותו
        # שם יושב שם ומחכה.
        query["_id"] = {"$ne": exclude_id}
    try:
        return coll.find_one(query, {"_id": 1}) is not None
    except Exception:
        # שאילתה שנכשלה אינה ראיה לכך שהשם פנוי. ראו ``check_note_quota``:
        # באותו ריפו כבר נקבע שכשל בדיקה נסגר ולא נפתח.
        return True


def _drop_index_if_present(coll: Any, name: str) -> None:
    """מפיל אינדקס, ובולע **רק** את המקרה שבו הוא כבר לא שם.

    תהליך מקביל שהספיק להפיל אותו לפנינו אינו תקלה — והחריגה שלו לא
    אמורה לעצור את שאר הרצף.
    """
    try:
        coll.drop_index(name)
    except Exception as exc:  # pragma: no cover - תלוי דרייבר
        if getattr(exc, "code", None) != _INDEX_NOT_FOUND:
            raise


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


def normalize_repo_path(value: Any) -> str:
    """נתיב קובץ בריפו, בדיוק בצורה ש-``repo_files`` שומר.

    **היעד אינו "עקביות פנימית" אלא התכנסות לצורה קיימת.** האינדוקסר
    (``services/code_indexer.py``) שומר את ``repo_files.path`` כפי שהוא
    מגיע מ-git — לוכסנים קדימה, בלי ``/`` מוביל. גילוי היתומים משווה את
    ``repo_path`` של הפתק מול המניפסט הזה; אם הצורות לא זהות, ההשוואה
    מחזירה "מיותם" לקובץ שקיים — כשל שקט. לכן הנורמליזציה כאן מתכנסת
    לאותה צורה: ``\\``→``/``, כיווץ ``//``, פתרון ``.``/``..``, והסרת ``/``
    מוביל.

    **רצה בשני הקצוות** — בכתיבה (:func:`build_note_target`) ובקריאה
    (:func:`repo_notes_filter`). נורמליזציה בצד אחד בלבד היא הכשל השקט
    הקלאסי: פתק שנכתב לא-מנורמל לא יימצא לעולם, כי השאילתה מחפשת את הצורה
    המנורמלת.

    **מעבר-מעלה נדחה** ל-``""``. ``../etc/passwd`` אינו נתיב בתוך הריפו,
    ופתק עם ``repo_path`` ריק ייפול ב-:func:`validate_note_target` (``repo``
    דורש את שני חצאיו). כלומר ניסיון traversal לא מייצר פתק, לא זולג לאינדקס.
    """
    raw = str(value or "").strip()
    if not raw:
        return ""

    # ``..`` פנימי שנשאר בתוך הריפו הוא נתיב לגיטימי ונפתר
    # (``webapp/../webapp/app.py`` ← ``webapp/app.py``); רק **בריחה מעל
    # השורש** נפסלת. הכלל נגזר מהמטרה — התכנסות לצורת ``repo_files`` —
    # ולא מפחד מהתו עצמו.
    #
    # הפתרון ידני ולא דרך ``normpath`` בלבד, כי ``normpath`` בולע ``/..``
    # אל השורש: ``/../x`` היה הופך ל-``x``, כלומר בריחה שנראית תמימה.
    # כאן חריגה מעל השורש מותירה ``..`` במחסנית, והנתיב נפסל.
    parts: List[str] = []
    for part in raw.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return ""  # בריחה אל מעל שורש הריפו
            parts.pop()
            continue
        parts.append(part)

    normalized = "/".join(parts)
    if normalized in ("", "."):
        return ""
    return normalized


#: לכל סוג יעד — קבוצת השדות שמותר לו לשאת. הכלל התכונתי שמחליף מניית
#: צירופים: כל שדה יעד שאינו של הסוג שנבחר הוא זיהום, ונדחה. מי שמוסיף
#: סוג רביעי בעתיד מוסיף שורה כאן, ולא צריך לזכור לעדכן רשימת "צירופים
#: אסורים" בשום מקום אחר.
TARGET_FIELDS: Dict[str, Tuple[str, ...]] = {
    "file": ("file_id", "scope_id", "file_name"),
    "board": ("board_id",),
    "repo": ("repo_name", "repo_path"),
}

#: שדות הזיהוי שקובעים לאיזה סוג הפתק שייך. ``file``/``board`` נקבעים
#: בשדה אחד; ``repo`` דורש את **שני** חצאיו יחד — ``repo_name`` בלי
#: ``repo_path`` (או להפך) הוא יעד חצוי, לא יעד.
_TARGET_IDENTITY: Dict[str, Tuple[str, ...]] = {
    "file": ("file_id",),
    "board": ("board_id",),
    "repo": ("repo_name", "repo_path"),
}


def _target_kind(doc: Mapping[str, Any]) -> str:
    """סוג היעד של מסמך — או :class:`NoteTargetError` אם אינו בדיוק אחד.

    ``repo`` דורש את שני חצאיו: חצי אחד בלבד הוא ``repo_target_incomplete``,
    ולא "אין יעד" סתמי — כדי שהשגיאה תסביר למה.
    """
    rname = bool(_clean(doc.get("repo_name")))
    rpath = bool(_clean(doc.get("repo_path")))
    if rname != rpath:
        raise NoteTargetError("repo_target_incomplete")

    present = []
    for kind, identity in _TARGET_IDENTITY.items():
        if all(_clean(doc.get(f)) for f in identity):
            present.append(kind)

    if len(present) > 1:
        raise NoteTargetError("note_target_ambiguous")
    if not present:
        raise NoteTargetError("note_target_missing")
    return present[0]


def validate_note_target(doc: Mapping[str, Any]) -> None:
    """מוודא שבמסמך מלא בדיוק יעד אחד — קובץ, לוח, או קובץ בריפו.

    :raises NoteTargetError: אם יש יותר מיעד אחד, אף אחד, או יעד ריפו חצוי.
    """
    _target_kind(doc)


def build_note_target(
    *,
    file_id: Any = None,
    board_id: Any = None,
    scope_id: Optional[str] = None,
    file_name: Optional[str] = None,
    repo_name: Any = None,
    repo_path: Any = None,
) -> Dict[str, Any]:
    """שדות היעד למסמך פתק חדש — אחרי ולידציה, לא לפניה.

    ``scope_id``/``file_name`` הם מושגים של קובץ, ו-``repo_name``/``repo_path``
    של ריפו. ערבוב ביניהם או עם ``board_id`` הוא באג של הקורא ולא קלט שיש
    להשלים בשקט, ולכן נדחה — לא כמניית צירופים אלא ככלל: כל שדה שאינו של
    הסוג שנבחר פוסל.

    ``repo_path`` עובר :func:`normalize_repo_path` **כאן, בכתיבה** — אותה
    פונקציה שרצה בקריאה, כך ששני הקצוות מתכנסים לאותה צורה.
    """
    fid = _clean(file_id)
    bid = _clean(board_id)
    rname = _clean(repo_name)
    rpath = normalize_repo_path(repo_path)

    # כל שדה שסופק נכנס לפי נוכחותו-שלו — לא מקונן תחת שדה אחר. כך פתק
    # לוח שקיבל ``scope_id`` נושא אותו בפועל, ובדיקת הזיהום שלמטה תפסול
    # אותו — במקום שהוא יישמט בשקט וההפרה תיעלם.
    target: Dict[str, Any] = {}
    if fid:
        target["file_id"] = fid
    if bid:
        target["board_id"] = bid
    if rname or rpath:
        target["repo_name"] = rname
        target["repo_path"] = rpath
    if scope_id:
        target["scope_id"] = scope_id
    if file_name:
        target["file_name"] = file_name

    # כלל הזיהום התכונתי: אחרי שידוע איזה סוג נבחר, כל שדה ב-``target``
    # שאינו ברשימת הסוג פוסל. ``target`` מורכב אך ורק משדות יעד (התוכן,
    # המיקום וכו' מתווספים מאוחר יותר בראוט), ולכן די בסריקה אחת שלו מול
    # ה-allowlist — בלי לעבור על שאר הסוגים, שממילא כל שדותיהם זרים.
    kind = _target_kind(target)
    allowed = set(TARGET_FIELDS[kind])
    for field in target:
        if field not in allowed:
            raise NoteTargetError(f"{kind}_note_cannot_carry_{field}")

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


def repo_notes_filter(user_id: int, repo_name: Any, repo_path: Any) -> Dict[str, Any]:
    """שאילתת פתקים של קובץ בריפו — לפי הזוג ``(repo_name, repo_path)``.

    **הנורמליזציה כאן היא אותה פונקציה שרצה בכתיבה** (ראו
    :func:`normalize_repo_path`). זה לא כפל: זה בדיוק מה שמונע את הכשל
    השקט שבו פתק נכתב בצורה אחת ומחופש בצורה אחרת, השאילתה רצה, מחזירה
    אפס, ולא זורקת כלום.

    **אי-דליפה, בשלושה כיוונים:** לפתק ריפו אין ``file_id``, אין ``scope_id``
    ואין ``board_id`` — ולכן :func:`file_notes_filter` ו-
    :func:`board_notes_filter` אינם תופסים אותו. לפתק קובץ/לוח אין
    ``repo_name``, ולכן הוא אינו נתפס כאן. אין דליפה, ולא נדרש שומר —
    בדיוק כמו שנקבע בין קובץ ללוח. מכוסה בטסט.

    **אין ``ref``/ענף במפתח בכוונה.** פתק שנרשם כשהיית על ``main`` חייב
    להופיע גם כשאתה מסתכל על ענף PR — אחרת הוא נעלם בדיוק ברגע שהוא הכי
    נחוץ. המלכודת שייכת לקובץ, לא לענף.
    """
    return {
        "user_id": int(user_id),
        "repo_name": _clean(repo_name),
        "repo_path": normalize_repo_path(repo_path),
    }


def note_search_filter(
    user_id: int, needle: Any, *, search_content: bool = False
) -> Dict[str, Any]:
    """שאילתת חיפוש פתקים, חוצת שלושת היעדים.

    האח הרביעי של :func:`file_notes_filter`, :func:`board_notes_filter`
    ו-:func:`repo_notes_filter` — ומאותה סיבה שהם כאן: שאילתה שמורכבת
    בכל צרכן בנפרד היא שאילתה שתיפרד.

    **ה-escaping הוא חלק מהחוזה, לא פרט מימוש.** בלעדיו חיפוש
    ``"config.py"`` היה תופס גם ``configXpy``, ושאילתה כמו ``"a("`` הייתה
    מפילה את מונגו בשגיאת פרסור. יש בריפו מקומות ששכחו זאת; הם אינם
    תקדים. הריכוז כאן מבטיח שראוט ווב עתידי לא יגזור החלטת escaping אחרת.
    הוא חל על **שני** הפרדיקטים, לא רק על הראשון.

    ``search_content`` **כבוי כברירת מחדל, ובכוונה.** חיפוש השם נשען על
    ``user_title_idx`` ומחזיר שורות בלי לגעת בגוף הפתק. הרחבתו לתוכן
    מוסיפה פרדיקט שאין ולא יהיה עליו אינדקס — מונגו מתיר **אינדקס טקסט
    אחד לכל אוסף**, וזו החלטה חד-כיוונית שלא נשרפת כאן. מה שכן מגן:
    ``user_id`` נשאר פרדיקט ראשון, ולכן הסריקה חסומה למכסת המשתמש
    (:data:`MAX_NOTES_PER_USER`) ואינה COLLSCAN.

    **פתק בלי שם הוא הסיבה שהדגל קיים.** רוב הפתקים בפועל נכתבים בלי
    כותרת, ולכן היו בלתי-נראים לחיפוש לחלוטין. ``$exists`` על ``title``
    אינו נחוץ לנכונות (רג'קס לעולם אינו תופס שדה חסר) אבל מצהיר על
    הכוונה — ובענף התוכן הוא **אסור**, כי הוא היה מחזיר בדיוק את הפתקים
    שהדגל בא למצוא אל מחוץ לתוצאה.

    .. note::
       פתקי legacy נשמרו עם ישויות HTML (``&quot;`` במקום ``"``);
       ``_sanitize`` מנקה רק בכתיבה חדשה. חיפוש תוכן על תו כזה יפספס
       אותם. זו מגבלת נתונים היסטוריים, לא של השאילתה.
    """
    pattern = {"$regex": re.escape(str(needle or "")), "$options": "i"}
    title_clause = {"title": {"$exists": True, **pattern}}
    if not search_content:
        return {"user_id": int(user_id), **title_clause}
    return {
        "user_id": int(user_id),
        "$or": [title_clause, {"content": dict(pattern)}],
    }


def title_search_filter(user_id: int, needle: Any) -> Dict[str, Any]:
    """חיפוש **לפי שם בלבד** — מעטפת דקה של :func:`note_search_filter`.

    שמורה כדי שהקוראים הקיימים לא ייגעו, ומממשת דרך המשותף כדי ששני
    בוני-שאילתה לא ייווצרו לאותה שאלה.
    """
    return note_search_filter(user_id, needle, search_content=False)


def repo_note_paths_pipeline(user_id: int, repo_name: Any) -> List[Dict[str, Any]]:
    """הנתיבים בריפו שיש עליהם פתקים, עם ספירה לכל נתיב.

    **מפת גילוי, לא תוכן.** :func:`repo_notes_filter` דורש שהקורא כבר ידע
    את הנתיב המדויק — כלומר צריך לדעת איפה הפתק כדי למצוא אותו. הצינור
    הזה סוגר את הלולאה: הוא מחזיר את הנתיבים בלבד, ומשם קוראים לכלי
    הרשימה על נתיב ספציפי.

    **אגרגציה ולא ``distinct`` בכוונה.** אותה מחלקת עלות, אבל הספירה
    מגיעה חינם והופכת את המפה לשימושית — נתיב עם 12 פתקים ונתיב עם אחד
    אינם אותו דבר לקורא.

    ``$match`` נושא ``user_id`` **וגם** ``repo_name``, שהם בדיוק תחילית
    ``user_repo_idx`` (``user_id, repo_name, repo_path``) — ולכן אין כאן
    צורך באינדקס חדש. הצינור **אינו נוגע ב-``content``**: הוא מקבץ לפי
    נתיב וסופר, כלומר עלותו מנותקת מגודל הפתקים.
    """
    return [
        {"$match": {"user_id": int(user_id), "repo_name": _clean(repo_name)}},
        {"$group": {"_id": "$repo_path", "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]


#: לכל סוג יעד — שדות הזיהוי שמאפשרים **לחזור אל הפתק**.
#:
#: **אלה בדיוק הארגומנטים של כלי הרשימה המתאים**, וזו האינווריאנטה שהופכת
#: תוצאת חיפוש לשימושית: ``file_name`` נכנס ל-``list_notes``, ``board_id``
#: ל-``list_board_notes``, והזוג ל-``list_repo_notes``.
#:
#: הטבלה נפרדת מ-:data:`TARGET_FIELDS` בכוונה. שם ``file`` כולל גם
#: ``scope_id``, שהוא hash פנימי של שם קובץ — חסר תועלת לקורא, ואסור
#: שיזלוג ככה כאילו הוא מזהה ניווט.
NOTE_TARGET_REF_FIELDS: Dict[str, Tuple[str, ...]] = {
    "file": ("file_name", "file_id"),
    "board": ("board_id",),
    "repo": ("repo_name", "repo_path"),
}


def note_target_ref(doc: Mapping[str, Any]) -> Dict[str, Any]:
    """זהות היעד של פתק, בצורה שאפשר לנווט לפיה.

    מחזיר ``{"target": <סוג>, <שדות הזיהוי>}``.

    **לעולם אינו זורק.** מסמכים שנוצרו לפני :func:`build_note_target`
    עשויים לא לשאת יעד חוקי כלל, ושורה פגומה אחת אינה אמורה להרוג תוצאת
    חיפוש שלמה. במקרה כזה מוחזר ``"unknown"`` — הצהרה כנה על מה שידוע,
    ולא המצאת יעד.
    """
    try:
        kind = _target_kind(doc)
    except NoteTargetError:
        return {"target": "unknown"}

    ref: Dict[str, Any] = {"target": kind}
    for field in NOTE_TARGET_REF_FIELDS.get(kind, ()):
        value = _clean(doc.get(field))
        if value:
            ref[field] = value
    return ref


def mirrored_repo_names(db: Any) -> Optional[set]:
    """שמות הריפואים הממוררים, או ``None`` אם השאילתה נכשלה.

    ``None`` אינו "אין ריפואים": הוא נבדל ממנו בכוונה, כי קריאה שנכשלה
    אינה ראיה שהריפו נעלם. מי שקורא מסמן יתומים רק כשיש לו רשימה אמיתית.
    """
    try:
        names = db.repo_metadata.distinct('repo_name')
    except Exception:
        return None
    if not isinstance(names, (list, tuple, set)):
        return None
    return {str(n) for n in names if n}


def repo_file_exists(db: Any, repo_name: str, repo_path: str) -> Optional[bool]:
    """האם הנתיב קיים בעץ הריפו הממורר, או ``None`` בכשל שאילתה.

    ההשוואה היא מול ``repo_files``, שנתיביו נשמרים בצורת git הגולמית —
    ולכן ``repo_path`` שהגיע לכאן כבר עבר :func:`normalize_repo_path`,
    שמתכנס בדיוק לאותה צורה. בלי ההתכנסות הזו קובץ קיים היה מסומן כמיותם.

    **שם השדה הוא ``path``, לא ``repo_path``** — כך ``services/code_indexer``
    כותב אותו. מי ש"יסדר" את זה לשם אחיד יגרום לכל קובץ להיראות מיותם,
    ולכל יצירת פתק להיחסם, בלי שום שגיאה. מכוסה בטסט.

    **מקבל את ידית המסד ולא אוסף**, בשונה מ-:func:`title_is_taken`: הידע
    שמרוכז כאן הוא המיפוי מיעד פתק אל המניפסט, וזה שתי עובדות — האוסף
    **וגם** שם השדה. העברת אוסף הייתה משאירה את השנייה משוכפלת אצל כל קורא.
    """
    try:
        doc = db.repo_files.find_one({'repo_name': repo_name, 'path': repo_path}, {'_id': 1})
    except Exception:
        return None
    return doc is not None


def repo_title_is_taken(
    coll: Any,
    *,
    user_id: Any,
    repo_name: Any,
    repo_path: Any,
    title: str,
    exclude_id: Any = None,
) -> bool:
    """האם השם כבר תפוס על אותו קובץ בריפו — אח תאום ל-:func:`title_is_taken`.

    אותו תפקיד ואותה משמעת, כולל הכלל שקובע את הכיוון בכשל: **שאילתה
    שנכשלה אינה ראיה שהשם פנוי**, ולכן מחזירים ``True``.
    """
    if not title:
        return False
    query: Dict[str, Any] = {
        "user_id": user_id,
        "repo_name": _clean(repo_name),
        "repo_path": normalize_repo_path(repo_path),
        "title": title,
    }
    if exclude_id is not None:
        query["_id"] = {"$ne": exclude_id}
    try:
        return coll.find_one(query, {"_id": 1}) is not None
    except Exception:
        return True


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
