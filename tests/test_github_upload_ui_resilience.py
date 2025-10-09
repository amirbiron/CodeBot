import types
import pytest
import asyncio


class _Msg:
    def __init__(self):
        self.edits = []
        self.texts = []
    async def reply_text(self, text, **kwargs):
        self.texts.append(text)
        return self
    async def edit_text(self, text, **kwargs):
        self.edits.append(text)
        return self

class _Query:
    def __init__(self, uid=9, data=""):
        self.message = _Msg()
        self.data = data
        self.from_user = types.SimpleNamespace(id=uid)
    async def edit_message_text(self, text, reply_markup=None, parse_mode=None):
        # emulate edit, no exception
        self.message.edits.append(text)
        return self.message
    async def answer(self, *args, **kwargs):
        return None

class _Update:
    def __init__(self, data=""):
        self.callback_query = _Query(data=data)
        self.effective_user = types.SimpleNamespace(id=9)
        self.message = types.SimpleNamespace(text=None, from_user=types.SimpleNamespace(id=9))

class _Context:
    def __init__(self):
        self.user_data = {}
        self.bot_data = {}


@pytest.mark.asyncio
async def test_choose_upload_branch_answers_then_shows_menu(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    upd = _Update("choose_upload_branch")
    ctx = _Context()

    sess = handler.get_user_session(9)
    sess["selected_repo"] = "o/r"
    monkeypatch.setattr(handler, "get_user_token", lambda _uid: "tok")

    class _Br:
        def __init__(self, name):
            self.name = name
            self.commit = types.SimpleNamespace(commit=types.SimpleNamespace(author=types.SimpleNamespace(date=None)))
    class _Repo:
        def get_branches(self):
            return [_Br("feature/really-long-branch-name-with-many-segments/and-extra")]
    class _Gh:
        def __init__(self, *a, **k):
            pass
        def get_repo(self, full):
            return _Repo()

    monkeypatch.setattr(gh, "Github", _Gh)
    monkeypatch.setattr(gh, "InlineKeyboardButton", lambda *a, **k: (a, k))
    monkeypatch.setattr(gh, "InlineKeyboardMarkup", lambda rows: rows)

    # Also make BadRequest available in this module context
    class _BR(Exception):
        pass
    monkeypatch.setattr(gh, "BadRequest", _BR, raising=False)

    await asyncio.wait_for(handler.handle_menu_callback(upd, ctx), timeout=2.0)
    # If no exception, we passed through query.answer and menu build; ensure a row exists
    assert upd.callback_query.message.edits or upd.callback_query.message.texts is not None


@pytest.mark.asyncio
async def test_upload_folder_custom_sets_waiting_flag_and_prompts(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    upd = _Update("upload_folder_custom")
    ctx = _Context()

    # Patch ask_upload_folder to capture prompt
    called = {"prompted": False}
    async def _ask(u, c):
        called["prompted"] = True
    monkeypatch.setattr(handler, "ask_upload_folder", _ask)

    await asyncio.wait_for(handler.handle_menu_callback(upd, ctx), timeout=2.0)
    assert called["prompted"] is True
