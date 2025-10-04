import types
import datetime as dt
import pytest


class DummyCollection:
    def __init__(self, docs):
        self._docs = list(docs)

    def aggregate(self, pipeline, allowDiskUse=False):  # noqa: N803
        data = list(self._docs)

        def eval_match(doc, expr):
            # supports $or, field matches with $exists/$eq/$not/$elemMatch/$regex and plain equality
            if not isinstance(expr, dict):
                return False
            if "$or" in expr:
                return any(eval_match(doc, sub) for sub in expr["$or"])
            for key, cond in expr.items():
                if key == "$or":
                    continue
                val = doc.get(key)
                if isinstance(cond, dict):
                    if "$exists" in cond:
                        exists = cond["$exists"]
                        if bool(val is not None) != bool(exists):
                            return False
                    if "$eq" in cond:
                        if val != cond["$eq"]:
                            return False
                    if "$not" in cond:
                        inner = cond["$not"]
                        # handle $elemMatch inside $not
                        if "$elemMatch" in inner:
                            arr = val or []
                            if isinstance(arr, str):
                                arr = [arr]
                            em = inner["$elemMatch"]
                            if "$regex" in em:
                                import re
                                rx = re.compile(em["$regex"])
                                # not any element matches
                                if any(rx.search(str(t) or "") for t in arr):
                                    return False
                    if "$elemMatch" in cond:
                        arr = val or []
                        if isinstance(arr, str):
                            arr = [arr]
                        em = cond["$elemMatch"]
                        if "$regex" in em:
                            import re
                            rx = re.compile(em["$regex"])
                            if not any(rx.search(str(t) or "") for t in arr):
                                return False
                    if "$regex" in cond:
                        import re
                        rx = re.compile(cond["$regex"]) 
                        # field could be string or list
                        if isinstance(val, list):
                            if not any(rx.search(str(t) or "") for t in val):
                                return False
                        else:
                            if not rx.search(str(val or "")):
                                return False
                else:
                    # equality: support array membership semantics like Mongo
                    if isinstance(val, list):
                        if cond not in val:
                            return False
                    else:
                        if val != cond:
                            return False
            return True

        def distinct_latest(rows):
            rows_sorted = sorted(rows, key=lambda x: (str(x.get("file_name", "")), -int(x.get("version", 1))))
            seen = {}
            for d in rows_sorted:
                fn = d.get("file_name")
                if fn not in seen:
                    seen[fn] = d
            return list(seen.values())

        rows = data

        for st in pipeline:
            if "$match" in st:
                rows = [d for d in rows if eval_match(d, st["$match"])]
            elif "$sort" in st:
                key = st["$sort"]
                if list(key.keys()) == ["updated_at"] and key["updated_at"] == -1:
                    rows = sorted(rows, key=lambda x: x.get("updated_at") or dt.datetime.min.replace(tzinfo=dt.timezone.utc), reverse=True)
                else:
                    rows = sorted(rows, key=lambda x: (str(x.get("file_name", "")), -int(x.get("version", 1))))
            elif "$group" in st and st["$group"].get("_id") == "$file_name":
                rows = distinct_latest(rows)
            elif "$replaceRoot" in st:
                # no-op in this simplified emulation
                pass
            elif "$project" in st:
                proj = st["$project"]
                out = []
                for d in rows:
                    nd = {}
                    for k, v in proj.items():
                        if v in (1, True):
                            nd[k] = d.get(k)
                        elif isinstance(v, str) and v.startswith("$"):
                            # support simple path like $_id or nested like $_id.tag
                            path = v[1:]
                            cur = d
                            for part in path.split('.'):
                                if isinstance(cur, dict):
                                    cur = cur.get(part)
                                else:
                                    cur = None
                                    break
                            nd[k] = cur
                    for k, v in proj.items():
                        if v in (0, False):
                            nd.pop(k, None)
                    out.append(nd)
                rows = out
            elif "$skip" in st:
                rows = rows[st["$skip"]:]
            elif "$limit" in st:
                rows = rows[: st["$limit"]]
            elif "$count" in st:
                # count distinct file_name when present (closer to pipeline intent), fallback to len
                if rows and isinstance(rows[0], dict) and "file_name" in rows[0]:
                    uniq = len({r.get("file_name") for r in rows})
                    return [{"count": uniq}]
                return [{"count": len(rows)}]
        return rows


class DummyManager:
    def __init__(self, docs):
        self.collection = DummyCollection(docs)
        self.large_files_collection = DummyCollection([])
        self.db = types.SimpleNamespace()


def _make_repo(docs):
    from database.repository import Repository
    return Repository(DummyManager(docs))


def _docs_for_user(uid=1, total=25, with_repo_every=2):
    now = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)
    docs = []
    for i in range(total):
        docs.append({
            "_id": f"id{i}",
            "user_id": uid,
            "file_name": f"f{i}.py",
            "programming_language": "python",
            "version": 2,
            "updated_at": now,
            "is_active": True,
            "tags": ([] if (i % with_repo_every == 0) else ["repo:me/app"]),
            "code": "print(1)",
        })
    return docs


def test_repository_regular_files_paginated_basic():
    repo = _make_repo(_docs_for_user(uid=1, total=25, with_repo_every=2))
    items, total = repo.get_regular_files_paginated(user_id=1, page=1, per_page=10)
    assert total == 13  # every 2nd item non-repo
    assert len(items) == 10
    assert all("code" not in it for it in items)


