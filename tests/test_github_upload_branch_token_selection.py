import types
import pytest
import asyncio


class _Msg:
    def __init__(self):
        self.edits = []
        self.texts = []
    async def reply_text(self, text=None, **kwargs):
        self.texts.append(text)
        return self

class _Query:
    def __init__(self, uid=21, data=""):
        self.data = data
        self.from_user = types.SimpleNamespace(id=uid)
        self.message = _Msg()
        self.answered = []
    async def edit_message_text(self, text=None, reply_markup=None, parse_mode=None):
        self.message.edits.append(text)
        return self.message
    async def answer(self, text=None, **kwargs):
        self.answered.append(text)
        return None

class _Update:
    def __init__(self, data=""):
        self.callback_query = _Query(data=data)
        self.effective_user = types.SimpleNamespace(id=21)

class _Ctx:
    def __init__(self):
        self.user_data = {}
        self.bot_data = {}


@pytest.mark.asyncio
async def test_branch_token_selection_success(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    upd = _Update("choose_upload_branch")
    ctx = _Ctx()

    # session and token
    sess = handler.get_user_session(21)
    sess["selected_repo"] = "o/r"
    monkeypatch.setattr(handler, "get_user_token", lambda _uid: "tok")

    # deterministic token
    monkeypatch.setattr(gh.secrets, "token_urlsafe", lambda n=6: "TokFix")

    class _Br:
        def __init__(self, name):
            self.name = name
            self.commit = types.SimpleNamespace(commit=types.SimpleNamespace(author=types.SimpleNamespace(date=None)))
    class _Repo:
        def get_branches(self):
            return [_Br("feature/super-long-branch-name-that-should-not-be-truncated")]
    class _Gh:
        def __init__(self, *a, **k):
            pass
        def get_repo(self, full):
            return _Repo()
    monkeypatch.setattr(gh, "Github", _Gh)
    monkeypatch.setattr(gh, "InlineKeyboardButton", lambda *a, **k: (a, k))
    monkeypatch.setattr(gh, "InlineKeyboardMarkup", lambda rows: rows)

    # stub show_pre_upload_check to assert branch was set
    called = {"branch": None}
    async def _pre(u, c):
        called["branch"] = c.user_data.get("upload_target_branch")
    monkeypatch.setattr(handler, "show_pre_upload_check", _pre)

    await asyncio.wait_for(handler.handle_menu_callback(upd, ctx), timeout=2.0)
    # select the token created above
    upd.callback_query.data = "upload_select_branch_tok:TokFix"
    await asyncio.wait_for(handler.handle_menu_callback(upd, ctx), timeout=2.0)

    assert called["branch"] == "feature/super-long-branch-name-that-should-not-be-truncated"


@pytest.mark.asyncio
async def test_branch_token_selection_missing_token_alert(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    upd = _Update("upload_select_branch_tok:missing")
    ctx = _Ctx()

    # capture answers
    answers = []
    async def _ans(text=None, **kwargs):
        answers.append(text)
    monkeypatch.setattr(upd.callback_query, "answer", _ans)

    await asyncio.wait_for(handler.handle_menu_callback(upd, ctx), timeout=2.0)
    assert answers != []
