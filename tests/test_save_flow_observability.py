import types
import pytest
import asyncio
import sys


def _mk_ctx_with_jobqueue():
    class _Job:
        pass

    class _JobQueue:
        def __init__(self):
            self.called = False
        def run_once(self, *a, **k):
            self.called = True
            return _Job()

    class _Ctx:
        def __init__(self):
            self.user_data = {}
            self.job_queue = _JobQueue()

    return _Ctx()


def test_schedule_timeout_emits_anomaly_on_failure(monkeypatch):
    from handlers.save_flow import _schedule_long_collect_timeout
    import handlers.save_flow as sf

    events = []
    def fake_emit(event: str, severity: str = "info", **fields):
        events.append((event, severity, fields))

    # Make job_queue.run_once raise to exercise anomaly path
    ctx = _mk_ctx_with_jobqueue()
    def boom_run_once(*a, **k):
        raise RuntimeError("queue boom")
    ctx.job_queue.run_once = boom_run_once  # type: ignore

    monkeypatch.setattr(sf, "emit_event", fake_emit)

    class _Update:
        def __init__(self):
            self.effective_chat = types.SimpleNamespace(id=111)
            self.effective_user = types.SimpleNamespace(id=222)

    u = _Update()
    _schedule_long_collect_timeout(u, ctx)

    names = [e[0] for e in events]
    assert "long_collect_schedule_timeout_failed" in names
    _, sev, fields = events[0]
    assert sev == "anomaly" and fields.get("handled") is True
    assert fields.get("user_id") == 222


@pytest.mark.asyncio
async def test_timeout_job_emits_anomaly_on_failure(monkeypatch):
    from handlers.save_flow import long_collect_timeout_job
    import handlers.save_flow as sf

    events = []
    def fake_emit(event: str, severity: str = "info", **fields):
        events.append((event, severity, fields))

    # Create a context whose job attribute lacks expected fields => will raise inside handler send
    class _Ctx:
        def __init__(self):
            self.user_data = {}
            self.job = types.SimpleNamespace(data=None)

    monkeypatch.setattr(sf, "emit_event", fake_emit)

    ctx = _Ctx()
    await long_collect_timeout_job(ctx)

    names = [e[0] for e in events]
    assert "long_collect_timeout_job_failed" in names
    _, sev, fields = events[0]
    assert sev == "anomaly" and fields.get("handled") is True


@pytest.mark.asyncio
async def test_save_file_final_emits_anomaly_on_exception(monkeypatch):
    import handlers.save_flow as sf

    # Force database.save_code_snippet to raise
    db_mod = types.ModuleType('database')
    class _DB:
        def save_code_snippet(self, snip):
            raise RuntimeError("db boom")
        def get_latest_version(self, *a, **k):
            return None
    class _CodeSnippet:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
    db_mod.db = _DB()
    db_mod.CodeSnippet = _CodeSnippet
    monkeypatch.setitem(sys.modules, 'database', db_mod)

    # Stub detect_language
    monkeypatch.setattr(sf.code_service, 'detect_language', lambda code, fn: 'python')

    events = []
    def fake_emit(event: str, severity: str = "info", **fields):
        events.append((event, severity, fields))
    monkeypatch.setattr(sf, "emit_event", fake_emit)

    class _Msg:
        async def reply_text(self, *a, **k):
            pass

    class _Update:
        def __init__(self):
            self.message = _Msg()

    class _Ctx:
        def __init__(self):
            self.user_data = {'code_to_save': 'x', 'note_to_save': ''}

    u = _Update()
    c = _Ctx()
    await sf.save_file_final(u, c, filename='a.py', user_id=7)

    names = [e[0] for e in events]
    assert "save_file_failed" in names
    _, sev, fields = events[0]
    assert sev == "anomaly" and fields.get("handled") is True
    assert fields.get("user_id") == 7 and fields.get("file_name") == 'a.py'
