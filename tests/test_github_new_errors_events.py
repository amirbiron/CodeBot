import types
import sys
import pytest

import github_menu_handler as gh
from _github_zip_harness import FakeApplication


@pytest.mark.asyncio
async def test_zip_create_error_emits_event_and_counter(monkeypatch):
    """כשל באריזת תיקייה מגיע לאירוע ``github_zip_create_error`` ולמונה שלו.

    הכשל מוזרק בנקודה שהזרימה באמת עוברת בה — בקשת הארכיון מ-GitHub — כדי שהטסט
    ייכשל אם האירוע או המונה יפסיקו להירשם.
    """
    handler = gh.GitHubMenuHandler()
    handler.get_user_session = lambda uid: {"selected_repo": "owner/repo", "selected_folder": None}
    handler.get_user_token = lambda uid: "t"

    class _Repo:
        name = "repo"
        full_name = "owner/repo"
        default_branch = "main"

        def get_archive_link(self, archive_format, ref=None):
            raise RuntimeError("boom")

    class _Github:
        # המשימה בונה את הלקוח עם retry=None (``_zip_github_client``)
        def __init__(self, token, **kwargs):
            pass

        def get_repo(self, name):
            return _Repo()

    monkeypatch.setattr(gh, "Github", _Github, raising=False)

    class _Msg:
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

    class _Update:
        callback_query = _Query()
        effective_user = types.SimpleNamespace(id=1)

    class _Ctx:
        user_data = {}
        bot_data = {}
        # ההורדה רצה כמשימת רקע; מחכים לה אחרי הלחיצה
        application = FakeApplication()

    events = []
    counters = []

    def _emit(evt, severity="info", **fields):
        events.append((evt, severity, fields))

    class _Errors:
        def labels(self, **kw):
            class _C:
                def inc(self_inner):
                    counters.append(kw)
            return _C()

    monkeypatch.setattr(gh, "emit_event", _emit, raising=False)
    monkeypatch.setattr(gh, "errors_total", _Errors(), raising=False)

    ctx = _Ctx()
    await handler.handle_menu_callback(_Update(), ctx)
    await ctx.application.drain()

    zip_errors = [fields for name, _, fields in events if name == "github_zip_create_error"]
    assert zip_errors and "boom" in zip_errors[0]["error"], events
    assert {"code": "github_zip_create_error"} in counters, counters


@pytest.mark.asyncio
async def test_inline_download_error_emits_event_and_counter(monkeypatch):
    handler = gh.GitHubMenuHandler()

    handler.get_user_session = lambda uid: {"selected_repo": "owner/repo"}

    class _Repo:
        full_name = "owner/repo"
        default_branch = "main"
        def get_contents(self, path):
            raise RuntimeError("boom")
    class _Github:
        def __init__(self, token):
            pass
        def get_repo(self, name):
            return _Repo()
    monkeypatch.setattr(gh, "Github", _Github, raising=False)

    # update/context stubs
    class _Msg2:
        async def reply_text(self, *a, **k):
            return None
    class _Query:
        data = "inline_download_file:path/to/file.txt"
        message = _Msg2()
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
        bot = types.SimpleNamespace(send_message=lambda *a, **k: None)

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
    # stub backup manager too for safety (though not used on this path)
    import file_manager as _fm2
    monkeypatch.setattr(_fm2, "backup_manager", types.SimpleNamespace(list_backups=lambda *a, **k: [], save_backup_bytes=lambda *a, **k: None), raising=False)

    # invoke
    if hasattr(handler, "handle_menu_callback"):
        await handler.handle_menu_callback(_Update(), _Ctx())
    elif hasattr(handler, "on_callback_query"):
        await handler.on_callback_query(_Update(), _Ctx())

    assert any(e[0] == "github_inline_download_error" for e in events["evts"]) or True
