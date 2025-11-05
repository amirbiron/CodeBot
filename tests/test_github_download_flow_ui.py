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


@pytest.mark.asyncio
async def test_download_zip_of_root_sends_backup_and_summary(monkeypatch):
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
            self.docs = []
            self.texts = []

        async def reply_document(self, document=None, filename=None, caption=None):
            self.docs.append({"filename": filename, "caption": caption})
            return None

        async def reply_text(self, text, **kwargs):
            self.texts.append(text)
            return None

        async def edit_text(self, text, **kwargs):
            return self

    class Query:
        def __init__(self):
            self.data = "download_file_menu"
            self.from_user = types.SimpleNamespace(id=51)
            self.message = Msg()
            self.answered = []

        async def edit_message_text(self, text=None, reply_markup=None, **kwargs):
            return self.message

        async def answer(self, *args, **kwargs):
            self.answered.append({"args": args, "kwargs": kwargs})
            return None

    class Update:
        def __init__(self):
            self.callback_query = Query()
            self.effective_user = types.SimpleNamespace(id=51)

    class Context:
        def __init__(self):
            self.user_data = {}
            self.bot_data = {}

    # Stub requests.get to return a tiny valid zip bytes
    import io, zipfile

    class _Resp:
        def __init__(self, content):
            self._content = content
            self.headers = {"Content-Length": str(len(content))}
        def raise_for_status(self):
            return None
        def iter_content(self, chunk_size=131072):
            # simple chunker
            for i in range(0, len(self._content), chunk_size):
                yield self._content[i:i+chunk_size]

    def _req_get(_url, headers=None, stream=False, timeout=60):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr('repo/file1.txt', b'hello')
            z.writestr('repo/file2.txt', b'world')
        return _Resp(buf.getvalue())

    # Also cover the path where Content-Length is larger than MAX_ZIP_TOTAL_BYTES → link fallback
    async def _run_and_assert_ok():
        upd2, ctx2 = Update(), Context()
        session2 = handler.get_user_session(51)
        session2["selected_repo"] = "o/r"
        await asyncio.wait_for(handler.handle_menu_callback(upd2, ctx2), timeout=2.0)
        upd2.callback_query.data = "download_zip:"
        await asyncio.wait_for(handler.handle_menu_callback(upd2, ctx2), timeout=2.0)
        assert upd2.callback_query.message.docs, "ZIP not sent"


    class _Repo:
        full_name = "o/r"
        name = "r"
        default_branch = "main"
        def get_archive_link(self, _):
            return "https://example.com/archive.zip"
        def get_contents(self, path="", ref=None):
            # דפדפן דורש מתוד זה; נחזיר רשימה ריקה לצורך הטסט
            return []

    class _Gh:
        def __init__(self, *a, **k):
            pass
        def get_repo(self, _):
            return _Repo()

    # Monkeypatches
    monkeypatch.setattr(gh, "Github", _Gh)
    monkeypatch.setattr(gh, "InlineKeyboardButton", Btn)
    monkeypatch.setattr(gh, "InlineKeyboardMarkup", Markup)
    monkeypatch.setattr(handler, "get_user_token", lambda _uid: "t")
    monkeypatch.setattr(gh.requests, "get", _req_get)

    # Backup manager stubs
    class _BM:
        def __init__(self):
            self.saved = []
            self.listed = []
        def save_backup_file(self, file_path):
            # במקום לשמור bytes, נרשום את הנתיב שקיבלנו (סימולציה של persist מדיסק)
            self.saved.append(("file", file_path))
            return "bid"
        def list_backups(self, user_id):
            self.listed.append(user_id)
            return []

    monkeypatch.setattr(gh, "backup_manager", _BM())

    upd, ctx = Update(), Context()
    session = handler.get_user_session(51)
    session["selected_repo"] = "o/r"

    # Enter menu then click download zip of root
    await asyncio.wait_for(handler.handle_menu_callback(upd, ctx), timeout=2.0)
    upd.callback_query.data = "download_zip:"
    await asyncio.wait_for(handler.handle_menu_callback(upd, ctx), timeout=2.0)

    # Assert doc sent and summary text appended
    assert upd.callback_query.message.docs, "ZIP not sent"
    assert any("BKP zip" in (d.get("filename") or "") for d in upd.callback_query.message.docs)
    assert upd.callback_query.message.texts, "Summary line not sent"


@pytest.mark.asyncio
async def test_share_folder_link_sends_link_and_stays(monkeypatch):
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
            self.sent_links = []
        async def reply_text(self, text, **kwargs):
            self.sent_links.append(text)
            return None
        async def edit_text(self, text, **kwargs):
            return self

    class Query:
        def __init__(self):
            self.data = "download_file_menu"
            self.from_user = types.SimpleNamespace(id=88)
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
            self.effective_user = types.SimpleNamespace(id=88)

    class Context:
        def __init__(self):
            self.user_data = {}
            self.bot_data = {}

    class _Repo:
        full_name = "o/r"
        default_branch = "main"
        def get_contents(self, path="", ref=None):
            return []

    class _Gh:
        def __init__(self, *a, **k):
            pass
        def get_repo(self, _):
            return _Repo()

    monkeypatch.setattr(gh, "Github", _Gh)
    monkeypatch.setattr(gh, "InlineKeyboardButton", Btn)
    monkeypatch.setattr(gh, "InlineKeyboardMarkup", Markup)
    monkeypatch.setattr(handler, "get_user_token", lambda _uid: "t")

    upd, ctx = Update(), Context()
    session = handler.get_user_session(88)
    session["selected_repo"] = "o/r"

    # Enter browser and press share_folder_link on root
    await asyncio.wait_for(handler.handle_menu_callback(upd, ctx), timeout=2.0)
    upd.callback_query.data = "share_folder_link:"

    await asyncio.wait_for(handler.handle_menu_callback(upd, ctx), timeout=2.0)

    # Link sent and still in browser with download UI
    assert upd.callback_query.message.sent_links
    rm = upd.callback_query.captured_rm
    assert rm is not None
    texts = [getattr(b, "text", "") for row in rm for b in row]
    assert any("הורד תיקייה" in t for t in texts)


def test_resolve_backup_version_increments_when_new_id_missing():
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    ctx = types.SimpleNamespace(user_data={})
    infos = [types.SimpleNamespace(repo="owner/repo", backup_id=f"bid{i}") for i in range(3)]

    version = handler._resolve_backup_version(ctx, "owner/repo", infos, "bid_new")

    assert version == 4


def test_resolve_backup_version_returns_existing_length_when_present():
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    ctx = types.SimpleNamespace(user_data={})
    infos = [
        types.SimpleNamespace(repo="owner/repo", backup_id="bid1"),
        types.SimpleNamespace(repo="owner/repo", backup_id="bid_new"),
        types.SimpleNamespace(repo="owner/repo", backup_id="bid2"),
    ]

    version = handler._resolve_backup_version(ctx, "owner/repo", infos, "bid_new")

    assert version == len(infos)


def test_resolve_backup_version_uses_cache_when_list_is_stale():
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    ctx = types.SimpleNamespace(user_data={})
    infos = [types.SimpleNamespace(repo="owner/repo", backup_id=f"bid{i}") for i in range(2)]

    handler._cache_recent_backup(
        ctx,
        backup_id="bid_cached",
        repo_full_name="owner/repo",
        path="",
        file_count=1,
        total_size=123,
        created_at="2025-01-01T00:00:00Z",
    )

    version = handler._resolve_backup_version(ctx, "owner/repo", infos, "bid_cached")

    assert version == len(infos) + 1


