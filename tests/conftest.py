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

import os
import sys
from pathlib import Path
import importlib.util

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
    """כתובת מונגו לבדיקות שאינן יכולות לרוץ מול סטאב.

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
    זה את זה.
    """
    import pymongo

    uri = _test_mongo_uri()
    if not uri:
        pytest.skip("דורש מונגו אמיתי; הגדירו NOTE_FONTS_TEST_MONGO_URI")
    if not _server_is_reachable(uri):
        pytest.skip(f"מונגו אינו נגיש ב-{uri}")

    import webapp.app as wa

    db_name = "cktest_" + Path(str(request.node.fspath)).stem
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


@pytest.fixture(scope="session")
def chromium_executable():
    """נתיב ל-Chromium, או ``None``. ``None`` פירושו "תן ל-Playwright לחפש"."""
    return _locate_chromium()


@pytest.fixture(scope="module")
def admin_live_server():
    """מריץ את הוובאפ האמיתי עם session של אדמין, בלי לגעת ב-DB או ברשת.

    מחזיר ``(base_url, session_cookie)``.

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
