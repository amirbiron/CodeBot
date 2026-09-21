"""כרטיס הפוש בדשבורד: ספירה שנכשלה היא "לא ידוע", לא 0.

מאז #3430 אפס הוא גם הערך הבריא של "תזכורות בהמתנה", ולכן כשל שמוצג כ-0
נראה בדיוק כמו "הכול נקי". שני מסלולים נמדדים: הבונה מחזיר ``None`` ורושם
אזהרה עם traceback, והעמוד עצמו מרנדר "לא ידוע" במקום מספר.
"""
import logging
import types

import pytest


class _Cursor:
    def sort(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def __iter__(self):
        return iter([])


class _Quiet:
    """אוסף שלא מוצא כלום ולא נכשל."""

    def count_documents(self, *_a, **_k):
        return 0

    def find(self, *_a, **_k):
        return _Cursor()

    def find_one(self, *_a, **_k):
        return {}

    def aggregate(self, *_a, **_k):
        return []

    def distinct(self, *_a, **_k):
        return []


class _Boom(_Quiet):
    """אוסף התזכורות כשהמסד לא עונה."""

    def count_documents(self, *_a, **_k):
        raise RuntimeError('mongo is down')

    def find(self, *_a, **_k):
        raise RuntimeError('mongo is down')


class _FakeDB:
    def __init__(self, reminders):
        self.note_reminders = reminders

    def __getattr__(self, _name):
        return _Quiet()


def test_a_failed_count_is_unknown_not_zero(caplog):
    import webapp.app as app_mod

    with caplog.at_level(logging.WARNING, logger='webapp.app'):
        card = app_mod._build_push_card(_FakeDB(_Boom()), 7)
    assert card['pending_count'] is None, card['pending_count']
    traced = [r for r in caplog.records if 'pending' in r.getMessage() and r.exc_info]
    assert traced, [r.getMessage() for r in caplog.records]


def test_a_healthy_count_is_still_a_number():
    import webapp.app as app_mod

    card = app_mod._build_push_card(_FakeDB(_Quiet()), 7)
    assert card['pending_count'] == 0


@pytest.fixture
def dashboard_client(monkeypatch):
    """הדשבורד האמיתי, עם מסד שבו ספירת התזכורות נופלת — ובלי לעקוף את הכרטיס."""
    import webapp.app as app_mod

    app_mod.app.testing = True
    app_mod.app.config['SECRET_KEY'] = 'test'
    monkeypatch.setattr(app_mod, 'get_db', lambda: _FakeDB(_Boom()))
    monkeypatch.setattr(app_mod, 'get_mirror_service', lambda: types.SimpleNamespace(
        get_last_commit_info=lambda *_a, **_k: None,
    ))
    monkeypatch.setattr(app_mod, '_build_activity_timeline', lambda *_a, **_k: {
        'groups': [], 'feed': [], 'filters': [], 'compact_limit': 0, 'has_events': False, 'updated_at': '',
    })
    monkeypatch.setattr(app_mod, '_build_notes_snapshot', lambda *_a, **_k: {
        'notes': [], 'total': 0, 'has_notes': False,
    })
    monkeypatch.setattr(app_mod, '_load_whats_new', lambda *_a, **_k: {
        'features': [], 'has_features': False, 'total': 0,
    })
    monkeypatch.setattr(app_mod, 'user_stats', types.SimpleNamespace(
        get_all_time_stats=lambda: {'total_users': 1, 'active_today': 1, 'active_week': 1},
        get_weekly_stats=lambda: [],
    ))
    with app_mod.app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = 7
            sess['user_data'] = {'id': 7, 'first_name': 'Test'}
        yield client


def test_the_dashboard_renders_unknown_instead_of_zero(dashboard_client):
    resp = dashboard_client.get('/dashboard')
    assert resp.status_code == 200, resp.status_code
    html = resp.get_data(as_text=True)
    assert 'תזכורות בהמתנה' in html
    tile = html.split('תזכורות בהמתנה', 1)[1][:240]
    assert 'לא ידוע' in tile, tile
    assert '<strong>0</strong>' not in tile, tile
