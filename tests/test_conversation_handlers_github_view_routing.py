import types
import pytest

from telegram.ext import ConversationHandler

import conversation_handlers as ch


class _Q:
    def __init__(self, data):
        self.data = data

    async def answer(self, *a, **k):  # noqa: ARG002
        return None


class _U:
    def __init__(self, data):
        self.update_id = 42
        self.callback_query = _Q(data)


@pytest.mark.asyncio
async def test_handle_callback_query_ignores_github_view_buttons():
    ctx = types.SimpleNamespace(user_data={})
    state1 = await ch.handle_callback_query(_U("view_more"), ctx)
    state2 = await ch.handle_callback_query(_U("view_back"), ctx)
    assert state1 == ConversationHandler.END
    assert state2 == ConversationHandler.END
