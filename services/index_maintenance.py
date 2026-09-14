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
