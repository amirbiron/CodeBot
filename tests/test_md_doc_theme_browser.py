"""ערכת המסמך בדפדפן: הכרטיס "תצוגת Markdown" נראה בדיוק כמו כשהערכה שנבחרה לו היא ערכת הממשק.

**האורקל.** אין רשימה ידנית של "איזה צבע צריך לצאת לכל רכיב": העמוד עם ערכת ממשק X וערכת מסמך D נמדד מול
העמוד שבו D היא ערכת הממשק, בלי ערכת מסמך. כל אלמנט בכרטיס — כולל ``::before``/``::after``, ``::marker``
ו-``::placeholder`` — נמדד במאפייני הצבע והגופן, ושני העמודים חייבים להיות זהים. היוצא מן הכלל היחיד הוא הרקע
של הכרטיס עצמו: כשהערכה היא ערכת הממשק הוא שכבת זכוכית מעל הרקע של העמוד, וכאן מאחוריו עמוד בערכה אחרת, ולכן
הוא נבדק בנפרד. כך כל כלל שנשאר מערכת הממשק בתוך הכרטיס — משתנה שעבר בירושה, וו דריסה, צבע תחביר — נתפס,
גם כלל שאיש לא חשב עליו.

**ומה עוד:** מחוץ לכרטיס העמוד זהה לעמוד בלי ערכת מסמך; ובערכת ממשק מובנית ערכת המסמך רדומה, והכרטיס זהה לעמוד
בלי ערכת מסמך.

העמוד אמיתי — ``/md/<id>`` דרך ``test_client``, כולל הסטטיים — והמסד ``FakeDB``. בדיקות בלי דפדפן:
``tests/test_md_doc_theme.py``.

מדולג כשאין Chromium.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone
from urllib.parse import urlsplit

import pytest
from bson import ObjectId

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _fake_mongo import FakeDB  # noqa: E402

from services.theme_parser_service import parse_vscode_theme, sanitize_syntax_css  # noqa: E402

HOST = "ck.test"
USER_ID = 5150
FORWARDED_HEADERS = ("content-type", "cache-control", "etag")
_ADDRESSES = itertools.count(1)

#: ערכה כהה עם כל מה שיכול לזלוג לכרטיס: ווי דריסה של צבעי המסמך, ``--secondary`` (שאינו ברשימת ברירות המחדל
#: של המייבא), ו-``tokenColors``, שכלליהם הם ``!important`` על כל העמוד.
DARK = {
    "name": "Swamp",
    "type": "dark",
    "colors": {
        "editor.background": "#313a36", "editor.foreground": "#e4e3e1", "sideBar.background": "#3d4843",
        "sideBar.foreground": "#d0cfcc", "activityBar.background": "#36403b", "focusBorder": "#fdec5a",
        "terminal.background": "#252c29", "terminal.foreground": "#e4e3e1", "panel.border": "#607169",
    },
    "tokenColors": [
        {"scope": ["comment"], "settings": {"foreground": "#6a9955", "fontStyle": "italic"}},
        {"scope": ["keyword", "storage"], "settings": {"foreground": "#c586c0"}},
        {"scope": ["string"], "settings": {"foreground": "#ce9178"}},
        {"scope": ["constant.numeric"], "settings": {"foreground": "#b5cea8"}},
        {"scope": ["entity.name.function"], "settings": {"foreground": "#dcdcaa", "fontStyle": "bold"}},
        {"scope": ["variable.parameter"], "settings": {"foreground": "#9cdcfe", "fontStyle": "italic"}},
        {"scope": ["entity.name.type"], "settings": {"foreground": "#4ec9b0"}},
    ],
    "variables": {
        "--primary": "#e1c636", "--secondary": "#ff00aa", "--link-color": "#7fdbca",
        "--md-heading-color-override": "#e1c636", "--md-subheading-color-override": "#cfd394",
        "--md-strong-color-override": "#dcdcaa", "--md-inline-code-color-override": "#b5cea8",
        "--md-blockquote-border-override": "#e1c636",
    },
}

#: ערכה בהירה, כמו Pen Paper Coffee: ``tokenColors`` משלה ווו אחד שערכה כהה לא מצהירה עליו. ``input.foreground``
#: שונה מ-``editor.foreground`` בכוונה: הוא דורס את ``--text-primary``, ואילו הטקסט הרגיל בבלוק קוד נצבע ב-
#: ``editor.foreground`` (הכלל הבסיסי ``.hljs``) — כך הבדיקה רואה אם הכלל הבסיסי הגיע לכרטיס.
LIGHT = {
    "name": "Paper",
    "type": "light",
    "colors": {
        "editor.background": "#f8f6f1", "editor.foreground": "#2b3f6a", "input.foreground": "#1d2b48",
        "sideBar.background": "#ebe8df",
        "activityBar.background": "#e0dad3", "focusBorder": "#6e4e44", "textLink.foreground": "#5e78e1",
        "textLink.activeForeground": "#6e4e44", "button.background": "#e4dcc8",
    },
    "tokenColors": [
        {"scope": ["comment"], "settings": {"foreground": "#9ca3b0", "fontStyle": "italic"}},
        {"scope": ["keyword"], "settings": {"foreground": "#5e78e1"}},
        {"scope": ["string"], "settings": {"foreground": "#8f6928"}},
        {"scope": ["entity.name.function"], "settings": {"foreground": "#d08e25"}},
    ],
    "variables": {
        "--glass": "rgba(224, 218, 211, 0.55)", "--glass-border": "rgba(110, 78, 68, 0.3)",
        "--md-search-capsule-border-override": "rgba(110, 78, 68, 0.3)",
    },
}

#: ערכה בלי ``tokenColors`` — כמו ערכה מבונה הערכות. צבעי התחביר שלה נגזרים מהמשתנים, ובהם ``--secondary``.
PLAIN = {
    "name": "Plain",
    "type": "light",
    "colors": {"editor.background": "#fffbe6", "editor.foreground": "#3a2e1f", "focusBorder": "#a0522d"},
}

MARKDOWN = """# כותרת ראשית

