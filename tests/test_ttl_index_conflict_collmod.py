"""שינוי חלון TTL של אינדקס קיים — ``safe_create_index`` מול ``collMod``.

בלי המסלול הזה, הוספת TTL לאוסף שכבר יש בו אינדקס TTL **בשם אחר** על אותו
מפתח פשוט לא חלה: מונגו מחזיר ``IndexOptionsConflict``, מסלול ה-``enforce``
מפיל לפי **שם** ולכן לא נוגע באינדקס החוסם, והכשל נרשם כאזהרה אחת ונשכח. זה
בדיוק המצב של ``service_metrics`` באישיו #3331, שבו יושבים בפרודקשן
``metrics_ttl`` מגרסה אחת ו-``ttl_cleanup_ts`` מגרסה אחרת.

המנגנון הנכון מתועד: *"You cannot use createIndex() to change the value of
expireAfterSeconds of an existing index. Instead, use the collMod database
command"* — https://www.mongodb.com/docs/manual/core/index-ttl/, וצורת הפקודה
ב-https://www.mongodb.com/docs/manual/reference/command/collMod/.
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
    """דמה שמתנגשת לפי **מפתח**, כמו מונגו — לא לפי שם."""

    def __init__(self, indexes=None):
        self.indexes = dict(indexes or {})
        self.dropped: list[str] = []
        self.created: list[tuple] = []

    def list_indexes(self):
        out = []
        for name, meta in self.indexes.items():
            row = {"name": name, "key": dict(meta["key"])}
            if meta.get("expireAfterSeconds") is not None:
                row["expireAfterSeconds"] = meta["expireAfterSeconds"]
            out.append(row)
        return out

    def create_index(self, keys, **kwargs):
        want = [(str(k), int(v)) for k, v in list(keys)]
        for name, meta in self.indexes.items():
            if meta["key"] != want:
                continue
            if name != kwargs.get("name") or meta.get("expireAfterSeconds") != kwargs.get("expireAfterSeconds"):
                error = Exception("IndexOptionsConflict")
                error.code = 85
                raise error
        self.created.append((want, kwargs))
        meta = {"key": want}
        if kwargs.get("expireAfterSeconds") is not None:
            meta["expireAfterSeconds"] = kwargs["expireAfterSeconds"]
        self.indexes[str(kwargs.get("name") or "idx")] = meta
        return kwargs.get("name")

    def drop_index(self, name):
        if name not in self.indexes:
            raise Exception("index not found")
        self.dropped.append(name)
        self.indexes.pop(name, None)


class _DB:
    """``collMod`` שמאתר את האינדקס לפי ``keyPattern`` ומעדכן את החלון."""

    def __init__(self, collection, *, applies: bool = True, raises: bool = False):
        self._collection = collection
        self._applies = applies
        self._raises = raises
        self.commands: list[dict] = []

    def __getitem__(self, name):
        return self._collection

    def command(self, cmd):
        self.commands.append(cmd)
        if self._raises:
            raise Exception("not authorized on db to execute command collMod")
        if not self._applies:
            # השרת ענה ok, והאינדקס לא זז. זה המצב שאסור לדווח עליו כהצלחה.
            return {"ok": 1}
        want = [(str(k), int(v)) for k, v in dict(cmd["index"]["keyPattern"]).items()]
        for meta in self._collection.indexes.values():
            if meta["key"] == want:
                meta["expireAfterSeconds"] = cmd["index"]["expireAfterSeconds"]
                break
        return {"ok": 1, "expireAfterSeconds_new": cmd["index"]["expireAfterSeconds"]}


class _Manager:
    def __init__(self, db):
        self.db = db


@pytest.fixture
def events(monkeypatch):
    def _collect(dm):
        bucket: list[tuple] = []
        monkeypatch.setattr(dm, "emit_event", lambda event, **kwargs: bucket.append((event, kwargs)))
        return bucket

    return _collect


class TestTTLChangeOnExistingIndex:
    def test_an_index_under_another_name_is_updated_and_kept(self, monkeypatch, events):
        """המקרה שהיה שקט: TTL של 24 שעות בשם ``ttl_cleanup_ts``, ביקשנו 30 יום.

        לפני התיקון: ``create_index`` מתנגש, ``drop_index("metrics_ttl")`` נכשל
        כי אין אינדקס בשם הזה, והיצירה החוזרת מתנגשת שוב — האוסף נשאר עם 24
        שעות, ובלוג יש אזהרה אחת.
        """
        dm = _import_manager(monkeypatch)
        bucket = events(dm)
        collection = _Collection({"ttl_cleanup_ts": {"key": [("ts", 1)], "expireAfterSeconds": 86400}})
        db = _DB(collection)

        dm.DatabaseManager.safe_create_index(
            _Manager(db),
            "service_metrics",
            [("ts", 1)],
            name="metrics_ttl",
            expire_after_seconds=2592000,
            enforce=True,
        )

        assert collection.indexes["ttl_cleanup_ts"]["expireAfterSeconds"] == 2592000
        assert collection.dropped == [], "לא צריך להפיל אינדקס כדי לשנות חלון TTL"
        assert db.commands and db.commands[0]["collMod"] == "service_metrics"
        assert [name for name, _ in bucket] == ["db_index_ttl_updated"]

    def test_a_command_that_did_not_apply_is_not_reported_as_success(self, monkeypatch, events):
        """ערך ההחזרה של ``collMod`` אינו ראיה.

        ‏``expireAfterSeconds_old`` מוחזר רק *"if the index had a value before"*,
        ולכן תשובה בלי השדות האלה אינה מעידה על כלום. מי שקובע הוא מצב האינדקס
        אחרי הפקודה — וכאן הוא לא זז, אז חייבת לצאת שגיאה.
        """
        dm = _import_manager(monkeypatch)
        bucket = events(dm)
        collection = _Collection({"ttl_cleanup_ts": {"key": [("ts", 1)], "expireAfterSeconds": 86400}})

        dm.DatabaseManager.safe_create_index(
            _Manager(_DB(collection, applies=False)),
            "service_metrics",
            [("ts", 1)],
            name="metrics_ttl",
            expire_after_seconds=2592000,
            enforce=True,
        )

        names = [name for name, _ in bucket]
        assert "db_index_ttl_collmod_unverified" in names
        assert "db_index_ttl_updated" not in names, "פקודה שלא החילה כלום דווחה כהצלחה"
        severities = {name: kwargs.get("severity") for name, kwargs in bucket}
        assert severities["db_index_ttl_collmod_unverified"] == "error"
        # ומכיוון שהתבקשה אכיפה, המסלול נופל להפלה+יצירה ולא מוותר על ה-TTL
        assert collection.indexes["metrics_ttl"]["expireAfterSeconds"] == 2592000

    def test_a_refused_command_falls_through_to_enforce(self, monkeypatch, events):
        """אין הרשאה ל-``collMod`` — לא נשארים בלי TTL בשקט."""
        dm = _import_manager(monkeypatch)
        bucket = events(dm)
        collection = _Collection({"metrics_ttl": {"key": [("ts", 1)], "expireAfterSeconds": 86400}})

        dm.DatabaseManager.safe_create_index(
            _Manager(_DB(collection, raises=True)),
            "service_metrics",
            [("ts", 1)],
            name="metrics_ttl",
            expire_after_seconds=2592000,
            enforce=True,
        )

        names = [name for name, _ in bucket]
        assert "db_index_ttl_collmod_error" in names
        assert collection.dropped == ["metrics_ttl"]
        assert collection.indexes["metrics_ttl"]["expireAfterSeconds"] == 2592000

    def test_a_plain_index_on_the_same_key_is_converted_to_ttl(self, monkeypatch, events):
        """אינדקס רגיל בשם אחר על אותו מפתח חוסם את ה-TTL לצמיתות.

        נמדד מול mongod 7.0.14: יצירת TTL על ``{ts: 1}`` כשקיים שם אינדקס רגיל
        בשם אחר נדחית בקוד 85, ו-``collMod`` על אותו ``keyPattern`` **כן** ממיר
        אותו ל-TTL (``{'expireAfterSeconds_new': 100, 'ok': 1.0}``, ו-
        ``list_indexes`` מאשר). התיעוד אינו אומר זאת במפורש, ולכן זו מדידה.
        """
        dm = _import_manager(monkeypatch)
        bucket = events(dm)
        collection = _Collection({"plain_ts": {"key": [("ts", 1)]}})
        db = _DB(collection)

        dm.DatabaseManager.safe_create_index(
            _Manager(db),
            "service_metrics",
            [("ts", 1)],
            name="metrics_ttl",
            expire_after_seconds=2592000,
            enforce=True,
        )

        assert collection.indexes["plain_ts"].get("expireAfterSeconds") == 2592000
        assert collection.dropped == []
        assert [name for name, _ in bucket] == ["db_index_ttl_updated"]

    def test_enforce_drops_the_blocking_index_and_not_the_requested_name(self, monkeypatch, events):
        """כש-``collMod`` נכשל, ההפלה חייבת להיות של מי שבאמת חוסם.

        הפלה לפי השם שביקשנו נכשלת ב-"index not found", היצירה החוזרת מתנגשת
        שוב, והתוצאה היא בדיוק הלולאה השקטה שהמסלול הזה קיים כדי לשבור.
        """
        dm = _import_manager(monkeypatch)
        bucket = events(dm)
        collection = _Collection({"ttl_cleanup_ts": {"key": [("ts", 1)], "expireAfterSeconds": 86400}})

        dm.DatabaseManager.safe_create_index(
            _Manager(_DB(collection, raises=True)),
            "service_metrics",
            [("ts", 1)],
            name="metrics_ttl",
            expire_after_seconds=2592000,
            enforce=True,
        )

        assert collection.dropped == ["ttl_cleanup_ts"]
        assert collection.indexes["metrics_ttl"]["expireAfterSeconds"] == 2592000
        assert "db_index_created" in [name for name, _ in bucket]

    def test_an_identical_ttl_index_is_left_alone(self, monkeypatch, events):
        """הרצה חוזרת בעלייה של התהליך לא מפילה ולא בונה מחדש כלום."""
        dm = _import_manager(monkeypatch)
        bucket = events(dm)
        collection = _Collection({"metrics_ttl": {"key": [("ts", 1)], "expireAfterSeconds": 2592000}})
        db = _DB(collection)

        dm.DatabaseManager.safe_create_index(
            _Manager(db),
            "service_metrics",
            [("ts", 1)],
            name="metrics_ttl",
            expire_after_seconds=2592000,
            enforce=True,
        )

        assert db.commands == []
        assert collection.dropped == []
        assert [name for name, _ in bucket] == ["db_index_created"]


class TestEnforceGatesTheDestructiveChange:
    """שינוי חלון TTL והמרת אינדקס רגיל ל-TTL מוחקים מסמכים.

    ``enforce`` הוא הדגל שמגדר ב-``safe_create_index`` את הפעולות ההרסניות
    (drop+create). אם מסלול ה-``collMod`` היה רץ בלעדיו, הקריאה ההרסנית ביותר
    בפונקציה — זו שמתחילה למחוק מסמכים שעד עכשיו לא נמחקו — הייתה היחידה שהדגל
    אינו שומר עליה.
    """

    def test_without_enforce_a_plain_index_is_not_turned_into_a_ttl(self, monkeypatch, events):
        dm = _import_manager(monkeypatch)
        bucket = events(dm)
        collection = _Collection({"plain_ts": {"key": [("ts", 1)]}})
        db = _DB(collection)

        dm.DatabaseManager.safe_create_index(
            _Manager(db),
            "service_metrics",
            [("ts", 1)],
            name="metrics_ttl",
            expire_after_seconds=2592000,
        )

        assert db.commands == [], "collMod רץ בלי enforce"
        assert collection.indexes["plain_ts"].get("expireAfterSeconds") is None
        assert [name for name, _ in bucket] == ["db_create_index_conflict"]

    def test_without_enforce_an_existing_window_is_left_alone(self, monkeypatch, events):
        dm = _import_manager(monkeypatch)
        events(dm)
        collection = _Collection({"metrics_ttl": {"key": [("ts", 1)], "expireAfterSeconds": 86400}})
        db = _DB(collection)

        dm.DatabaseManager.safe_create_index(
            _Manager(db),
            "service_metrics",
            [("ts", 1)],
            name="metrics_ttl",
            expire_after_seconds=2592000,
        )

        assert db.commands == []
        assert collection.indexes["metrics_ttl"]["expireAfterSeconds"] == 86400


class TestReturnValue:
    """``safe_create_index`` אינה זורקת, ולכן ערך ההחזרה הוא ערוץ הכשל היחיד."""

    def test_true_when_the_index_ends_up_in_the_requested_state(self, monkeypatch, events):
        dm = _import_manager(monkeypatch)
        events(dm)
        collection = _Collection()

        assert dm.DatabaseManager.safe_create_index(
            _Manager(_DB(collection)), "service_metrics", [("ts", 1)],
            name="metrics_ttl", expire_after_seconds=2592000, enforce=True,
        ) is True

    def test_false_when_the_conflict_could_not_be_resolved(self, monkeypatch, events):
        """בלי הערך הזה, קורא שהפיל אינדקס לפני הקריאה אינו יכול לדעת שנשאר בלי."""
        dm = _import_manager(monkeypatch)
        events(dm)
        collection = _Collection({"plain_ts": {"key": [("ts", 1)]}})

        assert dm.DatabaseManager.safe_create_index(
            _Manager(_DB(collection)), "service_metrics", [("ts", 1)],
            name="metrics_ttl", expire_after_seconds=2592000,
        ) is False

    def test_false_when_there_is_no_db(self, monkeypatch):
        dm = _import_manager(monkeypatch)

        assert dm.DatabaseManager.safe_create_index(
            _Manager(None), "service_metrics", [("ts", 1)], name="metrics_ttl",
        ) is False
