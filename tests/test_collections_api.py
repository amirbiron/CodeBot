import types
import pytest


class FakeManager:
    def __init__(self):
        self._store = {}
        self._items = {}

    def create_collection(self, user_id, name, description="", mode="manual", rules=None, **kw):
        if not name:
            return {"ok": False, "error": "שם האוסף חייב להיות 1..80 תווים"}
        cid = str(len(self._store) + 1)
        col = {
            "id": cid,
            "user_id": user_id,
            "name": name,
            "slug": "slug-" + cid,
            "description": description,
            "mode": mode,
            "rules": rules or {},
            "items_count": 0,
            "pinned_count": 0,
            "is_active": True,
        }
        self._store[cid] = col
        self._items[cid] = []
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
        # No-op for fake
        return {"ok": True, "updated": len(order)}


# אפליקציית Flask ו-monkeypatch של get_manager
@pytest.fixture(scope="function")
def app_client(monkeypatch):
    import importlib
    app_mod = importlib.import_module('webapp.app')
    app = app_mod.app
    # דגל פיצ'ר
    try:
        from config import config as cfg
        if hasattr(cfg, 'FEATURE_MY_COLLECTIONS'):
            setattr(cfg, 'FEATURE_MY_COLLECTIONS', True)
    except Exception:
        pass
    # החלפת get_manager בפייק
    import webapp.collections_api as api
    fake = FakeManager()
    monkeypatch.setattr(api, 'get_manager', lambda: fake, raising=True)
    app.testing = True
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess['user_id'] = 123
            # משתמש ב-dict כדי להיות serializable ל-JSON בסשן
            sess['user_data'] = {'first_name': 'Test'}
        yield c


def test_collections_crud_list(app_client):
    r = app_client.post('/api/collections', json={'name': '📁 נבחרים', 'mode': 'manual'})
    assert r.status_code == 200
    data = r.get_json(); assert data and data.get('ok')
    cid = data['collection']['id']

    r = app_client.get(f'/api/collections/{cid}')
    assert r.status_code == 200
    d2 = r.get_json(); assert d2['ok']

    r = app_client.get('/api/collections?limit=50&skip=0')
    assert r.status_code == 200
    d3 = r.get_json(); assert d3['ok'] and isinstance(d3['collections'], list)

    r = app_client.put(f'/api/collections/{cid}', json={'description': 'קבצים חשובים'})
    assert r.status_code == 200
    d4 = r.get_json(); assert d4['ok']

    r = app_client.get(f'/api/collections/{cid}/items')
    assert r.status_code == 200
    d5 = r.get_json(); assert d5['ok'] and isinstance(d5['items'], list)

    r = app_client.post(f'/api/collections/{cid}/items', json={'items': [{'source': 'regular', 'file_name': 'algo.py'}]})
    assert r.status_code == 200
    d6 = r.get_json(); assert d6['ok'] and d6['added'] == 1

    r = app_client.delete(f'/api/collections/{cid}')
    assert r.status_code == 200
    d7 = r.get_json(); assert d7['ok']


def test_collections_validation_and_auth(app_client):
    import importlib
    app_mod = importlib.import_module('webapp.app')
    app = app_mod.app
    app.testing = True
    with app.test_client() as c:
        r = c.post('/api/collections', json={'name': 'x'})
        assert r.status_code == 401

    r = app_client.post('/api/collections', json={'name': ''})
    assert r.status_code == 200
    d = r.get_json(); assert not d['ok']

    r = app_client.get('/api/collections?limit=bad&skip=0')
    assert r.status_code == 400

    r = app_client.get('/api/collections/invalid-id')
    assert r.status_code == 200
    d2 = r.get_json(); assert not d2['ok']
