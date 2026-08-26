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


def test_handwriting_toggle_is_per_board(logged_in):
    """מתג כתב-היד קיים, והמפתח שלו נושא את מזהה הלוח.

    **המפתח הוא מה שנבדק כאן, לא רק קיום המתג.** מפתח בלי מזהה הלוח היה
    הופך את ההעדפה לגלובלית: הדלקה בלוח אחד הייתה מדליקה בכולם, וזה כשל
    שנראה זהה לחלוטין בבדיקה ידנית על לוח יחיד.
    """
    res = logged_in.get('/boards/507f1f77bcf86cd799439011')
    html = res.get_data(as_text=True)

    assert res.status_code == 200
    assert 'handwritingToggle' in html
    assert "'board-handwriting:' + BOARD_ID" in html
    # אותה צורה בדיוק כמו שתי ההעדפות שכבר קיימות — אם אחת מהן תשתנה,
    # הבדיקה הזו מזכירה שגם החדשה צריכה להשתנות איתה.
    assert "'board-markdown:' + BOARD_ID" in html
    assert "'board-infinite:' + BOARD_ID" in html


def test_handwriting_font_is_loaded_for_board_pages(logged_in):
    """הגופן נטען, אחרת המתג מחליף למשפחה שאינה קיימת ושום דבר לא משתנה."""
    res = logged_in.get('/boards/507f1f77bcf86cd799439011')
    html = res.get_data(as_text=True)

    assert 'family=Gveret+Levin' in html
    # **התגית המלאה ולא תת-מחרוזת.** ``preconnect`` ל-gstatic נדרש כדי
    # שקובץ הגופן לא ישלם על handshake מלא בפעם הראשונה, והוא כבר קיים
    # עבור Heebo — אבל בדיקת הכלה של הכתובת לבדה הייתה עוברת גם אם היא
    # מופיעה בכל הקשר אחר בעמוד, למשל בתוך ``href`` של משהו לגמרי אחר.
    assert '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>' in html


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


# -- מעבר מהיר ולוחות נעוצים --
#
# **האסרשנים כאן מעוגנים לאלמנט, לא למחרוזת חופשית.** בגרסה ראשונה הם היו
# ``'boardSwitchBtn' in html`` וכדומה, ושלוש מוטציות עברו אותם: שם מזהה
# שהשתנה ל-``...BtnX`` עדיין מכיל את המקור כתת-מחרוזת, ו-``base.html``
# תורם בעצמו ``href="/boards"`` ושלושה ``role="dialog"`` שסיפקו את
# הבדיקות במקום התבנית הנבדקת.

def _tag_with_id(html, el_id):
    """התגית הפותחת של אלמנט לפי מזהה — או ``''`` אם אין כזה.

    מאפשר לבדוק תכונות **על האלמנט עצמו**, ולא במקום כלשהו בעמוד.
    """
    import re
    m = re.search(r'<[a-zA-Z]+[^>]*\bid="' + re.escape(el_id) + r'"[^>]*>', html)
    return m.group(0) if m else ''


def test_board_page_serves_the_quick_switch(logged_in):
    """הכפתור ושני המודאלים מוגשים בעמוד לוח בודד.

    נופל אם מזהה ישונה — כולל שינוי שמוסיף תו, כי המרכאה הסוגרת חלק
    מהחיפוש.
    """
    html = logged_in.get('/boards/507f1f77bcf86cd799439011').get_data(as_text=True)

    for el_id in ('boardSwitchBtn', 'boardSwitchTiles', 'boardPinManager', 'boardPinList'):
        assert _tag_with_id(html, el_id), f'חסר אלמנט עם id={el_id}'


def test_the_quick_switch_is_not_on_the_boards_list(logged_in):
    """עמוד ``/boards`` כבר מציג את כל הלוחות, ולכן אין בו קפיצה מהירה."""
    html = logged_in.get('/boards').get_data(as_text=True)

    assert not _tag_with_id(html, 'boardSwitchBtn')
    assert not _tag_with_id(html, 'boardPinManager')


def test_the_full_boards_link_stays_in_the_toolbar(logged_in):
    """הרשת נשארת — היא לעמוד המלא, והחדש לקפיצה מהירה. שני דברים שונים.

    **הבדיקה על הקישור שבסרגל הלוח**, ולא על ``href="/boards"`` כלשהו:
    ל-``base.html`` יש קישור כזה משלו בתפריט הקיצורים, והוא היה מספק
    בדיקה רחבה גם אם הקישור בסרגל נמחק.
    """
    import re

    html = logged_in.get('/boards/507f1f77bcf86cd799439011').get_data(as_text=True)
    # ``(.*?)</div>`` עוצר ב-``</div>`` **הראשון**, שהוא של הסרגל. הגרסה
    # הקודמת דרשה גם ``\s*<!--`` אחריו — אבל אחרי הסרגל בא ישירות
    # ``<div class="board-settings-modal"`` ולא הערה, ולכן הלכידה נמשכה
    # ובלעה את מודאל ההגדרות כולו: 3420 תווים במקום 2260. אז כפתור
    # שהיה עובר לתוך המודאל עדיין היה "נמצא בסרגל".
    toolbar = re.search(r'<div class="board-toolbar">(.*?)</div>', html, re.S)
    assert toolbar, 'סרגל הלוח לא נמצא'
    assert 'board-settings-modal' not in toolbar.group(1), 'הלכידה חורגת מהסרגל'
    inner = toolbar.group(1)

    assert 'href="/boards"' in inner          # הקישור לעמוד המלא
    assert 'id="boardSwitchBtn"' in inner     # והכפתור החדש, לצידו


def test_each_board_modal_declares_itself_as_a_dialog(logged_in):
    """``role="dialog"`` ו-``aria-modal`` הם מה שמצדיק את מלכודת הפוקוס.

    **נבדק על כל מודאל בנפרד**, ולא בספירה: ל-``base.html`` יש שלושה
    ``role="dialog"`` משלו, וספירה כוללת הייתה עוברת גם אם מודאל של
    הלוח מאבד את ההצהרה.
    """
    html = logged_in.get('/boards/507f1f77bcf86cd799439011').get_data(as_text=True)

    for el_id in ('boardSettings', 'boardSwitch', 'boardPinManager'):
        tag = _tag_with_id(html, el_id)
        assert 'role="dialog"' in tag, f'{el_id} אינו מוצהר כדיאלוג'
        assert 'aria-modal="true"' in tag, f'{el_id} חסר aria-modal'
