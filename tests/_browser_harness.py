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
import struct
import time
import zlib
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

    # **שלושת השלבים של נגיעה, כל אחד לחוד** — למי שבודק מה קורה באמצעה, כשהאצבע
    # עוד על המסך (למשל: פתק שנגרר כבר עלה מעל שכניו). ``swipe`` ו-``tap`` בנויים מהם.

    def start(self, x, y):
        self.cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})

    def move(self, x, y):
        self.cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x, "y": y}]})

    def end(self):
        self.cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})

    def swipe(self, x, y, dx, dy, steps=8):
        self.start(x, y)
        for i in range(1, steps + 1):
            self.move(x + dx * i / steps, y + dy * i / steps)
        self.end()

    def tap(self, x, y):
        self.start(x, y)
        self.end()


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


#: **איפה הדפדפן צייר תו.** ביטוי JS של פונקציה ``(el, i) => DOMRect``: המלבן של התו במיקום ``i`` בטקסט של ``el``
#: (כמו ב-``el.textContent``, גם כשהטקסט מפוצל לכמה צמתים), או ``null`` כשאין תו כזה. ``CHAR_X_JS`` ו-``ONE_LINE_JS``
#: בנויים עליו; משבצים אותם בתוך סקריפט מדידה (``"const x = " + CHAR_X_JS``). עבר לכאן מ-
#: ``tests/test_md_auto_dir_browser.py`` כשבדיקה שנייה הייתה צריכה אותו (``tests/test_sticky_inline_code_dir_browser.py``).
CHAR_RECT_JS = """(el, i) => {
  const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  let n, seen = 0;
  while ((n = w.nextNode())) {
    if (i < seen + n.data.length) {
      const r = document.createRange();
      r.setStart(n, i - seen); r.setEnd(n, i - seen + 1);
      return r.getBoundingClientRect();
    }
    seen += n.data.length;
  }
  return null;
}"""

#: ``(el, i) => x``: המרכז האופקי, בפיקסלי CSS, של התו במיקום ``i``, או ``null``. כך בודקים סדר על המסך ולא ב-DOM:
#: ב-``--flag`` המקף הראשון צריך להיות משמאל ל-``f``, ובשם קובץ עברי הסיומת משמאל לשם.
CHAR_X_JS = """(el, i) => {
  const b = (""" + CHAR_RECT_JS + """)(el, i);
  return b ? b.left + b.width / 2 : null;
}"""

#: ``(el) => bool``: האם הטקסט של ``el`` כולו על שורת מסך אחת — התו הראשון והאחרון באותו גובה. **תנאי מקדים להשוואה
#: של ``CHAR_X_JS``**: בטקסט שנשבר לכמה שורות, תו בשורה השנייה יכול להיות מכל צד של תו בראשונה, וההשוואה אינה אומרת
#: דבר. כך קרה בבניית ``tests/test_sticky_inline_code_dir_browser.py``: שם קובץ בכותרת של כרטיס צר נשבר לשלוש שורות,
#: ובדיקת סדר אחת עברה בו במקרה.
ONE_LINE_JS = """(el) => {
  const rect = (""" + CHAR_RECT_JS + """);
  const first = rect(el, 0), last = rect(el, el.textContent.length - 1);
  if (!first || !last) return false;
  const mid = (b) => (b.top + b.bottom) / 2;
  return Math.abs(mid(first) - mid(last)) < first.height / 2;
}"""


#: ``(el) => {...}``: **הצורה של שם קובץ עברי שמפורק** (``FileName.parts`` ב-``utils/file-name.js``: עברית, ואחריה
#: חלק לטיני לפני הסיומת). השם מתחיל בצד ימין, החלק הלטיני האחרון משמאל לעברית, הנקודה משמאל לחלק הלטיני, והסיומת
#: משמאל לנקודה — כלומר הסיומת בקצה השמאלי. בלי הפירוק הנקודה והסיומת נדבקות לחלק הלטיני ויושבות בקצה הימני שלו,
#: באמצע השם. ``one_line`` — תנאי מקדים לשאר (``ONE_LINE_JS``). משותף ל-``tests/test_sticky_inline_code_dir_browser.py``,
#: ל-``tests/test_md_auto_dir_browser.py`` ול-``tests/test_file_name_display_browser.py``.
FILE_NAME_SHAPE_JS = """(el) => {
  const x = (""" + CHAR_X_JS + """);
  const t = el.textContent, dot = t.lastIndexOf('.');
  let hebrew = -1, tail = -1;
  for (let i = dot - 1; i >= 0; i--) if (/\\p{Script=Hebrew}/u.test(t[i])) { hebrew = i; break; }
  for (let i = hebrew + 1; i < dot; i++) if (/\\p{Script=Latin}/u.test(t[i])) { tail = i; break; }
  return {
    one_line: (""" + ONE_LINE_JS + """)(el),
    starts_right: hebrew === 0 || x(el, 0) > x(el, hebrew),
    tail_left_of_hebrew: x(el, tail) < x(el, hebrew),
    dot_left_of_tail: x(el, dot) < x(el, tail),
    extension_left_of_dot: x(el, dot + 1) < x(el, dot),
  };
}"""

