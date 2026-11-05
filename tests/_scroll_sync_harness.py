"""מדידה של הגלילה המסונכרנת בין העורך לתצוגה החיה — לבדיקות הדפדפן של העורך הציבורי ושל עמוד העריכה.

**מה נמדד.** נקודת הקריאה של כל צד (ראש החלון כשהגלילה בהתחלה, התחתית בסוף, ובאמצע לפי היחס — ההסבר בראש
``webapp/static/js/live-preview-scroll-sync.js``), מול המיקום של שורה מסוימת: בעורך — ראש השורה לפי CodeMirror
(``lineBlockAt`` ו-``documentTop``), ובתצוגה — ראש האלמנט שמסומן בשורה (``data-source-line``). כשהסנכרון עובד,
שורה שמוצבת בנקודת הקריאה של צד אחד נמצאת בנקודת הקריאה של הצד השני.

**הבדיקה אינה משתמשת בחשבון של המנוע.** המיקומים נמדדים מה-DOM ומ-CodeMirror, ונקודת הקריאה היא ההגדרה של
ההתנהגות, ולא הקוד שמחשב אותה. ``proportional_delta`` מחשב מה גלילה לפי אחוזים (כמו ב-``/compare/paste``) הייתה
נותנת באותו מקום — כדי שהבדיקה תוכיח שהמסמך שלה מבדיל בין שתי השיטות.

**ולמה מציבים כמה פעמים.** CodeMirror מעריך את הגובה של שורות שעוד לא הוצגו, ומודד אותן כשהן נכנסות לחלון. אחרי
גלילה רחוקה המיקום של שורה משתנה, ולכן ``place_editor`` מחשב ומציב שוב, עד שהמיקום יציב.
"""

from __future__ import annotations

#: ``window.__syncProbe`` — מדידות בדף. נרשם פעם אחת לכל דף (``install``).
PROBE = r"""
window.__syncProbe = {
  view() { return window.editorManager.cmInstance; },
  canvas() { return document.querySelector('[data-preview-canvas]'); },
  // ראש השורה (0-based) בעורך, בפיקסלים מראש התוכן של הגולל.
  editorLineY(line) {
    const v = this.view(), sc = v.scrollDOM;
    const b = v.lineBlockAt(v.state.doc.line(line + 1).from);
    return v.documentTop + b.top - sc.getBoundingClientRect().top - sc.clientTop + sc.scrollTop;
  },
  previewEl(line) { return this.canvas().querySelector('[data-source-line="' + line + '"]'); },
  previewLineY(line) {
    const cv = this.canvas(), el = this.previewEl(line);
    return el.getBoundingClientRect().top - cv.getBoundingClientRect().top - cv.clientTop + cv.scrollTop;
  },
  reading(el) { const m = el.scrollHeight - el.clientHeight; return m > 0 ? el.scrollTop / m * el.scrollHeight : 0; },
  scrollForReading(el, y) { const m = el.scrollHeight - el.clientHeight; return m > 0 ? y * m / el.scrollHeight : 0; },
  state(line) {
    const sc = this.view().scrollDOM, cv = this.canvas();
    const eMax = sc.scrollHeight - sc.clientHeight, pMax = cv.scrollHeight - cv.clientHeight;
    return {
      editorDelta: this.editorLineY(line) - this.reading(sc),
      previewDelta: this.previewLineY(line) - this.reading(cv),
      // לפי אחוזים: התצוגה באותו יחס כמו העורך, והמרחק של השורה מנקודת הקריאה שלה.
      proportionalDelta: this.previewLineY(line) - (eMax > 0 ? sc.scrollTop / eMax : 0) * cv.scrollHeight,
      editorTop: sc.scrollTop, editorMax: eMax, previewTop: cv.scrollTop, previewMax: pMax,
    };
  },
  headings() {
    return Array.from(this.canvas().querySelectorAll(':is(h1,h2,h3)[data-source-line]'))
      .map((h) => Number(h.getAttribute('data-source-line')));
  },
  // האלמנט ה-``index`` שמתאים ל-``selector`` בתצוגה — לפי הסדר, ולא לפי הסימון שלו, כדי שהמדידה תעבוד גם כשאין לו
  // סימון (זה בדיוק מה שנבדק אצל הקונטיינרים) — מול השורה ``line`` בעורך.
  elementState(selector, index, line) {
    const cv = this.canvas(), sc = this.view().scrollDOM;
    const el = cv.querySelectorAll(selector)[index];
    const y = el.getBoundingClientRect().top - cv.getBoundingClientRect().top - cv.clientTop + cv.scrollTop;
    return {editorDelta: this.editorLineY(line) - this.reading(sc), previewDelta: y - this.reading(cv)};
  },
};
"""


def install(page) -> None:
    page.evaluate(PROBE)


def lead(page, selector: str) -> None:
    """גלגלת קטנה מעל ``selector``: כך הצד הזה הוא המוביל, כמו כשמשתמש מתחיל לגלול בו."""
    box = page.locator(selector).bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.wheel(0, 1)
    page.wait_for_timeout(50)


def settle(page, ms: int = 250) -> None:
    page.wait_for_timeout(ms)


def place_editor(page, line: int, passes: int = 4) -> None:
    """גולל את העורך כך שראש השורה ``line`` נמצא בנקודת הקריאה שלו."""
    for _ in range(passes):
        page.evaluate(
            "(line) => { const p = window.__syncProbe, sc = p.view().scrollDOM;"
            " sc.scrollTop = p.scrollForReading(sc, p.editorLineY(line)); }",
            line,
        )
        settle(page, 120)
    settle(page)


def place_preview(page, line: int, passes: int = 3) -> None:
    """גולל את התצוגה כך שראש האלמנט של השורה ``line`` נמצא בנקודת הקריאה שלה."""
    for _ in range(passes):
        page.evaluate(
            "(line) => { const p = window.__syncProbe, cv = p.canvas();"
            " cv.scrollTop = p.scrollForReading(cv, p.previewLineY(line)); }",
            line,
        )
        settle(page, 120)
    settle(page, 400)


def state(page, line: int) -> dict:
    return page.evaluate("(line) => window.__syncProbe.state(line)", line)


def headings(page) -> list[int]:
    return page.evaluate("() => window.__syncProbe.headings()")


def element_state(page, selector: str, index: int, line: int) -> dict:
    return page.evaluate(
        "([s, i, line]) => window.__syncProbe.elementState(s, i, line)", [selector, index, line]
    )
