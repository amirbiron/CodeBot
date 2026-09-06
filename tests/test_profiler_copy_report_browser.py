"""בדיקת התנהגות אמיתית לכפתור "העתק דוח ל-AI" ב-``/admin/profiler``.

בדיקת שרת מאמתת שה-HTML נוצר. היא **אינה** יכולה לאמת מה יש בלוח: הדוח
נבנה ב-JS מתוך מה שהמשתמש ביקש ומתוך מה שהשרת החזיר, וההרכבה הזו קורית
רק בדפדפן. לכן הטסטים כאן קוראים את ``navigator.clipboard`` בפועל.

שלושת הטסטים האחרונים תופסים באגים שהיו בקוד:

* דוח שהסיק את רמת הפירוט מתוך "אין מספרים", ולכן הכריז "רץ ב-queryPlanner"
  גם על ניתוח שרץ ב-``executionStats`` והחזיר אפס.
* שורת גדר בתוך דוגמת הקוד, שסגרה את הבלוק מוקדם וקטעה את הדוח.
* גרש אחורי בשם ה-collection, שסגר את תוחם הקוד-בשורה וקטע את השם.

הטסט מדולג בשקט כשאין Chromium — הוא נועד לרוץ מקומית ובכל סביבה שיש בה
דפדפן, ולא להפיל CI שאין בו אחד. הדפוס לקוח מ-``test_admin_mcp_tabs_browser.py``.
"""

from __future__ import annotations

import json
import os
import threading

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

COLLECTION = "code_snippets"

#: תשובת ``find`` עם מדידה אמיתית.
FIND_WITH_STATS = {
    "status": "success",
    "data": {
        "explain": {
            "query_id": "q1",
            "collection": COLLECTION,
            "query_shape": {"user_id": "<value>"},
            "winning_plan": {
                "stage": "COLLSCAN", "index_name": None, "direction": "forward",
                "filter_condition": None, "input_stage": None, "children": [],
            },
            "rejected_plans": [],
            "stats": {
                "execution_time_ms": 1053, "docs_examined": 48213, "docs_returned": 25,
                "keys_examined": 0, "index_used": None, "is_covered_query": False,
                "efficiency_ratio": 0.0005,
            },
            "timestamp": "2026-09-05T22:00:00",
        },
        "recommendations": [],
    },
}

#: אותה שאילתה, בלי מדידה — ``queryPlanner`` אינו מריץ אותה.
FIND_WITHOUT_STATS = json.loads(json.dumps(FIND_WITH_STATS))
FIND_WITHOUT_STATS["data"]["explain"]["stats"] = None

#: ``aggregate`` שרץ ב-``executionStats`` וסכום זמני השלבים שלו הוא אפס.
#: ``total_execution_time_ms`` הוא סכום של ``execution_time_ms`` לכל שלב
#: (``services/query_profiler_service.py``), ולכן אפס הוא ערך אפשרי לגמרי
#: גם כשהמדידה כן רצה.
AGGREGATE_ZERO_TIME = {
    "status": "success",
    "data": {
        "aggregation_explain": {
            "query_id": "q2",
            "collection": COLLECTION,
            "pipeline_shape": [{"$match": {"user_id": "<value>"}}],
            "stages": [{
                "stage_name": "$match", "execution_time_ms": 0.0, "docs_examined": 3,
                "n_returned": 3, "uses_disk": False, "memory_usage_bytes": 0,
                "index_used": None, "lookup_collection": None, "lookup_strategy": None,
            }],
            "total_execution_time_ms": 0.0,
            "timestamp": "2026-09-05T22:00:00",
        },
        "recommendations": [],
    },
}

#: שם collection שמכיל גרש אחורי. הוא נכנס לדוח כקוד-בשורה, ותוחם של גרש
#: אחד נסגר על הגרש הראשון שבתוכן — כלומר השם נקטע.
HOSTILE_COLLECTION = "code`snippets"

#: דוגמת קוד שמכילה **שורת גדר שלמה**.
#:
#: זה מה שבאמת שובר בלוק קוד, ולא גרשיים באמצע שורה: לפי CommonMark גדר
#: סוגרת "may be followed only by spaces or tabs", ולכן ``a```b`` בתוך שורה
#: אינו סוגר כלום. הקלט הזה נגזר משם שדה שמכיל שורה חדשה ואז שלושה
#: גרשיים — JSON חוקי לגמרי בתיבת הטקסט, ו-``_create_collscan_recommendation``
#: משרשר את שם השדה לדוגמה כמו שהוא.
HOSTILE_CODE_EXAMPLE = 'db.code_snippets.createIndex({ "a\n```\nb": 1 })'

