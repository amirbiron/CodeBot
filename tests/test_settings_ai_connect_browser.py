"""הסעיף "חיבור סוכן AI" בעמוד ההגדרות — נמדד בדפדפן אמיתי.

בדיקת שרת מאמתת שה-HTML נוצר. היא אינה יכולה לאמת שהלשוניות מתחלפות, שכפתור ההעתקה
מעתיק בדיוק את הכתובת, שהעוגן ``#ai-connect`` מגיע לסעיף, או שהכתובת אינה דוחפת את
העמוד לרוחב בטלפון — כל אלה קורים רק בדפדפן.

הכתובת מגיעה מ-``MCP_SERVER_URL`` בכל טעינה של העמוד (``_mcp_connect_url`` ב-
``webapp/routes/settings_routes.py``), ולכן כל בדיקה קובעת אותו ב-``monkeypatch`` לפני
שהיא טוענת את העמוד: השרת רץ בחוט של אותו תהליך וקורא את אותה סביבה.

**"אין שגיאות בקונסול" — בשני חלקים.** לשרת הבדיקה אין מסד, ולכן קריאות API אחרות
בעמוד (ערכות נושא, הוראות לסוכן, תזכורות) עונות 500 ומדפיסות שגיאות שאינן קשורות לסעיף.
לכן: שגיאת JS שלא נתפסה (``pageerror``) אסורה **בכל העמוד**, ושגיאת קונסול אסורה כשמקורה
בסקריפט של הסעיף — לפי טווח השורות שלו בתשובה, ולא לפי הניסוח שלה.

הטסט מדולג בשקט כשאין Chromium. הרמת השרת ואיתור Chromium מגיעים מהפיקסצ'רים
המשותפים ב-``tests/conftest.py``.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

from _browser_harness import poll  # noqa: E402

MCP_BASE = "https://mcp.example.test"
PANELS = ("claude-web", "gemini", "claude-code")
#: מחרוזת שמופיעה רק בסקריפט של הסעיף — ממנה נגזר טווח השורות שלו.
SECTION_SCRIPT_MARK = "getElementById('ai-connect')"


class _PageErrors:
    """מה שהעמוד דיווח: שגיאות שלא נתפסו, ושגיאות קונסול עם המיקום שלהן."""

    def __init__(self):
        self.uncaught: list[str] = []
        self.console: list[tuple[str, dict]] = []
        self.section_lines: tuple[int, int] = (-1, -1)

    def relevant(self) -> list[str]:
        start, end = self.section_lines
        ours = [
            text for text, location in self.console
            if urlsplit(location.get("url") or "").path == "/settings"
            and start <= int(location.get("lineNumber", -1)) <= end
        ]
        return self.uncaught + ours


def _section_script_lines(html: str) -> tuple[int, int]:
    """טווח השורות (מאפס, כמו ``lineNumber`` של הקונסול) של תגית ה-``<script>`` של הסעיף."""
    mark = html.index(SECTION_SCRIPT_MARK)
    start = html.rindex("<script>", 0, mark)
    end = html.index("</script>", mark)
    return html.count("\n", 0, start), html.count("\n", 0, end)


@pytest.fixture(scope="module")
def browser(chromium_executable):
    executable = chromium_executable
    with sync_playwright() as pw:
        try:
            b = (
                pw.chromium.launch(executable_path=executable)
                if executable
                else pw.chromium.launch()
            )
        except Exception as exc:  # pragma: no cover
            pytest.skip(f"אין Chromium זמין: {exc}")
        with b:
            yield b


def _open(browser, server, *, width=1280, height=900, fragment="#ai-connect"):
    """עמוד ההגדרות, ואיתו ``_PageErrors`` שנאסף מהרגע הראשון של הטעינה."""
    context = browser.new_context(viewport={"width": width, "height": height})
    context.add_cookies([{
        "name": "session", "value": server.session_cookie,
        "domain": "127.0.0.1", "path": "/",
    }])
    page = context.new_page()
    errors = _PageErrors()
    page.on("pageerror", lambda exc: errors.uncaught.append(f"pageerror: {exc}"))
    page.on("console", lambda msg: msg.type == "error" and errors.console.append((msg.text, msg.location)))
    response = page.goto(f"{server.base_url}/settings{fragment}", wait_until="load")
    assert response is not None and response.status == 200
    errors.section_lines = _section_script_lines(response.text())
    return context, page, errors


def _state(page):
    """לכל לשונית: האם היא מסומנת, ב-tab order, והאם הפאנל שלה מוצג."""
    return page.evaluate("""() => Array.from(document.querySelectorAll('#ai-connect [role="tab"]')).map(t => {
        const panel = document.getElementById(t.getAttribute('aria-controls'));
        return {
            id: t.id,
            selected: t.getAttribute('aria-selected'),
            tabIndex: t.tabIndex,
            panelShown: !!panel && !panel.hidden && panel.getBoundingClientRect().height > 0,
        };
    })""")


def _expect_selected(page, key):
    state = _state(page)
    expected = [
        {"id": f"ai-connect-tab-{k}", "selected": "true" if k == key else "false",
         "tabIndex": 0 if k == key else -1, "panelShown": k == key}
        for k in PANELS
    ]
    assert state == expected


def test_clicking_a_tab_shows_its_panel_only(browser, admin_live_server, monkeypatch):
    monkeypatch.setenv("MCP_SERVER_URL", MCP_BASE)
    context, page, errors = _open(browser, admin_live_server)
    try:
        _expect_selected(page, "claude-web")
        page.click("#ai-connect-tab-gemini")
        _expect_selected(page, "gemini")
        page.click("#ai-connect-tab-claude-code")
        _expect_selected(page, "claude-code")
        page.click("#ai-connect-tab-claude-web")
        _expect_selected(page, "claude-web")
    finally:
        context.close()
    assert errors.relevant() == []


def test_the_menu_path_reads_right_to_left(browser, admin_live_server, monkeypatch):
    """שמות התפריט באנגלית מבודדים ב-``<bdi>``, ולכן החצים שביניהם נשארים בזרימה העברית.

    בלי הבידוד שלוש המילים והחצים הופכים לרצף אחד משמאל לימין, ו-Settings יושב משמאל —
    כלומר החצים מצביעים אחורה. נמדד במיקום: כל שם יושב משמאל לשם שלפניו.
    """
    monkeypatch.setenv("MCP_SERVER_URL", MCP_BASE)
    context, page, errors = _open(browser, admin_live_server)
    try:
        items = page.evaluate("""() => Array.from(document.querySelectorAll('#ai-connect-panel-claude-web bdi'))
            .map(b => ({text: b.textContent, right: b.getBoundingClientRect().right}))""")
    finally:
        context.close()
    assert [i["text"] for i in items] == ["Settings", "Connectors", "Add custom connector"]
    rights = [i["right"] for i in items]
    assert rights[0] > rights[1] > rights[2], items
    assert errors.relevant() == []


def test_the_bot_link_points_at_the_configured_bot(browser, admin_live_server, monkeypatch):
    """הקישור נבנה מ-``bot_username`` שהוובאפ כבר מזריק לכל תבנית — לא משם שהוקלד בתבנית."""
    import webapp.app as app_mod

    monkeypatch.setenv("MCP_SERVER_URL", MCP_BASE)
    context, page, errors = _open(browser, admin_live_server)
    try:
        page.click("#ai-connect-tab-claude-code")
        href = page.get_attribute("#ai-connect-panel-claude-code a[href^='https://t.me/']", "href")
    finally:
        context.close()
    assert href == f"https://t.me/{app_mod.BOT_USERNAME_CLEAN}"
    assert errors.relevant() == []


@pytest.mark.parametrize("direction", ["rtl", "ltr"])
def test_arrow_keys_move_to_the_tab_that_sits_in_that_direction(browser, admin_live_server, monkeypatch, direction):
    """החץ השמאלי עובר ללשונית שיושבת משמאל, בשתי הפריסות — נמדד במיקום ולא מונח.

    העמוד RTL. הפריסה ההפוכה נבדקת בהחלפת ``dir`` על הרשימה, כדי לוודא שהכיוון נגזר
    מה-direction בפועל ולא מהנחה שהעמוד RTL.
    """
    monkeypatch.setenv("MCP_SERVER_URL", MCP_BASE)
    context, page, errors = _open(browser, admin_live_server)
    try:
        page.evaluate("d => document.querySelector('#ai-connect [role=\"tablist\"]').setAttribute('dir', d)", direction)
        xs = page.evaluate("""() => Array.from(document.querySelectorAll('#ai-connect [role="tab"]'))
            .map(t => t.getBoundingClientRect().left)""")
        # הלשונית השנייה ב-DOM יושבת משמאל לראשונה ב-RTL, ומימין לה ב-LTR.
        assert (xs[1] < xs[0]) == (direction == "rtl"), xs

        page.focus("#ai-connect-tab-claude-web")
        toward_second = "ArrowLeft" if direction == "rtl" else "ArrowRight"
        back = "ArrowRight" if direction == "rtl" else "ArrowLeft"

        page.keyboard.press(toward_second)
        _expect_selected(page, "gemini")
        assert page.evaluate("() => document.activeElement.id") == "ai-connect-tab-gemini"

        page.keyboard.press(back)
        _expect_selected(page, "claude-web")

        # מהראשונה אחורה — מסתובבים לאחרונה.
        page.keyboard.press(back)
        _expect_selected(page, "claude-code")

        page.keyboard.press("Home")
        _expect_selected(page, "claude-web")
        page.keyboard.press("End")
        _expect_selected(page, "claude-code")
        assert page.evaluate("() => document.activeElement.id") == "ai-connect-tab-claude-code"
    finally:
        context.close()
    assert errors.relevant() == []


@pytest.mark.parametrize("panel", ["claude-web", "gemini"])
def test_the_copy_button_copies_exactly_the_url(browser, admin_live_server, monkeypatch, panel):
    monkeypatch.setenv("MCP_SERVER_URL", MCP_BASE + "/")
    context, page, errors = _open(browser, admin_live_server)
    try:
        context.grant_permissions(["clipboard-read", "clipboard-write"], origin=admin_live_server.base_url)
        page.click(f"#ai-connect-tab-{panel}")
        page.click(f"#ai-connect-panel-{panel} .ai-connect__copy")
        poll(page, "() => document.querySelector('#ai-connect-panel-%s .ai-connect__copy-status').textContent !== ''" % panel,
             "שורת הסטטוס שליד כפתור ההעתקה")
        copied = page.evaluate("() => navigator.clipboard.readText()")
        selection = page.evaluate("() => window.getSelection().toString()")
    finally:
        context.close()
    # ה-``/`` בסוף ``MCP_SERVER_URL`` לא מוכפל, והנתיב הוא הקבוע של שירות ה-MCP.
    from mcp_server.public_url import MCP_ENDPOINT_PATH

    assert copied == MCP_BASE + MCP_ENDPOINT_PATH
    # הסימון שמור לכשל ההעתקה (הבדיקה הבאה); בהצלחה שום דבר לא מסומן.
    assert selection == ""
    assert errors.relevant() == []


def test_a_failed_copy_selects_the_url_for_manual_copy(browser, admin_live_server, monkeypatch):
    """כשההעתקה נכשלת אין "הועתק": הכתובת מסומנת, ואין מסלול חלופי שמעתיק בשקט."""
    monkeypatch.setenv("MCP_SERVER_URL", MCP_BASE)
    context, page, errors = _open(browser, admin_live_server)
    try:
        page.evaluate("""() => {
            window.__clipboardCalls = 0;
            navigator.clipboard.writeText = () => {
                window.__clipboardCalls += 1;
                return Promise.reject(new DOMException('denied', 'NotAllowedError'));
            };
        }""")
        page.click("#ai-connect-panel-claude-web .ai-connect__copy")
        poll(page, "() => document.querySelector('#ai-connect-panel-claude-web .ai-connect__copy-status').textContent !== ''",
             "שורת הסטטוס שליד כפתור ההעתקה")
        selection = page.evaluate("() => window.getSelection().toString()")
        calls = page.evaluate("() => window.__clipboardCalls")
    finally:
        context.close()
    from mcp_server.public_url import MCP_ENDPOINT_PATH

    assert calls == 1
    assert selection == MCP_BASE + MCP_ENDPOINT_PATH
    assert errors.relevant() == []


def test_the_anchor_scrolls_to_the_section(browser, admin_live_server, monkeypatch):
    """בלי העוגן הסעיף מתחת לקצה המסך, ועם העוגן הוא בחצי העליון.

    הבקרה בלי העוגן היא מה שמוכיח שהעוגן גלל: סעיף שיושב בראש העמוד היה עובר גם בלעדיו.
    ובעמוד הזה מי שנגלל הוא ``body`` ולא החלון (``html, body`` ב-``base.html`` הם בגובה
    100% עם ``overflow-x: hidden``), ולכן נמדד המיקום של הסעיף ולא ``window.scrollY``.
    """
    monkeypatch.setenv("MCP_SERVER_URL", MCP_BASE)
    context, page, errors = _open(browser, admin_live_server, height=700, fragment="")
    try:
        top = page.evaluate("() => document.getElementById('ai-connect').getBoundingClientRect().top")
        assert top > page.evaluate("() => window.innerHeight"), top
    finally:
        context.close()
    assert errors.relevant() == []

    context, page, errors = _open(browser, admin_live_server, height=700)
    try:
        # מה שמעל הסעיף נטען ברקע ויכול להזיז אותו אחרי הגלילה, ולכן נדגם עד שהוא בתצוגה.
        poll(page, """() => {
            const top = document.getElementById('ai-connect').getBoundingClientRect().top;
            return {ok: top >= 0 && top < window.innerHeight / 2, top};
        }""", "ראש הסעיף בחצי העליון של המסך")
    finally:
        context.close()
    assert errors.relevant() == []


@pytest.mark.parametrize("width", [320, 360, 390])
def test_at_phone_width_nothing_overflows_and_the_url_reads_left_to_right(browser, admin_live_server, monkeypatch, width):
    # כתובת ארוכה בכוונה: היא מה שיכול לדחוף את הכרטיס לרוחב.
    long_base = "https://codekeeper-mcp-service-with-a-long-name.onrender.example"
    monkeypatch.setenv("MCP_SERVER_URL", long_base)
    context, page, errors = _open(browser, admin_live_server, width=width, height=760)
    try:
        for key in PANELS:
            page.click(f"#ai-connect-tab-{key}")
            report = page.evaluate("""() => {
                const vw = document.documentElement.clientWidth;
                const root = document.getElementById('ai-connect');
                const outside = Array.from(root.querySelectorAll('*'))
                    .filter(el => el.getClientRects().length)
                    .map(el => ({el, r: el.getBoundingClientRect()}))
                    .filter(({r}) => r.left < -0.5 || r.right > vw + 0.5)
                    .map(({el, r}) => `${el.tagName}.${el.className} ${Math.round(r.left)}..${Math.round(r.right)}`);
                const codes = Array.from(root.querySelectorAll('code')).filter(c => c.getClientRects().length);
                return {
                    vw,
                    docOverflow: document.documentElement.scrollWidth - vw,
                    outside,
                    clipped: codes.filter(c => c.scrollWidth > c.clientWidth + 1).map(c => c.textContent),
                    notLtr: codes.filter(c => getComputedStyle(c).direction !== 'ltr').map(c => c.textContent),
                    codes: codes.map(c => c.textContent),
                    // פקודה קצרה או שם תפריט שנחצו לשתי שורות — רק הכתובת רשאית להישבר.
                    split: Array.from(root.querySelectorAll('code:not(.ai-connect__code), bdi'))
                        .filter(el => el.getClientRects().length > 1).map(el => el.textContent),
                };
            }""")
            assert report["docOverflow"] <= 0, (key, report)
            assert report["outside"] == [], (key, report)
            assert report["clipped"] == [], (key, report)
            assert report["notLtr"] == [], (key, report)
            assert report["split"] == [], (key, report)
            assert report["codes"], (key, report)
    finally:
        context.close()
    assert errors.relevant() == []


@pytest.mark.parametrize("value", [None, "https://user:secret@mcp.example.test", "not a url"])
def test_without_a_usable_url_the_section_renders_without_the_url_row(browser, admin_live_server, monkeypatch, value):
    """``MCP_SERVER_URL`` חסר או נדחה — הלשוניות מוצגות, ושורת הכתובת פשוט לא קיימת."""
    if value is None:
        monkeypatch.delenv("MCP_SERVER_URL", raising=False)
    else:
        monkeypatch.setenv("MCP_SERVER_URL", value)
    context, page, errors = _open(browser, admin_live_server)
    try:
        assert page.evaluate("() => document.querySelectorAll('#ai-connect .ai-connect__url').length") == 0
        html = page.inner_html("#ai-connect")
        for key in PANELS:
            page.click(f"#ai-connect-tab-{key}")
            _expect_selected(page, key)
    finally:
        context.close()
    assert "secret" not in html
    assert "mcp.example.test" not in html
    assert errors.relevant() == []
