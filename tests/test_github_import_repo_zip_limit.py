import io
import types
import zipfile

import pytest


@pytest.mark.asyncio
async def test_import_repo_allows_zip_over_content_limit(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    monkeypatch.setattr(handler, "get_user_token", lambda _uid: "token")

    class _Repo:
        def get_archive_link(self, *_a, **_k):
            return "https://example.com/archive.zip"

    class _Gh:
        def __init__(self, *a, **k):
            pass

        def get_repo(self, _full):
            return _Repo()

    monkeypatch.setattr(gh, "Github", _Gh)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("repo-123/file.txt", "hello")
    payload = buf.getvalue()

    class _Resp:
        def __init__(self, content):
            self._content = content
            self.headers = {"Content-Length": str(gh.IMPORT_MAX_TOTAL_BYTES + 1024)}

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=131072):
            for i in range(0, len(self._content), chunk_size):
                yield self._content[i:i + chunk_size]

    monkeypatch.setattr(gh, "http_request", lambda *a, **k: _Resp(payload))

    saved = {"n": 0}

    class _Facade:
        def get_latest_version(self, user_id, file_name):
            return None

        def save_file(self, **kwargs):
            saved["n"] += 1
            return True

    monkeypatch.setattr(gh, "_get_files_facade", lambda: _Facade())

    class _Msg:
        def __init__(self):
            self.texts = []

        async def edit_text(self, text, **kwargs):
            self.texts.append(text)
            return self

    class _Query:
        def __init__(self):
            self.from_user = types.SimpleNamespace(id=1)
            self.message = _Msg()

        async def edit_message_text(self, text, **kwargs):
            self.message.texts.append(text)
            return self.message

        async def answer(self, *args, **kwargs):
            return None

    class _Update:
        def __init__(self):
            self.callback_query = _Query()

    class _Context:
        def __init__(self):
            self.user_data = {}
            self.bot_data = {}

    upd, ctx = _Update(), _Context()

    await handler.import_repo_from_zip(upd, ctx, "o/r", "main")

    assert saved["n"] == 1
    combined = "\n".join(upd.callback_query.message.texts)
    assert "repo:o/r" in combined
    assert "20MB" not in combined
