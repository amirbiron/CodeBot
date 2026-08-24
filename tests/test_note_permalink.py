"""בדיקות לפרמלינק ``/note/<id>`` ולזרימת התזכורות של פתקי לוח.

הבעיה שהשלב הזה פותר: כל צרכן הרכיב את יעד ההתראה בעצמו מהמזהים שהיו לו
ביד. ``sw.js`` בנה ``/md/<file_id>``, והפעמון ב-``base.html`` עשה אותו דבר
מאחורי ``if (fileId)``. לפתק לוח אין ``file_id``, ולכן ההתראה נחתה בשורש
האתר ולחיצה על הפעמון לא עשתה כלום.

התיקון הוא בונה אחד — הראוט הזה. הצרכנים פותחים ``/note/<id>`` ולא צריכים
לדעת דבר על סוג הפתק.
"""

from pathlib import Path

import pytest

pytest.importorskip("flask")

REPO_ROOT = Path(__file__).resolve().parent.parent


def _repo_file(rel: str) -> str:
    """קורא קובץ יחסית לשורש הריפו ולא ל-cwd.

    pytest אינו מבטיח את ספריית העבודה, ובדיקה שקוראת נתיב יחסי הייתה
    נכשלת — או גרוע מזה, עוברת על קובץ אחר — כשמריצים אותה מתיקייה אחרת.
    """
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


class _Coll:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def find_one(self, query, projection=None):
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return doc
        return None


@pytest.fixture
def client(monkeypatch):
    from webapp import boards_ui
    from webapp.app import app

    notes = _Coll([
        {"_id": 1, "user_id": 7, "file_id": "file-abc"},
        {"_id": 2, "user_id": 7, "board_id": "board-xyz"},
        {"_id": 3, "user_id": 7},                      # פתק בלי יעד — לא אמור לקרות
        {"_id": 4, "user_id": 99, "file_id": "other"},  # של משתמש אחר
        {"_id": 5, "user_id": 7, "repo_name": "CodeBot", "repo_path": "webapp/app.py"},
        {"_id": 6, "user_id": 7, "repo_name": "CodeBot", "repo_path": "docs/a&b.rst"},
        {"_id": 7, "user_id": 7, "repo_name": "CodeBot"},   # חצי יעד — לא אמור לקרות
    ])
    db = type("DB", (), {"sticky_notes": notes})()

    monkeypatch.setattr(boards_ui, "ObjectId", lambda x: int(x))
    # ``get_db`` מיובא בתוך הפונקציה, ולכן מחליפים אותו במקור
    import webapp.app as webapp_app
    monkeypatch.setattr(webapp_app, "get_db", lambda: db)

    app.config['TESTING'] = True
    c = app.test_client()
    with c.session_transaction() as sess:
        sess['user_id'] = 7
    return c


def test_file_note_redirects_to_markdown_view(client):
    res = client.get('/note/1')

    assert res.status_code == 302
    assert res.headers['Location'] == '/md/file-abc?note=1'


def test_board_note_redirects_to_its_board(client):
    """זה המקרה שהיה שבור: פתק לוח נחת בשורש האתר."""
    res = client.get('/note/2')

    assert res.status_code == 302
    assert res.headers['Location'] == '/boards/board-xyz?note=2'


def test_note_without_target_falls_back_to_boards(client):
    res = client.get('/note/3')

    assert res.status_code == 302
    assert res.headers['Location'] == '/boards'


def test_foreign_note_is_not_disclosed(client):
    """פתק של משתמש אחר מקבל את אותה תשובה כמו פתק שנמחק.

    אחרת הראוט היה מדליף אם מזהה מסוים קיים במערכת.
    """
    res = client.get('/note/4')

    assert res.status_code == 302
    assert res.headers['Location'] == '/boards'


def test_deleted_note_falls_back_to_boards(client):
    res = client.get('/note/999')

    assert res.status_code == 302
    assert res.headers['Location'] == '/boards'


def test_guest_keeps_the_note_in_next():
    """סשן שפג מחזיר את המשתמש לפתק אחרי ההתחברות, ולא לשורש."""
    from webapp.app import app

    app.config['TESTING'] = True
    res = app.test_client().get('/note/abc')

    assert res.status_code == 302
    assert 'next=/note/abc' in res.headers['Location']


# -- הצרכנים --

