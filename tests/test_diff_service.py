from bson import ObjectId

from services.diff_service import DiffService


class FakeCollection:
    def __init__(self, docs):
        self.docs = docs

    def find_one(self, query, *args, **kwargs):
        for doc in self.docs:
            match = True
            for key, value in query.items():
                if doc.get(key) != value:
                    match = False
                    break
            if match:
                return doc
        return None


class FakeDB:
    def __init__(self, docs):
        self.code_snippets = FakeCollection(docs)


def _build_docs(user_id=7):
    file_id = ObjectId()
    return [
        {
            '_id': file_id,
            'user_id': user_id,
            'file_name': 'demo.py',
            'version': 1,
            'code': 'print("hi")\n',
            'updated_at': '2025-01-01T00:00:00Z',
        },
        {
            '_id': ObjectId(),
            'user_id': user_id,
            'file_name': 'demo.py',
            'version': 2,
            'code': 'print("hi")\nprint("bye")\n',
            'updated_at': '2025-01-02T00:00:00Z',
        },
    ]


def test_compute_diff_counts_changes():
    service = DiffService()
    result = service.compute_diff('a\nb\n', 'a\nc\n')
    assert result.stats['unchanged'] == 1
    assert result.stats['modified'] == 1


def test_compare_versions_returns_result():
    docs = _build_docs()
    service = DiffService(FakeDB(docs))
    result = service.compare_versions(7, 'demo.py', 1, 2)
    assert result is not None
    assert result.stats['added'] == 1
    assert result.left_info['version'] == 1
    assert result.right_info['version'] == 2


def test_compare_versions_missing_returns_none():
    service = DiffService(FakeDB(_build_docs()))
    assert service.compare_versions(7, 'demo.py', 1, 99) is None


def test_compare_files_requires_same_user():
    docs = _build_docs()
    other_doc = {
        '_id': ObjectId(),
        'user_id': 99,
        'file_name': 'other.py',
        'version': 1,
        'code': 'pass',
    }
    docs.append(other_doc)
    service = DiffService(FakeDB(docs))
    result = service.compare_files(7, str(docs[0]['_id']), str(other_doc['_id']))
    assert result is None

