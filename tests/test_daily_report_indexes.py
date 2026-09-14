"""אינדקסים שדוח הבוקר היומי נשען עליהם.

שני דברים נבדקים כאן, ושניהם נבדקים כי הם כבר נכשלו בריפו הזה בדיוק באותה
צורה: אינדקס שמוצהר במסמך ולא נוצר בקוד.

1. **ה-TTL של ``daily_report_snapshots``** — בלעדיו האוסף גדל בלי גבול, בדיוק
   כמו ``job_runs`` ו-``service_metrics``.
2. **האינדקס ``(job_id, started_at)`` על ``job_runs``** — הוא כבר מוצהר
   ב-``database/job_runs_collection.py``, אבל אותו קובץ אינו מיובא בשום מקום,
   ולכן אף אינדקס שבו לא נוצר בפועל. הבדיקה מקבעת שהוא באמת נוצר עכשיו.
"""

from __future__ import annotations


def _import_manager(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "x")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/db")
    monkeypatch.setenv("DISABLE_DB", "1")
    import database.manager as dm

    return dm


class TestDailyReportSnapshotIndex:
    def test_creates_a_ttl_index_on_the_field_the_writer_actually_writes(self, monkeypatch):
        dm = _import_manager(monkeypatch)
        import services.daily_report_service as drs

        requested: list[tuple] = []
        dm.DatabaseManager._create_daily_report_indexes(
            object(), lambda collection, keys, **kwargs: requested.append((collection, keys, kwargs))
        )

        assert len(requested) == 1
        collection, keys, kwargs = requested[0]
        assert collection == drs.COLLECTION_NAME
        # ``created_at`` הוא השדה ש-``collect_snapshot`` כותב. אינדקס TTL על
        # שדה שאיש אינו כותב פשוט לא מוחק כלום — וזה בדיוק המצב של
        # ``ttl_cleanup`` על ``service_metrics.timestamp`` היום.
        assert keys == [("created_at", 1)]
        assert kwargs["name"] == "ttl_cleanup"
        assert kwargs["expire_after_seconds"] == drs.TTL_SECONDS
        # בלי enforce, שינוי עתידי של TTL_SECONDS לא יוחל על אינדקס קיים.
        assert kwargs["enforce"] is True

    def test_snapshot_ttl_outlives_the_sources_it_compares_against(self, monkeypatch):
        """הסנאפשוט חייב לשרוד יותר מהמקורות, אחרת אין מול מה להשוות.

        ``slow_queries_log`` נשמר שבעה ימים, והזיכרון של דפוסים מוכרים הוא 30
        יום — TTL קצר מהם היה מוחק את הבסיס להשוואה לפני שהוא מספיק לשמש.
        """
        _import_manager(monkeypatch)
        import services.daily_report_service as drs
        from services.query_profiler_service import PersistentQueryProfilerService

        assert drs.TTL_SECONDS > PersistentQueryProfilerService.TTL_SECONDS
        assert drs.TTL_SECONDS > drs.KNOWN_ITEMS_WINDOW_DAYS * 24 * 3600

    def test_writer_and_index_agree_on_the_field_name(self, monkeypatch):
        """מקבע את החוזה בין הכותב לאינדקס, במקום להסתמך על כך שמישהו יזכור."""
        from datetime import datetime, timezone

        import services.daily_report_service as drs

        snapshot = drs.collect_snapshot(
            day_key="2026-09-06",
            day_start_utc=datetime(2026, 9, 6, 8, 0, tzinfo=timezone.utc),
            day_end_utc=datetime(2026, 9, 7, 8, 0, tzinfo=timezone.utc),
            deps=drs.ReportDeps(),
            now=datetime(2026, 9, 7, 8, 0, tzinfo=timezone.utc),
        )
        assert isinstance(snapshot["created_at"], datetime)


class TestJobRunsQueryIndex:
    def test_job_runs_gets_the_compound_index_its_queries_need(self, monkeypatch):
        """האינדקס שהוצהר ולא נוצר — עד עכשיו.

        משרת את ``JobTracker.get_job_history``, את ``/jobs failed`` ב-ChatOps,
        ואת בדיקת "job מתוזמן שלא רץ" שרצה כל 60 שניות.

        ‏``_create_indexes`` קוראת ל-``safe_create_index`` מתוך ``self``
        (ראו ההערה בגוף הפונקציה על תאימות לטסטים), ויוצאת מוקדם כש-``db``
        הוא ``None`` — ולכן הדמה כאן מספקת את שניהם.
        """
        dm = _import_manager(monkeypatch)
        requested: list[tuple] = []

        class _Recorder:
            db = object()

            @staticmethod
            def safe_create_index(collection, keys, **kwargs):
                requested.append((collection, keys, kwargs))

        dm.DatabaseManager._create_indexes(_Recorder())

        job_runs_indexes = {
            kwargs.get("name"): keys for collection, keys, kwargs in requested if collection == "job_runs"
        }
        assert "idx_job_runs_job_started" in job_runs_indexes, (
            "האינדקס מוצהר ב-database/job_runs_collection.py אך אותו קובץ אינו מיובא; "
            "הוא חייב להיווצר כאן"
        )
        assert job_runs_indexes["idx_job_runs_job_started"] == [("job_id", 1), ("started_at", -1)]
        # האינדקס הייחודי הקיים לא זז.
        assert "idx_job_runs_id" in job_runs_indexes

    def test_create_indexes_also_wires_the_snapshot_ttl(self, monkeypatch):
        """האינדקס לא שווה כלום אם ``_create_indexes`` לא קוראת לו בעלייה."""
        dm = _import_manager(monkeypatch)
        import services.daily_report_service as drs

        requested: list[tuple] = []

        class _Recorder:
            db = object()

            @staticmethod
            def safe_create_index(collection, keys, **kwargs):
                requested.append((collection, keys, kwargs))

        dm.DatabaseManager._create_indexes(_Recorder())
        assert any(collection == drs.COLLECTION_NAME for collection, _, _ in requested)
