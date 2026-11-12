"""החיפוש בתצוגת קובץ ובתצוגת Markdown רץ רק באנטר — בכרומיום, בעמודים האמיתיים.

**מה נבדק:** בעמוד ``/file/<id>``, בשתי התצוגות (הבסיסית ו-CodeMirror), ובעמוד
``/md/<id>``: הקלדה לבדה לא מחפשת; אנטר מחפש ומסמן את ההתאמה הראשונה; כל אנטר
נוסף מתקדם בדיוק התאמה אחת, ו-Shift+Enter חוזר אחת; שינוי הטקסט מנקה מיד; ▼ על
טקסט שעוד לא חיפשו מחפש; והחלפת תצוגה מחפשת שוב את מה שחיפשו — ולא טקסט
שהוקלד ועוד לא חיפשו. הכלל עצמו נבדק ב-CI ב-``tests/search-submit.test.js``; כאן
נבדק שהעמודים מחוברים אליו ושהמנועים מבצעים.

**העמוד אמיתי, המסד לא.** הדפדפן מקבל את מה שהראוט של Flask מגיש (דרך
``test_client``, כמו ב-``tests/test_markdown_external_images_browser.py``), כולל
``base.html``, ה-JS וחבילת CodeMirror מהדיסק. הקובץ נשמר בדמה (``_fake_mongo``),
ולכן הבדיקה רצה בלי מונגו. ``tests/test_view_file_scroll_browser.py`` בודק את
הגאומטריה של אותו חיפוש מול מונגו אמיתי.

**מה לא נבדק:** מקלדת וירטואלית של טאבלט — מה היא שולחת כשנוגעים במקש האנטר
שלה, וש-``enterkeyhint="search"`` מציג עליו "חיפוש". לפי התקן התכונה קובעת רק את
התווית (WHATWG HTML, ‏"The enterkeyhint attribute"); כאן נבדק רק שהיא קיימת.

מדולג כשאין Chromium.
"""

from __future__ import annotations

import itertools
from urllib.parse import urlsplit

import pytest
from bson import ObjectId

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _browser_harness import poll  # noqa: E402
from _fake_mongo import FakeDB  # noqa: E402

HOST = "ck.test"
OWNER_ID = 7162
CODE_OID = ObjectId("0123456789abcdef0123ab51")
MD_OID = ObjectId("0123456789abcdef0123ab52")
LETTERS_OID = ObjectId("0123456789abcdef0123ab53")
TERM = "zebra_marker"
FORWARDED_HEADERS = ("content-type", "cache-control", "etag")

#: שלוש התאמות. מספר אי-זוגי בכוונה: כשאנטר קידם שתי התאמות בכל לחיצה (ממצא 1
#: ב-#3477), עם שלוש התאמות השלישית לא הוצגה אף פעם.
CODE = "\n".join(
    f"value_{i:02d} = '{TERM}'" if i in (5, 15, 25) else f"value_{i:02d} = {i}"
    for i in range(1, 31)
) + "\n"
MARKDOWN = f"# כותרת\n\nפסקה עם {TERM} אחד.\n\nועוד {TERM}, ו-{TERM} שלישי.\n"
#: קוד בלי אף ספרה: כל ספרה בעמוד היא מספר שורה.
LETTERS = "".join(f"line_{chr(97 + i)} = '{chr(97 + i) * 3}'\n" for i in range(12))

_ADDRESSES = itertools.count(1)


@pytest.fixture(scope="module")
def site(chromium_executable):
    import webapp.app as wa

    db = FakeDB()
    for oid, name, code, lang in ((CODE_OID, "zebra.py", CODE, "python"),
                                  (MD_OID, "zebra.md", MARKDOWN, "markdown"),
                                  (LETTERS_OID, "letters.py", LETTERS, "python")):
        db["code_snippets"].insert_one({
            "_id": oid, "user_id": OWNER_ID, "file_name": name, "code": code,
            "programming_language": lang, "version": 1, "is_active": True,
        })
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(wa, "get_db", lambda: db)
        with sync_playwright() as pw:
            try:
                b = (
                    pw.chromium.launch(executable_path=chromium_executable)
                    if chromium_executable
                    else pw.chromium.launch()
                )
            except Exception as exc:  # noqa: BLE001 — כשל חולף בהרמה, אחרי שהשער כבר אמר שיש דפדפן
                pytest.skip(f"Chromium לא עלה: {exc}")
            try:
                yield b, wa
            finally:
                b.close()


