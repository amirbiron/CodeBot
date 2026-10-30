"""המילוי של ה-mirrors החסרים בדיסק של הוובאפ בעלייה (``services/repo_sync_service.py``), וה-worker שמחכה לו.

**למה הקובץ הזה קיים.** שירות וובאפ חדש (המעבר לפרנקפורט) עולה עם דיסק ריק. עד המילוי, דפדפן הקוד לא מצא אף ריפו,
וכל ג'וב סנכרון נכשל על ``mirror_missing`` עד ייבוא ידני של כל ריפו — והייבוא דורס את ``last_synced_sha`` ומאנדקס הכול.
המילוי משכפל רק מתוך הרשומות הקיימות, ולא כותב למסד: כל דמות של אוסף כאן נכשלת על כל פעולת כתיבה.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import services.repo_sync_service as rss

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# דמויות: אוסף שאי אפשר לכתוב אליו, ודיסק של mirrors בזיכרון
# ---------------------------------------------------------------------------


class _ReadOnlyRepoMetadata:
    """``repo_metadata`` לקריאה בלבד. ``find_one`` עונה לפי ``answers`` (רשימה לכל ריפו), כדי לדמות הסרה באמצע."""

    def __init__(self, records, answers=None):
        self.records = [dict(r) for r in records]
        self.answers = {name: list(seq) for name, seq in (answers or {}).items()}
        self.asked = []
        self.fail_find = False

    def with_options(self, codec_options=None, read_preference=None, write_concern=None, read_concern=None):
        # השמות של pymongo (4.15.3, ``Collection.with_options``): שם שגוי נופל כאן כמו שהיה נופל שם.
        self.asked.append(read_preference)
        return self

    def find(self, query, projection=None):
        if self.fail_find:
            raise RuntimeError("mongo is down")
        return [dict(r) for r in self.records]

    def find_one(self, query, projection=None):
        name = query["repo_name"]
        if name in self.answers:
            return self.answers[name].pop(0)
        return next((dict(r) for r in self.records if r["repo_name"] == name), None)

    def __getattr__(self, name):
        raise AssertionError(f"the mirror fill must not write to the database (called {name})")


class _Db:
    def __init__(self, coll):
        self.coll = coll

    def __getitem__(self, name):
        assert name == "repo_metadata", name
        return self.coll

    def __getattr__(self, name):
        raise AssertionError(f"the mirror fill touched db.{name}")


class _Disk:
    def __init__(self, existing=(), clone_fails=(), sticky=False, broken=()):
        self.dirs = set(existing)
        self.clone_fails = set(clone_fails)
        self.sticky = sticky
        self.broken = set(broken)
        self.clones = []
        self.deletes = []
        self.on_clone = None

    def mirror_exists(self, name):
        if name in self.broken:
            raise OSError("disk error")
        return name in self.dirs

    def init_mirror(self, url, name):
        self.clones.append((url, name))
        if name in self.clone_fails:
            return {"success": False, "message": "fatal: 'https://x-access-token:ghp_" + "S" * 36 + "@github.com/o/r'"}
        self.dirs.add(name)
        if self.on_clone:
            self.on_clone(name)
        return {"success": True}

    def delete_mirror(self, name):
        self.deletes.append(name)
        if not self.sticky:
            self.dirs.discard(name)
        return {"success": True, "existed": True}


def _rec(name, url=None, sha="a" * 40):
    return {"repo_name": name, "repo_url": url or f"https://github.com/o/{name}", "default_branch": "main",
            "last_synced_sha": sha}


# ---------------------------------------------------------------------------
# fill_missing_mirrors
# ---------------------------------------------------------------------------


def test_only_a_record_without_a_mirror_is_cloned_and_nothing_is_written():
    coll = _ReadOnlyRepoMetadata([_rec("alpha"), _rec("beta")])
    disk = _Disk(existing={"alpha"})

    stats = rss.fill_missing_mirrors(_Db(coll), disk)

    assert disk.clones == [("https://github.com/o/beta", "beta")]
    assert (stats["cloned"], stats["existed"], stats["errors"]) == (1, 1, 0)


def test_the_records_are_read_from_the_primary():
    from pymongo import ReadPreference

    coll = _ReadOnlyRepoMetadata([_rec("beta")])
    rss.fill_missing_mirrors(_Db(coll), _Disk())

    # הרשימה, הקריאה שלפני השכפול והקריאה שאחריו
    assert coll.asked == [ReadPreference.PRIMARY] * 3


def test_a_repo_removed_before_its_clone_is_not_cloned():
    coll = _ReadOnlyRepoMetadata([_rec("beta")], answers={"beta": [None]})
    disk = _Disk()

    stats = rss.fill_missing_mirrors(_Db(coll), disk)

    assert disk.clones == [] and stats["removed"] == 1


def test_the_clone_uses_the_url_the_record_has_now():
    coll = _ReadOnlyRepoMetadata(
        [_rec("beta", url="https://github.com/old/beta")],
        answers={"beta": [_rec("beta", url="https://github.com/new/beta"), _rec("beta")]},
    )
    disk = _Disk()

    rss.fill_missing_mirrors(_Db(coll), disk)

    assert disk.clones == [("https://github.com/new/beta", "beta")]


def test_a_repo_removed_during_its_clone_is_deleted_from_the_disk(caplog):
    """``unmirror_repo`` מוחק קודם את ה-mirror (שעוד לא קיים) ואז את הרשומה; השכפול מסתיים אחריו — ונשאר יתום."""
    coll = _ReadOnlyRepoMetadata([_rec("beta")], answers={"beta": [_rec("beta"), None]})
    disk = _Disk()

    with caplog.at_level(logging.INFO, logger="services.repo_sync_service"):
        stats = rss.fill_missing_mirrors(_Db(coll), disk)

    assert disk.deletes == ["beta"] and "beta" not in disk.dirs
    assert (stats["discarded"], stats["cloned"], stats["errors"]) == (1, 0, 0)
    assert "removed while it was being cloned" in caplog.text


def test_a_delete_that_leaves_the_clone_on_disk_is_an_error_not_a_discard(caplog):
    coll = _ReadOnlyRepoMetadata([_rec("beta")], answers={"beta": [_rec("beta"), None]})
    disk = _Disk(sticky=True)

    with caplog.at_level(logging.WARNING, logger="services.repo_sync_service"):
        stats = rss.fill_missing_mirrors(_Db(coll), disk)

    assert (stats["discarded"], stats["errors"]) == (0, 1)
    assert "still on disk" in caplog.text


def test_a_mirror_someone_else_made_meanwhile_is_counted_as_existing_and_kept():
    """בלי הנעילה, שני תהליכים שממלאים יחד: ה-``init_mirror`` של השני מוצא את התיקייה שהראשון יוצר, ועונה
    ``already_existed`` (נמדד עם שני תהליכים ו-``git clone`` אמיתי). זה לא שכפול של התהליך הזה — וגם לא מועמד
    למחיקה כשהרשומה נעלמת, כי לא הוא יצר אותו."""
    coll = _ReadOnlyRepoMetadata([_rec("beta")], answers={"beta": [_rec("beta"), None]})
    disk = _Disk()
    disk.init_mirror = lambda url, name: (disk.dirs.add(name), {"success": True, "already_existed": True})[1]

    stats = rss.fill_missing_mirrors(_Db(coll), disk)

    assert (stats["existed"], stats["cloned"], stats["discarded"]) == (1, 0, 0)
    assert disk.deletes == [] and "beta" in disk.dirs


def test_a_failed_clone_is_counted_and_its_log_is_redacted(caplog):
    coll = _ReadOnlyRepoMetadata([_rec("beta")])

    with caplog.at_level(logging.WARNING, logger="services.repo_sync_service"):
        stats = rss.fill_missing_mirrors(_Db(coll), _Disk(clone_fails={"beta"}))

    assert stats["errors"] == 1
    assert "clone failed for beta" in caplog.text
    assert "ghp_" not in caplog.text and "x-access-token" not in caplog.text


def test_a_record_without_a_url_is_not_cloned_and_is_logged(caplog):
    coll = _ReadOnlyRepoMetadata([_rec("beta", url="")], answers={"beta": [{"repo_name": "beta", "repo_url": ""}]})
    disk = _Disk()

    with caplog.at_level(logging.WARNING, logger="services.repo_sync_service"):
        stats = rss.fill_missing_mirrors(_Db(coll), disk)

    assert disk.clones == [] and stats["no_url"] == 1
    assert "has no repo_url" in caplog.text


def test_one_failing_repo_does_not_stop_the_others(caplog):
    coll = _ReadOnlyRepoMetadata([_rec("alpha"), _rec("beta")])
    disk = _Disk(broken={"alpha"})

    with caplog.at_level(logging.WARNING, logger="services.repo_sync_service"):
        stats = rss.fill_missing_mirrors(_Db(coll), disk)

    assert (stats["errors"], stats["cloned"]) == (1, 1)
    assert disk.clones == [("https://github.com/o/beta", "beta")]
    assert "repo mirror fill: alpha failed" in caplog.text


def test_a_failed_read_of_the_records_raises_to_the_caller():
    coll = _ReadOnlyRepoMetadata([_rec("beta")])
    coll.fail_find = True

    with pytest.raises(RuntimeError):
        rss.fill_missing_mirrors(_Db(coll), _Disk())


# ---------------------------------------------------------------------------
# מול git אמיתי: דיסק ריק מתמלא מהרשומה, בלי לגעת בה
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


def test_an_empty_disk_gets_a_real_mirror_of_every_record(tmp_path, monkeypatch):
    """``git clone --mirror`` אמיתי לתוך דיסק ריק. ``_validate_repo_url`` מקבל רק כתובות של GitHub, ולכן הוא היחיד
    שמוחלף — כדי לשכפל מריפו מקומי בלי רשת. כל השאר הוא ``GitMirrorService`` כמו שהוא."""
    from services.git_mirror_service import GitMirrorService

    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q")
    (work / "a.py").write_text("a = 1\n", encoding="utf-8")
    _git(work, "add", "a.py")
    _git(work, "commit", "-q", "-m", "a")
    head = _git(work, "rev-parse", "HEAD")

    svc = GitMirrorService(base_path=str(tmp_path / "mirrors"))
    monkeypatch.setattr(svc, "_validate_repo_url", lambda url: True)
    record = _rec("demo", url=str(work), sha=head)
    coll = _ReadOnlyRepoMetadata([record])

    stats = rss.fill_missing_mirrors(_Db(coll), svc)

    assert stats["cloned"] == 1 and stats["errors"] == 0
    assert svc.mirror_exists("demo")
    assert svc.get_current_sha("demo", "main") == head
    assert coll.records == [record]

    # מעבר שני: הכול קיים, ואין שכפול נוסף
    again = rss.fill_missing_mirrors(_Db(coll), svc)
    assert (again["cloned"], again["existed"]) == (0, 1)


# ---------------------------------------------------------------------------
# ה-worker מחכה למילוי
# ---------------------------------------------------------------------------


class _Stop(BaseException):
    """עוצר את הלולאה של ``_sync_worker`` (שתופסת ``Exception``) ברגע שהוא מנסה לתפוס ג'וב."""


