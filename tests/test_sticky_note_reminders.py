import unittest
from unittest.mock import MagicMock
from datetime import datetime, timedelta, timezone

from flask import Flask, session, json

# Import blueprint and helpers to patch
import importlib
sticky_mod = importlib.import_module('webapp.sticky_notes_api')


class _StubColl:
    def __init__(self):
        self._docs = []
        self.calls = []

    # index methods
    def create_index(self, *args, **kwargs):
        return None

    def create_indexes(self, *args, **kwargs):
        return None

    # basic CRUD mocks
    def find_one(self, query, *args, **kwargs):
        # very naive match on _id and user_id
        for d in self._docs:
            ok = True
            for k, v in query.items():
                if d.get(k) != v:
                    ok = False
                    break
            if ok:
                return d
        return None

    def insert_one(self, doc):
        self._docs.append(dict(doc))
        class R: inserted_id = '1'
        return R()

    def update_one(self, filt, update, upsert=False):
        # simplistic: record call and simulate matched
        self.calls.append(('update_one', filt, update, upsert))
        class R:
            matched_count = 1
            modified_count = 1
        return R()

    def delete_one(self, filt):
        self.calls.append(('delete_one', filt))
        class R:
            deleted_count = 1
        return R()

    def find(self, query):
        # Support simple comparisons for remind_at
        def _match(doc):
            for k, v in query.items():
                if isinstance(v, dict) and '$in' in v:
                    if doc.get(k) not in v['$in']:
                        return False
                elif isinstance(v, dict) and '$lte' in v:
                    if not (isinstance(doc.get(k), datetime) and doc.get(k) <= v['$lte']):
                        return False
                else:
                    if doc.get(k) != v:
                        return False
            return True
        return [d for d in self._docs if _match(d)]

    def sort(self, *args, **kwargs):
        return self


class _StubDB:
    def __init__(self):
        self.sticky_notes = _StubColl()
        self.note_reminders = _StubColl()


def _make_app(db_stub):
    app = Flask(__name__)
    app.secret_key = 'test-secret'

    # Monkeypatch get_db used inside the module
    sticky_mod.get_db = lambda: db_stub

    app.register_blueprint(sticky_mod.sticky_notes_bp)
    return app


class TestNoteRemindersAPI(unittest.TestCase):
    def setUp(self):
        self.db = _StubDB()
        # Seed a note for the user
        self.user_id = 123
        self.note_id = '507f1f77bcf86cd799439011'
        self.db.sticky_notes._docs.append({'_id': self.note_id, 'user_id': self.user_id, 'file_id': 'file-1'})
        self.app = _make_app(self.db)
        self.client = self.app.test_client()

    def _login(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.user_id
            sess['user_data'] = {'first_name': 'Test'}

    def test_set_reminder_preset_1h(self):
        self._login()
        r = self.client.post(f'/api/sticky-notes/note/{self.note_id}/reminder', json={'preset': '1h', 'tz': 'UTC'})
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data['ok'])
        # ensure DB update called
        calls = [c for c in self.db.note_reminders.calls if c[0] == 'update_one']
        self.assertTrue(calls)

    def test_get_reminder_empty(self):
        self._login()
        r = self.client.get(f'/api/sticky-notes/note/{self.note_id}/reminder')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json().get('reminder'), None)

    def test_snooze_updates_time(self):
        self._login()
        # create existing reminder
        self.db.note_reminders._docs.append({
            '_id': 'r1', 'user_id': self.user_id, 'note_id': self.note_id,
            'status': 'pending', 'remind_at': datetime.now(timezone.utc)+timedelta(minutes=1)
        })
        r = self.client.post(f'/api/sticky-notes/note/{self.note_id}/snooze', json={'minutes': 10})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()['ok'])

    def test_summary_has_due(self):
        self._login()
        now = datetime.now(timezone.utc)
        self.db.note_reminders._docs.append({
            '_id': 'r1', 'user_id': self.user_id, 'note_id': self.note_id, 'file_id': 'file-1',
            'status': 'pending', 'remind_at': now - timedelta(minutes=1), 'ack_at': None
        })
        r = self.client.get('/api/sticky-notes/reminders/summary')
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data['ok'])
        self.assertTrue(data['has_due'])
        self.assertIsNotNone(data['next'])

    def test_delete_reminder(self):
        self._login()
        r = self.client.delete(f'/api/sticky-notes/note/{self.note_id}/reminder')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()['ok'])


if __name__ == '__main__':
    unittest.main()
