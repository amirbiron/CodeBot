from __future__ import annotations

from dataclasses import dataclass

import pytest

# repo_sync_service מייבא pymongo.ReturnDocument בטופ-לבל.
# בחלק מסביבות הפיתוח (כולל סביבת הסוכן כאן) pymongo לא מותקן,
# אבל לטסטים שלנו מספיק stub מינימלי כדי לאפשר import.
try:
    import pymongo as _pymongo  # noqa: F401
except Exception:  # pragma: no cover
    import sys
    import types

    _pymongo_stub = types.ModuleType("pymongo")

    class ReturnDocument:  # noqa: D401 - stub
        AFTER = object()

    _pymongo_stub.ReturnDocument = ReturnDocument
    sys.modules["pymongo"] = _pymongo_stub


class _FakeRepoMetadataCollection:
    def __init__(self) -> None:
        self.last_update = None

    def update_one(self, filt, update, upsert=False):  # noqa: D401 - test stub
        self.last_update = {"filter": filt, "update": update, "upsert": upsert}
        return None

    def find_one(self, filt, projection=None):  # noqa: D401 - test stub
        return {"repo_name": filt.get("repo_name"), "last_synced_sha": "o" * 40}


class _FakeRepoFilesCollection:
    """ספירה בשליטת הבדיקה, כולל אפשרות להיכשל.

    הכשל מדגמן **תקלת מסד** (``PyMongoError``) ולא ``RuntimeError`` שרירותי:
    ההלפר תופס חריגות מונגו בלבד, ובצדק — חריגה אחרת פירושה באג בקוד או
    באדפטר, וסטאב שמדגמן אותה היה מכסה על כך שהיא נבלעת.
    """

    def __init__(self, count=0) -> None:
        self.count = count
        self.count_fails = False
        self.calls = []
        #: הנתיבים שכבר באינדקס — משמש ליישוב מול הריפו בייבוא חוזר
        self.paths = []
        self.removed = []
        self.distinct_fails = False

    def distinct(self, field, filt=None):  # noqa: D401 - test stub
        if self.distinct_fails:
            from pymongo.errors import OperationFailure

            raise OperationFailure("distinct failed")
        return list(self.paths)

    def count_documents(self, filt):  # noqa: D401 - test stub
        self.calls.append(filt)
        if self.count_fails:
            from pymongo.errors import OperationFailure

            raise OperationFailure("count failed")
        return self.count


class _FakeDb:
    def __init__(self) -> None:
        self.repo_metadata = _FakeRepoMetadataCollection()
        self.repo_files = _FakeRepoFilesCollection()


@dataclass
class _GitCommandResult:
    success: bool
    stdout: str
    stderr: str = ""
    return_code: int = 0


class _StubGitService:
    def __init__(self, *, list_files=None, current_sha=None, head_branch="main") -> None:
        self._list_files = list_files
        self._current_sha = current_sha
        self._head_branch = head_branch

    def init_mirror(self, repo_url: str, repo_name: str):
        return {"success": True, "path": f"/tmp/{repo_name}.git", "already_existed": True}

    def _get_repo_path(self, repo_name: str):
        return f"/tmp/{repo_name}.git"

    def _run_git_command(self, cmd, cwd=None, timeout=60):
        # HEAD branch detection
        if cmd[:3] == ["git", "symbolic-ref", "--short"]:
            return _GitCommandResult(success=True, stdout=self._head_branch)
        # SHA resolution fallback
        if cmd[:2] == ["git", "rev-parse"]:
            # return a stable SHA for tests
            return _GitCommandResult(success=True, stdout="a" * 40)
        return _GitCommandResult(success=False, stdout="", stderr="unsupported", return_code=1)

    def list_all_files(self, repo_name: str, ref: str = "HEAD"):
        return self._list_files

    def get_current_sha(self, repo_name: str, branch: str = "main"):
        return self._current_sha

    def get_file_content(self, repo_name: str, file_path: str, ref: str = "HEAD"):
        return "print('ok')\n"


_LAST_REMOVED = []


