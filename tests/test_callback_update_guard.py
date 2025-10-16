import types
import pytest

from conversation_handlers import handle_callback_query


class _Msg:
    def __init__(self):
        self.sent = []

    async def reply_text(self, *args, **kwargs):
        self.sent.append((args, kwargs))


class _Query:
    def __init__(self, data: str):
        self.data = data
        self.message = _Msg()
        self.answered = False

    async def answer(self, *_, **__):
        self.answered = True

    async def edit_message_text(self, *args, **kwargs):
        self.message.sent.append((args, kwargs))


@pytest.mark.asyncio
async def test_guard_allows_processing_when_update_id_none():
    ctx = types.SimpleNamespace(user_data={})
    q = _Query("main")
    upd = types.SimpleNamespace(update_id=None, callback_query=q, effective_user=types.SimpleNamespace(id=1))

    await handle_callback_query(upd, ctx)

    assert len(q.message.sent) >= 1


@pytest.mark.asyncio
async def test_guard_sets_last_id_and_processes_once():
    ctx = types.SimpleNamespace(user_data={})
    q = _Query("main")
    upd = types.SimpleNamespace(update_id=42, callback_query=q, effective_user=types.SimpleNamespace(id=1))

    await handle_callback_query(upd, ctx)

    assert ctx.user_data.get("_last_callback_update_id") == 42
    assert len(q.message.sent) >= 1


@pytest.mark.asyncio
async def test_guard_blocks_duplicate_same_update_id():
    ctx = types.SimpleNamespace(user_data={})
    q = _Query("main")
    upd1 = types.SimpleNamespace(update_id=99, callback_query=q, effective_user=types.SimpleNamespace(id=1))

    await handle_callback_query(upd1, ctx)
    sent_count_after_first = len(q.message.sent)

    upd2 = types.SimpleNamespace(update_id=99, callback_query=q, effective_user=types.SimpleNamespace(id=1))
    await handle_callback_query(upd2, ctx)

    assert len(q.message.sent) == sent_count_after_first
