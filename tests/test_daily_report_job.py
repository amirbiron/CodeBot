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
    """דמה של ``admin_reports`` שמתנהגת כמו מונגו, לא כמו שנוח לנו.

    זו הנקודה החשובה בקובץ הזה. ה-upsert המותנה
    (``{"_id": ..., "day_key": {"$ne": today}}`` עם ``upsert=True``) **לא**
    מחזיר "0 מסמכים עודכנו" כשהמסמך כבר קיים עם ה-``day_key`` של היום.
    תיעוד MongoDB, בסעיף Upsert Behavior, אומר שהמסמך החדש נבנה *מסעיפי
    השוויון בלבד* ושאופרטורי השוואה (``$ne``) אינם נכנסים אליו — ולכן מונגו
    מנסה ליצור מסמך עם אותו ``_id`` שכבר קיים, ונכשל בהתנגשות מפתח ייחודי.

    הדמה הקודמת החזירה ``modified_count=0``, כלומר הייתה **סלחנית מהמציאות**,
    וזו הייתה הסיבה היחידה שהבדיקה "לא מדווח פעמיים" עברה. עכשיו היא זורקת,
    כמו השרת.
    """

    def __init__(self, raises=None):
        self.docs = {}
        self.calls = 0
        self._raises = raises

    async def update_one(self, query, update, upsert=False):  # noqa: ARG002
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        key = query["_id"]
        blocked = query.get("day_key", {}).get("$ne")
        existing = self.docs.get(key)
        if existing is not None and existing.get("day_key") == blocked:
            raise _duplicate_key_error()
        self.docs[key] = dict(existing or {}, **update.get("$set", {}))
        return type("R", (), {"modified_count": 1, "upserted_id": None})()


def _duplicate_key_error():
    """אותה חריגה שהקוד תופס — מיובאת מאותו מקום שממנו ``main`` מייבא אותה."""
    import main

    return main.DuplicateKeyError("E11000 duplicate key error")


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
    """התראה אחת ליום — אחרת המנגנון מייצר רעש כל 60 שניות.

    מול הדמה המתוקנת, שזורקת ``DuplicateKeyError`` בהתנגשות כמו השרת, הבדיקה
    הזו מבדילה בין "השער עובד" לבין "השער נכשל וה-``except`` הרחב בלע אותו".
    """
    now = datetime(2026, 9, 7, 8, 0, tzinfo=UTC)
    db = _AsyncDB(_AsyncJobRuns([]))
    loop = asyncio.get_event_loop()
    first = loop.run_until_complete(main_mod._check_missed_scheduled_jobs(db, now))
    second = loop.run_until_complete(main_mod._check_missed_scheduled_jobs(db, now))
    third = loop.run_until_complete(main_mod._check_missed_scheduled_jobs(db, now))
    assert first == ["daily_morning_report"]
    assert second == [], "התנגשות מפתח ייחודי היא 'כבר דיווחנו', לא 'לא הצלחנו לבדוק'"
    assert third == []


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


def test_missed_check_is_silent_when_nothing_declares_the_metadata(main_mod, registered_daily_job):
    """המנגנון כללי ונשען על ``metadata``, ולא קשיח ל-job אחד.

    הפיקסצ'ר ``registered_daily_job`` חיוני כאן ולא קישוט: הוא זה שרושם את
    ה-jobs. בלעדיו, כשהקובץ רץ לבדו, הרגיסטרי ריק — הלולאה שמנקה
    ``missed_after_hours`` לא מוחקת כלום, והבדיקה עוברת בלי שבדקה דבר.
    """
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


def test_missed_job_is_reported_again_on_a_new_day(main_mod, registered_daily_job):
    """הצד השני: השער חוסם יום, לא לתמיד.

    בלי הטענה הזו, קוד שפשוט מפסיק לדווח לעד היה עובר את הבדיקה שמעל.
    """
    db = _AsyncDB(_AsyncJobRuns([]))
    loop = asyncio.get_event_loop()
    day_one = datetime(2026, 9, 7, 8, 0, tzinfo=UTC)
    day_two = datetime(2026, 9, 8, 8, 0, tzinfo=UTC)
    assert loop.run_until_complete(main_mod._check_missed_scheduled_jobs(db, day_one)) == [
        "daily_morning_report"
    ]
    assert loop.run_until_complete(main_mod._check_missed_scheduled_jobs(db, day_two)) == [
        "daily_morning_report"
    ]


