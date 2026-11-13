"""``TextHighlight.highlightWithin`` ו-``clearHighlights`` בכרומיום אמיתי.

**למה כאן ולא בבדיקת היחידה.** שתי הפונקציות האלה שואלות את הדפדפן שאלות
שרק הוא עונה עליהן נאמנה: איך ``TreeWalker`` מדלג על תת-עץ שנדחה, מה
``matches('svg')`` מחזיר לאלמנט במרחב השמות של SVG, ומה ``normalize`` עושה
לצמתי הטקסט שנשארו אחרי הסרת עטיפה. דמות שנכתבה ביד הייתה עונה עליהן לפי
מה שכותב הדמות חושב — ובדיוק על השאלה של SVG נפל המימוש הקודם במסמך, שהשווה
``tagName`` ל-``'SVG'`` בזמן שהדפדפן מחזיר ``'svg'``.

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

#: המופעים שצריכים להיעטף: שניים ב-``#plain``; ב-``#split`` גם ``Alpha`` וגם ``alpha`` שחציו מודגש
#: (``<b>alp</b>ha``) — התאמה שעוברת בין שני צמתי טקסט בתוך אותה שורה; ואחד ב-``summary`` ואחד בגוף
#: ה-``details``. לא ב-SVG, לא ב-``script``/``style``, ולא ב-``.skip-me``.
EXPECTED_HITS = 6

#: כמה עטיפות נוצרות: אחת לכל התאמה, ועוד אחת לחלק השני של ``alpha`` שחציו מודגש.
EXPECTED_WRAPS = 7

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
    assert result["count"] == EXPECTED_HITS, "התאמה אחת לכל מופע, גם כשהוא עטוף בשני חלקים"
    assert result["inDom"] == EXPECTED_WRAPS, "כל החלקים בעץ"
    assert result["tags"] == ["SPAN"], "ברירת המחדל לתגית היא span"
    # של ``alpha`` שחציו מודגש מוחזר החלק הראשון — ``alp`` שבתוך ה-``<b>``.
    assert result["texts"] == ["alpha", "alpha", "Alpha", "alp", "alpha", "alpha"]
    assert result["ordered"], "העטיפות מוחזרות בסדר המסמך"
    # זה התיקון: הבדיקה הקודמת לפי ``tagName`` לא תפסה SVG לעולם.
    assert result["svgUntouched"] and result["svgHits"] == 0, "לא נוגעים בתוך SVG"
    assert result["svgStyleText"] == ".alpha{fill:red}", "ה-CSS שבתוך הדיאגרמה שלם"
    assert result["scriptText"] == "alpha" and result["styleText"] == ".alpha{color:red}"
    assert result["skipped"] == "alpha", "הסלקטור שהצרכן הוסיף מדלג על תת-העץ"
    # התאמה שחוצה גבול בין צמתים בתוך אותה שורה נתפסת: כל צומת מקבל עטיפה משלו, עם מזהה התאמה משותף, והחלק השני
    # מסומן כהמשך. עד נובמבר 2026 נעטף כאן רק ``Alpha``.
    assert result["splitHtml"] == (
        '<span class="hit" data-hl-match="2">Alpha</span> <b><span class="hit" data-hl-match="3">alp</span></b>'
        '<span class="hit" data-hl-match="3" data-hl-continuation="">ha</span>'
    )
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
    assert result["removed"] == EXPECTED_WRAPS, "כל העטיפות הוסרו, כולל החלק השני של התאמה שעוברת בין צמתים"
    assert result["same"], "ה-HTML חוזר להיות זהה"
    # ``normalize`` הוא מה שמאחד את השאריות: בלעדיו מספר צמתי הטקסט היה
    # נשאר גבוה גם כשה-HTML נראה זהה.
    assert result["nodesDuring"] > result["nodesBefore"]
    assert result["nodesAfter"] == result["nodesBefore"], "אותו מספר צמתי טקסט כמו בהתחלה"


def test_scroll_into_view_within_scrolls_only_up_to_the_root(page):
    """``scrollIntoViewWithin`` גולל את המכלים שבין ההתאמה ל-``root`` בלבד, ורק כשצריך.

    הבקרה היא ``scrollIntoView`` על אותה התאמה, באותו עץ: הוא כן גולל גם את המכל החיצוני או את החלון —
    כלומר יש כאן אבות נגללים מעל ``root``, והבדיקה לא עוברת רק כי לא היה מה לגלול.
    """
    _reset(page)
    result = page.evaluate(
        """() => {
          const root = document.getElementById('root');
          root.innerHTML =
            '<div id="outer" style="height:300px;overflow:auto">' +
              '<div style="height:150px"></div>' +
              '<div id="box" style="height:100px;overflow:auto">' +
                '<div style="height:400px"></div><span id="far">far</span><div style="height:50px"></div>' +
              '</div>' +
              // מחוץ ל-``box`` אבל בתוך מכל נגלל: בלי הבדיקה שההתאמה בתוך ``root``, ההליכה ממנה
              // הייתה גוללת את ``outer``.
              '<div style="height:600px"></div><span id="elsewhere">elsewhere</span>' +
            '</div>' +
            '<div style="height:2000px"></div>';
          const outer = document.getElementById('outer');
          const box = document.getElementById('box');
          const far = document.getElementById('far');
          const scrolls = () => [box.scrollTop, outer.scrollTop, window.scrollY];
          const visible = () => {
            const h = far.getBoundingClientRect(), b = box.getBoundingClientRect();
            return h.top >= b.top && h.bottom <= b.bottom;
          };
          const before = scrolls();
          TextHighlight.scrollIntoViewWithin(box, far);
          const after = scrolls();
          const shown = visible();
          TextHighlight.scrollIntoViewWithin(box, far);
          const again = scrolls();
          TextHighlight.scrollIntoViewWithin(box, document.getElementById('elsewhere'));
          const outside = scrolls();
          // ``root`` עצמו, כשהוא מחוץ לחלון של ``outer``: ``contains`` כולל את הצומת עצמו, ובלי הבדיקה
          // על ``hit === root`` ההליכה הייתה מתחילה מעליו וגוללת את ``outer``.
          outer.scrollTop = 500;
          const hidden = scrolls();
          TextHighlight.scrollIntoViewWithin(box, box);
          const itself = scrolls();
          outer.scrollTop = 0;
          box.scrollTop = 0;
          far.scrollIntoView({ block: 'center' });
          const control = scrolls();
          outer.scrollTop = 0;
          window.scrollTo(0, 0);
          return { before, after, shown, again, outside, hidden, itself, control };
        }"""
    )
    assert result["before"] == [0, 0, 0]
    box_top, outer_top, window_y = result["after"]
    assert box_top > 0 and outer_top == 0 and window_y == 0, result
    assert result["shown"], "ההתאמה בתוך החלון של המכל"
    assert result["again"] == result["after"], "התאמה שכבר גלויה אינה גוללת שוב"
    assert result["outside"] == result["after"], "התאמה מחוץ ל-root אינה גוללת דבר"
    assert result["hidden"][1] == 500 and result["itself"] == result["hidden"], "root עצמו אינו גולל דבר"
    assert result["control"][1] > 0 or result["control"][2] > 0, f"הבקרה לא גללה מעל root: {result}"


def test_a_hit_that_is_not_rendered_scrolls_to_its_nearest_rendered_ancestor(page):
    """התאמה בתוך ``<details>`` סגור מביאה אל העין את הבלוק עצמו, והתאמה מתחת ל-``display: none`` בלי
    אב מצויר עד ``root`` אינה גוללת דבר.

    המלבן של התאמה שאינה מצוירת אינו מתאר שום דבר על המסך: תחת ``display: none`` הוא אפס, והגלילה
    לפיו קפצה (נמדד בכרומיום: מ-300 ל-192) למקום שאין בו כלום.
    """
    _reset(page)
    result = page.evaluate(
        """() => {
          const root = document.getElementById('root');
          root.innerHTML = '<div id="box" style="height:200px;overflow:auto">' +
            '<div style="height:600px"></div>' +
            '<details id="closed"><summary>s</summary><p><span id="inside">alpha</span></p></details>' +
            '<div style="height:600px"></div>' +
            '<p style="display:none"><span id="none">alpha</span></p></div>';
          const box = document.getElementById('box');
          const closed = document.getElementById('closed');
          const shown = (el) => {
            const r = el.getBoundingClientRect(), b = box.getBoundingClientRect();
            return r.height > 0 && r.top >= b.top && r.bottom <= b.bottom;
          };
          box.scrollTop = 0;
          const closedBefore = shown(closed);
          TextHighlight.scrollIntoViewWithin(box, document.getElementById('inside'));
          const closedAfter = shown(closed);
          box.scrollTop = 300;
          TextHighlight.scrollIntoViewWithin(box, document.getElementById('none'));
          return { closedBefore, closedAfter, noneScroll: box.scrollTop, stillClosed: !closed.open };
        }"""
    )
    assert result["closedBefore"] is False, result
    assert result["closedAfter"] is True, "הבלוק הסגור עצמו נגלל אל העין"
    assert result["stillClosed"] is True, "הגלילה אינה פותחת את הבלוק"
    assert result["noneScroll"] == 300, "התאמה בלי אב מצויר עד root אינה גוללת"


def test_the_tex_source_inside_a_formula_is_not_scanned(page):
    """בנוסחה מוצג רק הילד הראשון של ``<semantics>``; מקור ה-TeX שב-``<annotation>`` אינו מוצג, ולכן גם
    אינו נספר.

    **הנוסחה היא פלט אמיתי של KaTeX** (``katex.renderToString`` מהבאנדל של התצוגה), ולא סימון שנכתב
    ביד — המבנה הוא מה שהספרייה מייצרת. ``display`` של ה-``annotation`` נמדד כאן, כדי שהבדיקה תיפול אם
    הנחת היסוד (שהיא אינה מוצגת) תשתנה. ``\\text{alpha}`` מוצג פעמיים בעמוד בלי ה-CSS של KaTeX — בעותק
    המעוצב ובעותק של MathML — ולכן שתי התאמות, ולא שלוש.
    """
    _reset(page)
    if page.evaluate("typeof window.katex") != "object":
        page.add_script_tag(url="/js/md_preview.bundle.js")
    result = page.evaluate(
        """() => {
          const root = document.getElementById('root');
          root.innerHTML = katex.renderToString('\\\\text{alpha} + x', { throwOnError: false });
          const annotation = root.querySelector('semantics > annotation');
          const wraps = TextHighlight.highlightWithin(root, 'alpha', { className: 'hit' });
          return {
            annotationDisplay: annotation ? getComputedStyle(annotation).display : null,
            annotationText: annotation ? annotation.textContent : null,
            count: wraps.length,
            inAnnotation: wraps.filter((w) => w.closest('annotation')).length,
          };
        }"""
    )
    assert result["annotationText"] == "\\text{alpha} + x", result
    assert result["annotationDisplay"] == "none", result
    assert result["inAnnotation"] == 0, result
    assert result["count"] == 2, result


def test_a_match_crosses_inline_elements_but_not_a_line_break(page):
    """התאמה עוברת דרך אלמנטים בתוך שורה — עיצוב, קוד, קישור, ``bdi`` — ולא דרך שום דבר אחר.

    כל מקרה כאן הוא ``alpha`` שמפוצל בין שני צמתי טקסט, ורק ההפרדה שביניהם שונה. ``br``, פסקה, תא ושורה של פתק
    (``div``) מפרידים, וגם תת-עץ שמדלגים עליו: הביטוי ממשיך שם למקום אחר, וההתאמה הייתה מחברת טקסט שאינו רציף.
    """
    _reset(page)
    result = page.evaluate(
        """() => {
          const root = document.getElementById('root');
          const cases = {
            em: '<p>al<em>pha</em></p>',
            link: '<p><a href="#">alp</a>ha</p>',
            nested: '<p><strong>a<code>lp</code></strong><mark>ha</mark></p>',
            bdi: '<p><code dir="rtl">alp<bdi>ha</bdi></code></p>',
            br: '<p>al<br>pha</p>',
            paragraphs: '<p>al</p><p>pha</p>',
            cells: '<table><tr><td>al</td><td>pha</td></tr></table>',
            lines: '<div>al</div><div>pha</div>',
            skipped: '<p>al<span class="skip-me">x</span>pha</p>',
          };
          const out = {};
          for (const [name, html] of Object.entries(cases)) {
            root.innerHTML = html;
            const hits = TextHighlight.highlightWithin(root, 'alpha', { className: 'hit', skip: '.skip-me' });
            out[name] = { hits: hits.length, wraps: root.querySelectorAll('.hit').length,
                          text: [...root.querySelectorAll('.hit')].map((w) => w.textContent).join('|') };
          }
          return out;
        }"""
    )
    assert result["em"] == {"hits": 1, "wraps": 2, "text": "al|pha"}, result["em"]
    assert result["link"] == {"hits": 1, "wraps": 2, "text": "alp|ha"}, result["link"]
    assert result["nested"] == {"hits": 1, "wraps": 3, "text": "a|lp|ha"}, result["nested"]
    assert result["bdi"] == {"hits": 1, "wraps": 2, "text": "alp|ha"}, result["bdi"]
    for name in ("br", "paragraphs", "cells", "lines", "skipped"):
        assert result[name] == {"hits": 0, "wraps": 0, "text": ""}, (name, result[name])


def test_hits_within_and_set_active_treat_a_split_match_as_one(page):
    """``hitsWithin`` מוצא מחדש התאמה אחת לכל מופע, ו-``setActive`` צובע את כל החלקים שלה — ורק שלה.

    צרכן שמוצא את ההתאמות מתוך העץ (המונה והניווט במסמך, הניווט בפתק) היה סופר כל חלק כהתאמה, וצרכן שמסמן את
    העטיפה שהוחזרה היה צובע רק את החלק הראשון.
    """
    _reset(page)
    result = page.evaluate(
        """() => {
          const root = document.getElementById('root');
          root.innerHTML = '<p>alpha <b>alp</b>ha alpha</p>';
          const opts = { className: 'hit' };
          const hits = TextHighlight.highlightWithin(root, 'alpha', opts);
          const again = TextHighlight.hitsWithin(root, 'hit');
          const active = (i) => {
            TextHighlight.setActive(root, 'hit', again[i]);
            return [...root.querySelectorAll('.hit')].map((w) => w.classList.contains('is-active') ? 1 : 0).join('');
          };
          const second = active(1);
          const third = active(2);
          TextHighlight.setActive(root, 'hit', null);
          return {
            hits: hits.length,
            sameHeads: again.length === hits.length && again.every((w, i) => w === hits[i]),
            second, third,
            cleared: root.querySelectorAll('.hit.is-active').length,
          };
        }"""
    )
    assert result["hits"] == 3
    assert result["sameHeads"] is True, "hitsWithin מחזיר את אותן עטיפות ש-highlightWithin החזיר"
    # ארבע עטיפות: alpha, ‏alp, ‏ha, ‏alpha. השנייה היא שני החלקים האמצעיים.
    assert result["second"] == "0110", result
    assert result["third"] == "0001", "המעבר לשלישית מוריד את הסימון משני החלקים של השנייה"
    assert result["cleared"] == 0, "setActive עם null רק מוריד"


def test_a_hebrew_file_name_with_an_isolated_extension_is_found_whole(page):
    """שם קובץ עברי שהסיומת שלו מבודדת ב-``<bdi>`` (``RtlCode.fillInlineCode``) נמצא כשמחפשים את כולו, או את
    הקטע שעובר מהשם לסיומת. בלי ההתאמה שעוברת בין צמתים — שתיהן לא היו נמצאות."""
    _reset(page)
    result = page.evaluate(
        """() => {
          const root = document.getElementById('root');
          root.innerHTML = '<p>ראו את <code dir="rtl">מדריך-תצוגת-Markdown-RTL.<bdi>md</bdi></code> כאן</p>';
          const find = (term) => {
            const hits = TextHighlight.highlightWithin(root, term, { className: 'hit' });
            return { hits: hits.length, parts: root.querySelectorAll('.hit').length };
          };
          return { whole: find('מדריך-תצוגת-Markdown-RTL.md'), across: find('RTL.md'), stem: find('Markdown') };
        }"""
    )
    assert result["whole"] == {"hits": 1, "parts": 2}, result
    assert result["across"] == {"hits": 1, "parts": 2}, result
    assert result["stem"] == {"hits": 1, "parts": 1}, result


#: פי כמה מותר לזמן של ``highlightWithin`` לגדול כשרצף אחד גדל פי ארבעה, בבדיקה שלמטה. מעבר לינארי גדל בערך פי ארבעה,
#: ומעבר שבודק את כל הטווחים לכל צומת — בערך פי שש-עשרה, ולכן הסף באמצע. נמדד ב-13.11.2026 בבדיקה עצמה, בכרומיום
#: 153: בקוד של היום פי 3.9–4.3 (3 הרצות), ובלולאה הקודמת (``wrapRanges`` בלי ``first``) פי 10.7–12.0 (6 הרצות).
LINEAR_GROWTH_LIMIT = 8


def test_a_long_run_with_many_matches_grows_linearly(page):
    """בלוק קוד גדול הוא רצף אחד עם הרבה צמתים (העטיפות של הדגשת התחביר), ובחיפוש מחרוזת קצרה ונפוצה יש בו גם הרבה
    התאמות. עטיפת ההתאמות צריכה לעבור על הצמתים ועל הטווחים פעם אחת, ולא לבדוק את כל הטווחים לכל צומת.

    **משווים זמן לזמן, ולא לתקרה בשניות** — כמו בדיקת הלינאריות של הסריקה האינלינית ב-
    ``tests/sticky-notes-target.test.js``: רצף מול רצף פי ארבעה ממנו, סבבים לסירוגין, והזמן הקצר ביותר לכל גודל.
    """
    _reset(page)
    result = page.evaluate(
        """([small, large]) => {
          const root = document.getElementById('root');
          const html = (n) => '<pre><code>' + Array.from({ length: n }, (_, i) => '<span class="t">ee' + i + '</span> ').join('')
            + '</code></pre>';
          const sizes = [small, large];
          const fastest = [Infinity, Infinity];
          const hits = [0, 0];
          for (let round = 0; round < 5; round++) {
            sizes.forEach((n, slot) => {
              root.innerHTML = html(n);
              const started = performance.now();
              hits[slot] = TextHighlight.highlightWithin(root, 'ee', { className: 'hit' }).length;
              fastest[slot] = Math.min(fastest[slot], performance.now() - started);
            });
          }
          root.innerHTML = '';
          return { fastest, hits, growth: fastest[1] / fastest[0] };
        }""",
        [2000, 8000],
    )
    assert result["hits"] == [2000, 8000], result
    assert result["growth"] < LINEAR_GROWTH_LIMIT, (
        f"הזמן גדל פי {result['growth']:.1f} כשהרצף גדל פי 4: {result['fastest']}"
    )


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
