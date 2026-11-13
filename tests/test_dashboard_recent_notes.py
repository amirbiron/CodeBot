"""כרטיס "פתקים אחרונים" בדשבורד: איפה כל פתק יושב, קישור לפתק, ובלי "ועוד N פתקים ממתינים".

עד נובמבר 2026 הכרטיס הכיר רק פתקים על קובץ: כל פתק אחר — לוח, ריפו, ארכיון — הוצג "ללא
קובץ", וגם פתק על קובץ גדול, כי השם חופש רק ב-``code_snippets``. הקישור היחיד היה "פתח קובץ"
לגרסה שעליה הפתק נוצר, ובסוף הרשימה "ועוד N פתקים ממתינים" ספר את כל הפתקים של המשתמש.

הדמות כאן מכבדות היטלה: דמה שמחזירה את כל המסמך הייתה מעבירה את הטסטים גם כששדה יעד חסר
בהיטלה של ``_build_notes_snapshot``, ובמסד האמיתי הפתק היה יוצא "מיקום לא ידוע". והן רושמות
כל שאילתה, כדי לבדוק שהשמות נקראים בשאילתה אחת ולא אחת לכל פתק.
"""
from datetime import datetime, timedelta, timezone

import pytest

jinja2 = pytest.importorskip("jinja2")

from bson import ObjectId  # noqa: E402
from pymongo.errors import AutoReconnect  # noqa: E402

USER, OTHER = 7, 99
NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, key, direction):
        self._docs.sort(key=lambda d: d.get(key) or datetime.min.replace(tzinfo=timezone.utc),
                        reverse=direction == -1)
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    def __iter__(self):
        return iter(self._docs)


def _project(doc, projection):
    if not projection:
        return dict(doc)
    return {k: v for k, v in doc.items() if k == '_id' or projection.get(k)}


class _Coll:
    """אוסף: ``find`` עם שוויון ו-``$in``, היטלה, ורישום של כל שאילתה. ``fail`` — חריגה לזרוק."""

    def __init__(self, docs=(), *, fail=None):
        self.docs = list(docs)
        self.fail = fail
        self.calls = []
        self.counted = 0

    @staticmethod
    def _matches(doc, filt):
        for key, cond in filt.items():
            if isinstance(cond, dict) and '$in' in cond:
                if doc.get(key) not in cond['$in']:
                    return False
            elif doc.get(key) != cond:
                return False
        return True

    def find(self, filt=None, projection=None):
        self.calls.append((filt, projection))
        if self.fail is not None:
            raise self.fail
        return _Cursor(_project(d, projection) for d in self.docs if self._matches(d, filt or {}))

    def count_documents(self, *_a, **_k):
        self.counted += 1
        return len(self.docs)


class _DB:
    def __init__(self, notes=(), boards=(), snippets=(), large=()):
        self.sticky_notes = _Coll(notes)
        self.note_boards = _Coll(boards)
        self.code_snippets = _Coll(snippets)
        self.large_files = _Coll(large)


def _note(minutes_ago=5, **fields):
    return dict({
        '_id': ObjectId(), 'user_id': USER, 'title': 'פתק',
        'updated_at': NOW - timedelta(minutes=minutes_ago),
    }, **fields)


def _snapshot(db):
    import webapp.app as app_mod

    return app_mod._build_notes_snapshot(db, USER)


def _locations(db):
    return [n['location'] for n in _snapshot(db)['notes']]


# -- פתקי לוח ----------------------------------------------------------------------------


def test_a_board_note_shows_the_board_it_sits_on():
    board = ObjectId()
    db = _DB([_note(board_id=str(board))], boards=[{'_id': board, 'user_id': USER, 'name': 'רעיונות'}])
    assert _locations(db) == ['לוח רעיונות']


