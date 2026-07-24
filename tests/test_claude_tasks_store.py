"""בדיקות ל-services/claude_tasks_store.py.

לפי מוסכמת הריפו — fake ידני ל-Mongo, בלי mongomock. ה-fake ב-tests/_fake_mongo.py
לא תומך ב-find/sort/count_documents שהחנות הזאת צריכה, אז יש כאן fake ממוקד.
"""

from datetime import datetime, timedelta, timezone

import pytest

from services import claude_tasks_store as store


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, key, direction=1):
        self._docs.sort(key=lambda d: d.get(key) or datetime.min.replace(tzinfo=timezone.utc),
                        reverse=direction < 0)
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    def __iter__(self):
        return iter(self._docs)


class _FakeCollection:
    def __init__(self):
        self.docs = []

    @staticmethod
    def _match(doc, query):
        for key, cond in query.items():
            value = doc.get(key)
            if isinstance(cond, dict):
                if "$ne" in cond and value == cond["$ne"]:
                    return False
                if "$in" in cond and value not in cond["$in"]:
                    return False
                if "$gte" in cond and (value is None or value < cond["$gte"]):
                    return False
            elif value != cond:
                return False
        return True

    def update_one(self, query, update, upsert=False):
        for doc in self.docs:
            if self._match(doc, query):
                doc.update(update.get("$set", {}))
                return None
        if upsert:
            new_doc = {k: v for k, v in query.items() if not isinstance(v, dict)}
            new_doc.update(update.get("$set", {}))
            self.docs.append(new_doc)
        return None

    def find_one(self, query):
        return next((dict(d) for d in self.docs if self._match(d, query)), None)

    def find(self, query):
        return _Cursor(dict(d) for d in self.docs if self._match(d, query))

    def count_documents(self, query):
        return sum(1 for d in self.docs if self._match(d, query))


class _FakeClient:
    def __init__(self):
        self._collections = {}

    def __getitem__(self, _db_name):
        return self

    def __call__(self, name):  # pragma: no cover - לא בשימוש
        return self._collections.setdefault(name, _FakeCollection())


class _FakeDBManager:
    """מחקה את ‎db.client[db.db_name][collection]‎ של DatabaseManager."""

    def __init__(self):
        self.db_name = "test"
        self._collections = {}
        self.client = self

    def __getitem__(self, name):
        if name == self.db_name:
            return self
        return self._collections.setdefault(name, _FakeCollection())


@pytest.fixture
def db():
    return _FakeDBManager()


def _create(db, request_id="r1", user_id=1, status="pending_confirm"):
    return store.create_task(
        request_id=request_id,
        user_id=user_id,
        chat_id=user_id,
        message_id=10,
        prompt="משימה כלשהי",
        repo="owner/repo",
        status=status,
        db_manager=db,
    )


class TestCrud:
    def test_create_and_get(self, db):
        assert _create(db) is True
        task = store.get_by_request_id("r1", db_manager=db)
        assert task["prompt"] == "משימה כלשהי"
        assert task["status"] == "pending_confirm"
        assert task["issue_number"] is None

    def test_update(self, db):
        _create(db)
        assert store.update_task(
            "r1", {"status": "dispatched", "issue_number": 7}, db_manager=db
        ) is True
        task = store.get_by_request_id("r1", db_manager=db)
        assert task["status"] == "dispatched"
        assert task["issue_number"] == 7

    def test_get_by_issue_number_scoped_to_user(self, db):
        _create(db, request_id="r1", user_id=1)
        store.update_task("r1", {"issue_number": 7, "status": "dispatched"}, db_manager=db)
        assert store.get_by_issue_number(7, user_id=1, db_manager=db) is not None
        assert store.get_by_issue_number(7, user_id=999, db_manager=db) is None

    def test_prompt_is_truncated(self, db):
        store.create_task(
            request_id="long",
            user_id=1,
            chat_id=1,
            message_id=1,
            prompt="א" * 9000,
            repo="owner/repo",
            db_manager=db,
        )
        task = store.get_by_request_id("long", db_manager=db)
        assert len(task["prompt"]) == 4000

    def test_new_request_id_is_short_and_unique(self):
        ids = {store.new_request_id() for _ in range(50)}
        assert len(ids) == 50
        assert all(len(i) == 8 for i in ids)


class TestListing:
    def test_pending_confirm_is_hidden_from_lists(self, db):
        _create(db, request_id="r1", status="pending_confirm")
        _create(db, request_id="r2", status="dispatched")
        listed = store.list_recent(1, db_manager=db)
        assert [t["request_id"] for t in listed] == ["r2"]

    def test_list_recent_is_newest_first(self, db):
        _create(db, request_id="old", status="completed")
        _create(db, request_id="new", status="completed")
        store.update_task(
            "old", {"created_at": datetime.now(timezone.utc) - timedelta(hours=5)}, db_manager=db
        )
        listed = store.list_recent(1, db_manager=db)
        assert listed[0]["request_id"] == "new"

    def test_get_last_for_user(self, db):
        _create(db, request_id="r1", status="dispatched")
        assert store.get_last_for_user(1, db_manager=db)["request_id"] == "r1"

    def test_get_last_for_user_when_empty(self, db):
        assert store.get_last_for_user(1, db_manager=db) is None


class TestCounters:
    def test_count_today_ignores_pending_and_old(self, db):
        _create(db, request_id="r1", status="dispatched")
        _create(db, request_id="r2", status="pending_confirm")
        _create(db, request_id="r3", status="completed")
        store.update_task(
            "r3", {"created_at": datetime.now(timezone.utc) - timedelta(days=3)}, db_manager=db
        )
        assert store.count_today(1, db_manager=db) == 1

    def test_count_today_is_per_user(self, db):
        _create(db, request_id="r1", user_id=1, status="dispatched")
        _create(db, request_id="r2", user_id=2, status="dispatched")
        assert store.count_today(1, db_manager=db) == 1

    def test_count_active_counts_only_in_flight(self, db):
        _create(db, request_id="r1", status="dispatched")
        _create(db, request_id="r2", status="running")
        _create(db, request_id="r3", status="completed")
        assert store.count_active(1, db_manager=db) == 2


class TestFailureIsolation:
    """כשל DB לא אמור להפיל את הפקודה — רק לגרוע פונקציונליות."""

    class _BrokenDB:
        db_name = "test"

        @property
        def client(self):
            raise RuntimeError("mongo down")

    def test_all_reads_degrade_gracefully(self):
        broken = self._BrokenDB()
        assert store.get_by_request_id("r1", db_manager=broken) is None
        assert store.get_by_issue_number(1, db_manager=broken) is None
        assert store.list_recent(1, db_manager=broken) == []
        assert store.get_last_for_user(1, db_manager=broken) is None
        assert store.count_today(1, db_manager=broken) == 0
        assert store.count_active(1, db_manager=broken) == 0

    def test_writes_report_failure_without_raising(self):
        broken = self._BrokenDB()
        assert _create(broken) is False
        assert store.update_task("r1", {"status": "x"}, db_manager=broken) is False


def test_collection_name_matches_declaration():
    """שם ה-collection בחנות ובקובץ ההצהרות חייב להישאר זהה."""
    from database.claude_tasks_collection import CLAUDE_TASKS_COLLECTION

    assert store.CLAUDE_TASKS_COLLECTION == CLAUDE_TASKS_COLLECTION