def test_service_worker_opens_the_permalink():
    """``sw.js`` מפסיק לבנות URL ממזהים.

    נופל אם מישהו יחזיר את בניית ``/md/<file_id>`` כמסלול הראשי.
    """
    sw = _repo_file('webapp/static/sw.js')

    assert '`/note/${encodeURIComponent(noteId)}`' in sw
    # הפולבק להתראות ישנות שכבר בתור נשאר, אבל רק כענף שני.
    # החיפוש מתחיל אחרי המופע הראשון — offset שלילי היה נספר מסוף
    # המחרוזת ומחפש במקום הלא נכון.
    idx_note = sw.index('/note/${encodeURIComponent(noteId)}')
    idx_md = sw.index('/md/${encodeURIComponent(fileId)}', idx_note)
    assert idx_note < idx_md


def test_service_worker_version_was_bumped():
    """בלי bump אי אפשר לאשש בפרודקשן שהגרסה החדשה נטענה."""
    import re

    sw = _repo_file('webapp/static/sw.js')

    m = re.search(r"const SW_VERSION = '([\d.]+)';", sw)
    assert m, "SW_VERSION לא נמצא"
    version = tuple(int(x) for x in m.group(1).split('.'))
    # השוואה לגרסה שקדמה לשינוי, ולא לערך מדויק — כך שה-bump הבא לא
    # יפיל את הבדיקה, אבל ויתור על bump כן.
    assert version > (2, 0, 4), f"SW_VERSION={m.group(1)} לא הועלה"


def test_bell_uses_the_permalink():
    base = _repo_file('webapp/templates/base.html')

    assert "window.location.href = '/note/' + encodeURIComponent(noteId)" in base


def test_push_projection_includes_board_id():
    """ה-projection של שולח ה-push שולף ``board_id``.

    באג אמיתי שהיה כאן: השדה נוסף ל-payload אבל לא ל-projection, ולכן
    ``r.get("board_id")`` החזיר תמיד מחרוזת ריקה — כלומר ההתראה על פתק
    לוח נשלחה בלי היעד שלה. שדה שנוסף לפלט ולא למקור הוא בדיוק סוג
    הכשל שנראה עובד עד שבודקים.
    """
    text = _repo_file("webapp/push_api.py")

    projection = text[text.index("    projection = {"):]
    projection = projection[:projection.index("}")]
    assert '"board_id": 1' in projection


def test_repo_note_redirects_to_the_repo_browser(client):
    """**זה המקרה שהיה שבור אחרי הוספת היעד השלישי.**

    ``note_permalink`` הכיר ``file_id`` ו-``board_id`` בלבד, ולכן פתק על
    קובץ בריפו נפל אל ``/boards`` — לחיצה על תזכורת הביאה את המשתמש
    ללוחות במקום לקובץ שהפתק יושב עליו.

    היעד הוא SPA: הריפו ב-query והקובץ ב-hash, בדיוק כפי ש-``updateUrlHash``
    בונה.

    נופל אם הראוט מפסיק להכיר פתקי ריפו.
    """
    res = client.get('/note/5')

    assert res.status_code == 302
    assert res.headers['Location'] == '/repo/?repo=CodeBot&note=5#file=webapp/app.py'


def test_repo_note_target_is_url_encoded(client):
    """נתיב עם ``&`` חייב לעבור קידוד, אחרת הוא שובר את מבנה ה-URL.

    **דווקא ``&`` ולא רווח:** Werkzeug מקודד רווחים בכותרת ``Location``
    בעצמו (נמדד), ולכן נתיב עם רווח היה עובר גם בלי ``quote`` — טסט
    שנראה מגן ואינו מגן. ``&`` אינו מקודד, ובלעדיו ``#file=docs/a&b.rst``
    מתפרק ב-``URLSearchParams`` לשני פרמטרים והקובץ פשוט לא נפתח.

    הלוכסנים **אינם** מקודדים בכוונה: הם מבנה הנתיב, לא תו בתוך שם.
    """
    res = client.get('/note/6')

    assert res.status_code == 302
    assert res.headers['Location'] == '/repo/?repo=CodeBot&note=6#file=docs/a%26b.rst'


def test_half_repo_target_falls_back_to_boards(client):
    """``repo_name`` בלי ``repo_path`` אינו יעד — לא בונים ממנו קישור."""
    res = client.get('/note/7')

    assert res.status_code == 302
    assert res.headers['Location'] == '/boards'
