"""הכפתור "צפייה ב-WebApp" בבוט: נבנה רק מ-``WEBAPP_URL``, ובלי כתובת תקינה אין כפתור.

עד אוקטובר 2026 הכפתור נבנה משלושה מקורות (קונפיג, ``WEBAPP_URL``, ``PUBLIC_BASE_URL``) ובסוף נפל לכתובת
של השירות באורגון, כך שבלי משתנה הוא הוביל לשם בשקט. היום יש קורא אחד (``webapp_url.py``) ואין ברירת מחדל.
"""

import pytest


class _Btn:
    def __init__(self, text, callback_data=None, url=None, **_):
        self.text = text
        self.callback_data = callback_data
        self.url = url


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    # מצב התחלה ידוע: שום כתובת בסביבה, וגם לא המשתנה שבוטל — כדי שטסט שבודק "חסר" לא יעבור בגלל ערך שדלף.
    monkeypatch.delenv('WEBAPP_URL', raising=False)
    monkeypatch.delenv('PUBLIC_BASE_URL', raising=False)


@pytest.fixture
def fv(monkeypatch):
    import handlers.file_view as fv

    monkeypatch.setattr(fv, 'InlineKeyboardButton', _Btn, raising=True)
    return fv


def test_button_points_at_webapp_url(monkeypatch, fv):
    monkeypatch.setenv('WEBAPP_URL', 'https://env.example')
    row = fv._get_webapp_button_row('abc', None)
    assert row[0].url == 'https://env.example/file/abc'


def test_search_fallback_when_there_is_no_id(monkeypatch, fv):
    monkeypatch.setenv('WEBAPP_URL', 'https://env.example')
    row = fv._get_webapp_button_row(None, 'demo file.py')
    assert row[0].url == 'https://env.example/files?q=demo+file.py#results'


def test_no_button_without_webapp_url(fv):
    """בלי משתנה אין כפתור — ולא כפתור לכתובת ישנה."""
    assert fv._get_webapp_button_row('id', 'name.py') is None


def test_public_base_url_is_not_a_source_anymore(monkeypatch, fv):
    """המשתנה שבוטל לא מחזיר את הכפתור בדלת אחורית."""
    monkeypatch.setenv('PUBLIC_BASE_URL', 'https://public.example')
    assert fv._get_webapp_button_row('id', None) is None


@pytest.mark.parametrize('value', ['https://env.example/', 'http://env.example', 'env.example'])
def test_no_button_with_an_invalid_webapp_url(monkeypatch, fv, value):
    monkeypatch.setenv('WEBAPP_URL', value)
    assert fv._get_webapp_button_row('id', None) is None


def test_conversation_handlers_uses_the_same_builder(fv):
    """אין עותק שני של הכפתור: ``conversation_handlers`` מייבא את הפונקציה מ-``handlers.file_view``."""
    import conversation_handlers as ch

    assert ch._get_webapp_button_row is fv._get_webapp_button_row
