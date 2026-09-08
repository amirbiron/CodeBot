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


def test_the_projection_is_passed_through_when_given(repo):
    r, collection = repo()
    r.get_latest_versions_by_names(7, ["a.py"], projection={"code": 1, "file_name": 1})

    assert collection.pipelines[0][-1] == {"$project": {"code": 1, "file_name": 1}}


def test_a_failure_is_raised_and_not_swallowed(repo):
    """**בשונה מ-``get_user_files``, שבולעת ומחזירה רשימה ריקה.**

    הקורא היחיד הוא מסלול החיפוש. בליעה כאן הייתה מחזירה "אין תוצאות" על
    תקלה חולפת — ובמסלול שלמעלה, נפילה-לאחור לשליפה קובץ-קובץ. שתיהן
    מחזירות את הבאג בשקט; חריגה גלויה עדיפה.
    """
    r, _ = repo(explode=True)
    with pytest.raises(RuntimeError):
        r.get_latest_versions_by_names(7, ["a.py"])
