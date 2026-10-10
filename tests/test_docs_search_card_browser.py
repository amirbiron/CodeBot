"""כרטיסי החיפוש בתיעוד — בכרומיום אמיתי, בעמוד ``/files`` האמיתי.

**מה נבדק.** אדמין בוחר "תיעוד", מחפש, ומקבל לכל סעיף כרטיס מימין לשמאל, שבתוכו הסעיף מרונדר
כמו בתצוגת ה-Markdown של דפדפן הריפו: הערה (``::: note``) ותרשים Mermaid, דרך
``MarkdownLiveRenderer`` והבאנדל שהטוען המשותף מביא. סביב זה: קובץ המקור בראש הכרטיס, הקישור
לאתר, ההעתקה כמארקדאון, הקיפול של סעיף ארוך — כפתור שמראה את המצב שהסעיף בו, וחזרה לכרטיס אחרי
כיווץ — שורת המצב, ההודעה כשהאינדקס לא זמין, ושומר הרצף — תשובה של חיפוש ישן שמגיעה אחרונה לא
דורסת את החדש.

**מה מזויף.** רק התשובה של ``POST /api/search/docs``, דרך ``page.route``: היא נבדקת לבד ב-
``tests/test_docs_search_service.py``, וכאן נבדק מה הדפדפן עושה איתה. השאר אמיתי — התבנית,
ה-CSS, ה-JS, הבאנדל, וה-CSP של העמוד. בקשות לכל מארח אחר נקטעות (``open_admin_page``).

מדולג כשאין Chromium, וגם כשאין מונגו אמיתי: ``/files`` מריץ צינורות ``aggregate`` שהדמה של המסד
אינה מכירה, כמו ב-``tests/test_card_preview_copy_browser.py``.
"""

from __future__ import annotations

import contextlib
import json
import re
import time
from urllib.parse import urlsplit

import pytest

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _browser_harness import open_admin_page, poll

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import Error as PlaywrightError  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

TABLET = {"width": 1280, "height": 800}
#: מסך נמוך, שהכרטיס המכווץ של ``LONG_SECTION`` גבוה ממנו (הטסטים שמשתמשים בו בודקים את זה).
SHORT_SCREEN = {"width": 1280, "height": 560}
COMMIT = "990a666b" + "0" * 32

#: סעיף ארוך מהגובה המקופל, עם הערה, תרשים, כותרת שחוזרת גם בסעיף השני, וקוד.
LONG_SECTION = "\n".join(
    [
        "החיפוש בעמוד הקבצים מחפש בתוכן הקבצים שלך.",
        "",
        "::: note",
        "הערה עם **הדגשה** ו-`קוד`.",
        ":::",
        "",
        "## דוגמה",
        "",
        "```mermaid",
        "flowchart TD",
        "  A[שאלה] --> B{אינדקס}",
        "  B --> C[סעיפים]",
        "```",
        "",
        "```python",
        "def search(query):",
        "    return run(query)",
        "```",
        "",
    ]
    + [f"שורה {i} בסעיף הארוך, כדי שיהיה מה לקפל." for i in range(1, 41)]
)
SHORT_SECTION = "## דוגמה\n\nסעיף קצר."

RESULTS = [
    {
        "section_id": "webapp/global-search.html#global-search-types",
        "title": "סוגי החיפוש",
        "breadcrumb": ["חיפוש גלובלי", "סוגי החיפוש"],
        "page_title": "חיפוש גלובלי",
        "page_path": "webapp/global-search.html",
        "source_path": "docs/webapp/global-search.rst",
        "anchor": "global-search-types",
        "url": "https://amirbiron.github.io/CodeBot/webapp/global-search.html#global-search-types",
        "markdown": LONG_SECTION,
        "score": 0.8312,
    },
    {
        "section_id": "webapp/global-search.html#docs-index",
        "title": "אינדקס התיעוד",
        "breadcrumb": ["חיפוש גלובלי", "אינדקס התיעוד"],
        "page_title": "חיפוש גלובלי",
        "page_path": "webapp/global-search.html",
        "source_path": "docs/webapp/global-search.rst",
        "anchor": "docs-index",
        "url": "https://amirbiron.github.io/CodeBot/webapp/global-search.html#docs-index",
        "markdown": SHORT_SECTION,
        "score": 0.71,
    },
]


