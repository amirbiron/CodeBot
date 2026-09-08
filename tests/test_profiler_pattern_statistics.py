"""‏``get_pattern_statistics`` — האגרגציה שמזינה את כרטיס "דפוסים ייחודיים".

**למה הקובץ הזה קיים.** הפייפליין נכתב מחדש עם ``$facet`` כדי שיחזיר גם את
העמוד וגם את מספר הדפוסים הכולל — בלי ספירה, "מוצגות 50 מתוך N" לא היה ניתן
לכתיבה וכל חיתוך היה נעלם בשקט. אבל עד הקובץ הזה **אף טסט לא קרא לפונקציה**:
היא הופיעה רק בהגדרתה ובראוט, והדמה בסוויטת העימוד מחזירה ``[]`` מ-``aggregate``
ואינה מממשת ``$facet`` בכלל. כלומר תוקן פער אחד ונוצר פער אחר.

**הצורות כאן נמדדו מול הקלאסטר** (``ClusterFrankfurt``, ‏``code_keeper_bot.slow_queries_log``)
ולא הומצאו — וזה משנה, כי מונגו מחזירה כאן משהו לא אינטואיטיבי:

===============================  =========================================
המצב                              מה מונגו מחזירה בפועל
===============================  =========================================
``$match`` שלא מתאים לכלום        ``[{"patterns": [], "total": []}]``
חלון עם נתונים                    ``total: [{"n": 17}]``, ‏``last_seen`` כ-``datetime``
===============================  =========================================

שים לב לשורה הראשונה: התוצאה **אינה** ריקה — היא מסמך אחד שבו ענף הספירה הוא
מערך **ריק**, ולא ``[{"n": 0}]``. זה בדיוק הענף שהיה מפיל ``total_branch[0]``
ב-``IndexError``, כלומר 500 על אוסף ריק. השומר קיים בקוד, וכאן יש לו הוכחה.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from services.query_profiler_service import (
    PROFILER_WINDOW_HOURS,
    PersistentQueryProfilerService,
)

#: מסמך אחד מהאגרגציה האמיתית, כולל ה-``_id`` המקונן ו-``last_seen`` כתאריך.
REAL_PATTERN = {
    "_id": {"query_id": "5c3429542f2a831a", "collection": "code_snippets", "operation": "find"},
    "count": 22,
    "avg_time_ms": 1075.9670454545455,
    "max_time_ms": 1293.941,
    "last_seen": datetime(2026, 9, 6, 17, 5, 40, 628000),
    "query_shape": {"user_id": "<value>", "$and": [{"is_active": "<value>"}]},
}

#: דפוס שני — ``query_shape`` ריק הוא מצב אמיתי בפרודקשן (``insert``).
SECOND_PATTERN = {
    "_id": {"query_id": "2a38fd8905a916a7", "collection": "snippet_chunks", "operation": "insert"},
    "count": 10,
    "avg_time_ms": 1033.2302,
    "max_time_ms": 1085.482,
    "last_seen": datetime(2026, 9, 6, 19, 56, 31, 744000),
    "query_shape": {},
}


class _FakeCollection:
    """לוכד את הפייפליין ומחזיר תשובה מוכנה. ``aggregate`` בלבד — זה כל מה שנבדק."""

    def __init__(self, result):
        self.result = result
        self.pipelines = []

    def aggregate(self, pipeline):
        self.pipelines.append(pipeline)
        return list(self.result)


class _FakeDB:
    def __init__(self, result):
        self.collection = _FakeCollection(result)

    def __getitem__(self, name):
        return self.collection


def _service(result):
    manager = MagicMock()
    manager.db = _FakeDB(result)
    return PersistentQueryProfilerService(db_manager=manager, slow_threshold_ms=100)


def _stage(pipeline, name):
    for stage in pipeline:
        if name in stage:
            return stage[name]
    raise AssertionError(f"אין שלב {name} בפייפליין: {[list(s)[0] for s in pipeline]}")


class TestThePipelineThatIsSent:
    """מה שנשלח למונגו, ולא רק מה שחוזר ממנה."""

    def test_the_window_comes_from_the_hours_argument(self):
        """חסם **דו-צדדי**, ובכוונה.

        הגרסה הראשונה כאן החזיקה שתי טענות שנראו שונות והיו אותה אי-שוויון
        מסודרת אחרת — שתיהן ``Δ ≥ 48h − 5s``. כלומר לא היה גבול עליון,
        והטסט היה עובר גם אם ``_window_hours`` היה מחזיר 144 שעות.
        """
        svc = _service([{"patterns": [], "total": []}])
        before = datetime.utcnow()

        svc.get_pattern_statistics(hours=48)

        since = _stage(svc.db_manager.db.collection.pipelines[0], "$match")["timestamp"]["$gte"]
        assert abs((before - since) - timedelta(hours=48)) < timedelta(seconds=5)

    def test_the_default_window_is_the_shared_constant(self):
        """הדפוסים חייבים לספור את אותה אוכלוסייה כמו הכרטיס והטבלה.

        קודם ברירת המחדל כאן הייתה שבעה ימים בזמן שהכרטיס ספר 24 שעות —
        שני מספרים על שתי אוכלוסיות, על אותו מסך.
        """
        svc = _service([{"patterns": [], "total": []}])
        before = datetime.utcnow()

        svc.get_pattern_statistics()

        since = _stage(svc.db_manager.db.collection.pipelines[0], "$match")["timestamp"]["$gte"]
        assert abs((before - since) - timedelta(hours=PROFILER_WINDOW_HOURS)) < timedelta(seconds=5)

    def test_both_facet_branches_are_asked_for(self):
        """בלי ענף הספירה, "מוצגות X מתוך Y" אינו ניתן לכתיבה — זו כל הסיבה ל-``$facet``."""
        svc = _service([{"patterns": [], "total": []}])

        svc.get_pattern_statistics(limit=25)

        facet = _stage(svc.db_manager.db.collection.pipelines[0], "$facet")
        assert set(facet) == {"patterns", "total"}
        assert {"$limit": 25} in facet["patterns"], "ה-``$limit`` שהתבקש לא הגיע לענף העמוד"
        assert facet["total"] == [{"$count": "n"}]

    def test_the_page_branch_sorts_by_frequency_with_a_tiebreaker(self):
        svc = _service([{"patterns": [], "total": []}])

        svc.get_pattern_statistics()

        facet = _stage(svc.db_manager.db.collection.pipelines[0], "$facet")
        assert facet["patterns"][0] == {"$sort": {"count": -1, "_id": -1}}

    @pytest.mark.parametrize("given,expected", [(0, 1), (-5, 1), (9999, 200), (None, 50), ("30", 50), (True, 50)])
    def test_the_limit_is_clamped_before_it_reaches_mongo(self, given, expected):
        """``limit`` הוא קלט חיצוני. ``CORE-PATTERNS`` U3: ``isinstance`` לפני חשבון."""
        svc = _service([{"patterns": [], "total": []}])

        svc.get_pattern_statistics(limit=given)

        facet = _stage(svc.db_manager.db.collection.pipelines[0], "$facet")
        assert {"$limit": expected} in facet["patterns"]


class TestWhatComesBack:
    def test_the_total_is_read_from_the_count_branch(self):
        """הצורה שנמדדה מול הקלאסטר: ``total`` הוא מערך עם מסמך ``{"n": …}``."""
        svc = _service([{"patterns": [REAL_PATTERN, SECOND_PATTERN], "total": [{"n": 17}]}])

        result = svc.get_pattern_statistics(limit=2)

        assert result["total"] == 17, "החיתוך אינו נאמר — 'מוצגות 2 מתוך 17' חוזר להיות בלתי ניתן לכתיבה"
        assert [p["_id"]["query_id"] for p in result["patterns"]] == ["5c3429542f2a831a", "2a38fd8905a916a7"]

    def test_an_empty_window_is_zero_and_not_a_crash(self):
        """**הצורה שמונגו באמת מחזירה על ``$match`` שלא מתאים לכלום.**

        לא תוצאה ריקה, אלא מסמך אחד שבו ענף הספירה הוא מערך **ריק** — ולא
        ``[{"n": 0}]``, שזו ההנחה הטבעית והשגויה. **המוטציה:** הסרת
        ``and total_branch`` מהתנאי הופכת את זה ל-``IndexError``, כלומר 500
        על אוסף ריק — המצב של כל התקנה חדשה.
        """
        svc = _service([{"patterns": [], "total": []}])

        assert svc.get_pattern_statistics() == {"patterns": [], "total": 0}

    def test_no_document_at_all_is_zero_and_not_a_crash(self):
        """הגנה על ``result[0]``: אגרגציה שלא החזירה שום מסמך."""
        svc = _service([])

        assert svc.get_pattern_statistics() == {"patterns": [], "total": 0}

    def test_without_a_database_nothing_is_aggregated(self):
        manager = MagicMock()
        manager.db = None
        svc = PersistentQueryProfilerService(db_manager=manager, slow_threshold_ms=100)

        assert svc.get_pattern_statistics() == {"patterns": [], "total": 0}


class TestThroughTheRoute:
    """מקצה לקצה — כי ה-``_id`` המקונן מגיע לדפדפן רק אחרי שיטוח."""

    @pytest.fixture
    def client(self, monkeypatch):
        import webapp.app as webapp_app

        monkeypatch.setattr(webapp_app, "_profiler_is_authorized", lambda: True, raising=True)
        monkeypatch.setattr(webapp_app, "_profiler_rate_limit_ok", lambda: True, raising=True)

        class _Svc:
            def get_pattern_statistics(self, hours=None, limit=None):
                return {"patterns": [REAL_PATTERN], "total": 17}

        monkeypatch.setattr(webapp_app, "_get_webapp_profiler_service", lambda: _Svc(), raising=True)
        return webapp_app.app.test_client()

    def test_the_nested_group_key_is_flattened_for_the_browser(self, client):
        """הדפדפן מקבל ``collection`` ו-``operation`` כשדות, לא ``_id`` מקונן."""
        row = client.get("/api/profiler/patterns").get_json()["data"][0]

        assert row["query_id"] == "5c3429542f2a831a"
        assert row["collection"] == "code_snippets"
        assert row["operation"] == "find"
        assert "_id" not in row

    def test_the_cut_is_reported_in_the_envelope(self, client):
        body = client.get("/api/profiler/patterns").get_json()

        assert body["count"] == 1
        assert body["total"] == 17, "בלי הסך, הכרטיס לא יכול לומר כמה נחתך"

    def test_the_timestamp_leaves_as_a_string_and_the_numbers_are_rounded(self, client):
        row = client.get("/api/profiler/patterns").get_json()["data"][0]

        assert row["last_seen"] == "2026-09-06T17:05:40.628000"
        assert row["avg_time_ms"] == 1075.97
        assert row["max_time_ms"] == 1293.94
