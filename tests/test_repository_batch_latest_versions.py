"""``get_latest_versions_by_names`` — צורת הצינור והחלוקה למנות.

**למה הקובץ הזה קיים.** המתודה נולדה מחיפוש שלקח 191.7 שניות, וכל הערך
שלה הוא בצורת השאילתה: ``$match`` עם ``$in`` ואחריו ``$sort`` ו-``$group
$first``, שמונגו מקפלת ל-``DISTINCT_SCAN`` על ``idx_snippets_latest_version``.
שינוי קטן בסדר השלבים מבטל את הקיפול הזה בשקט — הקוד ימשיך להחזיר תשובות
נכונות, רק יסרוק את הכול. לכן הבדיקות כאן מקליטות את הצינור **שנשלח
בפועל** לדרייבר, ולא קוראות את קוד המקור.

הצינור אומת מול הקלאסטר האמיתי (``executionStats``): ``DISTINCT_SCAN`` +
``$groupByDistinctScan``, בלי מיון חוסם, ובדיוק מסמך אחד לכל שם מבוקש.
"""

from __future__ import annotations

import pytest

from database.repository import Repository


class _RecordingCollection:
    """מקליטה כל צינור שנשלח, ומחזירה מסמך לכל שם מבוקש."""

    def __init__(self, known: set[str] | None = None, *, explode: bool = False):
        self.pipelines: list[list] = []
        self.known = known
        self.explode = explode

    def aggregate(self, pipeline, **_kwargs):
        self.pipelines.append(list(pipeline))
        if self.explode:
            raise RuntimeError("תקלת מונגו מדומה")
        names = self._names_in(pipeline)
        return [
            {"file_name": n, "code": "x", "version": 1}
            for n in names
            if self.known is None or n in self.known
        ]

    @staticmethod
    def _names_in(pipeline):
        return pipeline[0]["$match"]["file_name"]["$in"]


class _FakeManager:
    def __init__(self, collection):
        self.collection = collection


@pytest.fixture
def repo():
    def _make(**kwargs):
        collection = _RecordingCollection(**kwargs)
        r = Repository(_FakeManager(collection))
        return r, collection
    return _make


def _names(n: int) -> list[str]:
    return [f"file_{i:04d}.py" for i in range(n)]


def test_the_pipeline_keeps_the_shape_the_index_can_serve(repo):
    """ארבעת השלבים, בסדר הזה — זה מה שמונגו מקפלת ל-DISTINCT_SCAN."""
    r, collection = repo()
    r.get_latest_versions_by_names(7, ["a.py", "b.py"])

    pipeline = collection.pipelines[0]
    stages = [next(iter(stage)) for stage in pipeline[:4]]
    assert stages == ["$match", "$sort", "$group", "$replaceRoot"], (
        f"סדר השלבים השתנה ל-{stages}; הקיפול ל-DISTINCT_SCAN מתבטל בשקט"
    )

    match = pipeline[0]["$match"]
    assert match["user_id"] == 7
    assert match["is_active"] is True, "בלי is_active אין תחילית תואמת לאינדקס"
    assert match["file_name"] == {"$in": ["a.py", "b.py"]}

    assert pipeline[1]["$sort"] == {"file_name": 1, "version": -1}, (
        "המיון חייב להתאים לסדר העמודות באינדקס"
    )
    assert pipeline[2]["$group"] == {"_id": "$file_name", "latest": {"$first": "$$ROOT"}}


def test_the_corpus_is_split_into_bounded_chunks(repo):
    """745 שמות — גודל הקורפוס שנמדד בפרודקשן — יורדים לשלוש מנות."""
    r, collection = repo()
    r.get_latest_versions_by_names(7, _names(745))

    assert len(collection.pipelines) == 3
    sizes = [len(_RecordingCollection._names_in(p)) for p in collection.pipelines]
    assert sizes == [250, 250, 245], f"חלוקה לא צפויה: {sizes}"

    # כל שם מבוקש נשלח בדיוק פעם אחת
    flat = [n for p in collection.pipelines for n in _RecordingCollection._names_in(p)]
    assert len(flat) == len(set(flat)) == 745


