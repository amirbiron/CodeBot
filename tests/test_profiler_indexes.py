"""אינדקסים ו-TTL לאוסף ``slow_queries_log``.

התיעוד (``docs/observability/query-performance-profiler.rst``) הבטיח שלושה אינדקסים,
ואישיו #3312 טען ש-``_create_profiler_indexes`` כבר קיימת ב-``database/manager.py`` —
אבל בפועל לא היה בקוד שום דבר שיוצר אותם, ובפרודקשן היה אינדקס אחד בלבד (``_id_``)
על 2,012 מסמכים. הבדיקות כאן מקבעות את מה שנוצר.

הערה על ENV: משתני הסביבה נקבעים לפני הייבוא של ``database.manager``, באותו דפוס
כמו ``tests/test_database_manager_profiler_independent.py``.
"""

from __future__ import annotations

import pytest


def _import_manager(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "x")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/db")
    monkeypatch.setenv("DISABLE_DB", "1")
    import database.manager as dm

    return dm


class _Collection:
    """דמה של אוסף. ``create_index`` מדמה את מונגו: התנגשות שם -> קוד 85."""

    def __init__(self, existing=None):
        self.created: list[tuple] = []
        self.dropped: list[str] = []
        self.existing = list(existing or [])

    def create_index(self, keys, **kwargs):
        for index in self.existing:
            if index.get("name") == kwargs.get("name"):
                error = Exception("IndexOptionsConflict")
                error.code = 85
                raise error
        self.created.append((keys, kwargs))
        return kwargs.get("name")

    def list_indexes(self):
        return list(self.existing)

    def drop_index(self, name):
        self.dropped.append(name)
        self.existing = [i for i in self.existing if i.get("name") != name]


class _DB:
    def __init__(self, collection):
        self._collection = collection

    def __getitem__(self, name):
        return self._collection


class _Manager:
    def __init__(self, collection):
        self.db = _DB(collection)


class TestProfilerIndexDefinitions:
    def test_creates_exactly_the_three_documented_indexes(self, monkeypatch):
        dm = _import_manager(monkeypatch)
        requested: list[tuple] = []

        dm.DatabaseManager._create_profiler_indexes(
            object(), lambda collection, keys, **kwargs: requested.append((collection, keys, kwargs))
        )

        assert [kwargs["name"] for _, _, kwargs in requested] == [
            "ttl_cleanup",
            "collection_timestamp",
            "query_pattern",
        ]
        assert {collection for collection, _, _ in requested} == {"slow_queries_log"}

        ttl_collection, ttl_keys, ttl_kwargs = requested[0]
        # שדה הזמן חייב להיות זה שהכותב באמת כותב (_persist_record)
        assert ttl_keys == [("timestamp", 1)]
        assert ttl_kwargs["expire_after_seconds"] == 7 * 24 * 60 * 60

    def test_ttl_matches_the_maintenance_endpoint(self, monkeypatch):
        """מקור אמת יחיד ל-retention.

        ``/api/debug/maintenance_cleanup`` יוצר אינדקס בשם ``ttl_cleanup`` על
        ``timestamp`` עם 604800 שניות. אם הערכים יתפצלו, כל הרצת תחזוקה תפיל
        ותיצור מחדש את האינדקס.
        """
        from services.query_profiler_service import PersistentQueryProfilerService

        assert PersistentQueryProfilerService.TTL_SECONDS == 604800
        assert PersistentQueryProfilerService.COLLECTION_NAME == "slow_queries_log"


