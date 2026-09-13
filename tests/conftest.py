"""
tests/conftest.py

Auto-load telegram stubs for all tests and provide minimal, safe env defaults.

This file ensures that imports of the optional dependency `python-telegram-bot`
are satisfied by light-weight stubs during tests. Some environments might have
an unrelated top-level package named `tests` on sys.path which could shadow the
local test directory. To make the import resilient, we attempt a regular import
first, then prefer the local `tests` directory on sys.path, and finally fall
back to loading the stub module directly from its file path.
"""

import json
import os
import sys
from pathlib import Path
from typing import List, NamedTuple
import importlib.util
from urllib.parse import urlsplit

import pytest
try:
    from PIL import Image
except ModuleNotFoundError:  # pragma: no cover
    Image = None  # type: ignore[assignment]

# Ensure safe, isolated test environment variables (no external IO)
os.environ.setdefault('DISABLE_ACTIVITY_REPORTER', '1')
os.environ.setdefault('DISABLE_DB', '1')
os.environ.setdefault('BOT_TOKEN', 'x')
os.environ.setdefault('MONGODB_URL', 'mongodb://localhost:27017/test')

# Import stubs so any import of `telegram` succeeds in tests
try:
    import tests._telegram_stubs  # noqa: F401
except ModuleNotFoundError:
    # Prefer the project root (parent of tests dir) on sys.path to avoid
    # shadowing by unrelated top-level `tests` packages
    tests_dir = Path(__file__).parent
    project_root = tests_dir.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    # If a conflicting top-level `tests` package is already imported from a
    # different location, clear it so imports will resolve against our local
    # namespace package at project_root/tests.
    existing = sys.modules.get('tests')
    if existing is not None:
        tests_dir_str = str(tests_dir)
        module_paths = []
        pkg_path = getattr(existing, '__path__', None)
        if pkg_path is not None:
            try:
                module_paths = [str(p) for p in pkg_path]
            except Exception:
                module_paths = []
        module_file = getattr(existing, '__file__', None)
        # If our local tests directory is not among the package paths, it's a conflict
        if (tests_dir_str not in module_paths) and (not module_file or tests_dir_str not in module_file):
            sys.modules.pop('tests', None)
    try:
        import tests._telegram_stubs  # noqa: F401
    except ModuleNotFoundError:
        # Hard fallback: load the stub module directly from file
        stubs_path = tests_dir / "_telegram_stubs.py"
        spec = importlib.util.spec_from_file_location("tests._telegram_stubs", stubs_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            sys.modules["tests._telegram_stubs"] = module
            spec.loader.exec_module(module)  # type: ignore[union-attr]
        else:
            # If we cannot even locate the file, re-raise the original error
            raise


@pytest.fixture(scope="session", autouse=True)
def initialize_pillow_codecs():
    """מניעת Race Condition בטעינת פורמטים (PNG) בזמן ריצה מקבילית."""
    if Image is None:
        return
    Image.init()


# ── מונגו ייעודי לבדיקות שמריצות את הראוטים באמת ─────────────────────────


def _test_mongo_uri() -> "str | None":
    r"""כתובת מונגו לבדיקות שאינן יכולות לרוץ מול סטאב.

    **משתנה ייעודי ולא נפילה ל-**\ ``MONGODB_URL``: שורה 29 בקובץ הזה
    עושה ``os.environ.setdefault('MONGODB_URL', 'mongodb://localhost:27017/test')``,
    כלומר הוא **תמיד** מוגדר בבדיקות — לערך דמה. נפילה אליו הייתה
    גורמת לכל בדיקה לחכות 30 שניות לכתובת שאין מאחוריה שרת, ואז
    להיכשל; ו-``--maxfail=1`` היה עוצר את כל החבילה.

    ב-CI המשתנה מוגדר במפורש בג'וב, ולכן הבדיקות **כן** רצות שם.

    נקרא כפונקציה ולא כקבוע ברמת המודול, כדי שבדיקה שמשנה ``ENV``
    בזמן ריצה תיקרא נכון.
    """
    return os.getenv("NOTE_FONTS_TEST_MONGO_URI")


#: תוצאת בדיקת הנגישות, לפי URI. הבדיקה עולה כשנייה, והפיקסצ'ר רץ לכל
#: בדיקה — בלי מטמון היו עשרים ומשהו בדיקות כפול הבדיקה הזו.
#: ``test_note_boards_mongo`` מקבל את זה בחינם כי הוא משתמש ב-``pytestmark``
#: שנבדק פעם אחת בטעינת המודול.
_MONGO_REACHABLE: "dict[str, bool]" = {}


def _server_is_reachable(url: str) -> bool:
    """האם יש שרת בקצה השני.

    **זה לא נימוס, זה מה שמונע נפילת חבילה.** בג'וב ``unit-tests``
    השירות ``mongodb`` מוגדר בלי ``ports:`` והג'וב אינו רץ בקונטיינר,
    ולכן שם המארח אינו נפתר כלל: ``[Errno -3] Temporary failure in name
    resolution``. בלי הבדיקה הזו הפיקסצ'ר זורק, פיקסצ'ר שזורק הוא
    ``ERROR``, ו-``--maxfail=1`` ב-``pytest.ini`` הופך שגיאה אחת
    לעצירת כל ההרצה. זה קרה: 23 שגיאות בבנייה אחת.

    הדפוס לקוח מ-``tests/test_note_boards_mongo.py:45``.
    """
    if url in _MONGO_REACHABLE:
        return _MONGO_REACHABLE[url]
    try:
        import pymongo

        client = pymongo.MongoClient(url, serverSelectionTimeoutMS=2000)
        try:
            client.admin.command("ping")
            ok = True
        finally:
            client.close()
    except Exception:
        ok = False
    _MONGO_REACHABLE[url] = ok
    return ok


@pytest.fixture
def wired_mongo(request):
    """מפנה את ``webapp.app`` למסד ייעודי, ומחזיר הכול בסיום.

    **הדילוג חי כאן ולא ב-marker מיובא.** ``claude-md-snippets/testing.md``
    אוסר לייבא מ-``conftest`` — pytest מוצא פיקסצ'רים לבד, וייבוא מריץ את
    המודול פעם שנייה. הניסיון הראשון ייבא מכאן ``requires_test_mongo``,
    וזה בדיוק מה שהפיל את איסוף הבדיקות ב-CI.

    ``DATABASE_NAME`` נדרס ולא רק ה-URI: ``get_db`` מחזיר
    ``client[DATABASE_NAME]``, וברירת המחדל היא ``code_keeper_bot``.
    בלי הדריסה, ``drop_database`` מוחק מסד שאיש אינו פותח, ואילו
    ``delete_many`` ו-``insert_one`` פוגעים במסד **האמיתי**.

    שם המסד נגזר משם קובץ הבדיקה, כדי ששני קבצים באותה הרצה לא ידרסו
    זה את זה, **וגם ממזהה ה-worker** כשרצים במקביל.

    למה גם ה-worker: היום ``ci.yml`` מריץ ``--dist=loadscope``, ובמצב הזה
    כל הבדיקות של מודול אחד רצות באותו worker — נמדד מול xdist 3.8.0,
    ובריצת בקרה עם ``--dist=load`` אותו מודול התפצל בין ארבעה workers.
    כלומר שם לפי קובץ בלבד מספיק **רק כל עוד הדגל הזה נשאר**, והוא חי
    בקובץ אחר לגמרי. מעבר ל-``--dist=load`` היה שולח שני workers לאותו
    מסד, כשכל אחד מריץ ``drop_database`` ו-``delete_many`` בתחילת בדיקה —
    כלומר מוחק את הנתונים של השני באמצע הריצה שלו. השם נעשה עצמאי מהדגל.
    """
    import pymongo

    uri = _test_mongo_uri()
    if not uri:
        pytest.skip("דורש מונגו אמיתי; הגדירו NOTE_FONTS_TEST_MONGO_URI")
    if not _server_is_reachable(uri):
        pytest.skip(f"מונגו אינו נגיש ב-{uri}")

    import webapp.app as wa

    # ``PYTEST_XDIST_WORKER`` (למשל ``gw0``) קיים רק תחת xdist — בהרצה
    # רגילה הוא חסר, והשם נשאר בדיוק כפי שהיה.
    _worker = os.environ.get("PYTEST_XDIST_WORKER", "")
    db_name = "cktest_" + Path(str(request.node.fspath)).stem
    if _worker:
        db_name += "_" + _worker
    previous = (wa.MONGODB_URL, wa.DATABASE_NAME, wa.client, wa.db,
                wa.app.config.get("TESTING"))

    # הלקוח הזה נפתח כאן ולכן נסגר כאן. הוא **אינו** ``wa.client``.
    # timeout קצר: כתובת שגויה תיכשל מיד עם הודעה ברורה, במקום לתלות
    # כל בדיקה 30 שניות ואז להפיל את החבילה דרך ``--maxfail=1``.
    cleaner = pymongo.MongoClient(uri, serverSelectionTimeoutMS=5000)
    try:
        cleaner.drop_database(db_name)
    finally:
        cleaner.close()

    wa.MONGODB_URL = uri
    wa.DATABASE_NAME = db_name
    wa.client = None
    wa.db = None
    wa.app.config["TESTING"] = True
    try:
        yield wa
    finally:
        # **``wa.client`` לא נסגר כאן, במכוון.** הוא גלובל משותף, וקוד
        # אחר בתהליך מחזיק הפניות אליו ואל ``wa.db`` שנגזר ממנו. סגירתו
        # הפילה את ``get_db`` בבדיקות מאוחרות יותר עם
        # ``InvalidOperation: Cannot use MongoClient after close`` —
        # וזה מה שהפיל את איסוף הבדיקות ב-CI. השחזור של ההפניות מספיק;
        # הלקוח שנוצר כאן נאסף כרגיל כשאיש לא מחזיק בו.
        created_client = wa.client
        (wa.MONGODB_URL, wa.DATABASE_NAME, wa.client, wa.db,
         _prev_testing) = previous
        if created_client is not None and created_client is not previous[2]:
            created_client.close()
        if _prev_testing is None:
            wa.app.config.pop("TESTING", None)
        else:
            wa.app.config["TESTING"] = _prev_testing


# ---------------------------------------------------------------------------
# תשתית משותפת לבדיקות דפדפן (Playwright)
#
# הפיקסצ'רים כאן יושבים ב-``conftest.py`` ולא בקבצי הטסט, כי pytest מוצא אותם
# לבד — **בלי ייבוא בין קבצי טסט**, שהוא הדבר שכבר הפיל כאן CI פעם אחת.
# קודם כל קובץ דפדפן החזיק עותק משלו של אותן ~60 שורות (הרמת שרת, עוגיית
# אדמין, המתנה לבריאות, איתור Chromium), וכל תיקון היה צריך להשתכפל.
#
# ``tests/test_admin_mcp_tabs_browser.py`` **אינו** משתמש בהם, במכוון: הוא
# מזייף את ``get_mcp_analytics_service`` לפני שהשרת מתחיל להגיש, ולכן הוא
# צריך שליטה על סדר ההקמה. הוא מחזיק עותק משלו, וזה מתועד שם.
# ---------------------------------------------------------------------------


def _locate_chromium():
    """נתיב ל-Chromium מותקן, או ``None`` — ואז בדיקת הדפדפן מדולגת בשקט."""
    root_env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    root = Path(root_env) if root_env else None
    if root and root.is_dir():
        for candidate in sorted(root.glob("chromium*/chrome-linux/chrome")):
            if candidate.exists():
                return str(candidate)
    return None


#: תשובות ברירת מחדל שפירות ל-endpoints של הפרופיילר, בצורה המינימלית
#: שה-JS של הדשבורד צורך (``loadSummary`` קורא ``total_slow_queries``,
#: ``avg_execution_time_ms``, ``collections_affected``, ``unique_patterns``;
#: ``renderSlowQueriesTable`` עושה ``forEach`` על ``data``).
_PROFILER_STUB_RESPONSES = {
    "/api/profiler/summary": {
        "status": "success",
        "data": {
            "total_slow_queries": 0,
            "avg_execution_time_ms": 0,
            "collections_affected": [],
            "unique_patterns": 0,
        },
    },
    "/api/profiler/slow-queries": {"status": "success", "data": [], "count": 0},
}


@pytest.fixture
def stub_profiler_api():
    """מחזיר פונקציה שמתקינה יירוט **כללי** לכל ``/api/profiler/`` על עמוד.

    למה כללי ולא ראוט לכל endpoint: הדשבורד יורה ב-``DOMContentLoaded`` גם
    ``loadSummary()`` וגם ``refreshSlowQueries()``, ובנוסף מחזיק
    ``setInterval(loadSummary, 30000)``. יירוט לפי רשימה נשבר בשקט ברגע
    שהעמוד יוסיף fetch נוסף, והבקשה יוצאת לשרת האמיתי ומגיעה למסד הנתונים —
    שם היא נבלעת ב-``catch`` של ה-JS ואיש לא רואה.

    **סדר הרישום:** יש לקרוא לזה **לפני** רישום ראוטים ספציפיים. אומת במקור
    של playwright 1.62.0 (``_impl/_page.py``): ``route`` עושה
    ``self._routes.insert(0, ...)`` ו-``_on_route`` לוקח את ההתאמה הראשונה,
    כלומר **הראוט שנרשם אחרון מנצח**.
    """
    def _install(page):
        def _handle(route):
            path = urlsplit(route.request.url).path
            body = _PROFILER_STUB_RESPONSES.get(path, {"status": "success", "data": {}})
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

        page.route("**/api/profiler/**", _handle)

    return _install


#: נדלק כשהשער למטה הכריע שאין דפדפן, כדי ש-``pytest_terminal_summary``
#: יאמר את זה בקול. בלי זה הדילוג נבלע בתוך אות ``s`` אחת מבין מאות,
#: ואי אפשר לענות על "האם בדיקות הדפדפן רצו בכלל?".
_BROWSER_SKIP_REASON: list[str] = []


@pytest.fixture(scope="session")
def chromium_executable():
    """ה-Chromium שבדיקות הדפדפן ישתמשו בו — ואם אין כזה, הן מדולגות **כאן**.

    מחזיר נתיב, או ``None`` שפירושו "תן ל-Playwright לחפש בעצמו".

    **ההכרעה נעשית פעם אחת לכל הריצה, וזה תיקון שורש ולא אופטימיזציה.**
    "יש דפדפן או אין" היא עובדה אחת על הסביבה, קבועה לאורך כל הסשן. עד
    כאן היא נגזרה מחדש בכל בדיקה, וכל גזירה עברה דרך הרמת תהליך דרייבר
    של Playwright ותפיסת חריגה. נמדד על שבעת קובצי הדפדפן כשאין דפדפן:
    **66 בדיקות, 28.50 שניות, 66 הרמות של תהליך דרייבר, ואפס בדיקות
    שרצו.**

    **ולמה הצורה ההיא לא רק בזבזה זמן.** מסלול שנשען על חריגה מטופל היטב
    כשהחריגה נזרקת, ואינו מטופל בכלל כשהמסלול פשוט **אינו חוזר**. וזה
    קרה: בריצת CI על פייתון 3.12, בקובץ אחד עשר בדיקות שנשענות על
    ``dashboard`` דולגו כרגיל, ובדיקה אחת שנשענת על ``racing_dashboard``
    לא חזרה — היא נתקעה, חצתה את ``timeout`` שב-``pytest.ini`` והרג עובד
    xdist שלם, ושתי אחיותיה לא רצו בכלל. **ואותה בדיקה בדיוק דולגה על
    פייתון 3.11 באותה ריצה ועל אותו קוד**, כלומר השומר היה קיים ולא היה
    אמין. הכרעה אחת מסירה את התנאי המקדים: אין דפדפן ← אף אחד אינו מרים
    תהליך, ולכן אין חלון שבו תקיעה כזאת יכולה לקרות.

    **מה שלא אומת, ונאמר במפורש:** לא שוחזרה כאן התקיעה עצמה, ולכן
    **המנגנון הפנימי שלה אינו מוכח** — על פייתון 3.11 בקונטיינר הפיתוח
    כל 13 הבדיקות בקובץ ההוא דולגו ב-11.29 שניות בלי להיתקע. התיקון כאן
    אינו נשען על אותו מנגנון אלא על ההכרעה שקדמה לו.

    **והשומרים המקומיים בקובצי הבדיקות נשארים במקומם ואינם מיותרים.**
    השער הזה עונה על "האם יש דפדפן בסביבה הזאת", והם עונים על "האם
    ההרמה **הזאת** נכשלה" — כשל חולף בזמן ריצה, אחרי שהשער כבר אמר כן.
    """
    playwright = pytest.importorskip(
        "playwright.sync_api", reason="playwright אינו מותקן"
    )
    executable = _locate_chromium()
    try:
        with playwright.sync_playwright() as pw:
            browser = (
                pw.chromium.launch(executable_path=executable)
                if executable
                else pw.chromium.launch()
            )
            browser.close()
    except Exception as exc:  # pragma: no cover - תלוי בסביבה
        # השורה הראשונה בלבד לשורת הסיכום: Playwright מחזיר אחריה תיבת
        # ASCII בת עשר שורות עם הוראות התקנה, ותיבה כזאת בתוך שורת סיכום
        # הופכת אותה לבלתי קריאה. הטקסט המלא נשמר בסיבת הדילוג, ששם הוא
        # באמת עוזר — ``pytest -rs`` מציג אותו.
        _BROWSER_SKIP_REASON.append(str(exc).strip().split("\n")[0])
        pytest.skip(f"אין Chromium שאפשר להרים: {exc}")
    return executable


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """אומר בקול שבדיקות הדפדפן דולגו, במקום להשאיר את זה בין מאות ``s``.

    **הדיווח הוא חלק מהתיקון ולא קוסמטיקה.** דילוג שקט של סוויטה שלמה
    נראה זהה לדילוג של בדיקה בודדת, ולכן אי אפשר לדעת שהכיסוי ירד לאפס.
    ב-CI של הריפו הזה אין שלב שמתקין דפדפן, כלומר זה המצב **הרגיל** שם
    ולא תקלה — ובדיוק בגלל זה הוא צריך להיאמר, אחרת הוא נשכח.
    """
    if not _BROWSER_SKIP_REASON:
        return
    terminalreporter.write_sep("-", "בדיקות דפדפן")
    terminalreporter.write_line(
        "כל בדיקות הדפדפן דולגו — הכיסוי שלהן בריצה הזאת הוא אפס."
    )
    terminalreporter.write_line(f"  הסיבה: {_BROWSER_SKIP_REASON[0]}")


class AdminLiveServer(NamedTuple):
    """מה ש-``admin_live_server`` מחזיר.

    ``profiler_hits`` הוא רשימת הנתיבים תחת ``/api/profiler/`` שבאמת הגיעו
    לשרת. טסט בידוד בודק שהיא ריקה — כלומר סופר בצד השרת במקום להסיק
    מהיעדר שגיאה בדפדפן, ששם כל כשל רשת נבלע ב-``catch`` של ה-JS.
    """

    base_url: str
    session_cookie: str
    profiler_hits: List[str]


@pytest.fixture(scope="module")
def admin_live_server():
    """מריץ את הוובאפ האמיתי עם session של אדמין, בלי לגעת ב-DB או ברשת חיצונית.

    מרים שרת ``loopback`` מקומי על ``127.0.0.1`` בפורט אקראי — זו הרשת
    היחידה שנוגעים בה, ובדיקת הבריאות פונה אליו דרך ``urllib``. אין חיבור
    למסד נתונים ואין יציאה החוצה.

    מחזיר ``AdminLiveServer(base_url, session_cookie, profiler_hits)``.

    ``MonkeyPatch.context`` ולא ``MonkeyPatch()`` ידני: הוא מבטל את עצמו
    ביציאה מהבלוק **גם כשההקמה נופלת באמצע**. עם ``patch.undo()`` שיושב רק
    אחרי ה-yield, חריגה בהקמה הייתה מותירה ``ADMIN_USER_IDS`` ו-``SECRET_KEY``
    דרוכים לכל שאר הסוויטה — כשל שמתגלה בטסט אחר לגמרי.
    """
    import threading
    import time
    import urllib.request

    import webapp.app as app_mod
    from werkzeug.serving import make_server

    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("ADMIN_USER_IDS", "1")

        app = app_mod.app
        patch.setitem(app.config, "SECRET_KEY", "browser-tests-admin-session")

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
        # עטיפת WSGI שסופרת בקשות לפרופיילר שהגיעו לשרת האמיתי. היא כאן ולא
        # ב-``before_request`` של האפליקציה כדי לא לשנות קוד ייצור בשביל טסט.
        profiler_hits: List[str] = []

        def counting_app(environ, start_response):
            path = environ.get("PATH_INFO", "") or ""
            if path.startswith("/api/profiler/"):
                profiler_hits.append(path)
            return app(environ, start_response)

        httpd = make_server("127.0.0.1", 0, counting_app, threaded=True)
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

            yield AdminLiveServer(f"http://127.0.0.1:{port}", session_cookie, profiler_hits)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)
