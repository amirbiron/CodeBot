"""תפיסה של ג'וב סנכרון: ג'וב רץ אחד לכל ריפו, דופק, ושחרור של ג'וב שה-worker שלו מת
(``services/repo_sync_service.py``).

**למה הקובץ הזה קיים.** שני workers — כמה תהליכי gunicorn, או שני שירותים על אותו מסד בזמן המעבר לפרנקפורט — יכלו
לסנכרן את אותו ריפו יחד, ו-``base_moved`` רק גילה את זה בדיעבד. ו-worker שנהרג באמצע ג'וב השאיר אותו ``running``
לתמיד. עכשיו המסד אוכף ג'וב רץ אחד לכל ריפו (אינדקס ייחודי חלקי), וג'וב בלי דופק משתחרר.

**רוב הבדיקות כאן רצות מול מונגו אמיתי** (``wired_mongo`` ב-``tests/conftest.py``), כי מה שנבדק הוא התנהגות של
המסד: אינדקס חלקי, ``DuplicateKeyError`` בתפיסה, ומפרט אינדקס כפי ש-``list_indexes`` מחזיר אותו. דמה הייתה מחזירה
בדיוק את מה שהקוד מניח. בלי ``NOTE_FONTS_TEST_MONGO_URI`` הן מדלגות; ב-CI הן רצות. מקומית — ``MONGODB_URL`` ו-
``NOTE_FONTS_TEST_MONGO_URI`` לאותו שרת.
"""

from __future__ import annotations

import importlib
import logging
import threading
import time
import types
from datetime import datetime, timedelta, timezone

import pytest

import services.repo_sync_service as rss


def _now():
    return datetime.now(timezone.utc)


def _job(job_id, repo, status=rss.JOB_PENDING, created=0, **extra):
    return {
        "_id": job_id,
        "repo_name": repo,
        "new_sha": "b" * 40,
        "status": status,
        "created_at": datetime(2026, 10, 30, tzinfo=timezone.utc) + timedelta(seconds=created),
        **extra,
    }


@pytest.fixture
def jobs_db(wired_mongo):
    db = wired_mongo.get_db()
    assert db is not None
    return db


@pytest.fixture
def indexed_db(jobs_db):
    rss.ensure_sync_jobs_indexes(jobs_db)
    return jobs_db


# ---------------------------------------------------------------------------
# האינדקסים, כפי שהמסד מחזיר אותם
# ---------------------------------------------------------------------------


def test_the_worker_path_creates_the_three_indexes_with_their_full_spec(jobs_db):
    """דפוס 9: ההצהרה במסלול שהכותב עובר בו, והטסט מקבע את המפרט המלא — מפתח, TTL, ייחודי ופילטר חלקי."""
    results = rss.ensure_sync_jobs_indexes(jobs_db)

    assert results == {
        rss.SYNC_JOBS_CLAIM_INDEX: True, rss.SYNC_JOBS_TTL_INDEX: True, rss.SYNC_JOBS_ONE_RUNNING_INDEX: True,
    }
    by_name = {idx["name"]: idx for idx in jobs_db.sync_jobs.list_indexes()}
    assert list(by_name[rss.SYNC_JOBS_CLAIM_INDEX]["key"].items()) == [("status", 1), ("created_at", 1)]
    assert list(by_name[rss.SYNC_JOBS_TTL_INDEX]["key"].items()) == [("expire_at", 1)]
    assert by_name[rss.SYNC_JOBS_TTL_INDEX]["expireAfterSeconds"] == 0
    one = by_name[rss.SYNC_JOBS_ONE_RUNNING_INDEX]
    assert list(one["key"].items()) == [("repo_name", 1)]
    assert one["unique"] is True
    assert dict(one["partialFilterExpression"]) == {"status": rss.JOB_RUNNING}


def test_indexes_the_manual_script_already_made_count_as_in_place(jobs_db):
    """במסד שבו הורץ ``scripts/create_repo_indexes.py`` שני האינדקסים קיימים בשמות ברירת המחדל. אינדקס שני על אותו
    מפתח היה נדחה; ``safe_create_index`` מזהה את הקיים כזהה."""
    jobs_db.sync_jobs.create_index([("status", 1), ("created_at", 1)])
    jobs_db.sync_jobs.create_index("expire_at", expireAfterSeconds=0)

    results = rss.ensure_sync_jobs_indexes(jobs_db)

    assert all(results.values()), results
    names = sorted(idx["name"] for idx in jobs_db.sync_jobs.list_indexes())
    assert names == sorted(["_id_", "status_1_created_at_1", "expire_at_1", rss.SYNC_JOBS_ONE_RUNNING_INDEX])


