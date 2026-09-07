"""בדיקות ל-job של דוח הבוקר: שער המסירה, התזמון, וזיהוי job שלא רץ.

הבדיקות כאן נוגעות בקוד שב-``main.py``, ולכן הן עובדות מול הפונקציות
ברמת המודול — אלה שנכתבו במפורש כדי להיות ניתנות לבדיקה בלי להרים את הבוט.

הדגש המרכזי: **שער המסירה**. ``emit_internal_alert`` מחזיר ``None`` תמיד
ואינו מדווח כשל, ולכן בלי בדיקה מוקדמת הדוח היה מסתיים כ-``completed`` גם
כשההודעה נחסמה על סף החומרה — הצלחה מדומה על משהו שלא קרה.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

UTC = timezone.utc


@pytest.fixture()
def main_mod():
    import main

    return main


# --------------------------------------------------------------------------
# שער המסירה — 11, 11א, 11ב
# --------------------------------------------------------------------------


@pytest.fixture()
def deliverable_env(monkeypatch):
    """סביבה שבה ההודעה כן אמורה להגיע — נקודת המוצא לכל בדיקות השער."""
    monkeypatch.setenv("ALERT_TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("ALERT_TELEGRAM_CHAT_ID", "1")
    monkeypatch.setenv("ALERT_TELEGRAM_MIN_SEVERITY", "warn")
    import alert_forwarder as af

    monkeypatch.setattr(af, "_TELEGRAM_SUPPRESS_ALERTS", set())


def test_gate_open_when_severity_is_allowed(main_mod, deliverable_env):
    """‏warn מול סף warn — עובר. זה הצד ש'סוגר' חייב להיבדל ממנו."""
    assert main_mod._daily_report_gate_reason() == ""


def test_gate_blocks_when_min_severity_is_above_report(main_mod, deliverable_env, monkeypatch):
    """הכשל שהתגלה בחקירה: סף ``critical`` בולע דוח ב-``warn`` בשקט מוחלט.

    בלי השער הזה ה-job היה מסתיים ב-``completed`` בזמן שאף הודעה לא נשלחה.
    """
    monkeypatch.setenv("ALERT_TELEGRAM_MIN_SEVERITY", "critical")
    assert main_mod._daily_report_gate_reason() == "below_min_severity"


def test_gate_blocks_when_alert_name_is_suppressed(main_mod, deliverable_env, monkeypatch):
    """רשימת ההשתקה נקראת מה-forwarder עצמו, לא ממשתנה הסביבה.

    ``_TELEGRAM_SUPPRESS_ALERTS`` מחושב בזמן ה-import, ולכן קריאה עצמאית של
    ``os.getenv`` הייתה יכולה לסתור את מה שקורה בפועל.
    """
    import alert_forwarder as af
    import services.daily_report_service as drs

    monkeypatch.setattr(af, "_TELEGRAM_SUPPRESS_ALERTS", {drs.REPORT_ALERT_NAME})
    assert main_mod._daily_report_gate_reason() == "suppressed"


@pytest.mark.parametrize(
    "missing,expected",
    [("ALERT_TELEGRAM_CHAT_ID", "no_chat"), ("ALERT_TELEGRAM_BOT_TOKEN", "no_token")],
)
def test_gate_blocks_when_telegram_is_not_configured(main_mod, deliverable_env, monkeypatch, missing, expected):
    monkeypatch.delenv(missing, raising=False)
    assert main_mod._daily_report_gate_reason() == expected


def test_gate_failure_fails_the_run_instead_of_reporting_success(main_mod, deliverable_env, monkeypatch):
    """הטענה המרכזית: שער חסום ← ``fail_run``, ולא ``completed``."""
    monkeypatch.setenv("ALERT_TELEGRAM_MIN_SEVERITY", "critical")

    class Tracker:
        def __init__(self):
            self.failed_with = None

        def fail_run(self, _run_id, message):
            self.failed_with = message

    class Run:
        run_id = "r1"

    tracker = Tracker()
    assert main_mod._daily_report_gate_ok(Run(), tracker) is False
    assert tracker.failed_with == "telegram_gate:below_min_severity"

    monkeypatch.setenv("ALERT_TELEGRAM_MIN_SEVERITY", "warn")
    tracker2 = Tracker()
    assert main_mod._daily_report_gate_ok(Run(), tracker2) is True
    assert tracker2.failed_with is None


# --------------------------------------------------------------------------
# קונפיגורציה
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [("08:00", (8, 0)), ("6:30", (6, 30)), ("23:59", (23, 59))],
)
def test_hour_env_is_parsed(main_mod, monkeypatch, value, expected):
    monkeypatch.setenv("DAILY_REPORT_HOUR_LOCAL", value)
    assert main_mod._daily_report_hour_minute() == expected


@pytest.mark.parametrize("bad", ["", "abc", "25:00", "08:99"])
def test_bad_hour_env_falls_back_to_eight_instead_of_crashing(main_mod, monkeypatch, bad):
    """ערך פגום לא מפיל את התזמון — job בלי זמן פשוט לא ירוץ."""
    monkeypatch.setenv("DAILY_REPORT_HOUR_LOCAL", bad)
    assert main_mod._daily_report_hour_minute() == (8, 0)


def test_correlation_window_env_is_clamped(main_mod, monkeypatch):
    """חלון של אפס או של יומיים אינו חלון — הערך נחסם לטווח שפוי."""
    monkeypatch.setenv("DAILY_REPORT_CORRELATION_WINDOW_MINUTES", "0")
    assert main_mod._daily_report_window_minutes() == 1
    monkeypatch.setenv("DAILY_REPORT_CORRELATION_WINDOW_MINUTES", "99999")
    assert main_mod._daily_report_window_minutes() == 120
    monkeypatch.setenv("DAILY_REPORT_CORRELATION_WINDOW_MINUTES", "5")
    assert main_mod._daily_report_window_minutes() == 5


# --------------------------------------------------------------------------
# תזמון
# --------------------------------------------------------------------------


class _JobQueueSpy:
    def __init__(self, daily_raises=None):
        self.daily_calls = []
        self.repeating_calls = []
        self._daily_raises = daily_raises

    def run_daily(self, callback, time=None, name=None, job_kwargs=None):  # noqa: A002
        self.daily_calls.append({"time": time, "name": name, "job_kwargs": job_kwargs})
        if self._daily_raises is not None:
            raise self._daily_raises

    def run_repeating(self, callback, interval=None, first=None, name=None):
        self.repeating_calls.append({"interval": interval, "first": first, "name": name})


class _AppSpy:
    def __init__(self, job_queue):
        self.job_queue = job_queue


def test_schedule_uses_run_daily_with_an_explicit_timezone(main_mod, monkeypatch):
    """ה-``time`` חייב לשאת ``tzinfo``.

    ה-``Defaults`` של הבוט מוגדר רק עם ``parse_mode``, וברירת המחדל של
    JobQueue היא UTC — כלומר בלי אזור זמן מפורש הדוח היה נשלח בשעה הלא נכונה.
    """
    monkeypatch.setenv("DAILY_REPORT_HOUR_LOCAL", "08:00")
    jq = _JobQueueSpy()
    main_mod._schedule_daily_morning_report(_AppSpy(jq), lambda *_a: None)

    assert len(jq.daily_calls) == 1
    call = jq.daily_calls[0]
    assert call["name"] == "daily_morning_report", "השם חייב להיות זהה ל-job_id, אחרת טריגר ידני לא ימצא אותו"
    assert (call["time"].hour, call["time"].minute) == (8, 0)
    assert call["time"].tzinfo is not None
    assert call["job_kwargs"]["misfire_grace_time"] == 3600
    assert jq.repeating_calls == []


def test_schedule_falls_back_to_repeating_when_run_daily_is_unavailable(main_mod, monkeypatch):
    """נפילה מבוקרת, באותה תבנית שכבר קיימת ב-``_safe_run_repeating``."""
    monkeypatch.setenv("DAILY_REPORT_HOUR_LOCAL", "08:00")

    class OnlyRepeating(_JobQueueSpy):
        def run_daily(self, *a, **k):
            raise TypeError("run_daily unsupported")

    jq = OnlyRepeating()
    main_mod._schedule_daily_morning_report(_AppSpy(jq), lambda *_a: None)
    assert len(jq.repeating_calls) == 1
    assert jq.repeating_calls[0]["interval"] == 24 * 3600
    assert jq.repeating_calls[0]["name"] == "daily_morning_report"
    assert jq.repeating_calls[0]["first"] >= 60


def test_scheduling_failure_never_raises(main_mod):
    """כשל תזמון אינו מפיל את עליית הבוט."""

    class Broken:
        def run_daily(self, *a, **k):
            raise RuntimeError("nope")

        def run_repeating(self, *a, **k):
            raise RuntimeError("nope")

    main_mod._schedule_daily_morning_report(_AppSpy(Broken()), lambda *_a: None)


# --------------------------------------------------------------------------
# 12 + 19 — זיהוי job מתוזמן שלא רץ
# --------------------------------------------------------------------------


class _AsyncCursor:
    def __init__(self, rows):
        self._rows = rows

    async def to_list(self, length=None):  # noqa: ARG002
        return list(self._rows)


class _AsyncJobRuns:
    """דמה אסינכרונית של ``job_runs``, בסגנון motor."""

    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.aggregate_calls = 0
        self.last_pipeline = None

    def aggregate(self, pipeline):
        self.aggregate_calls += 1
        self.last_pipeline = pipeline
        match = pipeline[0]["$match"]
        wanted = set(match["job_id"]["$in"])
        statuses = set(match["status"]["$in"])
        cutoff = match["started_at"]["$gte"]
        grouped = {}
        for row in self.rows:
            if row["job_id"] in wanted and row["status"] in statuses and row["started_at"] >= cutoff:
                current = grouped.get(row["job_id"])
                if current is None or row["started_at"] > current:
                    grouped[row["job_id"]] = row["started_at"]
        return _AsyncCursor(
            [{"_id": job_id, "last_started_at": ts} for job_id, ts in grouped.items()]
        )


class _AsyncAdminReports:
    def __init__(self):
        self.docs = {}

    async def update_one(self, query, update, upsert=False):  # noqa: ARG002
        key = query["_id"]
        blocked = query.get("day_key", {}).get("$ne")
        existing = self.docs.get(key)
        if existing is not None and existing.get("day_key") == blocked:
            return type("R", (), {"modified_count": 0, "upserted_id": None})()
        self.docs[key] = dict(existing or {}, **update.get("$set", {}))
        return type("R", (), {"modified_count": 1, "upserted_id": None})()


class _AsyncDB:
    def __init__(self, job_runs, admin_reports=None):
        self.job_runs = job_runs
        self.admin_reports = admin_reports or _AsyncAdminReports()


@pytest.fixture()
def registered_daily_job():
    """מוודא שה-job רשום עם ה-metadata שהבדיקה נשענת עליו."""
    from services.register_jobs import register_all_jobs
    from services.job_registry import JobRegistry

    register_all_jobs()
    job = JobRegistry().get("daily_morning_report")
    assert job is not None, "ה-job חייב להיות רשום, אחרת הוא לא יופיע בדשבורד"
    assert (job.metadata or {}).get("missed_after_hours") == 26
    return job


def test_missed_job_is_reported_once_and_a_recent_run_is_not(main_mod, registered_daily_job):
    """שני הכיוונים: היעדר ריצה מדווח, וריצה טרייה לא.

    בלי הצד השני הבדיקה הייתה עוברת גם על קוד שמדווח על הכול תמיד.
    """
    now = datetime(2026, 9, 7, 8, 0, tzinfo=UTC)

    silent = _AsyncDB(_AsyncJobRuns([]))
    reported = asyncio.get_event_loop().run_until_complete(
        main_mod._check_missed_scheduled_jobs(silent, now)
    )
    assert "daily_morning_report" in reported

    recent = _AsyncDB(
        _AsyncJobRuns(
            [{"job_id": "daily_morning_report", "status": "completed", "started_at": now - timedelta(hours=3)}]
        )
    )
    assert asyncio.get_event_loop().run_until_complete(
        main_mod._check_missed_scheduled_jobs(recent, now)
    ) == []


def test_a_failed_run_still_counts_as_having_run(main_mod, registered_daily_job):
    """כשל כבר מכוסה ב-``job_failed``; ``job_missed`` הוא על אי-התחלה בלבד."""
    now = datetime(2026, 9, 7, 8, 0, tzinfo=UTC)
    db = _AsyncDB(
        _AsyncJobRuns(
            [{"job_id": "daily_morning_report", "status": "failed", "started_at": now - timedelta(hours=2)}]
        )
    )
    assert asyncio.get_event_loop().run_until_complete(
        main_mod._check_missed_scheduled_jobs(db, now)
    ) == []


def test_missed_job_is_not_reported_twice_in_the_same_day(main_mod, registered_daily_job):
    """התראה אחת ליום — אחרת המנגנון מייצר רעש כל 60 שניות."""
    now = datetime(2026, 9, 7, 8, 0, tzinfo=UTC)
    db = _AsyncDB(_AsyncJobRuns([]))
    loop = asyncio.get_event_loop()
    first = loop.run_until_complete(main_mod._check_missed_scheduled_jobs(db, now))
    second = loop.run_until_complete(main_mod._check_missed_scheduled_jobs(db, now))
    assert first == ["daily_morning_report"]
    assert second == []


def test_missed_check_uses_a_single_aggregate_not_a_loop(main_mod, registered_daily_job):
    """הבדיקה רצה כל 60 שניות ואסור לה לייצר את בעיית הביצועים שהיא תופסת."""
    now = datetime(2026, 9, 7, 8, 0, tzinfo=UTC)
    job_runs = _AsyncJobRuns([])
    asyncio.get_event_loop().run_until_complete(
        main_mod._check_missed_scheduled_jobs(_AsyncDB(job_runs), now)
    )
    assert job_runs.aggregate_calls == 1
    stages = [list(stage)[0] for stage in job_runs.last_pipeline]
    assert stages == ["$match", "$group"]


def test_clock_skew_does_not_hide_a_real_run(main_mod, registered_daily_job):
    """ריצה עם חותמת 'בעתיד' לא תיחשב כהיעדר ריצה."""
    now = datetime(2026, 9, 7, 8, 0, tzinfo=UTC)
    db = _AsyncDB(
        _AsyncJobRuns(
            [{"job_id": "daily_morning_report", "status": "completed", "started_at": now + timedelta(minutes=5)}]
        )
    )
    assert asyncio.get_event_loop().run_until_complete(
        main_mod._check_missed_scheduled_jobs(db, now)
    ) == []


def test_missed_check_is_silent_when_nothing_declares_the_metadata(main_mod):
    """המנגנון כללי ונשען על ``metadata``, ולא קשיח ל-job אחד."""
    from services.job_registry import JobRegistry

    registry = JobRegistry()
    saved = {}
    for job in registry.list_all():
        meta = getattr(job, "metadata", None) or {}
        if meta.get("missed_after_hours"):
            saved[job.job_id] = dict(meta)
            job.metadata = {}
    try:
        job_runs = _AsyncJobRuns([])
        result = asyncio.get_event_loop().run_until_complete(
            main_mod._check_missed_scheduled_jobs(_AsyncDB(job_runs), datetime(2026, 9, 7, 8, 0, tzinfo=UTC))
        )
        assert result == []
        assert job_runs.aggregate_calls == 0, "בלי job שמצהיר על ציפייה אין בכלל שאילתה"
    finally:
        for job_id, meta in saved.items():
            registry.get(job_id).metadata = meta
