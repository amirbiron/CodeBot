"""בדיקות לפרמלינק ``/note/<id>`` ולזרימת התזכורות של פתקי לוח.

הבעיה שהשלב הזה פותר: כל צרכן הרכיב את יעד ההתראה בעצמו מהמזהים שהיו לו
ביד. ``sw.js`` בנה ``/md/<file_id>``, והפעמון ב-``base.html`` עשה אותו דבר
מאחורי ``if (fileId)``. לפתק לוח אין ``file_id``, ולכן ההתראה נחתה בשורש
האתר ולחיצה על הפעמון לא עשתה כלום.

התיקון הוא בונה אחד — הראוט הזה. הצרכנים פותחים ``/note/<id>`` ולא צריכים
לדעת דבר על סוג הפתק.
"""

import pytest

pytest.importorskip("flask")


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
    from pathlib import Path

    sw = Path('webapp/static/sw.js').read_text(encoding='utf-8')

    assert '`/note/${encodeURIComponent(noteId)}`' in sw
    # הפולבק להתראות ישנות שכבר בתור נשאר, אבל רק כענף שני
    idx_note = sw.index('/note/${encodeURIComponent(noteId)}')
    idx_md = sw.index('/md/${encodeURIComponent(fileId)}', idx_note - 400)
    assert idx_note < idx_md


def test_service_worker_version_was_bumped():
    """בלי bump אי אפשר לאשש בפרודקשן שהגרסה החדשה נטענה."""
    from pathlib import Path

    sw = Path('webapp/static/sw.js').read_text(encoding='utf-8')

    assert "const SW_VERSION = '2.0.4';" not in sw
    assert "const SW_VERSION = '2.1.0';" in sw


def test_bell_uses_the_permalink():
    from pathlib import Path

    base = Path('webapp/templates/base.html').read_text(encoding='utf-8')

    assert "window.location.href = '/note/' + encodeURIComponent(noteId)" in base
