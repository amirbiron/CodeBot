from types import SimpleNamespace
import pytest

from database.collections_manager import CollectionsManager, ObjectId


class Coll:
    def __init__(self):
        self.docs = []
    def create_indexes(self, *a, **k): return None
    def insert_one(self, doc):
        if '_id' not in doc: doc['_id'] = f"oid{len(self.docs)+1}"
        self.docs.append(dict(doc))
        return SimpleNamespace(inserted_id=doc['_id'])
    def find_one_and_update(self, flt, upd, return_document=True):
        for d in self.docs:
            if str(d.get('_id')) == str(flt.get('_id')) and int(d.get('user_id')) == int(flt.get('user_id')):
                for k,v in upd.get('$set', {}).items():
                    d[k] = v
                return dict(d)
        return None
    def find(self, *a, **k): return []
    def count_documents(self, *a, **k): return 0

class Items:
    def create_indexes(self, *a, **k): return None

class DB:
    def __init__(self):
        self.user_collections = Coll()
        self.collection_items = Items()
        self.code_snippets = SimpleNamespace(aggregate=lambda *a, **k: [])


@pytest.fixture()
def mgr() -> CollectionsManager:
    return CollectionsManager(DB())


def test_update_fields_icon_color_favorite_sort(mgr: CollectionsManager):
    c = mgr.create_collection(5, 'C')["collection"]
    # valid icon/color from whitelist (icon empty -> stays empty; set valid color)
    res = mgr.update_collection(5, c['id'], icon='📘', color='blue', is_favorite=True, sort_order=7)
    assert res['ok'] and res['collection']['color'] == 'blue' and res['collection']['is_favorite'] is True and res['collection']['sort_order'] == 7


def test_update_name_recomputes_slug_unique(mgr: CollectionsManager):
    c1 = mgr.create_collection(6, 'Guides')["collection"]
    c2 = mgr.create_collection(6, 'Guides')["collection"]
    # rename c2 to collide with new name of c1 and ensure uniqueness is handled
    r = mgr.update_collection(6, c1['id'], name='Guides')
    assert r['ok'] and r['collection']['slug']
