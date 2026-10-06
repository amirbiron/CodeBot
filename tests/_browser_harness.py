"""מגע אמיתי ודגימת תנאי — לבדיקות הדפדפן שרצות בעמוד אמיתי במגע של טאבלט.

**למה קובץ משותף.** שני קובצי דפדפן צריכים בדיוק את אותם שני כלים, והם נכתבו
לראשונה בתוך ``tests/test_repo_notes_browser.py``. עותק שני היה נסחף מהראשון ביום
שאחד מהם מתוקן — למשל ביום שמישהו מגלה פרט נוסף בפרוטוקול המגע.

**ומה אין כאן, בכוונה: הרמת הדפדפן.** היא נשארת בקובצי ``*_browser.py``, כי
``tests/test_browser_suite_is_gated_once.py`` מוודא שרק שם, ובשער שב-``tests/conftest.py``,
מרימים דפדפן.
"""

from __future__ import annotations

import time

#: כמה מחכים לתנאי שתלוי ברשת, ברינדור או בגלילה חלקה. ``wait_for_function`` חסום:
#: ה-CSP של העמודים אוסר ``unsafe-eval``, ולכן תנאים נדגמים מכאן.
WAIT_S = 15.0


def poll(page, js: str, what: str, arg=None):
    """דוגם תנאי בדף עד שהוא מתקיים, או נכשל עם ``what`` — לעולם לא תלוי לנצח.

    התנאי מתקיים כשהסקריפט מחזיר ``true``, או מילון שה-``ok`` שבו אמת. כל ערך אחר
    הוא המצב שנצפה, והאחרון שבהם נכנס להודעת הכישלון: כישלון אומר מה נמדד, ולא
    רק מה לא קרה.
    """
    deadline = time.monotonic() + WAIT_S
    while True:
        value = page.evaluate(js, arg)
        if value is True or (isinstance(value, dict) and value.get("ok")):
            return value
        if time.monotonic() > deadline:
            raise AssertionError(f"לא התקיים תוך {WAIT_S} שניות: {what} — נצפה לאחרונה: {value!r}")
        time.sleep(0.1)


class Touch:
    """מגע דרך צינור הקלט של הדפדפן, ולא ``TouchEvent`` שנבנה ב-JS — שאינו מפעיל גלילה.

    מקור: ``Input.dispatchTouchEvent`` בהגדרות הפרוטוקול שנשלחות עם
    Playwright 1.49 (``driver/package/types/protocol.d.ts``): ``touchEnd`` חייב
    להגיע בלי נקודות מגע, ו-``x``/``y`` הם פיקסלי CSS ביחס לאזור התצוגה.
    """

    def __init__(self, cdp):
        self.cdp = cdp

    def swipe(self, x, y, dx, dy, steps=8):
        self.cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
        for i in range(1, steps + 1):
            self.cdp.send("Input.dispatchTouchEvent", {
                "type": "touchMove", "touchPoints": [{"x": x + dx * i / steps, "y": y + dy * i / steps}]})
        self.cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})

    def tap(self, x, y):
        self.cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
        self.cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
