import types
import pytest

class _App:
    def __init__(self):
        self.handlers = []
    def add_handler(self, *a, **k):
        self.handlers.append((a, k))

class _Msg:
    def __init__(self, fail_first=False):
        self.sent = []
        self._fail_first = fail_first
        self._calls = 0
    async def reply_text(self, *a, **k):
        self._calls += 1
        if self._fail_first and self._calls == 1:
            raise RuntimeError("simulate send failure")
        self.sent.append((a, k))

@pytest.fixture
def handlers():
    import bot_handlers as bh
    return bh.AdvancedBotHandlers(_App())

@pytest.mark.asyncio
async def test_send_long_message_no_split(handlers):
    # msg shorter than MAX_LEN -> single send, preserves kwargs
    msg = _Msg()
    text = "hello"
    dummy_markup = object()
    await handlers._send_long_message(msg, text, parse_mode="HTML", reply_markup=dummy_markup)
    assert len(msg.sent) == 1
    args, kwargs = msg.sent[0]
    assert kwargs.get("parse_mode") == "HTML"
    assert kwargs.get("reply_markup") is dummy_markup

@pytest.mark.asyncio
async def test_send_long_message_split(handlers):
    # message longer than MAX_LEN -> multiple sends
    msg = _Msg()
    # 8000 chars with newlines to exercise chunking by lines
    big = ("line\n" * 2000)
    await handlers._send_long_message(msg, big, parse_mode=None, reply_markup=None)
    assert len(msg.sent) >= 2

@pytest.mark.asyncio
async def test_send_long_message_exception_fallback(handlers):
    # first send raises -> fallback path sends full text once
    msg = _Msg(fail_first=True)
    text = "short"
    await handlers._send_long_message(msg, text, parse_mode="HTML", reply_markup=None)
    # Two calls overall: first raised, second succeeded
    assert len(msg.sent) == 1
