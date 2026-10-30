"""ג'וב סנכרון שלא בוצע מסומן ``failed`` עם סיבה, וסנכרון שמצליח משלים את מה שג'ובים שנכשלו פספסו.

עד אוקטובר 2026 ארבעה מצבי כשל ב-``_run_sync_logic`` (אין mirror, fetch נכשל, אין SHA קודם, אין רשימת שינויים)
חזרו כ-``{"error": ...}``, וה-worker סימן כל תוצאה שלא נזרקה בה חריגה כ-``completed``. ובנוסף, הבסיס של ההבדלים
היה ``before`` שב-webhook — ולכן השינויים של push שהסנכרון שלו נכשל לא נכנסו לאינדקס לעולם: ה-push הבא התחיל
מה-SHA שאחריו. הבדיקה המרכזית כאן רצה מול ריפו git אמיתי בתיקייה זמנית, ולא מול דמות של ``diff-tree``.
"""

from __future__ import annotations

import os
import subprocess
import types

import pytest

from services import repo_sync_service as rss

# ---------------------------------------------------------------------------
# דמויות
# ---------------------------------------------------------------------------


class _Metadata:
    """``repo_metadata`` עם רשומה אחת (או בלי), ו-``update_one`` שמכבד פילטר על ``last_synced_sha`` כמו מונגו."""

    def __init__(self, doc):
        self.doc = doc
        self.updates = []

    def find_one(self, filt, projection=None):
        if self.doc is None or self.doc.get("repo_name") != filt.get("repo_name"):
            return None
        return dict(self.doc)

    def update_one(self, filt, update, upsert=False):
        self.updates.append({"filter": filt, "update": update, "upsert": upsert})
        matched = int(
            self.doc is not None
            and all(self.doc.get(k) == v for k, v in filt.items())
        )
        if matched:
            self.doc.update(update.get("$set", {}))
        return types.SimpleNamespace(acknowledged=True, matched_count=matched, modified_count=matched)


class _Files:
    def __init__(self):
        self.count = 0

    def count_documents(self, filt):
        return self.count


class _Jobs:
    def __init__(self):
        self.updates = []

    def update_one(self, filt, update):
        self.updates.append((filt, update))
        return types.SimpleNamespace(acknowledged=True, matched_count=1)


class _Db:
    def __init__(self, metadata_doc):
        self.repo_metadata = _Metadata(metadata_doc)
        self.repo_files = _Files()
        self.sync_jobs = _Jobs()


class _Indexer:
    """האינדקס כמילון: נתיב ← התוכן שנכנס אליו אחרון."""

    def __init__(self):
        self.files = {}

    def should_index(self, path):
        return True

    def index_file(self, repo_name, path, content, sha):
        self.files[path] = content
        return True

    def remove_file(self, repo_name, path):
        self.files.pop(path, None)

    def remove_files(self, repo_name, paths):
        for path in paths:
            self.files.pop(path, None)
        return len(paths)


class _Git:
    """שירות mirror בשליטת הבדיקה, שזוכר מאיזה בסיס התבקשו ההבדלים."""

    def __init__(self, *, exists=True, fetch_ok=True, changes=None):
        self.exists = exists
        self.fetch_ok = fetch_ok
        self.changes = {"added": ["x.py"], "modified": [], "removed": [], "renamed": []} if changes is None else changes
        self.diff_calls = []

    def mirror_exists(self, name):
        return self.exists

    def fetch_updates(self, name):
        return {"success": self.fetch_ok, "message": "boom" if not self.fetch_ok else ""}

    def get_changed_files(self, name, old, new):
        self.diff_calls.append((old, new))
        return self.changes

    def get_file_content(self, name, path, ref):
        return f"{path}@{ref}"


def _meta(sha="a" * 40):
    doc = {"repo_name": "demo", "repo_url": "https://github.com/o/demo.git", "default_branch": "main"}
    if sha is not None:
        doc["last_synced_sha"] = sha
    return doc


def _run(db, git, *, new="c" * 40, before="b" * 40):
    return rss._run_sync_logic(git, _Indexer(), db, "demo", new, before)


