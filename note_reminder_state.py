"""
Note Reminder State — מתי תזכורת נחשבת פעילה, ומי מכריע את זה.

לתזכורת של פתק יש שני שדות שמתארים את אותה עובדה: ``status``, שהוא עמודת
מחזור החיים, ו-``ack_at``, שמסמן שהמשתמש כבר ראה אותה. כל עוד שניהם נכתבים
בנפרד הם נסחפים — וזה בדיוק מה שקרה: ``reminders_ack`` כתב ``ack_at`` ולא
נגע ב-``status``, ולכן תזכורת שנצפתה ונסגרה נשארה ``pending`` לנצח. כרטיס
הדשבורד, שסופר לפי ``status`` בלבד, דיווח כל תזכורת שנצפתה כ"בהמתנה" כשאף
אחת מהן לא המתינה לכלום. במדידה מול המסד, ביום שהבאג נמצא, **כל** המסמכים
באוסף היו במצב הזה — כלומר לא מקרה קצה אלא ההתנהגות היחידה שהייתה.

**גם הכתיבה עוברת כאן.** :func:`armed_fields`, :func:`snoozed_fields` ו-
:func:`acknowledge_fields` הן שלושת המעברים במחזור החיים, ואתרי הכתיבה
במסלולים מחזיקים רק את שדות הזהות (משתמש, פתק, קובץ). קבוע מצב שמשתנה משנה
כך גם מה נקרא וגם מה נכתב; לפני כן שני אתרי כתיבה החזיקו מחרוזות משלהם,
ותזכורות חדשות היו מפסיקות להתאים לפילטר בשקט.

המודול הזה הוא המקום היחיד שיודע מהי "תזכורת פעילה", והוא טהור בכוונה: בלי
Flask, בלי pymongo, בלי ``get_db``. כך ``webapp/sticky_notes_api``,
``webapp/app`` ו-``webapp/push_api`` — שלושת הצרכנים — מייבאים את אותה
הגדרה, בדיוק כמו ש-``sticky_notes_target`` עושה ליעד הפתק.

**למה פונקציה ולא קבוע.** הפילטר הורכב ביד בשמונה מקומות, בחמש וריאציות
שונות: חלקן בדקו ``ack_at``, חלקן לא, וההבדל לא נראה בקריאת אף אתר בנפרד.
:func:`active_reminder_filter` מחזירה מילון חדש בכל קריאה — הקורא מרחיב
אותו לפי הצורך (משתמש, זמן) בלי לשנות את המקור המשותף. קבוע ברמת מודול היה
משותף בהפניה, ומרחיב אחד היה מזהם את כל השאר.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from file_dates import as_utc


#: התזכורת נוצרה וממתינה למועדה.
REMINDER_STATUS_PENDING = "pending"

#: המשתמש דחה אותה; ``remind_at`` הוזז קדימה ו-``ack_at`` אופס.
REMINDER_STATUS_SNOOZED = "snoozed"

#: **המצב הסופי, והשדה שחסר עד היום.** בלעדיו ``status`` לא סינן כלום:
#: לא היה לו ערך שלישי, ולכן ``status in (pending, snoozed)`` היה נכון על
#: כל מסמך באוסף. מי שסינן לפיו בלבד קיבל את הכול וחשב שסינן.
REMINDER_STATUS_ACKED = "acked"

#: המצבים שבהם תזכורת עדיין במחזור החיים הפעיל.
ACTIVE_REMINDER_STATUSES: Tuple[str, ...] = (
    REMINDER_STATUS_PENDING,
    REMINDER_STATUS_SNOOZED,
)


def active_reminder_filter() -> Dict[str, Any]:
    """תנאי ה"תזכורת פעילה" — שני השדות יחד, תמיד.

    ``status`` לבדו אינו מספיק גם אחרי התיקון: מסמך שנכתב לפני שהמצב הסופי
    היה קיים נשאר ``pending`` עם ``ack_at`` מלא, ויישאר כזה עד שהמיגרציה
    תרוץ. ``ack_at`` לבדו אינו מספיק כי ``snooze`` מאפס אותו בכוונה — תזכורת
    דחויה היא פעילה שוב. רק שניהם יחד מתארים את מה שהקוראים באמת שואלים.

    :returns: מילון חדש בכל קריאה, בטוח להרחבה במקום.
    """
    return {
        "status": {"$in": list(ACTIVE_REMINDER_STATUSES)},
        "ack_at": None,
    }


def armed_fields(remind_at: datetime, now: datetime) -> Dict[str, Any]:
    """השדות שדורכים תזכורת — קביעה ראשונה או קביעה מחדש, אותה כתיבה.

    ``ack_at`` מתאפס בכוונה: קביעה מחדש פותחת גם תזכורת שכבר אושרה, וזה
    המסלול היחיד שעושה זאת. ``needs_push`` נדרך כדי שהשליחה תצא שוב.

    :param remind_at: המועד, מודע-אזור, באחריות הקורא.
    :param now: חותמת הכתיבה, מודעת-אזור.
    """
    return {
        "status": REMINDER_STATUS_PENDING,
        "remind_at": remind_at,
        "snooze_until": None,
        "ack_at": None,
        "updated_at": now,
        "needs_push": True,
    }


def snoozed_fields(until: datetime, now: datetime) -> Dict[str, Any]:
    """השדות שדוחים תזכורת **פעילה** ל-``until``.

    אין כאן ``ack_at``: הדחייה חלה רק תחת :func:`active_reminder_filter`, שכבר
    דורש שהוא ריק, ולכן איפוס שלו היה כתיבה מתה. תזכורת שאושרה נפתחת מחדש
    דרך :func:`armed_fields`, לא דרך דחייה.
    """
    return {
        "status": REMINDER_STATUS_SNOOZED,
        "remind_at": until,
        "snooze_until": until,
        "updated_at": now,
        "needs_push": True,
    }


def acknowledge_fields(now: Any) -> Dict[str, Any]:
    """השדות שסוגרים תזכורת — **את שניהם, באותה כתיבה**.

    זו הנקודה שבה הסחיפה נולדה, ולכן היא הפכה לפונקציה: מי שסוגר תזכורת
    אינו יכול לכתוב ``ack_at`` ולשכוח את ``status``, כי אין לו את המילון
    החלקי בכלל. הקורא מעביר את המילון הזה כמו שהוא ל-``$set`` יחיד, וכך
    מונגו מחילה את שניהם אטומית על המסמך.

    :param now: חותמת הזמן לכתיבה — מודעת-אזור, באחריות הקורא.
    """
    return {
        "status": REMINDER_STATUS_ACKED,
        "ack_at": now,
        "updated_at": now,
    }


def seconds_until(value: Any, now: datetime) -> Optional[int]:
    """כמה שניות נותרו עד ``value`` — או ``None`` כשאין מה למדוד.

    **התיוג קורה כאן, ובכוונה.** מונגו מחזירה ערך נאיבי אלא אם הלקוח נבנה
    עם ``tz_aware``, והחיסור בין ערך נאיבי לערך מודע־אזור זורק ``TypeError``
    בפייתון. הבדיקה אינה קישוט: היא ההבדל בין חישוב נכון לבין חריגה שתיבלע
    למעלה ותחזיר 500 על מסלול שנקרא בכל טעינת עמוד.

    ערך שכבר עבר מוחזר כ-``0`` ולא כמספר שלילי — הקורא מתרגם את זה
    ל"שאל שוב מיד", וזו התשובה הנכונה לתזכורת שמועדה חלף.

    **ומעוגל כלפי מעלה.** ``int`` חתך מטה, ולכן הלקוח התעורר רגע לפני המועד,
    לא מצא כלום, קיבל ``0``, ורצפת הדקה שלו הפכה את זה לכמעט דקה של איחור
    בבועה — כמעט בכל יקיצה מתוזמנת. התיוג של ערך נאיבי עובר דרך
    :func:`file_dates.as_utc`, אותו כלל שכל שאר הקוראים משתמשים בו.

    :param value: חותמת מהמסד, מודעת־אזור או נאיבית (שאז היא UTC).
    :param now: ההווה, מודע־אזור.
    """
    if not isinstance(value, datetime):
        return None
    return max(0, math.ceil((as_utc(value) - as_utc(now)).total_seconds()))


def occurrence_key(value: datetime) -> datetime:
    """המועד כפי שהמסד שומר אותו: UTC מודע-אזור, ברזולוציית מילישניות.

    תאריך ב-BSON הוא מספר המילישניות מאז epoch, ו-pymongo זורק את שארית
    המיקרו-שניות בכתיבה (``bson._datetime_to_millis`` מחלק ב-1000). מפתח
    שמשווים לערך שנקרא מהמסד חייב לעבור את אותו חיתוך, אחרת אישור שנושא
    מחרוזת מדויקת יותר מהמסד לא יתאים לעולם.
    """
    utc = as_utc(value)
    return utc.replace(microsecond=(utc.microsecond // 1000) * 1000)


def parse_remind_at(raw: Any) -> Optional[datetime]:
    """המועד שההתראה או החלונית נשאו, כמפתח להתאמה מול המסד.

    ``None`` או מחרוזת ריקה ← אין קשירה: לקוח ישן, או התראה שהוצגה לפני
    שהמועד נוסף לה. מחרוזת ISO ← המפתח דרך :func:`occurrence_key`; מחרוזת
    בלי offset נקראת כ-UTC, כמו כל ערך נאיבי במסד. כל דבר אחר — טיפוס לא
    נכון או מחרוזת שאינה ISO — זורק ``ValueError``, והמסלול עונה 400: קלט
    פסול אינו "בלי קשירה", אחרת שגיאה בלקוח הייתה סוגרת תזכורת שרירותית.
    ``datetime.fromisoformat`` מקבל גם סיומת ``Z`` מפייתון 3.11, שהיא הרצפה
    של הפרויקט. ומועד תקין תחבירית שההמרה שלו ל-UTC יוצאת מטווח ``datetime``
    (``0001-01-01T00:00:00+03:00``) מפיל את ``astimezone`` ב-``OverflowError``
    ולא ב-``ValueError`` — נמדד, ובמימוש הייחוס ``Lib/datetime.py`` זה
    ``raise OverflowError("result out of range")`` בחיבור התאריכים. החוזה כאן
    הוא "מפתח או ``ValueError``", ולכן זה מנורמל; בלי הנרמול המסלול היה עונה
    500 עם traceback על טעות של הלקוח.
    """
    if raw is None or raw == '':
        return None
    if not isinstance(raw, str):
        raise ValueError(f"remind_at must be an ISO string, not {type(raw).__name__}")
    try:
        return occurrence_key(datetime.fromisoformat(raw))
    except OverflowError as exc:
        raise ValueError("remind_at is outside the supported datetime range") from exc
