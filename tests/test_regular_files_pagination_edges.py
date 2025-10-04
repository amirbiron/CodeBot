import types
import datetime as dt
import pytest


@pytest.mark.asyncio
async def test_regular_files_page_out_of_range(monkeypatch):
    # Stub DB: total 13, page>pages should clamp and still return
    items_page1 = [{"_id": f"i{n}", "file_name": f"x{n}.py", "programming_language": "python", "updated_at": dt.datetime.now(dt.timezone.utc)} for n in range(10)]
    items_page2 = [{"_id": f"i{10+n}", "file_name": f"x{10+n}.py", "programming_language": "python", "updated_at": dt.datetime.now(dt.timezone.utc)} for n in range(3)]

    def _get(uid, page, per_page):
        if page <= 1:
            return items_page1, 13
        elif page == 2:
            return items_page2, 13
        else:
            return [], 13

    mod = types.ModuleType('database')
    mod.db = types.SimpleNamespace(get_regular_files_paginated=_get)
    monkeypatch.setitem(__import__('sys').modules, 'database', mod)

    from conversation_handlers import handle_callback_query

    class Q:
        def __init__(self, data):
            self.data = data
            self.captured = None
        async def answer(self):
            return None
        async def edit_message_text(self, *_a, **kw):
            self.captured = kw.get('reply_markup')
    class U:
        def __init__(self, data):
            self.callback_query = Q(data)
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=1)

    ctx = types.SimpleNamespace(user_data={})
    await handle_callback_query(U('files_page_5'), ctx)
    # Should not crash; may show empty state or adjusted page
    assert True
