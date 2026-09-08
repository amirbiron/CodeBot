"""``_clear_superseded_chunks`` ב-WebApp — אותו מירוץ, נתיב שני.

הרקע (אישו #3332, ריוויו PR #3342): שמירת גרסה חדשה אינה מכבה את הקודמת,
ולכן כל גרסה היסטורית נשארת מאונדקסת. אבל "מחק הכל חוץ ממני" הוא TOCTOU:
כששתי שמירות של אותו קובץ חופפות, הניקוי של הישנה יכול לרוץ **אחרי**
שהחדשה כבר נשמרה, ולמחוק את הצ'אנקים שלה. הגרסה החדשה כבר סומנה
``chunkerVersion`` נוכחי ולכן לא תיחתך שוב — הקובץ נעלם מהחיפוש הסמנטי
לצמיתות, וג'וב הניקוי לא עוזר כי הוא מוחק ואינו בונה.

הפתרון אינו נעילה אלא תנאי בשאילתה: ``version < N``.
"""

import inspect

import pytest

from database.manager import delete_snippet_chunks as _real_delete_snippet_chunks
from webapp import app as webapp_app

_DELETE_SIG = inspect.signature(_real_delete_snippet_chunks)


@pytest.fixture()
def cleanup_calls(monkeypatch):
    """הדמה נקשרת לחתימה האמיתית, כדי שלא תיסחף ממנה בשקט."""
    calls = []

    def _delete(*args, **kwargs):
        bound = _DELETE_SIG.bind(*args, **kwargs)
        bound.apply_defaults()
        calls.append(dict(bound.arguments))
        return 0

    monkeypatch.setattr(webapp_app, "_delete_snippet_chunks", _delete)
    return calls


def _doc(**extra):
    doc = {"user_id": 7, "file_name": "a.py", "version": 5}
    doc.update(extra)
    return doc


def test_cleanup_is_bounded_to_older_versions(cleanup_calls):
    webapp_app._clear_superseded_chunks(_doc(), "new-id")

    assert len(cleanup_calls) == 1
    call = cleanup_calls[0]
    assert call["older_than_version"] == 5, (
        "unbounded cleanup; a concurrent newer save would lose its chunks"
    )
    assert call["file_name"] == "a.py"
    assert call["exclude_snippet_id"] == "new-id"
    assert call["user_id"] == 7


def test_each_call_passes_its_own_version_as_the_bound(cleanup_calls):
    """כל קריאה נושאת את הגבול של **עצמה**, גם כשהן מגיעות בסדר הפוך.

    מה הטסט הזה כן מוכיח ומה לא: ``_delete_snippet_chunks`` ממוקה כאן, ולכן
    שתי הקריאות הן הקלטות בלתי תלויות — הן לא נוגעות במירוץ עצמו. ההגנה
    האמיתית מפני המירוץ היא תנאי ה-``$lt`` **בתוך** הפונקציה הממוקה, והיא
    נבדקת ב-``tests/test_repository_delete_cleans_chunks.py``
    (``TestOverlappingSaves``) מול השאילתה שנבנית בפועל.

    מה שכן נבדק כאן: ש-``_clear_superseded_chunks`` אינו שומר מצב בין
    קריאות ואינו לוקח את הגבול ממקום גלובלי — כלומר גרסה 4 שמנקה אחרי
    גרסה 9 שולחת 4, לא 9.
    """
    webapp_app._clear_superseded_chunks(_doc(version=9), "id-9")
    webapp_app._clear_superseded_chunks(_doc(version=4), "id-4")

    assert [c["older_than_version"] for c in cleanup_calls] == [9, 4]


def test_a_failed_insert_never_triggers_cleanup(cleanup_calls):
    """מחיקה לפני הכנסה מוצלחת הייתה מוציאה את הגרסה הנוכחית מהחיפוש
    בלי שום דבר שיחזיר אותה."""
    webapp_app._clear_superseded_chunks(_doc(), None)
    assert cleanup_calls == []


@pytest.mark.parametrize(
    "doc",
    [
        {"user_id": 7, "file_name": "a.py"},                 # אין version
        {"user_id": 7, "file_name": "a.py", "version": None},
        {"user_id": 7, "file_name": "a.py", "version": "x"},
        {"user_id": None, "file_name": "a.py", "version": 3},
        {"user_id": 7, "file_name": "", "version": 3},
    ],
    ids=["no-version", "null-version", "bad-version", "no-user", "no-file-name"],
)
def test_an_incomplete_document_deletes_nothing(cleanup_calls, doc):
    """בלי גבול ברור לא מוחקים. הג'וב היומי ינקה את הגרסאות הישנות —
    זו הטעות הבטוחה מבין השתיים."""
    webapp_app._clear_superseded_chunks(doc, "new-id")
    assert cleanup_calls == []
