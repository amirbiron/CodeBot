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

#: כתובת מונגו לבדיקות שאינן יכולות לרוץ מול סטאב. בלעדיה הן מדולגות.
NOTE_FONTS_TEST_MONGO_URI = os.getenv("NOTE_FONTS_TEST_MONGO_URI")

#: דילוג אחיד. **חובה על כל בדיקה שמשתמשת ב-**``wired_mongo``: בלי זה
#: הפיקסצ'ר רץ עם ``MongoClient(None)``, נופל ל-``localhost:27017``,
#: מנסה להתחבר ונכשל — ו-``--maxfail=1`` ב-``pytest.ini`` הופך את זה
#: לעצירה של כל החבילה, לא לבדיקה בודדת שנכשלת.
requires_test_mongo = pytest.mark.skipif(
    not NOTE_FONTS_TEST_MONGO_URI,
    reason="דורש מונגו אמיתי; הגדירו NOTE_FONTS_TEST_MONGO_URI",
)


@pytest.fixture
def wired_mongo(request):
    """מפנה את ``webapp.app`` למסד ייעודי, ומחזיר הכול בסיום.

    **שני דברים שנראים טכניים ואינם.**

    ``DATABASE_NAME`` נדרס ולא רק ה-URI: ``get_db`` מחזיר
    ``client[DATABASE_NAME]``, וברירת המחדל היא ``code_keeper_bot``.
    בלי הדריסה, ``drop_database`` מוחק מסד שאיש אינו פותח, ואילו
    ``delete_many`` ו-``insert_one`` פוגעים במסד **האמיתי** — כלומר
    הפניית ``NOTE_FONTS_TEST_MONGO_URI`` למונגו של פרודקשן הייתה
    מוחקת משתמש אמיתי.

    והשחזור ב-``finally`` אינו נימוס: ``webapp.app`` הוא מודול, ומצבו
    נשמר לכל אורך התהליך. בלעדיו כל בדיקה אחרת שרצה אחריו ממשיכה
    להתחבר למונגו של הבדיקות.

    שם המסד נגזר משם קובץ הבדיקה, כדי ששני קבצים שרצים באותה הרצה לא
    ידרסו זה את זה.
    """
    import pymongo

    import webapp.app as wa

    db_name = "cktest_" + Path(str(request.node.fspath)).stem
    previous = (wa.MONGODB_URL, wa.DATABASE_NAME, wa.client, wa.db)
    pymongo.MongoClient(NOTE_FONTS_TEST_MONGO_URI).drop_database(db_name)
    wa.MONGODB_URL = NOTE_FONTS_TEST_MONGO_URI
    wa.DATABASE_NAME = db_name
    wa.client = None
    wa.db = None
    wa.app.config["TESTING"] = True
    try:
        yield wa
    finally:
        # הלקוח שנפתח כאן נסגר; אחרת כל הרצה מדליפה pool של חיבורים.
        try:
            if wa.client is not None:
                wa.client.close()
        except Exception:
            pass
        wa.MONGODB_URL, wa.DATABASE_NAME, wa.client, wa.db = previous
