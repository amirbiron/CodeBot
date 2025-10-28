import types
import pytest

# טסטי API בסיסיים ל-Collections (Flask test_client)

@pytest.fixture()
def client(monkeypatch):
    import importlib
    import os as _os
    _os.environ.setdefault("FEATURE_MY_COLLECTIONS", "1")
    app_mod = importlib.import_module('webapp.app')
    app = app_mod.app
    # הפעלת דגל
    try:
        from config import config as cfg
        if hasattr(cfg, 'FEATURE_MY_COLLECTIONS'):
            setattr(cfg, 'FEATURE_MY_COLLECTIONS', True)
    except Exception:
        pass
    # החלפת get_manager בפייק (באמצעות monkeypatch להבטחת ניקיון בין טסטים)
    import webapp.collections_api as api
    class _FakeManager:
        def __init__(self):
            self._store = {}
            self._items = {}
        def create_collection(self, user_id, name, description="", mode="manual", rules=None, **kw):
            if not name:
                return {"ok": False, "error": "שם האוסף חייב להיות 1..80 תווים"}
            cid = str(len(self._store) + 1)
            col = {"id": cid, "user_id": user_id, "name": name, "slug": "slug-" + cid, "description": description, "mode": mode, "rules": rules or {}, "items_count": 0, "pinned_count": 0, "is_active": True}
            self._store[cid] = col; self._items[cid] = []
            return {"ok": True, "collection": col}
        def get_collection(self, user_id, collection_id):
            col = self._store.get(collection_id)
            if not col:
                return {"ok": False, "error": "האוסף לא נמצא"}
            return {"ok": True, "collection": col}
        def list_collections(self, user_id, limit=100, skip=0):
            cols = list(self._store.values())[skip:skip+limit]
            return {"ok": True, "collections": cols, "count": len(self._store)}
        def update_collection(self, user_id, collection_id, **fields):
            col = self._store.get(collection_id)
            if not col:
                return {"ok": False, "error": "האוסף לא נמצא"}
            col.update({k: v for k, v in fields.items() if k in {"name", "description", "mode", "rules"}})
            return {"ok": True, "collection": col}
        def delete_collection(self, user_id, collection_id):
            if collection_id in self._store:
                self._store[collection_id]["is_active"] = False
                return {"ok": True}
            return {"ok": False, "error": "האוסף לא נמצא"}
        def get_collection_items(self, user_id, collection_id, page=1, per_page=20, include_computed=True):
            items = list(self._items.get(collection_id, []))
            start = (page - 1) * per_page
            return {"ok": True, "items": items[start:start+per_page], "page": page, "per_page": per_page, "total_manual": len(items), "total_computed": 0}
        def add_items(self, user_id, collection_id, items):
            arr = self._items.setdefault(collection_id, [])
            for it in items:
                arr.append({"id": str(len(arr)+1), **it})
            return {"ok": True, "added": len(items)}
        def remove_items(self, user_id, collection_id, items):
            arr = self._items.get(collection_id, [])
            to_remove = {(it.get('source', 'regular'), it.get('file_name')) for it in items}
            left = [x for x in arr if (x.get('source', 'regular'), x.get('file_name')) not in to_remove]
            self._items[collection_id] = left
            return {"ok": True, "deleted": len(arr) - len(left)}
        def reorder_items(self, user_id, collection_id, order):
            return {"ok": True, "updated": len(order)}
    _fake = _FakeManager()
    monkeypatch.setattr(api, 'get_manager', lambda: _fake, raising=True)
    # סשן משתמש
    app.testing = True
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess['user_id'] = 321
            # שמור כ-dict כדי שיהיה serializable
            sess['user_data'] = {'first_name': 'Api'}
        yield c


def test_api_create_list_get_update_delete(client):
    r = client.post('/api/collections', json={'name': 'API Test', 'mode': 'manual'})
    assert r.status_code == 200
    data = r.get_json(); assert data['ok']
    cid = data['collection']['id']

    r = client.get('/api/collections?limit=10&skip=0')
    assert r.status_code == 200 and r.get_json()['ok']

    r = client.get(f'/api/collections/{cid}')
    assert r.status_code == 200 and r.get_json()['ok']

    r = client.put(f'/api/collections/{cid}', json={'description':'d'})
    assert r.status_code == 200 and r.get_json()['ok']

    r = client.delete(f'/api/collections/{cid}')
    assert r.status_code == 200 and r.get_json()['ok']


def test_api_items_flow_and_reorder(client):
    # create
    r = client.post('/api/collections', json={'name': 'With Items', 'mode': 'manual'})
    cid = r.get_json()['collection']['id']

    # add items
    r = client.post(f'/api/collections/{cid}/items', json={'items': [
        {'source':'regular','file_name':'f1.py'},
        {'source':'regular','file_name':'f2.py'}
    ]})
    assert r.status_code == 200 and r.get_json()['ok']

    # list items
    r = client.get(f'/api/collections/{cid}/items?page=1&per_page=20&include_computed=true')
    assert r.status_code == 200 and r.get_json()['ok']

    # reorder
    r = client.put(f'/api/collections/{cid}/reorder', json={'order': [
        {'source':'regular','file_name':'f2.py'},
        {'source':'regular','file_name':'f1.py'}
    ]})
    assert r.status_code == 200 and r.get_json()['ok']

    # remove one
    r = client.delete(f'/api/collections/{cid}/items', json={'items':[{'source':'regular','file_name':'f2.py'}]})
    assert r.status_code == 200 and r.get_json()['ok']


def test_api_4xx(client):
    assert client.get('/api/collections?limit=bad&skip=0').status_code == 400
    assert client.get('/api/collections/invalid-id').get_json()['ok'] is False
    assert client.post('/api/collections', json={'name':''}).get_json()['ok'] is False
    assert client.post('/api/collections/notid/items', json={'items': []}).status_code == 200
    assert client.put('/api/collections/notid/reorder', json={'order': []}).status_code == 200