# ---------------------------------------------------------------------------
# כל מצב כשל מוחזר ככשל, עם סיבה — ומסומן failed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "db_doc, git, reason",
    [
        (_meta(), _Git(exists=False), rss.FAIL_MIRROR_MISSING),
        (_meta(), _Git(fetch_ok=False), rss.FAIL_FETCH),
        (_meta(sha=None), _Git(), rss.FAIL_NO_PREVIOUS_SHA),
    ],
)
def test_each_failure_is_a_failed_result_with_its_reason(db_doc, git, reason):
    result = _run(_Db(db_doc), git)
    assert (result["status"], result["reason"]) == (rss.RESULT_FAILED, reason)
    assert rss._job_status_for(result) == (rss.JOB_FAILED, reason)


def test_missing_changes_are_a_failure():
    git = _Git()
    git.get_changed_files = lambda *a: None
    result = _run(_Db(_meta()), git)
    assert (result["status"], result["reason"]) == (rss.RESULT_FAILED, rss.FAIL_CHANGES_UNAVAILABLE)


def test_a_repo_without_a_record_is_skipped_and_not_failed():
    """push לריפו שהוסר (ה-webhook נשאר ב-GitHub) — אין מה לסנכרן, וזה לא כשל."""
    db = _Db(None)
    result = _run(db, _Git(exists=False))
    assert (result["status"], result["reason"]) == (rss.RESULT_SKIPPED, rss.SKIP_NOT_TRACKED)
    assert rss._job_status_for(result) == (rss.JOB_SKIPPED, None)
    assert db.repo_metadata.updates == [], "לא נוצרה רשומה לריפו שהוסר"


def test_a_failure_writes_nothing_to_the_metadata():
    db = _Db(_meta())
    _run(db, _Git(exists=False))
    assert db.repo_metadata.updates == []
    assert db.repo_metadata.doc["last_synced_sha"] == "a" * 40


@pytest.mark.parametrize(
    "result, expected",
    [
        ({"status": rss.RESULT_SYNCED}, (rss.JOB_COMPLETED, None)),
        ({"status": rss.RESULT_UP_TO_DATE}, (rss.JOB_COMPLETED, None)),
        ({"status": rss.RESULT_SKIPPED, "reason": rss.SKIP_NOT_TRACKED}, (rss.JOB_SKIPPED, None)),
        ({"status": rss.RESULT_FAILED, "reason": rss.FAIL_FETCH}, (rss.JOB_FAILED, rss.FAIL_FETCH)),
        # הצורה הישנה, בלי status — אם באג יחזיר אותה, היא לא תסומן שוב כהצלחה
        ({"error": "Mirror not found. Run initial import first."}, (rss.JOB_FAILED, "unrecognized_result")),
        (None, (rss.JOB_FAILED, "unrecognized_result")),
    ],
)
def test_job_status_mapping_is_fail_closed(result, expected):
    assert rss._job_status_for(result) == expected


def test_the_worker_writes_the_status_the_result_gives():
    db = _Db(_meta())
    result = _run(db, _Git(exists=False))
    status = rss._finish_job(db, {"_id": "job-1", "repo_name": "demo"}, result)

    assert status == rss.JOB_FAILED
    [(filt, update)] = db.sync_jobs.updates
    assert filt == {"_id": "job-1"}
    written = update["$set"]
    assert (written["status"], written["error"]) == (rss.JOB_FAILED, rss.FAIL_MIRROR_MISSING)
    assert written["result"] is result and written["completed_at"] is not None


# ---------------------------------------------------------------------------
# הבסיס של ההבדלים הוא מה שבאינדקס, והכתיבה מותנית בו
# ---------------------------------------------------------------------------


def test_the_diff_starts_from_the_indexed_sha_and_not_from_the_webhook():
    db = _Db(_meta(sha="a" * 40))
    git = _Git()
    result = _run(db, git, new="c" * 40, before="b" * 40)

    assert result["status"] == rss.RESULT_SYNCED
    assert git.diff_calls == [("a" * 40, "c" * 40)]
    [update] = db.repo_metadata.updates
    assert update["filter"] == {"repo_name": "demo", "last_synced_sha": "a" * 40}
    assert update["upsert"] is False, "upsert עם last_synced_sha בפילטר היה יוצר רשומה שנייה"
    assert db.repo_metadata.doc["last_synced_sha"] == "c" * 40


