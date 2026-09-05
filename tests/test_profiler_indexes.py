"""אינדקסים ו-TTL לאוסף ``slow_queries_log``.

התיעוד (``docs/observability/query-performance-profiler.rst``) הבטיח שלושה אינדקסים,
ואישיו #3312 טען ש-``_create_profiler_indexes`` כבר קיימת ב-``database/manager.py`` —
אבל בפועל לא היה בקוד שום דבר שיוצר אותם, ובפרודקשן היה אינדקס אחד בלבד (``_id_``)
על 2,012 מסמכים. הבדיקות כאן מקבעות את מה שנוצר.

הערה על ENV: משתני הסביבה נקבעים לפני הייבוא של ``database.manager``, באותו דפוס
כמו ``tests/test_database_manager_profiler_independent.py``.
"""

from __future__ import annotations

import types

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
    def test_creates_exactly_the_three_indexes_the_queries_need(self, monkeypatch):
        dm = _import_manager(monkeypatch)
        requested: list[tuple] = []

        dm.DatabaseManager._create_profiler_indexes(
            object(), lambda collection, keys, **kwargs: requested.append((collection, keys, kwargs))
        )

        assert [kwargs["name"] for _, _, kwargs in requested] == [
            "ttl_cleanup",
            "slow_queries_duration",
            "slow_queries_coll_dur",
        ]
        assert {collection for collection, _, _ in requested} == {"slow_queries_log"}

        _, ttl_keys, ttl_kwargs = requested[0]
        # שדה הזמן חייב להיות זה שהכותב באמת כותב (_persist_record)
        assert ttl_keys == [("timestamp", 1)]
        assert ttl_kwargs["expire_after_seconds"] == 7 * 24 * 60 * 60
        # בלי enforce, שינוי עתידי של TTL_SECONDS לא יוחל על אינדקס קיים —
        # מונגו יחזיר IndexOptionsConflict וה-retention הישן יישאר בשקט.
        assert ttl_kwargs["enforce"] is True

        # שני האינדקסים האחרים משרתים את המיון של get_slow_queries, שהוא תמיד
        # לפי execution_time_ms יורד. בלעדיהם מונגו ממיין בזיכרון את כל חלון ה-TTL.
        _, duration_keys, _ = requested[1]
        _, compound_keys, _ = requested[2]
        assert duration_keys == [("execution_time_ms", -1)]
        assert compound_keys == [("collection", 1), ("execution_time_ms", -1)]

    def test_the_constants_exist_on_the_service(self):
        """שני הערכים שכל שאר הקוד קורא משם."""
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


class _RecordingCollection:
    """אוסף שרושם כל פעולה, כדי שאפשר יהיה לשאול "האם נגעת ב-DB?"."""

    def __init__(self) -> None:
        self.delete_calls = 0
        self.dropped: list = []
        self.created: list = []
        self._info: dict = {}

    def delete_many(self, _query):
        self.delete_calls += 1
        return types.SimpleNamespace(deleted_count=0)

    def index_information(self):
        return dict(self._info)

    def drop_index(self, name):
        self.dropped.append(str(name))
        self._info.pop(str(name), None)

    def create_index(self, keys, **kwargs):
        self.created.append({"keys": list(keys), **kwargs})
        name = str(kwargs.get("name") or "idx")
        # ``index_information`` של pymongo מחזירה גם את האפשרויות, לא רק את
        # המפתחות. בלי זה הדמה מדווחת על אינדקס TTL כאילו אין לו retention,
        # וקוד שמשווה מול הקיים היה מפיל ויוצר אותו מחדש בלי סוף.
        info = {"key": list(keys)}
        if "expireAfterSeconds" in kwargs:
            info["expireAfterSeconds"] = kwargs["expireAfterSeconds"]
        if kwargs.get("unique"):
            info["unique"] = True
        self._info[name] = info
        return name


class _RecordingDB:
    """דמה של ``Database`` שיוצרת אוספים לפי דרישה ורושמת מה נעשה בהם.

    יוצרת אוסף בכל שם שמבקשים — וזה מה שמאפשר לבדוק שקוד התחזוקה ניגש לאוסף
    ששמו נקבע ב-``COLLECTION_NAME`` ולא לשם קשיח. תומכת בשתי צורות הגישה,
    כי ב-pymongo 4.15.3 ``__getitem__`` ו-``__getattr__`` שקולות (אומת מול
    קוד המקור המותקן).
    """

    def __init__(self) -> None:
        object.__setattr__(self, "collections", {})

    def __getitem__(self, name):
        return self.collections.setdefault(str(name), _RecordingCollection())

    def __getattr__(self, name):
        if str(name).startswith("_") or name == "collections":
            raise AttributeError(name)
        return self[name]

    def touched(self) -> dict:
        """אילו אוספים נמחקו או הופל בהם אינדקס."""
        return {
            name: (coll.delete_calls, list(coll.dropped))
            for name, coll in self.collections.items()
            if coll.delete_calls or coll.dropped
        }


