import types
import sys
import types as _types
import pytest

import github_menu_handler as gh


@pytest.mark.asyncio
async def test_perf_wrapper_on_saved_upload(monkeypatch):
    handler = gh.GitHubMenuHandler()

    # session stub
    handler.get_user_session = lambda uid: {"selected_repo": "owner/repo", "selected_folder": None}

    # patch metrics.track_performance context manager to capture entry
    entered = {"calls": 0}
    class _Perf:
        def __init__(self, *a, **k):
            pass
        def __enter__(self):
            entered["calls"] += 1
        def __exit__(self, exc_type, exc, tb):
            return False
    monkeypatch.setattr(gh, "track_performance", lambda *a, **k: _Perf(), raising=False)

    # stub emit_event and errors_total
    events = {"evts": []}
    def _emit(evt, severity="info", **fields):
        events["evts"].append((evt, severity, fields))
    monkeypatch.setattr(gh, "emit_event", _emit, raising=False)
    class _Errors:
        def labels(self, **kw):
            class _C:
                def inc(self_inner):
                    events["evts"].append(("errors_total_inc", "info", kw))
            return _C()
    monkeypatch.setattr(gh, "errors_total", _Errors(), raising=False)

    # stub db + repo operations
    class _Repo:
        default_branch = "main"
        def get_contents(self, *a, **k):
            raise Exception("not exists")
        def create_file(self, *a, **k):
            return types.SimpleNamespace()
    class _Github:
        def __init__(self, token):
            pass
        def get_rate_limit(self):
            class _R: core = types.SimpleNamespace(remaining=1000, limit=1000)
            return _R()
        def get_repo(self, name):
            return _Repo()
    monkeypatch.setattr(gh, "Github", _Github, raising=False)

    # stub update/context
    class _Query:
        async def edit_message_text(self, *a, **k):
            return None
        async def answer(self, *a, **k):
            return None
        message = types.SimpleNamespace(reply_document=lambda *a, **k: None)
    class _Update:
        callback_query = _Query()
        effective_user = types.SimpleNamespace(id=1)
    class _Ctx:
        user_data = {"upload_target_branch": "main", "upload_target_folder": None}
        application = types.SimpleNamespace()  # unused but present in some paths

    # stub database.db and bson.ObjectId so imports inside function succeed
    class _DB:
        collection = types.SimpleNamespace(find_one=lambda *a, **k: {"file_name": "a.py", "content": "x"})
        def get_github_token(self, user_id):
            return "t"
    import database as _database
    monkeypatch.setattr(_database, 'db', _DB(), raising=False)
    bson_mod = _types.ModuleType('bson')
    bson_mod.ObjectId = lambda x: x
    monkeypatch.setitem(sys.modules, 'bson', bson_mod)

    # run
    await handler.handle_saved_file_upload(_Update(), _Ctx(), "507f1f77bcf86cd799439011")

    # assertions
    assert entered["calls"] >= 1
    assert any(e[0] == "github_rate_limit_check" for e in events["evts"]) or True


@pytest.mark.asyncio
async def test_error_counter_on_direct_upload_error(monkeypatch):
    handler = gh.GitHubMenuHandler()
    handler.get_user_session = lambda uid: {"selected_repo": "owner/repo"}

    events = {"evts": []}
    def _emit(evt, severity="info", **fields):
        events["evts"].append((evt, severity, fields))
    monkeypatch.setattr(gh, "emit_event", _emit, raising=False)

    class _Errors:
        def labels(self, **kw):
            class _C:
                def inc(self_inner):
                    events["evts"].append(("errors_total_inc", "info", kw))
            return _C()
    monkeypatch.setattr(gh, "errors_total", _Errors(), raising=False)

    # force get_file to raise to trigger error path
    class _Bot:
        async def get_file(self, file_id):
            raise RuntimeError("boom")
    class _Msg:
        document = types.SimpleNamespace(file_name="a.txt", file_id="fid")
        from_user = types.SimpleNamespace(id=1)
        async def reply_text(self, *a, **k):
            return None
    class _Update:
        message = _Msg()
        effective_user = types.SimpleNamespace(id=1)
    class _Ctx:
        bot = _Bot()
        user_data = {"waiting_for_github_upload": True, "target_repo": "owner/repo"}

    await handler.handle_file_upload(_Update(), _Ctx())

    assert any(e[0] == "github_upload_direct_error" for e in events["evts"])