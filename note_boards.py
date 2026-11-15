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
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from webapp.file_name_display import has_hebrew

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


def board_order(doc: Dict[str, Any]) -> int:
    """``order`` של מסמך לוח כמספר שלם — סדר היצירה, שבמיון (:func:`_board_sort_key`) שובר שוויון בין לוחות
    באותו שם.

    **כל מי שקורא את השדה ממסמך במסד עובר כאן**: המיון, התשובה של ``webapp/note_boards_api`` (``_board_response``)
    והמקסימום שממנו נגזר ``order`` של לוח חדש (``create_board``), והייצוא והשחזור ב-
    ``services/personal_backup_service``. ההמרה הייתה כתובה בכל אחד מהם בנפרד, ובחלק מהם כ-``int(...)`` חשוף.

    הכותבים כותבים תמיד מספר שלם (:func:`ensure_default_board`, ``create_board``, ו-``_restore_note_boards`` בשחזור),
    ולכן ערך אחר מגיע רק מעריכה ביד במסד. ערך כזה — מחרוזת שאינה מספר, NaN, אינסוף, רשימה — הוא ``0``, ולא
    חריגה: ``int`` זורק עליו ``ValueError``, ``OverflowError`` או ``TypeError``, ועד היום החריגה הזו הפילה את
    רשימת הלוחות כולה, וב-``/boards`` זה 500 בלי אף לוח, גם כשרק מסמך אחד פגום.
    """
    try:
        return int(doc.get("order") or 0)
    except (TypeError, ValueError, OverflowError):
        # בלי לוג, בכוונה: הפונקציה רצה על כל לוח בכל טעינה של הרשימה, ולוג היה חוזר בכל טעינה עד שמישהו מתקן
        # את המסמך ביד. ו-0 אינו מאבד דבר: התפקיד היחיד של השדה הוא סדר בין לוחות באותו שם, ולוח עם 0 פשוט
        # מוצג ראשון ביניהם.
        return 0


#: אות סופית ← אותה אות בצורתה הרגילה. בסדר הא'-ב' ‏ך היא כ', ‏ם היא מ' וכן הלאה; בטבלת יוניקוד כל
#: סופית היא תו נפרד שיושב **לפני** הצורה הרגילה שלה (‏ך U+05DA, ‏כ U+05DB). בלי ההמרה ההשוואה נעצרת
#: על הסופית ולא ממשיכה לתו שאחריה: "אםב" היה קודם ל"אמא", כשלפי הא'-ב' ההכרעה היא בין ה-ב' לבין ה-א'.
_HEBREW_FINAL_TO_REGULAR = str.maketrans("ךםןףץ", "כמנפצ")


def _board_sort_key(doc: Dict[str, Any]) -> Tuple[Any, ...]:
    """מפתח המיון של לוח ב-:func:`list_boards` — הסדר שבו הלוחות מוצגים בכל מקום שקורא לה.

    1. **לוח ברירת המחדל ראשון** (``is_default``), תמיד — הוא הלוח הראשי: היחיד שאי אפשר למחוק, והיעד של
       הפתקים מלוח שנמחק (שניהם ב-``webapp/note_boards_api.delete_board``).
    2. **הקבוצה, לפי האות הראשונה בשם**: עברית (:func:`webapp.file_name_display.has_hebrew`), אחריה כל
       אות אחרת, ובסוף שם שאין בו אות בכלל. "אות" היא מה ש-``str.isalpha`` מקבל — הקטגוריות ``Lm``,
       ``Lt``, ``Lu``, ``Ll`` ו-``Lo`` ביוניקוד (התיעוד של ``str.isalpha`` ב-Python 3.11) — ולכן אימוג'י,
       ספרה או סימן בתחילת השם אינם נספרים: "📌 משימות" שייך לעברית, וממוין לפי ה-מ'. ומספיקה אות עברית
       אחת בהתחלה: ``מCLAUDE.md`` שייך לעברית גם כשכל השאר באנגלית.
    3. **השם, מהאות הראשונה והלאה, בהשוואה בסיסית**: בלי הבדל בין אותיות גדולות לקטנות, בלי ניקוד
       ואקסנטים (פירוק ``NFKD`` והשמטת תווי צירוף, קטגוריה ``M``), ואות סופית כמו הרגילה
       (:data:`_HEBREW_FINAL_TO_REGULAR`). בלי ``casefold`` כל האותיות הגדולות היו קודמות לקטנות,
       ו-``amir`` היה נופל אחרי ``To CC``.
    4. **שוברי שוויון**: השם המלא כפי שהוא, אחריו ``order`` (סדר היצירה, דרך :func:`board_order`), ואחריו
       המזהה — כך שגם שני לוחות באותו שם בדיוק מוצגים תמיד באותו סדר.

    הקירוב של שלב 3 — ‏NFKD, השמטת ``M`` ו-``casefold`` — הוא אותו קירוב שעושה ``_match_key`` ב-
    ``services/docs_index_service.py``, אבל **בכוונה אינו נשען עליו**: שם הבעלים הוא הדפדפן (מה ש-Chromium
    משווה כשהוא קופץ לטקסט בעמוד), וכל התאמה שלו לדפדפן הייתה משנה כאן את סדר הלוחות.
    """
    name = str(doc.get("name") or "")
    first_letter = next((index for index, char in enumerate(name) if char.isalpha()), None)
    if first_letter is None:
        group, text = 2, name
    else:
        group, text = (0 if has_hebrew(name[first_letter]) else 1), name[first_letter:]
    decomposed = unicodedata.normalize("NFKD", text)
    base = "".join(char for char in decomposed if not unicodedata.category(char).startswith("M"))
    primary = base.casefold().translate(_HEBREW_FINAL_TO_REGULAR)
    return (
        0 if doc.get("is_default") else 1,
        group,
        primary,
        name,
        board_order(doc),
        str(doc.get("_id") or ""),
    )


