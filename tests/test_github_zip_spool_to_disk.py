import asyncio
import io
import os
import types
import zipfile

import pytest


@pytest.mark.asyncio
async def test_zipball_spools_to_disk_and_uses_save_backup_file(monkeypatch, tmp_path):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()

    # Session/token
    handler.get_user_session = lambda uid: {"selected_repo": "o/r"}
    handler.get_user_token = lambda uid: "t"

    # Create a small valid zip payload
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('repo/a.txt', b'a')
    payload = mem.getvalue()

    class _Resp:
        def __init__(self, content):
            self._content = content
            self.headers = {"Content-Length": str(len(content))}
        def raise_for_status(self):
            return None
        def iter_content(self, chunk_size=131072):
            for i in range(0, len(self._content), chunk_size):
                yield self._content[i:i+chunk_size]

    def _req_get(_url, headers=None, stream=False, timeout=60):
        return _Resp(payload)

    class _Repo:
        full_name = "o/r"
        name = "r"
        default_branch = "main"
        def get_archive_link(self, _):
            return "https://example.com/archive.zip"

    class _Gh:
        def __init__(self, *a, **k):
            pass
        def get_repo(self, _):
            return _Repo()

    # Stub Telegram message
    class _Msg:
        def __init__(self):
            self.docs = []
            self.texts = []
        async def reply_document(self, document=None, filename=None, caption=None):
            self.docs.append({"filename": filename, "caption": caption})
            return None
        async def reply_text(self, text, **kwargs):
            self.texts.append(text)
            return None

    class _Query:
        def __init__(self):
            self.data = "download_zip:"
            self.message = _Msg()
            self.from_user = types.SimpleNamespace(id=7)
        async def edit_message_text(self, *a, **k):
            return None
        async def answer(self, *a, **k):
            return None

    class _Upd:
        callback_query = _Query()
        effective_user = types.SimpleNamespace(id=7)

    class _Ctx:
        user_data = {}
        bot_data = {}

    # Monkeypatch external deps
    monkeypatch.setattr(gh, "Github", _Gh)
    monkeypatch.setattr(gh.requests, "get", _req_get)

    # Track that save_backup_file is used and receives a path that exists at call time
    called = {"args": None}
    def _save_backup_file(path):
        assert os.path.exists(path)
        assert zipfile.is_zipfile(path)
        called["args"] = path
        return "bid"

    class _BM:
        def save_backup_file(self, p):
            return _save_backup_file(p)
        def list_backups(self, user_id):
            return []

    monkeypatch.setattr(gh, "backup_manager", _BM())

    # Run flow
    await asyncio.wait_for(handler.handle_menu_callback(_Upd(), _Ctx()), timeout=2.0)

    # Assert save_backup_file was called with a path
    assert called["args"], "save_backup_file was not called"
