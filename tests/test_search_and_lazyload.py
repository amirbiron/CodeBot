import types
import sys
import pytest


class DummyDB:
    def __init__(self):
        self._docs = []

    def search_code(self, user_id, search_term="", programming_language=None, tags=None, limit=10000):
        # very naive filter for tests only
        results = list(self._docs)
        if programming_language:
            results = [d for d in results if str(d.get("programming_language", "")).lower() == programming_language]
        if tags:
            tag = tags[0]
            results = [d for d in results if tag in (d.get("tags") or [])]
        if search_term:
            st = search_term.lower()
            results = [d for d in results if st in str(d.get("file_name", "")).lower()]
        return results[:limit]


@pytest.mark.asyncio
async def test_search_flow_parsing_and_pagination(monkeypatch):
    # Arrange minimal environment
    from types import SimpleNamespace
    user_id = 123

    # Fake db
    dummy = DummyDB()
    dummy._docs = [
        {"file_name": f"util_{i}.py", "programming_language": "python", "tags": ["repo:me/app"]}
        for i in range(23)
    ]

    # Patch database import site to return our dummy
    # Inject a stub 'database' module so that main.py can import CodeSnippet/DatabaseManager/db
    mod = types.ModuleType("database")
    class _CodeSnippet:  # minimal stub for import
        pass
    class _LargeFile:  # minimal stub for import
        pass
    class _DatabaseManager:
        pass
    mod.CodeSnippet = _CodeSnippet
    mod.LargeFile = _LargeFile
    mod.DatabaseManager = _DatabaseManager
    mod.db = dummy
    monkeypatch.setitem(sys.modules, "database", mod)

    # Simulate main.handle_text_message search branch
    from main import CodeKeeperBot
    bot = CodeKeeperBot()

    class DummyMessage:
        def __init__(self, text):
            self.text = text
            self.message_id = 1

        async def reply_text(self, *_args, **_kwargs):
            return None

    class DummyUpdate:
        def __init__(self, text):
            self.message = DummyMessage(text)

        @property
        def effective_user(self):
            return SimpleNamespace(id=user_id, username="u")

    class DummyContext:
        def __init__(self):
            self.user_data = {"awaiting_search_text": True}

    # Act: query with combined filters
    update = DummyUpdate("name:util lang:python tag:repo:me/app")
    ctx = DummyContext()

    await bot.handle_text_message(update, ctx)

    # Assert: results cached and paginated (10 per page)
    files_cache = ctx.user_data.get("files_cache")
    assert files_cache is not None
    assert len(files_cache) == 10  # first page


@pytest.mark.asyncio
async def test_lazy_buttons_single_instance(monkeypatch):
    # Ensure only one Show More button is added in direct view
    from types import SimpleNamespace

    # Minimal stubs
    user_id = 1
    long_code = "\n".join([f"line {i}" for i in range(800)])
    doc = {"file_name": "a.py", "code": long_code, "programming_language": "python", "_id": "x"}

    class DummyQuery:
        def __init__(self):
            self.data = "view_direct_a.py"

        async def answer(self):
            return None

        async def edit_message_text(self, *_args, **_kwargs):
            # capture reply_markup to check buttons
            self.captured = _kwargs.get("reply_markup")

    class DummyUpdate:
        def __init__(self):
            self.callback_query = DummyQuery()

        @property
        def effective_user(self):
            return SimpleNamespace(id=user_id)

    class DummyContext:
        def __init__(self):
            self.user_data = {}

    # Patch db.get_latest_version
    # stub database module
    mod = types.ModuleType("database")
    class _LargeFile:
        pass
    mod.LargeFile = _LargeFile
    mod.db = SimpleNamespace(get_latest_version=lambda _u, _n: doc, get_large_file=lambda *_: None)
    monkeypatch.setitem(sys.modules, "database", mod)

    # Act
    from handlers.file_view import handle_view_direct_file
    update = DummyUpdate()
    ctx = DummyContext()
    await handle_view_direct_file(update, ctx)

    # Assert: only one Show More button present
    rm = update.callback_query.captured
    assert rm is not None
    rows = rm.inline_keyboard
    flat_labels = [btn.text for row in rows for btn in row]
    assert sum(1 for t in flat_labels if t.startswith("הצג עוד ")) == 1


