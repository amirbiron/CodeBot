"""החיפוש במסמך של ``md_preview.html`` בכרומיום אמיתי, דרך הממשק שלו.

**הקוד נשלף מהתבנית, ולא נכתב כאן.** בלוק החיפוש הוא סקריפט אינליין בתוך
``md_preview.html``, ועמוד אמיתי דורש שרת ומסד. לכן הבדיקה שולפת מהתבנית את
תג הטעינה של ``utils/text-highlight.js`` ואת בלוק החיפוש עצמו, ומריצה אותם
על ``#md-content`` מינימלי. שינוי בתבנית — הסרת התג, או חזרה להדגשה משלה —
משנה את מה שרץ כאן.

**מה נבדק:** הקלדה מדגישה ומעדכנת את המונה, Enter ו-Shift+Enter מנווטים,
הכפתור מנקה, טקסט בתוך SVG אינו נספר, ועמוד שהמודול לא נטען בו משבית את
התיבה במקום לענות "אין תוצאות".

מדולג כשאין Chromium.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "webapp" / "static"
TEMPLATE = REPO_ROOT / "webapp" / "templates" / "md_preview.html"

#: תחילת בלוק החיפוש ותחילת מה שבא אחריו — שתי הערות שכבר קיימות בתבנית.
BLOCK_START = "    // חיפוש והדגשה בכל תוכן המסמך"
BLOCK_END = "    // Lazy loading לתמונות"

MODULE_TAG_RE = re.compile(r"<script[^>]*?utils/text-highlight\.js[^>]*?>\s*</script>")
SRC_ATTR_RE = re.compile(r'src="[^"]*"')


def search_block() -> str:
    src = TEMPLATE.read_text(encoding="utf-8")
    start = src.index(BLOCK_START)
    end = src.index(BLOCK_END, start)
    return src[start:end]


def module_tag() -> str:
    match = MODULE_TAG_RE.search(TEMPLATE.read_text(encoding="utf-8"))
    assert match, "לא נמצא תג טעינה של utils/text-highlight.js ב-md_preview.html"
    return SRC_ATTR_RE.sub('src="/js/utils/text-highlight.js"', match.group(0))


#: ה-DOM הוא מה שבלוק החיפוש נוגע בו: התיבה, הכפתורים והמונה (עם המזהים
#: מהתבנית), ו-``#md-content`` עם טקסט ודיאגרמה.
PAGE = """<!doctype html>
<html dir="rtl" lang="he"><head><meta charset="utf-8"></head><body>
  <input id="mdSearchInput"><span id="mdSearchCount"></span>
  <button id="mdSearchPrev">▲</button><button id="mdSearchNext">▼</button>
  <button id="mdSearchClear">✕</button>
  <div id="md-content">
    <p>Alice פוגשת את Bob, ו-alice שוב.</p>
    <svg width="60" height="20"><style>.alice{fill:red}</style><text x="0" y="15">Alice</text></svg>
  </div>
  __MODULE_TAG__
  <script>
    (function(){
      const container = document.getElementById('md-content');
      __SEARCH_BLOCK__
    })();
  </script>
</body></html>
"""


@pytest.fixture(scope="module")
def browser(chromium_executable):
    with sync_playwright() as p:
        try:
            b = (
                p.chromium.launch(executable_path=chromium_executable)
                if chromium_executable
                else p.chromium.launch()
            )
        except Exception as exc:  # noqa: BLE001 — כל כשל השקה פירושו אין דפדפן
            pytest.skip(f"אין Chromium זמין: {exc}")
        try:
            yield b
        finally:
            b.close()


def _open(browser, *, with_module: bool = True):
    html = PAGE.replace("__MODULE_TAG__", module_tag() if with_module else "")
    html = html.replace("__SEARCH_BLOCK__", search_block())

    def serve(route):
        path = urlsplit(route.request.url).path
        if path == "/page.html":
            route.fulfill(status=200, content_type="text/html", body=html)
            return
        target = (STATIC_DIR / path.lstrip("/")).resolve()
        if not target.is_file() or STATIC_DIR.resolve() not in target.parents:
            route.fulfill(status=404, body="")
            return
        route.fulfill(status=200, content_type="application/javascript",
                      body=target.read_text(encoding="utf-8"))

    page = browser.new_page()
    errors: list[str] = []
    warnings: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: warnings.append(m.text) if m.type == "warning" else None)
    page.route("**/*", serve)
    page.goto("http://md.test/page.html")
    return page, errors, warnings


def test_typing_highlights_counts_and_navigates(browser):
    page, errors, _ = _open(browser)
    page.fill("#mdSearchInput", "alice")
    first = page.evaluate(
        """() => ({
          count: document.getElementById('mdSearchCount').textContent,
          hits: document.querySelectorAll('#md-content .md-highlight').length,
          inSvg: document.querySelectorAll('#md-content svg .md-highlight').length,
          active: [...document.querySelectorAll('#md-content .md-highlight')]
                    .findIndex(el => el.classList.contains('is-active')),
        })"""
    )
    # שתי ההתאמות שבטקסט, ולא ה-Alice שבתוך הדיאגרמה.
    assert first == {"count": "1/2", "hits": 2, "inSvg": 0, "active": 0}

    # Enter אחרי מיקוד אוטומטי נשאר על הראשונה (justAutoFocused), והבא מתקדם.
    page.press("#mdSearchInput", "Enter")
    page.press("#mdSearchInput", "Enter")
    assert page.text_content("#mdSearchCount") == "2/2"
    page.press("#mdSearchInput", "Shift+Enter")
    assert page.text_content("#mdSearchCount") == "1/2"

    page.click("#mdSearchClear")
    after = page.evaluate(
        """() => ({
          hits: document.querySelectorAll('.md-highlight').length,
          count: document.getElementById('mdSearchCount').textContent,
          text: document.querySelector('#md-content p').innerHTML,
        })"""
    )
    assert after == {"hits": 0, "count": "", "text": "Alice פוגשת את Bob, ו-alice שוב."}
    assert errors == []
    page.close()


def test_without_the_module_the_box_is_disabled(browser):
    """היעדר המודול הוא היעדר יכולת: תיבה מושבתת עם הסבר, לא "אין תוצאות"."""
    page, errors, warnings = _open(browser, with_module=False)
    state = page.evaluate(
        """() => {
          const input = document.getElementById('mdSearchInput');
          return { disabled: input.disabled, title: input.title };
        }"""
    )
    assert state["disabled"] is True
    assert state["title"]
    assert any("text-highlight.js" in w for w in warnings), warnings
    assert errors == []
    page.close()