class _StubIndexer:
    def __init__(self, db=None) -> None:
        self.db = db

    def should_index(self, file_path: str) -> bool:
        return True

    def index_file(self, repo_name: str, file_path: str, content: str, commit_sha: str = "HEAD") -> bool:
        return True

    def remove_files(self, repo_name, file_paths):  # noqa: D401 - test stub
        _LAST_REMOVED.append((repo_name, list(file_paths)))
        return len(file_paths)



def test_initial_import_fails_fast_when_list_all_files_returns_none(monkeypatch):
    from services import repo_sync_service as rss

    db = _FakeDb()
    monkeypatch.setattr(rss, "get_mirror_service", lambda: _StubGitService(list_files=None, current_sha="b" * 40))
    monkeypatch.setattr(rss, "CodeIndexer", _StubIndexer)

    out = rss.initial_import("https://example.com/repo.git", "Repo", db)
    assert out.get("error") == "Failed to list repository files"


def test_initial_import_never_stores_symbolic_head_sha(monkeypatch):
    from services import repo_sync_service as rss

    db = _FakeDb()
    # get_current_sha returns None => must fall back to rev-parse and store real SHA
    monkeypatch.setattr(rss, "get_mirror_service", lambda: _StubGitService(list_files=["a.py"], current_sha=None))
    monkeypatch.setattr(rss, "CodeIndexer", _StubIndexer)

    out = rss.initial_import("https://example.com/repo.git", "Repo", db)
    assert out["status"] == "completed"
    assert out["sha"] == ("a" * 7)
    saved = (db.repo_metadata.last_update or {}).get("update", {}).get("$set", {})
    assert saved.get("last_synced_sha") == ("a" * 40)


def test_initial_import_counts_read_failures_as_errors(monkeypatch):
    from services import repo_sync_service as rss

    class _Git(_StubGitService):
        def get_file_content(self, repo_name: str, file_path: str, ref: str = "HEAD"):
            return None

    db = _FakeDb()
    monkeypatch.setattr(rss, "get_mirror_service", lambda: _Git(list_files=["a.py"], current_sha="c" * 40))
    monkeypatch.setattr(rss, "CodeIndexer", _StubIndexer)

    out = rss.initial_import("https://example.com/repo.git", "Repo", db)
    # **``total_files`` הוא מה שנכנס לאינדקס, לא מה שנבחר לאינדוקס.**
    # הקובץ היחיד נכשל בקריאה, ולכן הוא נספר ב-``errors`` ולא ב-
    # ``total_files``. קודם לכן השדה החזיק ``len(code_files)`` וספר גם
    # כשלונות — ואז הסנכרון הראשון, שסופר את האינדקס בפועל, היה מוריד
    # את המספר בלי ששום קובץ השתנה.
    assert out["total_files"] == 0
    assert out["code_files"] == 1, "הקובץ אכן נבחר לאינדוקס"
    assert out["indexed"] == 0
    assert out["errors"] == 1
    # **וגם הערך שנשמר במסד** — זה מה שדפדפן הריפו קורא ומציג, ולכן
    # אסור שיתפצל מהערך המוחזר. בלי האימות הזה, שינוי באחד מהם לבדו
    # היה עובר בשקט.
    saved = (db.repo_metadata.last_update or {}).get("update", {}).get("$set", {})
    assert saved.get("total_files") == 0
    assert out["errors"] == 1


# ---------- מונה הקבצים מתעדכן בכל סנכרון, לא רק בייבוא ----------

class _SyncGitService(_StubGitService):
    """מראה שיש בה שינוי אחד בין שני SHA-ים."""

    def mirror_exists(self, repo_name: str) -> bool:
        return True

    def fetch_updates(self, repo_name: str):
        return {"success": True}

    def get_changed_files(self, repo_name: str, old_sha: str, new_sha: str):
        return {"added": ["new.py"], "modified": [], "removed": [], "renamed": []}

    def get_file_content(self, repo_name: str, file_path: str, ref: str = "HEAD"):
        return "print('hi')"


