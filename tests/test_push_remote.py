import unittest
import os
import sys
from flask import Flask
import importlib

push_mod = importlib.import_module('webapp.push_api')


class _StubResp:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
    def json(self):
        return self._body


class _StubRequestsModule:
    def __init__(self, scenario):
        self._scenario = scenario
    def post(self, url, data=None, headers=None, timeout=None):
        if self._scenario == 'success':
            return _StubResp(200, { 'ok': True })
        if self._scenario == '404':
            return _StubResp(200, { 'ok': False, 'status': 404, 'error': 'not found' })
        if self._scenario == '401':
            return _StubResp(200, { 'ok': False, 'status': 401, 'error': 'unauthorized' })
        if self._scenario == '5xx':
            return _StubResp(502, {})
        if self._scenario == 'timeout':
            # Simulate requests raising Timeout
            class _Timeout(Exception):
                pass
            raise _Timeout('timeout')
        return _StubResp(200, { 'ok': False })


class _StubColl:
    def __init__(self):
        self._docs = []
    def create_index(self, *args, **kwargs):
        return None
    def create_indexes(self, *args, **kwargs):
        return None
    def update_one(self, filt, update, upsert=False):
        return type('R', (), { 'matched_count': 1, 'modified_count': 1 })()
    def delete_many(self, filt):
        return type('R', (), { 'deleted_count': 0 })()
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


class TestPushRemote(unittest.TestCase):
    def setUp(self):
        self.db = _StubDB()
        # one subscription
        self.user_id = 42
        self.db.push_subscriptions._docs.append({
            'user_id': self.user_id,
            'endpoint': 'https://example.com/ep/777',
            'keys': { 'p256dh': 'k', 'auth': 'a' },
            'subscription': { 'endpoint': 'https://example.com/ep/777', 'keys': { 'p256dh': 'k', 'auth': 'a' } }
        })
        os.environ['PUSH_REMOTE_DELIVERY_ENABLED'] = 'true'
        os.environ['PUSH_DELIVERY_URL'] = 'https://worker.example'
        os.environ['PUSH_DELIVERY_TOKEN'] = 'ABC'
        os.environ['VAPID_PUBLIC_KEY'] = 'BExxxxTestKey'
        self.app = _make_app(self.db)
        self.client = self.app.test_client()
        # login
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.user_id
            sess['user_data'] = {'first_name': 'Tester'}
        self._orig_requests = sys.modules.get('requests')

    def tearDown(self):
        # restore
        if self._orig_requests is None:
            sys.modules.pop('requests', None)
        else:
            sys.modules['requests'] = self._orig_requests

    def _run_with_scenario(self, scenario):
        sys.modules['requests'] = _StubRequestsModule(scenario)
        r = self.client.post('/api/push/test')
        self.assertEqual(r.status_code, 200)
        return r.get_json()

    def test_success(self):
        j = self._run_with_scenario('success')
        self.assertTrue(j['ok'])
        self.assertEqual(j['sent'], 1)

    def test_404(self):
        j = self._run_with_scenario('404')
        self.assertTrue(j['ok'])
        self.assertEqual(j['codes'].get(404), 1)

    def test_401(self):
        j = self._run_with_scenario('401')
        self.assertTrue(j['ok'])
        self.assertEqual(j['codes'].get(401), 1)

    def test_timeout(self):
        j = self._run_with_scenario('timeout')
        self.assertTrue(j['ok'])
        # status 0 indicates transport error
        self.assertGreaterEqual(len(j['errors']), 1)
        self.assertEqual(j['errors'][0]['status'], 0)


if __name__ == '__main__':
    unittest.main()
