import types
import pytest

import main as mod


@pytest.mark.asyncio
async def test_file_read_unreadable_emits_and_counts(monkeypatch):
    # stub DB and utils
    class _DB:
        def save_large_file(self, lf): return True
        def get_large_file(self, user_id, file_name): return {"_id": "oid"}
        def save_code_snippet(self, s): return True
        def get_latest_version(self, user_id, file_name): return {"_id": "oid"}
    monkeypatch.setattr(mod, "db", _DB(), raising=False)

    # capture events and counters
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

    # stub Telegram file retrieval to return bytes that are undecodable by our loop
    class _Doc:
        file_name = "bin.dat"
        file_size = 10
        file_id = "fid-x"
    class _Msg:
        document = _Doc()
        async def reply_text(self, *a, **k):
            return None
    class _Update:
        message = _Msg()
        effective_user = types.SimpleNamespace(id=1)
    class _Ctx:
        user_data = {}
    class _Bot:
        async def get_file(self, fid):
            class _F:
                async def download_to_memory(self, buf):
                    # Write bytes that are invalid for all encodings we'll force below
                    buf.write(b"\x80\x81\x8D\x8F\x90\x9D")
            return _F()
    ctx = _Ctx()
    ctx.bot = _Bot()

    # Force encoding list to a single encoding that will fail for given bytes
    # Force the function to try only encodings that will fail for bytes above
    mod.encodings_to_try = ["utf-8", "utf-16"]

    await bot.handle_document(_Update(), ctx)

    assert any(e[0] == "file_read_unreadable" for e in events["evts"]) and any(e[0] == "errors_total_inc" and e[2].get("code") == "E_FILE_UNREADABLE" for e in events["evts"]) 