## כותרת שנייה

### כותרת שלישית

פסקה עם **מודגש**, *נטוי*, [קישור](https://example.com/a), `קוד בשורה` ו-==סימון==.

- פריט
- [ ] משימה פתוחה
- [x] משימה סגורה

1. ראשון
2. שני

> ציטוט עם **מודגש** ו-[קישור](https://example.com/b)

| עמודה | ערך |
|---|---|
| א | `1` |

```python
def greet(name: str) -> int:
    # הערה
    count = 42
    return print(f"hi {name}", count, True)
```

---

::: tip טיפ
תוכן עם [קישור](https://example.com/c)
:::

::: details פרטים
תוכן מתקפל
:::

```mermaid
graph TD
  A[התחלה] --> B[סוף]
```
"""

MEASURED = (
    "color", "background-color", "background-image", "border-top-color", "border-right-color",
    "border-bottom-color", "border-left-color", "outline-color", "text-decoration-color", "text-decoration-line",
    "caret-color", "fill", "stroke", "box-shadow", "text-shadow", "font-style", "font-weight", "opacity", "display",
)

#: כל אלמנט ב-``scope`` (בסדר המסמך), עם הפסאודו-אלמנטים שיש לו. ``scope`` — ``"card"`` או ``"outside"``.
MEASURE_JS = """([props, scope]) => {
  const card = document.getElementById('mdCard');
  const all = Array.from(document.querySelectorAll('html, html *'));
  const els = scope === 'card'
    ? [card, ...card.querySelectorAll('*')]
    : all.filter(el => el !== card && !card.contains(el)
        && !['SCRIPT', 'STYLE', 'LINK', 'META', 'TITLE', 'HEAD'].includes(el.tagName));
  const pick = (cs) => Object.fromEntries(props.map(p => [p, cs.getPropertyValue(p)]));
  return els.map((el, i) => {
    const row = {
      i, tag: el.tagName.toLowerCase(), id: el.id, cls: String(el.getAttribute('class') || '').slice(0, 50),
      mermaid: !!el.closest('svg[id^="mmd_"]'), self: pick(getComputedStyle(el)),
    };
    for (const pe of ['::before', '::after', '::marker', '::placeholder']) {
      if (pe === '::marker' && el.tagName !== 'LI') continue;
      if (pe === '::placeholder' && el.tagName !== 'INPUT') continue;
      const cs = getComputedStyle(el, pe);
      if ((pe === '::before' || pe === '::after') && (cs.content === 'none' || cs.content === 'normal')) continue;
      row[pe] = pick(cs);
    }
    return row;
  });
}"""


SETTLE_JS = """() => Promise.all(document.getAnimations().map(a => {
  const timing = a.effect && a.effect.getComputedTiming ? a.effect.getComputedTiming() : null;
  if (timing && timing.iterations === Infinity) { a.pause(); a.currentTime = 0; return null; }
  return a.finished.catch(() => null);
}))"""


def _custom_doc(theme_id: str, vscode: dict, *, active: bool) -> dict:
    parsed = parse_vscode_theme(vscode)
    variables = dict(parsed["variables"])
    # כמו ``import_theme``: בלוק ``variables`` בקובץ דורס אחרי המיפוי.
    variables.update(vscode.get("variables") or {})
    now = datetime(2026, 11, 1, tzinfo=timezone.utc)
    return {
        "id": theme_id, "name": vscode["name"], "is_active": active, "variables": variables,
        "syntax_css": parsed["syntax_css"], "syntax_colors": parsed["syntax_colors"],
        "created_at": now, "updated_at": now,
    }


def _shared_doc(slug: str, vscode: dict) -> dict:
    custom = _custom_doc(slug, vscode, active=False)
    # כמו הפרסום: המשתנים של הערכה האישית, וה-``syntax_css`` שלה אחרי ``sanitize_syntax_css``.
    return {
        "_id": slug, "name": vscode["name"], "colors": custom["variables"],
        "syntax_css": sanitize_syntax_css(custom["syntax_css"]).css, "syntax_colors": custom["syntax_colors"],
        "is_active": True, "created_at": custom["created_at"], "updated_at": custom["updated_at"],
    }


THEMES = {"dark": DARK, "light": LIGHT, "plain": PLAIN}
CUSTOM_IDS = {name: f"{name}-theme-0000-0000" for name in THEMES}
SHARED_SLUGS = {name: f"{name}_public" for name in THEMES}


def token(kind: str, name: str) -> str:
    return f"custom:{CUSTOM_IDS[name]}" if kind == "custom" else f"shared:{SHARED_SLUGS[name]}"


@pytest.fixture(scope="module")
def browser(chromium_executable):
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
            yield b
        finally:
            b.close()


@pytest.fixture
def measure(browser, monkeypatch):
    """``measure(ui, doc, scope)`` — מודד את ``/md/<id>`` בערכת ממשק ``ui`` (טוקן או ערכה מובנית) ובערכת מסמך
    ``doc``."""
    import webapp.app as wa

    db = FakeDB()
    monkeypatch.setattr(wa, "get_db", lambda: db)
    file_id = ObjectId()
    db.code_snippets.insert_one({
        "_id": file_id, "user_id": USER_ID, "file_name": "doc.md", "code": MARKDOWN,
        "programming_language": "markdown", "version": 1, "is_active": True,
    })
    for name, vscode in THEMES.items():
        db.shared_themes.insert_one(_shared_doc(SHARED_SLUGS[name], vscode))
    contexts = []

    def run(ui: str, doc: str | None, scope: str = "card", *, before=None):
        db.users.delete_many({"user_id": USER_ID})
        active_custom = ui.split(":", 1)[1] if ui.startswith("custom:") else None
        prefs = {"theme": ui}
        if doc:
            prefs["md_doc_theme"] = doc
        db.users.insert_one({
            "user_id": USER_ID,
            "ui_prefs": prefs,
            "custom_themes": [
                _custom_doc(CUSTOM_IDS[n], v, active=CUSTOM_IDS[n] == active_custom) for n, v in THEMES.items()
            ],
        })
        client = wa.app.test_client()
        client.environ_base["HTTP_X_FORWARDED_FOR"] = f"198.51.100.{next(_ADDRESSES) % 250 + 1}"
        with client.session_transaction() as sess:
            sess["user_id"] = USER_ID
            sess["user_data"] = {"id": USER_ID, "first_name": "בדיקה"}

        def handle(route, request):
            u = urlsplit(request.url)
            if u.hostname != HOST:
                return route.abort()
            target = u.path + (f"?{u.query}" if u.query else "")
            r = client.open(target, method=request.method, data=request.post_data_buffer,
                            headers={"Content-Type": request.headers.get("content-type", "")})
            headers = {k: v for k, v in r.headers.items() if k.lower() in FORWARDED_HEADERS}
            route.fulfill(status=r.status_code, body=r.data, headers=headers)

        ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="he-IL")
        contexts.append(ctx)
        ctx.route("**/*", handle)
        page = ctx.new_page()
        page.goto(f"http://{HOST}/md/{file_id}?nc=1", wait_until="load")
        page.wait_for_function(
            "() => document.querySelector('#md-content .hljs-keyword')"
            " && document.querySelector('#md-content .admonition')",
            timeout=20000,
        )
        # Mermaid מרונדר אחרי המסמך; אם הוא לא זמין בבאנדל, הבלוק נשאר קוד — ושני העמודים זהים גם אז.
        page.wait_for_timeout(800)
        if before:
            before(page)
        # מעברים ואנימציות (המעבר של שורת החיפוש בפוקוס, הכניסה של המסמך) נמדדים רק כשהסתיימו — אחרת שני עמודים
        # זהים נמדדים בשתי נקודות שונות של אותו מעבר. ``getAnimations`` כולל גם מעברי CSS. אנימציה אינסופית (שלד טעינה)
        # לא מסתיימת אף פעם, ולכן היא נעצרת בנקודה קבועה — אחרת ההמתנה לא הייתה חוזרת.
        page.evaluate(SETTLE_JS)
        rows = page.evaluate(MEASURE_JS, [list(MEASURED), scope])
        attrs = page.evaluate(
            "() => [document.documentElement.getAttribute('data-theme'),"
            " document.getElementById('mdCard').hasAttribute('data-md-doc-theme')]"
        )
        return rows, attrs

    yield run
    for ctx in contexts:
        ctx.close()


#: הרקע של הכרטיס עצמו — היוצא מן הכלל של האורקל (ה-docstring של הקובץ), ונבדק בנפרד.
CARD_BACKGROUND = ("background-color", "background-image")


def _differences(got, want, *, skip_card_background: bool, skip_mermaid: bool = False):
    out = []
    if len(got) != len(want):
        out.append(f"מספר האלמנטים שונה: {len(got)} מול {len(want)}")
    for a, b in zip(got, want):
        if (a["tag"], a["id"]) != (b["tag"], b["id"]):
            out.append(f"#{a['i']}: <{a['tag']} id={a['id']}> מול <{b['tag']} id={b['id']}> — המבנה שונה")
            break
        if skip_mermaid and a["mermaid"]:
            continue
        for part in sorted(set(a) | set(b)):
            if part in ("i", "tag", "id", "cls", "mermaid"):
                continue
            pa, pb = a.get(part) or {}, b.get(part) or {}
            for prop in MEASURED:
                card_background = a["id"] == "mdCard" and part == "self" and prop in CARD_BACKGROUND
                if skip_card_background and card_background:
                    continue
                if pa.get(prop) != pb.get(prop):
                    where = f"#{a['i']} <{a['tag']} id={a['id']} class={a['cls']}> {part} {prop}"
                    out.append(f"{where}: {pa.get(prop)!r} ≠ {pb.get(prop)!r}")
    return out


#: ``(ערכת ממשק, ערכת מסמך)``: כהה עם בהירה ולהפך, ערכה בלי ``tokenColors``, ערכה ציבורית בשני הצדדים.
ORACLE_CASES = [
    (("custom", "dark"), ("custom", "light")),
    (("custom", "light"), ("custom", "dark")),
    (("custom", "dark"), ("custom", "plain")),
    (("shared", "dark"), ("custom", "light")),
    (("custom", "dark"), ("shared", "light")),
]


@pytest.mark.parametrize("ui, doc", ORACLE_CASES, ids=lambda c: f"{c[0]}-{c[1]}")
def test_the_card_looks_exactly_like_the_document_theme_as_the_ui_theme(measure, ui, doc):
    got, attrs = measure(token(*ui), token(*doc))
    assert attrs[1], "לכרטיס אין data-md-doc-theme"
    oracle, oracle_attrs = measure(token(*doc), None)
    assert not oracle_attrs[1]
    # ערכה ציבורית כערכת ממשק מקבלת היום Mermaid כהה גם כשהיא בהירה: ההחלטה ב-``md_preview.html`` בודקת את הבהירות
    # רק כש-``data-theme`` הוא ``custom``. בכרטיס של ערכת מסמך ההחלטה היא לפי הבהירות, כמו בכל ערכה מותאמת, ולכן
    # כאן הדיאגרמה אינה חלק מהאורקל. מה שהיא כן — ``test_mermaid_in_the_card_follows_the_document_theme``.
    diffs = _differences(got, oracle, skip_card_background=True, skip_mermaid=doc[0] == "shared")
    assert not diffs, f"{len(diffs)} הבדלים מול האורקל:\n" + "\n".join(diffs[:60])

    # והבדיקה אינה ריקה: בלי ערכת מסמך אותו כרטיס שונה מהאורקל.
    plain, _ = measure(token(*ui), None)
    assert len(_differences(plain, oracle, skip_card_background=True)) > 50


def test_mermaid_in_the_card_follows_the_document_theme(measure):
    """ערכת מסמך ציבורית בהירה: הדיאגרמה בהירה, כמו כשאותה ערכה — כאישית — היא ערכת הממשק."""
    got, _ = measure(token("custom", "dark"), token("shared", "light"))
    oracle, _ = measure(token("custom", "light"), None)
    mermaid_got = [row for row in got if row["mermaid"]]
    mermaid_oracle = [row for row in oracle if row["mermaid"]]
    assert mermaid_got, "הדיאגרמה לא רונדרה — הבדיקה לא בודקת כלום"
    # רק הדיאגרמה: שאר הכרטיס נבדק מול האורקל של הערכה הציבורית, והמשתנים של שתי הערכות זהים
    assert [r["self"]["fill"] for r in mermaid_got] == [r["self"]["fill"] for r in mermaid_oracle]
    assert [r["self"]["stroke"] for r in mermaid_got] == [r["self"]["stroke"] for r in mermaid_oracle]


def test_the_card_background_is_the_document_theme_page(measure):
    rows, _ = measure(token("custom", "dark"), token("custom", "light"))
    card = rows[0]["self"]
    assert card["background-color"] == "rgba(0, 0, 0, 0)"
    assert card["background-image"] == (
        "linear-gradient(rgba(224, 218, 211, 0.55), rgba(224, 218, 211, 0.55)), "
        "linear-gradient(135deg, rgb(248, 246, 241) 0%, rgb(235, 232, 223) 100%)"
    )


def test_hover_and_focus_inside_the_card_follow_the_document_theme(measure):
    def interact(page):
        page.focus("#mdSearchInput")
        page.hover("#md-content p a")

    got, _ = measure(token("custom", "dark"), token("custom", "light"), before=interact)
    oracle, _ = measure(token("custom", "light"), None, before=interact)
    diffs = _differences(got, oracle, skip_card_background=True)
    assert not diffs, "\n".join(diffs[:40])


@pytest.mark.parametrize("ui, doc", ORACLE_CASES[:2] + ORACLE_CASES[3:4], ids=lambda c: f"{c[0]}-{c[1]}")
def test_outside_the_card_nothing_changes(measure, ui, doc):
    got, _ = measure(token(*ui), token(*doc), scope="outside")
    without, _ = measure(token(*ui), None, scope="outside")
    diffs = _differences(got, without, skip_card_background=False)
    assert not diffs, f"{len(diffs)} הבדלים מחוץ לכרטיס:\n" + "\n".join(diffs[:40])


@pytest.mark.parametrize("ui", ["classic", "nebula", "high-contrast"])
def test_under_a_builtin_ui_theme_the_document_theme_is_dormant(measure, ui):
    got, attrs = measure(ui, token("custom", "light"))
    assert attrs == [ui, True], attrs  # התכונה על הכרטיס, והתנאי ב-CSS הוא שמשאיר אותה רדומה
    without, _ = measure(ui, None)
    diffs = _differences(got, without, skip_card_background=False)
    assert not diffs, "\n".join(diffs[:40])


# ---------------------------------------------------------------------------
# מסך הייבוא: התיבה "ערכת המסמך" ותיבת הסימון שליד הייבוא
# ---------------------------------------------------------------------------


@pytest.fixture
def gallery(browser, monkeypatch):
    """``/settings/theme-gallery`` אמיתי מול ``FakeDB``. מחזיר ``(page, db, requests)`` — ``requests`` הם גופי
    ה-POST ל-``/api/ui_prefs``, כפי שהדפדפן שלח אותם."""
    import json

    import webapp.app as wa

    db = FakeDB()
    monkeypatch.setattr(wa, "get_db", lambda: db)
    db.users.insert_one({
        "user_id": USER_ID,
        "ui_prefs": {"theme": token("custom", "dark")},
        "custom_themes": [
            _custom_doc(CUSTOM_IDS["dark"], DARK, active=True),
            _custom_doc(CUSTOM_IDS["light"], LIGHT, active=False),
        ],
    })
    client = wa.app.test_client()
    client.environ_base["HTTP_X_FORWARDED_FOR"] = f"198.51.100.{next(_ADDRESSES) % 250 + 1}"
    with client.session_transaction() as sess:
        sess["user_id"] = USER_ID
        sess["user_data"] = {"id": USER_ID, "first_name": "בדיקה"}
    posted: list[dict] = []
    # ה-cookies של ``/api/ui_prefs`` הם ``Secure`` (הייצור ב-HTTPS), והדפדפן לא שומר אותם על ה-``http`` של הבדיקה.
    # לכן נבדק מה השרת שלח, מכותרות התשובה.
    set_cookies: list[str] = []

    def handle(route, request):
        u = urlsplit(request.url)
        if u.hostname != HOST:
            return route.abort()
        target = u.path + (f"?{u.query}" if u.query else "")
        r = client.open(target, method=request.method, data=request.post_data_buffer,
                        headers={"Content-Type": request.headers.get("content-type", "")})
        if u.path == "/api/ui_prefs":
            posted.append(json.loads(request.post_data or "{}"))
            set_cookies.extend(r.headers.getlist("Set-Cookie"))
        headers = {k: v for k, v in r.headers.items() if k.lower() in FORWARDED_HEADERS}
        route.fulfill(status=r.status_code, body=r.data, headers=headers)

    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="he-IL")
    ctx.route("**/*", handle)
    page = ctx.new_page()
    page.goto(f"http://{HOST}/settings/theme-gallery", wait_until="load")
    page.click('.tab-btn[data-tab="import"]')
    page.wait_for_function(
        "() => document.querySelectorAll('#mdDocThemeSelect optgroup option').length > 0", timeout=10000
    )
    page.set_cookies_sent = set_cookies
    yield page, db, posted
    ctx.close()


def _pointer(db):
    return (db.users.find_one({"user_id": USER_ID}).get("ui_prefs") or {}).get("md_doc_theme", "<absent>")


def test_the_box_lists_my_themes_and_saves_the_choice_for_all_devices(gallery):
    page, db, posted = gallery
    options = page.eval_on_selector_all(
        "#mdDocThemeSelect optgroup option", "els => els.map(e => [e.value, e.textContent])"
    )
    assert [token("custom", "dark"), "Swamp"] in options and [token("custom", "light"), "Paper"] in options
    assert "אין ערכת מסמך" in page.text_content("#mdDocThemeStatus")

    page.select_option("#mdDocThemeSelect", token("custom", "light"))
    page.click("#mdDocThemeApply")
    page.wait_for_function("() => document.querySelector('#mdDocThemeStatus').textContent.includes('Paper')")
    assert posted[-1] == {"md_doc_theme": token("custom", "light"), "md_doc_theme_scope": "global"}
    assert _pointer(db) == token("custom", "light")

    page.select_option("#mdDocThemeSelect", "")
    page.click("#mdDocThemeApply")
    page.wait_for_function("() => document.querySelector('#mdDocThemeStatus').textContent.includes('אין ערכת מסמך')")
    assert posted[-1] == {"md_doc_theme": None, "md_doc_theme_scope": "global"}
    assert _pointer(db) == "<absent>"


def test_device_scope_keeps_the_choice_on_this_device(gallery):
    page, db, posted = gallery
    page.select_option("#mdDocThemeSelect", token("custom", "light"))
    page.select_option("#mdDocThemeScope", "device")
    page.click("#mdDocThemeApply")
    page.wait_for_function("() => document.querySelector('#mdDocThemeStatus').textContent.includes('Paper')")
    assert posted[-1]["md_doc_theme_scope"] == "device"
    assert _pointer(db) == "<absent>"
    cookies = dict(c.split(";", 1)[0].split("=", 1) for c in page.set_cookies_sent)
    assert cookies.get("ui_md_doc_theme") == token("custom", "light")
    assert cookies.get("ui_md_doc_theme_scope") == "device"


def test_importing_with_the_box_checked_makes_the_new_theme_the_document_theme(gallery):
    import json

    page, db, posted = gallery
    page.check("#importAsDocTheme")
    page.fill("#jsonInput", json.dumps(PLAIN))
    page.click("#importJsonBtn")
    page.wait_for_function(
        "() => document.querySelector('#mdDocThemeStatus').textContent.includes('Plain')", timeout=10000
    )

    new_ids = [t["id"] for t in db.users.find_one({"user_id": USER_ID})["custom_themes"] if t["name"] == "Plain"]
    assert len(new_ids) == 1
    assert posted[-1] == {"md_doc_theme": f"custom:{new_ids[0]}", "md_doc_theme_scope": "global"}
    assert _pointer(db) == f"custom:{new_ids[0]}"
    # הלשונית נשארה "ייבוא", כדי שהמצב ייראה; והערכה החדשה מסומנת בתיבה
    assert page.is_visible("#import-tab")
    assert page.input_value("#mdDocThemeSelect") == f"custom:{new_ids[0]}"