def test_repository_regular_files_paginated_second_page():
    # all non-repo to reach total=13 and second page of 3
    repo = _make_repo(_docs_for_user(uid=2, total=13, with_repo_every=1))
    items, total = repo.get_regular_files_paginated(user_id=2, page=2, per_page=10)
    assert total == 13
    assert len(items) == 3


def test_repository_files_by_repo_projection_excludes_code():
    # build only repo-tagged docs
    now = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)
    docs = [{
        "_id": f"id{i}",
        "user_id": 3,
        "file_name": f"r{i}.py",
        "programming_language": "python",
        "version": 1,
        "updated_at": now,
        "is_active": True,
        "tags": ["repo:me/app"],
        "code": "print(1)",
    } for i in range(7)]
    repo = _make_repo(docs)
    items, total = repo.get_user_files_by_repo(user_id=3, repo_tag="repo:me/app", page=1, per_page=5)
    assert total == 7
    assert len(items) == 5
    assert all("code" not in it for it in items)


@pytest.mark.asyncio
async def test_regular_files_flow_uses_db_pagination(monkeypatch):
    # Stub database module with get_regular_files_paginated
    mod = types.ModuleType("database")
    class _CodeSnippet: pass
    class _LargeFile: pass
    class _DatabaseManager: pass
    mod.CodeSnippet = _CodeSnippet
    mod.LargeFile = _LargeFile
    mod.DatabaseManager = _DatabaseManager

    items = [{"_id": f"i{n}", "file_name": f"a{n}.py", "programming_language": "python", "updated_at": dt.datetime.now(dt.timezone.utc)} for n in range(10)]
    mod.db = types.SimpleNamespace(get_regular_files_paginated=lambda uid, page, per_page: (items, 23))
    monkeypatch.setitem(__import__('sys').modules, "database", mod)

    from conversation_handlers import handle_callback_query

    class Q:
        def __init__(self):
            self.data = "show_regular_files"
            self.captured = None
        async def answer(self):
            return None
        async def edit_message_text(self, *_a, **kw):
            self.captured = kw.get("reply_markup")
    class U:
        def __init__(self):
            self.callback_query = Q()
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=1)
    ctx = types.SimpleNamespace(user_data={})
    await handle_callback_query(U(), ctx)
    cache = ctx.user_data.get('files_cache')
    assert cache is not None
    # code should be absent in list entries (metadata only)
    assert all('code' not in v for v in cache.values())


@pytest.mark.asyncio
async def test_regular_files_page_second(monkeypatch):
    mod = types.ModuleType("database")
    class _CodeSnippet: pass
    class _LargeFile: pass
    class _DatabaseManager: pass
    mod.CodeSnippet = _CodeSnippet
    mod.LargeFile = _LargeFile
    mod.DatabaseManager = _DatabaseManager

    items = [{"_id": f"i{n}", "file_name": f"b{n}.py", "programming_language": "python", "updated_at": dt.datetime.now(dt.timezone.utc)} for n in range(10)]
    def _get(uid, page, per_page):
        if page == 2:
            start = 10
            it = [{"_id": f"i{start+n}", "file_name": f"b{start+n}.py", "programming_language": "python", "updated_at": dt.datetime.now(dt.timezone.utc)} for n in range(3)]
            return it, 13
        return items, 13
    mod.db = types.SimpleNamespace(get_regular_files_paginated=_get)
    monkeypatch.setitem(__import__('sys').modules, "database", mod)

    from conversation_handlers import handle_callback_query

    class Q:
        def __init__(self, data):
            self.data = data
            self.captured = None
        async def answer(self):
            return None
        async def edit_message_text(self, *_a, **kw):
            self.captured = kw.get("reply_markup")
    class U:
        def __init__(self, data):
            self.callback_query = Q(data)
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=1)
    ctx = types.SimpleNamespace(user_data={})
    await handle_callback_query(U("show_regular_files"), ctx)
    await handle_callback_query(U("files_page_2"), ctx)
    cache = ctx.user_data.get('files_cache')
    assert cache is not None
    assert any(k == '10' for k in cache.keys())


@pytest.mark.asyncio
async def test_handle_view_file_lazy_loads_code(monkeypatch):
    # Prepare list with metadata only (no code) and ensure handler fetches code lazily
    mod = types.ModuleType("database")
    class _LargeFile: pass
    mod.LargeFile = _LargeFile
    mod.db = types.SimpleNamespace(get_latest_version=lambda _u, _n: {
        'file_name': 'c.py', 'code': 'print(1)', 'programming_language': 'python', 'version': 3
    })
    monkeypatch.setitem(__import__('sys').modules, "database", mod)

    from handlers.file_view import handle_view_file

    class Q:
        def __init__(self):
            self.data = 'view_0'
            self.captured = None
        async def answer(self):
            return None
        async def edit_message_text(self, *_a, **_kw):
            self.captured = True
    class U:
        def __init__(self):
            self.callback_query = Q()
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=1)

    ctx = types.SimpleNamespace(user_data={
        'files_cache': {'0': {'file_name': 'c.py', 'programming_language': 'python', 'version': 1}},
        'files_last_page': 1,
        'files_origin': {'type': 'regular'},
    })
    await handle_view_file(U(), ctx)
    assert ctx.user_data['files_cache']['0'].get('code') == 'print(1)'
