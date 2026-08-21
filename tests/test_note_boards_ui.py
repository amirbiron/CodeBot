"""בדיקות לעמודי לוחות הפתקים.

הבדיקות כאן מרנדרות את התבניות **באפליקציה האמיתית** ולא ב-Flask מינימלי.
הסיבה: רישום שני ה-blueprints ב-``webapp/app`` עטוף ב-``try/except`` שבולע
כשלים, ולכן ייבוא שבור או תבנית חסרה היו מדלגים בשקט — והבדיקות עם stub
היו ממשיכות לעבור.
"""

import pytest

pytest.importorskip("flask")


@pytest.fixture
def app_client():
    from webapp.app import app

    app.config['TESTING'] = True
    return app.test_client()


@pytest.fixture
def logged_in(app_client):
    with app_client.session_transaction() as sess:
        sess['user_id'] = 7
    return app_client


# -- רישום --

def test_board_pages_are_registered():
    """שני הראוטים קיימים במפת ה-URL של האפליקציה האמיתית."""
    from webapp.app import app

    rules = {str(r) for r in app.url_map.iter_rules()}
    assert '/boards' in rules
    assert '/boards/<board_id>' in rules


def test_board_api_routes_are_registered():
    from webapp.app import app

    rules = {str(r) for r in app.url_map.iter_rules()}
    assert '/api/note-boards' in rules
    assert '/api/note-boards/<board_id>' in rules
    assert '/api/sticky-notes/board/<board_id>' in rules


# -- הרשאות --

def test_boards_page_requires_login(app_client):
    """אורח מנותב להתחברות, עם ``next`` שמחזיר אותו לאותו עמוד."""
    res = app_client.get('/boards')

    assert res.status_code == 302
    assert '/login' in res.headers['Location']
    assert 'next=/boards' in res.headers['Location']


def test_single_board_page_keeps_the_id_in_next(app_client):
    res = app_client.get('/boards/abc123')

    assert res.status_code == 302
    assert 'next=/boards/abc123' in res.headers['Location']


# -- רינדור --

def test_boards_list_renders(logged_in):
    """התבנית מתרנדרת בפועל. תבנית חסרה או Jinja שבור ייפלו כאן."""
    res = logged_in.get('/boards')
    html = res.get_data(as_text=True)

    assert res.status_code == 200
    assert 'לוחות פתקים' in html
    assert 'css/note-boards.css' in html


def test_board_surface_renders_with_its_id(logged_in):
    """מזהה הלוח מגיע ל-JS דרך ``tojson``, ולא כהדבקת מחרוזת."""
    res = logged_in.get('/boards/507f1f77bcf86cd799439011')
    html = res.get_data(as_text=True)

    assert res.status_code == 200
    assert '"507f1f77bcf86cd799439011"' in html
    assert 'js/sticky-notes.js' in html
    assert 'boardSurface' in html


def test_board_id_is_escaped_not_interpolated(logged_in):
    """מזהה עוין אינו נשבר החוצה מה-JS.

    ``{{ board_id | tojson }}`` הוא מה שמונע את זה. בלעדיו מזהה שמכיל
    מרכאות או ``</script>`` היה מייצר XSS מאוחסן-בנתיב.
    """
    res = logged_in.get('/boards/x";alert(1)')
    html = res.get_data(as_text=True)

    assert res.status_code == 200
    # המרכאה מומלטת, ולכן ההשמה נשארת מחרוזת אחת ולא נשברת לקוד
    assert 'const BOARD_ID = "x\\";alert(1)"' in html
    assert 'const BOARD_ID = "x";alert(1)' not in html


# -- כניסה מהנאבבר --

def test_navbar_links_to_boards(logged_in):
    """בלי הפריט הזה הפיצ'ר קיים ב-URL ואף אחד לא מוצא אותו."""
    res = logged_in.get('/boards')
    html = res.get_data(as_text=True)

    assert 'href="/boards"' in html
    assert 'לוחות פתקים' in html
