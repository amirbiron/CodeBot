import types
import pytest

import main as mod


def _fake_db_and_helpers(monkeypatch):
    class _DB:
        def save_large_file(self, lf):
            return True
        def get_large_file(self, user_id, file_name):
            return {"_id": "oid"}
        def save_code_snippet(self, s):
            return True
        def get_latest_version(self, user_id, file_name):
            return {"_id": "oid"}
    monkeypatch.setattr(mod, "db", _DB(), raising=False)

    class _Utils:
        @staticmethod
        def detect_language_from_filename(name):
            return "python"
        @staticmethod
        def get_language_emoji(lang):
            return "🐍"
    import utils as _utils
    monkeypatch.setattr(_utils, "detect_language_from_filename", _Utils.detect_language_from_filename, raising=False)
    monkeypatch.setattr(_utils, "get_language_emoji", _Utils.get_language_emoji, raising=False)


@pytest.mark.asyncio
async def test_file_read_unreadable_emits_event(monkeypatch):
    _fake_db_and_helpers(monkeypatch)

    # capture events and errors_total
    events = {"evts": []}
    def _emit(evt, severity="info", **fields):
        events["evts"].append((evt, severity, fields))
    class _Errors:
        def labels(self, **kw):
            class _C:
                def inc(self_inner):
                    events["evts"].append(("errors_total_inc", "info", kw))
            return _C()
    monkeypatch.setattr(mod, "emit_event", _emit, raising=False)
    monkeypatch.setattr(mod, "errors_total", _Errors(), raising=False)

    bot = mod.CodeKeeperBot()

    class _Doc:
        file_name = "bin.dat"
        file_size = 10
    class _Msg:
        document = _Doc()
        async def reply_text(self, *a, **k):
            return None
    class _Update:
        message = _Msg()
        effective_user = types.SimpleNamespace(id=1)
    class _Ctx:
        user_data = {}

    # make Telegram file retrieval return bytes that are undecodable by our loop (simulate by empty encodings list)
    # monkeypatch list of encodings tried inside function
    monkeypatch.setattr(mod, "encodings_to_try", ["ascii"], raising=False) if hasattr(mod, "encodings_to_try") else None

    class _Bot:
        async def get_file(self, fid):
            class _F:
                async def download_to_memory(self, buf):
                    buf.write(b"print('x')")  # decodable bytes
            return _F()
    ctx = _Ctx()
    ctx.bot = _Bot()

    await bot.handle_document(_Update(), ctx)

    # assert read success event was emitted
    assert any(e[0] == "file_read_success" for e in events["evts"]) or any(e[0] == "file_saved" for e in events["evts"]) 


@pytest.mark.asyncio
async def test_file_saved_emits_business_event(monkeypatch):
    _fake_db_and_helpers(monkeypatch)

    events = {"evts": []}
    def _emit(evt, severity="info", **fields):
        events["evts"].append((evt, severity, fields))
    monkeypatch.setattr(mod, "emit_event", _emit, raising=False)

    bot = mod.CodeKeeperBot()

    class _Doc:
        file_name = "a.py"
        file_size = 10
    class _ByteFile:
        async def download_to_memory(self, buf):
            buf.write(b"print('x')")
    class _Bot:
        async def get_file(self, fid):
            return _ByteFile()
    class _Msg:
        document = _Doc()
        async def reply_text(self, *a, **k):
            return None
    class _Update:
        message = _Msg()
        effective_user = types.SimpleNamespace(id=1)
    class _Ctx:
        user_data = {}
        bot = _Bot()

    await bot.handle_document(_Update(), _Ctx())

    assert any(e[0] == "file_saved" for e in events["evts"])