def test_a_broken_gate_still_lets_the_alert_through(main_mod, registered_daily_job):
    """כשל אחר בשער — fail-open, בכוונה.

    התראה שנעלמת גרועה מהתראה כפולה. זו המדיניות ההפוכה מזו של הדוח היומי,
    ולכן היא נבדקת בנפרד: מי שיהפוך את ה-``except`` הרחב ל-``continue``
    יראה את הבדיקה הזו נופלת.
    """
    now = datetime(2026, 9, 7, 8, 0, tzinfo=UTC)
    reports = _AsyncAdminReports(raises=RuntimeError("mongo down"))
    db = _AsyncDB(_AsyncJobRuns([]), admin_reports=reports)
    result = asyncio.get_event_loop().run_until_complete(
        main_mod._check_missed_scheduled_jobs(db, now)
    )
    assert result == ["daily_morning_report"]
    assert reports.calls == 1


# --------------------------------------------------------------------------
# שער האידמפוטנטיות של הדוח היומי
# --------------------------------------------------------------------------


class _SyncAdminReports:
    """דמה סינכרונית (pymongo), כי הדוח היומי רץ מול לקוח האפליקציה."""

    def __init__(self, raises=None):
        self.docs = {}
        self.calls = 0
        self._raises = raises

    def update_one(self, query, update, upsert=False):  # noqa: ARG002
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        key = query["_id"]
        blocked = query.get("day_key", {}).get("$ne")
        existing = self.docs.get(key)
        if existing is not None and existing.get("day_key") == blocked:
            raise _duplicate_key_error()
        self.docs[key] = dict(existing or {}, **update.get("$set", {}))
        return type("R", (), {"modified_count": 0, "upserted_id": key})()


class _SyncDB:
    def __init__(self, reports):
        self._reports = reports

    def __getitem__(self, name):
        assert name == "admin_reports"
        return self._reports


def test_daily_report_claims_the_day_once(main_mod):
    """התביעה הראשונה מצליחה, השנייה מזהה שהיום כבר נתפס."""
    now = datetime(2026, 9, 7, 8, 0, tzinfo=UTC)
    db = _SyncDB(_SyncAdminReports())
    assert main_mod._claim_daily_report_day(db, "2026-09-07", now) == "claimed"
    assert main_mod._claim_daily_report_day(db, "2026-09-07", now) == "already"
    # יום חדש נתפס מחדש — אחרת הדוח היה נשלח פעם אחת ודי.
    assert main_mod._claim_daily_report_day(db, "2026-09-08", now) == "claimed"


def test_daily_report_claim_fails_closed(main_mod):
    """כשל בתביעה אינו 'claimed'.

    זו המדיניות ההפוכה מ-``job_missed``, ובכוונה: דוח כפול גרוע מדוח חסר.
    """
    db = _SyncDB(_SyncAdminReports(raises=RuntimeError("mongo down")))
    assert main_mod._claim_daily_report_day(db, "2026-09-07", datetime(2026, 9, 7, tzinfo=UTC)) == "error"


def test_claim_outcome_reads_both_shapes_of_a_successful_write(main_mod):
    """‏upsert מחזיר ``upserted_id``, עדכון מחזיר ``modified_count`` — שניהם תפיסה."""

    def _res(modified=0, upserted=None):
        return type("R", (), {"modified_count": modified, "upserted_id": upserted})()

    assert main_mod._claim_outcome(_res(upserted="x")) == "claimed"
    assert main_mod._claim_outcome(_res(modified=1)) == "claimed"
    assert main_mod._claim_outcome(_res()) == "already"


# --------------------------------------------------------------------------
# שתי בדיקות המוניטור — עצמאיות
# --------------------------------------------------------------------------


class _BrokenJobRuns(_AsyncJobRuns):
    """‏``find`` נופל, ``aggregate`` תקין — בדיוק תרחיש הכשל החלקי."""

    def find(self, *_a, **_k):
        raise RuntimeError("find exploded")


