"""כשל בשליפת המטא-דאטה לשיתוף נרשם ללוג, ולא מתחפש ל-404.

**למה הקובץ הזה קיים.** ה-``except`` בענף ה-``preview`` של ``create_public_share``
היה ``meta = {}`` בלבד. שתי שורות מתחתיו ``if not meta`` מחזיר **404 "קובץ לא
נמצא"** — כלומר כשל בשאילתה הוגש למשתמש כקובץ שאינו קיים, בלי שום שורת לוג
שתאפשר להבחין בין השניים. זה מה שהחזיק את #3353 מוסתר.

⚠️ **מה הקובץ הזה מוכיח, ומה לא.** הוא מזריק חריגה מלאכותית מהסטאב, ולכן הוא
ראיה על כך שה-``except`` **מלוגג** — ולא ראיה על כך שמסלול השיתוף עדיין יכול
להישבר. אחרי המעבר ל-``$substrCP`` הסיבה שהפילה אותו בפרודקשן נעלמת, וה-``except``
נשאר עבור תקלות אחרות (נפילת קישוריות למונגו, ``$split`` על ``code`` שאינו
מחרוזת, ``ObjectId`` פגום). זהו **טסט רגרסיה על הלוגינג בלבד**. הראיה על מסלול
השיתוף עצמו נמצאת ב-``tests/test_snippet_hebrew_offsets_mongo.py``, שמריץ את
הראוט מול מונגו אמיתי.

הטסטים בודקים את **ההתנהגות** — מה יצא ללוג — ולא את קיום השורה בקוד; קריאת
הקוד הייתה "מאמתת" גם ניסוח שאינו רץ לעולם. זו אותה גישה כמו ב-
``tests/test_search_fallback_is_logged.py``.
"""

from __future__ import annotations

import logging

import pytest
from bson import ObjectId

FILE_ID = "0123456789abcdef01234567"
USER_ID = 4242

_META = {
    "file_name": "demo.py",
    "programming_language": "python",
    "description": "",
    "file_size": 8,
    "lines_count": 1,
    "snippet_preview": "print(1)",
}


class _CodeSnippets:
    def __init__(self, explode: bool):
        self.explode = explode

    def find_one(self, *_a, **_k):
        return {
            "_id": ObjectId(FILE_ID),
            "user_id": USER_ID,
            "file_name": "demo.py",
            "programming_language": "python",
            "description": "",
            "code": "print(1)",
        }

    def aggregate(self, _pipeline):
        if self.explode:
            raise RuntimeError("aggregate exploded")
        return [dict(_META)]


class _InternalShares:
    def __init__(self):
        self.docs: list = []

    def create_index(self, *_a, **_k):
        return "idx"

    def insert_one(self, doc):
        self.docs.append(dict(doc))
        return type("_R", (), {"inserted_id": 1})()


class _DB:
    def __init__(self, snippets):
        self.code_snippets = snippets
        self.internal_shares = _InternalShares()


@pytest.fixture
def share(monkeypatch):
    import webapp.app as wa

    def _post(explode: bool):
        monkeypatch.setattr(wa, "get_db", lambda: _DB(_CodeSnippets(explode)), raising=True)
        client = wa.app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = USER_ID
            sess["user_data"] = {"id": USER_ID, "first_name": "Test"}
        return client.post(f"/api/share/{FILE_ID}", json={})

    return _post


def _share_warnings(caplog):
    return [r for r in caplog.records if "share preview" in r.getMessage()]


def test_a_failing_preview_aggregation_is_logged(share, caplog):
    with caplog.at_level(logging.WARNING):
        share(explode=True)

    assert _share_warnings(caplog), (
        f"כשל בשאילתת השיתוף חזר שקט: {[r.getMessage() for r in caplog.records]}"
    )


def test_the_failure_carries_the_exception_itself(share, caplog):
    """בלי ``exc_info`` השורה אומרת "משהו נשבר" ולא **מה**."""
    with caplog.at_level(logging.WARNING):
        share(explode=True)

    records = _share_warnings(caplog)
    assert records and records[0].exc_info is not None, "השורה אינה נושאת את החריגה"


def test_the_404_contract_is_unchanged(share, caplog):
    """נעילת היקף: הוספת הלוג לא משנה את מה שהמשתמש מקבל.

    להבחין בין "לא נמצא" ל"השאילתה נשברה" הוא שינוי חוזה API, והוא מכוון
    מחוץ להיקף של התיקון הזה.
    """
    with caplog.at_level(logging.WARNING):
        resp = share(explode=True)

    assert resp.status_code == 404
    # jsonify מקודד עברית ל-\uXXXX, ולכן בודקים את ה-JSON המפורסר ולא את הטקסט הגולמי
    assert resp.get_json() == {"ok": False, "error": "קובץ לא נמצא"}


def test_a_successful_preview_logs_nothing(share, caplog):
    """**האסרשן שהופך את הקובץ למסוגל להיכשל בכיוון הנכון.**

    בלעדיו, ``logger.warning`` שהונח **מחוץ** ל-``except`` היה מספק את שלושת
    הטסטים שמעליו — כלומר הם היו עוברים על קוד שמלוגג אזהרה בכל שיתוף מוצלח.
    """
    with caplog.at_level(logging.WARNING):
        resp = share(explode=False)

    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert not _share_warnings(caplog), (
        f"שיתוף מוצלח כתב אזהרה: {[r.getMessage() for r in caplog.records]}"
    )
