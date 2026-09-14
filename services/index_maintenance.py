"""עזרי תחזוקת אינדקסים, משותפים לשני ה-endpointים של ``maintenance_cleanup``.

הגדרה אחת ולא שתיים: ה-endpoint ב-``webapp/app.py`` (Flask) וזה ב-
``services/webserver.py`` (aiohttp) הם מראה זה של זה, וכל לוגיקה שמועתקת
ביניהם מתפצלת בהמשך. בדיוק כך נולדה הסתירה שאישיו #3331 מתאר.

המודול עצמאי בכוונה — בלי ייבוא של ``database`` ובלי תופעות לוואי בזמן טעינה.
‏``database/__init__.py`` בונה ``DatabaseManager()`` בזמן הייבוא, כלומר מתחבר
למונגו; מודול עזר שנטען משני שירותים אינו יכול לגרור את זה.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

#: מפתחות שמונגו מחזירה ב-``index_information`` ואינם אופציות ליצירה מחדש.
#: ``v`` הוא גרסת פורמט האינדקס ו-``ns`` הוא שם ה-namespace (בגרסאות ישנות);
#: העברתם ל-``create_index`` היא שגיאה, ולא שחזור.
_NON_OPTION_KEYS = frozenset({"key", "v", "ns"})


def index_creation_options(meta: Dict[str, Any]) -> Tuple[List[Tuple[str, Any]], Dict[str, Any]]:
    """מפרק רשומת ``index_information`` למה ש-``create_index`` מקבל.

    מחזיר ``(keys, options)``. ``keys`` הוא רשימת הזוגות כפי שמונגו מחזירה
    אותה, ו-``options`` הוא כל השאר — ``expireAfterSeconds``, ``unique``,
    ``partialFilterExpression``, ``sparse`` — בלי מטא-דאטה שאינו אופציה.
    """
    keys = [(str(field), direction) for field, direction in list(meta.get("key") or [])]
    options = {str(k): v for k, v in meta.items() if str(k) not in _NON_OPTION_KEYS}
    return keys, options


def drop_indexes_recording(coll: Any, index_names: List[str]) -> Tuple[List[str], List[Tuple[str, Dict[str, Any]]]]:
    """מפיל אינדקסים, ושומר את ההגדרה של כל אחד לפני ההפלה.

    מחזיר ``(מה שהופל, מה שאפשר להחזיר)``. ההגדרות נקראות **פעם אחת** לפני
    הלולאה, כי אחרי ההפלה הראשונה הן כבר לא שם.

    בלי הרישום הזה, הפלה שקדמה ליצירה שנכשלה משאירה את האוסף עם פחות משהיה לו
    לפני הקריאה. זה חוזר בכל מקום שבו הסדר הוא drop ואז create, ולכן הוא יושב
    כאן פעם אחת ולא בשלושה עותקים.
    """
    try:
        info = coll.index_information() or {}
    except Exception:
        info = {}

    dropped: List[str] = []
    recorded: List[Tuple[str, Dict[str, Any]]] = []
    for name in index_names or []:
        meta = info.get(name) if isinstance(info, dict) else None
        try:
            coll.drop_index(name)
        except Exception:
            continue
        dropped.append(str(name))
        if isinstance(meta, dict):
            recorded.append((str(name), dict(meta)))
    return dropped, recorded


def restore_indexes(coll: Any, recorded: List[Tuple[str, Dict[str, Any]]]) -> Dict[str, str]:
    """מחזיר את כל מה ש-``drop_indexes_recording`` הפיל. מחזיר מצב לכל אחד."""
    return {name: restore_dropped_index(coll, name, meta) for name, meta in (recorded or [])}


def restore_dropped_index(coll: Any, index_name: str, meta: Optional[Dict[str, Any]]) -> str:
    """מחזיר אינדקס שהופל, אחרי שהיצירה שבאה במקומו נכשלה.

    ``_ensure_ttl_index`` מפיל קודם ויוצר אחר כך. אם היצירה נכשלת, האוסף נשאר
    **בלי אינדקס TTL בכלל** — מצב גרוע מזה שלפני הקריאה, ובלי שאף חריגה מדווחת
    עליו: הכשל חוזר כשדה ``status`` בתוך JSON שמישהו צריך לקרוא.

    מחזיר מחרוזת מצב לתשובת ה-endpoint: ``not_needed`` כשלא הופל דבר,
    ``restored`` כשהאינדקס הישן חזר, או ``failed: <סיבה>``. **המחרוזת נגזרת
    מהניסיון עצמו** — היא אינה הבטחה שהאינדקס קיים; מי שרוצה ודאות קורא את
    ``index_information`` אחרי הקריאה.
    """
    if not isinstance(meta, dict) or not meta.get("key"):
        return "not_needed"
    try:
        keys, options = index_creation_options(meta)
        if not keys:
            return "not_needed"
        options.pop("name", None)
        coll.create_index(keys, name=str(index_name), **options)
        return "restored"
    except Exception as e:
        return f"failed: {e}"