def test_sync_refreshes_total_files():
    """**המספר בדפדפן הריפו היה קפוא מאז הייבוא הראשוני.**

    ``_run_sync_logic`` עדכן ``last_synced_sha``, ``last_sync_time`` ו-
    ``sync_status`` — אבל לא את ``total_files``, שנכתב רק ב-
    ``initial_import``. לכן "1529 files" לא זז אחרי אף מיזוג.

    נופל אם ``total_files`` יוסר מעדכון המטא-דאטה של הסנכרון.
    """
    from services import repo_sync_service as rss

    db = _FakeDb()
    db.repo_files.count = 1530          # אחרי המיזוג נוסף קובץ

    out = rss._run_sync_logic(_SyncGitService(), _StubIndexer(), db, "CodeBot", "n" * 40, "o" * 40)

    assert out["status"] == "synced"
    saved = (db.repo_metadata.last_update or {}).get("update", {}).get("$set", {})
    assert saved.get("total_files") == 1530


def test_sync_leaves_total_files_alone_when_the_count_fails():
    """ספירה שנכשלה אינה עדות שאין קבצים.

    כתיבת ``0`` הייתה מציגה "0 files" על ריפו מלא. עדיף להשאיר את המספר
    הקודם — ישן, אבל נכון פעם.

    נופל אם הכשל ייכתב כאפס במקום להישמט מהעדכון.
    """
    from services import repo_sync_service as rss

    db = _FakeDb()
    db.repo_files.count_fails = True

    out = rss._run_sync_logic(_SyncGitService(), _StubIndexer(), db, "CodeBot", "n" * 40, "o" * 40)

    assert out["status"] == "synced"
    saved = (db.repo_metadata.last_update or {}).get("update", {}).get("$set", {})
    assert "total_files" not in saved, "לא נכתב ערך שקרי"
    # **שהמסלול באמת נוסה.** בלי זה, טסט שבו הספירה כלל לא נקראה היה
    # עובר מאותה סיבה — היעדר השדה — ולא מגן על כלום.
    assert db.repo_files.calls, "count_documents נקרא"
    # ושאר המטא-דאטה כן התעדכן
    assert saved.get("last_synced_sha") == "n" * 40


def test_up_to_date_sync_still_refreshes_the_counter():
    """**סנכרון ללא שינויים מתקן מונה שנסחף.**

    אם הספירה נכשלה בסנכרון קודם, אותו סנכרון עדיין התקדם ל-SHA החדש
    וסומן כהושלם — והסנכרון הבא לאותו SHA יוצא במסלול ``up_to_date``,
    לפני הספירה. בלי ריענון כאן, המספר הישן היה נשאר לתמיד.

    נופל אם מסלול ``up_to_date`` חוזר לצאת בלי לספור.
    """
    from services import repo_sync_service as rss

    db = _FakeDb()
    db.repo_files.count = 1530

    out = rss._run_sync_logic(_SyncGitService(), _StubIndexer(), db, "CodeBot", "s" * 40, "s" * 40)

    assert out["status"] == "up_to_date"
    saved = (db.repo_metadata.last_update or {}).get("update", {}).get("$set", {})
    assert saved.get("total_files") == 1530
    # ורק המונה עודכן — לא סטטוס ולא SHA, כי שום דבר לא סונכרן
    assert "last_synced_sha" not in saved
    assert "sync_status" not in saved


def test_up_to_date_sync_does_not_write_when_the_count_fails():
    """ספירה שנכשלה במסלול הזה לא כותבת כלום."""
    from services import repo_sync_service as rss

    db = _FakeDb()
    db.repo_files.count_fails = True

    out = rss._run_sync_logic(_SyncGitService(), _StubIndexer(), db, "CodeBot", "s" * 40, "s" * 40)

    assert out["status"] == "up_to_date"
    assert db.repo_metadata.last_update is None, "לא בוצעה כתיבה"
    assert db.repo_files.calls, "אבל הספירה כן נוסתה"


# ---------- ייבוא חוזר: יישוב האינדקס מול הריפו ----------

