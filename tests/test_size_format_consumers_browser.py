"""הצרכנים של ``size-format.js`` עובדים בסדר הטעינה האמיתי של האפליקציה.

**הבאג שהבדיקה הזו נולדה ממנו.** המודול המשותף נטען בהתחלה עם ``defer``, ובדיקת
היחידה לא ראתה בעיה — כל הקריאות ל-``formatFileSize`` יושבות בתוך פונקציות.
אבל ``compare_files.html`` קורא ל-``CompareView.initFilesMode`` ב-script אינליין
שרץ **בזמן ניתוח המסמך**, וכשיש קבצים נבחרים מראש הוא מגיע משם ל-
``updateFilePreview`` ← ``formatFileSize`` מיד. סקריפט דחוי עדיין לא רץ באותו
רגע, והאתחול נפל ב-``TypeError: Cannot read properties of undefined``.

**למה הבדיקה שולפת את תג ה-``<script>`` מ-``base.html`` ולא כותבת אותו כאן.**
הדבר שנשבר הוא **התכונה על התג**, לא הקוד. תג שנכתב בקובץ הבדיקה היה מתעד את
מה שהבדיקה מקווה שקיים, וממשיך לעבור גם אחרי ש-``defer`` יחזור לתבנית. שליפה
מהתבנית האמיתית פירושה שהחזרת ``defer`` מפילה את הבדיקה — וזה כל תפקידה.

הבדיקה מכסה גם את ``live-preview.js``, שמשתמש במודול דרך ``updateMeta``.

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
BASE_TEMPLATE = REPO_ROOT / "webapp" / "templates" / "base.html"

#: תג הטעינה של המודול המשותף, כפי שהוא ב-``base.html``.
SIZE_FORMAT_TAG_RE = re.compile(r"<script[^>]*?size-format\.js[^>]*?>\s*</script>")

#: ההחלפה היחידה בתג: ה-``src`` של Jinja בנתיב שאפשר להגיש. שאר התכונות —
#: ובראשן ``defer``, אם מישהו יחזיר אותה — נשארות בדיוק כפי שהן.
SRC_ATTR_RE = re.compile(r'src="[^"]*"')

MIME_TYPES = {".js": "application/javascript", ".html": "text/html"}


def size_format_script_tag() -> str:
    """התג האמיתי מ-``base.html``, עם ``src`` שאפשר להגיש."""
    match = SIZE_FORMAT_TAG_RE.search(BASE_TEMPLATE.read_text(encoding="utf-8"))
    assert match, "לא נמצא תג טעינה של size-format.js ב-base.html"
    return SRC_ATTR_RE.sub('src="/js/utils/size-format.js"', match.group(0))


#: העמוד משחזר את סדר הטעינה של האפליקציה: המודול המשותף במקום שבו
#: ``base.html`` טוען אותו, והצרכנים אחריו — במקום של ``block extra_js``.
#: ה-DOM הוא המינימום שהצרכנים באמת נוגעים בו.
PAGE_TEMPLATE = """<!doctype html>
<html dir="rtl" lang="he"><head><meta charset="utf-8"></head><body>
  __SIZE_FORMAT_TAG__

  <select id="file-left"></select>
  <select id="file-right"></select>
  <div id="preview-left"><span class="size-text">-</span></div>
  <div id="preview-right"><span class="size-text">-</span></div>

  <div id="livePreviewRoot">
    <div data-preview-content><div data-preview-canvas></div></div>
    <div data-preview-meta></div>
    <p data-preview-status></p>
  </div>

  <script src="/js/compare.js"></script>
  <script src="/js/live-preview.js" defer></script>
  <script>
    // בדיוק מה ש-compare_files.html עושה: קריאה סינכרונית בזמן ניתוח המסמך,
    // עם קבצים נבחרים מראש. זה המסלול שנפל.
    window.__compareInit = { ok: null };
    try {
      window.CompareView.initFilesMode({
        files: [
          {_id: "a", file_size: 107520, programming_language: "python", lines_count: 12},
          {_id: "b", file_size: 4096, programming_language: "python", lines_count: 3}
        ],
        selectedLeft: "a",
        selectedRight: "b"
      });
      window.__compareInit.ok = true;
    } catch (error) {
      window.__compareInit.ok = false;
      window.__compareInit.error = String(error);
    }
  </script>
