import types

import pytest


@pytest.mark.asyncio
async def test_large_files_menu_shows_error_when_facade_unavailable(monkeypatch):
    import large_files_handler as lfh

    handler = lfh.LargeFilesHandler()
    monkeypatch.setattr(handler, "_facade", lambda: None, raising=True)

    class DummyQuery:
        def __init__(self):
            self.edits = []

        async def edit_message_text(self, text, **kwargs):
            self.edits.append((text, kwargs))
            return None

    update = types.SimpleNamespace(
        callback_query=DummyQuery(),
        effective_user=types.SimpleNamespace(id=1),
    )
    context = types.SimpleNamespace(user_data={})

    await handler.show_large_files_menu(update, context, page=1)

    text, _kw = update.callback_query.edits[-1]
    assert "לא ניתן לטעון" in text
    assert "קבצים הגדולים" in text


@pytest.mark.asyncio
async def test_view_large_file_shows_db_error_when_facade_unavailable(monkeypatch):
    import large_files_handler as lfh

    handler = lfh.LargeFilesHandler()
    monkeypatch.setattr(handler, "_facade", lambda: None, raising=True)

    class DummyQuery:
        def __init__(self):
            self.data = "lf_view_0"
            self.edits = []

        async def answer(self, *_a, **_k):
            return None

        async def edit_message_text(self, text, **kwargs):
            self.edits.append((text, kwargs))
            return None

    update = types.SimpleNamespace(
        callback_query=DummyQuery(),
        effective_user=types.SimpleNamespace(id=123),
    )
    context = types.SimpleNamespace(
        user_data={"large_files_cache": {"0": {"file_name": "big.txt"}}}
    )

    await handler.view_large_file(update, context)

    text, _kw = update.callback_query.edits[-1]
    assert "שגיאה במסד הנתונים" in text