def test_a_board_name_that_already_starts_with_the_word_is_not_prefixed_again():
    """"לוח עבודה" — השם של לוח ברירת המחדל — ולא "לוח לוח עבודה". הכלל הוא על המילה הראשונה,
    ולכן "לוחות שנה" מקבל את המילה לפניו."""
    from note_boards import DEFAULT_BOARD_NAME

    work, years = ObjectId(), ObjectId()
    db = _DB(
        [_note(1, board_id=str(work)), _note(2, board_id=str(years))],
        boards=[
            {'_id': work, 'user_id': USER, 'name': DEFAULT_BOARD_NAME},
            {'_id': years, 'user_id': USER, 'name': 'לוחות שנה'},
        ],
    )
    assert _locations(db) == [DEFAULT_BOARD_NAME, 'לוח לוחות שנה']


def test_a_board_that_is_not_found_shows_only_the_word():
    """לוח שאינו קיים, או שאינו של המשתמש: אין שם להציג, וגם לא שם של לוח של מישהו אחר."""
    foreign = ObjectId()
    db = _DB(
        [_note(1, board_id=str(ObjectId())), _note(2, board_id=str(foreign))],
        boards=[{'_id': foreign, 'user_id': OTHER, 'name': 'של מישהו אחר'}],
    )
    assert _locations(db) == ['לוח', 'לוח']


def test_board_names_are_read_in_one_query_of_the_users_boards():
    ideas, work = ObjectId(), ObjectId()
    db = _DB(
        [_note(1, board_id=str(ideas)), _note(2, board_id=str(work)), _note(3, board_id=str(ideas))],
        boards=[
            {'_id': ideas, 'user_id': USER, 'name': 'רעיונות'},
            {'_id': work, 'user_id': USER, 'name': 'משימות'},
        ],
    )

    assert _locations(db) == ['לוח רעיונות', 'לוח משימות', 'לוח רעיונות']
    assert len(db.note_boards.calls) == 1
    query, projection = db.note_boards.calls[0]
    assert query['user_id'] == USER and projection == {'name': 1}
    assert sorted(map(str, query['_id']['$in'])) == sorted([str(ideas), str(work)])


# -- פתקים על קובץ -----------------------------------------------------------------------


def test_a_file_note_shows_the_name_it_carries_without_looking_it_up():
    """השם ששמור בפתק הוא גם השם שהקישור הקבוע פותח את הגרסה האחרונה שלו."""
    db = _DB([_note(file_id=str(ObjectId()), file_name='מדריך.md')])
    assert _locations(db) == ['מדריך.md']
    assert db.code_snippets.calls == [] and db.large_files.calls == []


def test_a_file_note_without_a_stored_name_gets_it_from_the_file():
    file_id = ObjectId()
    db = _DB(
        [_note(file_id=str(file_id))],
        snippets=[{'_id': file_id, 'user_id': USER, 'file_name': 'ישן.py'}],
    )
    assert _locations(db) == ['ישן.py']
    assert db.large_files.calls == [], "נמצא ב-code_snippets — אין סיבה לחפש בקבצים הגדולים"


def test_a_note_on_a_large_file_shows_the_file_name():
    """על קובץ גדול השם לא נשמר בפתק (``_resolve_scope`` מחפש רק ב-``code_snippets``)."""
    file_id = ObjectId()
    db = _DB(
        [_note(file_id=str(file_id))],
        large=[{'_id': file_id, 'user_id': USER, 'file_name': 'גדול.log'}],
    )
    assert _locations(db) == ['גדול.log']
    (query, projection), = db.large_files.calls
    assert query['user_id'] == USER and projection == {'file_name': 1}


def test_file_names_come_only_from_the_users_own_files():
    file_id = ObjectId()
    db = _DB(
        [_note(file_id=str(file_id))],
        snippets=[{'_id': file_id, 'user_id': OTHER, 'file_name': 'של מישהו אחר.py'}],
    )
    assert _locations(db) == ['קובץ']


# -- ריפו, ארכיון ויעד פגום -------------------------------------------------------------


def test_a_repo_note_and_an_archived_note_say_where_they_are():
    db = _DB([
        _note(1, repo_name='CodeBot', repo_path='webapp/app.py'),
        _note(2, archived_at=NOW - timedelta(days=1)),
    ])
    assert _locations(db) == ['ריפו: CodeBot/webapp/app.py', 'ארכיון']