def _client(wa):
    """‏``test_client`` עם כתובת IP משלו — מגבלת הקצב הגורפת משותפת לכל הטסטים בתהליך."""
    client = wa.app.test_client()
    client.environ_base["HTTP_X_FORWARDED_FOR"] = f"192.0.2.{next(_ADDRESSES) % 250 + 1}"
    with client.session_transaction() as sess:
        sess["user_id"] = OWNER_ID
        sess["user_data"] = {"id": OWNER_ID, "first_name": "בדיקה"}
    return client


def _open(site, path: str, *, view_mode: str = "basic"):
    b, wa = site
    client = _client(wa)
    errors: list[str] = []

    def handle(route, request):
        u = urlsplit(request.url)
        if u.hostname != HOST:
            return route.abort()
        target = u.path + (f"?{u.query}" if u.query else "")
        r = client.open(
            target, method=request.method, data=request.post_data_buffer,
            headers={"Content-Type": request.headers.get("content-type", "")},
        )
        headers = {k: v for k, v in r.headers.items() if k.lower() in FORWARDED_HEADERS}
        route.fulfill(status=r.status_code, body=r.data, headers=headers)

    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    ctx.add_init_script(f"try {{ localStorage.setItem('ck_view_mode', '{view_mode}'); }} catch (e) {{}}")
    ctx.route("**/*", handle)
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"http://{HOST}{path}")
    return ctx, page, errors


#: תצוגת קוד: המונה, מספר ההדגשות בתצוגה הבסיסית, והבחירה ב-CodeMirror.
CODE_STATE_JS = """() => {
  const v = window.__ck_view_cm_view;
  const sel = v ? v.state.selection.main : null;
  return {
    count: document.getElementById('searchCount').textContent,
    hits: document.querySelectorAll('#codeBasicContainer .md-highlight').length,
    cmSelected: sel ? v.state.sliceDoc(sel.from, sel.to) : null,
  };
}"""

MD_STATE_JS = """() => ({
  count: document.getElementById('mdSearchCount').textContent,
  hits: document.querySelectorAll('#md-content .md-highlight').length,
})"""


def _count(page, js, expected, what):
    poll(page, f"""() => {{ const s = ({js})(); return {{...s, ok: s.count === {expected!r}}}; }}""", what)


def test_basic_code_view_searches_only_on_enter(site):
    ctx, page, errors = _open(site, f"/file/{CODE_OID}")
    try:
        page.click("#codeSearchInput")
        page.keyboard.type(TERM)
        assert page.evaluate(CODE_STATE_JS)["count"] == ""
        assert page.evaluate(CODE_STATE_JS)["hits"] == 0, "הקלדה לבדה הדגישה"

        page.keyboard.press("Enter")
        _count(page, CODE_STATE_JS, "1/3", "אנטר חיפש ועמד על הראשונה")
        assert page.evaluate(CODE_STATE_JS)["hits"] == 3
        # כל אנטר — בדיוק התאמה אחת. השלישית מוצגת.
        page.keyboard.press("Enter")
        _count(page, CODE_STATE_JS, "2/3", "אנטר שני")
        page.keyboard.press("Enter")
        _count(page, CODE_STATE_JS, "3/3", "אנטר שלישי")
        page.keyboard.press("Shift+Enter")
        _count(page, CODE_STATE_JS, "2/3", "Shift+Enter")
        page.click("#nextMatchBtn")
        _count(page, CODE_STATE_JS, "3/3", "▼ מתקדם אחת")

        page.click("#codeSearchInput")
        page.keyboard.press("Backspace")
        assert page.evaluate(CODE_STATE_JS) == {"count": "", "hits": 0, "cmSelected": None}

        # ``zebra_marke`` — עדיין חלק מכל שלוש השורות. ▼ מחפש אותו, ועומד על הראשונה.
        page.click("#nextMatchBtn")
        _count(page, CODE_STATE_JS, "1/3", "▼ על טקסט שעוד לא חיפשו — חיפוש")
        assert page.get_attribute("#codeSearchInput", "enterkeyhint") == "search"
        assert errors == []
    finally:
        ctx.close()


