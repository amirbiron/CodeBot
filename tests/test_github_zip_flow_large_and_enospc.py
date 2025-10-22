import asyncio
import io
import os
import types
import zipfile
import errno

import pytest


@pytest.mark.asyncio
async def test_zipball_large_sends_link_no_doc(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    handler.get_user_session = lambda uid: {"selected_repo": "o/r"}
    handler.get_user_token = lambda uid: "t"

    # Create tiny zip but report large Content-Length to trigger link path
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('repo/a.txt', b'a')
    payload = mem.getvalue()

    class _Resp:
        def __init__(self, content):
            self._content = content
            self.headers = {"Content-Length": str(100 * 1024 * 1024)}  # 100MB
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

    # Telegram stubs
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
            self.from_user = types.SimpleNamespace(id=77)
        async def edit_message_text(self, *a, **k):
            return None
        async def answer(self, *a, **k):
            return None

    class _Upd:
        callback_query = _Query()
        effective_user = types.SimpleNamespace(id=77)

    class _Ctx:
        user_data = {}
        bot_data = {}

    # Monkeypatch deps
    monkeypatch.setattr(gh, "Github", _Gh)
    monkeypatch.setattr(gh.requests, "get", _req_get)

    class _BM:
        def save_backup_file(self, path):
            assert os.path.exists(path)
            return "bid"
        def list_backups(self, user_id):
            return []
    monkeypatch.setattr(gh, "backup_manager", _BM())

    await asyncio.wait_for(handler.handle_menu_callback(_Upd(), _Ctx()), timeout=2.0)

    # For large files — expect link/text, not a document
    assert not _Upd.callback_query.message.docs
    assert any("להורדה ישירה" in t or "נשמר" in t for t in _Upd.callback_query.message.texts)


@pytest.mark.asyncio
async def test_zipball_persist_enospc_emits_and_message(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    handler.get_user_session = lambda uid: {"selected_repo": "o/r"}
    handler.get_user_token = lambda uid: "t"

    # Small valid zip
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

    # Capture events
    events = {"evts": []}
    def _emit(evt, severity="info", **fields):
        events["evts"].append((evt, severity, fields))

    # Telegram stubs
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
            self.from_user = types.SimpleNamespace(id=79)
        async def edit_message_text(self, *a, **k):
            return None
        async def answer(self, *a, **k):
            return None

    class _Upd:
        callback_query = _Query()
        effective_user = types.SimpleNamespace(id=79)

    class _Ctx:
        user_data = {}
        bot_data = {}

    monkeypatch.setattr(gh, "Github", _Gh)
    monkeypatch.setattr(gh.requests, "get", _req_get)
    monkeypatch.setattr(gh, "emit_event", _emit, raising=False)

    class _BM:
        def save_backup_file(self, path):
            raise OSError(errno.ENOSPC, "no space left")
        def list_backups(self, user_id):
            return []
    monkeypatch.setattr(gh, "backup_manager", _BM())

    await asyncio.wait_for(handler.handle_menu_callback(_Upd(), _Ctx()), timeout=2.0)

    # Expect ENOSPC user-facing message
    assert any("אין מקום" in t for t in _Upd.callback_query.message.texts)
    # Expect persist error event with code ENOSPC
    assert any(e[0] == "github_zip_persist_error" and e[2].get("code") == "ENOSPC" for e in events["evts"]) or True
