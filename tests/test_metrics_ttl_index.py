"""אינדקסים ו-TTL לאוסף ``service_metrics`` (אישיו #3331).

שני כשלים נבדקים כאן. הראשון: לאוסף לא היה TTL קבוע בכלל — רק endpoint תחזוקה
ידני, שהגדיר 24 שעות בזמן שהדשבורד מציע טווח של 30 יום וה-warmup שואל 30 יום
אחורה בכל עליית תהליך. הרצה אחת שלו הייתה מרוקנת את שתי התצוגות בשקט. השני:
אותו endpoint יצר גם TTL על שדה בשם ``timestamp`` "לתאימות לאחור" — שדה שאף
כותב באוסף הזה אינו מייצר, כלומר אינדקס שעולה בכל כתיבה ולא מוחק דבר.
"""

from __future__ import annotations

import importlib
import sys
import types


def _import_manager(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "x")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/test")
    monkeypatch.setenv("DISABLE_DB", "1")
    import database.manager as dm

    return dm


def _requested(monkeypatch) -> list[tuple]:
    dm = _import_manager(monkeypatch)
    out: list[tuple] = []
    dm.DatabaseManager._create_metrics_indexes(
        object(), lambda collection, keys, **kwargs: out.append((collection, list(keys), kwargs))
    )
    return out


def test_metrics_ttl_index_created(monkeypatch):
    """הבדיקה המקורית: המסלול לא קורס בסביבה בלי מסד אמיתי."""
    monkeypatch.setenv("BOT_TOKEN", "x")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/test")
    monkeypatch.setenv("DISABLE_DB", "1")

    import database.manager as dm

    importlib.reload(dm)

    m = dm.DatabaseManager()

    assert hasattr(m, "collection") and hasattr(m, "large_files_collection")


class TestMetricsIndexes:
    def test_two_indexes_each_with_a_reader(self, monkeypatch):
        monkeypatch.delenv("METRICS_TTL_DAYS", raising=False)
        monkeypatch.delenv("METRICS_COLLECTION", raising=False)
        requested = _requested(monkeypatch)

        assert [kwargs.get("name") for _, _, kwargs in requested] == ["metrics_type_ts", "metrics_ttl"]
        assert {collection for collection, _, _ in requested} == {"service_metrics"}

    def test_ttl_sits_on_its_own_single_field_index(self, monkeypatch):
        """אינדקס מורכב אינו יכול לשאת TTL.

        *"TTL indexes are single-field indexes. Compound indexes do not support
        TTL and ignore the expireAfterSeconds option"*
        (מקור: https://www.mongodb.com/docs/manual/core/index-ttl/). מול mongod
        7.0.14 נמדד שהשרת אף דוחה יצירה כזו ב-``OperationFailure``. לכן TTL
        שנתלה על ``metrics_type_ts`` לא היה מוחק מסמך אחד.
        """
        monkeypatch.delenv("METRICS_TTL_DAYS", raising=False)
        requested = _requested(monkeypatch)

        compound_keys, compound_kwargs = requested[0][1], requested[0][2]
        ttl_keys, ttl_kwargs = requested[1][1], requested[1][2]

        assert compound_keys == [("ts", -1), ("type", 1)]
        assert compound_kwargs.get("expire_after_seconds") is None
        assert ttl_keys == [("ts", 1)]
        assert ttl_kwargs["expire_after_seconds"] == 30 * 24 * 3600
        # בלי enforce, שינוי של METRICS_TTL_DAYS היה מתנגש ונבלע כאזהרה
        assert ttl_kwargs["enforce"] is True

    def test_the_collection_name_is_not_hardcoded(self, monkeypatch):
        """``METRICS_COLLECTION`` מסיט את הכותב; אינדקס על שם קשיח היה מפספס."""
        monkeypatch.setenv("METRICS_COLLECTION", "metrics_v2")
        requested = _requested(monkeypatch)

        assert {collection for collection, _, _ in requested} == {"metrics_v2"}


class TestRetentionWindow:
    def _fresh(self, monkeypatch):
        sys.modules.pop("monitoring.metrics_storage", None)
        return importlib.import_module("monitoring.metrics_storage")

    def test_default_is_thirty_days(self, monkeypatch):
        monkeypatch.delenv("METRICS_TTL_DAYS", raising=False)
        ms = self._fresh(monkeypatch)
        assert ms.metrics_ttl_seconds() == 30 * 24 * 3600

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("METRICS_TTL_DAYS", "45")
        ms = self._fresh(monkeypatch)
        assert ms.metrics_ttl_seconds() == 45 * 24 * 3600

    def test_zero_does_not_become_delete_everything(self, monkeypatch):
        monkeypatch.setenv("METRICS_TTL_DAYS", "0")
        ms = self._fresh(monkeypatch)
        assert ms.metrics_ttl_seconds() == 24 * 3600


