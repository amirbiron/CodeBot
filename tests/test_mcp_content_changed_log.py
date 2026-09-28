"""שורת ה-``WARNING`` של רשת הביטחון — בתהליך נקי, ולא ב-``caplog``.

**למה לא ``caplog``:** הוא מתקין handler משלו על ה-root logger, ולכן טסט שכתוב
איתו עובר בלי קשר למה שהתהליך מוגדר לעשות — כך שורות לוג יצאו ירוקות ולא הופיעו
בייצור (``tests/test_mcp_logging_visible.py``). כאן רץ מפרש חדש, שמייבא את
``mcp_server.app`` כמו ש-uvicorn עושה — שם מוגדר הלוג של השירות — ומה שנבדק הוא
מה שהגיע בפועל ל-stdout/stderr שלו.

**למה השורה חשובה:** תשובה מגוף כלי נרשמת ב-PostHog כהצלחה, ו-``$mcp_response``
נחסם בשער הפרטיות. בלי השורה, אף אחד חוץ מהסוכן לא יודע שהרשת תפסה משהו.

**ומה אסור שיהיה בה:** code points ותוכן. המילה "הסודית" כאן, שם הקובץ, וכל
``U+`` — לא מופיעים בפלט, גם לא ב-traceback של כשל הקריאה החוזרת.

התהליך רץ עם ``-B`` ו-``cwd=tmp_path``: שום ``__pycache__`` ושום קובץ לא נכתבים לעץ.
"""

import os
import pathlib
import subprocess
import sys
import textwrap

import pytest

pytest.importorskip("mcp")
pytest.importorskip("structlog")

REPO = str(pathlib.Path(__file__).resolve().parents[1])
SECRET_WORD = "תוכן-פרטי-של-המשתמש"
FILE_NAME = "private-name.md"

_PROBE = """
import os, sys
sys.path.insert(0, {repo!r})
os.environ["MCP_PUSH_NOTIFICATIONS_ENABLED"] = "false"
try:
    import mcp_server.app  # noqa: F401 — הגדרת הלוג של השירות, כמו ב-uvicorn
except Exception:
    pass

from pymongo.errors import AutoReconnect
from mcp_server.backend import ProductionBackend

RLM = "\\u200f"
SECRET_WORD = {secret!r}
FILE_NAME = {file_name!r}


class _Dbm:
    '''שכבת מסד קטנה עם שלושה מסלולים — לפי שם הכלי, כדי לייחס כל שורה למסלול שלה.'''

    def __init__(self):
        self.docs = {{}}

    def get_latest_version_fresh(self, user_id, file_name):
        return None

    def save_code_snippet_returning_id(self, snippet):
        snippet.version = 7
        doc_id = "65f0c0ffee00000000000" + str(len(self.docs) + 100)
        code = snippet.code
        if snippet.description == "lose-rlm":
            code = code.replace(RLM, "", 1)
        self.docs[doc_id] = {{"_id": doc_id, "user_id": snippet.user_id, "file_name": snippet.file_name,
                             "version": 7, "code": code, "description": snippet.description}}
        return doc_id

    def find_version_by_id(self, doc_id, user_id):
        doc = self.docs.get(doc_id)
        if doc and doc["description"] == "read-back-fails":
            raise AutoReconnect("connection reset during read-back")
        return dict(doc) if doc and doc["user_id"] == user_id else None


backend = ProductionBackend(db_manager=_Dbm())
sent = "שורה ראשונה\\n" + SECRET_WORD + RLM + " המשך\\n"
equal = backend.save_file(5, file_name=FILE_NAME, code=sent, programming_language="markdown",
                          tool="codekeeper_save_file")
changed = backend.save_file(5, file_name=FILE_NAME, code=sent, programming_language="markdown",
                            description="lose-rlm", tool="codekeeper_edit_file")
unread = backend.save_file(5, file_name=FILE_NAME, code=sent, programming_language="markdown",
                           description="read-back-fails", tool="codekeeper_append_file")
assert equal["content_changed"] is False, equal
assert changed["content_changed"] is True, changed
assert unread["content_changed"] is None, unread
print("PROBE-DONE", flush=True)
"""


#: כשל אמיתי של הקריאה החוזרת, דרך ``Repository.find_version_by_id`` ו-pymongo אמיתי,
#: מול שרת שאינו קיים — עם סיסמה ושם משתמש בכתובת החיבור. בלי mongod: בחירת השרת
#: נכשלת אחרי ``serverSelectionTimeoutMS``.
_PASSWORD = "N0t-A-Real-Passw0rd-7f3a"
_USERNAME = "probe-reader"

