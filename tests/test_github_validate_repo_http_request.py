import io
import os
import zipfile
import pytest


class _Msg:
    def __init__(self):
        self.texts = []
    async def edit_text(self, text):
        self.texts.append(text)
        return self

class _Query:
    def __init__(self, user_id):
        self.from_user = type("U", (), {"id": user_id})()
        self.message = _Msg()
        self.data = "validate_repo"
    async def edit_message_text(self, text, **kwargs):
        # return a message-like object with edit_text
        return _Msg()
    async def answer(self, *a, **k):
        return None

class _Update:
    def __init__(self, user_id=1):
        self.callback_query = _Query(user_id)

class _Context:
    def __init__(self):
        self.user_data = {}


def _zip_bytes():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('root/file.txt', 'hello')
    return buf.getvalue()


@pytest.mark.asyncio
async def test_validate_repo_uses_http_request(monkeypatch):
    # Arrange minimal env for module imports
    monkeypatch.setenv("BOT_TOKEN", "x")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/db")

    import github_menu_handler as gh

    # Fake GitHub client
    class _Repo:
        def get_archive_link(self, *_a, **_k):
            return "http://example.com/archive.zip"
    class _GH:
        def __init__(self, *a, **k):
            pass
        def get_repo(self, *_):
            return _Repo()

    called = {"n": 0}

    def fake_http_request(method, url, **kw):
        called["n"] += 1
        class Resp:
            status_code = 200
            content = _zip_bytes()
            def raise_for_status(self):
                return None
        return Resp()

    # Monkeypatch external deps
    monkeypatch.setattr(gh, "Github", _GH)
    monkeypatch.setattr(gh, "http_request", fake_http_request)

    h = gh.GitHubMenuHandler()
    # Prepare session
    sess = h.get_user_session(1)
    sess["selected_repo"] = "owner/repo"
    # minimal token
    def fake_get_user_token(_self, _uid):
        return "tkn"
    monkeypatch.setattr(gh.GitHubMenuHandler, "get_user_token", fake_get_user_token)

    update = _Update(user_id=1)
    ctx = _Context()

    # Act
    await h.handle_menu_callback(update, ctx)

    # Assert: our fake http_request called at least once
    assert called["n"] >= 1
