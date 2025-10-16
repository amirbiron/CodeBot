import types
import pytest

import github_menu_handler as gh


@pytest.mark.asyncio
async def test_github_zip_persist_error_emits(monkeypatch):
    handler = gh.GitHubMenuHandler()

    handler.get_user_session = lambda uid: {"selected_repo": "owner/repo"}
    handler.get_user_token = lambda uid: "t"

    # Repo stub for folder zip branch
    class _FileObj:
        size = 3
        decoded_content = b"abc"
    class _Repo:
        full_name = "owner/repo"
        name = "repo"
        default_branch = "main"
        def get_contents(self, path=""):
            # first call with "folder" returns a list with one file item
            if path in ("folder", "folder/"):
                return [types.SimpleNamespace(type="file", name="f.txt", path="folder/f.txt")]
            # second call returns file object with content
            return _FileObj()
    class _GH:
        def __init__(self, token):
            pass
        def get_repo(self, name):
            return _Repo()
    monkeypatch.setattr(gh, "Github", _GH, raising=False)

    events = {"evts": []}
    def _emit(evt, severity="info", **fields):
        events["evts"].append((evt, severity, fields))
    monkeypatch.setattr(gh, "emit_event", _emit, raising=False)

    # Force persist to raise
    class _BM:
        def save_backup_bytes(self, *a, **k):
            raise RuntimeError("persist-fail")
        def list_backups(self, *a, **k):
            return []
    monkeypatch.setattr(gh, "backup_manager", _BM(), raising=False)

    # update/context
    class _Msg:
        async def reply_document(self, *a, **k):
            return None
        async def reply_text(self, *a, **k):
            return None
    class _Query:
        data = "download_zip:folder"
        message = _Msg()
        from_user = types.SimpleNamespace(id=1)
        async def edit_message_text(self, *a, **k):
            return None
        async def answer(self, *a, **k):
            return None
    class _Upd:
        callback_query = _Query()
        effective_user = types.SimpleNamespace(id=1)
    class _Ctx:
        user_data = {}
        bot_data = {}

    await handler.handle_menu_callback(_Upd(), _Ctx())

    assert any(e[0] == "github_zip_persist_error" for e in events["evts"]) 


@pytest.mark.asyncio
async def test_github_delete_file_error_emits_and_counts(monkeypatch):
    handler = gh.GitHubMenuHandler()
    handler.get_user_session = lambda uid: {"selected_repo": "owner/repo"}
    handler.get_user_token = lambda uid: "t"

    # direct delete branch (safe_delete=False)
    class _Repo:
        default_branch = "main"
        full_name = "owner/repo"
        def get_contents(self, path):
            return types.SimpleNamespace(path=path, sha="sha1")
        def delete_file(self, *a, **k):
            raise RuntimeError("delete-fail")
    class _GH:
        def __init__(self, token):
            pass
        def get_repo(self, *a, **k):
            return _Repo()
    monkeypatch.setattr(gh, "Github", _GH, raising=False)

    events = {"evts": []}
    def _emit(evt, severity="info", **fields):
        events["evts"].append((evt, severity, fields))
    class _Errors:
        def labels(self, **kw):
            class _C:
                def inc(self_inner):
                    events["evts"].append(("errors_total_inc", "info", kw))
            return _C()
    monkeypatch.setattr(gh, "emit_event", _emit, raising=False)
    monkeypatch.setattr(gh, "errors_total", _Errors(), raising=False)

    class _Msg:
        async def reply_text(self, *a, **k):
            return None
    class _Query:
        data = "multi_execute"
        message = _Msg()
        from_user = types.SimpleNamespace(id=1)
        async def edit_message_text(self, *a, **k):
            return None
        async def answer(self, *a, **k):
            return None
    class _Upd:
        callback_query = _Query()
        effective_user = types.SimpleNamespace(id=1)
    class _Ctx:
        def __init__(self):
            self.user_data = {"multi_mode": True, "multi_selection": ["a.txt"], "safe_delete": False}
            self.bot_data = {}
    ctx = _Ctx()

    await handler.handle_menu_callback(_Upd(), ctx)

    assert any(e[0] == "github_delete_file_error" for e in events["evts"]) and any(e[0] == "errors_total_inc" for e in events["evts"]) 