@pytest.fixture
def worker(monkeypatch):
    import database.db_manager as dbm

    claims = []

    def _claim(db):
        claims.append(time.monotonic())
        raise _Stop()

    monkeypatch.setattr(dbm, "get_db", lambda: object())
    monkeypatch.setattr(rss, "_claim_next_job", _claim)
    return claims


def test_the_worker_claims_nothing_before_the_fill_is_done(worker, monkeypatch):
    done = threading.Event()
    monkeypatch.setattr(rss, "_mirror_fill_done", done)
    released = []

    def _finish_fill():
        time.sleep(0.3)
        released.append(time.monotonic())
        done.set()

    threading.Thread(target=_finish_fill, daemon=True).start()
    with pytest.raises(_Stop):
        rss._sync_worker()

    assert len(worker) == 1 and worker[0] >= released[0]


def test_after_the_deadline_the_worker_starts_and_says_so(worker, monkeypatch, caplog):
    monkeypatch.setattr(rss, "_mirror_fill_done", threading.Event())
    monkeypatch.setattr(rss, "MIRROR_FILL_WAIT_SECONDS", 0.2)

    with caplog.at_level(logging.WARNING, logger="services.repo_sync_service"), pytest.raises(_Stop):
        rss._sync_worker()

    assert len(worker) == 1
    assert "still running after" in caplog.text and rss.FAIL_MIRROR_MISSING in caplog.text


