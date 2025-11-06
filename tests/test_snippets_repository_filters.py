from database.repository import Repository


class _SnippetsCollection:
    def __init__(self, docs):
        self._docs = list(docs)

    def find(self, match=None, sort=None):
        # naive filter
        rows = []
        for d in self._docs:
            ok = True
            for k, v in (match or {}).items():
                if k == 'status':
                    ok = ok and d.get('status') == v
                elif k == 'language':
                    ok = ok and d.get('language') == v
                elif k == '$or':
                    cond_ok = False
                    for cond in v:
                        for f, spec in cond.items():
                            if '$regex' in spec:
                                pat = spec['$regex']
                                s = (d.get(f) or '')
                                if spec.get('$options') == 'i':
                                    pat = pat.lower()
                                    s = s.lower()
                                if pat in s:
                                    cond_ok = True
                    ok = ok and cond_ok
            if ok:
                rows.append(d)
        # sorting supported on approved_at desc
        if sort:
            for key, direction in reversed(sort):
                rows.sort(key=lambda x: x.get(key), reverse=(direction == -1))
        return rows

    def count_documents(self, match):
        return len(self.find(match))


class _Mgr:
    def __init__(self, docs):
        self.snippets_collection = _SnippetsCollection(docs)


def test_public_snippets_filters_and_pagination():
    docs = [
        {"title": "Alpha", "description": "d", "code": "x", "language": "py", "status": "approved", "approved_at": 3},
        {"title": "Bravo", "description": "d", "code": "print('a')", "language": "js", "status": "approved", "approved_at": 2},
        {"title": "Charlie", "description": "alpha", "code": "c", "language": "py", "status": "approved", "approved_at": 1},
    ]
    repo = Repository(_Mgr(docs))

    # language filter
    items, total = repo.list_public_snippets(language='py', page=1, per_page=10)
    assert total == 2 and all(it['language'] == 'py' for it in items)

    # q search (title/description/code)
    items2, total2 = repo.list_public_snippets(q='alpha', page=1, per_page=10)
    assert total2 == 2  # Alpha in title and alpha in description

    # pagination
    items3, total3 = repo.list_public_snippets(page=1, per_page=1)
    assert total3 == 3 and len(items3) == 1
