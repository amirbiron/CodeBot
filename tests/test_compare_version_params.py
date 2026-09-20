"""``left``/``right`` בכתובת דף ההשוואה — תשובה אחת, ואימות אמיתי.

**שתי בעיות נפרדות שהבדיקות כאן שומרות עליהן.**

הראשונה: שלושה מקומות חישבו את אותן שתי גרסאות — הראוט, ה-``selected``
בתבנית, ו-``compare.js``. שלוש תשובות לאותה שאלה הן שלוש דרכים להיסחף,
וכאן הסחיפה נראית כרשימה נפתחת שאומרת דבר אחד ודיף שמראה אחר.

השנייה: ``request.args.get(name, type=int, default=...)`` נראה כמו אימות
ואינו כזה — ב-Flask המרה כושלת מחזירה את ברירת המחדל בשקט. ``?left=abc``
הציג דיף של גרסה אחרת בלי לומר דבר. מספר גרסה שהגיע מהכתובת הוא טקסט
של מישהו, לא נתון.

הבסיס (``_import_app`` ו-monkeypatch על ``database.db``) לקוח
מ-``tests/test_compare_api.py``, שזו המוסכמה הקיימת לראוטים האלה.
"""

import importlib
import os

import pytest

pytest.importorskip("flask")

USER_ID = 123
FILE_ID = "abc123"


def _import_app():
    os.environ.setdefault("COMMUNITY_LIBRARY_ENABLED", "1")
    os.environ.setdefault("CHATOPS_ALLOW_ALL_IF_NO_ADMINS", "1")
    app_mod = importlib.import_module("webapp.app")
    app_mod.app.testing = True
    return app_mod.app


def _wire(monkeypatch, *, versions=(1, 2, 3), doc_version=3):
    """קובץ עם שלוש גרסאות. ``doc_version`` הוא מה שהמסמך שבכתובת מכיל."""
    import database

    def _get_file_by_id(file_id):
        return {
            "_id": file_id,
            "user_id": USER_ID,
            "file_name": "test.py",
            "version": doc_version,
            "programming_language": "python",
            "code": "line1\n",
        }

    def _get_all_versions(user_id, file_name):
        return [
            {"_id": f"v{v}", "version": v, "code": "x\n" * v, "user_id": user_id,
             "file_name": file_name}
            for v in sorted(versions, reverse=True)
        ]

    def _get_version(user_id, file_name, version):
        if version in versions:
            return {"_id": f"v{version}", "code": "x\n" * version,
                    "updated_at": "2025-01-01"}
        return None

    monkeypatch.setattr(database.db, "get_file_by_id", _get_file_by_id)
    monkeypatch.setattr(database.db, "get_all_versions", _get_all_versions)
    monkeypatch.setattr(database.db, "get_version", _get_version)


def _client(app):
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["user_id"] = USER_ID
        sess["user_data"] = {"id": USER_ID, "first_name": "בדיקה"}
    return c


# ------------------------------------------- תשובה אחת, לא שלוש


def test_the_dropdowns_and_the_diff_agree_on_the_requested_versions(monkeypatch):
    """הטסט שמגן על המלכודת: הרשימה וה-``init`` חייבים לומר אותו דבר."""
    app = _import_app()
    _wire(monkeypatch)
    body = _client(app).get(f"/compare/{FILE_ID}?left=1&right=3").get_data(as_text=True)

    assert "leftVersion: 1" in body, "ה-JS לא קיבל את הגרסה שביקשו"
    assert "rightVersion: 3" in body

    # ``selected`` יושב בשורה שאחרי ``value="N"`` בתבנית, ולכן נבדק
    # על כל תגית ה-``option`` ולא על התו הצמוד.
    import re
    options = re.findall(r'<option\s+value="(\d+)"(.*?)>', body, re.S)
    chosen = [int(v) for v, attrs in options if 'selected' in attrs]
    assert chosen == [1, 3], f"הרשימות הנפתחות מסומנות על {chosen} ולא על [1, 3]"


def test_without_parameters_the_defaults_are_previous_and_current(monkeypatch):
    app = _import_app()
    _wire(monkeypatch)
    body = _client(app).get(f"/compare/{FILE_ID}").get_data(as_text=True)
    assert "leftVersion: 2" in body
    assert "rightVersion: 3" in body


def test_the_current_version_comes_from_the_file_and_not_from_the_url_document(monkeypatch):
    """``file_id`` יכול להיות ה-``_id`` של גרסה ישנה — כל גרסה היא מסמך.

    בלי זה, פתיחת השוואה מתוך עמוד של גרסה ישנה הייתה מחשבת ברירות
    מחדל מול מסמך ישן.
    """
    app = _import_app()
    _wire(monkeypatch, doc_version=1)
    body = _client(app).get(f"/compare/{FILE_ID}").get_data(as_text=True)
    assert "rightVersion: 3" in body, "ברירת המחדל חושבה מול המסמך שבכתובת"


# ------------------------------------------------- קלט לא תקין


@pytest.mark.parametrize("bad", ["abc", "0", "-1", "999", "1.5", ""])
def test_the_page_redirects_instead_of_silently_showing_something_else(monkeypatch, bad):
    """הכתובת ומה שמוצג בה לא אמורים לסתור זה את זה."""
    app = _import_app()
    _wire(monkeypatch)
    resp = _client(app).get(f"/compare/{FILE_ID}?left={bad}&right=3")
    if bad == "":
        # ריק הוא "לא נמסר", ולכן ברירת המחדל — ולא שגיאה.
        assert resp.status_code == 200
        return
    assert resp.status_code == 302, f"ערך {bad!r} לא נדחה"
    assert resp.headers["Location"].endswith(f"/compare/{FILE_ID}")


@pytest.mark.parametrize("bad", ["abc", "0", "-1", "1.5"])
def test_the_api_rejects_a_malformed_version_with_a_message(monkeypatch, bad):
    app = _import_app()
    _wire(monkeypatch)
    resp = _client(app).get(f"/api/compare/versions/{FILE_ID}?left={bad}&right=3")
    assert resp.status_code == 400, f"ערך {bad!r} התקבל"
    assert "left" in (resp.get_json() or {}).get("error", ""), "השגיאה אינה אומרת מה נפסל"


def test_the_api_says_which_version_is_missing(monkeypatch):
    app = _import_app()
    _wire(monkeypatch)
    resp = _client(app).get(f"/api/compare/versions/{FILE_ID}?left=999&right=3")
    assert resp.status_code == 400
    assert "999" in (resp.get_json() or {}).get("error", "")


def test_a_valid_request_still_works(monkeypatch):
    """בקרה: בלעדיה כל הבדיקות למעלה היו עוברות גם על ראוט שבור."""
    app = _import_app()
    _wire(monkeypatch)
    resp = _client(app).get(f"/api/compare/versions/{FILE_ID}?left=1&right=3")
    assert resp.status_code == 200
    assert "lines" in (resp.get_json() or {})
