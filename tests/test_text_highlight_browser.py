"""``TextHighlight.highlightWithin`` ו-``clearHighlights`` בכרומיום אמיתי.

**למה כאן ולא בבדיקת היחידה.** שתי הפונקציות האלה שואלות את הדפדפן שלוש
שאלות: איך ``TreeWalker`` מדלג על תת-עץ שנדחה, מה ``matches('svg')`` מחזיר
לאלמנט במרחב השמות של SVG, ומה ``normalize`` עושה לצמתי הטקסט שנשארו אחרי
הסרת עטיפה. דמות שנכתבה ביד הייתה עונה על שלושתן לפי מה שכותב הדמות חושב
— ובדיוק על השאלה הראשונה הזו נפל המימוש הקודם במסמך, שהשווה ``tagName``
ל-``'SVG'`` בזמן שהדפדפן מחזיר ``'svg'``.

הליבה הטהורה (כללי ההתאמה) נבדקת ב-``tests/text-highlight.test.js``.

מדולג כשאין Chromium.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "webapp" / "static"

#: ה-DOM שכל בדיקה מתחילה ממנו. כל אלמנט כאן מייצג מקרה אחד:
#: טקסט רגיל, התאמה שחוצה גבול בין צמתים, SVG (כולל ``<style>`` שבתוכו
#: ו-``foreignObject`` עם HTML), ``script`` ו-``style`` של העמוד, תת-עץ
#: שהצרכן ביקש לדלג עליו, ו-``details`` סגור.
FIXTURE = (
    '<p id="plain">alpha beta alpha</p>'
    '<p id="split">Alpha <b>alp</b>ha</p>'
    '<svg id="diagram" width="10" height="10"><style>.alpha{fill:red}</style>'
    '<text x="0" y="9">alpha</text>'
    '<foreignObject width="10" height="10"><div>alpha</div></foreignObject></svg>'
    '<script type="text/plain">alpha</script>'
    "<style>.alpha{color:red}</style>"
    '<span class="skip-me">alpha</span>'
    "<details><summary>alpha</summary><div>alpha</div></details>"
)

#: המופעים שצריכים להיעטף: שניים ב-``#plain``, ‏``Alpha`` ב-``#split``,
#: ואחד ב-``summary`` ואחד בגוף ה-``details``. לא ב-SVG, לא ב-``script``/
#: ``style``, ולא ב-``.skip-me``.
EXPECTED_HITS = 5

PAGE = """<!doctype html>
<html dir="rtl" lang="he"><head><meta charset="utf-8"></head><body>
<div id="root"></div>
<script src="/js/utils/text-highlight.js"></script>
</body></html>
"""


@pytest.fixture(scope="module")
def page(chromium_executable):
    """עמוד אחד לכל הקובץ; כל בדיקה מאפסת את ``#root`` בעצמה.

    הקבצים מוגשים דרך ``page.route`` מהדיסק, ולכן שום דבר אינו נכתב לתוך
    ``webapp/static`` ואין צורך בשרת.
    """

    def serve(route):
        path = urlsplit(route.request.url).path
        if path == "/page.html":
            route.fulfill(status=200, content_type="text/html", body=PAGE)
            return
        target = (STATIC_DIR / path.lstrip("/")).resolve()
        if not target.is_file() or STATIC_DIR.resolve() not in target.parents:
            route.fulfill(status=404, body="")
            return
        route.fulfill(
            status=200,
            content_type="application/javascript",
            body=target.read_text(encoding="utf-8"),
        )

    with sync_playwright() as p:
        try:
            browser = (
                p.chromium.launch(executable_path=chromium_executable)
                if chromium_executable
                else p.chromium.launch()
            )
        except Exception as exc:  # noqa: BLE001 — כל כשל השקה פירושו אין דפדפן
            pytest.skip(f"אין Chromium זמין: {exc}")
        try:
            pg = browser.new_page()
            errors: list[str] = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.route("**/*", serve)
            pg.goto("http://highlight.test/page.html")
            assert pg.evaluate("typeof window.TextHighlight") == "object", errors
            yield pg
            assert errors == [], f"שגיאות בעמוד: {errors}"
        finally:
            browser.close()


def _reset(pg) -> None:
    pg.evaluate("(html) => { document.getElementById('root').innerHTML = html; }", FIXTURE)


def test_wraps_only_visible_text_in_document_order(page):
    _reset(page)
    result = page.evaluate(
        """() => {
          const root = document.getElementById('root');
          const svgBefore = document.getElementById('diagram').innerHTML;
          const textBefore = root.textContent;
          const wraps = TextHighlight.highlightWithin(root, 'alpha',
            { className: 'hit', skip: '.skip-me' });
          let ordered = true;
          for (let i = 1; i < wraps.length; i++) {
            if (!(wraps[i - 1].compareDocumentPosition(wraps[i]) & Node.DOCUMENT_POSITION_FOLLOWING)) ordered = false;
          }
          return {
            count: wraps.length,
            inDom: root.querySelectorAll('.hit').length,
            tags: [...new Set(wraps.map(w => w.tagName))],
            texts: wraps.map(w => w.textContent),
            ordered,
            svgUntouched: document.getElementById('diagram').innerHTML === svgBefore,
            svgHits: document.querySelectorAll('#diagram .hit').length,
            // ``:scope >`` כי גם ב-SVG יש ``style``, והוא ראשון בסדר המסמך.
            scriptText: root.querySelector(':scope > script').textContent,
            styleText: root.querySelector(':scope > style').textContent,
            svgStyleText: document.querySelector('#diagram style').textContent,
            skipped: root.querySelector('.skip-me').innerHTML,
            splitHtml: document.getElementById('split').innerHTML,
            textSame: root.textContent === textBefore,
          };
        }"""
    )
    assert result["count"] == EXPECTED_HITS
    assert result["inDom"] == EXPECTED_HITS, "כל עטיפה שהוחזרה נמצאת בעץ"
    assert result["tags"] == ["SPAN"], "ברירת המחדל לתגית היא span"
    assert result["texts"] == ["alpha", "alpha", "Alpha", "alpha", "alpha"]
    assert result["ordered"], "העטיפות מוחזרות בסדר המסמך"
    # זה התיקון: הבדיקה הקודמת לפי ``tagName`` לא תפסה SVG לעולם.
    assert result["svgUntouched"] and result["svgHits"] == 0, "לא נוגעים בתוך SVG"
    assert result["svgStyleText"] == ".alpha{fill:red}", "ה-CSS שבתוך הדיאגרמה שלם"
    assert result["scriptText"] == "alpha" and result["styleText"] == ".alpha{color:red}"
    assert result["skipped"] == "alpha", "הסלקטור שהצרכן הוסיף מדלג על תת-העץ"
    # התאמה שחוצה גבול בין צמתים אינה נתפסת — מתועד ב-docstring של הפונקציה.
    assert result["splitHtml"] == '<span class="hit">Alpha</span> <b>alp</b>ha'
    assert result["textSame"], "אף תו לא נוסף ולא נמחק"


def test_second_call_replaces_instead_of_nesting(page):
    _reset(page)
    result = page.evaluate(
        """() => {
          const root = document.getElementById('root');
          const opts = { className: 'hit', skip: '.skip-me' };
          TextHighlight.highlightWithin(root, 'alpha', opts);
          const again = TextHighlight.highlightWithin(root, 'alpha', opts);
          const other = TextHighlight.highlightWithin(root, 'beta', opts);
          return {
            again: again.length,
            nested: root.querySelectorAll('.hit .hit').length,
            afterOther: root.querySelectorAll('.hit').length,
            otherTexts: other.map(w => w.textContent),
            empty: TextHighlight.highlightWithin(root, '', opts).length,
            afterEmpty: root.querySelectorAll('.hit').length,
          };
        }"""
    )
    assert result["again"] == EXPECTED_HITS
    assert result["nested"] == 0, "אין עטיפה בתוך עטיפה"
    assert result["afterOther"] == 1 and result["otherTexts"] == ["beta"], "מונח חדש מחליף את הקודם"
    assert result["empty"] == 0 and result["afterEmpty"] == 0, "מונח ריק מנקה"


def test_clear_restores_the_original_tree(page):
    _reset(page)
    result = page.evaluate(
        """() => {
          const root = document.getElementById('root');
          const countTextNodes = () => {
            const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
            let n = 0; while (w.nextNode()) n++; return n;
          };
          const htmlBefore = root.innerHTML;
          const nodesBefore = countTextNodes();
          TextHighlight.highlightWithin(root, 'alpha', { className: 'hit', skip: '.skip-me' });
          const nodesDuring = countTextNodes();
          const removed = TextHighlight.clearHighlights(root, 'hit');
          return { removed, same: root.innerHTML === htmlBefore,
                   nodesBefore, nodesDuring, nodesAfter: countTextNodes() };
        }"""
    )
    assert result["removed"] == EXPECTED_HITS
    assert result["same"], "ה-HTML חוזר להיות זהה"
    # ``normalize`` הוא מה שמאחד את השאריות: בלעדיו מספר צמתי הטקסט היה
    # נשאר גבוה גם כשה-HTML נראה זהה.
    assert result["nodesDuring"] > result["nodesBefore"]
    assert result["nodesAfter"] == result["nodesBefore"], "אותו מספר צמתי טקסט כמו בהתחלה"


def test_invalid_skip_selector_is_loud(page):
    """סלקטור שגוי הוא שגיאת קורא, ו-``matches`` זורק ``SyntaxError`` — לא בולעים."""
    _reset(page)
    name = page.evaluate(
        """() => {
          try {
            TextHighlight.highlightWithin(document.getElementById('root'), 'alpha',
              { className: 'hit', skip: '[[' });
            return 'no error';
          } catch (e) { return e.name; }
        }"""
    )
    assert name == "SyntaxError"