def ok_response(results=RESULTS, *, commit=COMMIT, complete=True) -> dict:
    return {"ok": True, "results": results, "source_commit": commit, "index_complete": complete}


class DocsApi:
    """התשובות של ``/api/search/docs``, לפי הסדר. ``None`` במקום תשובה — הבקשה נשארת באוויר
    עד ש-``release`` נקרא, כמו שרת שעוד מטמיע את השאלה."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests: list[dict] = []
        self.held: list = []
        #: כל בקשה של העמוד לנתיב תחת ``/api/search/``, לפי הסדר — גם לנתיבים שאינם מזויפים כאן.
        self.searched: list[str] = []

    def record(self, request):
        path = urlsplit(request.url).path
        if path.startswith("/api/search/"):
            self.searched.append(path)

    def handle(self, route):
        self.requests.append(json.loads(route.request.post_data or "{}"))
        answer = self.answers.pop(0)
        if answer is None:
            self.held.append(route)
            return
        status, body = answer
        route.fulfill(status=status, content_type="application/json", body=json.dumps(body))

    def release(self, status, body):
        self.held.pop(0).fulfill(status=status, content_type="application/json", body=json.dumps(body))


@contextlib.contextmanager
def files_page(server, executable, api: DocsApi, viewport=TABLET):
    """עמוד הקבצים של האדמין עם הלוח מאושר — **המקום היחיד שמרים דפדפן כאן**."""
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=executable) if executable else pw.chromium.launch()
        except PlaywrightError as exc:  # pragma: no cover - תלוי בסביבה
            pytest.skip(f"אין Chromium זמין: {exc}")
        try:
            page, _touch = open_admin_page(browser, server, "/files", viewport=viewport)
            page.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=server.base_url)
            # נרשם אחרי הראוט הכללי של ``open_admin_page``, ולכן גובר עליו בכתובת הזו.
            page.route(re.compile(r".*/api/search/docs$"), api.handle)
            page.on("request", api.record)
            yield page
        finally:
            browser.close()


def search_docs(page, query: str) -> None:
    page.select_option("#searchType", "docs")
    page.fill("#globalSearchInput", query)
    page.click("#searchBtn")


#: הכרטיסים מרונדרים עד הסוף: כל הכרטיסים, התרשים של הראשון כבר SVG, וגוף הכרטיס האחרון —
#: שמרונדר אחרון — כבר לא ריק.
RENDERED_JS = """(count) => {
  const cards = document.querySelectorAll('[data-testid="docs-result"]');
  const svg = cards.length ? cards[0].querySelectorAll('.mermaid-diagram svg').length : 0;
  const last = cards.length ? cards[cards.length - 1].querySelector('[data-docs-body]').childElementCount : 0;
  return {ok: cards.length === count && svg === 1 && last > 0, cards: cards.length, svg, last};
}"""


def wait_rendered(page, cards: int = 2) -> None:
    poll(page, RENDERED_JS, f"{cards} כרטיסים, התרשים בראשון כבר מרונדר והאחרון כבר מלא", cards)


def test_a_section_is_rendered_in_its_card_right_to_left_like_in_the_repo_browser(
        admin_live_server, chromium_executable, wired_mongo):
    api = DocsApi((200, ok_response()))
    with files_page(admin_live_server, chromium_executable, api) as page:
        search_docs(page, "איך מחפשים בתיעוד")
        wait_rendered(page)
        card = page.evaluate("""() => {
          const card = document.querySelector('[data-testid="docs-result"]');
          const body = card.querySelector('.markdown-preview-content');
          const link = card.querySelector('a[target="_blank"]');
          const file = card.querySelector('.docs-result-file span');
          return {
            direction: getComputedStyle(card).direction,
            bodyDirection: getComputedStyle(body).direction,
            surface: !!body.closest('.markdown-preview-container'),
            admonition: !!body.querySelector('.admonition.admonition-note .admonition-title'),
            diagram: !!body.querySelector('.mermaid-diagram svg'),
            highlighted: !!body.querySelector('pre code.hljs'),
            file: file && file.textContent,
            fileDirection: file && getComputedStyle(file).direction,
            // הנתיב מתחיל מימין, כמו שאר השורות בראש הכרטיס.
            fileFromRight: file && (card.querySelector('.docs-result-heading').getBoundingClientRect().right
                                    - file.getBoundingClientRect().right),
            trail: card.querySelector('.docs-result-trail').textContent,
            title: card.querySelector('.docs-result-title').textContent,
            href: link && link.getAttribute('href'),
            rel: link && link.getAttribute('rel'),
          };
        }""")
        # החיפוש הסתיים כולו, ורק אז בודקים לאן נשלח: נפילה לחיפוש בקבצים הייתה יוצאת אחרי הכרטיסים.
        poll(page, "() => !document.getElementById('searchBtn').disabled", "החיפוש הסתיים")
        assert api.requests == [{"query": "איך מחפשים בתיעוד"}]
        # ההצעות להשלמה נשלחות בזמן ההקלדה, לכל סוג חיפוש, ואינן חיפוש.
        searches = [path for path in api.searched if path != "/api/search/suggestions"]
        assert searches == ["/api/search/docs"], api.searched

    assert card["direction"] == "rtl" and card["bodyDirection"] == "rtl", card
    assert card["surface"], "הסעיף אינו על המשטח של תצוגת ה-Markdown"
    assert card["admonition"] and card["diagram"] and card["highlighted"], card
    assert (card["file"], card["fileDirection"]) == (RESULTS[0]["source_path"], "ltr"), card
    assert abs(card["fileFromRight"]) < 1, card
    assert (card["trail"], card["title"]) == ("חיפוש גלובלי", "סוגי החיפוש"), card
    assert card["href"] == RESULTS[0]["url"]
    assert "noopener" in card["rel"].split(), card["rel"]


def test_the_status_line_names_the_indexed_commit_and_links_to_the_index_page(
        admin_live_server, chromium_executable, wired_mongo):
    api = DocsApi((200, ok_response(complete=False)))
    with files_page(admin_live_server, chromium_executable, api) as page:
        search_docs(page, "אינדקס")
        wait_rendered(page)
        status = page.evaluate("""() => {
          const el = document.querySelector('[data-testid="docs-search-status"]');
          const link = el.querySelector('a');
          return {text: el.textContent, warning: el.classList.contains('alert-warning'),
                  href: link && link.getAttribute('href'),
                  adminUrl: document.querySelector('#searchType option[value="docs"]').dataset.adminUrl};
        }""")

    assert COMMIT[:7] in status["text"], status
    assert status["warning"] and "לא מעודכן" in status["text"], status
    assert status["href"] == status["adminUrl"] == "/admin/docs-index", status


def test_copy_puts_the_whole_section_markdown_on_the_clipboard(admin_live_server, chromium_executable, wired_mongo):
    api = DocsApi((200, ok_response()))
    with files_page(admin_live_server, chromium_executable, api) as page:
        search_docs(page, "העתקה")
        wait_rendered(page)
        page.click('[data-testid="docs-result"] [data-docs-copy]')
        poll(page, "() => document.querySelector('[data-docs-copy]').textContent.includes('הועתק')",
             "הכפתור אישר העתקה")
        copied = page.evaluate("() => navigator.clipboard.readText()")

    assert copied == LONG_SECTION.strip()


def test_a_long_section_is_collapsed_until_asked_and_a_short_one_is_not(
        admin_live_server, chromium_executable, wired_mongo):
    api = DocsApi((200, ok_response()))
    with files_page(admin_live_server, chromium_executable, api) as page:
        search_docs(page, "קיפול")
        wait_rendered(page)
        state_js = """() => Array.from(document.querySelectorAll('[data-testid="docs-result"]')).map((card) => {
          const clip = card.querySelector('[data-docs-clip]');
          const button = card.querySelector('[data-docs-expand]');
          return {collapsed: clip.classList.contains('is-collapsed'), cut: clip.scrollHeight > clip.clientHeight,
                  button: !button.hidden, expanded: button.getAttribute('aria-expanded')};
        })"""
        before = page.evaluate(state_js)
        page.click('[data-testid="docs-result"] [data-docs-expand]')
        after = page.evaluate(state_js)

    long_card, short_card = before
    assert long_card == {"collapsed": True, "cut": True, "button": True, "expanded": "false"}, long_card
    assert short_card["collapsed"] is False and short_card["button"] is False, short_card
    assert after[0]["collapsed"] is False and after[0]["cut"] is False and after[0]["expanded"] == "true", after[0]


#: מה שכפתור ההרחבה של הכרטיס הראשון מראה, לצד המצב של הסעיף עצמו.
EXPAND_BUTTON_JS = """() => {
  const card = document.querySelector('[data-testid="docs-result"]');
  const button = card.querySelector('[data-docs-expand]');
  const icon = button.querySelector('i');
  return {collapsed: card.querySelector('[data-docs-clip]').classList.contains('is-collapsed'),
          expanded: button.getAttribute('aria-expanded'), icon: icon && icon.className,
          text: button.textContent.trim()};
}"""


#: איפה הכרטיס הראשון ביחס למסך, ומיקום הגלילה של העמוד — ``body`` ולא החלון (Issue #3534).
CARD_ON_SCREEN_JS = """() => {
  const rect = document.querySelector('[data-testid="docs-result"]').getBoundingClientRect();
  return {ok: rect.top >= 0 && rect.bottom <= window.innerHeight, top: rect.top, bottom: rect.bottom,
          screen: window.innerHeight, scrollTop: document.body.scrollTop};
}"""

#: מיקום הגלילה זהה בכמה דגימות רצופות — גלילה חלקה שהתחילה, למשל לראש התוצאות, כבר הסתיימה.
SCROLL_SETTLED_JS = """async () => {
  const samples = [];
  for (let i = 0; i < 5; i += 1) {
    samples.push(document.body.scrollTop);
    await new Promise((resolve) => requestAnimationFrame(resolve));
  }
  return {ok: samples.every((value) => value === samples[0]), samples};
}"""


@pytest.mark.parametrize("viewport", [TABLET, SHORT_SCREEN], ids=["tablet", "short-screen"])
def test_the_expand_button_shows_the_state_of_the_section_both_ways(
        admin_live_server, chromium_executable, wired_mongo, viewport):
    """הטקסט, האייקון ו-``aria-expanded`` מתחלפים יחד, בהרחבה ובכיווץ. עד התיקון הלחיצה החליפה רק את
    הטקסט ואת ``aria-expanded``, והאייקון נשאר של הרחבה גם כשהסעיף פתוח. וההרחבה לא גוללת: הסעיף
    נפתח כלפי מטה, והגלילה שייכת רק לכיווץ — גם במסך נמוך, שבו ראש הכרטיס המכווץ כבר מעל המסך
    כשמגיעים לכפתור."""
    api = DocsApi((200, ok_response()))
    with files_page(admin_live_server, chromium_executable, api, viewport=viewport) as page:
        search_docs(page, "הרחבה")
        wait_rendered(page)
        button = page.locator('[data-testid="docs-result"] [data-docs-expand]').first
        button.scroll_into_view_if_needed()
        poll(page, SCROLL_SETTLED_JS, "הגלילה אל הכפתור הסתיימה")
        states = [page.evaluate(EXPAND_BUTTON_JS)]
        before_expand = page.evaluate(CARD_ON_SCREEN_JS)
        button.click()
        states.append(page.evaluate(EXPAND_BUTTON_JS))
        scroll_after_expand = page.evaluate(CARD_ON_SCREEN_JS)["scrollTop"]
        button.click()
        states.append(page.evaluate(EXPAND_BUTTON_JS))

    collapsed = {"collapsed": True, "expanded": "false", "icon": "fas fa-up-right-and-down-left-from-center",
                 "text": "הצג את כל הסעיף"}
    expanded = {"collapsed": False, "expanded": "true", "icon": "fas fa-down-left-and-up-right-to-center",
                "text": "כווץ את הסעיף"}
    assert states == [collapsed, expanded, collapsed], states
    assert scroll_after_expand == before_expand["scrollTop"], (before_expand, scroll_after_expand)
    # המקרה שכל גודל מסך מייצג: בטאבלט ראש הכרטיס על המסך כשלוחצים, ובמסך הנמוך הוא כבר מעליו.
    assert (before_expand["top"] >= 0) == (viewport is TABLET), before_expand


#: ראש הכרטיס הראשון בראש המסך.
CARD_AT_TOP_JS = """() => {
  const rect = document.querySelector('[data-testid="docs-result"]').getBoundingClientRect();
  return {ok: Math.abs(rect.top) < 1, top: rect.top, bottom: rect.bottom, screen: window.innerHeight};
}"""


@pytest.mark.parametrize("viewport", [TABLET, SHORT_SCREEN], ids=["tablet", "short-screen"])
def test_collapsing_brings_the_top_of_the_card_back_on_screen(
        admin_live_server, chromium_executable, wired_mongo, viewport):
    """כפתור הכיווץ בתחתית הסעיף הפתוח, ולכן מגיעים אליו בגלילה. עד התיקון הסעיף התקצר מעל הכפתור
    והגלילה זזה רק בחלק מהקיצור, כך שהכרטיס כולו נשאר מעל המסך, ועל המסך היה תוכן אחר. עכשיו המסך
    חוזר לראש הכרטיס. במסך נמוך הכרטיס המכווץ גבוה מהמסך, וגם אז הראש — קובץ המקור והכותרת — הוא
    שחוזר, ולא התחתית (שם ``block: 'nearest'`` היה חותך את הראש)."""
    api = DocsApi((200, ok_response()))
    with files_page(admin_live_server, chromium_executable, api, viewport=viewport) as page:
        search_docs(page, "כיווץ")
        wait_rendered(page)
        button = page.locator('[data-testid="docs-result"] [data-docs-expand]').first
        button.click()
        button.scroll_into_view_if_needed()
        poll(page, SCROLL_SETTLED_JS, "הגלילה אל הכפתור הסתיימה")
        before = page.evaluate(CARD_ON_SCREEN_JS)
        button.click()
        after = poll(page, CARD_AT_TOP_JS, "ראש הכרטיס המכווץ בראש המסך")

    # התנאי שבלעדיו הטסט לא בודק כלום: ליד הכפתור, ראש הכרטיס הפתוח כבר מעל המסך.
    assert before["top"] < 0, before
    # והמקרה שכל גודל מסך מייצג: בטאבלט הכרטיס המכווץ נכנס במסך, ובמסך הנמוך הוא גבוה ממנו.
    fits = after["bottom"] - after["top"] <= after["screen"]
    assert fits == (viewport is TABLET), after


def test_collapsing_a_card_that_is_all_on_screen_does_not_scroll(admin_live_server, chromium_executable, wired_mongo):
    """כרטיס פתוח שכולו על המסך נשאר במקומו כשמכווצים אותו: הגלילה רק כשראש הכרטיס מעל המסך, ו-``start``
    בלי התנאי היה מקפיץ אותו לראש המסך בלי סיבה. המסך גבוה כדי שהסעיף הפתוח ייכנס בו, ויש מספיק
    כרטיסים מתחתיו כדי שהעמוד יוכל לגלול — אחרת גם קפיצה לא הייתה זזה, והטסט לא היה מבחין."""
    others = [dict(RESULTS[1], section_id=f"webapp/x.html#more-{n}", anchor=f"more-{n}", title=f"עוד סעיף {n}")
              for n in range(6)]
    api = DocsApi((200, ok_response(RESULTS + others)))
    with files_page(admin_live_server, chromium_executable, api, viewport={"width": 1280, "height": 2400}) as page:
        search_docs(page, "כיווץ במקום")
        wait_rendered(page, cards=2 + len(others))
        poll(page, SCROLL_SETTLED_JS, "הגלילה לראש התוצאות הסתיימה")
        page.click('[data-testid="docs-result"] [data-docs-expand]')
        before = poll(page, CARD_ON_SCREEN_JS, "הכרטיס הפתוח כולו על המסך")
        page.click('[data-testid="docs-result"] [data-docs-expand]')
        poll(page, SCROLL_SETTLED_JS, "אין גלילה באוויר")
        after = page.evaluate(CARD_ON_SCREEN_JS)
        room = page.evaluate("() => document.body.scrollHeight - document.body.clientHeight - document.body.scrollTop")

    # שני התנאים שבלעדיהם הטסט לא מבחין: הכרטיס לא בראש המסך, והעמוד יכול לגלול עד שיהיה שם.
    assert before["top"] > 10 and room >= before["top"], (before, room)
    assert (after["top"], after["scrollTop"]) == (before["top"], before["scrollTop"]), (before, after)


def test_the_file_name_is_shown_as_text_and_not_as_markup(admin_live_server, chromium_executable, wired_mongo):
    """הנתיב מגיע מהמסד ונכנס לכרטיס כטקסט (``escapeHtml``), כמו שמות קבצים בכל הממשק (``docs/security.rst``)."""
    hostile = 'docs/<img src="x" onerror="window.__docsPathRan = 1">.rst'
    api = DocsApi((200, ok_response([dict(RESULTS[0], source_path=hostile), RESULTS[1]])))
    with files_page(admin_live_server, chromium_executable, api) as page:
        search_docs(page, "נתיב")
        wait_rendered(page)
        shown = page.evaluate("""() => {
          const line = document.querySelector('[data-testid="docs-result"] .docs-result-file');
          return line ? {text: line.textContent, images: line.querySelectorAll('img').length,
                         ran: window.__docsPathRan === 1} : null;
        }""")

    assert shown == {"text": hostile, "images": 0, "ran": False}, shown


def test_ids_inside_a_card_do_not_collide_with_another_card(admin_live_server, chromium_executable, wired_mongo):
    """שני הסעיפים מכילים "## דוגמה". בלי הקידומת היו שני אלמנטים עם אותו ``id`` בעמוד."""
    api = DocsApi((200, ok_response()))
    with files_page(admin_live_server, chromium_executable, api) as page:
        search_docs(page, "מזהים")
        wait_rendered(page)
        ids = page.evaluate("""() => Array.from(document.querySelectorAll('[data-testid="docs-result"] h2'))
          .map((h) => {
            const anchor = h.querySelector('a.header-anchor');
            return [h.id, anchor ? anchor.getAttribute('href') : null];
          })""")

    assert len(ids) == 2 and ids[0][0] != ids[1][0], ids
    for heading_id, anchor_href in ids:
        assert anchor_href in (None, "#" + heading_id), (heading_id, anchor_href)


def test_the_bundle_comes_from_the_loader_folder_with_the_page_version(
        admin_live_server, chromium_executable, wired_mongo):
    """``markdown-deps.js`` נטען עם ``defer``, ובכל זאת ``document.currentScript`` מצביע עליו.

    הבדיקה העצמאית של הטוען (``tests/markdown-deps.test.js``) מדמה את ``currentScript``. כאן הוא
    אמיתי: הבאנדל התבקש מאותה תיקייה ועם אותו ``?v=`` כמו התגית בעמוד.
    """
    api = DocsApi((200, ok_response()))
    with files_page(admin_live_server, chromium_executable, api) as page:
        search_docs(page, "באנדל")
        wait_rendered(page)
        srcs = page.evaluate("""() => ({
          loader: document.querySelector('script[src*="/js/markdown-deps.js"]').src,
          bundles: Array.from(document.querySelectorAll('script[src*="md_preview.bundle.js"]')).map((s) => s.src),
        })""")

    loader = urlsplit(srcs["loader"])
    assert loader.query.startswith("v=") and len(srcs["bundles"]) == 1, srcs
    bundle = urlsplit(srcs["bundles"][0])
    assert bundle.path == loader.path.replace("markdown-deps.js", "md_preview.bundle.js"), srcs
    assert bundle.query == loader.query, srcs


def test_an_older_search_that_answers_last_does_not_replace_the_newer_one(
        admin_live_server, chromium_executable, wired_mongo):
    """החיפוש הראשון נתקע אצל השרת, השני עונה מיד, ורק אז הראשון חוזר.

    בלי שומר הרצף, מי שעונה אחרון נכתב אחרון — והשאלה הישנה הייתה מוצגת מתחת לחדשה. וגם
    הכפתור: החיפוש השני התחיל כשהכפתור כבר הראה "מחפש...", ובלי השמירה של המצב במנוחה הוא היה
    מחזיר את "מחפש..." לתמיד.
    """
    older = [dict(RESULTS[1], title="מהחיפוש הישן", breadcrumb=["ישן", "מהחיפוש הישן"])]
    api = DocsApi(None, (200, ok_response()))
    with files_page(admin_live_server, chromium_executable, api) as page:
        search_docs(page, "ישן")
        poll(page, "() => document.getElementById('searchBtn').disabled", "החיפוש הראשון באוויר")
        page.fill("#globalSearchInput", "חדש")
        page.press("#globalSearchInput", "Enter")
        wait_rendered(page)
        with page.expect_event("requestfinished", lambda request: "/api/search/docs" in request.url):
            api.release(200, ok_response(older))
        # התשובה הישנה כבר אצל הדף. כמה סבבים של לולאת האירועים, כדי שה-JS יספיק לטפל בה.
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            final = page.evaluate("""() => ({
              status: document.querySelector('[data-testid="docs-search-status"]').textContent,
              titles: Array.from(document.querySelectorAll('.docs-result-title')).map((t) => t.textContent),
              button: document.getElementById('searchBtn').textContent.trim(),
              disabled: document.getElementById('searchBtn').disabled,
            })""")
            assert "חדש" in final["status"] and "מהחיפוש הישן" not in final["titles"], final
            time.sleep(0.1)

    assert [r["query"] for r in api.requests] == ["ישן", "חדש"]
    assert final["titles"] == ["סוגי החיפוש", "אינדקס התיעוד"], final
    assert (final["button"], final["disabled"]) == ("חפש", False), final


def test_an_unavailable_index_says_why_and_links_to_the_index_page(
        admin_live_server, chromium_executable, wired_mongo):
    body = {"ok": False, "error": "index_unavailable", "reason": "vector_index_missing"}
    api = DocsApi((503, body))
    with files_page(admin_live_server, chromium_executable, api) as page:
        search_docs(page, "אין אינדקס")
        problem = poll(page, """() => {
          const el = document.querySelector('[data-testid="docs-search-problem"]');
          if (!el) return {ok: false};
          const link = el.querySelector('a');
          return {ok: true, text: el.textContent, href: link && link.getAttribute('href'),
                  cards: document.querySelectorAll('[data-testid="docs-result"]').length};
        }""", "הודעה על אינדקס שאינו זמין")

    assert "לא קיים" in problem["text"] and "vector_index_missing" in problem["text"], problem
    assert problem["href"] == "/admin/docs-index" and problem["cards"] == 0, problem


def test_choosing_docs_disables_the_filters_it_ignores(admin_live_server, chromium_executable, wired_mongo):
    """הסעיפים המובילים, בלי עמודים, מיון או שפות: פקד שנבחר בלי השפעה היה נראה כאילו השפיע."""
    api = DocsApi()
    filters_js = """() => ['resultsPerPage', 'sortOrder', 'languageFilterBtn']
      .map((id) => document.getElementById(id).disabled)"""
    with files_page(admin_live_server, chromium_executable, api) as page:
        page.select_option("#searchType", "docs")
        with_docs = page.evaluate(filters_js)
        page.select_option("#searchType", "content")
        with_content = page.evaluate(filters_js)
        page.select_option("#searchType", "docs")
        page.evaluate("() => clearSearch()")
        after_clear = page.evaluate(filters_js)

    assert with_docs == [True, True, True], with_docs
    assert with_content == [False, False, False], with_content
    assert after_clear == [False, False, False], after_clear