def test_a_broken_stuck_check_does_not_silence_the_missed_check(main_mod, registered_daily_job, monkeypatch):
    """הממצא: שתי הבדיקות חלקו גורל.

    ‏``job_stuck`` משתמש ב-``find`` ו-``job_missed`` ב-``aggregate``. עד
    התיקון, יציאה מוקדמת או חריגה במסלול הראשון דילגה על השני לגמרי.
    """
    import observability

    emitted = []
    monkeypatch.setattr(observability, "emit_event", lambda name, **kw: emitted.append((name, kw)))

    db = _AsyncDB(_BrokenJobRuns([]))
    asyncio.get_event_loop().run_until_complete(
        main_mod._jobs_monitor_tick(db, datetime(2026, 9, 7, 8, 0, tzinfo=UTC))
    )
    assert [name for name, _ in emitted] == ["job_missed"]


def test_a_collection_without_find_does_not_silence_the_missed_check(main_mod, registered_daily_job, monkeypatch):
    """המסלול השני של אותו באג: יציאה מוקדמת, לא חריגה."""
    import observability

    emitted = []
    monkeypatch.setattr(observability, "emit_event", lambda name, **kw: emitted.append((name, kw)))

    class _NoFind(_AsyncJobRuns):
        find = None

    db = _AsyncDB(_NoFind([]))
    asyncio.get_event_loop().run_until_complete(
        main_mod._jobs_monitor_tick(db, datetime(2026, 9, 7, 8, 0, tzinfo=UTC))
    )
    assert [name for name, _ in emitted] == ["job_missed"]


def test_the_missed_event_carries_the_declared_hours(main_mod, registered_daily_job, monkeypatch):
    """האירוע נושא את ``missed_after_hours`` מה-metadata ולא מספר קשיח."""
    import observability

    emitted = []
    monkeypatch.setattr(observability, "emit_event", lambda name, **kw: emitted.append((name, kw)))

    db = _AsyncDB(_AsyncJobRuns([]))
    asyncio.get_event_loop().run_until_complete(
        main_mod._jobs_monitor_tick(db, datetime(2026, 9, 7, 8, 0, tzinfo=UTC))
    )
    assert emitted and emitted[0][0] == "job_missed"
    assert emitted[0][1]["job_id"] == "daily_morning_report"
    assert emitted[0][1]["hours"] == 26


# --------------------------------------------------------------------------
# מסלול השליחה המלא — שהשערים באמת נקראים, ולא רק קיימים
# --------------------------------------------------------------------------


class _TrackerSpy:
    def __init__(self):
        self.logs = []
        self.skipped = None
        self.failed = None

    def add_log(self, _run_id, level, message):
        self.logs.append((level, message))

    def skip_run(self, _run_id, reason):
        self.skipped = reason

    def fail_run(self, _run_id, reason):
        self.failed = reason


class _RunStub:
    run_id = "r1"


@pytest.fixture()
def sending_report(main_mod, monkeypatch, deliverable_env):
    """מרכיב מסלול שליחה מלא שבו רק שער היום עוד לא הוכרע.

    המקורות עצמם מוחלפים: מה שנבדק כאן הוא **החיווט** — האם הגוף באמת
    קורא לשער לפני ``emit_internal_alert`` — ולא הלוגיקה של האיסוף, שיש לה
    בדיקות משלה ב-``test_daily_report_service.py``.
    """
    import internal_alerts
    import services.daily_report_service as drs

    reports = _SyncAdminReports()

    class _DB:
        def __getitem__(self, name):
            if name == "admin_reports":
                return reports
            return object()

    sent = []
    monkeypatch.setattr(main_mod, "_daily_report_db", lambda: _DB())
    monkeypatch.setattr(main_mod, "_build_daily_report_deps", lambda _db: None)
    monkeypatch.setattr(main_mod, "get_admin_ids", lambda: [1])
    monkeypatch.setattr(drs, "load_snapshot", lambda *_a, **_k: None)
    monkeypatch.setattr(drs, "collect_snapshot", lambda **_k: {"_id": "d"})
    monkeypatch.setattr(drs, "save_snapshot", lambda *_a, **_k: {"_id": "d"})
    monkeypatch.setattr(drs, "compare", lambda *_a, **_k: drs.ReportDiff(day_label="07/09", sections=["alerts"]))
    monkeypatch.setattr(drs, "render_report", lambda *_a, **_k: "📋 דוח")
    monkeypatch.setattr(internal_alerts, "emit_internal_alert", lambda *a, **k: sent.append(k or a))
    monkeypatch.delenv("DISABLE_DAILY_REPORT", raising=False)
    return sent, reports