@pytest.mark.asyncio
async def test_lazy_buttons_less_and_edges_idx(monkeypatch):
    # Prepare a long code text (more than two chunks)
    code = ("line\n" * 10000)
    file_index = "5"

    class DummyQuery:
        def __init__(self, data):
            self.data = data
            self.captured = None

        async def answer(self):
            return None

        async def edit_message_text(self, *_args, **kwargs):
            self.captured = kwargs.get("reply_markup")

    class DummyUpdate:
        def __init__(self, data):
            self.callback_query = DummyQuery(data)

        @property
        def effective_user(self):
            return types.SimpleNamespace(id=1)

    class Ctx:
        def __init__(self):
            self.user_data = {
                'files_cache': {
                    file_index: {
                        'file_name': 'b.py',
                        'code': code,
                        'programming_language': 'python',
                        'version': 1,
                    }
                },
                'files_last_page': 1,
                'files_origin': {'type': 'regular'},
            }

    from conversation_handlers import handle_callback_query

    # First expand (should show both "עוד" and "פחות")
    update = DummyUpdate(f"fv_more:idx:{file_index}:3500")
    ctx = Ctx()
    await handle_callback_query(update, ctx)
    mk = update.callback_query.captured
    assert mk is not None
    labels = [b.text for row in mk.inline_keyboard for b in row]
    assert any(t.startswith("הצג עוד ") for t in labels)
    assert any(t.startswith("הצג פחות ") for t in labels)

    # Then shrink to base (should remove "פחות" when at base)
    update2 = DummyUpdate(f"fv_less:idx:{file_index}:7000")
    await handle_callback_query(update2, ctx)
    mk2 = update2.callback_query.captured
    labels2 = [b.text for row in mk2.inline_keyboard for b in row]
    assert any(t.startswith("הצג עוד ") for t in labels2)
    assert not any(t.startswith("הצג פחות ") for t in labels2)


@pytest.mark.asyncio
async def test_search_pagination_next_prev(monkeypatch):
    # Stub database with many items
    dummy = DummyDB()
    dummy._docs = [
        {"file_name": f"proj_{i}.py", "programming_language": "python", "tags": ["repo:me/app"]}
        for i in range(23)
    ]
    mod = types.ModuleType("database")
    class _CodeSnippet:
        pass
    class _LargeFile:
        pass
    class _DatabaseManager:
        pass
    mod.CodeSnippet = _CodeSnippet
    mod.LargeFile = _LargeFile
    mod.DatabaseManager = _DatabaseManager
    mod.db = dummy
    monkeypatch.setitem(sys.modules, "database", mod)

    # Perform initial search via main
    from main import CodeKeeperBot
    bot = CodeKeeperBot()

    class Msg:
        def __init__(self, text):
            self.text = text
            self.message_id = 1

        async def reply_text(self, *_args, **_kwargs):
            return None

    class Upd:
        def __init__(self, text):
            self.message = Msg(text)

        @property
        def effective_user(self):
            return types.SimpleNamespace(id=9, username="u")

    class Ctx:
        def __init__(self):
            self.user_data = {"awaiting_search_text": True}

    u = Upd("name:proj lang:python")
    c = Ctx()
    await bot.handle_text_message(u, c)

    # Now move to page 2 via conversation handler
    from conversation_handlers import handle_callback_query

    class Q2:
        def __init__(self):
            self.data = "search_page_2"
            self.captured = None

        async def answer(self):
            return None

        async def edit_message_text(self, *_a, **kw):
            self.captured = kw.get("reply_markup")

    class U2:
        def __init__(self):
            self.callback_query = Q2()

        @property
        def effective_user(self):
            return types.SimpleNamespace(id=9)

    u2 = U2()
    await handle_callback_query(u2, c)
    rm = u2.callback_query.captured
    assert rm is not None
    labels = [b.text for row in rm.inline_keyboard for b in row]
    # Expect both next and prev on middle page
    assert any("הקודם" in t for t in labels)
    assert any("הבא" in t for t in labels)