def test_a_single_chunk_is_one_round_trip(repo):
    """מתחת לגודל המנה — סיבוב אחד, לא יותר."""
    r, collection = repo()
    r.get_latest_versions_by_names(7, _names(250))
    assert len(collection.pipelines) == 1


def test_duplicate_and_empty_names_are_dropped_before_the_query(repo):
    """שם כפול היה מנפח את המנה ואת התשובה בלי להוסיף דבר."""
    r, collection = repo()
    r.get_latest_versions_by_names(7, ["a.py", "a.py", "", None, "b.py"])

    assert _RecordingCollection._names_in(collection.pipelines[0]) == ["a.py", "b.py"]


def test_an_empty_request_does_not_touch_the_database(repo):
    r, collection = repo()
    assert r.get_latest_versions_by_names(7, []) == {}
    assert collection.pipelines == [], "שאילתה מיותרת על רשימה ריקה"


def test_a_missing_file_is_simply_absent_from_the_result(repo):
    """אותו חוזה כמו ``None`` מ-``get_latest_version``, בלי מפתח שקרי."""
    r, _ = repo(known={"a.py"})
    out = r.get_latest_versions_by_names(7, ["a.py", "gone.py"])

    assert set(out) == {"a.py"}
    assert out["a.py"]["file_name"] == "a.py"


def _project_stage(pipeline):
    last = pipeline[-1]
    assert "$project" in last, f"אין שלב $project בצינור: {[next(iter(x)) for x in pipeline]}"
    return last["$project"]


def test_the_projection_is_passed_through_when_given(repo):
    r, collection = repo()
    r.get_latest_versions_by_names(7, ["a.py"], projection={"code": 1, "file_name": 1})

    assert _project_stage(collection.pipelines[0]) == {"code": 1, "file_name": 1}


def test_an_include_projection_always_keeps_file_name(repo):
    """**כשל שקט אחרת: מיפוי ריק, בלי חריגה ובלי לוג.**

    המתודה בונה את התשובה לפי ``doc.get("file_name")``. קורא שיבקש
    היטלה שאינה כוללת אותו — למשל ``{"_id": 1, "code": 1}`` — היה מקבל
    ``{}``, וחיפוש שנשבר היה נראה בדיוק כמו חיפוש בלי תוצאות.

    ``get_user_files`` שלוש פונקציות משם כבר מתגוננת מזה
    (``proj.setdefault("file_name", 1)``); זו אותה הגנה, מאותו עוזר.
    """
    r, collection = repo()
    out = r.get_latest_versions_by_names(7, ["a.py"], projection={"_id": 1, "code": 1})

    assert _project_stage(collection.pipelines[0]).get("file_name") == 1, (
        "file_name לא נכפה, והמיפוי יוצא ריק בלי שאיש ידע"
    )
    assert set(out) == {"a.py"}, f"התשובה יצאה ריקה: {out!r}"


def test_an_exclude_projection_still_drops_the_heavy_fields(repo):
    """היטלת exclude חייבת לקבל את השדות הכבדים בתוכה, כמו ב-``get_user_files``."""
    from database.repository import _HEAVY_FIELDS_EXCLUDE_PROJECTION

    r, collection = repo()
    r.get_latest_versions_by_names(7, ["a.py"], projection={"description": 0})

    proj = _project_stage(collection.pipelines[0])
    assert proj["description"] == 0
    for field in _HEAVY_FIELDS_EXCLUDE_PROJECTION:
        assert proj.get(field) == 0, f"{field} לא הוחרג בהיטלת exclude"


