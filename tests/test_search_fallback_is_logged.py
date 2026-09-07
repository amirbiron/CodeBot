"""כשמסלול החיפוש המהיר נכשל — זה נרשם, ולא נבלע.

**למה הקובץ הזה קיים.** שלושה ``except`` ב-``_safe_search`` היו שקטים
לחלוטין. כשה-``$text`` נשבר, המערכת עברה בשקט לשאילתה **אחרת** — ``$regex``
על ``code``, סריקה מלאה בלי אינדקס — שנמדדה בפרודקשן כשאילתה האיטית ביותר
בכל הלוח (3,730ms). לקח שלושה סבבי חקירה רק כדי להבין שזה מה שקורה, ובסוף
לא היה אפשר לדעת **למה** הוא נשבר, כי אף שורה לא נכתבה.

הטסטים כאן מאלצים כל אחד מהכשלים ובודקים שנכתבה שורת לוג. הם בודקים את
**ההתנהגות** (מה יצא ללוג) ולא את קיום השורה בקוד — קריאת הקוד הייתה
"מאמתת" גם ניסוח שאינו רץ לעולם.

⚠️ **שני פולבאקים שונים, ואל תבלבלו:** להגיע ל-``_safe_search`` בכלל זה
מסלול **תקין** — היא נקראת כשמנוע החיפוש החזיר אפס תוצאות, וזו לא שגיאה.
מה שנבדק כאן הוא ה-``except`` הפנימי: השאילתה עצמה נזרקה.
"""

from __future__ import annotations

import logging

import pytest


class _RaisingCollection:
    """‏``aggregate`` שנכשל במספר הקריאות הראשונות, ואז מצליח.

    ``fail_times=1`` מדמה "המסלול המהיר נשבר, הפולבאק הצליח";
    ``fail_times=3`` מדמה נפילה עד הסוף.
    """

    def __init__(self, fail_times):
        self.fail_times = fail_times
        self.calls = 0

    def aggregate(self, pipeline, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError(f"aggregate exploded (call {self.calls})")
        return []


class _FakeDB:
    def __init__(self, collection):
        self.code_snippets = collection


@pytest.fixture
def app_module(monkeypatch):
    import webapp.app as webapp_app

    # מנוע החיפוש מחזיר אפס תוצאות — המסלול התקין שמוביל לפונקציה הזו.
    monkeypatch.setattr(webapp_app, "search_engine", None, raising=False)
    return webapp_app


def _run(app_module, monkeypatch, fail_times):
    collection = _RaisingCollection(fail_times)
    monkeypatch.setattr(app_module, "get_db", lambda: _FakeDB(collection), raising=True)
    results = app_module._safe_search(6865105071, "סטיקי", limit=50)
    return results, collection


def test_a_failing_text_pipeline_is_logged(app_module, monkeypatch, caplog):
    """הכשל שבגללו רצה השאילתה האיטית ביותר במערכת — עכשיו יש לו שורה."""
    with caplog.at_level(logging.WARNING):
        _results, collection = _run(app_module, monkeypatch, fail_times=1)

    assert collection.calls >= 2, "הפולבאק לא רץ, אז אין מה לבדוק"
    assert any("$text" in r.getMessage() for r in caplog.records), (
        f"אין שורת לוג על כשל המסלול המהיר: {[r.getMessage() for r in caplog.records]}"
    )


def test_the_failure_carries_the_exception_itself(app_module, monkeypatch, caplog):
    """‏``exc_info`` ולא רק הודעה.

    בלי ה-traceback השורה אומרת "משהו נשבר" ולא **מה** — וזה בדיוק הפער
    שהשאיר את הסיבה בלתי ידועה שלושה סבבים.
    """
    with caplog.at_level(logging.WARNING):
        _run(app_module, monkeypatch, fail_times=1)

    failed = [r for r in caplog.records if "$text" in r.getMessage()]
    assert failed and failed[0].exc_info is not None, "השורה אינה נושאת את החריגה"


def test_falling_all_the_way_down_is_logged_too(app_module, monkeypatch, caplog):
    """נפילה עד "לא נמצאו תוצאות" — המצב שנראה בדיוק כמו חיפוש שלא מצא.

    זה ההבדל היחיד שחשוב למשתמש, ועד עכשיו הוא לא היה מובחן בשום מקום.
    """
    with caplog.at_level(logging.WARNING):
        results, _collection = _run(app_module, monkeypatch, fail_times=99)

    assert results == []
    messages = [r.getMessage() for r in caplog.records]
    assert any("no results" in m for m in messages), (
        f"חיפוש שנשבר לגמרי חזר שקט: {messages}"
    )
