"""החוזה של דמת המונגו המשותפת — מה שהיא מבטיחה לטסטים שנשענים עליה.

הדמה מימשה קבוצה קטנה של אופרטורים, וכל השאר נפלו למסלול "לא מזוהה ⇐ תואם"
בשאילתה, או "לא מזוהה ⇐ מתעלמים" בכתיבה. טסט עתידי עם ``$regex`` היה עובר
בטעות; עם ``$inc`` היה עובר בלי שהמונה זז. עכשיו זה נופל בקול.
"""

from __future__ import annotations

import pytest

# ‏``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _fake_mongo import FakeCollection


@pytest.fixture
def coll():
    c = FakeCollection()
    c.insert_one({"a": 1, "tags": ["x"]})
    c.insert_one({"a": 2, "tags": ["y"]})
    return c


@pytest.mark.parametrize(
    "query",
    [
        {"a": {"$regex": "^1"}},
        {"a": {"$type": "int"}},
        {"$or": [{"a": 1}, {"a": 2}]},
        {"$expr": {"$gt": ["$a", 1]}},
        {"$and": [{"a": 1}]},
    ],
)
def test_an_unimplemented_query_operator_raises_instead_of_matching_everything(coll, query):
    with pytest.raises(NotImplementedError, match="does not implement"):
        list(coll.find(query))


@pytest.mark.parametrize(
    "update",
    [
        {"$inc": {"a": 1}},
        {"$addToSet": {"tags": "z"}},
        {"$setOnInsert": {"a": 9}},
        {"$push": {"tags": {"$each": ["z"], "$position": 0}}},
    ],
)
def test_an_unimplemented_update_operator_raises_instead_of_being_ignored(coll, update):
    with pytest.raises(NotImplementedError, match="does not implement"):
        coll.update_one({"a": 1}, update)


def test_the_operators_the_repo_relies_on_keep_working(coll):
    assert [d["a"] for d in coll.find({"a": {"$nin": [1]}})] == [2]
    assert [d["a"] for d in coll.find({"a": {"$lt": 2}})] == [1]
    assert coll.count_documents({"tags": {"$exists": True}}) == 2

    res = coll.update_one(
        {"a": 1},
        {"$set": {"b": 1}, "$unset": {"tags": ""}, "$push": {"log": {"$each": [1, 2, 3], "$slice": -2}}},
    )
    doc = coll.find_one({"a": 1})
    assert res.matched_count == 1
    assert doc["b"] == 1 and "tags" not in doc and doc["log"] == [2, 3]

    res = coll.update_one({"a": 7}, {"$set": {"b": 2}, "$push": {"log": {"$each": ["first"]}}}, upsert=True)
    assert res.upserted_id is not None
    assert coll.find_one({"a": 7})["log"] == ["first"]


def test_update_many_applies_the_same_write_semantics(coll):
    coll.update_many({"a": {"$gte": 1}}, {"$unset": {"tags": ""}})
    assert all("tags" not in d for d in coll.find({}))
