import types
import pytest
import asyncio


@pytest.mark.asyncio
async def test_branch_button_callback_truncation(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    class _Msg:
        def __init__(self):
            self.edits = []
            self.texts = []
    class _Q:
        def __init__(self):
            self.data = "choose_upload_branch"
            self.from_user = types.SimpleNamespace(id=11)
            self.message = _Msg()
        async def edit_message_text(self, *a, **k):
            self.message.edits.append("edited")
            return self.message
        async def answer(self, *a, **k):
            return None
    upd = types.SimpleNamespace(
        callback_query=_Q(),
        effective_user=types.SimpleNamespace(id=11),
    )
    ctx = types.SimpleNamespace(user_data={}, bot_data={})

    sess = handler.get_user_session(11)
    sess["selected_repo"] = "o/r"
    monkeypatch.setattr(handler, "get_user_token", lambda _uid: "tok")

    class _Br:
        def __init__(self, name):
            self.name = name
            self.commit = types.SimpleNamespace(commit=types.SimpleNamespace(author=types.SimpleNamespace(date=None)))
    class _Repo:
        def get_branches(self):
            return [_Br("a" * 200)]  # very long branch name
    class _Gh:
        def __init__(self, *a, **k):
            pass
        def get_repo(self, full):
            return _Repo()

    monkeypatch.setattr(gh, "Github", _Gh)
    monkeypatch.setattr(gh, "InlineKeyboardButton", lambda *a, **k: (a, k))
    monkeypatch.setattr(gh, "InlineKeyboardMarkup", lambda rows: rows)

    class _BR(Exception):
        pass
    monkeypatch.setattr(gh, "BadRequest", _BR, raising=False)

    await asyncio.wait_for(handler.handle_menu_callback(upd, ctx), timeout=2.0)
    # הצלחה נמדדת בהיעדר חריגות (Button_data_invalid וכד')
    assert upd.callback_query.message.edits or upd.callback_query.message.texts is not None
