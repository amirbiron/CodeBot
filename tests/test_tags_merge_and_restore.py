import io
import zipfile
from datetime import datetime, timezone


class _FakeInsertResult:
    def __init__(self, inserted_id=True):
        self.inserted_id = inserted_id


class _FakeCollection:
    def __init__(self, existing_doc):
        self._existing_doc = existing_doc
        self.last_insert = None

    def find_one(self, query, sort=None):
        # Simulate latest version query by file_name and user_id
        return dict(self._existing_doc) if self._existing_doc else None

    def insert_one(self, payload):
        # capture the inserted document for assertions
        self.last_insert = dict(payload)
        return _FakeInsertResult(True)


class _FakeManager:
    def __init__(self, existing_doc):
        self.collection = _FakeCollection(existing_doc)
        self.large_files_collection = None


def _make_repository_with_existing(existing_doc):
    from database.repository import Repository
    fake = _FakeManager(existing_doc)
    return Repository(fake), fake


def test_save_file_preserves_existing_repo_when_no_new_repo_tag():
    # existing carries repo tag; extra has no repo tag => must keep existing repo
    existing = {
        'user_id': 123,
        'file_name': 'a.py',
        'version': 3,
        'tags': ['repo:owner/old', 'util', 'alpha'],
        'description': 'desc',
    }
    repo, fake = _make_repository_with_existing(existing)

    ok = repo.save_file(user_id=123, file_name='a.py', code='print(1)', programming_language='python', extra_tags=['beta', 'util'])
    assert ok is True
    inserted = fake.collection.last_insert
    assert inserted is not None
    tags = inserted.get('tags')
    # non-repo tags merged & dedup, repo tag preserved from existing
    assert 'repo:owner/old' in tags
    assert 'beta' in tags
    assert 'util' in tags


def test_save_file_uses_new_repo_when_provided():
    existing = {
        'user_id': 123,
        'file_name': 'a.py',
        'version': 1,
        'tags': ['repo:owner/old', 'x'],
        'description': 'd',
    }
    repo, fake = _make_repository_with_existing(existing)
    ok = repo.save_file(user_id=123, file_name='a.py', code='x', programming_language='python', extra_tags=['repo:owner/new', 'y'])
    assert ok is True
    inserted = fake.collection.last_insert
    tags = inserted.get('tags')
    # should choose the new repo tag
    assert 'repo:owner/new' in tags
    assert 'repo:owner/old' not in tags
    assert 'y' in tags


def test_restore_from_backup_passes_single_repo_tag(monkeypatch, tmp_path):
    # Prepare a ZIP with one file and metadata
    zpath = tmp_path / 'bkp.zip'
    with zipfile.ZipFile(zpath, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('index.html', '<html></html>')
        zf.writestr('metadata.json', '{"backup_id":"t1"}')

    calls = []

    class _DBStub:
        def save_file(self, user_id, file_name, code, programming_language, extra_tags=None):
            calls.append({'user_id': user_id, 'file_name': file_name, 'tags': list(extra_tags or [])})
            return True

    import sys, types
    fake_db_module = types.SimpleNamespace(db=_DBStub())
    monkeypatch.setitem(sys.modules, 'database', fake_db_module)

    from file_manager import backup_manager
    res = backup_manager.restore_from_backup(user_id=999, backup_path=str(zpath), overwrite=True, purge=False, extra_tags=['repo:A', 'repo:B', 'misc'])
    assert isinstance(res, dict)
    # ensure save_file was called and only single repo tag was passed (the last one)
    assert calls, 'save_file should be called'
    tags = calls[0]['tags']
    assert any(t == 'repo:B' for t in tags)
    assert not any(t == 'repo:A' for t in tags)