def test_reimport_removes_paths_that_left_the_repo(monkeypatch):
    """**ייבוא חוזר מסיר נתיבים שכבר אינם בריפו.**

    ``index_file`` הוא upsert לפי ``(repo_name, path)``: ייבוא חוזר מעדכן
    ומוסיף, אבל לעולם לא מסיר. הרפאים שנשארו אינם רק מספר — הם מופיעים
    בעץ הקבצים ובחיפוש, ומאז שהמונה נספר מהאינדקס גם מנפחים אותו.

    נופל אם היישוב יוסר מ-``initial_import``.
    """
    from services import repo_sync_service as rss

    _LAST_REMOVED.clear()
    db = _FakeDb()
    # באינדקס יש קובץ שכבר לא קיים בריפו
    db.repo_files.paths = ["a.py", "gone.py"]
    monkeypatch.setattr(rss, "get_mirror_service", lambda: _StubGitService(list_files=["a.py"], current_sha="c" * 40))
    monkeypatch.setattr(rss, "CodeIndexer", _StubIndexer)

    out = rss.initial_import("https://example.com/repo.git", "Repo", db)

    assert out["status"] == "completed"
    assert _LAST_REMOVED == [("Repo", ["gone.py"])], "רק הנתיב שנעלם הוסר"


def test_reimport_does_not_reconcile_when_listing_is_empty(monkeypatch):
    """ליסטינג ריק אינו רשיון למחוק את כל האינדקס.

    ``all_files`` ריק פירושו ריפו ריק — או ליסטינג שנכשל בשקט. במקרה
    השני מחיקה גורפת הייתה מוחקת אינדקס תקין, ולכן היישוב מדלג.

    נופל אם השומר על ``all_files`` יוסר.
    """
    from services import repo_sync_service as rss

    _LAST_REMOVED.clear()
    db = _FakeDb()
    db.repo_files.paths = ["a.py", "b.py"]
    monkeypatch.setattr(rss, "get_mirror_service", lambda: _StubGitService(list_files=[], current_sha="c" * 40))
    monkeypatch.setattr(rss, "CodeIndexer", _StubIndexer)

    rss.initial_import("https://example.com/repo.git", "Repo", db)

    assert _LAST_REMOVED == [], "לא בוצעה שום מחיקה"


def test_reimport_skips_reconcile_when_paths_cannot_be_listed(monkeypatch):
    """כשל בקריאת הנתיבים הקיימים מדלג על היישוב, ולא מוחק על סמך ניחוש."""
    from services import repo_sync_service as rss

    _LAST_REMOVED.clear()
    db = _FakeDb()
    db.repo_files.paths = ["a.py", "gone.py"]
    db.repo_files.distinct_fails = True
    monkeypatch.setattr(rss, "get_mirror_service", lambda: _StubGitService(list_files=["a.py"], current_sha="c" * 40))
    monkeypatch.setattr(rss, "CodeIndexer", _StubIndexer)

    out = rss.initial_import("https://example.com/repo.git", "Repo", db)

    assert out["status"] == "completed", "הייבוא לא נכשל בגלל היישוב"
    assert _LAST_REMOVED == []


def test_up_to_date_refresh_reports_when_no_metadata_matched(caplog):
    """``$set`` שלא תפס מסמך אינו זורק — ולכן חייבים לבדוק את התוצאה.

    זה דפוס K11: הכתיבה "מצליחה" בשקט בזמן שהסנכרון מדווח ``up_to_date``.

    נופל אם בדיקת ``matched_count`` תוסר.
    """
    import logging

    from services import repo_sync_service as rss

    class _NoMatch(_FakeRepoMetadataCollection):
        def update_one(self, filt, update, upsert=False):
            super().update_one(filt, update, upsert)
            return type("R", (), {"matched_count": 0, "modified_count": 0})()

    db = _FakeDb()
    db.repo_metadata = _NoMatch()
    db.repo_files.count = 7

    with caplog.at_level(logging.WARNING):
        out = rss._run_sync_logic(_SyncGitService(), _StubIndexer(), db, "CodeBot", "s" * 40, "s" * 40)

    assert out["status"] == "up_to_date"
    assert any("matched no repo_metadata" in r.getMessage() for r in caplog.records), \
        "הכשל השקט דווח"
