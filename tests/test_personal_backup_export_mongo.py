"""ייצוא הגיבוי האישי — מול **מונגו אמיתי**, ולא מול stub.

``tests/test_personal_backup.py`` בודק את הייצוא מעל ``MagicMock``: הזרימה, הסדר וערוץ הכשל. מה שהוא לא יכול לבדוק הוא מה שהשרת עושה: איזו גרסה ``$top`` בוחר בשני מסמכים עם אותו ``version``, אילו פקודות נשלחות בפועל, ומה קורה כשבאוסף יש יותר מסמכים מהתקרה הישנה. כאן הייצוא רץ מקצה לקצה — ``PersonalBackupService.export_user_data``, מתודות ההאצלה של ``DatabaseManager`` ו-``Repository`` אמיתי — על מסד אמיתי.

מתי הן רצות: כש-``NOTE_FONTS_TEST_MONGO_URI``, או ``MONGODB_URL`` כשהוא ריק, מצביע לשרת נגיש. כשאין שם שרת הן מדלגות; כשיש שרת והחיבור נכשל מסיבה אחרת הן נכשלות (``mongo_client``, כמו ב-``tests/test_recycle_bin_ttl_index_mongo.py``).

**בטיחות מחיקה:** כל בדיקה עובדת על מסד עם שם ייחודי משלה, וה-teardown מוחק רק מסד שמתחיל בתחילית שלמטה.
"""

from __future__ import annotations

import json
import os
import types
import uuid
import zipfile
from datetime import timezone

import pytest

pymongo = pytest.importorskip("pymongo")

from pymongo import ASCENDING, DESCENDING  # noqa: E402
from pymongo import monitoring  # noqa: E402
from pymongo.errors import ServerSelectionTimeoutError  # noqa: E402

from database.manager import DatabaseManager  # noqa: E402
from database.repository import Repository  # noqa: E402

#: תחילית מסדי הבדיקה. ה-teardown מוחק **רק** מסד שמתחיל בה.
_TEST_DB_PREFIX = "codebot_backup_export_it_"

_MONGO_URL = (
    os.environ.get("NOTE_FONTS_TEST_MONGO_URI") or os.environ.get("MONGODB_URL") or ""
).strip()

pytestmark = pytest.mark.skipif(
    not _MONGO_URL,
    reason="דורש NOTE_FONTS_TEST_MONGO_URI או MONGODB_URL",
)

USER_ID = 7070
OTHER_USER_ID = 7171


class _Commands(monitoring.CommandListener):
    """כל פקודה שהלקוח שולח לשרת — כדי לטעון על מה שנשלח בפועל, ולא על מה שהקוד מתכוון לשלוח."""

    def __init__(self):
        self.log = []

    def started(self, event):
        self.log.append((event.database_name, event.command_name, dict(event.command)))

    def succeeded(self, event):
        pass

    def failed(self, event):
        pass


@pytest.fixture(scope="module")
def commands():
    return _Commands()


@pytest.fixture(scope="module")
def mongo_client(commands):
    """לקוח מחובר, או דילוג — **רק** כשאין שרת בקצה השני (``ServerSelectionTimeoutError``). כל חריגה אחרת עולה; סיבת הדילוג אינה מצטטת את החריגה, כי הכתובת יכולה לשאת סיסמה (K13)."""
    client = pymongo.MongoClient(
        _MONGO_URL, serverSelectionTimeoutMS=2000, tz_aware=True, tzinfo=timezone.utc, event_listeners=[commands]
    )
    try:
        client.admin.command("ping")
    except ServerSelectionTimeoutError:
        client.close()
        pytest.skip("אין שרת מונגו נגיש בכתובת שהוגדרה")
    except Exception:
        client.close()
        raise
    try:
        yield client
    finally:
        client.close()


class _Manager:
    """``DatabaseManager`` מעל מסד אמיתי: מתודה של ``DatabaseManager`` רצה כמו שהיא (ההאצלה ל-``Repository`` היא חלק ממה שנבדק), ו-``Repository`` אמיתי מאחוריה."""

    def __init__(self, db):
        self.db = db
        self.collection = db.code_snippets
        self.large_files_collection = db.large_files
        self._repo = Repository(self)

    def _get_repo(self):
        return self._repo

    def __getattr__(self, name):
        method = getattr(DatabaseManager, name, None)
        if callable(method):
            return types.MethodType(method, self)
        return getattr(self._repo, name)


@pytest.fixture
def env(mongo_client, commands):
    from services.personal_backup_service import PersonalBackupService

    name = f"{_TEST_DB_PREFIX}{uuid.uuid4().hex[:12]}"
    db = mongo_client[name]
    # האינדקס שהמסד בפרודקשן מחזיק (``idx_snippets_latest_version`` ב-``DatabaseManager._create_indexes``): בלעדיו מונגו בוחר תוכנית אחרת, ושוויון בין גרסאות נשבר בסדר אחר מבפרודקשן
    db.code_snippets.create_index(
        [("user_id", ASCENDING), ("is_active", ASCENDING), ("file_name", ASCENDING), ("version", DESCENDING)],
        name="idx_snippets_latest_version",
    )

    def export():
        commands.log.clear()
        buffer = PersonalBackupService(_Manager(db)).export_user_data(USER_ID)
        return zipfile.ZipFile(buffer, "r")

    def sent_to(collection):
        """``(שם הפקודה, הפקודה)`` לכל פקודה שהייצוא האחרון שלח לאוסף הזה במסד של הבדיקה."""
        return [(cname, cmd) for dbname, cname, cmd in commands.log if dbname == name and cmd.get(cname) == collection]

    try:
        yield types.SimpleNamespace(db=db, export=export, sent_to=sent_to)
    finally:
        # סורג בטיחות: מוחקים רק מסד שנוצר כאן
        if name.startswith(_TEST_DB_PREFIX):
            mongo_client.drop_database(name)


