"""בונה הערכות שולח בשמירה ובפרסום רק את מה שהמשתמש שינה, ומחוון השקיפות שומר על צבע הזכוכית של הערכה.

**מה היה שבור.** לבונה יש מחוון "שקיפות" ואין לו פקד לצבע הזכוכית. בטעינת ערכה הוא לקח מ-``--glass`` רק את
השקיפות, ובשמירה ובפרסום כתב את שלושת משתני הזכוכית — ``--glass``, ``--glass-border`` ו-``--glass-hover`` — תמיד
כלבן, ``rgba(255, 255, 255, …)``. בפרסום ערכי הטופס גברו על המשתנים המקוריים, ולכן ערכה מיובאת עם זכוכית צבעונית
(Pen Paper Coffee: בז' וקפה) פורסמה כערכה ציבורית עם זכוכית לבנה: הכרטיסים והכפתורים לבנים בלי מסגרת, וכל וו
דריסה שומר על הצבע שלו — המראה "התהפך". "שמור שינויים" בלי לגעת בשום פקד שלח את אותם שלושה ערכים לבנים, והשרת
ממזג אותם לתוך הערכה האישית.

**מה נמדד כאן.** הדף האמיתי (``/settings/theme-builder`` דרך ``test_client``, כולל הסטטיים) עם ערכה שהזכוכית שלה
צבעונית, בכרומיום: מה הבונה שולח בפרסום, בשמירה בלי שינוי, בשמירה אחרי שינוי צבע אחד, ואחרי הזזת המחוון; וערכה
חדשה, שנבנית מאפס בבונה, שולחת זכוכית לבנה כמו עד היום.

**מה לא עובר כאן דרך השרת.** פרטי הערכה (``GET /api/themes/<id>``) מוגשים מהבדיקה, באותה צורה ש-
``get_theme_details`` ב-``webapp/themes_api.py`` מחזיר ומאותו מסמך: הוא קורא ב-``{"custom_themes.$": 1}`` עם
``"custom_themes.id"``, ו-``FakeDB`` אינו תומך בהיטלה המיקומית ובהתאמה דרך מערך. הבקשות שהבונה שולח — שמירה, פרסום,
יצירה — נלכדות ולא מגיעות לשרת: מה שנבדק הוא מה שהלקוח שולח. המיזוג בשרת (``update_theme``) לא השתנה.

מדולג כשאין Chromium.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _fake_mongo import FakeDB  # noqa: E402

HOST = "ck.test"
USER_ID = 7301
THEME_ID = "glass-theme-0000-0000"
THEME_NAME = "Coffee Glass"
#: ערכה מיובאת בהירה עם זכוכית צבעונית — הערכים של Pen Paper Coffee. הזכוכית ב-55%, הגבול 30% והריחוף 12%: היחס
#: ביניהם אינו היחס שהמחוון מחשב (+10 ו-+5), ולכן ערך שהבונה בונה מחדש בלי שנגעו בו נתפס כשינוי.
VARIABLES = {
    "--bg-primary": "#f8f6f1",
    "--bg-secondary": "#ebe8df",
    "--card-bg": "#ebe8df",
    "--primary": "#6e4e44",
    "--text-primary": "#2b3f6a",
    "--md-surface": "#f8f6f1",
    "--md-text": "#2b3f6a",
    "--btn-primary-bg": "#e4dcc8",
    "--btn-primary-color": "#2a120a",
    "--glass": "rgba(224, 218, 211, 0.55)",
    "--glass-border": "rgba(110, 78, 68, 0.3)",
    "--glass-hover": "rgba(110, 78, 68, 0.12)",
    "--glass-blur": "20px",
    "--link-color": "#5e78e1",
    "--nested-card-bg-override": "rgba(110, 78, 68, 0.06)",
}
GLASS = ("--glass", "--glass-border", "--glass-hover")
WAIT_S = 15.0


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
def builder(browser, monkeypatch):
    """``builder()`` — דף בונה הערכות של אדמין, עם הערכה הצבעונית כערכה אישית. מחזיר ``(page, sent, errors)``: ``sent``
    הוא מילון שאליו נכנס גוף כל בקשה שהבונה שולח — ``"publish"``, ``"save"`` ו-``"create"`` — ו-``errors``
    הוא רשימת השגיאות שהדף זרק."""
    import webapp.app as wa

    monkeypatch.setenv("ADMIN_USER_IDS", str(USER_ID))  # כפתור הפרסום מוצג לאדמין בלבד
    db = FakeDB()
    monkeypatch.setattr(wa, "get_db", lambda: db)
    now = datetime(2026, 11, 18, tzinfo=timezone.utc)
    theme = {
        "id": THEME_ID, "name": THEME_NAME, "description": "", "is_active": True, "variables": dict(VARIABLES),
        "syntax_css": "", "syntax_colors": {}, "source": "vscode", "created_at": now, "updated_at": now,
    }
    db.users.insert_one({"user_id": USER_ID, "ui_prefs": {"theme": f"custom:{THEME_ID}"}, "custom_themes": [theme]})
    contexts = []

    def open_builder():
        client = wa.app.test_client()
        client.environ_base["HTTP_X_FORWARDED_FOR"] = "198.51.100.73"
        with client.session_transaction() as sess:
            sess["user_id"] = USER_ID
            sess["user_data"] = {"id": USER_ID, "first_name": "בדיקה"}
        sent: dict = {}

        def fulfill_json(route, payload):
            route.fulfill(status=200, body=json.dumps(payload), headers={"content-type": "application/json"})

        def handle(route, request):
            u = urlsplit(request.url)
            if u.hostname != HOST:
                return route.abort()
            if u.path == f"/api/themes/{THEME_ID}" and request.method == "GET":
                # הצורה של get_theme_details, מאותו מסמך (ה-docstring של הקובץ אומר למה לא דרך השרת).
                stored = db.users.find_one({"user_id": USER_ID})["custom_themes"][0]
                return fulfill_json(route, {"ok": True, "theme": {
                    "id": stored["id"], "name": stored["name"], "description": stored["description"],
                    "is_active": stored["is_active"], "created_at": stored["created_at"].isoformat(),
                    "updated_at": stored["updated_at"].isoformat(), "variables": stored["variables"],
                    "syntax_css": stored["syntax_css"], "syntax_colors": stored["syntax_colors"],
                    "source": stored["source"],
                }})
            if u.path == f"/api/themes/{THEME_ID}" and request.method == "PUT":
                sent["save"] = json.loads(request.post_data or "{}")
                return fulfill_json(route, {"ok": True, "message": "ok"})
            if u.path == "/api/themes/publish" and request.method == "POST":
                sent["publish"] = json.loads(request.post_data or "{}")
                return fulfill_json(route, {"ok": True, "theme_id": "x", "message": "ok", "syntax_rules_dropped": 0})
            if u.path == "/api/themes" and request.method == "POST":
                sent["create"] = json.loads(request.post_data or "{}")
                return fulfill_json(route, {"ok": False, "error": "captured_by_test"})
            r = client.open(u.path + (f"?{u.query}" if u.query else ""), method=request.method,
                            data=request.post_data_buffer,
                            headers={"Content-Type": request.headers.get("content-type", "")})
            headers = {k: v for k, v in r.headers.items() if k.lower() in ("content-type", "cache-control", "etag")}
            route.fulfill(status=r.status_code, body=r.data, headers=headers)

        ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="he-IL")
        contexts.append(ctx)
        ctx.route("**/*", handle)
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("dialog", lambda d: d.accept())  # אישור "יש שינויים שלא נשמרו" / אזהרת ניגודיות
        page.goto(f"http://{HOST}/settings/theme-builder", wait_until="load")
        # הבונה בוחר לבד את הערכה הפעילה (fetchThemes), כמו שמשתמש רואה אותו. לחיצה נוספת הייתה מתחילה טעינה שנייה,
        # שחוזרת אחרי שהבדיקה כבר הזיזה פקד ומחזירה אותו. הטעינה הסתיימה כשהטופס מייצג את הערכה — השם, והשקיפות שלה
        # במחוון — וכפתור השמירה כבר לא מושבת (setFormDisabled(false) רץ אחרי loadThemeIntoForm).
        page.wait_for_function(
            "([name]) => document.getElementById('themeName').value === name"
            " && document.getElementById('glassOpacityValue').textContent.trim() === '55%'"
            " && !document.getElementById('saveThemeBtn').disabled",
            arg=[THEME_NAME], timeout=WAIT_S * 1000,
        )
        return page, sent, errors

    yield open_builder
    for ctx in contexts:
        ctx.close()


def _wait_for(page, sent, key):
    deadline = time.monotonic() + WAIT_S
    while key not in sent:
        if time.monotonic() > deadline:
            raise AssertionError(f"הבונה לא שלח בקשת {key} תוך {WAIT_S} שניות")
        page.wait_for_timeout(100)
    return sent[key]


def _publish(page, sent):
    page.click("#publishThemeBtn")
    page.wait_for_selector("#publishModal:not([hidden])", timeout=WAIT_S * 1000)
    if not page.input_value("#publishSlug"):
        page.fill("#publishSlug", "coffee_glass")
    page.click("#publishSubmitBtn")
    return _wait_for(page, sent, "publish")


def _save(page, sent):
    page.click("#saveThemeBtn")
    return _wait_for(page, sent, "save")


def _set_opacity(page, value: int):
    page.evaluate(
        "(v) => { const s = document.getElementById('glassOpacity'); s.value = String(v);"
        " s.dispatchEvent(new Event('input', { bubbles: true })); }",
        value,
    )


def _rgba(value):
    m = re.fullmatch(r"rgba\((\d+), (\d+), (\d+), ([\d.]+)\)", str(value))
    assert m, value
    return tuple(int(x) for x in m.groups()[:3]), float(m.group(4))


def test_publishing_untouched_sends_the_themes_own_glass(builder):
    """הבאג עצמו: פרסום בלי לגעת בשום פקד שולח את שלושת משתני הזכוכית כמו שהם בערכה, ולא לבן."""
    page, sent, errors = builder()
    colors = _publish(page, sent)["colors"]
    for name in GLASS:
        assert colors.get(name) == VARIABLES[name], (name, colors.get(name))
    # ושום משתנה אחר של הערכה לא נדרס בדרך — כולל אלה שאינם בטופס.
    for name, value in VARIABLES.items():
        assert str(colors.get(name, "")).lower() == value.lower(), (name, colors.get(name))
    assert not errors, errors


def test_saving_untouched_sends_no_variables(builder):
    """"שמור שינויים" בלי שינוי לא שולח משתנים, ולכן השרת לא ממזג לתוך הערכה האישית שום ערך מהטופס."""
    page, sent, errors = builder()
    body = _save(page, sent)
    assert body.get("variables") == {}, body.get("variables")
    assert body.get("name") == THEME_NAME
    assert not errors, errors


def test_saving_one_changed_color_sends_only_that_color(builder):
    """שינוי של צבע אחד בטופס נשלח לבדו — ושאר הטופס, כולל הזכוכית, לא נכתב חזרה."""
    page, sent, errors = builder()
    page.fill("#primaryText", "#123456")
    page.dispatch_event("#primaryText", "change")
    body = _save(page, sent)
    assert {k.lower(): str(v).lower() for k, v in body["variables"].items()} == {"--primary": "#123456"}
    assert not errors, errors


def test_the_opacity_slider_keeps_each_glass_colour(builder):
    """אפשרות א: המחוון משנה את השקיפות של שלושת המשתנים יחד, כמו עד היום — וכל אחד שומר את הצבע שלו."""
    page, sent, errors = builder()
    _set_opacity(page, 40)
    colors = _publish(page, sent)["colors"]
    expected = {
        "--glass": ((224, 218, 211), 0.40),
        "--glass-border": ((110, 78, 68), 0.50),
        "--glass-hover": ((110, 78, 68), 0.45),
    }
    for name, (rgb, alpha) in expected.items():
        got_rgb, got_alpha = _rgba(colors[name])
        assert got_rgb == rgb and abs(got_alpha - alpha) < 1e-9, (name, colors[name])
    assert not errors, errors


def test_a_new_theme_still_gets_white_glass(builder):
    """ערכה חדשה, שנבנית מאפס בבונה, שולחת את כל הטופס, והזכוכית לבנה — בדיוק כמו עד היום."""
    page, sent, errors = builder()
    page.click("#createNewThemeBtn")
    page.wait_for_function("() => document.getElementById('themeName').value === ''", timeout=WAIT_S * 1000)
    page.fill("#themeName", "ערכה חדשה")
    page.click("#saveThemeBtn")
    variables = _wait_for(page, sent, "create")["variables"]
    assert variables["--glass"] == "rgba(255, 255, 255, 0.10)"
    assert variables["--glass-border"] == "rgba(255, 255, 255, 0.20)"
    assert variables["--glass-hover"] == "rgba(255, 255, 255, 0.15)"
    # כל הטופס נשלח, כי אין ערכה מקורית שאפשר להשאיר אותו בה.
    assert {"--bg-primary", "--primary", "--text-primary", "--glass-blur"} <= set(variables)
    assert not errors, errors