def list_boards(db: Any, user_id: int) -> List[Dict[str, Any]]:
    """לוחות המשתמש בסדר התצוגה — :func:`_board_sort_key`: ברירת המחדל ראשונה, ואחריה לפי השם."""
    coll = _boards_coll(db)
    if coll is None:
        return []
    cursor = coll.find({"user_id": int(user_id)})
    docs = [d for d in (list(cursor) if cursor is not None else []) if isinstance(d, dict)]
    docs.sort(key=_board_sort_key)
    return docs


def board_names_by_id(coll: Any, user_id: int, board_ids: Iterable[Any]) -> Dict[str, str]:
    """שמות הלוחות של המשתמש לפי מזהה — שאילתה אחת לכל המזהים, בהיטלה של השם בלבד.

    בשביל מי שמציג פתקים מכמה לוחות ורוצה לכתוב ליד כל אחד באיזה לוח הוא יושב: כרטיס
    "פתקים אחרונים" בדשבורד (``webapp/app._build_notes_snapshot``) ושורת התגובות שממתינות
    לסוכן בפריימר של ה-MCP (``ProductionBackend.pending_note_threads``). עד נובמבר 2026
    השליפה הייתה כתובה בתוך הפריימר, והדשבורד לא הכיר שמות לוחות בכלל.

    * ``coll`` הוא אוסף ``note_boards`` עצמו, ולא ``db``: לשני הקוראים יש גישה אחרת למסד.
    * המפתח הוא המזהה כמחרוזת, כמו ``board_id`` בפתק. לוח שאינו של ``user_id``, או שאינו
      קיים, חסר במפה, ושם ריק נשאר מחרוזת ריקה — הקורא מחליט מה מציגים במקומו.
    * מזהה שאינו ``ObjectId`` מדולג. על מחרוזת, ``ObjectId`` זורק רק ``InvalidId`` (נבדק
      במקור של pymongo 4.15.3, ``bson/objectid.py``, ``__validate``), ולכן רק אותו תופסים
      כאן. כשאין אף מזהה תקין, אין שאילתה.
    * **כשל של המסד עולה לקורא** (``PyMongoError``) ואינו נבלע כאן: מפה ריקה הייתה נראית
      בדיוק כמו "אין לוחות כאלה", וכל קורא רושם את הכשל בלוג שלו.
    """
    from bson import ObjectId  # lazy heavy import
    from bson.errors import InvalidId

    oids: List[Any] = []
    seen = set()
    for raw in board_ids or ():
        text = str(raw or "")
        if not text or text in seen:
            continue
        seen.add(text)
        try:
            oids.append(ObjectId(text))
        except InvalidId:
            continue
    if not oids:
        return {}
    names: Dict[str, str] = {}
    for board in coll.find({"_id": {"$in": oids}, "user_id": int(user_id)}, {"name": 1}):
        names[str(board.get("_id"))] = str(board.get("name") or "")
    return names


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
    # היעד עצמו חייב להיחשב תקין, אחרת פתק שכבר יושב על לוח ברירת
    # המחדל ייספר כיתום — וה-update_many "יעביר" אותו לאותו מקום,
    # כך שהספירה החוזרת לעולם לא תרד לאפס והדיווח יהיה שגוי.
    valid = [str(b) for b in (known_board_ids or []) if str(b)]
    if str(default_board_id) not in valid:
        valid.append(str(default_board_id))
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
        # בלי ``updated_at``: מעבר בין לוחות אינו עריכה של הפתק (``sticky_notes_target.NOTE_EDIT_FIELDS``).
        coll.update_many(
            orphan_query,
            {"$set": {"board_id": str(default_board_id)}},
        )
    except Exception as exc:
        logger.warning("orphan notes reattach failed: %s", exc)
    try:
        after = coll.count_documents(orphan_query)
    except Exception:
        return 0
    return max(0, before - after)
