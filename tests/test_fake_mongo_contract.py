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


def test_not_over_an_operator_matches_a_missing_field_like_mongo(coll):
    """``$not`` כמו במונגו: שדה שאינו עונה לאופרטור — וגם שדה חסר, שגם הוא אינו עונה לו."""
    coll.insert_one({"tags": ["z"]})
    assert sorted(doc.get("a", 0) for doc in coll.find({"a": {"$not": {"$lt": 2}}})) == [0, 2]


@pytest.mark.parametrize("inner", ["^1", 1, {}])
def test_not_over_anything_but_operators_raises(coll, inner):
    """``$not`` עם ביטוי רגולרי או עם ערך הוא צורה אחרת, שהדמה אינה מממשת."""
    with pytest.raises(NotImplementedError, match="does not implement"):
        list(coll.find({"a": {"$not": inner}}))


@pytest.mark.parametrize(
    "update",
    [
        {"$inc": {"a": 1}},
        {"$addToSet": {"tags": "z"}},
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


def test_find_one_takes_projection_and_sort_like_pymongo(coll):
    """``Repository.save_code_snippet`` שואל ``find_one(query, projection, sort=...)``.

    דמה שלוקחת רק שאילתה זורקת שם ``TypeError``, והשמירה מדווחת על כשל. ה-sort
    רץ לפני ההיטלה (שדה שהוחרג עדיין קובע את הסדר), וערך חסר ממוין ראשון,
    כמו ``null`` במונגו.
    """
    coll.insert_one({"a": 1, "version": 3, "code": "v3"})
    coll.insert_one({"a": 1, "version": 5, "code": "v5"})
    coll.insert_one({"a": 1})

    top = coll.find_one({"a": 1}, {"version": 1}, sort=[("version", -1)])
    assert top["version"] == 5 and "code" not in top and "_id" in top

    lowest = coll.find_one({"a": 1}, sort=[("version", 1)])
    assert "version" not in lowest  # ה-None ממוין ראשון

    assert coll.find_one({"a": 99}, {"version": 1}, sort=[("version", -1)]) is None


def test_an_exclusion_projection_drops_the_field_like_mongo():
    """``{"code": 0}`` מחזיר הכול חוץ מ-``code`` — כמו במונגו, ולא את המסמך המלא.

    עד כאן הדמה התעלמה מהחרגה, ולכן קוד שקורא שדה שהוא עצמו החריג עבר כאן
    ונשבר בפרודקשן: עמוד השיתוף הציבורי קרא בלי ``code``, ושיתוף שנוצר בבוט
    הוצג ריק (#2235). הערכים כאן נמדדו מול ``mongod`` 7.0.14.
    """
    c = FakeCollection()
    c.insert_one({"_id": 1, "a": 1, "b": {"x": 1, "y": 2}, "code": "big"})

    assert c.find_one({}, {"code": 0}) == {"_id": 1, "a": 1, "b": {"x": 1, "y": 2}}
    assert c.find_one({}, {"b.y": 0}) == {"_id": 1, "a": 1, "b": {"x": 1}, "code": "big"}
    assert c.find_one({}, {"_id": 0, "code": 0}) == {"a": 1, "b": {"x": 1, "y": 2}}
    assert list(c.find({}, {"code": False})) == [{"_id": 1, "a": 1, "b": {"x": 1, "y": 2}}]
    # ההחרגה חלה על העותק שחוזר, לא על המסמך השמור
    assert c.find_one({})["code"] == "big"


def test_an_inclusion_projection_drops_id_only_when_asked():
    c = FakeCollection()
    c.insert_one({"_id": 1, "a": 1, "code": "big"})

    assert c.find_one({}, {"a": 1}) == {"_id": 1, "a": 1}
    assert c.find_one({}, {"a": 1, "_id": 0}) == {"a": 1}


def test_mixing_inclusion_and_exclusion_is_rejected_like_mongo():
    """מונגו דוחה ``{"a": 1, "code": 0}`` (31254); דמה שמחזירה משהו הייתה מכשירה קוד שנשבר במסד."""
    from pymongo.errors import OperationFailure

    c = FakeCollection()
    c.insert_one({"_id": 1, "a": 1, "code": "big"})

    with pytest.raises(OperationFailure, match="Cannot do exclusion on field code") as info:
        c.find_one({}, {"a": 1, "code": 0})
    assert info.value.code == 31254


def test_find_one_still_refuses_an_unimplemented_operator(coll):
    with pytest.raises(NotImplementedError, match="does not implement"):
        coll.find_one({"a": {"$regex": "^1"}}, {"a": 1}, sort=[("a", -1)])


def test_insert_one_reports_the_inserted_id(coll):
    res = coll.insert_one({"a": 3})
    assert res.inserted_id is not None
    assert coll.find_one({"_id": res.inserted_id})["a"] == 3


def test_with_options_reads_the_same_documents_and_takes_pymongos_keywords(coll):
    """``with_options`` מחזיר מבט על **אותם** מסמכים, ומקבל רק את שמות הפרמטרים של pymongo.

    הקריאה החוזרת אחרי שמירה (``Repository.find_version_by_id``) עוברת דרכו כדי לבקש
    ``PRIMARY``. בלעדיו הדמה זרקה ``AttributeError``, ושם פרמטר שגוי היה עובר כאן
    בשקט ונופל רק מול מונגו אמיתי.
    """
    from pymongo import ReadPreference

    view = coll.with_options(read_preference=ReadPreference.PRIMARY)
    res = coll.insert_one({"a": 3})
    assert view.find_one({"_id": res.inserted_id})["a"] == 3
    with pytest.raises(TypeError):
        coll.with_options(readPreference=ReadPreference.PRIMARY)


def test_set_on_insert_writes_only_when_the_upsert_inserts(coll):
    """כמו במונגו: ``$setOnInsert`` נכתב רק כשה-upsert יוצר מסמך, ועל מסמך קיים הוא לא עושה כלום."""
    coll.update_one({"a": 1}, {"$setOnInsert": {"b": "new"}}, upsert=True)
    assert "b" not in coll.find_one({"a": 1})

    res = coll.update_one({"a": 9}, {"$setOnInsert": {"b": "new"}, "$set": {"c": 1}}, upsert=True)
    created = coll.find_one({"a": 9})
    assert (created["b"], created["c"]) == ("new", 1)
    assert res.upserted_id == created["_id"]


def test_delete_many_removes_every_match_and_counts_them(coll):
    res = coll.delete_many({"a": {"$in": [1, 2, 3]}})
    assert res.deleted_count == 2
    assert coll.count_documents({}) == 0


def test_bulk_write_replaces_or_upserts_like_pymongo(coll):
    """``ReplaceOne`` של pymongo עצמו: מחליף מסמך קיים, יוצר כשאין (עם ``upsert``), וסופר."""
    from pymongo import ReplaceOne

    existing = coll.find_one({"a": 1})["_id"]
    res = coll.bulk_write(
        [
            ReplaceOne({"_id": existing}, {"a": 10}, upsert=True),
            ReplaceOne({"_id": "new"}, {"_id": "new", "a": 11}, upsert=True),
            ReplaceOne({"_id": "missing"}, {"a": 12}),
        ]
    )
    assert (res.matched_count, res.upserted_count) == (1, 1)
    assert coll.find_one({"_id": existing}) == {"_id": existing, "a": 10}
    assert coll.find_one({"_id": "new"})["a"] == 11
    assert coll.count_documents({"a": 12}) == 0


def test_bulk_write_refuses_an_operation_it_does_not_implement(coll):
    from pymongo import UpdateOne

    with pytest.raises(NotImplementedError, match="does not implement"):
        coll.bulk_write([UpdateOne({"a": 1}, {"$set": {"b": 1}})])
