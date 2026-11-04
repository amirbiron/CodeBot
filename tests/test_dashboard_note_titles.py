"""הדשבורד מציג פתק בשם שלו — בכרטיס הפוש, בציר הזמן וב"פתקים אחרונים".

שלושתם נשענים על ``_dashboard_note_title``, כלומר על ``sticky_notes_target.note_label`` —
אותה פונקציה של התראת הפוש וחלונית הפעמון: שם הפתק, ובלעדיו השורה הראשונה שלו. עד נובמבר
2026 הדשבורד לקח תמיד את השורה הראשונה, וגם ``_lookup_notes_map`` לא שלף את ``title``.

הדמה של ``sticky_notes`` מכבדת את ההיטלה: דמה שמחזירה את כל המסמך הייתה מעבירה את הטסט גם
כש-``title`` חסר בהיטלה, ובמסד האמיתי השם לא היה מגיע.
"""
from datetime import datetime, timedelta, timezone

from bson import ObjectId

USER = 7
NOTE_ID = ObjectId('64b7f1d2e3a4b5c6d7e8f901')
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *_a, **_k):
        return self

    def limit(self, n):
        self._docs = self._docs[:n] if n else self._docs
        return self

    def __iter__(self):
        return iter(self._docs)


def _project(doc, projection):
    if not projection:
        return dict(doc)
    return {k: v for k, v in doc.items() if k == '_id' or projection.get(k)}


class _Notes:
    """``sticky_notes``: מסנן לפי ``user_id`` ו-``_id``/``$in``, ומכבד היטלה."""

    def __init__(self, docs):
        self.docs = docs

    def _matches(self, doc, filt):
        if 'user_id' in filt and doc.get('user_id') != filt['user_id']:
            return False
        if '_id' in filt:
            cond = filt['_id']
            if isinstance(cond, dict) and '$in' in cond:
                return doc.get('_id') in cond['$in']
            return doc.get('_id') == cond
        return True

    def find(self, filt=None, projection=None, *_a, **_k):
        return _Cursor(_project(d, projection) for d in self.docs if self._matches(d, filt or {}))

    def count_documents(self, filt=None, *_a, **_k):
        return sum(1 for d in self.docs if self._matches(d, filt or {}))


class _Reminders:
    """``note_reminders`` עם תזכורת אחת שנשלחה וגם מתוזמנת — מספיק לשתי השורות בכרטיס."""

    def __init__(self, docs):
        self.docs = docs

    def find(self, *_a, **_k):
        return _Cursor(self.docs)

    def count_documents(self, *_a, **_k):
        return len(self.docs)


class _Quiet:
    def count_documents(self, *_a, **_k):
        return 0

    def find(self, *_a, **_k):
        return _Cursor([])

    def find_one(self, *_a, **_k):
        return None

    def aggregate(self, *_a, **_k):
        return []

    def distinct(self, *_a, **_k):
        return []


class _FakeDB:
    def __init__(self, notes, reminders=()):
        self.sticky_notes = _Notes(notes)
        self.note_reminders = _Reminders(list(reminders))

    def __getattr__(self, _name):
        return _Quiet()

    def __getitem__(self, name):
        return getattr(self, name)


def _note(**fields):
    return dict({
        '_id': NOTE_ID, 'user_id': USER, 'file_id': '', 'updated_at': NOW - timedelta(hours=1),
        'content': '# שורה ראשונה של הפתק\nשורה שנייה',
    }, **fields)


REMINDER = {
    '_id': 'r1', 'user_id': USER, 'note_id': str(NOTE_ID), 'status': 'pending',
    'remind_at': NOW + timedelta(hours=2), 'updated_at': NOW - timedelta(minutes=5),
    'last_push_success_at': NOW - timedelta(minutes=14), 'ack_at': None,
}


def _push_card(note):
    import webapp.app as app_mod

    return app_mod._build_push_card(_FakeDB([note], [REMINDER]), USER, now=NOW)


def _timeline_push_titles(note):
    import webapp.app as app_mod

    timeline = app_mod._build_activity_timeline(_FakeDB([note], [REMINDER]), USER, now=NOW)
    groups = {g['id']: g for g in timeline['groups']}
    return [ev['title'] for ev in groups['push']['events']]


def _snapshot_titles(note):
    import webapp.app as app_mod

    return [n['title'] for n in app_mod._build_notes_snapshot(_FakeDB([note]), USER)['notes']]


# -- כרטיס הפוש: "שליחה אחרונה" ו"התזכורת הבאה" ------------------------------------------


def test_the_push_card_shows_the_note_name():
    card = _push_card(_note(title='שם הפתק'))
    assert card['last_push']['title'] == 'שם הפתק', card['last_push']
    assert card['next_reminder']['title'] == 'שם הפתק', card['next_reminder']


def test_the_push_card_shows_the_first_line_of_a_note_without_a_name():
    card = _push_card(_note())
    assert card['last_push']['title'] == '# שורה ראשונה של הפתק'
    assert card['next_reminder']['title'] == '# שורה ראשונה של הפתק'


# -- ציר הזמן ו"פתקים אחרונים" ----------------------------------------------------------


def test_the_timeline_shows_the_note_name():
    assert _timeline_push_titles(_note(title='שם הפתק')) == ['תזכורת לפתק שם הפתק']


def test_recent_notes_show_the_note_name():
    assert _snapshot_titles(_note(title='שם הפתק')) == ['שם הפתק']


def test_a_note_with_nothing_to_show_says_so():
    """בלי שם, בלי תוכן ובלי עוגן — הטקסט של הדשבורד נשאר "פתק ללא תוכן"."""
    assert _snapshot_titles(_note(content='')) == ['פתק ללא תוכן']


def test_a_long_first_line_is_cut_at_the_name_ceiling():
    from sticky_notes_target import NOTE_LABEL_MAX_CHARS

    line = 'א' * (NOTE_LABEL_MAX_CHARS + 30)
    assert _snapshot_titles(_note(content=line + '\nעוד')) == ['א' * NOTE_LABEL_MAX_CHARS + '…']