FIND_WITH_HOSTILE_RECOMMENDATION = json.loads(json.dumps(FIND_WITH_STATS))
FIND_WITH_HOSTILE_RECOMMENDATION["data"]["explain"]["collection"] = HOSTILE_COLLECTION
FIND_WITH_HOSTILE_RECOMMENDATION["data"]["recommendations"] = [{
    "id": "r1",
    "title": "🔴 COLLSCAN זוהה",
    "description": "סריקה מלאה",
    "severity": "critical",
    "category": "index",
    "suggested_action": "צור אינדקס",
    "estimated_improvement": "פי 10",
    "code_example": HOSTILE_CODE_EXAMPLE,
    "documentation_link": "",
}]


def _find_chromium():
    """מאתר Chromium מותקן. מחזיר ``None`` אם אין — הטסט ידולג."""
    from pathlib import Path

    root_env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    root = Path(root_env) if root_env else None
    if root and root.is_dir():
        for candidate in sorted(root.glob("chromium*/chrome-linux/chrome")):
            if candidate.exists():
                return str(candidate)
    return None


def fenced_block(report: str, info: str) -> str:
    """מחלץ את תוכן בלוק הקוד לפי כללי CommonMark, כמו כל קורא Markdown.

    זה לב הטסט של הגדרות: **לא** מחפשים מחרוזת בדוח, אלא מפרשים אותו.
    לפי CommonMark 0.31.2 גדר פותחת היא רצף של שלושה גרשיים אחוריים או
    יותר, והגדר הסוגרת חייבת להיות "at least as long as the opening
    fence" — ולכן גדר של שלושה שנפתחה על תוכן שמכיל שלושה נסגרת מוקדם,
    והתוכן נקטע. הפונקציה הזו תיפול בדיוק על המקרה הזה.
    """
    lines = report.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("```") or not stripped.endswith(info) or info == "":
            continue
        fence = stripped[: len(stripped) - len(info)]
        if set(fence) != {"`"} or len(fence) < 3:
            continue
        body = []
        for following in lines[i + 1:]:
            candidate = following.strip()
            if set(candidate) == {"`"} and len(candidate) >= len(fence):
                return "\n".join(body)
            body.append(following)
        raise AssertionError(f"בלוק ה-{info} נפתח ולא נסגר")
    raise AssertionError(f"לא נמצא בלוק {info} בדוח")


def code_span(line: str) -> str:
    """מחלץ קוד-בשורה לפי כללי CommonMark, כמו כל קורא Markdown.

    התוחם הוא רצף גרשיים, והסוגר חייב להיות **באותו אורך בדיוק**. לכן
    תוחם של גרש אחד על תוכן שמכיל גרש אחד נסגר מוקדם, והתוכן נקטע. בנוסף,
    כשהתוצאה מתחילה ומסתיימת ברווח — רווח אחד מוסר מכל צד.
    """
    import re

    match = re.search(r"(`+)", line)
    assert match, f"אין קוד-בשורה בשורה: {line!r}"
    delim = match.group(1)
    rest = line[match.end():]
    closing = re.search(r"(?<!`)" + "`" * len(delim) + r"(?!`)", rest)
    assert closing, f"תוחם הקוד לא נסגר: {line!r}"
    content = rest[: closing.start()]
    if len(content) > 1 and content.startswith(" ") and content.endswith(" "):
        content = content[1:-1]
    return content


