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


def _as_utc(value: datetime) -> datetime:
    """מונגו מחזיר datetime בלי תווית אזור זמן, והוא תמיד UTC.

    בלי הנרמול הזה השוואה בין ערך naive לערך aware זורקת ``TypeError``.
    אותה מוסכמה שכבר נהוגה ב-``TimeUtils.to_israel_time``.
    """
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


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
    return _as_utc(updated_at) > _as_utc(created_at)
