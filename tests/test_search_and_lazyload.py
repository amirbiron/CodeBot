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


def test_search_flow_parsing_and_pagination(monkeypatch):
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
    from main import BotHandlers
    bot = BotHandlers()

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

    import asyncio
    asyncio.get_event_loop().run_until_complete(bot.handle_text_message(update, ctx))

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