def test_without_a_projection_the_heavy_fields_are_excluded_by_default(repo):
    """**ברירת המחדל אינה "מסמך מלא".**

    זו מתודה ציבורית שנועדה לשלוף מאות מסמכים. ברירת מחדל שמושכת ``code``
    ו-``snippetEmbedding`` סותרת את כלל ה-Smart Projection דווקא במקום
    שהוא הכי חשוב בו. ``get_user_files`` נוהגת אותו דבר.
    """
    from database.repository import _HEAVY_FIELDS_EXCLUDE_PROJECTION

    r, collection = repo()
    r.get_latest_versions_by_names(7, ["a.py"])

    proj = _project_stage(collection.pipelines[0])
    assert proj == dict(_HEAVY_FIELDS_EXCLUDE_PROJECTION), (
        f"ברירת המחדל מושכת מסמך מלא: {proj!r}"
    )


def test_the_search_projection_passes_through_untouched(repo):
    """נעילת היקף: המסלול החי אינו משתנה מהתיקון.

    ``SEARCH_RESULT_PROJECTION`` כבר כוללת ``file_name``, ולכן ההגנה
    החדשה אינה אמורה לגעת בה בכלל.
    """
    import search_engine as se

    r, collection = repo()
    r.get_latest_versions_by_names(7, ["a.py"], projection=se.SEARCH_RESULT_PROJECTION)

    assert _project_stage(collection.pipelines[0]) == dict(se.SEARCH_RESULT_PROJECTION)


def test_a_failure_is_raised_and_not_swallowed(repo):
    """**בשונה מ-``get_user_files``, שבולעת ומחזירה רשימה ריקה.**

    הקורא היחיד הוא מסלול החיפוש. בליעה כאן הייתה מחזירה "אין תוצאות" על
    תקלה חולפת — ובמסלול שלמעלה, נפילה-לאחור לשליפה קובץ-קובץ. שתיהן
    מחזירות את הבאג בשקט; חריגה גלויה עדיפה.
    """
    r, _ = repo(explode=True)
    with pytest.raises(RuntimeError):
        r.get_latest_versions_by_names(7, ["a.py"])


# --------------------------------------------------------------------------
# ``get_user_files`` — האחות שההיגיון נלקח ממנה
# --------------------------------------------------------------------------


class _ListCollection(_RecordingCollection):
    """``get_user_files`` מוסיפה ``$skip``/``$limit``, ולכן ה-``$project``
    אינו השלב האחרון. אין צורך בהתנהגות אחרת — רק בהקלטה."""


def _project_of(pipeline):
    for stage in pipeline:
        if "$project" in stage:
            return stage["$project"]
    return None


@pytest.mark.parametrize(
    "projection, expected",
    [
        pytest.param(None, "heavy", id="בלי-היטלה"),
        pytest.param({}, "heavy", id="היטלה-ריקה"),
        pytest.param({"description": 0}, "heavy+description", id="exclude-ממוקד"),
        pytest.param({"_id": 1, "code": 1}, {"_id": 1, "code": 1, "file_name": 1},
                     id="include-בלי-file_name"),
        pytest.param({"file_name": 1, "version": 1}, {"file_name": 1, "version": 1},
                     id="include-עם-file_name"),
    ],
)
def test_get_user_files_projection_is_unchanged_by_the_shared_helper(projection, expected):
    """נעילת התנהגות על המסלול החם של **כל מסכי הרשימות**.

    היגיון ההיטלה נכתב במקור בתוך ``get_user_files``, וחולץ ל-
    ``_latest_version_projection_stage`` כדי ש-``get_latest_versions_by_names``
    תשתמש בו ולא תחזיק עותק שני. חילוץ הוא ריפקטור, וריפקטור במסלול הזה
    צריך רשת: הבדיקה מקבעת את חמשת המצבים כפי שנמדדו לפני החילוץ.
    """
    from database.repository import _HEAVY_FIELDS_EXCLUDE_PROJECTION

    collection = _ListCollection()
    Repository(_FakeManager(collection)).get_user_files(7, 50, projection=projection)

    proj = _project_of(collection.pipelines[0])
    if expected == "heavy":
        assert proj == dict(_HEAVY_FIELDS_EXCLUDE_PROJECTION)
    elif expected == "heavy+description":
        assert proj == {**_HEAVY_FIELDS_EXCLUDE_PROJECTION, "description": 0}
    else:
        assert proj == expected
