import types
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import pytest

# Minimal in-memory collection with aggregate stages used by get_favorites
class InMemoryResult:
    def __init__(self, inserted_id: Any = None, matched: int = 0, modified: int = 0):
        self.inserted_id = inserted_id
        self.matched_count = matched
        self.modified_count = modified

class InMemoryCollection:
    def __init__(self):
        self.docs: List[Dict[str, Any]] = []

    def insert_one(self, doc: Dict[str, Any]):
        d = dict(doc)
        d.setdefault('_id', f"{d.get('file_name','doc')}-{d.get('version',1)}")
        d.setdefault('is_active', True)
        self.docs.append(d)
        return InMemoryResult(inserted_id=d['_id'])

    def aggregate(self, pipeline: List[Dict[str, Any]], allowDiskUse: bool = False):
        data = list(self.docs)
        for stage in pipeline:
            if '$match' in stage:
                data = self._filter(stage['$match'], docs=data)
            elif '$sort' in stage:
                for key, direction in reversed(list(stage['$sort'].items())):
                    data.sort(key=lambda d: d.get(key, 0), reverse=(int(direction) < 0))
            elif '$group' in stage:
                spec = stage['$group']
                if spec.get('_id') == '$file_name' and 'latest' in spec:
                    latest_map: Dict[str, Dict[str, Any]] = {}
                    for d in data:
                        fn = d.get('file_name')
                        if fn not in latest_map or (d.get('version', 0) or 0) > (latest_map[fn].get('version', 0) or 0):
                            latest_map[fn] = d
                    data = [{'_id': fn, 'latest': latest_map[fn]} for fn in latest_map]
                elif spec.get('_id') == '$file_name':
                    names = {}
                    for d in data:
                        names[d.get('file_name')] = True
                    data = [{'_id': fn} for fn in names.keys()]
            elif '$replaceRoot' in stage:
                data = [dict(item.get('latest') or {}) for item in data]
            elif '$limit' in stage:
                data = data[: int(stage['$limit'])]
            elif '$project' in stage:
                proj = stage['$project']
                out = []
                for d in data:
                    row = {}
                    for k, v in proj.items():
                        if v == 1:
                            row[k] = d.get(k)
                        elif isinstance(v, str) and v.startswith('$'):
                            row[k] = d.get(v[1:], None)
                    out.append(row)
                data = out
            elif '$count' in stage:
                return [{"count": len(data)}]
        return data

    def _filter(self, query: Dict[str, Any], docs: Optional[List[Dict[str, Any]]] = None):
        src = self.docs if docs is None else docs
        def matches(d: Dict[str, Any]) -> bool:
            for k, v in query.items():
                if k == '$or':
                    if not any(matches(cond) for cond in v):
                        return False
                else:
                    dv = d.get(k)
                    if isinstance(v, dict) and '$exists' in v:
                        exists = v['$exists']
                        if exists and k not in d:
                            return False
                        if (not exists) and (k in d):
                            return False
                    elif dv != v:
                        return False
            return True
        return [d for d in src if matches(d)]

class FakeManager:
    def __init__(self):
        self.collection = InMemoryCollection()
        self.db = types.SimpleNamespace()

@pytest.fixture()
def repo():
    from database.repository import Repository
    return Repository(FakeManager())


def test_get_favorites_sort_and_filter(repo):
    now = datetime.now(timezone.utc)
    docs = [
        # a.py v1 favorite older
        {
            '_id': 'a-1', 'user_id': 1, 'file_name': 'a.py', 'version': 1, 'code': 'print(1)',
            'programming_language': 'python', 'is_favorite': True, 'favorited_at': now - timedelta(days=2), 'is_active': True,
        },
        # a.py v2 favorite newer
        {
            '_id': 'a-2', 'user_id': 1, 'file_name': 'a.py', 'version': 2, 'code': 'print(2)',
            'programming_language': 'python', 'is_favorite': True, 'favorited_at': now - timedelta(days=1), 'is_active': True,
        },
        # b.js v1 favorite mid
        {
            '_id': 'b-1', 'user_id': 1, 'file_name': 'b.js', 'version': 1, 'code': 'console.log(1)',
            'programming_language': 'javascript', 'is_favorite': True, 'favorited_at': now - timedelta(days=1, hours=12), 'is_active': True,
        },
        # c.py v1 not favorite
        {
            '_id': 'c-1', 'user_id': 1, 'file_name': 'c.py', 'version': 1, 'code': 'print(3)',
            'programming_language': 'python', 'is_favorite': False, 'is_active': True,
        },
    ]
    for d in docs:
        repo.manager.collection.insert_one(d)

    # default: sort by favorited_at desc (date)
    favs = repo.get_favorites(1)
    names = [f['file_name'] for f in favs]
    assert names[0] in {'a.py', 'b.js'}  # newest favorited first
    assert set(names) == {'a.py', 'b.js'}

    # filter by language
    py_favs = repo.get_favorites(1, language='python')
    assert [f['file_name'] for f in py_favs] == ['a.py']

    # sort by name asc
    favs_by_name = repo.get_favorites(1, sort_by='name')
    assert [f['file_name'] for f in favs_by_name] == ['a.py', 'b.js']

    # sort by language asc
    favs_by_lang = repo.get_favorites(1, sort_by='language')
    assert [f['programming_language'] for f in favs_by_lang] == ['javascript', 'python']

    # count distinct
    cnt = repo.get_favorites_count(1)
    assert cnt == 2
