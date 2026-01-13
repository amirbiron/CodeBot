import types

import pytest


@pytest.mark.asyncio
async def test_large_files_handler_delete_large_file_db_error_shows_message(monkeypatch):
    import large_files_handler as lfh

    class ExplodingFacade:
        def delete_large_file(self, user_id, file_name):  # noqa: ARG002
            raise RuntimeError("db down")

    handler = lfh.LargeFilesHandler()
    monkeypatch.setattr(handler, "_facade", lambda: ExplodingFacade(), raising=True)

    class DummyQuery:
        def __init__(self):
            self.data = "lf_confirm_delete_0"
            self.edits = []

        async def answer(self):
            return None

        async def edit_message_text(self, text, **kwargs):
            self.edits.append((text, kwargs))
            return None

    update = types.SimpleNamespace(
        callback_query=DummyQuery(),
        effective_user=types.SimpleNamespace(id=123),
    )
    context = types.SimpleNamespace(
        user_data={
            "large_files_cache": {
                "0": {"file_name": "big.txt"},
            }
        }
    )

    await handler.delete_large_file(update, context)

    text, _kw = update.callback_query.edits[-1]
    assert "שגיאה במסד הנתונים" in text

