"""האחסון של היועץ (``services/advisor_store.py``) — בלי מסד אמיתי.

כאן: שמסלול העלייה באמת מבקש את אינדקסי ה-TTL במפרט המלא, שכשל ביצירה שלהם
מדווח, ומה קורה מול מסד no-op. מה שרק שרת עונה עליו — המכסה תחת מקביליות,
סדר ההיסטוריה והאינדקסים שנוצרו בפועל — ב-``test_advisor_store_mongo.py``.
"""

from __future__ import annotations

import types
from datetime import datetime, timedelta, timezone

import pytest

import advisor_collections
import database
from database.manager import DatabaseManager, NoOpDB
from services import advisor_store


class _Coll:
    def create_indexes(self, indexes):
        return None

    def list_indexes(self):
        return []


class _DB:
    def __getitem__(self, name):
        return _Coll()


def _requested_indexes() -> list[tuple]:
    """כל קריאה ל-``safe_create_index`` שיצאה מ-``_create_indexes`` — המסלול שכל עלייה עוברת בו."""
    requested: list[tuple] = []
    fake_self = types.SimpleNamespace(
        collection=_Coll(),
        large_files_collection=_Coll(),
        db=_DB(),
        backup_ratings_collection=_Coll(),
        internal_shares_collection=_Coll(),
        community_library_collection=_Coll(),
        snippets_collection=_Coll(),
        safe_create_index=lambda collection, keys, **kwargs: requested.append((collection, list(keys), kwargs)) or True,
    )
    DatabaseManager._create_indexes(fake_self)
    return requested


def test_startup_requests_both_ttl_indexes_with_the_full_spec():
    """בלי ה-TTL זיכרון השיחה לא נמחק לעולם — בניגוד למה שהפתיחה מבטיחה לגולש."""
    ttl = {
        collection: (keys, kwargs)
        for collection, keys, kwargs in _requested_indexes()
        if collection in (advisor_collections.HISTORY_COLLECTION, advisor_collections.USAGE_COLLECTION)
        and kwargs.get("expire_after_seconds")
    }
    assert set(ttl) == {advisor_collections.HISTORY_COLLECTION, advisor_collections.USAGE_COLLECTION}, (
        "מסלול העלייה לא מבקש TTL לאחד מאוספי היועץ — המסמכים שלו לא יימחקו לעולם"
    )
    history_keys, history_kwargs = ttl[advisor_collections.HISTORY_COLLECTION]
    assert history_keys == [("created_at", 1)]
    assert history_kwargs["expire_after_seconds"] == advisor_collections.HISTORY_RETENTION_DAYS * 24 * 60 * 60
    # בלי enforce, שינוי של HISTORY_RETENTION_DAYS היה נבלע כהתנגשות, והחלון הישן ממשיך
    assert history_kwargs["enforce"] is True
    usage_keys, usage_kwargs = ttl[advisor_collections.USAGE_COLLECTION]
    assert usage_keys == [("created_at", 1)]
    assert usage_kwargs["enforce"] is True


def test_startup_requests_the_history_query_index():
    names = [kwargs["name"] for collection, _, kwargs in _requested_indexes()
             if collection == advisor_collections.HISTORY_COLLECTION]
    assert "advisor_history_user_recent" in names


def test_a_failed_ttl_index_is_reported_as_an_error(monkeypatch):
    events: list[tuple] = []
    monkeypatch.setitem(
        DatabaseManager._create_advisor_indexes.__globals__,
        "emit_event",
        lambda event, severity="info", **fields: events.append((event, severity, fields)),
    )
    results = DatabaseManager._create_advisor_indexes(types.SimpleNamespace(), lambda *a, **k: False)
    assert set(results.values()) == {False}
    reported = {(fields["collection"], fields["index_name"]) for event, severity, fields in events
                if event == "db_advisor_index_missing" and severity == "error"}
    # שני ה-TTL מדווחים; אינדקס הביצועים אינו required
    assert reported == {
        (advisor_collections.HISTORY_COLLECTION, "advisor_history_ttl"),
        (advisor_collections.USAGE_COLLECTION, "advisor_daily_usage_ttl"),
    }


@pytest.fixture
def noop_db(monkeypatch):
    monkeypatch.setattr(database.db, "db", NoOpDB())


def test_noop_database_reads_no_history(noop_db):
    assert advisor_store.get_history(1, 5) == []


def test_noop_database_does_not_report_a_saved_exchange(noop_db):
    """מסד no-op מחזיר הצלחה בלי מזהה — זה כשל, לא שמירה (K11)."""
    with pytest.raises(advisor_store.AdvisorStoreError):
        advisor_store.save_exchange(1, "שאלה", "תשובה")


def test_noop_database_does_not_allow_a_question(noop_db):
    """בלי מסד אי אפשר לספור, ולכן גם לא לאשר — המכסה נכשלת סגור."""
    with pytest.raises(advisor_store.AdvisorStoreError):
        advisor_store.take_daily_question(1)


def test_the_quota_day_is_the_israel_date():
    # 22.10.2026 — שעון קיץ בישראל, UTC+3
    assert advisor_store.israel_day(datetime(2026, 10, 22, 20, 59, tzinfo=timezone.utc)) == "2026-10-22"
    assert advisor_store.israel_day(datetime(2026, 10, 22, 21, 0, tzinfo=timezone.utc)) == "2026-10-23"
    # אחרי סוף שעון הקיץ — UTC+2
    winter = datetime(2026, 12, 1, 22, 0, tzinfo=timezone.utc)
    assert advisor_store.israel_day(winter) == "2026-12-02"
    assert advisor_store.israel_day(winter - timedelta(minutes=1)) == "2026-12-01"
