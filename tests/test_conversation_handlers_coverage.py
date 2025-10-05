import types
import pytest


@pytest.mark.asyncio
async def test_regular_files_page_out_of_range_clamps(monkeypatch):
    # Stub DB for get_regular_files_paginated
    mod = types.ModuleType("database")
    class _CodeSnippet: pass
    class _LargeFile: pass
    class _DatabaseManager: pass
    mod.CodeSnippet = _CodeSnippet
    mod.LargeFile = _LargeFile
    mod.DatabaseManager = _DatabaseManager

    total = 13
    def _get(uid, page, per_page):
        # return empty when page too large; handler should clamp and re-fetch
        if page > 2:
            return [], total
        items = [{"_id": f"i{n}", "file_name": f"c{n}.py", "programming_language": "python"} for n in range((page-1)*per_page, min(page*per_page, total))]
        return items, total
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
    # jump to a too-large page
    await handle_callback_query(U("files_page_9"), ctx)
    assert isinstance(ctx.user_data.get('files_last_page'), int)


@pytest.mark.asyncio
async def test_show_regular_files_message_not_modified(monkeypatch):
    # Stub DB for get_regular_files_paginated
    mod = types.ModuleType("database")
    class _CodeSnippet: pass
    class _LargeFile: pass
    class _DatabaseManager: pass
    mod.CodeSnippet = _CodeSnippet
    mod.LargeFile = _LargeFile
    mod.DatabaseManager = _DatabaseManager
    def _get(uid, page, per_page):
        items = [{"_id": "x", "file_name": "a.py", "programming_language": "python"}]
        return items, 1
    mod.db = types.SimpleNamespace(get_regular_files_paginated=_get)
    monkeypatch.setitem(__import__('sys').modules, "database", mod)

    from conversation_handlers import show_regular_files_page_callback

    class Q:
        def __init__(self, data):
            self.data = data
        async def answer(self, *a, **k):
            return None
        async def edit_message_text(self, *a, **k):
            # Simulate Telegram 'message is not modified' behavior
            import telegram.error
            raise telegram.error.BadRequest("message is not modified")

    class U:
        def __init__(self, data):
            self.callback_query = Q(data)
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=1)

    ctx = types.SimpleNamespace(user_data={})
    # Should swallow the BadRequest and not raise
    await show_regular_files_page_callback(U("files_page_1"), ctx)