def test_a_document_without_a_valid_target_is_not_guessed():
    """בלי יעד, או עם שני יעדים — ``note_target_ref`` אומר ``unknown``, וכך גם השורה."""
    db = _DB([
        _note(1),
        _note(2, file_id=str(ObjectId()), board_id=str(ObjectId())),
    ])
    assert _locations(db) == ['מיקום לא ידוע', 'מיקום לא ידוע']


# -- הקישור, והספירה שהוסרה ---------------------------------------------------------------


def test_each_note_links_to_its_permalink():
    """הקישור הוא ``/note/<id>``, והנתיב נבדק מול הראוט שמגיש אותו — לא מול מחרוזת."""
    import webapp.app as app_mod

    note = _note(board_id=str(ObjectId()))
    (item,) = _snapshot(_DB([note]))['notes']

    assert item['url'] == f"/note/{note['_id']}"
    endpoint, args = app_mod.app.url_map.bind('localhost').match(item['url'])
    assert endpoint == 'boards_ui.note_permalink' and args == {'note_id': str(note['_id'])}


def test_the_card_does_not_count_all_the_notes():
    db = _DB([_note(i, board_id=str(ObjectId())) for i in range(12)])
    snapshot = _snapshot(db)
    assert len(snapshot['notes']) == 10
    assert 'total' not in snapshot and db.sticky_notes.counted == 0


# -- כשלים --------------------------------------------------------------------------------


def test_a_failure_to_read_board_names_is_logged_and_the_note_still_shows(caplog):
    db = _DB([_note(board_id=str(ObjectId()))])
    db.note_boards.fail = AutoReconnect("down")

    with caplog.at_level('WARNING'):
        assert _locations(db) == ['לוח']
    assert any('board names lookup failed' in r.getMessage() for r in caplog.records)


def test_a_failure_to_read_file_names_is_logged_and_the_note_still_shows(caplog):
    db = _DB([_note(file_id=str(ObjectId()))])
    db.code_snippets.fail = AutoReconnect("down")

    with caplog.at_level('WARNING'):
        assert _locations(db) == ['קובץ']
    assert any('file names lookup failed' in r.getMessage() for r in caplog.records)


def test_a_bug_while_reading_board_names_is_not_swallowed():
    """רק כשל של המסד נבלע (``PyMongoError``). באג — כאן ``TypeError`` — עולה הלאה."""
    db = _DB([_note(board_id=str(ObjectId()))])
    db.note_boards.fail = TypeError("bug, not a database failure")

    with pytest.raises(TypeError, match="bug, not a database failure"):
        _snapshot(db)


# -- התבנית -------------------------------------------------------------------------------


def _render(notes_snapshot):
    # הרינדור המשותף לבדיקות הדשבורד — ``tests/_dashboard_render.py``.
    from _dashboard_render import render_dashboard

    return render_dashboard(notes_snapshot=notes_snapshot)


def _notes_card(html):
    start = html.index('data-card="notes"')
    return html[start:html.index('</article>', start)]


def test_the_card_links_each_title_to_the_note_in_a_new_tab_and_shows_where_it_is():
    board = ObjectId()
    notes = [_note(i, title=f'פתק {i}', board_id=str(board)) for i in range(12)]
    db = _DB(notes, boards=[{'_id': board, 'user_id': USER, 'name': 'רעיונות'}])

    card = _notes_card(_render(_snapshot(db)))

    # בלשונית חדשה, כדי שהדשבורד יישאר פתוח
    assert (f'<a class="note-title" href="/note/{notes[0]["_id"]}" target="_blank" rel="noopener">'
            'פתק 0</a>') in card
    assert card.count('class="note-title"') == 10
    assert 'לוח רעיונות' in card
    assert 'ממתינים' not in card, "לא 'ועוד N פתקים ממתינים', וגם לא 'ממתינים לתזכורת' בכותרת המשנה"
    assert 'פתח קובץ' not in card
    assert 'ללא קובץ' not in card