def test_advanced_code_view_searches_only_on_enter_and_a_view_switch_reruns_what_was_searched(site):
    ctx, page, errors = _open(site, f"/file/{CODE_OID}", view_mode="advanced")
    try:
        poll(page, "() => !!window.__ck_view_cm_view && !document.getElementById('codeMirrorContainer').hidden",
             "התצוגה המתקדמת (CodeMirror) עלתה")
        page.click("#codeSearchInput")
        page.keyboard.type(TERM)
        assert page.evaluate(CODE_STATE_JS)["count"] == "", "הקלדה לבדה חיפשה ב-CodeMirror"

        page.keyboard.press("Enter")
        _count(page, CODE_STATE_JS, "1/3", "אנטר חיפש ב-CodeMirror")
        assert page.evaluate(CODE_STATE_JS)["cmSelected"] == TERM
        # הקפיצה קוראת ל-``viewInstance.focus()``, אבל תצוגה שאינה עריכה לא לוקחת את
        # הפוקוס — ולכן אנטר נוסף, בלי לגעת שוב בתיבה, מגיע לחיפוש.
        assert page.evaluate("document.activeElement.id") == "codeSearchInput"
        page.keyboard.press("Enter")
        _count(page, CODE_STATE_JS, "2/3", "אנטר שני")

        # החלפה לבסיסית: מה שחיפשו מחופש שוב שם.
        page.click("#viewModeToggleBtn")
        poll(page, "() => !document.getElementById('codeBasicContainer').hidden", "חזרה לתצוגה הבסיסית")
        _count(page, CODE_STATE_JS, "1/3", "החיפוש רץ שוב בתצוגה הבסיסית")
        assert page.evaluate(CODE_STATE_JS)["hits"] == 3

        # טקסט שהוקלד ולא חיפשו — ההחלפה לא מחפשת אותו.
        page.click("#codeSearchInput")
        page.keyboard.type("_x")
        assert page.evaluate(CODE_STATE_JS)["hits"] == 0, "שינוי הטקסט לא ניקה"
        page.click("#viewModeToggleBtn")
        poll(page, "() => !document.getElementById('codeMirrorContainer').hidden", "חזרה לתצוגה המתקדמת")
        state = page.evaluate(CODE_STATE_JS)
        assert state["count"] == "", state
        assert state["cmSelected"] in ("", None), state
        assert errors == []
    finally:
        ctx.close()


def test_markdown_view_searches_only_on_enter(site):
    ctx, page, errors = _open(site, f"/md/{MD_OID}")
    try:
        poll(page, "() => document.querySelectorAll('#md-content p').length >= 2", "המסמך רונדר")
        page.click("#mdSearchInput")
        page.keyboard.type(TERM)
        assert page.evaluate(MD_STATE_JS) == {"count": "", "hits": 0}, "הקלדה לבדה חיפשה"

        page.keyboard.press("Enter")
        _count(page, MD_STATE_JS, "1/3", "אנטר חיפש")
        page.keyboard.press("Enter")
        _count(page, MD_STATE_JS, "2/3", "אנטר שני")

        page.keyboard.press("Backspace")
        assert page.evaluate(MD_STATE_JS) == {"count": "", "hits": 0}, "שינוי הטקסט לא ניקה"
        assert page.get_attribute("#mdSearchInput", "enterkeyhint") == "search"
        assert errors == []
    finally:
        ctx.close()


def test_a_number_that_is_only_a_line_number_is_not_found(site):
    """ממצא 2 ב-#3477: מספרי השורות אינם חלק מהקוד. ``12`` מופיע כאן רק כמספר שורה."""
    ctx, page, errors = _open(site, f"/file/{LETTERS_OID}")
    try:
        page.fill("#codeSearchInput", "12")
        page.press("#codeSearchInput", "Enter")
        _count(page, CODE_STATE_JS, "אין תוצאות", "מספר שורה לא נספר")
        assert page.evaluate("document.querySelectorAll('.linenos .md-highlight, .linenodiv .md-highlight').length") == 0
        # ובקרה: טקסט מהקוד עצמו נמצא באותו עמוד.
        page.fill("#codeSearchInput", "line_l")
        page.press("#codeSearchInput", "Enter")
        _count(page, CODE_STATE_JS, "1/1", "טקסט מהקוד נמצא")
        assert errors == []
    finally:
        ctx.close()
