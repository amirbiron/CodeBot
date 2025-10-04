import types
import pytest


@pytest.mark.asyncio
async def test_safe_answer_integrated_with_recycle_handlers(monkeypatch):
    import conversation_handlers as ch
    from utils import TelegramUtils

    calls = {"answered": 0}
    async def fake_answer(self, query, text=None, show_alert=False, cache_time=None):
        calls["answered"] += 1
    monkeypatch.setattr(TelegramUtils, "safe_answer", fake_answer)

    class Q:
        def __init__(self, data):
            self.data = data
            self.answers = []
        async def answer(self, *a, **k):
            self.answers.append(k)
        async def edit_message_text(self, *a, **k):
            return None

    class U:
        def __init__(self, data):
            self.callback_query = Q(data)
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=123)

    # When fid is missing -> safe_answer called with alert
    ctx = types.SimpleNamespace(user_data={})
    await ch.recycle_restore(U("recycle_restore:"), ctx)
    await ch.recycle_purge(U("recycle_purge:"), ctx)
    assert calls["answered"] >= 2