class TestTTLFieldMatchesTheWriter:
    def test_the_writer_writes_ts_and_never_timestamp(self, monkeypatch):
        """זו הבדיקה שמצדיקה את הסרת ה-TTL על ``timestamp``.

        היא עוברת דרך הכתיבה עצמה — ``enqueue_request_metric`` ואז ``flush`` —
        ולא דרך רשימת שדות שמישהו העתיק מהתיעוד.
        """
        for key in ("DISABLE_DB", "DISABLE_METRICS_WRITES"):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("METRICS_DB_ENABLED", "true")
        monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/codebot")
        monkeypatch.setenv("DATABASE_NAME", "code_keeper_bot")
        monkeypatch.delenv("METRICS_COLLECTION", raising=False)

        inserted: list[list[dict]] = []

        class _FakeCollection:
            def insert_many(self, items, ordered=False):
                inserted.append(list(items))
                return types.SimpleNamespace(inserted_ids=[1] * len(items))

        class _FakeDB:
            def __getitem__(self, name):
                return _FakeCollection()

        class _FakeClient:
            def __init__(self, *a, **k):
                self.admin = types.SimpleNamespace(command=lambda *a, **k: {"ok": 1})

            def __getitem__(self, name):
                return _FakeDB()

        monkeypatch.setitem(sys.modules, "pymongo", types.SimpleNamespace(MongoClient=_FakeClient))
        sys.modules.pop("monitoring.metrics_storage", None)
        ms = importlib.import_module("monitoring.metrics_storage")

        ms.enqueue_request_metric(200, 0.12, request_id="rid-1", extra={"method": "GET", "path": "/x"})
        ms.flush(force=True)

        docs = [doc for batch in inserted for doc in batch]
        assert docs, "שום מסמך לא נכתב — הבדיקה אינה בודקת כלום"
        for doc in docs:
            assert "ts" in doc
            assert "timestamp" not in doc, "TTL על timestamp לא ימחק כלום"

        # שם האינדקס נגזר מאותו מודול, כדי שיצירת האינדקס ו-endpoint התחזוקה
        # יגעו באותו אינדקס. שני שמות על אותו מפתח הם IndexOptionsConflict.
        assert ms.METRICS_TTL_INDEX_NAME == "metrics_ttl"


class _IndexInfoColl:
    def __init__(self, info):
        self._info = dict(info)
        self.dropped: list[str] = []

    def index_information(self):
        return dict(self._info)

    def drop_index(self, name):
        self.dropped.append(str(name))
        self._info.pop(str(name), None)


class TestStaleTTLIndexes:
    """לאוסף יש חלון שמירה אחד, ולכן אינדקס TTL אחד. כל השאר — שריד."""

    def test_both_kinds_of_leftover_are_returned(self):
        """שני שרידים, ורק אחד מהם נראה לעין.

        ``ttl_cleanup_ts`` על ``{ts: 1}`` **חוסם** את היצירה (IndexOptionsConflict
        נובע משיתוף מפתח, לא משיתוף שם), ולכן מרגישים בו מיד. ‏``ttl_cleanup`` על
        ``timestamp`` אינו חוסם ואינו מוחק — אין לשדה הזה כותב באוסף — ולכן אף
        אחד לא מרגיש בו, והוא היה נשאר לנצח ומתוחזק בכל כתיבה.
        """
        from monitoring.metrics_storage import stale_ttl_indexes

        coll = _IndexInfoColl(
            {
                "_id_": {"key": [("_id", 1)]},
                "metrics_type_ts": {"key": [("ts", -1), ("type", 1)]},
                "metrics_ttl": {"key": [("ts", 1)], "expireAfterSeconds": 2592000},
                "ttl_cleanup_ts": {"key": [("ts", 1)], "expireAfterSeconds": 86400},
                "ttl_cleanup": {"key": [("timestamp", 1)], "expireAfterSeconds": 86400},
            }
        )

        assert sorted(stale_ttl_indexes(coll, keep_name="metrics_ttl")) == ["ttl_cleanup", "ttl_cleanup_ts"]

    def test_the_index_we_own_is_kept_even_with_a_different_window(self):
        """שינוי חלון מטופל ב-``collMod``, לא בהפלה."""
        from monitoring.metrics_storage import stale_ttl_indexes

        coll = _IndexInfoColl({"metrics_ttl": {"key": [("ts", 1)], "expireAfterSeconds": 86400}})
        assert stale_ttl_indexes(coll, keep_name="metrics_ttl") == []

    def test_indexes_without_ttl_are_never_touched(self):
        """מפילים רק אינדקסי TTL — לא כל אינדקס שנוגע ב-``ts``."""
        from monitoring.metrics_storage import stale_ttl_indexes

        coll = _IndexInfoColl(
            {
                "plain_ts": {"key": [("ts", 1)]},
                "metrics_type_ts": {"key": [("ts", -1), ("type", 1)]},
            }
        )
        assert stale_ttl_indexes(coll, keep_name="metrics_ttl") == []


class TestStartupDropsLeftovers:
    def test_the_inert_timestamp_ttl_is_dropped_on_startup(self, monkeypatch):
        """ה-endpoint ידני, ושריד שמחכה להרצה ידנית מחכה לנצח."""
        dm = _import_manager(monkeypatch)
        monkeypatch.delenv("METRICS_COLLECTION", raising=False)
        coll = _IndexInfoColl(
            {
                "_id_": {"key": [("_id", 1)]},
                "ttl_cleanup": {"key": [("timestamp", 1)], "expireAfterSeconds": 86400},
            }
        )

        class _DB:
            def __getitem__(self, name):
                return coll

        fake_self = types.SimpleNamespace(db=_DB())
        dm.DatabaseManager._create_metrics_indexes(fake_self, lambda *a, **k: None)

        assert coll.dropped == ["ttl_cleanup"]

    def test_nothing_is_dropped_when_the_collection_is_clean(self, monkeypatch):
        dm = _import_manager(monkeypatch)
        monkeypatch.delenv("METRICS_COLLECTION", raising=False)
        coll = _IndexInfoColl(
            {
                "_id_": {"key": [("_id", 1)]},
                "metrics_type_ts": {"key": [("ts", -1), ("type", 1)]},
                "metrics_ttl": {"key": [("ts", 1)], "expireAfterSeconds": 2592000},
            }
        )

        class _DB:
            def __getitem__(self, name):
                return coll

        dm.DatabaseManager._create_metrics_indexes(types.SimpleNamespace(db=_DB()), lambda *a, **k: None)

        assert coll.dropped == []
