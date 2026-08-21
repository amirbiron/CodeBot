"""
Sticky Notes Tasks — צ'קבוקסים בתוך תוכן פתק.

שורה בצורת ``- [ ] טקסט`` היא משימה. לחיצה על התיבה היא **כתיבה למסד**, לא
שינוי תצוגה, ולכן הזיהוי והכתיבה חיים כאן — בשתי פונקציות טהורות שאפשר
לבדוק בלי Flask ובלי מסד.

**שתי החלטות מפורשות, לא מקריות:**

1. **התאמה לפי מספר סידורי ולא לפי טקסט.** שתי שורות ``- [ ] לבדוק`` זהות
   באותו פתק חייבות להיות ניתנות לסימון בנפרד. ``str.replace`` היה מסמן את
   הראשונה בשני המקרים, ולחיצה על השנייה הייתה "קופצת" לראשונה.

2. **לא מפרשים בלוקי קוד.** שורת ``- [ ]`` בתוך גדר ``` נספרת כמו כל שורה
   אחרת. האלטרנטיבה היא פרסר מארקדאון מלא, שהוא מחוץ להיקף — וכבר למדנו
   בריפו הזה מה עולה פרסור מארקדאון שנכתב ביד. ההחלטה מכוסה בבדיקה, כדי
   שהיא תהיה מתועדת ולא הפתעה.

הערה על אורך: ההתמרה שומרת אורך (``- [ ]`` ו-``- [x]`` זהים באורכם), ולכן
תקרת 5,000 התווים אינה יכולה להישבר כאן. יש על כך בדיקה.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

#: שורת משימה: הזחה, תו רשימה, תיבה, והמשך אופציונלי.
#: הקבוצות: 1=הזחה+תו רשימה+פתיחה, 2=תו הסימון, 3=סגירה+המשך.
_TASK_RE = re.compile(r"^([ \t]*[-*][ \t]\[)([ xX])(\].*)$")

#: תווי סימון אפשריים.
_CHECKED = "x"
_UNCHECKED = " "


def _split_lines(content: str) -> Tuple[List[str], str]:
    """פיצול לשורות תוך שמירת שובר השורה.

    ``\\r\\n`` **אינו** דורש טיפול מיוחד, וזה נבדק ולא הונח: פיצול על
    ``\\n`` משאיר ``\\r`` בסוף השורה, ה-regex עדיין תואם (``.`` תואם
    ``\\r``, ו-``$`` תופס לפניו), והחיבור מחדש מרכיב את ``\\r\\n`` בחזרה.
    ענף מיוחד לזה היה קוד שאי אפשר להפיל — מוטציה שביטלה אותו לא הפילה
    אף בדיקה.

    ``\\r`` לבדו כן דורש טיפול: בלעדיו כל התוכן נקרא כשורה אחת, ושתי
    משימות נספרות כאחת.
    """
    if "\r" in content and "\n" not in content:
        return content.split("\r"), "\r"
    return content.split("\n"), "\n"


def count_tasks(content: str) -> int:
    """כמה צ'קבוקסים יש בתוכן."""
    lines, _ = _split_lines(content or "")
    return sum(1 for line in lines if _TASK_RE.match(line))


def task_state_at_index(content: str, index: int) -> Optional[bool]:
    """מצב המשימה במיקום הסידורי הנתון, או ``None`` אם אין כזו.

    זו הפונקציה שמשמשת ל**אימות אחרי הכתיבה**: קוראים את המסמך מחדש
    מהמסד ושואלים אותה אם התו באמת השתנה.
    """
    if index is None or int(index) < 0:
        return None
    lines, _ = _split_lines(content or "")
    seen = 0
    for line in lines:
        m = _TASK_RE.match(line)
        if not m:
            continue
        if seen == int(index):
            return m.group(2).lower() == _CHECKED
        seen += 1
    return None


def toggle_task_at_index(content: str, index: int, checked: bool) -> Tuple[str, bool]:
    """מסמן או מבטל את המשימה במיקום הסידורי הנתון.

    מחזירה ``(תוכן_חדש, השתנה)``. ``השתנה=False`` פירושו שהמשימה כבר
    במצב המבוקש — ואז אין טעם לכתוב, וזה גם מה שהופך את הפעולה
    לאידמפוטנטית.

    מוחלף **רק התו בתוך הסוגריים**. ההזחה, תו הרשימה (``-`` או ``*``)
    והמשך השורה נשמרים מילה במילה.
    """
    if index is None or int(index) < 0:
        return content, False

    lines, sep = _split_lines(content or "")
    want = _CHECKED if checked else _UNCHECKED
    seen = 0
    for i, line in enumerate(lines):
        m = _TASK_RE.match(line)
        if not m:
            continue
        if seen == int(index):
            # השוואת **מצב** ולא של תווים: ``X`` ו-``x`` הם אותו דבר, ולכן
            # השוואת תווים ישירה הייתה מייצרת כתיבה מיותרת על ``- [X]``.
            is_checked = m.group(2).lower() == _CHECKED
            if is_checked == bool(checked):
                return content, False
            lines[i] = f"{m.group(1)}{want}{m.group(3)}"
            return sep.join(lines), True
        seen += 1
    return content, False