#: בוחר את כל התוכן של האלמנט הראשון ב-``selector`` שהטקסט שלו הוא ``text``. ``false`` כשאין כזה.
_SELECT_FOR_COPY_JS = """([selector, text]) => {
  const el = [...document.querySelectorAll(selector)].find((e) => e.textContent === text);
  if (!el) return false;
  const range = document.createRange();
  range.selectNodeContents(el);
  const sel = getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
  return true;
}"""


def copied_to_clipboard(page, origin: str, selector: str, text: str) -> str:
    """**העתקה אמיתית ללוח:** בוחר את האלמנט שהטקסט שלו ``text``, לוחץ Ctrl+C כמו משתמש, וקורא את הלוח בחזרה
    (``navigator.clipboard.readText``). כך בודקים שהעתקה מחזירה את הטקסט כמו שנכתב — בלי תווי כיווניות נסתרים,
    וגם כשהוא מפוצל לכמה צמתים.

    ``origin`` מקבל הרשאת קריאה וכתיבה ללוח (``BrowserContext.grant_permissions``, ‏Playwright 1.49.0), והקריאה
    דורשת הקשר מאובטח — ``localhost`` או ``127.0.0.1`` מספיקים. נמדד בכרומיום 153 ב-13.11.2026: שם קובץ עברי
    שהסיומת שלו ב-``<bdi>`` חזר מהלוח זהה למקור.
    """
    page.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=origin)
    assert page.evaluate(_SELECT_FOR_COPY_JS, [selector, text]), f"לא נמצא {selector} עם הטקסט {text!r}"
    page.keyboard.press("Control+C")
    return page.evaluate("() => navigator.clipboard.readText()")


def tap_on(page, touch, sel: str, index: int = 0) -> None:
    """נגיעה באלמנט שעל המסך, כשהוא כבר לא זז. אלמנט שאינו על המסך הוא כישלון הבדיקה, לא דילוג.

    ``hitsIt`` הוא תנאי מקדים ולא ההוכחה שהנגיעה הגיעה: במגע הדפדפן יכול להצמיד
    נגיעה לכפתור סמוך, ולכן מי שבודק **לאן** הגיעה נגיעה מודד את זה מהאירוע עצמו.
    """
    c = poll(page, CENTER_JS, f"{sel}[{index}] הפסיק לזוז", [sel, index])
    assert c["onScreen"] and c["hitsIt"], f"{sel}[{index}] אינו על המסך במקום שאפשר לגעת בו: {c}"
    touch.tap(c["x"], c["y"])


#: איזה פתק מצויר למעלה באמצע החפיפה של שני פתקים — מה שהמשתמש רואה שם ונוגע בו.
#:
#: **לא ``z-index``:** הוא פרט מימוש, והשאלה היא מה הדפדפן מוצא בנקודה (``elementFromPoint``).
#: החלונית, הבועות והכותרת הם ילדים של הפתק, ולכן ``closest`` מחזיר את הפתק בכל אחד מהם.
#: ``ok: false`` כשהמלבנים אינם חופפים: נקודה מחוץ לחפיפה הייתה עונה בלי לבדוק את הסדר.
TOP_NOTE_IN_OVERLAP_JS = """([a, b]) => {
  const box = (id) => {
    const r = document.querySelector(`.sticky-note[data-note-id="${id}"]`).getBoundingClientRect();
    return {left: r.left, right: r.right, top: r.top, bottom: r.bottom};
  };
  const ra = box(a), rb = box(b);
  const left = Math.max(ra.left, rb.left), right = Math.min(ra.right, rb.right);
  const top = Math.max(ra.top, rb.top), bottom = Math.min(ra.bottom, rb.bottom);
  if (left >= right || top >= bottom) return {ok: false, why: 'הפתקים אינם חופפים', a: ra, b: rb};
  const x = (left + right) / 2, y = (top + bottom) / 2;
  const hit = document.elementFromPoint(x, y);
  const note = hit && hit.closest('.sticky-note');
  return {ok: true, x, y, top: note ? note.dataset.noteId : null,
          hit: hit ? (hit.className || hit.tagName) : null};
}"""


def top_note_in_overlap(page, a: str, b: str) -> dict:
    """מה מצויר באמצע החפיפה של הפתקים ``a`` ו-``b``: ``top`` הוא מזהה הפתק שלמעלה.

    פתקים שאינם חופפים הם כישלון של הבדיקה ולא תשובה — ראו ``TOP_NOTE_IN_OVERLAP_JS``.
    """
    res = page.evaluate(TOP_NOTE_IN_OVERLAP_JS, [a, b])
    assert res["ok"], f"בקרה: {res}"
    return res


def png_bytes(width: int, height: int) -> bytes:
    """PNG אדום בגודל נתון, בלי ספרייה — לתמונה ש-``route`` מגיש מ"אתר אחר": חתימה, ‏IHDR, ‏IDAT ו-IEND."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    rows = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


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
    if local_storage:
        page.add_init_script(
            "try{"
            + "".join(f"localStorage.setItem({json.dumps(k)},{json.dumps(v)});" for k, v in local_storage.items())
            + "}catch(e){}"
        )
    page.route("**/*", lambda route: route.abort()
               if urlsplit(route.request.url).hostname != "127.0.0.1" else route.continue_())
    page.goto(f"{server.base_url}{path}", wait_until="load")
    return page, Touch(context.new_cdp_session(page))
