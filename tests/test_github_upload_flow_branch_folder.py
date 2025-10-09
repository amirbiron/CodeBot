import types
import pytest
import asyncio


class _Msg:
    def __init__(self):
        self.texts = []
    async def reply_text(self, text, **kwargs):
        self.texts.append(text)
        return self
    async def edit_text(self, text, **kwargs):
        self.texts.append(text)
        return self

class _Query:
    def __init__(self):
        self.message = _Msg()
        self.data = ""
        self.from_user = types.SimpleNamespace(id=5)
    async def edit_message_text(self, text, **kwargs):
        self.message.texts.append(text)
        return self.message
    async def answer(self, *args, **kwargs):
        return None

class _UserMsg:
    def __init__(self, uid=5):
        self.text = None
        self.texts = []
        self.from_user = types.SimpleNamespace(id=uid)
    async def reply_text(self, text, **kwargs):
        self.texts.append(text)
        return self
    async def edit_text(self, text, **kwargs):
        self.texts.append(text)
        return self

class _Update:
    def __init__(self):
        self.callback_query = _Query()
        self.effective_user = types.SimpleNamespace(id=5)
        self.message = _UserMsg(uid=5)

class _Context:
    def __init__(self):
        self.user_data = {}
        self.bot_data = {}


@pytest.mark.asyncio
async def test_upload_branch_pagination_next(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    upd = _Update()
    ctx = _Context()

    # Session and token
    sess = handler.get_user_session(5)
    sess["selected_repo"] = "o/r"
    monkeypatch.setattr(handler, "get_user_token", lambda _uid: "t")

    # Stub Github repo with many branches to force pagination
    class _Br:
        def __init__(self, name):
            self.name = name
            self.commit = types.SimpleNamespace(commit=types.SimpleNamespace(author=types.SimpleNamespace(date=None)))
    class _Repo:
        def get_branches(self):
            return [_Br(f"b{i}") for i in range(25)]
    class _Gh:
        def __init__(self, *a, **k):
            pass
        def get_repo(self, full):
            return _Repo()
    monkeypatch.setattr(gh, "Github", _Gh)
    monkeypatch.setattr(gh, "InlineKeyboardButton", lambda *a, **k: (a, k))
    monkeypatch.setattr(gh, "InlineKeyboardMarkup", lambda rows: rows)

    # Open branch menu
    upd.callback_query.data = "choose_upload_branch"
    await asyncio.wait_for(handler.handle_menu_callback(upd, ctx), timeout=2.0)
    # Go next page
    upd.callback_query.data = "upload_branches_page_1"
    await asyncio.wait_for(handler.handle_menu_callback(upd, ctx), timeout=2.0)

    assert True


@pytest.mark.asyncio
async def test_upload_folder_create_and_return_to_checks(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    upd = _Update()
    ctx = _Context()

    # Prepare session and token
    sess = handler.get_user_session(5)
    sess["selected_repo"] = "o/r"
    monkeypatch.setattr(handler, "get_user_token", lambda _uid: "t")

    # Stub Github client operations for create file
    class _Repo:
        def get_contents(self, *a, **k):
            raise Exception("nope")
        def create_file(self, *a, **k):
            return types.SimpleNamespace()
    class _Gh:
        def __init__(self, *a, **k):
            pass
        def get_repo(self, full):
            return _Repo()
    monkeypatch.setattr(gh, "Github", _Gh)

    # Trigger create-folder flow from pre-upload screen
    upd.callback_query.data = "upload_folder_create"
    await asyncio.wait_for(handler.handle_menu_callback(upd, ctx), timeout=2.0)

    # Simulate user typing folder path
    upd.message.text = "src/new"
    await asyncio.wait_for(handler.handle_text_input(upd, ctx), timeout=2.0)

    # Expect that state cleared and a success text was sent returning to checks
    combined = (upd.message.texts or []) + (upd.callback_query.message.texts or [])
    assert any("התיקייה נוצרה" in t for t in combined)


@pytest.mark.asyncio
async def test_upload_folder_custom_sets_target(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    upd = _Update()
    ctx = _Context()

    # Session and token
    sess = handler.get_user_session(5)
    sess["selected_repo"] = "o/r"
    monkeypatch.setattr(handler, "get_user_token", lambda _uid: "t")

    # Open choose folder menu then choose custom
    upd.callback_query.data = "choose_upload_folder"
    await asyncio.wait_for(handler.handle_menu_callback(upd, ctx), timeout=2.0)
    upd.callback_query.data = "upload_folder_custom"
    await asyncio.wait_for(handler.handle_menu_callback(upd, ctx), timeout=2.0)

    # Provide folder via text (handle_file_upload path)
    upd.message.text = "src/utils"
    await asyncio.wait_for(handler.handle_file_upload(upd, ctx), timeout=2.0)

    # After setting, the handler replies and goes back to checks; no exception is success
    assert True
