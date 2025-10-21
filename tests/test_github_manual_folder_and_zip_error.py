import types
import pytest
import asyncio


class _Msg:
    def __init__(self):
        self.texts = []

    async def reply_text(self, text, **kwargs):
        self.texts.append(text)
        return self


class _Query:
    def __init__(self, uid=101, data=""):
        self.data = data
        self.from_user = types.SimpleNamespace(id=uid)
        self.message = _Msg()
        self.edits = []

    async def edit_message_text(self, text=None, **kwargs):
        self.edits.append(text or "")
        return self.message

    async def answer(self, *args, **kwargs):
        return None


class _Update:
    def __init__(self, uid=101, data=""):
        self.callback_query = _Query(uid=uid, data=data)
        self.effective_user = types.SimpleNamespace(id=uid)
        self.message = types.SimpleNamespace(text=None, from_user=types.SimpleNamespace(id=uid))


class _Ctx:
    def __init__(self):
        self.user_data = {}
        self.bot_data = {}


@pytest.mark.asyncio
async def test_manual_upload_folder_text_input_routes_and_sets_target(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()

    # Stub show_pre_upload_check to capture call
    called = {"pre": False}

    async def _pre(upd, ctx):
        called["pre"] = True
        return None

    monkeypatch.setattr(handler, "show_pre_upload_check", _pre)

    class _Msg2:
        def __init__(self):
            self.text = " //my//nested/path/ "
            self.from_user = types.SimpleNamespace(id=202)

        async def reply_text(self, text, **kwargs):
            return None

    upd = types.SimpleNamespace(message=_Msg2(), effective_user=types.SimpleNamespace(id=202))
    ctx = _Ctx()
    ctx.user_data["waiting_for_upload_folder"] = True

    # Execute the text handler directly
    res = await asyncio.wait_for(handler.handle_text_input(upd, ctx), timeout=2.0)

    assert res is True
    assert ctx.user_data.get("waiting_for_upload_folder") is False
    # Expect normalized path without leading/trailing slashes and collapsed
    assert ctx.user_data.get("upload_target_folder") == "my/nested/path"
    assert called["pre"] is True


@pytest.mark.asyncio
async def test_download_zip_repo_error_does_not_open_backups_list(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()

    # Stubs
    class _Repo:
        full_name = "o/r"
        name = "r"

        def get_archive_link(self, _):
            return "https://example.com/archive.zip"

    class _Gh:
        def __init__(self, *a, **k):
            pass

        def get_repo(self, _):
            return _Repo()

    class _Resp:
        def raise_for_status(self):
            raise Exception("boom")
    def _req_get(_url, headers=None, stream=False, timeout=60):
        return _Resp()

    # Patch environment
    monkeypatch.setattr(gh, "Github", _Gh)
    monkeypatch.setattr(gh.requests, "get", _req_get)
    monkeypatch.setattr(handler, "get_user_token", lambda _uid: "t")
    monkeypatch.setattr(gh, "InlineKeyboardButton", lambda *a, **k: (a, k))
    monkeypatch.setattr(gh, "InlineKeyboardMarkup", lambda rows: rows)

    # Keep a sentinel backup handler that should NOT be used when the ZIP fails
    class _BH:
        def __init__(self):
            self.called = False

        async def _show_backups_list(self, *a, **k):
            self.called = True

    ctx = _Ctx()
    ctx.bot_data["backup_handler"] = _BH()

    upd = _Update(uid=77, data="download_zip:")
    # Prime session
    sess = handler.get_user_session(77)
    sess["selected_repo"] = "o/r"

    # Run
    await asyncio.wait_for(handler.handle_menu_callback(upd, ctx), timeout=2.0)

    # Expect an error edit and that backup list wasn't invoked
    assert any(str(e).startswith("❌ שגיאה בהורדת ZIP של הריפו:") for e in upd.callback_query.edits)
    assert ctx.bot_data["backup_handler"].called is False