class TestMaintenanceEndpointBehaviour:
    """בדיקות התנהגות ל-``/api/debug/maintenance_cleanup`` ב-WebApp.

    גרסה קודמת של הבדיקות האלה קראה את קובץ המקור וחיפשה סדר של מחרוזות. זה
    נשבר מהוצאת קוד לפונקציית עזר, מהוספת הערה, או מהרצה שאינה משורש הריפו —
    כלומר אזעקות שווא על קוד תקין. כאן נבדקת ההתנהגות: מריצים את ה-endpoint
    ושואלים את הדמה מה קרה לה.
    """

    TOKEN = "test-maintenance-token"

    def _client(self, monkeypatch):
        import webapp.app as webapp_app

        monkeypatch.setenv("DB_HEALTH_TOKEN", self.TOKEN)
        db = _RecordingDB()
        monkeypatch.setattr(webapp_app, "get_db", lambda: db, raising=True)
        return webapp_app, db

    def test_a_failure_before_the_db_returns_json_and_touches_nothing(self, monkeypatch):
        """כשל בשליפת הגדרות הפרופיילר חייב לעצור לפני כל פעולה הרסנית.

        ושתי דרישות, לא אחת: גם שה-DB לא ייגע, וגם שהתשובה תישאר JSON. כשהשליפה
        ישבה מחוץ ל-``try`` של הראוט, Flask החזיר דף HTML גנרי — וכל לקוח שמצפה
        לחוזה ה-JSON של ה-endpoint נשבר בלי הסבר.
        """
        webapp_app, db = self._client(monkeypatch)

        def _boom():
            raise ImportError("services.query_profiler_service is unavailable")

        monkeypatch.setattr(webapp_app, "_profiler_persistence", _boom, raising=True)

        with webapp_app.app.test_client() as client:
            resp = client.get(f"/api/debug/maintenance_cleanup?token={self.TOKEN}")

        assert resp.status_code == 500
        payload = resp.get_json()
        assert payload is not None, "התשובה אינה JSON — חוזה ה-endpoint נשבר"
        assert payload.get("ok") is False
        assert db.touched() == {}, f"ה-DB נגע למרות הכשל: {db.touched()}"

    def test_the_ttl_it_installs_is_the_services_own(self, monkeypatch):
        """ה-retention שנכתב למונגו הוא זה של השירות, לא מספר קשיח מקומי."""
        from services.query_profiler_service import PersistentQueryProfilerService

        webapp_app, db = self._client(monkeypatch)

        with webapp_app.app.test_client() as client:
            resp = client.get(f"/api/debug/maintenance_cleanup?token={self.TOKEN}")

        assert resp.status_code == 200, resp.get_data(as_text=True)[:400]
        coll = db.collections[PersistentQueryProfilerService.COLLECTION_NAME]
        ttl_indexes = [i for i in coll.created if i.get("name") == "ttl_cleanup"]
        assert ttl_indexes, f"לא נוצר אינדקס ttl_cleanup. נוצרו: {coll.created}"
        assert ttl_indexes[-1]["expireAfterSeconds"] == PersistentQueryProfilerService.TTL_SECONDS

    def test_it_cleans_the_collection_the_service_names(self, monkeypatch):
        """הוכחה שהבטחת ה-Single Source of Truth אמיתית ולא רק כתובה בתיעוד.

        שם האוסף היה קשיח כאן (``db.slow_queries_log``). שינוי של ``COLLECTION_NAME``
        היה מותיר את התחזוקה מנקה את האוסף הישן, בזמן שהחדש מתנפח בלי בקרה.
        """
        from services.query_profiler_service import PersistentQueryProfilerService

        monkeypatch.setattr(
            PersistentQueryProfilerService, "COLLECTION_NAME", "renamed_profiler_log", raising=True
        )
        webapp_app, db = self._client(monkeypatch)

        with webapp_app.app.test_client() as client:
            resp = client.get(f"/api/debug/maintenance_cleanup?token={self.TOKEN}")

        assert resp.status_code == 200, resp.get_data(as_text=True)[:400]
        assert db.collections["renamed_profiler_log"].delete_calls == 1
        assert "slow_queries_log" not in db.collections, (
            "התחזוקה ניקתה את האוסף הישן — שם האוסף עדיין קשיח איפשהו"
        )


