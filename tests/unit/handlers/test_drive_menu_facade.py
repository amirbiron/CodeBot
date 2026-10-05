import types
import pytest

from handlers.drive.menu import GoogleDriveMenuHandler


class DummyMsg:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, **kwargs):
        self.sent.append(text)


class DummyUpdateMsg:
    def __init__(self):
        self.message = DummyMsg()
        self.callback_query = None
        self.effective_user = types.SimpleNamespace(id=111)


class DummyQuery:
    def __init__(self, data):
        self.data = data
        self.edits = []
        self.answered = False
        self.message = types.SimpleNamespace(chat_id=111, message_id=1)
        # Handlers expect Telegram's CallbackQuery.from_user
        self.from_user = types.SimpleNamespace(id=111)

    async def answer(self, *a, **k):
        self.answered = True

    async def edit_message_text(self, text, **kwargs):
        self.edits.append(text)


class DummyUpdateCb:
    def __init__(self, data):
        self.callback_query = DummyQuery(data)
        self.effective_user = types.SimpleNamespace(id=111)


class DummyContext:
    def __init__(self):
        self.user_data = {}
        self.bot_data = {}
        self.application = types.SimpleNamespace(job_queue=types.SimpleNamespace(scheduler=None))


class FacadeStub:
    """``owner`` חובה כמו ב-FilesFacade האמיתי, ונרשם: תפריט הבוט חייב לעבוד רק על החיבור של הבוט.

    התפריט עוטף את רוב הקריאות ב-try/except, ולכן קריאה בלי owner הייתה נבלעת ונראית כמו "אין חיבור" —
    הטסטים בודקים את ``owners`` כדי שתוצאה כזו לא תעבור כהצלחה.
    """

    def __init__(self, tokens=None, prefs=None):
        self.tokens = dict(tokens or {})
        self.prefs = dict(prefs or {})
        self.saved = []
        self.deleted_tokens = False
        self.owners = []

    def get_drive_tokens(self, user_id, *, owner):
        self.owners.append(owner)
        return dict(self.tokens)

    def get_drive_prefs(self, user_id, *, owner):
        self.owners.append(owner)
        return dict(self.prefs)

    def save_drive_prefs(self, user_id, update_prefs, *, owner):
        self.owners.append(owner)
        self.prefs.update(dict(update_prefs or {}))
        self.saved.append(dict(update_prefs or {}))
        return True

    def delete_drive_tokens(self, user_id, *, owner):
        self.owners.append(owner)
        self.deleted_tokens = True
        self.tokens = {}
        return True

    # Files for advanced checks
    def get_user_large_files(self, user_id, page=1, per_page=1):
        return ([], 0)

    def get_user_files(self, user_id, limit=1, skip=0):
        return []


@pytest.mark.asyncio
async def test_drive_menu_not_connected(monkeypatch):
    # Enable feature flag
    monkeypatch.setattr('handlers.drive.menu.config', types.SimpleNamespace(DRIVE_MENU_V2=True), raising=False)
    # Facade returns no tokens
    f = FacadeStub(tokens={})
    monkeypatch.setitem(__import__('sys').modules, 'src.infrastructure.composition', types.SimpleNamespace(get_files_facade=lambda: f))
    handler = GoogleDriveMenuHandler()
    upd = DummyUpdateMsg()
    ctx = DummyContext()
    await handler.menu(upd, ctx)
    assert any("לא מחובר" in t for t in upd.message.sent)
    # "לא מחובר" נקבע מקריאה אמיתית לחיבור של הבוט — לא מקריאה שנכשלה ונבלעה
    assert f.owners == ["bot"]


@pytest.mark.asyncio
async def test_drive_select_zip_saves_pref(monkeypatch):
    monkeypatch.setattr('handlers.drive.menu.config', types.SimpleNamespace(DRIVE_MENU_V2=True), raising=False)
    f = FacadeStub(tokens={"access_token": "x"})
    monkeypatch.setitem(__import__('sys').modules, 'src.infrastructure.composition', types.SimpleNamespace(get_files_facade=lambda: f))
    # No saved zips so it shows info but still saves pref
    monkeypatch.setattr('handlers.drive.menu.backup_manager', types.SimpleNamespace(list_backups=lambda user_id: []), raising=False)
    handler = GoogleDriveMenuHandler()
    upd = DummyUpdateCb("drive_sel_zip")
    ctx = DummyContext()
    await handler.handle_callback(upd, ctx)
    assert any(d.get("last_selected_category") == "zip" for d in f.saved)
    assert f.owners and set(f.owners) == {"bot"}


@pytest.mark.asyncio
async def test_drive_select_all_saves_pref(monkeypatch):
    monkeypatch.setattr('handlers.drive.menu.config', types.SimpleNamespace(DRIVE_MENU_V2=True), raising=False)
    f = FacadeStub(tokens={"access_token": "x"})
    monkeypatch.setitem(__import__('sys').modules, 'src.infrastructure.composition', types.SimpleNamespace(get_files_facade=lambda: f))
    handler = GoogleDriveMenuHandler()
    upd = DummyUpdateCb("drive_sel_all")
    ctx = DummyContext()
    await handler.handle_callback(upd, ctx)
    assert any(d.get("last_selected_category") == "all" for d in f.saved)
    assert f.owners and set(f.owners) == {"bot"}


@pytest.mark.asyncio
async def test_drive_logout_do(monkeypatch):
    monkeypatch.setattr('handlers.drive.menu.config', types.SimpleNamespace(DRIVE_MENU_V2=True), raising=False)
    f = FacadeStub(tokens={"access_token": "x"})
    monkeypatch.setitem(__import__('sys').modules, 'src.infrastructure.composition', types.SimpleNamespace(get_files_facade=lambda: f))
    handler = GoogleDriveMenuHandler()
    upd = DummyUpdateCb("drive_logout_do")
    ctx = DummyContext()
    await handler.handle_callback(upd, ctx)
    assert f.deleted_tokens is True
    assert any("נותקת" in t for t in upd.callback_query.edits)
    # ניתוק מהבוט מוחק רק את החיבור של הבוט
    assert f.owners == ["bot"]

