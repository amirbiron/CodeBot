"""הדף של "הגרסה האחרונה לכל קובץ" — ההיטלה לפני המיון, והקוד לא נכנס למיון.

**הבעיה.** חמש מתודות ב-``database/repository.py`` בחרו את הגרסה האחרונה של כל קובץ (``$sort`` לפי
``file_name`` ו-``version``, ואחריו ``$group`` עם ``$first`` של ``$$ROOT``), ואז **מיינו שוב** — לפי
``updated_at``, או לפי שדה המועדפים — **לפני ההיטלה**. המיון השני חוסם בזיכרון, ומונגו מאחדת לתוכו
את ה-``$skip`` וה-``$limit`` שאחריו, כך שהוא החזיק ``skip + limit`` מסמכים מלאים, עם הקוד. באשכול
Flex התקרה היא 32MB ו-``allowDiskUse`` לא חל; מעליה שגיאה 292, והמתודות מחזירות ריק — "אין קבצים".

**מה נבדק כאן, בלי מסד:** הצינור **שנשלח בפועל** לדרייבר, דרך המתודה הציבורית — ההיטלה לפני המיון
האחרון ובלי שדה כבד, שדה מיון שהקורא לא ביקש שנשאר למיון ויורד אחריו, ובמסלול הכבד (היטלה שמביאה
``code``) — שהקוד נשלף ב-``find`` אחרי העימוד, בסדר של העמוד. מה שהמסד עושה עם זה — כמה בייטים
המיון מחזיק — נמדד ב-explain ב-``tests/test_repository_latest_page_mongo.py``.
"""

from __future__ import annotations

import pytest

from database.repository import Repository, _HEAVY_FIELDS_EXCLUDE_PROJECTION


class _Collection:
    """מקליטה כל צינור וכל ``find``. ``aggregate`` מחזיר את ``heads``, ו-``find`` את ``found``.

    **לא ``docs``:** ל-``get_favorites`` יש מסלול מהיר לסטאבים שמחזיקים רשימה בשם הזה, והוא עוקף את
    ``aggregate`` לגמרי — כלומר הבדיקה הייתה עוברת בלי לבדוק דבר.
    """

    def __init__(self, heads=None, found=None):
        self.pipelines: list[list] = []
        self.finds: list[tuple] = []
        self.heads = list(heads or [])
        self.found = list(found or [])

    def aggregate(self, pipeline, **_kwargs):
        self.pipelines.append(list(pipeline))
        return list(self.heads)

    def find(self, flt, projection=None):
        self.finds.append((flt, projection))
        return list(self.found)


class _Manager:
    def __init__(self, collection):
        self.collection = collection


def _repo(**kwargs):
    collection = _Collection(**kwargs)
    return Repository(_Manager(collection)), collection


_HEAVY_CODE = {"file_name": 1, "tags": 1, "code": 1, "_id": 1}

#: חמשת הקוראים, דרך המתודות הציבוריות — כמו שהבוט, הוובאפ וה-MCP קוראים להן.
CALLERS = {
    "get_user_files": lambda r: r.get_user_files(7, 1000),
    "get_user_files+code (גיבוי Drive)": lambda r: r.get_user_files(7, 1000, projection=_HEAVY_CODE),
    "get_user_files_by_repo": lambda r: r.get_user_files_by_repo(7, "repo:me/proj", 1, 500),
    "search_code": lambda r: r.search_code(7, "def", limit=1000),
    "get_user_file_names": lambda r: r.get_user_file_names(7, 1000),
    "get_favorites": lambda r: r.get_favorites(7, limit=1000),
}


def _stage_names(pipeline):
    return [next(iter(stage)) for stage in pipeline]


@pytest.mark.parametrize("call", list(CALLERS.values()), ids=list(CALLERS))
def test_every_latest_list_projects_before_the_sort_that_pages_it(call):
    """המיון האחרון — זה שמחזיק ``skip + limit`` מסמכים — בא אחרי ``$project``, וה-``$project``
    הזה אינו מביא שדה כבד. נופל על הסדר הקודם (``$sort`` ואז ``$project``) בכל אחד מהקוראים."""
    r, collection = _repo(heads=[{"_id": 1, "updated_at": 0, "favorited_at": 0}])
    call(r)

    pipeline = collection.pipelines[0]
    names = _stage_names(pipeline)
    last_sort = len(names) - 1 - names[::-1].index("$sort")
    projects = [i for i, name in enumerate(names) if name == "$project"]
    assert projects and projects[0] < last_sort, names
    before_sort = pipeline[projects[0]]["$project"]
    assert not any(before_sort.get(field) for field in _HEAVY_FIELDS_EXCLUDE_PROJECTION), before_sort


