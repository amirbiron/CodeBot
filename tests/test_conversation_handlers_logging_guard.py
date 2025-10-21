import types
import sys
import pytest

import conversation_handlers as ch


class _Query:
    def __init__(self, data):
        self.data = data

    async def answer(self):
        return None

    async def edit_message_text(self, *a, **k):
        return None


class _Update:
    def __init__(self):
        self.callback_query = _Query("edit_0")
        self.effective_user = types.SimpleNamespace(id=123)
        self.message = types.SimpleNamespace(text="hello")


class _Context:
    def __init__(self):
        self.user_data = {"files_cache": {"0": {"file_name": "f.py"}}}


@pytest.mark.asyncio
async def test_handle_edit_code_logging_fallback(monkeypatch):
    # Force exception inside the try to trigger except block
    update = _Update()
    context = _Context()

    # Make query.data access raise to hit except path
    update.callback_query.data = None

    # Patch import in except: make code_processor import succeed but code_logger logging raise
    class _CodeLogger:
        def error(self, *_a, **_k):
            raise RuntimeError("log error")

    class _CP:
        code_logger = _CodeLogger()

    monkeypatch.setitem(sys.modules, 'code_processor', types.SimpleNamespace(code_processor=_CP()))

    # Run handler; it should handle logging failure silently (via internal debug)
    await ch.handle_edit_code(update, context)
