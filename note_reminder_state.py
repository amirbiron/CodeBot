"""
Note Reminder State — מתי תזכורת נחשבת פעילה, ומי מכריע את זה.

לתזכורת של פתק יש שני שדות שמתארים את אותה עובדה: ``status``, שהוא עמודת
מחזור החיים, ו-``ack_at``, שמסמן שהמשתמש כבר ראה אותה. כל עוד שניהם נכתבים
בנפרד הם נסחפים — וזה בדיוק מה שקרה: ``reminders_ack`` כתב ``ack_at`` ולא
נגע ב-``status``, ולכן תזכורת שנצפתה ונסגרה נשארה ``pending`` לנצח. כרטיס
הדשבורד, שסופר לפי ``status`` בלבד, דיווח 23 תזכורות "בהמתנה" כשאף אחת מהן
לא המתינה לכלום. במדידה מול המסד **כל** 23 המסמכים באוסף היו במצב הזה —
כלומר לא מקרה קצה אלא ההתנהגות היחידה שהייתה.

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

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple


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

    :param value: חותמת מהמסד, מודעת־אזור או נאיבית (שאז היא UTC).
    :param now: ההווה, מודע־אזור.
    """
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return max(0, int((value - now).total_seconds()))