def test_two_live_running_jobs_for_one_repo_block_the_unique_index_and_say_so(jobs_db, caplog):
    jobs_db.sync_jobs.insert_many([
        _job("a1", "A", rss.JOB_RUNNING, heartbeat_at=_now()),
        _job("a2", "A", rss.JOB_RUNNING, heartbeat_at=_now()),
    ])

    with caplog.at_level(logging.ERROR, logger="services.repo_sync_service"):
        results = rss.ensure_sync_jobs_indexes(jobs_db)

    assert results[rss.SYNC_JOBS_ONE_RUNNING_INDEX] is False
    assert results[rss.SYNC_JOBS_CLAIM_INDEX] and results[rss.SYNC_JOBS_TTL_INDEX]
    assert "more than one running job for ['A']" in caplog.text
    assert rss.SYNC_JOBS_ONE_RUNNING_INDEX not in {idx["name"] for idx in jobs_db.sync_jobs.list_indexes()}


def test_a_dead_duplicate_is_released_first_and_then_the_unique_index_is_created(jobs_db):
    old = _now() - timedelta(seconds=rss.SYNC_JOB_STALE_SECONDS + 60)
    jobs_db.sync_jobs.insert_many([
        _job("a1", "A", rss.JOB_RUNNING, heartbeat_at=old),
        _job("a2", "A", rss.JOB_RUNNING, heartbeat_at=_now()),
    ])

    results = rss.ensure_sync_jobs_indexes(jobs_db)

    assert results[rss.SYNC_JOBS_ONE_RUNNING_INDEX] is True
    assert jobs_db.sync_jobs.find_one({"_id": "a1"})["error"] == rss.FAIL_ABANDONED


# ---------------------------------------------------------------------------
# התפיסה
# ---------------------------------------------------------------------------


def test_a_repo_with_a_running_job_is_skipped_and_the_next_repo_is_taken(indexed_db):
    indexed_db.sync_jobs.insert_many(
        [_job("a1", "A", created=1), _job("a2", "A", created=2), _job("b1", "B", created=3)]
    )

    first = rss._claim_next_job(indexed_db)
    second = rss._claim_next_job(indexed_db)
    third = rss._claim_next_job(indexed_db)

    assert (first["_id"], second["_id"], third) == ("a1", "b1", None)
    assert indexed_db.sync_jobs.find_one({"_id": "a2"})["status"] == rss.JOB_PENDING
    # התפיסה כותבת דופק מיד, כדי שג'וב שנתפס ולא התחיל לא ייראה מת.
    assert first["heartbeat_at"] is not None


def test_after_the_running_job_ends_the_repo_next_job_is_taken_in_order(indexed_db):
    indexed_db.sync_jobs.insert_many([_job("a1", "A", created=1), _job("a2", "A", created=2)])
    rss._claim_next_job(indexed_db)
    indexed_db.sync_jobs.update_one({"_id": "a1"}, {"$set": {"status": rss.JOB_COMPLETED}})

    assert rss._claim_next_job(indexed_db)["_id"] == "a2"


def test_a_claim_that_races_another_worker_for_the_same_repo_is_refused_by_the_database(
    indexed_db, monkeypatch, caplog
):
    """הדילוג בשאילתה נשען על רשימה שנקראה רגע לפני. worker אחר יכול לתפוס ג'וב לאותו ריפו בינתיים — כאן הרשימה
    "ישנה" (ריקה), והאינדקס הוא שעוצר. הג'וב נשאר ``pending``."""
    indexed_db.sync_jobs.insert_many(
        [_job("a1", "A", rss.JOB_RUNNING, heartbeat_at=_now()), _job("a2", "A", created=2)]
    )
    monkeypatch.setattr(rss, "_running_repos", lambda db: [])

    with caplog.at_level(logging.INFO, logger="services.repo_sync_service"):
        assert rss._claim_next_job(indexed_db) is None

    assert indexed_db.sync_jobs.find_one({"_id": "a2"})["status"] == rss.JOB_PENDING
    assert "claim lost to another worker" in caplog.text


