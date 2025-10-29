import io
import os
import zipfile
import pytest


def _zip_bytes():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('file.txt', 'hello')
    return buf.getvalue()


class _Msg:
    def __init__(self):
        self.texts = []
        self.docs = []
    async def edit_text(self, text):
        self.texts.append(text)
        return self
    async def reply_text(self, text, **kwargs):
        self.texts.append(text)
        return self
    async def reply_document(self, document=None, filename=None, caption=None):
        self.docs.append((filename, caption))
        return self

class _Query:
    def __init__(self, user_id):
        self.from_user = type("U", (), {"id": user_id})()
        self.message = _Msg()
        self.data = "download_zip:"
    async def edit_message_text(self, text, **kwargs):
        return _Msg()
    async def answer(self, *a, **k):
        return None

class _Update:
    def __init__(self, user_id=1):
        self.callback_query = _Query(user_id)

class _Context:
    def __init__(self):
        self.user_data = {}
        self.bot_data = {}


@pytest.mark.asyncio
async def test_download_zip_root_uses_http_request(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "x")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/db")

    import github_menu_handler as gh

    # Fake Github client and repo
    class _Repo:
        full_name = "owner/repo"
        name = "repo"
        def get_archive_link(self, *a, **k):
            return "http://example.com/archive.zip"
    class _GH:
        def __init__(self, *a, **k):
            pass
        def get_repo(self, *_):
            return _Repo()

    # Track calls to http_request
    calls = {"n": 0}
    def fake_http_request(method, url, **kw):
        calls["n"] += 1
        class Resp:
            status_code = 200
            headers = {"Content-Length": "100"}
            def raise_for_status(self):
                return None
            def iter_content(self, chunk_size=8192):
                yield _zip_bytes()
        return Resp()

    # Backup manager stubs
    class _BM:
        def save_backup_file(self, path):
            return None
        def list_backups(self, user_id):
            return []
    monkeypatch.setattr(gh, "backup_manager", _BM())

    # Monkeypatch external deps
    monkeypatch.setattr(gh, "Github", _GH)
    monkeypatch.setattr(gh, "http_request", fake_http_request)

    h = gh.GitHubMenuHandler()
    sess = h.get_user_session(1)
    sess["selected_repo"] = "owner/repo"
    # minimal token
    def fake_get_user_token(_self, _uid):
        return "tkn"
    monkeypatch.setattr(gh.GitHubMenuHandler, "get_user_token", fake_get_user_token)

    update = _Update(user_id=1)
    ctx = _Context()

    await h.handle_menu_callback(update, ctx)

    assert calls["n"] >= 1
