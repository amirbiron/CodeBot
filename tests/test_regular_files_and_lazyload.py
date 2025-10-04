import types
import datetime as dt
import pytest


class DummyCollection:
    def __init__(self, docs):
        self._docs = list(docs)

    def aggregate(self, pipeline, allowDiskUse=False):  # noqa: N803
        # Minimal emulation for pipelines used in repository.py
        data = list(self._docs)

        def _apply_match(stage, rows):
            cond = stage.get("$match") or {}
            out = []
            for d in rows:
                ok = True
                for k, v in cond.items():
                    if k == "tags":
                        # either exact tag or regex
                        if isinstance(v, dict) and "$regex" in v:
                            import re
                            rx = re.compile(v["$regex"])  # lower-case only per project convention
                            tags = d.get("tags") or []
                            if not any(rx.search(str(t) or "") for t in tags):
                                ok = False
                                break
                        else:
                            if v not in (d.get("tags") or []):
                                ok = False
                                break
                    else:
                        if d.get(k) != v:
                            ok = False
                            break
                if ok:
                    out.append(d)
            return out

        def _distinct_latest_by_filename(rows):
            # sort by file_name asc, version desc; then group first
            rows_sorted = sorted(rows, key=lambda x: (str(x.get("file_name", "")), -int(x.get("version", 1))))
            seen = {}
            for d in rows_sorted:
                fn = d.get("file_name")
                if fn not in seen:
                    seen[fn] = d
            return list(seen.values())

        rows = data
        # support simple count pipeline recognition
        if pipeline and pipeline[-1].get("$count") == "count":
            # apply matches and grouping by file_name
            for st in pipeline:
                if "$match" in st:
                    rows = _apply_match(st, rows)
                elif "$group" in st and st["$group"].get("_id") == "$file_name":
                    # collapse to distinct file_name
                    rows = _distinct_latest_by_filename(rows)
            return [{"count": len(rows)}]

        # general items pipeline
        for st in pipeline:
            if "$match" in st:
                rows = _apply_match(st, rows)
            elif "$sort" in st:
                key = st["$sort"]
                # support updated_at desc and (file_name asc, version desc)
                if list(key.keys()) == ["updated_at"]:
                    rows = sorted(rows, key=lambda x: x.get("updated_at") or dt.datetime.min.replace(tzinfo=dt.timezone.utc), reverse=True)
                else:
                    rows = sorted(rows, key=lambda x: (str(x.get("file_name", "")), -int(x.get("version", 1))))
            elif "$group" in st and st["$group"].get("_id") == "$file_name":
                rows = _distinct_latest_by_filename(rows)
            elif "$replaceRoot" in st:
                # rows already latest docs
                pass
            elif "$project" in st:
                proj = st["$project"]
                out = []
                for d in rows:
                    nd = {}
                    for k, v in proj.items():
                        if v in (1, True):
                            nd[k] = d.get(k)
                    # remove excluded fields (code=0)
                    for k, v in proj.items():
                        if v in (0, False) and k in nd:
                            nd.pop(k, None)
                    out.append(nd)
                rows = out
            elif "$skip" in st:
                rows = rows[st["$skip"]:]
            elif "$limit" in st:
                rows = rows[: st["$limit"]]
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
    repo = _make_repo(_docs_for_user(uid=2, total=13, with_repo_every=100))
    items, total = repo.get_regular_files_paginated(user_id=2, page=2, per_page=10)
    assert total == 13
    assert len(items) == 3


def test_repository_files_by_repo_projection_excludes_code():
    docs = _docs_for_user(uid=3, total=7, with_repo_every=1)
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
