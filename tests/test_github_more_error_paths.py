import types
import pytest

import github_menu_handler as gh


@pytest.mark.asyncio
async def test_zipball_fetch_error_emits_and_counts(monkeypatch):
    handler = gh.GitHubMenuHandler()

    handler.get_user_session = lambda uid: {"selected_repo": "owner/repo"}
    handler.get_user_token = lambda uid: "t"

    # Stub Github repo to provide archive link
    class _Repo:
        full_name = "owner/repo"
        name = "repo"
        default_branch = "main"
        def get_archive_link(self, *a, **k):
            return "https://example.invalid/archive.zip"
    class _GH:
        def __init__(self, token):
            pass
        def get_repo(self, name):
            return _Repo()
    monkeypatch.setattr(gh, "Github", _GH, raising=False)

    # Force requests.get().raise_for_status to raise to simulate fetch error
    class _Resp:
        content = b""
        def raise_for_status(self):
            raise RuntimeError("fetch-fail")
    monkeypatch.setattr(gh, "requests", types.SimpleNamespace(get=lambda *a, **k: _Resp()))

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
        data = "download_zip:"
        message = _Msg()
        from_user = types.SimpleNamespace(id=1)
        async def edit_message_text(self, *a, **k):
            return None
        async def answer(self, *a, **k):
            return None
    class _Update:
        callback_query = _Query()
        effective_user = types.SimpleNamespace(id=1)
    class _Ctx:
        user_data = {}
        bot_data = {}

    await handler.handle_menu_callback(_Update(), _Ctx())

    assert any(e[0] == "github_zipball_fetch_error" for e in events["evts"]) and any(e[0] == "errors_total_inc" for e in events["evts"]) 


@pytest.mark.asyncio
async def test_github_safe_delete_error_emits_and_counts(monkeypatch):
    handler = gh.GitHubMenuHandler()
    handler.get_user_session = lambda uid: {"selected_repo": "owner/repo"}
    handler.get_user_token = lambda uid: "t"

    # Prepare selection for multi_execute delete flow
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
            self.user_data = {"multi_mode": True, "multi_selection": ["a.txt", "b.txt"]}
            self.bot_data = {}
    ctx = _Ctx()

    # Github stub that raises during safe delete branch (create_git_ref)
    class _Repo:
        default_branch = "main"
        def get_git_ref(self, *a, **k):
            return types.SimpleNamespace(object=types.SimpleNamespace(sha="sha"))
        def create_git_ref(self, *a, **k):
            raise RuntimeError("create-ref-fail")
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

    await handler.handle_menu_callback(_Upd(), ctx)

    assert any(e[0] == "github_safe_delete_error" for e in events["evts"]) and any(e[0] == "errors_total_inc" for e in events["evts"]) 
