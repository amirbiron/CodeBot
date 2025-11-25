from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from webapp import app as webapp_app


class StubCursor(list):
    def sort(self, key, direction=None):
        if isinstance(key, list):
            key, direction = key[0]
        reverse = bool(direction and direction < 0)
        return StubCursor(sorted(self, key=lambda doc: doc.get(key) or datetime.min.replace(tzinfo=timezone.utc), reverse=reverse))

    def limit(self, n):
        return StubCursor(self[:n])


class StubCollection:
    def __init__(self, docs):
        self._docs = docs

    def find(self, *args, **kwargs):
        return StubCursor([doc.copy() for doc in self._docs])


def test_build_activity_timeline_groups(monkeypatch):
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    files = [
        {
            '_id': 'f1',
            'file_name': 'main.py',
            'programming_language': 'python',
            'updated_at': now - timedelta(minutes=5),
            'created_at': now - timedelta(days=1),
            'version': 2,
            'description': '',
        },
    ]
    reminders = [
        {
            'note_id': 'n1',
            'status': 'pending',
            'remind_at': now + timedelta(minutes=30),
            'updated_at': now - timedelta(minutes=2),
            'last_push_success_at': None,
            'ack_at': None,
        }
    ]
    notes = [
        {
            '_id': 'n1',
            'content': 'תזכורת לבדוק בדיקות',
            'file_id': 'f1',
            'updated_at': now - timedelta(minutes=3),
        }
    ]
    stub_db = SimpleNamespace(
        code_snippets=StubCollection(files),
        note_reminders=StubCollection(reminders),
        sticky_notes=StubCollection(notes),
    )
    monkeypatch.setattr(webapp_app.TimeUtils, "format_relative_time", lambda *_: "unit-test")

    timeline = webapp_app._build_activity_timeline(stub_db, user_id=1, active_query=None, now=now)

    assert timeline['has_events'] is True
    assert timeline['filters'][0]['count'] == len(timeline['feed'])
    groups = {group['id']: group for group in timeline['groups']}
    assert 'files' in groups and groups['files']['events']
    assert 'push' in groups and groups['push']['events']
    assert 'backups' not in groups
    assert timeline['feed'][0]['group'] in {'files', 'push'}


def test_build_activity_timeline_empty(monkeypatch):
    stub_db = SimpleNamespace(
        code_snippets=StubCollection([]),
        note_reminders=StubCollection([]),
        sticky_notes=StubCollection([]),
    )
    monkeypatch.setattr(webapp_app.TimeUtils, "format_relative_time", lambda *_: "unit-test")

    timeline = webapp_app._build_activity_timeline(stub_db, user_id=1, active_query=None, now=datetime.now(timezone.utc))

    assert timeline['has_events'] is False
    assert all(not group['events'] for group in timeline['groups'])
