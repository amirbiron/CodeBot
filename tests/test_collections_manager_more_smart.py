from types import SimpleNamespace
import pytest

from database.collections_manager import CollectionsManager


class AggSpy:
    def __init__(self, rows):
        self.rows = rows
        self.last_pipeline = None
    def aggregate(self, pipeline, allowDiskUse=True):
        self.last_pipeline = pipeline
        return list(self.rows)


class DB:
    def __init__(self):
        self.user_collections = SimpleNamespace(create_indexes=lambda *a, **k: None, insert_one=lambda doc: SimpleNamespace(inserted_id='id1'))
        self.collection_items = SimpleNamespace(create_indexes=lambda *a, **k: None)
        self.code_snippets = AggSpy([{ 'file_name': 'a.py' }])


@pytest.fixture()
def mgr() -> CollectionsManager:
    return CollectionsManager(DB())


def _get_match_from_pipeline(mgr: CollectionsManager):
    pl = mgr.code_snippets.last_pipeline  # type: ignore[attr-defined]
    assert isinstance(pl, list) and pl and '$match' in pl[0]
    return pl[0]['$match']


def test_compute_tags_only(mgr: CollectionsManager):
    rules = { 'tags': ['t1', 't2'] }
    _ = mgr.compute_smart_items(1, rules, limit=5)
    mt = _get_match_from_pipeline(mgr)
    assert isinstance(mt.get('tags'), dict) and '$in' in mt['tags']
    assert set(mt['tags']['$in']) == {'t1', 't2'}


def test_compute_repo_tag_only(mgr: CollectionsManager):
    rules = { 'repo_tag': 'repo:core' }
    _ = mgr.compute_smart_items(2, rules, limit=5)
    mt = _get_match_from_pipeline(mgr)
    assert mt.get('tags') == 'repo:core'


def test_compute_tags_and_repo_tag_appends(mgr: CollectionsManager):
    rules = { 'tags': ['t1'], 'repo_tag': 'repo:core' }
    _ = mgr.compute_smart_items(3, rules, limit=5)
    mt = _get_match_from_pipeline(mgr)
    assert isinstance(mt.get('tags'), dict) and '$in' in mt['tags']
    assert set(mt['tags']['$in']) == {'t1', 'repo:core'}
