import asyncio


def test_file_view_receive_new_name_invalid(monkeypatch):
    import handlers.file_view as fv
    from handlers.states import EDIT_NAME

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

    update = _Update("...")  # invalid due to punctuation-only
    ctx = _Ctx()

    result = asyncio.run(fv.receive_new_name(update, ctx))
    assert result == EDIT_NAME
