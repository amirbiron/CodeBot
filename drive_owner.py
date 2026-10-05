"""בעלות על חיבור Google Drive — לכל שירות חיבור משלו.

הבוט והוובאפ מתחברים ל-Google Drive כל אחד עם OAuth client משלו: הבוט ב-Device Flow (``services.google_drive_service.start_device_authorization``), והוובאפ בהפניה בדפדפן (``webapp/drive_auth.py``). refresh token עובד רק מול ה-client שהנפיק אותו (RFC 6749, סעיף 6), ולכן טוקן שהונפק לשירות אחד אינו שמיש בשני.

**מה היה קודם.** שני השירותים קראו וכתבו את אותם שדות במסמך המשתמש. מי שהתחבר אחרון "ניצח", והשני נכשל בשקט בגיבוי הבא. גם שני המתזמנים — של הבוט ושל הוובאפ — כתבו את אותו מועד גיבוי הבא, ושניהם הריצו את אותו תזמון.

**הכלל.** לכל שירות חיבור שמור משלו (טוקנים) והעדפות משלו (תזמון, תיקייה, גיבוי אחרון), והמודול הזה הוא המקום היחיד שממפה שירות ← שמות השדות במסמך המשתמש (``_FIELDS``). הבוט נשאר על השדות ההיסטוריים, בלי מיגרציה; לוובאפ שדות חדשים, והוא מתחיל מנותק עד שמתחברים בו.

**בלי ברירת מחדל.** כל פונקציה שקוראת או כותבת טוקנים או העדפות של Drive מקבלת ``owner`` כפרמטר חובה (keyword-only). קורא ששכח לציין נכשל מיד ב-``TypeError``, במקום ליפול בשקט לשדות של השירות השני — וזה בדיוק סוג הבאג שההפרדה נועדה לסגור.

**ערוץ הכשל: זריקה.** ``owner`` שאינו אחד מהערכים המוכרים הוא שגיאה של הקורא, ולכן ``ValueError`` ולא שדה ברירת מחדל.
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = ["BOT", "WEBAPP", "DriveFields", "drive_fields"]

BOT = "bot"
WEBAPP = "webapp"


@dataclass(frozen=True)
class DriveFields:
    """שמות השדות של שירות אחד במסמך המשתמש באוסף ``users``."""

    tokens: str
    prefs: str


# docs:drive-owner-fields:start — הקטע מוטמע בתיעוד (docs/services/google_drive_service.rst); אל תסיר את הסימון
_FIELDS = {
    BOT: DriveFields(tokens="drive_tokens", prefs="drive_prefs"),
    WEBAPP: DriveFields(tokens="webapp_drive_tokens", prefs="webapp_drive_prefs"),
}
# docs:drive-owner-fields:end


def drive_fields(owner: str) -> DriveFields:
    """מחזיר את שמות השדות של השירות ``owner`` (``BOT`` או ``WEBAPP``).

    הבדיקה ש-``owner`` הוא מחרוזת קודמת לחיפוש במילון: ערך שאינו hashable היה זורק ``TypeError`` מתוך החיפוש עצמו, במקום שגיאה שאומרת מה לא תקין.
    """
    if not isinstance(owner, str) or owner not in _FIELDS:
        raise ValueError(f"unknown Drive owner: {owner!r}")
    return _FIELDS[owner]