def test_without_a_fill_the_worker_does_not_wait(worker, monkeypatch):
    monkeypatch.setattr(rss, "_mirror_fill_done", None)
    monkeypatch.setattr(rss, "MIRROR_FILL_WAIT_SECONDS", 60)

    started = time.monotonic()
    with pytest.raises(_Stop):
        rss._sync_worker()

    assert worker[0] - started < 5


# ---------------------------------------------------------------------------
# start_mirror_fill ו-_run_mirror_fill
# ---------------------------------------------------------------------------


@pytest.fixture
def fresh_fill(monkeypatch, tmp_path):
    monkeypatch.setattr(rss, "_mirror_fill_done", None)
    monkeypatch.setattr(rss, "_MIRROR_FILL_STARTUP_DELAY_SECONDS", 0)
    monkeypatch.setattr(rss, "_MIRROR_FILL_LOCK_PATH", str(tmp_path / "fill.lock"))
    monkeypatch.delenv("WEBAPP_REPO_AUTOFILL", raising=False)


@pytest.mark.parametrize("value", ["0", "false", "OFF", " no "])
def test_the_kill_switch_starts_nothing_and_the_worker_does_not_wait(fresh_fill, monkeypatch, value):
    monkeypatch.setenv("WEBAPP_REPO_AUTOFILL", value)

    assert rss.start_mirror_fill() is False
    assert rss._mirror_fill_done is None