</body></html>
"""


@pytest.fixture(scope="module")
def loaded_page(chromium_executable):
    """מעלה את העמוד פעם אחת ומחזיר את מה שנמדד עליו.

    הקבצים מוגשים דרך ``page.route`` מהדיסק, ולכן שום דבר אינו נכתב לתוך
    ``webapp/static`` ואין צורך בשרת.

    ``chromium_executable`` מגיע מ-``tests/conftest.py``; pytest מוצא אותו לבד,
    בלי ייבוא בין קבצי טסט. ``None`` פירושו "תן ל-Playwright לחפש בעצמו" ולא
    "אין דפדפן" — שתי הדרכים נחוצות: בסביבה הזו הגרסה שמותקנת אינה הרוויזיה
    ש-Playwright מחפש בעצמו, ורק הנתיב מהפיקסצ'ר עובד.
    """
    # ``replace`` ולא ``format``: העמוד מלא בסוגריים מסולסלים של JS,
    # ו-``format`` היה מנסה לפרש כל אחד מהם כמציין-מקום.
    page_html = PAGE_TEMPLATE.replace("__SIZE_FORMAT_TAG__", size_format_script_tag())

    def serve(route):
        path = urlsplit(route.request.url).path
        if path == "/page.html":
            route.fulfill(status=200, content_type="text/html", body=page_html)
            return
        target = (STATIC_DIR / path.lstrip("/")).resolve()
        if not target.is_file() or STATIC_DIR.resolve() not in target.parents:
            route.fulfill(status=404, body="")
            return
        route.fulfill(
            status=200,
            content_type=MIME_TYPES.get(target.suffix, "text/plain"),
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
            page = browser.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.route("**/*", serve)
            page.goto("http://codebot.test/page.html", wait_until="load")

            result = {
                "compare_init": page.evaluate("window.__compareInit"),
                "left_size": page.eval_on_selector("#preview-left .size-text", "el => el.textContent"),
                "right_size": page.eval_on_selector("#preview-right .size-text", "el => el.textContent"),
                "meta": page.evaluate(
                    """() => {
                        const out = {};
                        const el = document.querySelector('[data-preview-meta]');
                        const call = (meta) => {
                            window.livePreviewController.updateMeta(meta);
                            return el.textContent;
                        };
                        out.controller = typeof window.livePreviewController;
                        out.small = call({language: 'markdown', bytes: 582});
                        out.large = call({language: 'markdown', bytes: 3.5 * 1024 * 1024, duration_ms: 12});
                        out.missing = call({language: 'markdown'});
                        out.not_a_number = call({language: 'markdown', bytes: 'לא מספר'});
                        return out;
                    }"""
                ),
                # שני ניסיונות השיבוש נמדדים בנפרד: אילו רצו יחד, החלפת
                # הפונקציה הייתה מסתירה את התוצאה של שינוי ``UNITS`` ובדיקת
                # ההקפאה של המערך לא הייתה מוכיחה דבר.
                "tamper_units": page.evaluate(
                    """() => {
                        const before = window.SizeFormat.formatFileSize(2048);
                        try { window.SizeFormat.UNITS[1] = 'שיבוש'; } catch (e) { /* strict mode זורק */ }
                        return { before, after: window.SizeFormat.formatFileSize(2048) };
                    }"""
                ),
                "tamper_function": page.evaluate(
                    """() => {
                        const before = window.SizeFormat.formatFileSize(2048);
                        try { window.SizeFormat.formatFileSize = () => 'נחטף'; } catch (e) { /* כנ"ל */ }
                        return { before, after: window.SizeFormat.formatFileSize(2048) };
                    }"""
                ),
                "errors": errors,
            }
        finally:
            browser.close()
    return result


def test_compare_files_initialises_during_parsing(loaded_page):
    """המסלול שנפל: אתחול סינכרוני עם קבצים נבחרים מראש.

    ייכשל שוב אם ``defer`` יחזור לתג ב-``base.html`` — התג נשלף משם.
    """
    init = loaded_page["compare_init"]

    assert init["ok"] is True, (
        "אתחול compare_files נפל בזמן ניתוח המסמך: "
        f"{init.get('error')}. סביר שהמודול המשותף נטען שוב עם defer."
    )
    assert loaded_page["errors"] == [], f"שגיאות JS בעמוד: {loaded_page['errors']}"


def test_compare_files_renders_the_shared_format(loaded_page):
    """ולא רק "לא קרס" — הערך שהוצג הוא הערך הנכון."""
    assert "105 KB" in loaded_page["left_size"]
    assert "4 KB" in loaded_page["right_size"]


def test_live_preview_meta_uses_the_shared_format(loaded_page):
    """``updateMeta`` — הצרכן שהמימוש הישן שלו הציג "0.6KB" ו-"3584KB"."""
    meta = loaded_page["meta"]

    assert meta["controller"] == "object", "livePreviewController לא נוצר"
    assert "582 B" in meta["small"], meta["small"]
    assert "3.5 MB" in meta["large"], meta["large"]
    assert "12ms" in meta["large"], "שאר שדות המטא נעלמו"


@pytest.mark.parametrize("case", ["missing", "not_a_number"])
def test_live_preview_meta_omits_a_size_that_is_not_a_number(loaded_page, case):
    """השומר ``typeof meta.bytes === 'number'`` — בלעדיו הופיע "0 B" מזויף.

    גודל שאינו מספר פירושו "אין מידע", ולא "אפס בתים".
    """
    text = loaded_page["meta"][case]

    assert "B" not in text and "KB" not in text, f"הוצג גודל למרות שאין: {text!r}"
    assert "markdown" in text, "שאר שדות המטא נעלמו יחד עם הגודל"


@pytest.mark.parametrize(
    "probe, what",
    [
        ("tamper_units", "שינוי של SizeFormat.UNITS"),
        ("tamper_function", "החלפה של SizeFormat.formatFileSize"),
    ],
)
def test_the_exported_api_cannot_be_tampered_with(loaded_page, probe, what):
    """``UNITS`` והאובייקט המיוצא מוקפאים.

    בלי זה כל סקריפט בעמוד היה יכול לשנות את טבלת היחידות או להחליף את
    הפונקציה, ולשנות בכך את התצוגה בכל ששת הצרכנים בבת אחת.
    """
    result = loaded_page[probe]

    assert result["before"] == result["after"], (
        f"{what} שינה את התוצאה: {result['before']!r} ← {result['after']!r}"
    )
    assert "2 KB" in result["after"]
