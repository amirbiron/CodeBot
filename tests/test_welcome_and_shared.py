import types


class FakeUsersCollection:
    def __init__(self):
        self.docs = {}

    def update_one(self, query, update, upsert=False):
        user_id = query.get('user_id')
        doc = self.docs.setdefault(user_id, {'user_id': user_id})
        for key, value in (update.get('$setOnInsert') or {}).items():
            doc.setdefault(key, value)
        for key, value in (update.get('$set') or {}).items():
            doc[key] = value
        return types.SimpleNamespace(acknowledged=True)

    def find_one(self, query):
        return self.docs.get(query.get('user_id'))


class FakeCodeSnippetsCollection:
    def __init__(self):
        self.docs = []

    def find_one(self, query, sort=None):
        user_id = query.get('user_id')
        file_name = query.get('file_name')
        for doc in reversed(self.docs):
            if doc.get('user_id') == user_id and doc.get('file_name') == file_name:
                return doc
        return None

    def insert_one(self, doc):
        stored = dict(doc)
        if '_id' not in stored:
            stored['_id'] = f"fake-{len(self.docs)+1}"
        self.docs.append(stored)
        return types.SimpleNamespace(inserted_id=stored['_id'])


def _stub_cache():
    class _Cache:
        def invalidate_user_cache(self, *args, **kwargs):
            return None

        def invalidate_file_related(self, *args, **kwargs):
            return None

    return _Cache()


def test_welcome_ack_sets_flag(monkeypatch):
    import webapp.app as app_mod

    fake_users = FakeUsersCollection()
    fake_db = types.SimpleNamespace(users=fake_users)

    monkeypatch.setattr(app_mod, 'get_db', lambda: fake_db)
    monkeypatch.setattr(app_mod, 'cache', _stub_cache())

    app_mod.app.testing = True
    with app_mod.app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = 123
            sess['user_data'] = {}
        resp = client.post('/api/welcome/ack')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data and data['ok'] is True
        stored = fake_users.docs[123]
        assert stored['has_seen_welcome_modal'] is True
        with client.session_transaction() as sess:
            assert sess['user_data']['has_seen_welcome_modal'] is True


def test_save_shared_file_creates_snippet(monkeypatch):
    import webapp.app as app_mod

    fake_users = FakeUsersCollection()
    fake_snippets = FakeCodeSnippetsCollection()
    fake_db = types.SimpleNamespace(users=fake_users, code_snippets=fake_snippets)

    monkeypatch.setattr(app_mod, 'get_db', lambda: fake_db)
    monkeypatch.setattr(app_mod, 'cache', _stub_cache())
    monkeypatch.setattr(
        app_mod,
        'get_internal_share',
        lambda share_id: {
            'share_id': share_id,
            'code': '# מדריך
התחלה מהירה',
            'language': 'markdown',
            'file_name': 'welcome-guide.md',
            'description': 'מדריך תפעול WebApp',
        },
    )

    app_mod.app.testing = True
    with app_mod.app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = 7
            sess['user_data'] = {'id': 7}
        resp = client.post('/api/shared/save', json={'share_id': 'welcome'})
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload and payload['ok'] is True
        assert fake_snippets.docs, 'snippet should be inserted'
        saved = fake_snippets.docs[0]
        assert saved['user_id'] == 7
        assert saved['programming_language'] == 'markdown'
        assert saved['file_name'].lower().endswith('.md')
