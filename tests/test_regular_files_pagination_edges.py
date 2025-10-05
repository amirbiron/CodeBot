import types
import datetime as dt
import pytest


@pytest.mark.asyncio
async def test_regular_files_page_clamps_to_total(monkeypatch):
    # Stub database with total=13, request page too large -> should clamp and still render
    mod = types.ModuleType("database")
    class _CodeSnippet: pass
    class _LargeFile: pass
    class _DatabaseManager: pass
    mod.CodeSnippet = _CodeSnippet
    mod.LargeFile = _LargeFile
    mod.DatabaseManager = _DatabaseManager

    total = 13
    # Provide empty list for out-of-range to simulate clamping path (handler will recompute page)
    def _get(uid, page, per_page):
        if page > (total + per_page - 1) // per_page:
            return [], total
        start = (page - 1) * per_page
        end = min(start + per_page, total)
        items = [{"_id": f"i{n}", "file_name": f"c{n}.py", "programming_language": "python", "updated_at": dt.datetime.now(dt.timezone.utc)} for n in range(start, end)]
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
    # first render
    await handle_callback_query(U("show_regular_files"), ctx)
    # go to an out-of-range page
    await handle_callback_query(U("files_page_9"), ctx)
    assert ctx.user_data.get('files_last_page') is not None
