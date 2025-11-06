import types
from datetime import datetime, timezone

from database.repository import Repository


class _CursorStub:
    def __init__(self, docs):
        self._docs = list(docs)
        self._skip = 0
        self._limit = None

    def skip(self, n):
        self._skip = int(n or 0)
        return self

    def limit(self, n):
        self._limit = int(n or 0)
        return self

    def __iter__(self):
        data = self._docs[self._skip:]
        if self._limit is not None:
            data = data[: self._limit]
        return iter(data)


class _SnippetsCollectionStub:
    def __init__(self):
        self.docs = []
        self._id_seq = 0

    def _next_id(self):
        self._id_seq += 1
        return str(self._id_seq)

    def insert_one(self, doc):
        d = dict(doc)
        d.setdefault('_id', self._next_id())
        self.docs.append(d)
        return types.SimpleNamespace(inserted_id=d['_id'])

    def update_one(self, query, update):
        matched = 0
        modified = 0
        for d in self.docs:
            ok = True
            for k, v in query.items():
                if k == '_id':
                    ok = ok and (str(d.get('_id')) == str(v))
                else:
                    ok = ok and (d.get(k) == v)
            if ok:
                matched += 1
                # apply $set
                fields = (update or {}).get('$set', {})
                for k, v in fields.items():
                    d[k] = v
                modified += 1
                break
        return types.SimpleNamespace(matched_count=matched, modified_count=modified)

    def count_documents(self, match):
        return len(list(self._filter(match)))

    def find(self, match=None, sort=None):
        docs = list(self._filter(match or {}))
        # basic sort support on approved_at desc
        if sort:
            for key, direction in reversed(sort):
                docs.sort(key=lambda x: x.get(key), reverse=(direction == -1))
        return _CursorStub(docs)

    def _filter(self, match):
        for d in self.docs:
            ok = True
            for k, v in (match or {}).items():
                if k == '$or':
                    # support regex contains (case-insensitive)
                    cond_ok = False
                    for cond in v:
                        for f, spec in cond.items():
                            if not isinstance(spec, dict):
                                continue
                            pat = str(spec.get('$regex') or '')
                            if not pat:
                                continue
                            val = str(d.get(f) or '')
                            if spec.get('$options') == 'i':
                                pat = pat.lower()
                                val = val.lower()
                            if pat in val:
                                cond_ok = True
                    ok = ok and cond_ok
                else:
                    ok = ok and (d.get(k) == v)
            if ok:
                yield d


class _ManagerStub:
    def __init__(self):
        self.snippets_collection = _SnippetsCollectionStub()


def test_repository_snippet_crud_basic():
    repo = Repository(_ManagerStub())
    sid = repo.create_snippet_proposal(
        title='My Snip', description='desc', code='print(1)', language='python', user_id=123
    )
    assert sid is not None

    # initially pending
    pend = repo.list_pending_snippets(limit=10, skip=0)
    assert len(pend) == 1

    # approve
    assert repo.approve_snippet(sid, admin_id=1) is True

    # after approve, pending empty
    pend2 = repo.list_pending_snippets(limit=10, skip=0)
    assert len(pend2) == 0

    # public list contains item, sortable by approved_at
    items, total = repo.list_public_snippets(q='my', language='python', page=1, per_page=10)
    assert total == 1
    assert items and items[0]['title'] == 'My Snip'
    assert isinstance(items[0].get('approved_at'), (datetime, type(None)))

    # reject flow
    sid2 = repo.create_snippet_proposal(
        title='Other', description='x', code='//', language='js', user_id=10
    )
    assert repo.reject_snippet(sid2, admin_id=2, reason='not good') is True
    # rejected item should not be public
    items2, total2 = repo.list_public_snippets(page=1, per_page=10)
    assert total2 == 1