_REAL_FAILURE_PROBE = """
import os, sys
sys.path.insert(0, {repo!r})
os.environ["MCP_PUSH_NOTIFICATIONS_ENABLED"] = "false"
try:
    import mcp_server.app  # noqa: F401 — הגדרת הלוג של השירות, כמו ב-uvicorn
except Exception:
    pass

from bson import ObjectId
from pymongo import MongoClient
from database.repository import Repository
from mcp_server.backend import ProductionBackend

client = MongoClient("mongodb://{username}:{password}@127.0.0.1:1/?serverSelectionTimeoutMS=300&connectTimeoutMS=300")


class _Manager:
    collection = client["probe"]["code_snippets"]

    def get_latest_version_fresh(self, user_id, file_name):
        return None

    def save_code_snippet_returning_id(self, snippet):
        snippet.version = 1
        return ObjectId()

    def find_version_by_id(self, doc_id, user_id):
        return Repository(self).find_version_by_id(doc_id, user_id)


res = ProductionBackend(db_manager=_Manager()).save_file(
    5, file_name="k13.md", code="x\\n", programming_language="markdown", tool="codekeeper_save_file")
assert res["content_changed"] is None, res
print("PROBE-DONE", flush=True)
"""


def _run(tmp_path, probe: str = _PROBE) -> str:
    script = textwrap.dedent(probe).format(repo=REPO, secret=SECRET_WORD, file_name=FILE_NAME,
                                           username=_USERNAME, password=_PASSWORD)
    proc = subprocess.run(
        [sys.executable, "-B", "-c", script],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(tmp_path),
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert "PROBE-DONE" in proc.stdout, f"the probe did not finish\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    return proc.stdout + proc.stderr


def test_a_changed_write_logs_one_warning_with_numbers_and_no_content(tmp_path):
    """שורה אחת, ברמת ``WARNING``, עם הכלי, ה-``_id``, הגרסה, הבתים והמיקום.

    המספרים מחושבים כאן מהמחרוזות ביד: ה-RLM הוא 3 בתים, והוא יושב בשורה 2.
    """
    output = _run(tmp_path)
    lines = [line for line in output.splitlines() if "codekeeper_edit_file" in line]
    assert len(lines) == 1, output
    line = lines[0]

    sent = "שורה ראשונה\n" + SECRET_WORD + "‏" + " המשך\n"
    before = sent[:sent.index("‏")]
    total = len(sent.encode("utf-8"))
    assert "WARNING" in line and "stored content differs" in line, line
    for field in (
        "_id=65f0c0ffee00000000000101",
        "version=7",
        f"line={before.count(chr(10)) + 1}",
        f"offset_bytes={len(before.encode('utf-8'))}",
        "intended_bytes=3",
        "stored_bytes=0",
        f"intended_total_bytes={total}",
        f"stored_total_bytes={total - 3}",
    ):
        assert field in line, (field, line)


def test_a_failed_read_back_logs_a_warning_and_an_equal_write_logs_nothing(tmp_path):
    """הקריאה החוזרת שנכשלה נרשמת, עם ה-traceback — ושמירה תקינה אינה נרשמת בכלל.

    החלק השני הוא הבקרה: בלעדיו טסט שמוצא שורת ``WARNING`` היה עובר גם על קוד
    שרושם שורה על כל כתיבה.
    """
    output = _run(tmp_path)
    failed = [line for line in output.splitlines() if "codekeeper_append_file" in line]
    assert len(failed) == 1, output
    assert "WARNING" in failed[0] and "could not read back" in failed[0], failed[0]
    assert "_id=65f0c0ffee00000000000102" in failed[0] and "version=7" in failed[0]
    assert "AutoReconnect" in output, "ה-traceback של הכשל חסר"
    assert "codekeeper_save_file" not in output, output


def test_nothing_from_the_content_or_the_file_name_reaches_the_output(tmp_path):
    """לא code points, לא תוכן ולא שם הקובץ — בשום שורה, גם לא ב-traceback."""
    output = _run(tmp_path)
    assert "U+" not in output, output
    assert SECRET_WORD not in output, output
    assert "שורה ראשונה" not in output, output
    assert FILE_NAME not in output, output


def test_a_real_read_back_failure_logs_its_traceback_without_the_connection_secrets(tmp_path):
    """‏``exc_info`` על כשל הקריאה החוזרת בטוח — כי pymongo אינו מכניס לחריגה את הסיסמה
    ואת שם המשתמש מכתובת החיבור. נבדק מול pymongo 4.15.3, והטסט מקבע את זה: שדרוג
    שיתחיל להדפיס את הכתובת בחריגה יפיל אותו, ולא ידליף סוד ליומן (``CRITICAL-PATTERNS``
    K13).

    הטענה הראשונה היא הבקרה — ה-traceback **כן** הגיע לפלט, כלומר נבדק הערוץ שבו הסוד
    היה דולף, ולא פלט שבמקרה ריק.
    """
    output = _run(tmp_path, _REAL_FAILURE_PROBE)
    assert "ServerSelectionTimeoutError" in output and "could not read back" in output, output
    assert _PASSWORD not in output
    assert _USERNAME not in output