def _snippet(file_name, version, code, *, user_id=USER_ID, is_active=True):
    return {"user_id": user_id, "file_name": file_name, "version": version, "code": code, "is_active": is_active, "programming_language": "python", "tags": []}


def test_the_backup_holds_the_version_the_file_list_shows(env):
    """שתי גרסאות פעילות עם אותו ``version`` קיימות בפרודקשן (ב-17.10.2026: קובץ אחד, חמש גרסאות). הייצוא הישן לקח ``$first`` אחרי מיון לפי ``version`` בלבד, ושם הסדר בין השתיים הוא סדר הכנסתן לאינדקס — הראשונה. רשימת הקבצים בוובאפ בוחרת את ``_id`` הגבוה — האחרונה. הגיבוי חייב לשמור את מה שהמשתמש רואה."""
    from webapp.app import _latest_version_per_file_stages

    env.db.code_snippets.insert_many([
        _snippet("tie.py", 1, "v1"),
        _snippet("tie.py", 2, "v2-first"),
        _snippet("tie.py", 2, "v2-second"),
        _snippet("plain.py", 1, "p1"),
        _snippet("plain.py", 3, "p3"),
        _snippet("plain.py", 2, "p2"),
        _snippet("gone.py", 1, "g1"),
        _snippet("gone.py", 2, "g2-in-the-recycle-bin", is_active=False),
        _snippet("tie.py", 9, "someone-else", user_id=OTHER_USER_ID),
    ])

    with env.export() as zf:
        exported = {name[len("files/"):]: zf.read(name).decode("utf-8") for name in zf.namelist() if name.startswith("files/")}

    listed_ids = {
        row["file_name"]: row["_id"]
        for row in env.db.code_snippets.aggregate(_latest_version_per_file_stages({"user_id": USER_ID, "is_active": True}, non_empty_only=False))
    }
    listed = {name: env.db.code_snippets.find_one({"_id": doc_id})["code"] for name, doc_id in listed_ids.items()}

    assert exported == listed
    assert exported == {"tie.py": "v2-second", "plain.py": "p3", "gone.py": "g1"}


def test_files_past_the_old_ten_thousand_cap_are_exported(env):
    """הצינור הישן נגמר ב-``$limit: 10000``: משתמש עם יותר קבצים קיבל גיבוי קטוע, ו-``files_count`` דיווח את המספר הקטוע כאילו זה הכול."""
    total = 10_001
    env.db.code_snippets.insert_many([_snippet(f"f{i:05d}.py", 1, f"#{i}") for i in range(total)])

    with env.export() as zf:
        files = [name for name in zf.namelist() if name.startswith("files/")]
        info = json.loads(zf.read("backup_info.json"))

    assert len(files) == total
    assert info["files_count"] == total


def test_two_active_large_files_with_one_name_become_one_entry(env):
    """``save_large_file`` מכבה את הקודם ואז מכניס חדש — בקוד, בלי אינדקס ייחודי — ולכן שתי שמירות מקבילות יכולות להשאיר שני מסמכים פעילים באותו שם. הייצוא הישן כתב את שניהם לאותו נתיב ב-ZIP, ואת התוכן לקח מ-``find_one`` בלי מיון."""
    env.db.large_files.insert_many([
        {"user_id": USER_ID, "file_name": "big.txt", "content": "older", "is_active": True, "file_size": 5, "lines_count": 1},
        {"user_id": USER_ID, "file_name": "big.txt", "content": "newer", "is_active": True, "file_size": 5, "lines_count": 1},
    ])

    with env.export() as zf:
        entries = [name for name in zf.namelist() if name.startswith("large_files/")]
        content = zf.read("large_files/big.txt").decode("utf-8")
        meta = json.loads(zf.read("metadata/files.json"))

    assert entries == ["large_files/big.txt"]
    assert content == "newer"
    assert [m["file_name"] for m in meta["large_files"]] == ["big.txt"]


def test_what_is_sent_has_no_sort_no_limit_and_no_query_per_file(env):
    """מה שנשלח לשרת בפועל. ``$sort`` על המסמכים המלאים חוסם בזיכרון (תקרה של 32MB באשכול Flex, בלי ``allowDiskUse``), ``$limit`` חותך בשקט, ושאילתה לכל קובץ גדול (``get_large_file``) היא N+1."""
    env.db.code_snippets.insert_many([_snippet(f"f{i}.py", 1, "x") for i in range(5)])
    env.db.large_files.insert_many([
        {"user_id": USER_ID, "file_name": f"big{i}.txt", "content": "y", "is_active": True, "file_size": 1, "lines_count": 1} for i in range(5)
    ])

    with env.export():
        pass

    snippet_commands = env.sent_to("code_snippets")
    pipelines = [cmd["pipeline"] for cname, cmd in snippet_commands if cname == "aggregate"]
    assert pipelines, "הייצוא לא שלח aggregate על code_snippets"
    stages = [next(iter(stage)) for pipeline in pipelines for stage in pipeline]
    assert "$sort" not in stages and "$limit" not in stages, stages

    # צינור אחד שבוחר, ו-find אחד למנה — לא פקודה לכל קובץ
    assert [cname for cname, _cmd in env.sent_to("large_files")] == ["aggregate", "find"]
    assert [cname for cname, _cmd in snippet_commands] == ["aggregate", "find"]