@pytest.mark.asyncio
async def test_search_pagination_last_page_prev_only(monkeypatch):
    # Reuse DB stub with 23 results
    dummy = DummyDB()
    dummy._docs = [
        {"file_name": f"proj_{i}.py", "programming_language": "python", "tags": ["repo:me/app"]}
        for i in range(23)
    ]
    mod = types.ModuleType("database")
    class _CodeSnippet:
        pass
    class _LargeFile:
        pass
    class _DatabaseManager:
        pass
    mod.CodeSnippet = _CodeSnippet
    mod.LargeFile = _LargeFile
    mod.DatabaseManager = _DatabaseManager
    mod.db = dummy
    monkeypatch.setitem(sys.modules, "database", mod)

    from main import CodeKeeperBot
    bot = CodeKeeperBot()

    class Msg:
        def __init__(self, text):
            self.text = text
            self.message_id = 1
        async def reply_text(self, *_a, **_k):
            return None
    class Upd:
        def __init__(self, text):
            self.message = Msg(text)
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=11, username="u")
    class Ctx:
        def __init__(self):
            self.user_data = {"awaiting_search_text": True}

    u = Upd("name:proj lang:python")
    c = Ctx()
    await bot.handle_text_message(u, c)

    from conversation_handlers import handle_callback_query
    class Q3:
        def __init__(self):
            self.data = "search_page_3"
            self.captured = None
        async def answer(self):
            return None
        async def edit_message_text(self, *_a, **kw):
            self.captured = kw.get("reply_markup")
    class U3:
        def __init__(self):
            self.callback_query = Q3()
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=11)
    u3 = U3()
    await handle_callback_query(u3, c)
    rm = u3.callback_query.captured
    assert rm is not None
    labels = [b.text for row in rm.inline_keyboard for b in row]
    assert any("הקודם" in t for t in labels)
    assert not any("הבא" in t for t in labels)

@pytest.mark.asyncio
async def test_lazy_buttons_more_less_direct(monkeypatch):
    # Stub database to force large_file path with long content
    long_code = "\n".join([f"line {i}" for i in range(12000)])
    mod = types.ModuleType("database")
    class _LargeFile: pass
    mod.LargeFile = _LargeFile
    mod.db = types.SimpleNamespace(
        get_latest_version=lambda _u, _n: None,
        get_large_file=lambda _u, _n: {
            'file_name': 'x.md',
            'content': long_code,
            'programming_language': 'markdown',
            '_id': '1'
        }
    )
    monkeypatch.setitem(sys.modules, "database", mod)

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
            return types.SimpleNamespace(id=7)
    ctx = types.SimpleNamespace(user_data={})

    # Expand from 3500 -> expect both buttons
    u1 = U("fv_more:direct:x.md:3500")
    await handle_callback_query(u1, ctx)
    rm1 = u1.callback_query.captured
    labels1 = [b.text for row in rm1.inline_keyboard for b in row]
    assert any(t.startswith("הצג עוד ") for t in labels1)
    assert any(t.startswith("הצג פחות ") for t in labels1)

    # Shrink to base -> expect no "פחות"
    u2 = U("fv_less:direct:x.md:7000")
    await handle_callback_query(u2, ctx)
    rm2 = u2.callback_query.captured
    labels2 = [b.text for row in rm2.inline_keyboard for b in row]
    assert any(t.startswith("הצג עוד ") for t in labels2)
    assert not any(t.startswith("הצג פחות ") for t in labels2)

@pytest.mark.asyncio
async def test_by_repo_pagination_basic(monkeypatch):
    # Stub db.get_user_files_by_repo to serve two pages
    items = [
        {"file_name": f"f_{i}.py", "programming_language": "python"}
        for i in range(15)
    ]
    def get_user_files_by_repo(_uid, _tag, page=1, per_page=10):
        start = (page - 1) * per_page
        end = min(start + per_page, len(items))
        return items[start:end], len(items)
    mod = types.ModuleType("database")
    mod.db = types.SimpleNamespace(get_user_files_by_repo=get_user_files_by_repo)
    monkeypatch.setitem(sys.modules, "database", mod)

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
            return types.SimpleNamespace(id=5)
    ctx = types.SimpleNamespace(user_data={})

    # First page
    u1 = U("by_repo:repo:me/app")
    await handle_callback_query(u1, ctx)
    rm1 = u1.callback_query.captured
    assert rm1 is not None
    # Verify next page callback exists (page 2)
    cb1 = [b.callback_data for row in rm1.inline_keyboard for b in row]
    # be robust to tag formatting; ensure a next-page callback exists to page 2
    assert any((str(cd).startswith("by_repo_page:") and str(cd).endswith(":2")) for cd in cb1)

    # Second page
    u2 = U("by_repo_page:repo:me/app:2")
    await handle_callback_query(u2, ctx)
    rm2 = u2.callback_query.captured
    cb2 = [b.callback_data for row in rm2.inline_keyboard for b in row]
    # On page 2 (last page), expect prev to page 1
    assert any((str(cd).startswith("by_repo_page:") and str(cd).endswith(":1")) for cd in cb2)