@pytest.fixture(scope="module")
def live_server():
    """מריץ את הוובאפ האמיתי עם session של אדמין, בלי לגעת ב-DB או ברשת."""
    import time
    import urllib.request

    import webapp.app as app_mod
    from werkzeug.serving import make_server

    # ``MonkeyPatch.context`` ולא ``MonkeyPatch()`` ידני: הוא מבטל את עצמו
    # ביציאה מהבלוק **גם כשההקמה נופלת באמצע**. עם ``patch.undo()`` שיושב רק
    # אחרי ה-yield, חריגה בהקמה הייתה מותירה ``ADMIN_USER_IDS`` ו-``SECRET_KEY``
    # דרוכים לכל שאר הסוויטה — כשל שמתגלה בטסט אחר לגמרי.
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("ADMIN_USER_IDS", "1")

        app = app_mod.app
        patch.setitem(app.config, "SECRET_KEY", "profiler-copy-test")

        # ה-session נבנה דרך ``test_client``, לא דרך route עזר: Flask אוסר
        # ``@app.route`` אחרי הבקשה הראשונה, ובסוויטה מלאה טסט קודם כבר עשה זאת.
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = 1
                sess["user_data"] = {"id": 1, "is_admin": True, "is_premium": False}
            cookie = client.get_cookie("session")
            assert cookie is not None, "לא נוצר session cookie"
            session_cookie = cookie.value

        # פורט 0: הליבה בוחרת פורט פנוי ומקצה אותו באותה פעולה. בחירת פורט
        # מראש ואז bind נפרד היא חלון מירוץ — מישהו אחר יכול לתפוס אותו בין
        # שתי הפעולות.
        httpd = make_server("127.0.0.1", 0, app, threaded=True)
        port = httpd.server_port
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()

        try:
            for _ in range(60):
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1)
                    break
                except Exception as exc:
                    if "HTTP Error" in str(exc):  # השרת עונה, גם אם 404
                        break
                    time.sleep(0.25)
            else:  # pragma: no cover
                pytest.skip("שרת הבדיקה לא עלה")

            yield f"http://127.0.0.1:{port}", session_cookie
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)


@pytest.fixture
def page(live_server):
    base_url, session_cookie = live_server
    executable = _find_chromium()
    with sync_playwright() as pw:
        try:
            browser = (
                pw.chromium.launch(executable_path=executable)
                if executable
                else pw.chromium.launch()
            )
        except Exception as exc:  # pragma: no cover
            pytest.skip(f"אין Chromium זמין: {exc}")

        # ``Browser`` ו-``BrowserContext`` הם context managers, ולכן הם נסגרים
        # גם כשההקמה שאחריהם נופלת. ``close()`` ידני אחרי ה-yield לא היה רץ אם
        # ``goto`` זרק — והתהליך של Chromium היה נשאר תלוי עד סוף הריצה.
        with browser, browser.new_context(
            viewport={"width": 1280, "height": 900},
            # בלי ההרשאות האלה ``clipboard.readText`` נחסם, והטסט היה בודק
            # את עצמו במקום את הדף.
            permissions=["clipboard-read", "clipboard-write"],
        ) as context:
            context.add_cookies([{
                "name": "session", "value": session_cookie,
                "domain": "127.0.0.1", "path": "/",
            }])
            p = context.new_page()
            # מודאל ה-onboarding נפתח למשתמש חדש וחוסם קליקים בעמוד.
            p.add_init_script(
                "try{localStorage.setItem('welcomeModalSeen','1');"
                "localStorage.setItem('onboarding_completed','1');}catch(e){}"
            )
            p.goto(f"{base_url}/admin/profiler", wait_until="domcontentloaded")
            p.wait_for_timeout(300)
            p.evaluate(
                "document.querySelectorAll('.welcome-modal, .welcome-modal__backdrop, #welcomeModal')"
                ".forEach(e => e.remove())"
            )
            yield p


def copy_report(page, payload, *, verbosity, aggregate=False, collection=COLLECTION):
    """מנתח ומעתיק, ומחזיר את **תוכן הלוח בפועל**."""
    page.route(
        "**/api/profiler/recommendations",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(payload)
        ),
    )
    page.fill("#analyze-collection", collection)
    page.select_option("#analyze-verbosity", verbosity)
    if aggregate:
        page.select_option("#analyze-operation", "aggregate")
        page.fill("#analyze-pipeline", '[{"$match": {"user_id": "1"}}]')
    else:
        page.fill("#analyze-query", '{"user_id": "1"}')

    page.click('button[onclick="analyzeQuery()"]')
    page.wait_for_selector("#analysis-results", state="visible", timeout=10000)
    page.click("button:has-text('העתק דוח ל-AI')")
    page.wait_for_timeout(400)
    return page.evaluate("navigator.clipboard.readText()")