def test_the_report_is_sent_once_a_day_even_across_restarts(main_mod, sending_report):
    """הטענה שהריוויו לא כיסה, וזו שנשברה בפרודקשן בדוח השבועי.

    שתי הרצות באותו יום — כמו שקורה בכל עלייה מחדש של הבוט — שולחות פעם
    אחת. מי שיסיר את השער מגוף ה-job יראה את הבדיקה הזו נופלת, ולא רק את
    הבדיקה של הפונקציה העצמאית.
    """
    sent, reports = sending_report
    tracker_one, tracker_two = _TrackerSpy(), _TrackerSpy()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main_mod._daily_morning_report_body(tracker_one, _RunStub()))
    loop.run_until_complete(main_mod._daily_morning_report_body(tracker_two, _RunStub()))

    assert len(sent) == 1, "הדוח נשלח פעמיים באותו יום — זה בדיוק מה שקרה לדוח השבועי"
    assert tracker_one.skipped is None
    assert tracker_two.skipped == "already_sent_today"
    assert reports.calls == 2, "השער חייב להיקרא בשתי ההרצות, אחרת הוא לא באמת שער"


def test_a_failed_claim_blocks_the_send(main_mod, sending_report, monkeypatch):
    """fail-closed לאורך כל המסלול, לא רק בפונקציה העצמאית."""
    sent, _reports = sending_report
    monkeypatch.setattr(main_mod, "_claim_daily_report_day", lambda *_a: "error")
    tracker = _TrackerSpy()
    asyncio.get_event_loop().run_until_complete(
        main_mod._daily_morning_report_body(tracker, _RunStub())
    )
    assert sent == []
    assert tracker.failed == "day_claim_failed"


def test_a_blocked_delivery_gate_never_reaches_the_day_claim(main_mod, sending_report, monkeypatch):
    """סדר השערים: מסירה קודם, תפיסת היום אחריה.

    אילו התפיסה הייתה קודמת, יום שנחסם על סף החומרה היה "נשרף" — והרצה
    חוזרת אחרי תיקון ההגדרות לא הייתה שולחת דבר.
    """
    sent, reports = sending_report
    monkeypatch.setenv("ALERT_TELEGRAM_MIN_SEVERITY", "critical")
    tracker = _TrackerSpy()
    asyncio.get_event_loop().run_until_complete(
        main_mod._daily_morning_report_body(tracker, _RunStub())
    )
    assert sent == []
    assert tracker.failed == "telegram_gate:below_min_severity"
    assert reports.calls == 0, "היום לא נתפס, ולכן הרצה חוזרת אחרי תיקון ההגדרות עדיין תוכל לשלוח"


def test_a_quiet_day_does_not_burn_the_day(main_mod, sending_report, monkeypatch):
    """יום שקט אינו הודעה, ואינו תופס את היום.

    זו הסיבה שהשער יושב אחרי הרינדור: טריגר ידני מאוחר יותר, אחרי שכן קרה
    משהו, חייב להיות מסוגל לשלוח.
    """
    sent, reports = sending_report
    import services.daily_report_service as drs

    monkeypatch.setattr(drs, "render_report", lambda *_a, **_k: None)
    tracker = _TrackerSpy()
    asyncio.get_event_loop().run_until_complete(
        main_mod._daily_morning_report_body(tracker, _RunStub())
    )
    assert sent == []
    assert reports.calls == 0
    assert ("info", "nothing_to_report") in tracker.logs
    assert tracker.skipped is None, "יום שקט הוא ריצה מוצלחת — הרשומה הזו היא מדד החיות של ה-job"