class TestRecursionGuard:
    """המגן שמונע מהפרופיילר להקליט את הכתיבה של עצמו.

    בלעדיו: הכתיבה ל-``slow_queries_log`` היא פקודת מונגו, שמפעילה את
    ה-``CommandListener``, שכותב שוב. רקורסיה.
    """

    def test_it_names_the_collection_the_service_names(self, monkeypatch):
        dm = _import_manager(monkeypatch)
        from services.query_profiler_service import PersistentQueryProfilerService

        monkeypatch.setattr(
            PersistentQueryProfilerService, "COLLECTION_NAME", "renamed_profiler_log", raising=True
        )
        guard = dm.DatabaseManager.profiler_guard_collections(types.SimpleNamespace())
        assert "renamed_profiler_log" in guard
        assert "system.profile" in guard

    def test_a_failed_import_is_not_cached(self, monkeypatch):
        """הכשל השקט: קבוצה חלקית שנשמרת לתמיד.

        ``_get_profiler_service`` מנסה לייבא מחדש בכל קריאה, אז כשל חולף בעליית
        התהליך (ייבוא מעגלי, למשל) מייצר מאוחר יותר פרופיילר **חי**. אם המגן
        הטמין את הקבוצה החלקית מהניסיון הראשון, הוא לא יכיר את האוסף של
        הפרופיילר — וזו בדיוק הרקורסיה שהוא קיים כדי למנוע.
        """
        dm = _import_manager(monkeypatch)
        import builtins

        manager = types.SimpleNamespace()
        real_import = builtins.__import__
        failing = {"on": True}

        def _maybe_fail(name, *args, **kwargs):
            if failing["on"] and name == "services.query_profiler_service":
                raise ImportError("circular import during startup")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _maybe_fail)

        during_failure = dm.DatabaseManager.profiler_guard_collections(manager)
        assert during_failure == frozenset({"system.profile"})
        assert not hasattr(manager, "_profiler_guard_cache"), (
            "קבוצה חלקית הוטמנה — הקריאה הבאה לא תנסה שוב"
        )

        failing["on"] = False
        after_recovery = dm.DatabaseManager.profiler_guard_collections(manager)
        from services.query_profiler_service import PersistentQueryProfilerService

        assert PersistentQueryProfilerService.COLLECTION_NAME in after_recovery, (
            "אחרי שהייבוא הסתדר המגן עדיין לא מכיר את האוסף של הפרופיילר"
        )

    def test_a_successful_result_is_cached(self, monkeypatch):
        """רץ על כל פקודה איטית, אז ייבוא חוזר בכל קריאה אינו מקובל."""
        dm = _import_manager(monkeypatch)
        manager = types.SimpleNamespace()

        first = dm.DatabaseManager.profiler_guard_collections(manager)
        assert getattr(manager, "_profiler_guard_cache", None) == first
        assert dm.DatabaseManager.profiler_guard_collections(manager) is first


async def _call_webserver_cleanup(ws, monkeypatch, db):
    """מריצה את ``/api/debug/maintenance_cleanup`` של שרת ה-aiohttp ומחזירה (status, payload)."""
    import aiohttp
    from aiohttp import web

    monkeypatch.setattr(ws, "DB_HEALTH_TOKEN", "test-db-health-token", raising=True)
    import services.db_provider as dbp

    monkeypatch.setattr(dbp, "get_db", lambda: db, raising=True)

    runner = web.AppRunner(ws.create_app())
    await runner.setup()
    site = web.TCPSite(runner, host="127.0.0.1", port=0)
    await site.start()
    try:
        port = list(site._server.sockets)[0].getsockname()[1]
        headers = {"Authorization": "Bearer test-db-health-token"}
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://127.0.0.1:{port}/api/debug/maintenance_cleanup", headers=headers
            ) as resp:
                return resp.status, await resp.json()
    finally:
        await runner.cleanup()


class TestWebserverMaintenanceEndpointBehaviour:
    """אותן בדיקות בדיוק, על מסלול התחזוקה השני.

    ``webapp/app.py`` ו-``services/webserver.py`` מממשים את אותו endpoint פעמיים.
    שני המימושים חייבים לקרוא את ``TTL_SECONDS`` ואת ``COLLECTION_NAME`` מאותו
    מקום; אם אחד מהם יתפצל — התחזוקה תפיל ותיצור מחדש את האינדקס, או תנקה אוסף
    ישן — ובלי הבדיקות האלה אף אחד לא יבחין. שתי המחלקות יושבות באותו קובץ
    בכוונה: הן בודקות את אותה הבטחה.
    """

    @pytest.mark.asyncio
    async def test_the_ttl_it_installs_is_the_services_own(self, monkeypatch):
        import services.webserver as ws
        from services.query_profiler_service import PersistentQueryProfilerService

        db = _RecordingDB()
        status, payload = await _call_webserver_cleanup(ws, monkeypatch, db)

        assert status == 200, payload
        coll = db.collections[PersistentQueryProfilerService.COLLECTION_NAME]
        ttl_indexes = [i for i in coll.created if i.get("name") == "ttl_cleanup"]
        assert ttl_indexes, f"לא נוצר אינדקס ttl_cleanup. נוצרו: {coll.created}"
        assert ttl_indexes[-1]["expireAfterSeconds"] == PersistentQueryProfilerService.TTL_SECONDS

    @pytest.mark.asyncio
    async def test_it_cleans_the_collection_the_service_names(self, monkeypatch):
        import services.webserver as ws
        from services.query_profiler_service import PersistentQueryProfilerService

        monkeypatch.setattr(
            PersistentQueryProfilerService, "COLLECTION_NAME", "renamed_profiler_log", raising=True
        )
        db = _RecordingDB()
        status, payload = await _call_webserver_cleanup(ws, monkeypatch, db)

        assert status == 200, payload
        assert db.collections["renamed_profiler_log"].delete_calls == 1
        assert "slow_queries_log" not in db.collections, (
            "התחזוקה ניקתה את האוסף הישן — שם האוסף עדיין קשיח איפשהו"
        )