def test_workers_claiming_at_the_same_moment_run_one_job_per_repo(indexed_db, monkeypatch):
    """במקביל ולא ברצף: שמונה חוטים, כל אחד עם תמונת "אין ג'וב רץ", תופסים יחד מתוך ארבעה ג'ובים של ריפו אחד."""
    indexed_db.sync_jobs.insert_many([_job(f"a{n}", "A", created=n) for n in range(4)])
    start = threading.Barrier(8)
    claimed = []

    def _claim():
        start.wait()
        job = rss._claim_next_job(indexed_db)
        if job:
            claimed.append(job["_id"])

    monkeypatch.setattr(rss, "_running_repos", lambda db: [])  # כולם רואים "אין ג'וב רץ", כמו בתזמון הגרוע
    threads = [threading.Thread(target=_claim) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)

    assert len(claimed) == 1
    assert indexed_db.sync_jobs.count_documents({"repo_name": "A", "status": rss.JOB_RUNNING}) == 1
    assert indexed_db.sync_jobs.count_documents({"repo_name": "A", "status": rss.JOB_PENDING}) == 3


# ---------------------------------------------------------------------------
# שחרור של ג'וב שה-worker שלו מת
# ---------------------------------------------------------------------------


def test_only_running_jobs_without_a_recent_heartbeat_are_released(indexed_db, caplog):
    stale = _now() - timedelta(seconds=rss.SYNC_JOB_STALE_SECONDS + 60)
    fresh = _now() - timedelta(seconds=30)
    indexed_db.sync_jobs.insert_many([
        _job("dead", "A", rss.JOB_RUNNING, heartbeat_at=stale, started_at=stale),
        _job("alive", "B", rss.JOB_RUNNING, heartbeat_at=fresh, started_at=stale),
        # נתפס לפני שהיה דופק: נמדד לפי ``started_at``.
        _job("old_claim", "C", rss.JOB_RUNNING, started_at=stale),
        _job("new_claim", "D", rss.JOB_RUNNING, started_at=fresh),
        _job("done", "E", rss.JOB_COMPLETED, heartbeat_at=stale),
    ])

    with caplog.at_level(logging.WARNING, logger="services.repo_sync_service"):
        released = rss._release_abandoned_jobs(indexed_db)

    assert released == 2
    status = {d["_id"]: (d["status"], d.get("error")) for d in indexed_db.sync_jobs.find()}
    assert status["dead"] == status["old_claim"] == (rss.JOB_FAILED, rss.FAIL_ABANDONED)
    assert status["alive"] == status["new_claim"] == (rss.JOB_RUNNING, None)
    assert status["done"] == (rss.JOB_COMPLETED, None)
    dead = indexed_db.sync_jobs.find_one({"_id": "dead"})
    assert (dead["result"]["status"], dead["result"]["reason"]) == (rss.RESULT_FAILED, rss.FAIL_ABANDONED)
    assert "released as abandoned" in caplog.text


def test_a_released_job_frees_its_repo_for_the_next_job(indexed_db):
    stale = _now() - timedelta(seconds=rss.SYNC_JOB_STALE_SECONDS + 60)
    indexed_db.sync_jobs.insert_many([_job("a1", "A", rss.JOB_RUNNING, heartbeat_at=stale), _job("a2", "A", created=2)])
    assert rss._claim_next_job(indexed_db) is None

    rss._release_abandoned_jobs(indexed_db)

    assert rss._claim_next_job(indexed_db)["_id"] == "a2"


# ---------------------------------------------------------------------------
# הדופק
# ---------------------------------------------------------------------------


def test_the_heartbeat_moves_while_the_job_runs_and_stops_once_it_is_released(indexed_db, monkeypatch, caplog):
    monkeypatch.setattr(rss, "SYNC_JOB_HEARTBEAT_SECONDS", 0.05)
    indexed_db.sync_jobs.insert_one(_job("a1", "A"))
    job = rss._claim_next_job(indexed_db)
    first = indexed_db.sync_jobs.find_one({"_id": "a1"})["heartbeat_at"]

    with caplog.at_level(logging.WARNING, logger="services.repo_sync_service"):
        stop = rss._start_heartbeat(indexed_db, job)
        try:
            deadline = time.monotonic() + 5
            while indexed_db.sync_jobs.find_one({"_id": "a1"})["heartbeat_at"] <= first:
                assert time.monotonic() < deadline, "the heartbeat never moved"
                time.sleep(0.02)
            indexed_db.sync_jobs.update_one({"_id": "a1"}, {"$set": {"status": rss.JOB_FAILED}})
            deadline = time.monotonic() + 5
            while "no longer running under this claim" not in caplog.text:
                assert time.monotonic() < deadline, "the heartbeat did not stop after the job was released"
                time.sleep(0.02)
            # החוט נגמר מעצמו, עוד לפני ה-``stop`` שבסוף.
            deadline = time.monotonic() + 5
            while any(t.name == "sync-job-heartbeat" and t.is_alive() for t in threading.enumerate()):
                assert time.monotonic() < deadline, "the heartbeat thread is still alive"
                time.sleep(0.02)
        finally:
            stop.set()


