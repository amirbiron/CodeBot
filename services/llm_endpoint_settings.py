"""הגדרות של נקודת קצה למודל שפה תואם OpenAI — מפתח, כתובת ומודל — מתוך משתני סביבה עם קידומת.

שני צרכנים, וכל אחד עם קידומת משלו: היועץ בבוט (``ADVISOR_``, ``services/advisor_service.py``) והחילוץ
בחיפוש בתיעוד (``DOCS_EXTRACT_``, ``services/docs_extract_service.py``). ההגדרות נפרדות בכוונה, כדי שהחלפת
מודל באחד לא תשנה את השני וכדי שהצריכה של כל אחד תיספר לחוד. הכללים על הערכים משותפים, ולכן הם כתובים כאן
פעם אחת: שני עותקים שלהם היו מתרחקים זה מזה עם הזמן (R6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Mapping, Optional, Tuple
from urllib.parse import urlsplit


#: הסכמות שכתובת של מודל השפה (``<prefix>BASE_URL``) יכולה להתחיל בהן.
BASE_URL_SCHEMES = ("https", "http")


def _is_full_url(value: str, schemes: Tuple[str, ...]) -> bool:
    """האם ``value`` הוא כתובת עם אחת מ-``schemes`` ועם שרת.

    ``urlsplit`` זורק ``ValueError`` על כתובת שהשרת בה בסוגריים מרובעים פגומים, כמו ``https://[::1``
    (``Invalid IPv6 URL``; נבדק ב-Python 3.13) — וזו בדיוק כתובת לא תקינה, ולא חריגה שעולה הלאה: מי שקורא את
    ההגדרות מצפה לרשימת שגיאות, ותבנית עמוד הקבצים קוראת אותן בכל רינדור.
    """
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    return parts.scheme in schemes and bool(parts.netloc)


def url_error(name: str, value: str, schemes: Tuple[str, ...]) -> Optional[str]:
    """``None`` כשהערך של ``name`` הוא כתובת מלאה באחת מ-``schemes``; אחרת השגיאה, שנוקבת בכל הסכמות.

    ההודעה נבנית מאותן ``schemes`` שהבדיקה משתמשת בהן, כדי שלא תוכל לומר משהו אחר ממה שנבדק: עד 28.11.2026
    ההודעות היו מוקלדות, והן הזכירו רק ``https://`` בזמן שגם ``http://`` עבר.
    """
    if _is_full_url(value, schemes):
        return None
    options = [f"ב-{scheme}://" for scheme in schemes]
    allowed = options[0] if len(options) == 1 else ", ".join(options[:-1]) + " או " + options[-1]
    return f"{name} חייב להיות כתובת מלאה שמתחילה {allowed}"


@dataclass(frozen=True)
class LlmEndpoint:
    api_key: str
    base_url: str
    model: str


def load_endpoint(prefix: str, environ: Mapping[str, str]) -> Tuple[Optional[LlmEndpoint], List[str]]:
    """``<prefix>API_KEY``, ``<prefix>BASE_URL`` ו-``<prefix>MODEL`` מתוך ``environ``.

    ``(נקודת קצה, [])`` — תקין. ``(None, [])`` — אף אחד מהשלושה לא הוגדר. ``(None, שגיאות)`` — הוגדרו
    חלקית או בערכים פגומים. השגיאות נוקבות בשם המשתנה ובכלל, ולא בערך, כך שמותר להציג אותן לאדמין.
    """
    key_name, url_name, model_name = f"{prefix}API_KEY", f"{prefix}BASE_URL", f"{prefix}MODEL"
    api_key = environ.get(key_name, "").strip()
    base_url = environ.get(url_name, "").strip()
    model = environ.get(model_name, "").strip()

    if not (api_key or base_url or model):
        return None, []

    errors: List[str] = []
    if not api_key:
        errors.append(f"{key_name} לא מוגדר")
    # המפתח נשלח בכותרת Authorization, וכותרת HTTP היא ASCII. תו נסתר שנכנס
    # בהעתקה מדפדפן היה מפיל כל קריאה בצד הלקוח, ולא בעלייה.
    elif not api_key.isascii() or any(ch.isspace() for ch in api_key):
        errors.append(f"{key_name} חייב להיות ASCII בלי רווחים")
    # הכתובת היא חובה: בלי ``base_url`` מפורש ה-SDK קורא בעצמו את ``OPENAI_BASE_URL`` מהסביבה
    # (openai 3.36.1, ``openai/_client.py``).
    base_url_error = url_error(url_name, base_url, BASE_URL_SCHEMES)
    if base_url_error:
        errors.append(base_url_error)
    if not model:
        errors.append(f"{model_name} לא מוגדר")
    if errors:
        return None, errors
    return LlmEndpoint(api_key=api_key, base_url=base_url, model=model), []
