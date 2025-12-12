from bson import ObjectId

import webapp.app as webapp_app
from services.diff_service import DiffService


class FakeCollection:
    def __init__(self, docs):
        self.docs = docs

    def find_one(self, query, *args, **kwargs):
        for doc in self.docs:
            if all(doc.get(k) == v for (k, v) in query.items()):
                return doc
        return None


class FakeDB:
    def __init__(self, docs):
        self.code_snippets = FakeCollection(docs)


def _build_docs():
    left = {
        '_id': ObjectId(),
        'user_id': 10,
        'file_name': 'demo.py',
        'version': 1,
        'code': 'print("a")\n',
        'updated_at': '2025-01-01',
    }
    right = {
        '_id': ObjectId(),
        'user_id': 10,
        'file_name': 'demo.py',
        'version': 2,
        'code': 'print("a")\nprint("b")\n',
        'updated_at': '2025-01-02',
    }
    other = {
        '_id': ObjectId(),
        'user_id': 10,
        'file_name': 'other.py',
        'version': 3,
        'code': 'pass\n',
    }
    return [left, right, other]


def _setup(monkeypatch, docs):
    fake_db = FakeDB(docs)
    service = DiffService(fake_db)
    monkeypatch.setattr('webapp.compare_api._get_db', lambda: fake_db)
    monkeypatch.setattr('webapp.compare_api._get_diff_service', lambda: service)
    app = webapp_app.app
    app.testing = True
    return app, docs


def test_compare_versions_requires_auth():
    app = webapp_app.app
    app.testing = True
    with app.test_client() as client:
        resp = client.get('/api/compare/versions/foo')
        assert resp.status_code == 401


def test_compare_versions_returns_diff(monkeypatch):
    docs = _build_docs()
    app, docs = _setup(monkeypatch, docs)
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = 10
        file_id = str(docs[1]['_id'])
        resp = client.get(f'/api/compare/versions/{file_id}?left=1&right=2')
        assert resp.status_code == 200
        payload = resp.get_json()
        assert 'lines' in payload
        assert payload['stats']['added'] == 1


def test_compare_files_validates_payload(monkeypatch):
    app, docs = _setup(monkeypatch, _build_docs())
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = 10
        resp = client.post('/api/compare/files', json={'left_file_id': ''})
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'missing_file_ids'


def test_compare_files_returns_diff(monkeypatch):
    docs = _build_docs()
    app, docs = _setup(monkeypatch, docs)
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = 10
        left_id = str(docs[0]['_id'])
        right_id = str(docs[1]['_id'])
        resp = client.post('/api/compare/files', json={'left_file_id': left_id, 'right_file_id': right_id})
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload['stats']['added'] == 1


def test_compare_raw_requires_auth():
    app = webapp_app.app
    app.testing = True
    with app.test_client() as client:
        resp = client.post('/api/compare/diff', json={})
        assert resp.status_code == 401


def test_compare_raw_returns_diff(monkeypatch):
    dummy_service = DiffService(None)
    monkeypatch.setattr('webapp.compare_api._get_diff_service', lambda: dummy_service)
    app = webapp_app.app
    app.testing = True
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = 5
        resp = client.post('/api/compare/diff', json={'left_content': 'a', 'right_content': 'a\nb'})
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload['stats']['added'] == 1