def test_the_worker_runs_a_job_with_a_heartbeat_and_prepares_the_indexes_first(jobs_db, monkeypatch):
    """מקצה לקצה דרך ``_sync_worker``: האינדקסים קיימים לפני התפיסה, הדופק רץ בזמן הג'וב, והג'וב מסתיים."""

    class _Stop(BaseException):
        pass

    jobs_db.sync_jobs.insert_one(_job("a1", "A"))
    seen = {}
    real_claim = rss._claim_next_job
    claims = []

    def _claim(db):
        claims.append(1)
        if len(claims) > 1:
            raise _Stop()
        return real_claim(db)

    def _run(job, db):
        seen["indexes"] = {idx["name"] for idx in db.sync_jobs.list_indexes()}
        seen["heartbeats"] = [t.name for t in threading.enumerate() if t.name == "sync-job-heartbeat"]
        return {"status": rss.RESULT_SYNCED}

    monkeypatch.setattr(rss, "_mirror_fill_done", None)
    monkeypatch.setattr(rss, "_claim_next_job", _claim)
    monkeypatch.setattr(rss, "_run_sync_from_doc", _run)

    with pytest.raises(_Stop):
        rss._sync_worker()

    assert rss.SYNC_JOBS_ONE_RUNNING_INDEX in seen["indexes"]
    assert seen["heartbeats"]
    assert jobs_db.sync_jobs.find_one({"_id": "a1"})["status"] == rss.JOB_COMPLETED


# ---------------------------------------------------------------------------
# בלי מונגו: המתג, וההכנה של sync_jobs בתחילת ה-worker
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["0", "false", "OFF", " no "])
def test_the_switch_keeps_the_worker_off_and_the_job_pending(monkeypatch, caplog, value):
    # המודול ולא ``import database.db_manager``: לחבילה יש תכונה בשם הזה (``database/__init__.py``).
    dbm = importlib.import_module("database.db_manager")

    writes = []
    db = types.SimpleNamespace(sync_jobs=types.SimpleNamespace(update_one=lambda *a, **k: writes.append(a)))
    monkeypatch.setattr(dbm, "get_db", lambda: db)
    monkeypatch.setattr(rss, "_worker_started", False)
    monkeypatch.setenv("WEBAPP_SYNC_WORKER", value)
    started = []
    monkeypatch.setattr(rss, "_sync_worker", lambda: started.append(1))

    with caplog.at_level(logging.INFO, logger="services.repo_sync_service"):
        rss.trigger_sync("A", "b" * 40, delivery_id="d1")

    assert len(writes) == 1 and writes[0][1]["$setOnInsert"]["status"] == rss.JOB_PENDING
    assert rss._worker_started is False and started == []
    assert "stays pending: the sync worker is off" in caplog.text


def test_without_the_switch_the_worker_starts(monkeypatch):
    monkeypatch.delenv("WEBAPP_SYNC_WORKER", raising=False)
    monkeypatch.setattr(rss, "_worker_started", False)
    ran = threading.Event()
    monkeypatch.setattr(rss, "_sync_worker", ran.set)

    assert rss._ensure_worker_started() is True
    assert ran.wait(5) and rss._worker_started is True


def test_a_worker_that_failed_to_start_at_boot_is_started_by_the_next_call(monkeypatch):
    """הרמה שנכשלה בעלייה לא מציבה את הדגל — אחרת ה-webhook הבא היה מדלג עליה, והשירות נשאר בלי worker עד
    הפעלה מחדש (K15 ב-amir-bug-patterns, סעיף 3)."""
    monkeypatch.delenv("WEBAPP_SYNC_WORKER", raising=False)
    monkeypatch.setattr(rss, "_worker_started", False)
    ran = threading.Event()
    monkeypatch.setattr(rss, "_sync_worker", ran.set)
    real_start = threading.Thread.start

    def _start(self):
        if self.name == rss.SYNC_WORKER_THREAD_NAME:
            raise RuntimeError("can't start new thread")
        return real_start(self)

    monkeypatch.setattr(threading.Thread, "start", _start)
    with pytest.raises(RuntimeError):
        rss.start_sync_worker()
    assert rss._worker_started is False and not ran.is_set()

    monkeypatch.setattr(threading.Thread, "start", real_start)
    assert rss.start_sync_worker() is True
    assert ran.wait(5) and rss._worker_started is True


