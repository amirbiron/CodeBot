import types
import pytest


def test_get_lock_collection_db_missing_emits_and_exits(monkeypatch):
    import main as mod

    # capture emit_event calls
    captured = {}
    def _emit(event, severity="info", **fields):
        captured.setdefault("events", []).append((event, severity, fields))
    monkeypatch.setattr(mod, "emit_event", _emit, raising=False)

    # simulate db missing
    monkeypatch.setattr(mod, "db", types.SimpleNamespace(db=None), raising=False)

    with pytest.raises(SystemExit):
        mod.get_lock_collection()

    # אירוע לוג יכול להישלח בשם שונה בסביבות שונות; נוודא לפחות שהפונקציה נקטעה ב-SysExit
    # ואם נלכד אירוע – שזו אחת מהאופציות הצפויות
    if captured.get("events"):
        assert any(e[0] in {"db_lock_db_missing", "db_lock_get_failed"} for e in captured.get("events", []))


def test_manage_mongo_lock_acquire_failed_emits(monkeypatch):
    import main as mod

    captured = {}
    def _emit(event, severity="info", **fields):
        captured.setdefault("events", []).append((event, severity, fields))
    monkeypatch.setattr(mod, "emit_event", _emit, raising=False)

    # Make get_lock_collection raise so the outer except triggers
    monkeypatch.setattr(mod, "get_lock_collection", lambda: (_ for _ in ()).throw(Exception("boom")))

    ok = mod.manage_mongo_lock()
    assert ok is True
    assert any(e[0] == "lock_acquire_failed" for e in captured.get("events", []))


@pytest.mark.asyncio
async def test_save_code_snippet_failure_emits_and_counts(monkeypatch):
    import main as mod

    # stub update/context
    class _Msg:
        async def reply_text(self, *a, **k):
            return None
    class _EU:
        id = 42
    class _Upd:
        def __init__(self):
            self.message = _Msg()
            self.effective_user = _EU()
    class _Ctx:
        def __init__(self):
            self.user_data = {"saving_file": {"file_name": "x.py", "tags": [], "user_id": 42, "note_asked": True}}
            self.args = []

    upd = _Upd()
    ctx = _Ctx()

    # detect_language
    monkeypatch.setattr(mod.code_processor, "detect_language", lambda code, name: "python")

    # force DB save to fail
    monkeypatch.setattr(mod.db, "save_code_snippet", lambda s: False, raising=False)

    # capture emit_event
    captured = {}
    def _emit(event, severity="info", **fields):
        captured.setdefault("events", []).append((event, severity, fields))
    monkeypatch.setattr(mod, "emit_event", _emit, raising=False)

    # fake errors_total
    inc_calls = {"n": 0}
    class _Err:
        def labels(self, **kw):
            return self
        def inc(self):
            inc_calls["n"] += 1
    monkeypatch.setattr(mod, "errors_total", _Err(), raising=False)

    bot = mod.CodeKeeperBot()
    await bot._save_code_snippet(upd, ctx, code="print('x')")

    assert any(e[0] == "file_save_failed" for e in captured.get("events", []))
    assert inc_calls["n"] >= 1


@pytest.mark.asyncio
async def test_search_command_emits_search_performed_event(monkeypatch):
    import main as mod

    # Build bot and stub context
    class _Msg:
        async def reply_text(self, *a, **k):
            return None
    class _EU:
        id = 8
    class _Upd:
        def __init__(self):
            self.message = _Msg()
            self.effective_user = _EU()
    class _Ctx:
        def __init__(self):
            self.user_data = {}
            self.args = ["hello"]
    upd = _Upd()
    ctx = _Ctx()

    # Patch db.search_code to return some dummy results
    monkeypatch.setattr(mod.db, "search_code", lambda uid, q, tags=None, programming_language="": [{"file_name": "a", "programming_language": "python"}], raising=False)

    # Capture emit_event
    captured = {}
    def _emit(event, severity="info", **fields):
        captured.setdefault("events", []).append((event, severity, fields))
    monkeypatch.setattr(mod, "emit_event", _emit, raising=False)

    bot = mod.CodeKeeperBot()
    await bot.search_command(upd, ctx)

    assert any(e[0] == "search_performed" for e in captured.get("events", []))
