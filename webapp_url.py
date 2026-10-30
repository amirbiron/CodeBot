"""כתובת הבסיס הציבורית של ה-WebApp — המקום היחיד שקורא את ``WEBAPP_URL``.

הבוט, ה-WebApp, שירות ה-MCP וההתראות בונים קישורים ל-WebApp. עד אוקטובר 2026 כל אחד חישב את הכתובת בעצמו, משלושה משתנים (``WEBAPP_URL``, ``PUBLIC_BASE_URL``, ``PUBLIC_URL``) ובסדרי עדיפויות שונים, ובשישה מקומות הכתובת של השירות באורגון הייתה כתובה בקוד כברירת מחדל. שירות שלא קיבל את המשתנה לא נכשל: הוא המשיך להפנות לשם בשקט, וכשהשירות יעבור כתובת אלה קישורים מתים בלי שום שגיאה.

עכשיו יש משתנה אחד וקורא אחד, ו**אין ברירת מחדל**. כשהמשתנה חסר או פגום, :func:`webapp_base_url` מחזירה ``None`` וכל צרכן מוותר על הקישור. ושזה לא יעבור בשקט: כל שירות כותב בעלייה את :func:`log_webapp_url_status` (ERROR כשאין כתובת תקינה), ובדיקות התקינות מציגות את המצב.

**הפורמט:** ``https://`` ואחריו שם מארח ופורט אופציונלי — בלי נתיב, בלי query ו-fragment, בלי משתמש וסיסמה בכתובת, ובלי ``/`` בסוף. ערך אחר הוא "פגום" ומטופל כמו חסר: קישור שנבנה מהכתובת צריך לעבוד כמו שהיא, ולא אחרי ניחוש של תיקון.

המודול טהור: בלי ייבוא של שירות ובלי פעולה בזמן ייבוא. הערך נקרא מהסביבה בכל קריאה, ולכן טסט שמגדיר או מוחק את המשתנה רואה את השינוי מיד.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlsplit

__all__ = [
    "STATE_CONFIGURED",
    "STATE_MISSING",
    "STATE_INVALID",
    "WebappUrlStatus",
    "webapp_url_status",
    "webapp_base_url",
    "webapp_link",
    "webapp_base_url_for_request",
    "log_webapp_url_status",
]

STATE_CONFIGURED = "configured"
STATE_MISSING = "missing"
STATE_INVALID = "invalid"

_SCHEME_PREFIX = "https://"

#: המארח והפורט, כפי ש-``urlsplit`` מחזיר אותם ב-``netloc``: אותיות לטיניות, ספרות, נקודות ומקפים, ואחריהם ``:`` ופורט אופציונלי.
#: הביטוי דוחה ``@`` (משתמש וסיסמה בכתובת), סוגריים של IPv6 ורווחים — ``urlsplit`` מקבל את כולם כ-netloc בלי שגיאה (נמדד ב-Python 3.11, הגרסה של ה-Dockerfile, וב-3.13).
_NETLOC_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?(?::[0-9]{1,5})?")


@dataclass(frozen=True)
class WebappUrlStatus:
    """מצב ``WEBAPP_URL``: ``state`` הוא אחד מ-``STATE_*``; ``url`` קיים רק ב-``STATE_CONFIGURED``; ``problem`` קיים רק ב-``STATE_INVALID``.

    ``problem`` הוא קוד קצר (``not_https``, ``bad_host``, ``bad_port``, ``trailing_slash``, ``has_path``) ולא הערך עצמו: ערך פגום יכול לשאת משתמש וסיסמה (``https://user:pass@host``), ולכן הוא אינו נכנס ללוג ולא לבדיקת התקינות.
    """

    state: str
    url: Optional[str] = None
    problem: Optional[str] = None


def _invalid(problem: str) -> WebappUrlStatus:
    return WebappUrlStatus(state=STATE_INVALID, problem=problem)


def webapp_url_status() -> WebappUrlStatus:
    """קורא את ``WEBAPP_URL`` ומחזיר את המצב שלו. לא זורק."""
    # שם המשתנה כמחרוזת ולא כקבוע: ``scripts/audit_config_definitions.py`` מזהה קריאה רק לפי ליטרל, ועליו נשען
    # ``test_webapp_url_has_one_reader`` — בדיקה שזה הקורא היחיד. קריאה דרך קבוע לא נראית שם בכלל.
    raw = os.environ.get("WEBAPP_URL")
    value = raw.strip() if isinstance(raw, str) else ""
    if not value:
        return WebappUrlStatus(state=STATE_MISSING)
    # בדיקה תלוית רישיות: ``urlsplit`` מנמיך את ה-scheme, ואז ``HTTPS://host`` היה עובר כאן ונכשל רק בהשוואה בסוף, עם קוד שגוי.
    if not value.startswith(_SCHEME_PREFIX):
        return _invalid("not_https")
    try:
        parts = urlsplit(value)
    except ValueError:
        # למשל סוגר מרובע שלא נסגר (``https://[x``) — "Invalid IPv6 URL".
        return _invalid("bad_host")
    if not _NETLOC_RE.fullmatch(parts.netloc):
        return _invalid("bad_host")
    try:
        port = parts.port
    except ValueError:
        # פורט מחוץ לטווח 0-65535 (הביטוי כבר מבטיח ספרות בלבד).
        return _invalid("bad_port")
    if port == 0:
        return _invalid("bad_port")
    expected = _SCHEME_PREFIX + parts.netloc
    if value != expected:
        if value == expected + "/":
            return _invalid("trailing_slash")
        # נתיב, query או fragment — כולל ``?`` או ``#`` ריקים, ש-``urlsplit`` מחזיר כמחרוזת ריקה.
        return _invalid("has_path")
    return WebappUrlStatus(state=STATE_CONFIGURED, url=value)


def webapp_base_url() -> Optional[str]:
    """הכתובת, בלי ``/`` בסוף — או ``None`` כשהמשתנה חסר או פגום. אין ברירת מחדל."""
    return webapp_url_status().url


def webapp_link(path: str) -> Optional[str]:
    """הכתובת ואחריה ``path`` (נתיב שמתחיל ב-``/``, אפשר עם query), או ``None`` כשאין כתובת.

    ``path`` שאינו מתחיל ב-``/`` הוא באג של הקורא ולא מצב ריצה, ולכן הוא זורק ``ValueError`` במקום לבנות קישור שבור.
    """
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError(f"webapp_link path must start with '/': {path!r}")
    base = webapp_base_url()
    return f"{base}{path}" if base else None


def webapp_base_url_for_request(request: Any) -> str:
    """בתוך בקשה ל-WebApp: הכתובת מ-``WEBAPP_URL``, ואם אין כתובת תקינה — הכתובת שהבקשה הגיעה אליה (``request.url_root``).

    **זה המקום היחיד שמותר לו ליפול לכתובת אחרת, ורק בתוך ה-WebApp.** הכתובת שהבקשה הגיעה אליה היא של השירות עצמו, ולא כתובת ישנה, ולכן הנפילה הזו לא שולחת לשום מקום מת. היא עדיין לא שקטה: המשתנה החסר נרשם בעלייה ומוצג ב-``/health``. המחיר: האפליקציה רצה בלי ProxyFix, ולכן הכתובת מהבקשה יוצאת ``http://`` — וחיבור לגוגל דרייב, שדורש התאמה מדויקת של כתובת החזרה, ייכשל אצל גוגל במקום לעבוד חלקית.

    ``request`` הוא האובייקט של Flask, ומועבר כפרמטר כדי שהמודול לא ייבא את Flask.
    """
    return webapp_base_url() or str(getattr(request, "url_root", "") or "").rstrip("/")


def log_webapp_url_status(log: logging.Logger, *, service: str) -> WebappUrlStatus:
    """שורת הלוג של עליית השירות: INFO עם הכתובת כשהיא תקינה, ו-ERROR כשהיא חסרה או פגומה. מחזיר את המצב.

    נקרא פעם אחת בעלייה של כל שירות — הבוט ב-``main()``, ה-WebApp בעליית השרת, ה-MCP ב-``create_app``.
    """
    status = webapp_url_status()
    if status.state == STATE_CONFIGURED:
        log.info("WEBAPP_URL (%s): %s", service, status.url)
    elif status.state == STATE_MISSING:
        log.error(
            "WEBAPP_URL is not set in %s: links to the WebApp are disabled until it is set (there is no default)",
            service,
        )
    else:
        log.error(
            "WEBAPP_URL in %s is invalid (%s): links to the WebApp are disabled until it is fixed; "
            "expected https://<host> with no path and no trailing slash",
            service,
            status.problem,
        )
    return status
