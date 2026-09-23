"""``Repository.save_file`` כותב את מה שיש **במסד**, ולא את מה שהקאש זוכר.

``save_file`` — עריכה בבוט, ייבוא מ-GitHub ומ-ZIP — מעתיק לגרסה החדשה את התיאור והתגיות של הגרסה הקודמת. עד התיקון הוא קרא אותה דרך ``get_latest_version``, שנשמרת בקאש, ולכן תיאור או תגיות ששונו בוובאפ חזרו לקדמותם בשמירה הבאה מהבוט, אם היא הגיעה לפני שהקאש פג. זה בדיוק מה שה-docstring של ``get_latest_version`` אוסר: היא לקריאה בלבד, ומי שצריך ערך טרי קורא ל-``_fetch_latest_version``.

אותו לקח כמו ב-``tests/test_edit_file_accumulates.py`` (מספר הגרסה) וכמו ב-``test_save_file_does_not_bring_back_a_mark_that_was_removed`` ב-``tests/test_favorite_is_a_file_state.py`` (סימון המועדף).

⚠️ מונגו אמיתי דרך ``wired_mongo`` — ראו את ההערה בראש ``tests/test_favorite_is_a_file_state.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

pytest.importorskip("flask")
pytest.importorskip("pymongo")

USER_ID = 7171
NAME = "fresh.md"
CREATED = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _empty_local_cache_store():
    """``@cached`` נופל ל-``_local_cache_store`` כש-Redis כבוי, והמילון הזה חי ברמת המודול — כמו ב-``tests/test_search_code_failure_is_not_cached.py``."""
    import cache_manager

    cache_manager._local_cache_store.clear()
    yield
    cache_manager._local_cache_store.clear()


class _Manager:
    """``Repository`` צריך רק ``manager.collection``."""

    def __init__(self, collection):
        self.collection = collection


@pytest.mark.parametrize("field, before, after", [
    ("description", "תיאור ישן", "תיאור חדש"),
    ("tags", ["old"], ["new"]),
])
def test_save_file_writes_what_the_database_holds_now_and_not_what_the_cache_remembers(wired_mongo, field, before, after):
    from database.repository import Repository

    collection = wired_mongo.get_db().code_snippets
    collection.delete_many({})
    collection.insert_one({
        "user_id": USER_ID, "file_name": NAME, "code": "# גרסה 1\n", "programming_language": "markdown",
        "description": "תיאור ישן", "tags": ["old"], "version": 1, "is_active": True,
        "created_at": CREATED, "updated_at": CREATED,
    })
    repo = Repository(_Manager(collection))
    assert repo.get_latest_version(USER_ID, NAME)[field] == before

    # השינוי נכתב ישירות למסד, כמו שהוובאפ כותב — בלי לעבור בקאש של ``Repository``.
    collection.update_many({"user_id": USER_ID, "file_name": NAME}, {"$set": {field: after}})
    assert repo.get_latest_version(USER_ID, NAME)[field] == before, "הקאש לא החזיק את הגרסה — הבדיקה לא בודקת כלום"

    assert repo.save_file(USER_ID, NAME, "# גרסה 2\n", "markdown") is True

    latest = collection.find_one({"user_id": USER_ID, "file_name": NAME, "is_active": True}, sort=[("version", -1)])
    assert latest["version"] == 2, latest
    assert latest[field] == after, f"{field} חזר לערך שהקאש זכר: {latest[field]!r}"