@pytest.mark.parametrize("call", [CALLERS["get_user_files+code (גיבוי Drive)"], CALLERS["get_favorites"]],
                         ids=["get_user_files+code", "get_favorites"])
def test_a_heavy_answer_is_fetched_after_the_page_in_the_order_of_the_page(call):
    """היטלה שמביאה ``code``: הצינור מחזיר רק מזהים בסדר העמוד, וה-``find`` שאחריו מביא את הקוד.
    ``find`` עם ``$in`` אינו מבטיח סדר, ולכן התשובה מסודרת לפי העמוד; ומזהה שה-``find`` לא החזיר —
    נמחק בין השלבים — פשוט אינו בתשובה."""
    heads = [{"_id": 3}, {"_id": 1}, {"_id": 2}]
    found = [{"_id": 2, "code": "b"}, {"_id": 1, "code": "a"}]  # בלי 3, ובסדר אחר
    r, collection = _repo(heads=heads, found=found)

    rows = call(r)

    assert [row["_id"] for row in rows] == [1, 2]
    [(flt, projection)] = collection.finds
    assert flt["_id"] == {"$in": [3, 1, 2]}
    assert flt["user_id"] == 7 and flt["is_active"] is True, "המסנן חל שוב בשלב השני"
    assert projection.get("code") == 1


def test_the_favorites_second_step_still_asks_for_favorites():
    """``match`` כולו חל שוב, ולא רק המשתמש: קובץ שהוסר מהמועדפים בין השלבים אינו חוזר."""
    r, collection = _repo(heads=[{"_id": 1}], found=[])
    r.get_favorites(7, language="python", limit=10)

    [(flt, _projection)] = collection.finds
    assert flt["is_favorite"] is True and flt["programming_language"] == "python"


def test_without_heads_there_is_no_second_query():
    r, collection = _repo(heads=[])
    assert r.get_user_files(7, 10, projection=_HEAVY_CODE) == []
    assert collection.finds == []


def test_a_sort_key_the_caller_did_not_ask_for_is_kept_for_the_sort_and_dropped_after():
    """``batch_commands`` מבקש ``{"file_name": 1}`` בלבד. בלי ``updated_at`` לפני המיון הוא היה ממיין
    לפי שדה חסר — סדר שרירותי, ועם ``$limit`` גם קבוצה אחרת של קבצים. השדה יורד אחרי ה-``$limit``,
    כדי שהתשובה תהיה מה שהייתה."""
    r, collection = _repo()
    r.get_user_files(7, 10, projection={"file_name": 1})

    pipeline = collection.pipelines[0]
    names = _stage_names(pipeline)
    project = pipeline[names.index("$project")]["$project"]
    assert project.get("updated_at") == 1
    assert names[-1] == "$unset" and pipeline[-1]["$unset"] == ["updated_at"]
    assert names.index("$limit") < names.index("$unset")


@pytest.mark.parametrize(("projection", "kept", "helpers"), [
    ({"file_name": 1}, {"file_name": 1, "updated_at": 1}, ["updated_at"]),
    ({"file_name": 1, "updated_at": 1}, {"file_name": 1, "updated_at": 1}, []),
    ({"code": 0, "updated_at": 0}, {"code": 0}, ["updated_at"]),
    ({"code": 0}, {"code": 0}, []),
    ({"_id": 0, "file_name": 1}, {"_id": 0, "file_name": 1, "updated_at": 1}, ["updated_at"]),
], ids=["include-בלי", "include-עם", "exclude-שמוריד", "exclude-שמשאיר", "בלי-_id"])
def test_keep_sort_keys(projection, kept, helpers):
    from database.repository import _keep_sort_keys

    assert _keep_sort_keys(projection, {"updated_at": -1}) == (kept, helpers)