class TestSafeCreateIndexTTL:
    def test_expire_after_seconds_reaches_pymongo(self, monkeypatch):
        """שם הפרמטר ב-pymongo הוא ``expireAfterSeconds``.

        מקור: pymongo/synchronous/collection.py, ``create_index`` (גרסה 4.15.3).
        """
        dm = _import_manager(monkeypatch)
        collection = _Collection()

        dm.DatabaseManager.safe_create_index(
            _Manager(collection),
            "slow_queries_log",
            [("timestamp", 1)],
            name="ttl_cleanup",
            expire_after_seconds=604800,
        )

        assert collection.created, "לא נוצר אינדקס"
        assert collection.created[0][1]["expireAfterSeconds"] == 604800

    def test_an_index_without_ttl_is_not_mistaken_for_the_ttl_index(self, monkeypatch):
        """זו הגדר שמונעת כשל שקט.

        בלי השוואת ``expireAfterSeconds`` ב-``_index_matches``, אינדקס קיים על
        ``timestamp`` **בלי** TTL היה נחשב "כבר קיים", ה-TTL לא היה נוצר לעולם,
        ושום מסמך לא היה נמחק — בלי שגיאה אחת. אומת במוטציה: הסרת ההשוואה
        מחזירה את הכשל.
        """
        dm = _import_manager(monkeypatch)
        events: list[str] = []
        monkeypatch.setattr(dm, "emit_event", lambda event, **kwargs: events.append(event))

        collection = _Collection(existing=[{"name": "ttl_cleanup", "key": {"timestamp": 1}}])
        dm.DatabaseManager.safe_create_index(
            _Manager(collection),
            "slow_queries_log",
            [("timestamp", 1)],
            name="ttl_cleanup",
            expire_after_seconds=604800,
        )

        assert "db_index_exists" not in events, (
            "אינדקס בלי TTL נחשב בטעות זהה לאינדקס עם TTL — הכשל השקט חזר"
        )

    def test_a_different_retention_is_not_swallowed(self, monkeypatch):
        dm = _import_manager(monkeypatch)
        events: list[str] = []
        monkeypatch.setattr(dm, "emit_event", lambda event, **kwargs: events.append(event))

        collection = _Collection(
            existing=[{"name": "ttl_cleanup", "key": {"timestamp": 1}, "expireAfterSeconds": 86400}]
        )
        dm.DatabaseManager.safe_create_index(
            _Manager(collection),
            "slow_queries_log",
            [("timestamp", 1)],
            name="ttl_cleanup",
            expire_after_seconds=604800,
        )

        assert "db_index_exists" not in events

    def test_an_identical_ttl_index_is_recognised(self, monkeypatch):
        dm = _import_manager(monkeypatch)
        events: list[str] = []
        monkeypatch.setattr(dm, "emit_event", lambda event, **kwargs: events.append(event))

        collection = _Collection(
            existing=[{"name": "ttl_cleanup", "key": {"timestamp": 1}, "expireAfterSeconds": 604800}]
        )
        dm.DatabaseManager.safe_create_index(
            _Manager(collection),
            "slow_queries_log",
            [("timestamp", 1)],
            name="ttl_cleanup",
            expire_after_seconds=604800,
        )

        assert "db_index_exists" in events
        assert collection.dropped == [], "אין סיבה להפיל אינדקס זהה"

    def test_enforce_recreates_with_the_new_retention(self, monkeypatch):
        dm = _import_manager(monkeypatch)
        collection = _Collection(
            existing=[{"name": "ttl_cleanup", "key": {"timestamp": 1}, "expireAfterSeconds": 86400}]
        )

        dm.DatabaseManager.safe_create_index(
            _Manager(collection),
            "slow_queries_log",
            [("timestamp", 1)],
            name="ttl_cleanup",
            expire_after_seconds=604800,
            enforce=True,
        )

        assert collection.dropped == ["ttl_cleanup"]
        assert collection.created[-1][1]["expireAfterSeconds"] == 604800


class TestRegisteredJobPointsAtRealCode:
    def test_the_profiler_indexes_job_names_a_function_that_exists(self, monkeypatch):
        """הג'וב הרשום הצביע על ``_profiler_indexes_job`` שלא היה קיים בשום מקום."""
        dm = _import_manager(monkeypatch)
        import services.register_jobs as register_jobs

        register_jobs.register_all_jobs()
        from services.job_registry import JobRegistry

        job = JobRegistry().get("profiler_indexes")
        assert job is not None
        assert hasattr(dm.DatabaseManager, job.callback_name), (
            f"הג'וב מצביע על {job.callback_name!r} שאינו קיים על DatabaseManager"
        )
