import types
import pytest

import github_menu_handler as gh


@pytest.mark.asyncio
async def test_github_share_selected_links_error_emits_and_counts(monkeypatch):
    handler = gh.GitHubMenuHandler()

    handler.get_user_session = lambda uid: {"selected_repo": "owner/repo"}
    handler.get_user_token = lambda uid: "t"

    class _Repo:
        full_name = "owner/repo"
        default_branch = "main"
    class _GH:
        def __init__(self, token):
            pass
        def get_repo(self, name):
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
            raise RuntimeError("send-fail")
    class _Query:
        data = "share_selected_links"
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
            self.user_data = {"multi_selection": ["a.txt", "b.txt"]}
            self.bot_data = {}

    await handler.handle_menu_callback(_Upd(), _Ctx())

    assert any(e[0] == "github_share_selected_links_error" for e in events["evts"]) and any(e[0] == "errors_total_inc" for e in events["evts"]) 


@pytest.mark.asyncio
async def test_github_share_single_link_error_emits_and_counts(monkeypatch):
    handler = gh.GitHubMenuHandler()

    handler.get_user_session = lambda uid: {"selected_repo": "owner/repo"}
    handler.get_user_token = lambda uid: "t"

    class _Repo:
        full_name = "owner/repo"
        default_branch = "main"
    class _GH:
        def __init__(self, token):
            pass
        def get_repo(self, name):
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
            raise RuntimeError("send-fail")
    class _Query:
        data = "share_selected_links_single:path/to/file.txt"
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

    assert any(e[0] == "github_share_single_link_error" for e in events["evts"]) and any(e[0] == "errors_total_inc" for e in events["evts"]) 
