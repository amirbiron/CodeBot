import asyncio
import types
import pytest


@pytest.mark.asyncio
async def test_db_disconnect_during_batch_sets_failed(monkeypatch):
    # Prepare batch processor fresh
    import sys, importlib
    sys.modules.pop('batch_processor', None)
    bp = importlib.import_module('batch_processor')

    # db first works, then raises
    calls = {"n": 0}
    db_mod = __import__('database', fromlist=['db'])
    class _DB:
        def get_latest_version(self, uid, name):
            calls["n"] += 1
            if calls["n"] > 1:
                raise RuntimeError("db connection lost")
            return {"code": "print(1)", "programming_language": "python"}
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)

    svc = __import__('services.code_service', fromlist=['code_service'])
    monkeypatch.setattr(svc, 'analyze_code', lambda c, l: {"ok": True}, raising=True)

    job_id = await bp.batch_processor.analyze_files_batch(1, ["a.py", "b.py"]) 
    # wait for finish
    for _ in range(300):
        job = bp.batch_processor.get_job_status(job_id)
        if job and job.status in {"completed", "failed"}:
            break
        await asyncio.sleep(0.01)
    job = bp.batch_processor.get_job_status(job_id)
    # Expect completed with one failure captured per-file, not a crash
    assert job is not None and job.status in {"completed", "failed"}
    # Ensure per-file error captured, or whole job failed early
    assert (job.status == "failed") or any((not r.get('success')) for r in job.results.values())


@pytest.mark.asyncio
async def test_telegram_retry_after_and_message_not_modified(monkeypatch):
    # Use a small slice of handler that edits messages via safe edit path
    import sys
    sys.modules.pop('github_menu_handler', None)
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()

    # Build stubs for query/message
    class _Msg:
        def __init__(self):
            self.texts = []
        async def edit_text(self, text, **kwargs):
            self.texts.append(text)
            return self
    class _Query:
        def __init__(self):
            self.message = _Msg()
            self.data = "github_import_repo"
            self.from_user = types.SimpleNamespace(id=1)
        async def edit_message_text(self, text, **kwargs):
            self.message.texts.append(text)
            return self.message
        async def answer(self, *args, **kwargs):
            return None
    class _Update:
        def __init__(self):
            self.callback_query = _Query()
            self.effective_user = types.SimpleNamespace(id=1)
    class _Context:
        def __init__(self):
            self.user_data = {}
            self.bot_data = {}

    # Simulate RetryAfter in Telegram API edit
    import telegram.error as terr
    async def _raise_retry_after(q, text, reply_markup=None, parse_mode=None):
        raise terr.RetryAfter(retry_after=0)

    monkeypatch.setattr(gh.TelegramUtils, "safe_edit_message_text", _raise_retry_after)

    # Stub Github token getter to avoid network
    monkeypatch.setattr(handler, "get_user_token", lambda _uid: "token")
    class _Gh:
        def __init__(self, *a, **k):
            pass
        def get_repo(self, full):
            class _Repo:
                def get_branches(self):
                    return []
            return _Repo()
    monkeypatch.setattr(gh, "Github", _Gh)

    upd, ctx = _Update(), _Context()
    # Should not crash even if safe_edit raises RetryAfter; handler should continue and finish quickly
    await asyncio.wait_for(handler.handle_menu_callback(upd, ctx), timeout=2.0)
    assert True
