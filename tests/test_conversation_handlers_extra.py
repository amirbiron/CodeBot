import types
import pytest


@pytest.mark.asyncio
async def test_regular_files_toggle_multi_delete(monkeypatch):
    # DB stub returns a single page of items
    mod = types.ModuleType("database")
    class _CodeSnippet: pass
    class _LargeFile: pass
    class _DatabaseManager: pass
    mod.CodeSnippet = _CodeSnippet
    mod.LargeFile = _LargeFile
    mod.DatabaseManager = _DatabaseManager

    items = [{"_id": f"i{n}", "file_name": f"m{n}.py", "programming_language": "python"} for n in range(10)]
    mod.db = types.SimpleNamespace(get_regular_files_paginated=lambda uid, page, per_page: (items, len(items)))
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
    # open regular files
    await handle_callback_query(U("show_regular_files"), ctx)
    # enter multi-delete mode
    await handle_callback_query(U("rf_multi_start"), ctx)
    # toggle one id (simulate an id value)
    await handle_callback_query(U("rf_toggle:1:i5"), ctx)
    # cancel multi-delete
    await handle_callback_query(U("rf_multi_cancel"), ctx)
    assert 'rf_multi_delete' in ctx.user_data