def test_up_to_date_is_judged_by_the_indexed_sha():
    db = _Db(_meta(sha="c" * 40))
    git = _Git()
    result = _run(db, git, new="c" * 40, before="b" * 40)
    assert result["status"] == rss.RESULT_UP_TO_DATE and git.diff_calls == []


def test_a_base_that_moved_during_the_sync_is_a_failure():
    """סנכרון אחר הזיז את ``last_synced_sha`` באמצע — הכתיבה לא נתפסת, והג'וב לא מסומן כהצלחה."""
    db = _Db(_meta(sha="a" * 40))
    git = _Git()

    def _moved(*args):
        db.repo_metadata.doc["last_synced_sha"] = "d" * 40  # מישהו אחר סנכרן בינתיים
        return {"added": ["x.py"], "modified": [], "removed": [], "renamed": []}

    git.get_changed_files = _moved
    result = _run(db, git)

    assert (result["status"], result["reason"]) == (rss.RESULT_FAILED, rss.FAIL_BASE_MOVED)
    assert db.repo_metadata.doc["last_synced_sha"] == "d" * 40, "הערך של הסנכרון האחר לא נדרס"


# ---------------------------------------------------------------------------
# מול git אמיתי: push שהסנכרון שלו נכשל — והסנכרון הבא משלים אותו
# ---------------------------------------------------------------------------


def _git(cwd, *args):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
        "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(cwd),
    }
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main", *args],
        cwd=cwd, env=env, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _commit(work, path, text):
    (work / path).write_text(text, encoding="utf-8")
    _git(work, "add", path)
    _git(work, "commit", "-q", "-m", path)
    return _git(work, "rev-parse", "HEAD")


def test_a_push_whose_sync_failed_is_indexed_by_the_next_sync(tmp_path, monkeypatch):
    """A ← B (ה-push שהסנכרון שלו נכשל כי אין mirror) ← C. אחרי הסנכרון של C, הקובץ של B באינדקס.

    עם הבסיס הישן (``before`` של ה-webhook) הסנכרון של C חישב B..C, ו-``b.py`` לא נכנס לעולם.
    """
    from services.git_mirror_service import GitMirrorService

    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q")
    sha_a = _commit(work, "a.py", "a = 1\n")
    sha_b = _commit(work, "b.py", "b = 2\n")
    sha_c = _commit(work, "c.py", "c = 3\n")

    mirrors = tmp_path / "mirrors"
    mirrors.mkdir()
    _git(mirrors, "clone", "-q", "--mirror", str(work), str(mirrors / "demo.git"))

    db = _Db(_meta(sha=sha_a))
    indexer = _Indexer()

    # ה-push של B מגיע לשירות שאין לו mirror (דיסק ריק)
    empty = GitMirrorService(base_path=str(tmp_path / "empty"))
    first = rss._run_sync_logic(empty, indexer, db, "demo", sha_b, sha_a)
    assert (first["status"], first["reason"]) == (rss.RESULT_FAILED, rss.FAIL_MIRROR_MISSING)
    assert indexer.files == {} and db.repo_metadata.doc["last_synced_sha"] == sha_a

    # ה-push של C מגיע לשירות שיש לו mirror. ה-fetch מוחלף רק כי אין כאן רשת — כל השאר git אמיתי.
    service = GitMirrorService(base_path=str(mirrors))
    monkeypatch.setattr(service, "fetch_updates", lambda name: {"success": True})
    second = rss._run_sync_logic(service, indexer, db, "demo", sha_c, sha_b)

    assert second["status"] == rss.RESULT_SYNCED
    assert set(indexer.files) == {"b.py", "c.py"}, indexer.files
    assert indexer.files["b.py"] == "b = 2\n"
    assert db.repo_metadata.doc["last_synced_sha"] == sha_c