def test_the_event_is_published_before_the_thread_runs_and_set_at_its_end(fresh_fill, monkeypatch):
    seen = []
    monkeypatch.setattr(rss, "_run_mirror_fill", lambda done: (seen.append(rss._mirror_fill_done is done), done.set()))

    assert rss.start_mirror_fill() is True
    assert rss._mirror_fill_done.wait(5)
    assert seen == [True]
    # פעם אחת לתהליך
    assert rss.start_mirror_fill() is True and seen == [True]


def test_a_thread_that_cannot_start_releases_waiters_and_can_be_retried(fresh_fill, monkeypatch):
    real_start = threading.Thread.start

    def _start(self):
        if self.name == rss.MIRROR_FILL_THREAD_NAME:
            raise RuntimeError("can't start new thread")
        return real_start(self)

    monkeypatch.setattr(threading.Thread, "start", _start)
    with pytest.raises(RuntimeError):
        rss.start_mirror_fill()
    assert rss._mirror_fill_done is None

    monkeypatch.setattr(threading.Thread, "start", real_start)
    monkeypatch.setattr(rss, "_run_mirror_fill", lambda done: done.set())
    assert rss.start_mirror_fill() is True


def test_a_fill_that_fails_still_releases_the_worker_and_logs(fresh_fill, monkeypatch, caplog):
    import database.db_manager as dbm

    def _boom(db, mirror):
        raise RuntimeError("mongo is down")

    monkeypatch.setattr(dbm, "get_db", lambda: object())
    monkeypatch.setattr(rss, "get_mirror_service", lambda: object())
    monkeypatch.setattr(rss, "fill_missing_mirrors", _boom)
    done = threading.Event()

    with caplog.at_level(logging.ERROR, logger="services.repo_sync_service"):
        rss._run_mirror_fill(done)

    assert done.is_set()
    assert "repo mirror fill failed" in caplog.text


def test_a_fill_with_errors_ends_with_a_warning(fresh_fill, monkeypatch, caplog):
    import database.db_manager as dbm

    monkeypatch.setattr(dbm, "get_db", lambda: object())
    monkeypatch.setattr(rss, "get_mirror_service", lambda: object())
    monkeypatch.setattr(rss, "fill_missing_mirrors", lambda db, mirror: {"cloned": 1, "errors": 1})
    done = threading.Event()

    with caplog.at_level(logging.INFO, logger="services.repo_sync_service"):
        rss._run_mirror_fill(done)

    finished = [r for r in caplog.records if "repo mirror fill finished" in r.getMessage()]
    assert done.is_set() and len(finished) == 1 and finished[0].levelno == logging.WARNING


# ---------------------------------------------------------------------------
# הנעילה בין תהליכים
# ---------------------------------------------------------------------------


