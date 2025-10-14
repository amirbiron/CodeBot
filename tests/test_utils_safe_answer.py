import types
import pytest


@pytest.mark.asyncio
async def test_safe_answer_passes_kwargs(monkeypatch):
    import utils as um
    from utils import TelegramUtils

    calls = {}

    class Q:
        async def answer(self, **kwargs):
            calls.update(kwargs)

    # ensure BadRequest class exists for type checking, not used here
    class FakeBR(Exception):
        pass
    um.telegram = types.SimpleNamespace(error=types.SimpleNamespace(BadRequest=FakeBR))

    q = Q()
    await TelegramUtils.safe_answer(q, text="hi", show_alert=True, cache_time=5)
    assert calls.get("text") == "hi"
    assert calls.get("show_alert") is True
    assert calls.get("cache_time") == 5


@pytest.mark.asyncio
async def test_safe_answer_swallows_old_query(monkeypatch):
    import utils as um
    from utils import TelegramUtils

    class FakeBR(Exception):
        pass
    um.telegram = types.SimpleNamespace(error=types.SimpleNamespace(BadRequest=FakeBR))

    class Q:
        def __init__(self):
            self.count = 0
        async def answer(self, **kwargs):
            self.count += 1
            raise FakeBR("Query is too old")

    q = Q()
    # Should not raise
    await TelegramUtils.safe_answer(q, text="x")
    assert q.count == 1


@pytest.mark.asyncio
async def test_safe_answer_raises_other_badrequest(monkeypatch):
    import utils as um
    from utils import TelegramUtils

    class FakeBR(Exception):
        pass
    um.telegram = types.SimpleNamespace(error=types.SimpleNamespace(BadRequest=FakeBR))

    class Q:
        async def answer(self, **kwargs):
            raise FakeBR("some other error")

    with pytest.raises(FakeBR):
        await TelegramUtils.safe_answer(Q(), text="y")
