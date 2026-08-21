"""בדיקות ל-``user_roles`` — מקור האמת היחיד להרשאות אדמין/פרימיום.

הפונקציות האלה היו משוכפלות מילה במילה ב-``webapp/app`` וב-
``webapp/code_tools_api``. הבדיקות כאן מכסות את ההתנהגות המשותפת, ובנוסף
מאמתות ששני הצרכנים באמת מצביעים לאותה פונקציה ולא לעותק.
"""

import pytest

import user_roles


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("ADMIN_USER_IDS", raising=False)
    monkeypatch.delenv("PREMIUM_USER_IDS", raising=False)


# -- is_admin --

def test_no_env_means_nobody_is_admin():
    """היעדר הגדרה אינו מעניק הרשאה — ברירת המחדל סגורה."""
    assert user_roles.is_admin(1) is False


def test_listed_id_is_admin(monkeypatch):
    monkeypatch.setenv("ADMIN_USER_IDS", "5, 7 ,9")
    assert user_roles.is_admin(7) is True
    assert user_roles.is_admin(8) is False


def test_non_numeric_entry_is_skipped_not_fatal(monkeypatch):
    """רשומה פגומה לא מעניקה הרשאה וגם לא מפילה את הבקשה.

    זו בדיוק ההתנהגות של שני העותקים שהוסרו, והיא נשמרת.
    """
    monkeypatch.setenv("ADMIN_USER_IDS", "abc,,5,-3")
    assert user_roles.is_admin(5) is True
    assert user_roles.is_admin(-3) is False  # ``isdigit`` דוחה מינוס — כמו קודם


def test_string_user_id_is_coerced(monkeypatch):
    """``session['user_id']`` מגיע לפעמים כמחרוזת."""
    monkeypatch.setenv("ADMIN_USER_IDS", "5")
    assert user_roles.is_admin("5") is True


def test_garbage_user_id_is_false_not_crash(monkeypatch):
    monkeypatch.setenv("ADMIN_USER_IDS", "5")
    assert user_roles.is_admin(None) is False
    assert user_roles.is_admin("not-a-number") is False


# -- is_premium --

def test_premium_reads_its_own_env(monkeypatch):
    monkeypatch.setenv("ADMIN_USER_IDS", "5")
    monkeypatch.setenv("PREMIUM_USER_IDS", "9")
    assert user_roles.is_premium(9) is True
    assert user_roles.is_premium(5) is False
    assert user_roles.is_admin(9) is False


# -- אין עותקים --

def test_both_consumers_point_at_the_same_function():
    """``app`` ו-``code_tools_api`` מייצאים את הפונקציה עצמה, לא עותק.

    זו הבדיקה שנופלת אם מישהו יחזיר מימוש מקומי לאחד מהם. ``is`` ולא
    ``==`` בכוונה: שני מימושים זהים היו עוברים השוואת התנהגות ונכשלים כאן.
    """
    pytest.importorskip("flask")
    from webapp import code_tools_api

    assert code_tools_api._is_admin is user_roles.is_admin
    assert code_tools_api._is_premium is user_roles.is_premium


def test_app_still_exports_the_names():
    """``from webapp.app import is_admin`` חייב להמשיך לעבוד.

    שלושה מודולים עושים את זה היום: ``themes_api``, ``routes/repo_browser``
    ו-``routes/auth_routes``.
    """
    pytest.importorskip("flask")
    from webapp import app as webapp_app

    assert webapp_app.is_admin is user_roles.is_admin
    assert webapp_app.is_premium is user_roles.is_premium
