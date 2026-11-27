"""הפניה מכתובת ישנה של ה-WebApp לכתובת שב-``WEBAPP_URL`` — דפים שנפתחים בדפדפן בלבד.

**הרקע.** בסוף נובמבר 2026 ה-WebApp עובר לדומיין ``codekeeper.dev``. תת-הדומיין של השירות ב-Render (``*.onrender.com``; הכתובת עצמה רק ב-``WEBAPP_LEGACY_HOSTS``, כדי שלא תהיה ברירת מחדל בקוד — ``test_the_old_webapp_host_is_not_in_code_that_runs``) נשאר פעיל לתמיד: תלויים בו קישורים שכבר נשלחו, ה-webhooks של GitHub, אפליקציות PWA שהותקנו ממנו ומנויי push שנרשמו בו. כיבוי שלו בהגדרות השירות היה מחזיר 404 לכל בקשה אליו, בלי שהיא מגיעה לשירות (https://render.com/docs/custom-domains, נקרא בנובמבר 2026). לתת-הדומיין יש שם שני מצבים בלבד, פעיל או כבוי (``renderSubdomainPolicy``), ולא הפניה, ולכן ההפניה כאן, באפליקציה. המעבר כולו — מה עבר, מה נשאר, ומה נעשה ידנית — ב-``docs/whats-new/2026-11.rst``, 2026-11-27.

**מה מופנה:** בקשת ``GET`` או ``HEAD`` שה-``Host`` שלה מופיע ב-``WEBAPP_LEGACY_HOSTS``, לאותו נתיב ולאותם פרמטרים בדיוק בכתובת של ``WEBAPP_URL``. כך קישור ישן לקובץ משותף מגיע לאותו קובץ. גם נתיבי ההתחברות (``/auth/token``, ``/auth/telegram`` ו-``/oauth/identify``) מופנים: הם יוצרים את ה-session, וה-session שייך לדומיין — התחברות בכתובת הישנה הייתה נשארת שם, והמשתמש היה מגיע לדומיין החדש מנותק.

**מה לא מופנה, ולמה:**

- **כל מתודה אחרת.** לקוח ששולח גוף לא תמיד עוקב אחרי הפניה, ו-302 על ``POST`` הופך אצל דפדפנים ל-``GET`` בלי הגוף (RFC 9110, סעיף 15.4.3).
- **כל מה שתחת** ``/api/``. אלה קריאות ``fetch`` מדפים, ה-webhooks (``/api/webhooks/github``) וכתובת החזרה של גוגל דרייב (``/api/drive/callback``). ה-Service Worker של הכתובת הישנה ממשיך לדחות ולאשר תזכורות מול הכתובת הישנה, עם ה-session שלה, וחזרה מגוגל צריכה להסתיים באותו דומיין שבו החיבור התחיל.
- :data:`EXEMPT_ENDPOINTS` — נתיבים שאינם דף: ``/sw.js`` (דפדפנים לא מקבלים הפניה בסקריפט של Service Worker, וה-Service Worker הישן היה נתקע בלי עדכון), בדיקות התקינות והמדדים (מוניטורים ו-Prometheus), קבצים סטטיים ו-``favicon.ico``, וקובץ האימות של Google Search Console — גוגל מוריד אותו בלי לעקוב אחרי הפניות, והאימות של הכתובת הישנה הוא תנאי לכלי ה-Change of Address.

**302 ואחר כך 301.** כברירת מחדל ההפניה זמנית (302): דפדפנים שומרים 301 לזמן ארוך, והפניה שגויה שנשמרה אי אפשר לבטל אצל מי שכבר קיבל אותה. אחרי שהמעבר אומת, ``WEBAPP_LEGACY_REDIRECT_PERMANENT=true`` מעביר ל-301.

**בלי תצורה תקינה אין הפניה בכלל**, אבל לא בשקט: :func:`log_legacy_redirect_status` כותבת שורת ERROR בעלייה, ו-``/health`` מציג את המצב (``WEBAPP_LEGACY_REDIRECT``). פגום הוא מארח שאינו בדקדוק של ``WEBAPP_URL`` (:func:`webapp_url.is_valid_host`), ``WEBAPP_URL`` שאינו תקין (אין לאן להפנות), כתובת ישנה ששווה לכתובת הקנונית (לולאה), או ערך של הדגל שאינו אחד מהערכים המוכרים.

**ההשוואה היא על המארח כולו** — באותיות קטנות, בשוויון מלא, ולא ``startswith``/``endswith``: הכתובת הישנה ואחריה ``.evil.net`` היא מארח אחר (K16 ב-amir-bug-patterns).

המודול טהור: בלי Flask, בלי ייבוא של שירות ובלי פעולה בזמן ייבוא. הערכים נקראים מהסביבה בכל קריאה, כמו ב-``webapp_url.py``, ולכן טסט שמגדיר או מוחק משתנה רואה את השינוי מיד. הרישום ב-Flask — ``_redirect_legacy_host`` ב-``webapp/app.py``, ראשון מבין ה-``before_request``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, FrozenSet, Optional, Tuple
from urllib.parse import quote

from webapp_url import STATE_CONFIGURED, is_valid_host, webapp_base_url, webapp_host, webapp_url_status

__all__ = [
    "STATE_OFF",
    "STATE_ON",
    "STATE_INVALID",
    "EXEMPT_ENDPOINTS",
    "LegacyRedirectConfig",
    "legacy_redirect_config",
    "legacy_redirect_for",
    "log_legacy_redirect_status",
]

STATE_OFF = "off"
STATE_ON = "on"
STATE_INVALID = "invalid"

#: נקודות הקצה (שמות ה-endpoint ב-Flask, לא נתיבים) שלא מופנות גם כשהן נפתחות ב-``GET``. הנימוק לכל אחת ב-docstring של
#: המודול. שם ולא נתיב, כדי ששינוי של נתיב לא יוציא נקודה מהרשימה בשקט — ו-``tests/test_legacy_host_redirect.py``
#: נכשל כששם כאן אינו רשום באפליקציה.
EXEMPT_ENDPOINTS: FrozenSet[str] = frozenset(
    {
        "service_worker_js",  # /sw.js
        "static",  # /static/<path>
        "favicon",  # /favicon.ico
        "health",  # /health
        "healthz",  # /healthz
        "metrics_endpoint",  # /metrics
        "google_site_verification",  # קובץ האימות של Search Console
    }
)

#: ערכי הדגל ``WEBAPP_LEGACY_REDIRECT_PERMANENT``. ערך אחר הוא פגום ולא "כבוי": טעות הקלדה בדגל הייתה משאירה 302 בלי שאיש
#: יידע, ומי שהדליק אותו מצפה ל-301.
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"", "0", "false", "no", "off"})

#: תווים שנשארים כמו שהם בנתיב. ``request.path`` כבר מפוענח (``%2F`` הפך ל-``/``, ``%25`` ל-``%``), ולכן ``%`` אינו כאן:
#: אחוז בנתיב המפוענח הוא אחוז אמיתי, וחוזר כ-``%25``. התווים — ה-path-segment של WHATWG ועוד ``/``, כמו ב-
#: ``werkzeug.sansio.utils.get_current_url`` (נקרא ב-Werkzeug 3.1.9) בלי ``%``. כל השאר, כולל ``\r`` ו-``\n``, מקודד.
_PATH_SAFE = "/!$&'()*+,:;=@"
#: ה-query string מגיע מהשרת כמו שנשלח, בלי פענוח, ולכן ``%`` נשאר בו כמו שהוא — אותו סט כמו ב-``get_current_url``.
_QUERY_SAFE = "!$&'()*+,/:;=?@%"


@dataclass(frozen=True)
class LegacyRedirectConfig:
    """התצורה של ההפניה: ``state`` הוא אחד מ-``STATE_*``. ``hosts``, ``target`` ו-``status_code`` קיימים רק ב-``STATE_ON``;
    ``problem`` רק ב-``STATE_INVALID`` — קוד קצר (``bad_host``, ``no_webapp_url``, ``legacy_is_canonical``,
    ``bad_permanent_flag``), ולא הערך עצמו."""

    state: str
    hosts: FrozenSet[str] = field(default_factory=frozenset)
    target: Optional[str] = None
    status_code: Optional[int] = None
    problem: Optional[str] = None


def _invalid(problem: str) -> LegacyRedirectConfig:
    return LegacyRedirectConfig(state=STATE_INVALID, problem=problem)


def legacy_redirect_config() -> LegacyRedirectConfig:
    """קורא את ``WEBAPP_LEGACY_HOSTS`` ואת ``WEBAPP_LEGACY_REDIRECT_PERMANENT`` ומחזיר את התצורה. לא זורק."""
    raw_hosts = os.environ.get("WEBAPP_LEGACY_HOSTS")
    hosts_value = raw_hosts.strip() if isinstance(raw_hosts, str) else ""
    if not hosts_value:
        return LegacyRedirectConfig(state=STATE_OFF)
    # רשימה מופרדת בפסיקים. פריט ריק ("a,,b", פסיק בסוף) הוא פגום ולא מדולג — כמו ב-``WEBAPP_URL``, ערך שאינו
    # בדיוק בצורה הנכונה לא מתוקן בניחוש.
    hosts = [part.strip().lower() for part in hosts_value.split(",")]
    if not all(is_valid_host(host) for host in hosts):
        return _invalid("bad_host")
    if webapp_url_status().state != STATE_CONFIGURED:
        return _invalid("no_webapp_url")
    if webapp_host() in hosts:
        return _invalid("legacy_is_canonical")
    raw_flag = os.environ.get("WEBAPP_LEGACY_REDIRECT_PERMANENT")
    flag = raw_flag.strip().lower() if isinstance(raw_flag, str) else ""
    if flag in _TRUE_VALUES:
        status_code = 301
    elif flag in _FALSE_VALUES:
        status_code = 302
    else:
        return _invalid("bad_permanent_flag")
    return LegacyRedirectConfig(
        state=STATE_ON,
        hosts=frozenset(hosts),
        target=webapp_base_url(),
        status_code=status_code,
    )


def _is_api_path(path: str) -> bool:
    # גבול מקטע מפורש: ``/api`` עצמו, או מה שמתחיל ב-``/api/`` — ולא ``/apiary`` (K16).
    return path == "/api" or path.startswith("/api/")


def legacy_redirect_for(request: Any) -> Optional[Tuple[str, int]]:
    """``(כתובת, קוד)`` כשהבקשה צריכה הפניה, ואחרת ``None``.

    ``request`` הוא הבקשה של Flask (``method``, ``host``, ``path``, ``query_string``, ``endpoint``), ומועבר כפרמטר כדי
    שהמודול לא ייבא את Flask. ``endpoint`` הוא ``None`` כשהנתיב לא נמצא, וגם אז הבקשה מופנית: דף שלא קיים בכתובת הישנה
    לא קיים גם בחדשה, ושם הוא מקבל את ה-404.
    """
    if request.method not in ("GET", "HEAD"):
        return None
    config = legacy_redirect_config()
    if config.state != STATE_ON:
        return None
    if (request.host or "").lower() not in config.hosts:
        return None
    if _is_api_path(request.path) or request.endpoint in EXEMPT_ENDPOINTS:
        return None
    location = config.target + quote(request.path, safe=_PATH_SAFE)
    if request.query_string:
        location += "?" + quote(request.query_string, safe=_QUERY_SAFE)
    return location, config.status_code


def log_legacy_redirect_status(log: logging.Logger) -> LegacyRedirectConfig:
    """שורת הלוג של עליית ה-WebApp: INFO כשההפניה פעילה או כבויה, ERROR כשהתצורה פגומה. מחזיר את התצורה.

    נקראת לצד ``log_webapp_url_status`` — בעליית השרת וב-``main`` של ``webapp/app.py``.
    """
    config = legacy_redirect_config()
    if config.state == STATE_ON:
        log.info(
            "Legacy host redirect is on: %s -> %s (HTTP %s)",
            ", ".join(sorted(config.hosts)),
            config.target,
            config.status_code,
        )
    elif config.state == STATE_OFF:
        log.info("Legacy host redirect is off (WEBAPP_LEGACY_HOSTS is not set)")
    else:
        log.error(
            "Legacy host redirect is disabled: the configuration is invalid (%s); "
            "nothing is redirected until it is fixed",
            config.problem,
        )
    return config