def test_a_process_waits_for_the_one_that_fills_and_gives_up_at_its_deadline(fresh_fill, monkeypatch, caplog):
    """``flock`` נקשר לפתיחה של הקובץ, ולא לתהליך: שתי פתיחות באותו תהליך מתנגשות כמו שני תהליכים
    (``flock(2)``; נמדד ב-Python 3.11 וב-3.13)."""
    import fcntl

    monkeypatch.setattr(rss, "_MIRROR_FILL_LOCK_POLL_SECONDS", 0.05)
    holder = open(rss._MIRROR_FILL_LOCK_PATH, "a+")
    fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        started = time.monotonic()
        with caplog.at_level(logging.WARNING, logger="services.repo_sync_service"):
            proceed, fh = rss._acquire_mirror_fill_lock(started + 0.3)
        assert (proceed, fh) == (False, None)
        assert time.monotonic() - started >= 0.3
        assert "stops waiting" in caplog.text
    finally:
        holder.close()

    proceed, fh = rss._acquire_mirror_fill_lock(time.monotonic() + 0.3)
    try:
        assert proceed is True and fh is not None
    finally:
        fh.close()


def test_the_second_process_fills_after_the_first_releases(fresh_fill, monkeypatch):
    import fcntl

    monkeypatch.setattr(rss, "_MIRROR_FILL_LOCK_POLL_SECONDS", 0.05)
    holder = open(rss._MIRROR_FILL_LOCK_PATH, "a+")
    fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    threading.Timer(0.2, holder.close).start()

    proceed, fh = rss._acquire_mirror_fill_lock(time.monotonic() + 5)
    try:
        assert proceed is True and fh is not None
    finally:
        fh.close()


# ---------------------------------------------------------------------------
# רק בשרת הוובאפ
# ---------------------------------------------------------------------------

_GUNICORN = "/opt/render/project/.venv/bin/gunicorn"
_PROBE = (
    "import logging, sys, threading, time\n"
    "logging.basicConfig(level=logging.INFO, stream=sys.stderr)\n"
    "sys.argv[0] = {argv0!r}\n"
    "import webapp.app\n"
    "time.sleep(0.5)\n"
    "names = sorted(t.name for t in threading.enumerate())\n"
    "print('MIRROR_FILL_RUNNING=' + str({thread!r} in names))\n"
)


def _fill_running_after_import_as(argv0, tmp_path, **env):
    """טעינה בתת-תהליך נקי עם ``-B``, כמו ב-``tests/test_push_sender_runs_only_in_the_webapp.py``: השאלה היא מה
    הייבוא עצמו מרים, ובתהליך הטסטים ``webapp.app`` כבר מיובא. החוט ישן ``_MIRROR_FILL_STARTUP_DELAY_SECONDS`` לפני
    שהוא נוגע במסד או בדיסק, והתהליך יוצא לפני כן."""
    proc = subprocess.run(
        [sys.executable, "-B", "-c", _PROBE.format(argv0=argv0, thread=rss.MIRROR_FILL_THREAD_NAME)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=50,
        env={
            **os.environ,
            "REPO_MIRROR_PATH": str(tmp_path / "mirrors"),
            "DISABLE_BACKUP_SCHEDULER": "1",
            "PUSH_NOTIFICATIONS_ENABLED": "false",
            "GEMINI_API_KEY": "",
            **env,
        },
    )
    lines = [line for line in proc.stdout.splitlines() if line.startswith("MIRROR_FILL_RUNNING=")]
    assert proc.returncode == 0 and len(lines) == 1, (proc.stdout + proc.stderr)[-3000:]
    return lines[0].endswith("True"), proc.stderr


@pytest.mark.parametrize("argv0", ["/srv/app/main.py", "/usr/bin/pytest"], ids=["bot", "pytest"])
def test_importing_the_webapp_outside_the_server_starts_no_fill(tmp_path, argv0):
    running, _ = _fill_running_after_import_as(argv0, tmp_path)
    assert not running


def test_the_webapp_server_starts_the_fill(tmp_path):
    """ריצת הבקרה: בלעדיה, הבדיקה שלמעלה הייתה עוברת גם על חוט שלא קם אף פעם."""
    running, stderr = _fill_running_after_import_as(_GUNICORN, tmp_path)
    assert running
    assert "repo mirror fill started" in stderr


def test_the_kill_switch_holds_in_the_server(tmp_path):
    running, stderr = _fill_running_after_import_as(_GUNICORN, tmp_path, WEBAPP_REPO_AUTOFILL="0")
    assert not running
    assert "repo mirror fill disabled via WEBAPP_REPO_AUTOFILL" in stderr
