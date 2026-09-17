"""תאריכי קובץ — מקור אמת יחיד לשני כללים שהיו משוכפלים.

ב-Ck כל "גרסה" של קובץ היא מסמך חדש באוסף. לכן ``created_at`` על מסמך כזה
חייב לייצג את יצירת **הקובץ** ולא את כתיבת השורה, אחרת כל עריכה מקדמת את
התאריך שמוצג למשתמש כ"נוצר". הכלל הזה נדרש בשכבת ה-DB, בראוטי ה-WebApp
שכותבים ישירות לאוסף, ובשמירת מסמך משותף — שלושה מקומות שאסור שיסטו זה מזה.

המודול טהור בכוונה — ``typing`` ו-``datetime`` ותו לא, בלי Flask ובלי מסד.
זה מה שמאפשר גם ל-``database/repository`` וגם ל-``webapp`` לייבא אותו ישירות
בלי ``try/except`` ובלי עותק fallback שצריך לתחזק. אותה תבנית שכבר עובדת עם
``user_roles`` ועם ``sticky_notes_scope``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def inherited_created_at(fallback: Any, *previous_docs: Any) -> Any:
    """תאריך היצירה של קובץ: מהמסמך הקודם אם יש לו אחד, אחרת ``fallback``.

    המועמדים נבדקים לפי הסדר ונשלפים שדה-שדה. אין מיזוג מילונים — מיזוג
    היה מאפשר למסמך בלי ``created_at`` לדרוס את הערך של מסמך שיש לו.
    """
    for doc in previous_docs:
        if isinstance(doc, dict):
            value = doc.get("created_at")
            if value:
                return value
    return fallback


#: שם השדה שנושא את זמן כתיבת מסמך הגרסה. מוגדר פעם אחת כי הוא נכתב בשבעה
#: מסלולי יצירה שונים ונקרא בתצוגת ההיסטוריה — מחרוזת מודפסת בכל אחד מהם
#: הייתה שמונה מקומות שאפשר לשגות בהם בלי ששום בדיקה תיפול.
VERSION_CREATED_AT_FIELD = "version_created_at"


def version_created_at(doc: Any) -> Any:
    """מתי **מסמך הגרסה הזה** נכתב — ולא מתי התוכן שבו נערך.

    שלושה שדות שנראים דומים ואינם, וזו כל הסיבה שהפונקציה קיימת:

    * ``created_at`` שייך ל**קובץ** ועובר בירושה מגרסה לגרסה
      (:func:`inherited_created_at`), ולכן הוא זהה בכל הגרסאות.
    * ``updated_at`` מציין מתי **התוכן** נערך, והוא שדה של הקובץ כפי
      שהוא מוגדר ב-``docs/database/detailed-schema.rst``. הוא **בר-שינוי**:
      עדכון תיאור כותב אותו מחדש על הגרסה האחרונה.
    * ``version_created_at`` נכתב פעם אחת ב-insert ולעולם אינו מתעדכן.
      הוא היחיד שמתאים להיסטוריית הגרסאות, כי היסטוריה שמוצגת משדה
      שמישהו רשאי לכתוב עליו מאוחר יותר אינה היסטוריה.

    **הנפילה האחורה למסמכים ישנים היא ה-ObjectId, וזו אינה ניחוש.** ארבעת
    הבתים הראשונים של ``ObjectId`` הם חותמת הזמן של הייצור, כלומר בדיוק
    הרגע שבו השורה נכתבה — אותה שאלה שהשדה עונה עליה. ב-pymongo 4.15.3
    ‏``ObjectId.generation_time`` מחזיר ``datetime`` מודע-אזור ב-UTC,
    ברזולוציית שנייה.

    **ובכוונה לפי יכולת ולא לפי טיפוס.** המודול הזה טהור — ``datetime``
    ו-``typing`` ותו לא — וייבוא של ``bson`` היה קושר אותו לסטאק המסד
    ושובר את מה שמאפשר גם ל-``webapp`` וגם ל-``database`` לייבא אותו.
    ‏``getattr`` כאן הוא זיהוי יכולת סטטי ("האם למזהה יש חותמת זמן"), לא
    מסלול חלופי בגלל כשל; ה-``isinstance`` שאחריו הוא שמונע ממזהה
    מחרוזתי — כפי שסטאבים בבדיקות מייצרים — להחזיר ערך שאינו תאריך.

    **הנפילה האחרונה היא** ``updated_at``, למסמך בלי ObjectId אמיתי. היא
    פחות מדויקת (הדריסה שתוקנה נגעה בדיוק בשדה הזה), אבל ערך מקורב עדיף
    על שורת היסטוריה ריקה.
    """
    if not isinstance(doc, dict):
        return None
    value = doc.get(VERSION_CREATED_AT_FIELD)
    if isinstance(value, datetime):
        return value
    generation_time = getattr(doc.get("_id"), "generation_time", None)
    if isinstance(generation_time, datetime):
        return generation_time
    return doc.get("updated_at")


def as_utc(value: datetime) -> datetime:
    """מנרמל ``datetime`` ל-UTC עם תווית אזור זמן.

    שני מקרים נפרדים, וחשוב לא לאחד ביניהם: ערך **naive** מגיע ממונגו,
    שמאחסן UTC בלי תווית — ולכן מצמידים לו UTC. ערך **aware** בהיסט אחר
    מומר. ``astimezone`` על ערך naive היה מניח שעון מקומי וזה שגוי כאן.

    בלי הנרמול הזה השוואה בין naive ל-aware זורקת ``TypeError``. אותה
    מוסכמה שכבר נהוגה ב-``TimeUtils.to_israel_time``.
    """
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def file_was_edited(created_at: Any, updated_at: Any) -> bool:
    """האם הקובץ נערך אי פעם, לפי התאריכים **הגולמיים**.

    נועד להחליף השוואה בין מחרוזות מפורמטות: הפורמט לתצוגה הוא ברזולוציית
    דקה, ולכן עריכה שקרתה באותה דקה שבה הקובץ נוצר הייתה נראית כאילו לא
    קרתה — והשוואת מחרוזות גם קושרת החלטה סמנטית לפורמט התצוגה, כך ששינוי
    עתידי של הפורמט היה משנה בשקט איזה מידע מוצג.

    שלושת המקרים, לפי מה שיש להציג בפועל:

    * אין ``updated_at`` שמיש — ``False``. אין תאריך עדכון להציג, ושורה עם
      ערך ריק גרועה משורה שאינה קיימת. זה מצב שקיים בנתונים: ראו הסינון על
      ``updated_at`` חסר ב-``webapp/routes/dashboard_routes``.
    * יש ``updated_at`` ואין ``created_at`` שמיש — ``True``. יש מה להציג
      ואין עם מה להשוות, ולכן מציגים.
    * שניהם שמישים — משווים.
    """
    if not isinstance(updated_at, datetime):
        return False
    if not isinstance(created_at, datetime):
        return True
    return as_utc(updated_at) > as_utc(created_at)
