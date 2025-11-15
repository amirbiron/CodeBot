import unittest
import os
from flask import Flask, session
import importlib

push_mod = importlib.import_module('webapp.push_api')


class _StubColl:
    def __init__(self):
        self._docs = []
        self.calls = []

    def create_index(self, *args, **kwargs):
        return None

    def create_indexes(self, *args, **kwargs):
        return None

    def update_one(self, filt, update, upsert=False):
        # emulate upsert by endpoint+user
        uid = filt.get('user_id')
        ep = filt.get('endpoint')
        found = None
        for d in self._docs:
            if d.get('user_id') == uid and d.get('endpoint') == ep:
                found = d
                break
        docset = dict(update.get('$set') or {})
        if found is None:
            base = { 'user_id': uid, 'endpoint': ep }
            base.update(docset)
            self._docs.append(base)
        else:
            found.update(docset)
        class R:
            matched_count = 1
            modified_count = 1
        return R()

    def delete_many(self, filt):
        uid = filt.get('user_id')
        ep = filt.get('endpoint')
        before = len(self._docs)
        self._docs = [d for d in self._docs if not (d.get('user_id') == uid and (ep == d.get('endpoint') or (isinstance(ep, dict) and d.get('endpoint') in (ep.get('$in') or []))))]
        class R:
            deleted_count = before - len(self._docs)
        return R()

    def find(self, filt):
        class _Cursor:
            def __iter__(self_inner):
                return iter([d for d in self._docs if d.get('user_id') == filt.get('user_id')])
        return _Cursor()


class _StubDB:
    def __init__(self):
        self.push_subscriptions = _StubColl()
        self.sticky_notes = _StubColl()
        self.note_reminders = _StubColl()


def _make_app(db_stub):
    app = Flask(__name__)
    app.secret_key = 'test-secret'
    # Monkeypatch get_db used inside the module
    push_mod.get_db = lambda: db_stub
    app.register_blueprint(push_mod.push_bp)
    return app


class TestPushApi(unittest.TestCase):
    def setUp(self):
        self.db = _StubDB()
        os.environ['VAPID_PUBLIC_KEY'] = 'BExxxxTestKey'
        self.app = _make_app(self.db)
        self.client = self.app.test_client()
        self.user_id = 777

    def _login(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.user_id
            sess['user_data'] = {'first_name': 'Tester'}

    def test_public_key_endpoint(self):
        r = self.client.get('/api/push/public-key')
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['vapidPublicKey'], 'BExxxxTestKey')

    def test_subscribe_requires_auth(self):
        r = self.client.post('/api/push/subscribe', json={})
        self.assertEqual(r.status_code, 401)

    def test_subscribe_and_unsubscribe(self):
        self._login()
        sub = {
            'endpoint': 'https://example.com/ep/123',
            'keys': { 'p256dh': 'k', 'auth': 'a' }
        }
        r = self.client.post('/api/push/subscribe', json=sub)
        self.assertEqual(r.status_code, 201)
        self.assertTrue(self.db.push_subscriptions._docs)
        r2 = self.client.delete('/api/push/subscribe?endpoint='+sub['endpoint'])
        self.assertEqual(r2.status_code, 200)


if __name__ == '__main__':
    unittest.main()