def test_preparing_the_jobs_is_tried_again_only_when_the_database_did_not_answer(monkeypatch, caplog):
    from pymongo.errors import AutoReconnect, OperationFailure

    def _raise(exc):
        def _ensure(db):
            raise exc
        return _ensure

    monkeypatch.setattr(rss, "ensure_sync_jobs_indexes", _raise(AutoReconnect("x")))
    assert rss._prepare_sync_jobs(object()) is False

    monkeypatch.setattr(rss, "ensure_sync_jobs_indexes", _raise(OperationFailure("not authorized")))
    with caplog.at_level(logging.ERROR, logger="services.repo_sync_service"):
        assert rss._prepare_sync_jobs(object()) is True
    assert "could not be prepared" in caplog.text


@pytest.mark.parametrize("outcome", ["finished", "raised"])
def test_the_heartbeat_is_stopped_before_the_final_status_is_written(monkeypatch, outcome):
    """דופק שמתעורר אחרי הסטטוס הסופי לא מוצא ג'וב ``running``, ורושם אזהרה על ג'וב שהסתיים כרגיל. לכן הוא נעצר קודם,
    בהצלחה ובכשל."""
    # המודול ולא ``import database.db_manager``: לחבילה יש תכונה בשם הזה (``database/__init__.py``).
    dbm = importlib.import_module("database.db_manager")

    class _Stop(BaseException):
        pass

    beats = []
    jobs = iter([{"_id": "a1", "repo_name": "A", "claim_id": "c1"}])

    def _claim(db):
        try:
            return next(jobs)
        except StopIteration:
            raise _Stop()

    def _start(db, job):
        beats.append(threading.Event())
        return beats[-1]

    def _run(job, db):
        if outcome == "raised":
            raise RuntimeError("the sync broke")
        return {"status": rss.RESULT_SYNCED}

    stopped_when_written = []
    monkeypatch.setattr(dbm, "get_db", lambda: object())
    monkeypatch.setattr(rss, "_mirror_fill_done", None)
    monkeypatch.setattr(rss, "_prepare_sync_jobs", lambda db: True)
    monkeypatch.setattr(rss, "_release_abandoned_jobs", lambda db: 0)
    monkeypatch.setattr(rss, "_claim_next_job", _claim)
    monkeypatch.setattr(rss, "_start_heartbeat", _start)
    monkeypatch.setattr(rss, "_run_sync_from_doc", _run)
    monkeypatch.setattr(rss, "_finish_job", lambda db, job, result: stopped_when_written.append(beats[0].is_set()))
    monkeypatch.setattr(
        rss, "_update_job_with_retry", lambda db, job_id, doc: stopped_when_written.append(beats[0].is_set())
    )

    with pytest.raises(_Stop):
        rss._sync_worker()

    assert stopped_when_written == [True]


def test_a_worker_without_a_database_waits_instead_of_failing_on_none(monkeypatch, caplog):
    """``get_db`` מחזיר ``None`` בחלון ההמתנה שאחרי חיבור שנכשל (K11): ה-worker מחכה, ולא נופל ב-``AttributeError``."""
    # המודול ולא ``import database.db_manager``: לחבילה יש תכונה בשם הזה (``database/__init__.py``).
    dbm = importlib.import_module("database.db_manager")

    class _Stop(BaseException):
        pass

    handles = iter([None])
    monkeypatch.setattr(dbm, "get_db", lambda: next(handles))
    monkeypatch.setattr(rss, "_mirror_fill_done", None)

    def _sleep(seconds):
        raise _Stop()

    monkeypatch.setattr(rss, "time", types.SimpleNamespace(monotonic=time.monotonic, sleep=_sleep))

    with caplog.at_level(logging.WARNING, logger="services.repo_sync_service"), pytest.raises(_Stop):
        rss._sync_worker()

    assert "MongoDB is not available yet" in caplog.text
    assert "Worker error" not in caplog.text
