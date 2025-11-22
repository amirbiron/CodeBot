import asyncio


def test_conversation_receive_new_name_invalid(monkeypatch):
    import conversation_handlers as ch

    class _Msg:
        def __init__(self, text):
            self.text = text

        async def reply_text(self, *a, **k):
            return None

    class _Update:
        def __init__(self, text):
            self.message = _Msg(text)

    class _Ctx:
        def __init__(self):
            self.user_data = {"editing_file_data": {"file_name": "old.py"}}

    update = _Update(".")  # invalid filename
    ctx = _Ctx()

    result = asyncio.run(ch.receive_new_name(update, ctx))
    assert result == ch.EDIT_NAME