def test_the_report_carries_the_measurements_when_execution_stats_ran(page):
    report = copy_report(page, FIND_WITH_STATS, verbosity="executionStats")

    assert COLLECTION in report
    assert "executionStats" in report
    assert "1053" in report, "זמן הביצוע לא הגיע לדוח"
    assert "48213" in report, "מספר המסמכים שנסרקו לא הגיע לדוח"
    assert "אין מדידה" not in report


def test_query_planner_says_it_did_not_measure(page):
    report = copy_report(page, FIND_WITHOUT_STATS, verbosity="queryPlanner")

    assert "אין מדידה" in report
    assert "לא נמדדה" in report, "הדוח חייב לומר במפורש שאין להסיק מהיעדר המספרים"


def test_zero_milliseconds_under_execution_stats_is_not_reported_as_unmeasured(page):
    """אפס אינו "לא נמדד" — הוא מדידה, וזה ההבדל שהדוח שידר הפוך.

    ``executionStats`` על pipeline קטן מסכם לאפס מילישניות. הקוד הישן קרא
    את האפס כ"אין זמנים" והכריז שהניתוח רץ ב-``queryPlanner`` — טענה שגויה,
    בשורה שכל תפקידה לומר מה נמדד ומה לא.
    """
    report = copy_report(page, AGGREGATE_ZERO_TIME, verbosity="executionStats", aggregate=True)

    assert "queryPlanner" not in report.split("## סטטיסטיקות ביצוע", 1)[1], (
        "הדוח מייחס לניתוח רמת פירוט שלא רצה"
    )
    assert "אין מדידה" not in report, "מדידה שהחזירה אפס אינה היעדר מדידה"
    assert "0.00 ms" in report, "האפס עצמו חייב להופיע — הוא התוצאה"


def test_a_fence_line_inside_the_code_example_does_not_cut_the_report(page):
    """דוגמת קוד שמכילה שורת גדר לא תקטע את הדוח המודבק.

    הקלט מגיע משם שדה שהמשתמש הקליד, והשרת משרשר אותו לדוגמה. גדר של
    שלושה גרשיים נסגרת על שורת ``` שבתוכן, וכל מה שאחריה — כולל שאר
    הדוגמה — יוצא מהבלוק.
    """
    report = copy_report(
        page, FIND_WITH_HOSTILE_RECOMMENDATION,
        verbosity="executionStats", collection=HOSTILE_COLLECTION,
    )

    assert fenced_block(report, "javascript") == HOSTILE_CODE_EXAMPLE


def test_a_backtick_in_the_collection_name_does_not_cut_the_code_span(page):
    """שם collection עם גרש אחורי חייב לצאת שלם מהדוח."""
    report = copy_report(
        page, FIND_WITH_HOSTILE_RECOMMENDATION,
        verbosity="executionStats", collection=HOSTILE_COLLECTION,
    )

    line = next(ln for ln in report.split("\n") if ln.startswith("- **Collection:**"))
    assert code_span(line) == HOSTILE_COLLECTION


def test_the_shared_toast_is_actually_visible_on_this_page(page):
    """הטוסט המשותף חייב להיראות כאן, לא רק להיווצר.

    ``ckToast`` יוצר את הצומת בכל מקרה, אבל העיצוב שלו חי ב-``css/toast.css``
    — קובץ שהעמוד הזה לא טען קודם. אם ה-``<link>`` חסר או שגוי, הטוסט קיים
    ב-DOM ובלתי נראה על המסך, וזה בדיוק סוג הכשל שבדיקה על ה-DOM לבדה
    מפספסת. לכן נבדק כאן ``position: fixed`` שמגיע רק מאותו קובץ.
    """
    copy_report(page, FIND_WITH_STATS, verbosity="executionStats")

    state = page.evaluate("""() => {
        const container = document.getElementById('ckToastContainer');
        const toast = document.querySelector('.ck-toast');
        if (!container || !toast) return { exists: false };
        return {
            exists: true,
            containerPosition: getComputedStyle(container).position,
            visible: toast.getBoundingClientRect().width > 0,
            text: toast.textContent,
        };
    }""")

    assert state["exists"], "הטוסט המשותף לא נוצר — כנראה js/toast.js לא נטען"
    assert state["containerPosition"] == "fixed", (
        "css/toast.css לא נטען: המכל אינו ממוקם, כלומר הטוסט אינו נראה"
    )
    assert state["visible"], "הטוסט נוצר אך אין לו רוחב על המסך"
    assert "הועתק ללוח" in state["text"]
