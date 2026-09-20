"""הכרעת ערכי ריצה שמגיעים מ-ENV או מהקונפיג — מקור אמת אחד.

המודול הזה מחזיק את ההחלטות שקודם ישבו בשני מקומות ונסחפו זו מזו: מה
נחשב ``SAFE_MODE`` דולק, ומה ה-timeouts של Redis כשאיש לא הגדיר אותם
במפורש. כל עוד ההכרעה חיה בשני עותקים, מספיק שאחד מהם יתוקן כדי ששניהם
יפסיקו להסכים — וזה בדיוק מה שקרה כאן: ``config.py`` הצהיר על 3 ו-5,
``cache_manager`` על 5 ו-5, והתיעוד על 3 ו-5 עם 1 ב-SAFE_MODE.

**המודול חסר תלויות בכוונה** — ספריית התקן בלבד. הוא נטען גם מתוך
``cache_manager`` (שנטען בכל שירות) וגם מתוך ``main``, ואסור לו לגרור
לשם ייבוא כבד.
"""

from __future__ import annotations

import logging
import math
import os
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)

#: הערכים שנחשבים "דולק" בדגל בוליאני שמגיע מ-ENV. הרשימה הזו הייתה
#: משוכפלת בחמישה מקומות בשלוש גרסאות שונות (חלקן קיבלו ``"y"``, חלקן לא).
_TRUE_VALUES = frozenset({"1", "true", "yes", "y", "on"})

#: ברירות המחדל של ה-timeouts ל-Redis, בשניות. הוגדלו בדצמבר 2025 בעקבות
#: עומס על בסיס הנתונים שגרם ל-Timeouts שגויים בקאש.
DEFAULT_REDIS_CONNECT_TIMEOUT = 3.0
DEFAULT_REDIS_SOCKET_TIMEOUT = 5.0

#: ב-``SAFE_MODE`` שני ה-timeouts יורדים לשנייה אחת: עדיף לוותר על הקאש
#: מהר מאשר להחזיק worker תקוע על חיבור שלא ייפתח.
SAFE_MODE_REDIS_TIMEOUT = 1.0


def safe_mode_enabled(env: Mapping[str, str] | None = None) -> bool:
    """האם ``SAFE_MODE`` דולק.

    ``env`` קיים כדי שאפשר יהיה לבדוק את הפונקציה בלי לגעת ב-``os.environ``
    הגלובלי; בקוד הייצור לא מעבירים אותו.
    """
    raw = (os.environ if env is None else env).get("SAFE_MODE")
    # הערך מגיע מחוץ לתהליך, ולכן לא מניחים שהוא מחרוזת.
    if not isinstance(raw, str):
        return False
    return raw.strip().lower() in _TRUE_VALUES


def resolve_redis_timeouts(
    explicit_connect: float | None,
    explicit_socket: float | None,
    safe_mode: bool,
) -> tuple[float, float]:
    """מכריעה את שני ה-timeouts של Redis ומחזירה ``(connect, socket)``.

    סדר הקדימות, וזה כל מה שהפונקציה עושה:

    1. ערך שהוגדר במפורש — מנצח תמיד, גם ``0.0`` וגם ב-``SAFE_MODE``.
    2. אחרת, ב-``SAFE_MODE`` — שנייה אחת לשניהם.
    3. אחרת — ברירות המחדל, 3 לחיבור ו-5 לשקע.

    הפונקציה טהורה: היא אינה קוראת ``os.environ``, אינה מייבאת את
    הקונפיג, ואינה תלויה בשום דבר שכבר נטען ל-``sys.modules``. זו הנקודה
    שלה — עד שהיא נכתבה, אותה הכרעה נפלה אחרת לפי מי הספיק לייבא את
    ``config`` קודם.
    """
    safe_default = SAFE_MODE_REDIS_TIMEOUT if safe_mode else None

    if explicit_connect is not None:
        connect = float(explicit_connect)
    elif safe_default is not None:
        connect = safe_default
    else:
        connect = DEFAULT_REDIS_CONNECT_TIMEOUT

    if explicit_socket is not None:
        socket = float(explicit_socket)
    elif safe_default is not None:
        socket = safe_default
    else:
        socket = DEFAULT_REDIS_SOCKET_TIMEOUT

    return connect, socket


def _coerce_timeout(raw: Any, name: str) -> float | None:
    """ממיר ערך timeout שהגיע מבחוץ למספר, או ``None`` כשאין ערך שמיש.

    הערך מגיע מ-ENV או מאובייקט קונפיג, ולכן אינו מובטח להיות מספר. ערך
    פגום **אינו** מפיל כאן: המסלול הזה רץ רק כשאובייקט הקונפיג אינו זמין
    (למשל בטסטים), ושם נפילה הייתה מכבה את הקאש כולו עם הודעה מטעה. הוא
    כן נרשם ללוג, כדי שלא יהיה שקט. כשהקונפיג כן נטען, ולידציה של pydantic
    כבר פוסלת ערך כזה בזמן עלייה — שם הכשל רועש בכוונה.
    """
    if raw is None:
        return None

    # ``bool`` הוא תת-מחלקה של ``int`` בפייתון, ו-``True`` אינו timeout.
    if isinstance(raw, bool):
        logger.warning("%s=%r אינו ערך timeout — ממשיכים עם ברירת המחדל", name, raw)
        return None

    if isinstance(raw, (int, float)):
        value = float(raw)
    elif isinstance(raw, str):
        text = raw.strip()
        if not text:
            # משתנה שהוגדר ריק פירושו "לא הוגדר", לא "אפס".
            return None
        try:
            value = float(text)
        except ValueError:
            logger.warning("%s=%r אינו מספר — ממשיכים עם ברירת המחדל", name, raw)
            return None
    else:
        logger.warning("%s=%r אינו ערך timeout — ממשיכים עם ברירת המחדל", name, raw)
        return None

    if not math.isfinite(value) or value < 0:
        logger.warning("%s=%r אינו timeout חוקי — ממשיכים עם ברירת המחדל", name, raw)
        return None

    return value


def redis_timeouts(
    cfg: Any = None,
    env: Mapping[str, str] | None = None,
) -> tuple[float, float]:
    """נקודת הכניסה היחידה ל-timeouts של Redis: ``(connect, socket)``.

    ``cfg`` הוא אובייקט הקונפיג אם הוא זמין. ה-``getattr`` עליו הוא
    נפילה-לאחור על **היעדר יכולת** ולא על כשל: בטסטים ``config`` מוחלף
    במודול דמה שאין בו את השדות האלה כלל, וזה מצב סטטי וידוע. כשהקונפיג
    כן זמין הוא כבר קרא את ה-ENV בעצמו, ולכן הקריאה ל-``env`` כאן היא
    המסלול היחיד שנשאר כשאין קונפיג.
    """
    environ: Mapping[str, str] = os.environ if env is None else env

    connect = _coerce_timeout(
        getattr(cfg, "REDIS_CONNECT_TIMEOUT", None), "REDIS_CONNECT_TIMEOUT"
    )
    if connect is None:
        connect = _coerce_timeout(
            environ.get("REDIS_CONNECT_TIMEOUT"), "REDIS_CONNECT_TIMEOUT"
        )

    socket = _coerce_timeout(
        getattr(cfg, "REDIS_SOCKET_TIMEOUT", None), "REDIS_SOCKET_TIMEOUT"
    )
    if socket is None:
        socket = _coerce_timeout(
            environ.get("REDIS_SOCKET_TIMEOUT"), "REDIS_SOCKET_TIMEOUT"
        )

    return resolve_redis_timeouts(connect, socket, safe_mode_enabled(environ))
