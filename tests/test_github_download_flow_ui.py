import asyncio
import types
import pytest


@pytest.mark.asyncio
async def test_download_menu_enters_safe_state_and_hides_delete_buttons(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()

    # Stubs for Telegram buttons/markup
    class Btn:
        def __init__(self, text, callback_data=None):
            self.text = text
            self.callback_data = callback_data

    def Markup(rows):
        return rows

    # Query/Update stubs capturing reply_markup
    class Msg:
        def __init__(self):
            self.edited = None

        async def edit_text(self, text, **kwargs):
            self.edited = {"text": text, **kwargs}
            return self

    class Query:
        def __init__(self):
            self.data = "download_file_menu"
            self.from_user = types.SimpleNamespace(id=123)
            self.message = Msg()
            self.captured = None

        async def edit_message_text(self, text=None, reply_markup=None, **kwargs):
            self.captured = reply_markup
            return self.message

        async def answer(self, *args, **kwargs):
            return None

    class Update:
        def __init__(self):
            self.callback_query = Query()
            self.effective_user = types.SimpleNamespace(id=123)

    class Context:
        def __init__(self):
            self.user_data = {}
            self.bot_data = {}

    # Minimal GitHub API stubs
    class _File:
        def __init__(self, name, path, size=10):
            self.type = "file"
            self.name = name
            self.path = path
            self.size = size

    class _Dir:
        def __init__(self, name, path):
            self.type = "dir"
            self.name = name
            self.path = path

    class _Repo:
        def get_contents(self, path="", ref=None):
            return [_Dir("src", "src"), _File("README.md", "README.md", 16)]

    class _Gh:
        def __init__(self, *a, **k):
            pass

        def get_repo(self, _):
            return _Repo()

    monkeypatch.setattr(gh, "Github", _Gh)
    monkeypatch.setattr(gh, "InlineKeyboardButton", Btn)
    monkeypatch.setattr(gh, "InlineKeyboardMarkup", Markup)
    # Token and session
    monkeypatch.setattr(handler, "get_user_token", lambda _uid: "t")
    session = handler.get_user_session(123)
    session["selected_repo"] = "o/r"

    upd, ctx = Update(), Context()
    await asyncio.wait_for(handler.handle_menu_callback(upd, ctx), timeout=2.0)

    # State assertions per .cursorrules
    assert ctx.user_data.get("browse_action") == "download"
    assert ctx.user_data.get("multi_mode") is False
    assert ctx.user_data.get("safe_delete") is True

    # UI assertions: no delete buttons/safe toggle; has download actions
    rm = upd.callback_query.captured
    assert rm is not None
    buttons = [b for row in rm for b in row]
    callback_datas = [getattr(b, "callback_data", "") for b in buttons]
    texts = [getattr(b, "text", "") for b in buttons]

    assert not any(str(cd).startswith("browse_select_delete") for cd in callback_datas)
    assert not any("מצב מחיקה" in t for t in texts)
    assert any(str(cd).startswith("browse_select_download") for cd in callback_datas)
    assert any("הורד תיקייה" in t for t in texts)


@pytest.mark.asyncio
async def test_download_mode_multi_toggle_shows_zip_not_delete(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()

    class Btn:
        def __init__(self, text, callback_data=None):
            self.text = text
            self.callback_data = callback_data

    def Markup(rows):
        return rows

    class Msg:
        def __init__(self):
            self.edited = None

        async def edit_text(self, text, **kwargs):
            self.edited = {"text": text, **kwargs}
            return self

    class Query:
        def __init__(self):
            self.data = "download_file_menu"
            self.from_user = types.SimpleNamespace(id=9)
            self.message = Msg()
            self.captured = None
            self.captured2 = None

        async def edit_message_text(self, text=None, reply_markup=None, **kwargs):
            self.captured = reply_markup
            return self.message

        async def answer(self, *args, **kwargs):
            return None

    class Update:
        def __init__(self):
            self.callback_query = Query()
            self.effective_user = types.SimpleNamespace(id=9)

    class Context:
        def __init__(self):
            self.user_data = {}
            self.bot_data = {}

    class _File:
        def __init__(self, name, path, size=10):
            self.type = "file"
            self.name = name
            self.path = path
            self.size = size

    class _Repo:
        def get_contents(self, path="", ref=None):
            return [_File("a.txt", "a.txt", 12), _File("b.txt", "b.txt", 34)]

    class _Gh:
        def __init__(self, *a, **k):
            pass

        def get_repo(self, _):
            return _Repo()

    monkeypatch.setattr(gh, "Github", _Gh)
    monkeypatch.setattr(gh, "InlineKeyboardButton", Btn)
    monkeypatch.setattr(gh, "InlineKeyboardMarkup", Markup)
    monkeypatch.setattr(handler, "get_user_token", lambda _uid: "t")
    session = handler.get_user_session(9)
    session["selected_repo"] = "o/r"

    upd, ctx = Update(), Context()
    # Enter download browser
    await asyncio.wait_for(handler.handle_menu_callback(upd, ctx), timeout=2.0)

    # Toggle multi select in download mode -> keyboard-only update
    upd.callback_query.data = "multi_toggle"

    captured = {}

    async def _safe_edit_rm(q, reply_markup=None):
        captured["rm"] = reply_markup

    monkeypatch.setattr(gh.TelegramUtils, "safe_edit_message_reply_markup", _safe_edit_rm)

    await asyncio.wait_for(handler.handle_menu_callback(upd, ctx), timeout=2.0)

    rm2 = captured.get("rm")
    assert rm2 is not None
    buttons2 = [b for row in rm2 for b in row]
    cds2 = [getattr(b, "callback_data", "") for b in buttons2]
    texts2 = [getattr(b, "text", "") for b in buttons2]

    # Expect multi ZIP action and no delete actions/safe toggle in download mode
    assert any(cd == "multi_execute" for cd in cds2)
    assert any("הורד נבחרים" in t for t in texts2)
    assert not any(str(cd).startswith("browse_select_delete") for cd in cds2)
    assert not any("מצב מחיקה" in t for t in texts2)


@pytest.mark.asyncio
async def test_stays_in_download_mode_after_file_download(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()

    class Btn:
        def __init__(self, text, callback_data=None):
            self.text = text
            self.callback_data = callback_data

    def Markup(rows):
        return rows

    class Msg:
        def __init__(self):
            self.replies = []

        async def reply_document(self, **kwargs):
            self.replies.append(kwargs)
            return None

        async def edit_text(self, text, **kwargs):
            return self

    class Query:
        def __init__(self):
            self.data = "download_file_menu"
            self.from_user = types.SimpleNamespace(id=77)
            self.message = Msg()
            self.captured_rm = None

        async def edit_message_text(self, text=None, reply_markup=None, **kwargs):
            self.captured_rm = reply_markup
            return self.message

        async def answer(self, *args, **kwargs):
            return None

    class Update:
        def __init__(self):
            self.callback_query = Query()
            self.effective_user = types.SimpleNamespace(id=77)

    class Context:
        def __init__(self):
            self.user_data = {}
            self.bot_data = {}

    class _File:
        def __init__(self, name, path, size=10):
            self.type = "file"
            self.name = name
            self.path = path
            self.size = size

        @property
        def decoded_content(self):
            return b"hello world\n"

    class _Repo:
        def get_contents(self, path="", ref=None):
            if path and path.endswith("README.md"):
                return _File("README.md", "README.md", 12)
            return [_File("README.md", "README.md", 12)]

    class _Gh:
        def __init__(self, *a, **k):
            pass

        def get_repo(self, _):
            return _Repo()

    monkeypatch.setattr(gh, "Github", _Gh)
    monkeypatch.setattr(gh, "InlineKeyboardButton", Btn)
    monkeypatch.setattr(gh, "InlineKeyboardMarkup", Markup)
    monkeypatch.setattr(handler, "get_user_token", lambda _uid: "t")
    session = handler.get_user_session(77)
    session["selected_repo"] = "o/r"

    upd, ctx = Update(), Context()
    # Enter browser
    await asyncio.wait_for(handler.handle_menu_callback(upd, ctx), timeout=2.0)
    # Click the first download button for README.md
    upd.callback_query.data = "browse_select_download:README.md"

    captured = {}

    async def _safe_edit_rm(q, reply_markup=None):
        captured["rm"] = reply_markup

    monkeypatch.setattr(gh.TelegramUtils, "safe_edit_message_reply_markup", _safe_edit_rm)

    await asyncio.wait_for(handler.handle_menu_callback(upd, ctx), timeout=2.0)

    # Still in download mode and no delete UI exposed
    assert ctx.user_data.get("browse_action") == "download"
    rm = captured.get("rm")
    assert rm is not None
    all_texts = [getattr(b, "text", "") for row in rm for b in row]
    assert not any("מצב מחיקה" in t for t in all_texts)
    assert any("הורד תיקייה" in t for t in all_texts)

