"""מגע אמיתי, דגימת תנאי והקמת עמוד — לבדיקות הדפדפן שרצות בעמוד אמיתי במגע של טאבלט.

**למה קובץ משותף.** כמה קובצי דפדפן צריכים בדיוק את אותם כלים, והם נכתבו
לראשונה בתוך ``tests/test_repo_notes_browser.py``. עותק שני היה נסחף מהראשון ביום
שאחד מהם מתוקן — למשל ביום שמישהו מגלה פרט נוסף בפרוטוקול המגע.

**ומה אין כאן, בכוונה: הרמת הדפדפן.** היא נשארת בקובצי ``*_browser.py``, כי
``tests/test_browser_suite_is_gated_once.py`` מוודא שרק שם, ובשער שב-``tests/conftest.py``,
מרימים דפדפן. ``open_admin_page`` מקבלת דפדפן שכבר הורם, ומקימה בו רק את העמוד.
"""

from __future__ import annotations

import json
import time
from urllib.parse import urlsplit

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


#: מרכז האלמנט, ומה הדפדפן מוצא בנקודה הזו. ``ok`` רק כשאף אנימציה אינה מזיזה
#: אותו: הכותרות של ``md_preview.html`` נכנסות באנימציה (``#md-content > *``), והקישור
#: שליד כותרת זז ומשנה גודל בזמנה — נגיעה שנמדדה באמצעה פספסה אותו. גם חלוניות
#: התפריטים של הסרגל העליון נפתחות במעבר, ותוכן ההמבורגר נפתח בגובה שגדל.
#:
#: **"מזיזה" היא אנימציה שרצה**, ולא כל מה ש-``getAnimations()`` מחזיר: אנימציה
#: שהסתיימה עם ``forwards`` נשארת ברשימה במצב ``finished``. כך כרטיסי עמוד הקבצים
#: (``.stagger-feed > *`` ב-``animations.css``): נמדד ``slideUpFade`` במצב ``finished``
#: גם שנייה וחצי אחרי הטעינה, ובלי הבדיקה הזו אף כפתור בכרטיס לא היה מקבל נגיעה.
#: ``paused`` ו-``finished`` הם המצבים שבהם ``currentTime`` אינו מתקדם (MDN,
#: ``Animation.playState``).
CENTER_JS = """([sel, index]) => {
  const el = document.querySelectorAll(sel)[index];
  const moving = document.getAnimations().some(a => a.playState === 'running'
    && a.effect && a.effect.target && a.effect.target.contains(el));
  const r = el.getBoundingClientRect();
  const x = r.left + r.width / 2, y = r.top + r.height / 2;
  const onScreen = y >= 0 && y <= innerHeight && x >= 0 && x <= innerWidth;
  const hit = onScreen ? document.elementFromPoint(x, y) : null;
  return {ok: !moving, x, y, onScreen, hitsIt: !!hit && (hit === el || el.contains(hit))};
}"""


def tap_on(page, touch, sel: str, index: int = 0) -> None:
    """נגיעה באלמנט שעל המסך, כשהוא כבר לא זז. אלמנט שאינו על המסך הוא כישלון הבדיקה, לא דילוג.

    ``hitsIt`` הוא תנאי מקדים ולא ההוכחה שהנגיעה הגיעה: במגע הדפדפן יכול להצמיד
    נגיעה לכפתור סמוך, ולכן מי שבודק **לאן** הגיעה נגיעה מודד את זה מהאירוע עצמו.
    """
    c = poll(page, CENTER_JS, f"{sel}[{index}] הפסיק לזוז", [sel, index])
    assert c["onScreen"] and c["hitsIt"], f"{sel}[{index}] אינו על המסך במקום שאפשר לגעת בו: {c}"
    touch.tap(c["x"], c["y"])


#: מה שכל עמוד צריך לפני הטעינה: מודאל הפתיחה וסיור ההיכרות לא קופצים, כמו אצל
#: משתמש שכבר ראה אותם.
_SEEN_ONBOARDING = {"welcomeModalSeen": "1", "onboarding_completed": "1"}


def open_admin_page(browser, server, path: str, *, viewport: dict, local_storage: dict | None = None):
    """עמוד אמיתי של אדמין במגע של טאבלט, בדפדפן ש**כבר** הורם. מחזיר ``(page, Touch)``.

    ``server`` הוא ``admin_live_server``, וה-session שלו נכנס כעוגייה. ``local_storage``
    נזרע לפני הטעינה, ולכן העמוד עולה כמו אצל משתמש שבחר בהגדרות האלה בעבר. בקשות
    לכל מארח אחר נקטעות, כך שגופנים וסקריפטים מ-CDN אינם נטענים — מי שנשען עליהם
    צריך לדעת את זה.
    """
    context = browser.new_context(
        viewport=viewport, device_scale_factor=2, is_mobile=True, has_touch=True, locale="he-IL",
    )
    context.add_cookies([{
        "name": "session", "value": server.session_cookie,
        "domain": "127.0.0.1", "path": "/",
    }])
    page = context.new_page()
    seed = {**_SEEN_ONBOARDING, **(local_storage or {})}
    page.add_init_script(
        "try{" + "".join(f"localStorage.setItem({json.dumps(k)},{json.dumps(v)});" for k, v in seed.items())
        + "}catch(e){}"
    )
    page.route("**/*", lambda route: route.abort()
               if urlsplit(route.request.url).hostname != "127.0.0.1" else route.continue_())
    page.goto(f"{server.base_url}{path}", wait_until="load")
    # מודאל הפתיחה מכסה את העמוד ובולע נגיעות.
    page.evaluate(
        "document.querySelectorAll('.welcome-modal, .welcome-modal__backdrop,"
        " #welcomeModal').forEach(e => e.remove())"
    )
    return page, Touch(context.new_cdp_session(page))
