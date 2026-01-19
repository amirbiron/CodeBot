import types

import pytest

from handlers.documents import DocumentHandler


class DummyMsg:
    def __init__(self):
        self.texts = []

    async def reply_text(self, text, **kwargs):
        self.texts.append(text)


class DummyUpdate:
    def __init__(self):
        self.message = DummyMsg()
        self.effective_user = types.SimpleNamespace(id=123)


class DummyContext:
    def __init__(self):
        self.user_data = {}


class FacadeStub:
    def __init__(self):
        self.saved_regular = []
        self.saved_large = []
        self.latest = {"_id": "OIDX"}
        self.large = {"_id": "LIDX"}

    def save_code_snippet(self, **kwargs):
        self.saved_regular.append(kwargs)
        return True

    def save_large_file(self, **kwargs):
        self.saved_large.append(kwargs)
        return True

    def get_latest_version(self, user_id, file_name):
        return dict(self.latest)

    def get_large_file(self, user_id, file_name):
        return dict(self.large)


@pytest.mark.asyncio
async def test_store_regular_and_large_files(monkeypatch):
    facade = FacadeStub()
    monkeypatch.setitem(__import__('sys').modules, 'src.infrastructure.composition', types.SimpleNamespace(get_files_facade=lambda: facade))

    handler = DocumentHandler(
        notify_admins=lambda *a, **k: None,
        get_reporter=lambda: None,
        log_user_activity=lambda *a, **k: None,
        encodings_to_try=("utf-8",),
        emit_event=None,
        errors_total=None,
    )
    upd = DummyUpdate()
    ctx = DummyContext()

    # Regular
    await handler._store_regular_file(upd, ctx, user_id=123, file_name="a.py", language="python", content="print(1)", detected_encoding="utf-8")
    assert facade.saved_regular and "file_name" in facade.saved_regular[0]
    assert any("הקובץ נשמר בהצלחה" in t for t in upd.message.texts)

    # Large
    upd2 = DummyUpdate()
    await handler._store_large_file(upd2, ctx, user_id=123, file_name="big", language="text", content="x"*100, detected_encoding="utf-8")
    assert facade.saved_large and facade.saved_large[0]["file_name"] == "big"
    assert any("הקובץ נשמר בהצלחה" in t for t in upd2.message.texts)


@pytest.mark.asyncio
async def test_regular_file_shows_error_when_facade_fails():
    facade = FacadeStub()
    # כשל יזום ב-FilesFacade
    facade.save_code_snippet = lambda **kwargs: False
    facade.latest = {}

    handler = DocumentHandler(
        notify_admins=lambda *a, **k: None,
        get_reporter=lambda: None,
        log_user_activity=lambda *a, **k: None,
        encodings_to_try=("utf-8",),
        emit_event=None,
        errors_total=None,
    )
    # נטרל גישה אמיתית ל-FilesFacade/DB והשתמש בסטאבים
    handler._files_facade = facade
    handler._files_facade_initialized = True

    upd = DummyUpdate()
    ctx = DummyContext()

    await handler._store_regular_file(
        upd,
        ctx,
        user_id=77,
        file_name="fallback.py",
        language="python",
        content="print('fallback')",
        detected_encoding="utf-8",
    )

    assert not facade.saved_regular
    assert any("שגיאה" in text for text in upd.message.texts)


@pytest.mark.asyncio
async def test_large_file_shows_error_when_facade_fails():
    facade = FacadeStub()
    facade.save_large_file = lambda **kwargs: False
    facade.large = {}

    handler = DocumentHandler(
        notify_admins=lambda *a, **k: None,
        get_reporter=lambda: None,
        log_user_activity=lambda *a, **k: None,
        encodings_to_try=("utf-8",),
        emit_event=None,
        errors_total=None,
    )
    handler._files_facade = facade
    handler._files_facade_initialized = True

    upd = DummyUpdate()
    ctx = DummyContext()

    await handler._store_large_file(
        upd,
        ctx,
        user_id=55,
        file_name="huge.py",
        language="python",
        content="x" * 5000,
        detected_encoding="utf-8",
    )

    assert not facade.saved_large
    assert any("שגיאה" in text for text in upd.message.texts)
