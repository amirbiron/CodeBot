import asyncio
import os
import types
import io
import json
from datetime import datetime, timezone

import pytest


def _make_backup_info(**over):
    base = {
        "backup_id": "backup_7_abc",
        "user_id": 7,
        "created_at": datetime.now(timezone.utc),
        "file_count": 3,
        "total_size": 1234,
        "backup_type": "manual",
        "status": "completed",
        "file_path": "/nonexistent",
        "repo": None,
        "path": None,
        "metadata": {"backup_id": "backup_7_abc", "user_id": 7},
    }
    base.update(over)
    return types.SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_build_download_button_text_variants():
    import backup_menu_handler as bmh

    info_repo = _make_backup_info(backup_type="github_repo_zip", repo="owner/really-long-repository-name-for-testing", backup_id="backup_7_a")
    txt = bmh._build_download_button_text(info_repo, force_hide_size=False, vnum=5, rating="🏆 מצוין")
    assert isinstance(txt, str) and txt.startswith("BKP zip") and len(txt) <= 64
    assert "v5" in txt

    info_zip = _make_backup_info(backup_type="manual", repo=None, backup_id="backup_7_b")
    txt2 = bmh._build_download_button_text(info_zip, force_hide_size=True, vnum=None, rating="👍 טוב")
    assert isinstance(txt2, str) and txt2.startswith("BKP zip") and len(txt2) <= 64


@pytest.mark.asyncio
async def test_show_backups_list_empty_back_targets(monkeypatch):
    import backup_menu_handler as bmh

    handler = bmh.BackupMenuHandler()

    class _Q:
        def __init__(self):
            self.from_user = types.SimpleNamespace(id=99)
            self.edited = []
        async def answer(self, *a, **k):
            return None
        async def edit_message_text(self, text, reply_markup=None):
            self.edited.append((text, reply_markup))

    class _Upd:
        def __init__(self):
            self.callback_query = _Q()
            self.effective_user = types.SimpleNamespace(id=99)

    class _Ctx:
        def __init__(self, back_to=None):
            self.user_data = {}
            if back_to is not None:
                self.user_data["zip_back_to"] = back_to

    # no backups
    monkeypatch.setattr(bmh, "backup_manager", types.SimpleNamespace(list_backups=lambda uid: []))

    # Case: back to files
    upd = _Upd()
    ctx = _Ctx("files")
    await handler._show_backups_list(upd, ctx)
    text, markup = upd.callback_query.edited[-1]
    assert "לא נמצאו" in text
    assert markup.inline_keyboard[-1][0].callback_data == "files"

    # Case: back to github_upload
    upd = _Upd()
    ctx = _Ctx("github_upload")
    await handler._show_backups_list(upd, ctx)
    text, markup = upd.callback_query.edited[-1]
    assert markup.inline_keyboard[-1][0].callback_data == "upload_file"

    # Case: back to github
    upd = _Upd()
    ctx = _Ctx("github")
    await handler._show_backups_list(upd, ctx)
    text, markup = upd.callback_query.edited[-1]
    assert markup.inline_keyboard[-1][0].callback_data == "github_backup_menu"

    # Default: back to backup menu
    upd = _Upd()
    ctx = _Ctx(None)
    await handler._show_backups_list(upd, ctx)
    text, markup = upd.callback_query.edited[-1]
    assert markup.inline_keyboard[-1][0].callback_data == "backup_menu"


@pytest.mark.asyncio
async def test_show_backups_list_repo_filter_empty(monkeypatch):
    import backup_menu_handler as bmh

    handler = bmh.BackupMenuHandler()

    # Return backups that do NOT match the requested repo
    infos = [
        _make_backup_info(backup_id="b_other", repo="owner/other"),
        _make_backup_info(backup_id="b_other2", repo="owner/another"),
    ]
    monkeypatch.setattr(bmh, "backup_manager", types.SimpleNamespace(list_backups=lambda uid: infos))

    class _Q:
        def __init__(self):
            self.from_user = types.SimpleNamespace(id=77)
            self.edited = []
        async def answer(self, *a, **k):
            return None
        async def edit_message_text(self, text, reply_markup=None):
            self.edited.append((text, reply_markup))

    class _Upd:
        def __init__(self):
            self.callback_query = _Q()
            self.effective_user = types.SimpleNamespace(id=77)

    class _Ctx:
        def __init__(self):
            self.user_data = {"github_backup_context_repo": "owner/target"}

    upd, ctx = _Upd(), _Ctx()
    await handler._show_backups_list(upd, ctx)
    text, markup = upd.callback_query.edited[-1]
    # Expect repo-specific empty state, not a list of all backups
    assert "לא נמצאו גיבויים עבור הריפו" in text
    assert "owner/target" in text
    # Back button should lead to GitHub backup menu in repo context
    assert markup.inline_keyboard[-1][0].callback_data == "github_backup_menu"

@pytest.mark.asyncio
async def test_delete_mode_toggle_selection_and_execute(monkeypatch):
    import backup_menu_handler as bmh

    handler = bmh.BackupMenuHandler()

    # Fake db ratings/note ops
    class _DB:
        def get_backup_rating(self, user_id, bid):
            return ""
        def delete_backup_ratings(self, user_id, bids):
            return 0
    # patch both global alias and dynamic import inside handler
    import database as _database
    monkeypatch.setattr(_database, "db", _DB(), raising=False)
    monkeypatch.setattr(bmh, "db", _DB(), raising=False)

    infos = [
        _make_backup_info(backup_id="b1"),
        _make_backup_info(backup_id="b2"),
    ]

    class _Mgr:
        def __init__(self):
            self.deleted_calls = []
        def list_backups(self, user_id):
            return infos
        def delete_backups(self, user_id, bids):
            self.deleted_calls.append((user_id, list(bids)))
            return {"deleted": len(list(bids)), "errors": []}

    mgr = _Mgr()
    monkeypatch.setattr(bmh, "backup_manager", mgr)

    class _Q:
        def __init__(self):
            self.data = ""
            self.from_user = types.SimpleNamespace(id=5)
            self.answers = []
            self.edits = []
        async def answer(self, *a, **k):
            self.answers.append((a, k))
        async def edit_message_text(self, text, reply_markup=None):
            self.edits.append((text, reply_markup))

    class _Upd:
        def __init__(self):
            self.callback_query = _Q()
            self.effective_user = types.SimpleNamespace(id=5)

    class _Ctx:
        def __init__(self):
            self.user_data = {}

    upd = _Upd()
    ctx = _Ctx()

    # Turn delete mode on
    upd.callback_query.data = "backup_delete_mode_on"
    await handler.handle_callback_query(upd, ctx)
    assert ctx.user_data.get("backup_delete_mode") is True

    # Toggle selection
    upd.callback_query.data = "backup_toggle_del:b1"
    await handler.handle_callback_query(upd, ctx)
    assert "b1" in ctx.user_data.get("backup_delete_selected", set())

    # Confirm screen
    upd.callback_query.data = "backup_delete_confirm"
    await handler.handle_callback_query(upd, ctx)
    last_text, last_markup = upd.callback_query.edits[-1]
    assert "אישור מחיקה" in last_text

    # Execute
    upd.callback_query.data = "backup_delete_execute"
    await handler.handle_callback_query(upd, ctx)
    assert mgr.deleted_calls and mgr.deleted_calls[-1] == (5, ["b1"])
    # Mode cleared
    assert not ctx.user_data.get("backup_delete_mode")


@pytest.mark.asyncio
async def test_delete_one_execute_error_path(monkeypatch):
    import backup_menu_handler as bmh

    handler = bmh.BackupMenuHandler()

    # Manager that raises on delete
    infos = [_make_backup_info(backup_id="x1")]
    class _Mgr:
        def list_backups(self, user_id):
            return infos
        def delete_backups(self, user_id, bids):
            raise RuntimeError("boom")
    monkeypatch.setattr(bmh, "backup_manager", _Mgr())

    class _Q:
        def __init__(self):
            self.data = "backup_delete_one_execute:x1"
            self.from_user = types.SimpleNamespace(id=4)
            self.last_text = None
        async def answer(self, *a, **k):
            return None
        async def edit_message_text(self, text, **kwargs):
            self.last_text = text

    upd = types.SimpleNamespace(callback_query=_Q(), effective_user=types.SimpleNamespace(id=4))
    ctx = types.SimpleNamespace(user_data={})

    await handler.handle_callback_query(upd, ctx)
    assert "שגיאה במחיקה" in upd.callback_query.last_text


@pytest.mark.asyncio
async def test_rate_flow_success_and_error(monkeypatch):
    import backup_menu_handler as bmh

    handler = bmh.BackupMenuHandler()

    called = {"saved": [], "shown": []}
    class _DB:
        def save_backup_rating(self, user_id, b_id, rating):
            called["saved"].append((user_id, b_id, rating))
            return True
    import database as _database
    monkeypatch.setattr(_database, "db", _DB(), raising=False)
    monkeypatch.setattr(bmh, "db", _database.db, raising=False)

    async def _show_details(upd, ctx, bid):
        called["shown"].append(bid)
    monkeypatch.setattr(handler, "_show_backup_details", _show_details)

    class _Q:
        def __init__(self):
            self.data = "backup_rate:bk1:excellent"
            self.from_user = types.SimpleNamespace(id=12)
            self.answered = []
        async def answer(self, text, show_alert=False):
            self.answered.append((text, show_alert))

    upd = types.SimpleNamespace(callback_query=_Q(), effective_user=types.SimpleNamespace(id=12))
    ctx = types.SimpleNamespace(user_data={})

    await handler.handle_callback_query(upd, ctx)
    assert called["saved"] and called["shown"] == ["bk1"]

    # Error branch: bad payload and db error
    upd.callback_query.data = "backup_rate:oops"
    await handler.handle_callback_query(upd, ctx)
    assert upd.callback_query.answered and upd.callback_query.answered[-1][1] is True

    class _DB2:
        def save_backup_rating(self, *a, **k):
            raise RuntimeError("db error")
    monkeypatch.setattr(_database, "db", _DB2(), raising=False)
    monkeypatch.setattr(bmh, "db", _database.db, raising=False)

    upd.callback_query.data = "backup_rate:bk2:ok"
    upd.callback_query.answered.clear()
    await handler.handle_callback_query(upd, ctx)
    assert upd.callback_query.answered and upd.callback_query.answered[-1][1] is True


@pytest.mark.asyncio
async def test_create_full_backup_flow(monkeypatch):
    import backup_menu_handler as bmh

    handler = bmh.BackupMenuHandler()

    class _DB:
        def get_user_files(self, user_id, limit=10000):
            return [
                {"_id": 1, "file_name": "a.py", "code": "print(1)"},
                {"_id": 2, "file_name": "b.js", "code": "var x;"},
            ]
    import database as _database
    monkeypatch.setattr(_database, "db", _DB(), raising=False)
    monkeypatch.setattr(bmh, "db", _database.db, raising=False)

    class _Mgr:
        def save_backup_bytes(self, data, metadata):
            # validate it's a zip containing metadata.json
            import zipfile
            bio = io.BytesIO(data)
            with zipfile.ZipFile(bio, 'r') as zf:
                assert 'metadata.json' in zf.namelist()
                md = json.loads(zf.read('metadata.json'))
                assert md.get('backup_id') and md.get('user_id')
            return True
    monkeypatch.setattr(bmh, "backup_manager", _Mgr())

    class _Q:
        def __init__(self):
            self.from_user = types.SimpleNamespace(id=21)
            self.message = types.SimpleNamespace()
            self.last_edit = None
            self.sent_docs = []
            async def _reply_document(document=None, caption=None, **kwargs):
                self.sent_docs.append((document, caption, kwargs))
            self.message.reply_document = _reply_document
        async def answer(self, *a, **k):
            return None
        async def edit_message_text(self, text, **kwargs):
            self.last_edit = text

    upd = types.SimpleNamespace(callback_query=_Q(), effective_user=types.SimpleNamespace(id=21), message=None)
    ctx = types.SimpleNamespace(user_data={})

    await handler._create_full_backup(upd, ctx)
    assert upd.callback_query.sent_docs, "expected a document to be sent"
    doc, caption, _ = upd.callback_query.sent_docs[-1]
    # doc is telegram.InputFile stub
    assert hasattr(doc, 'filename') and str(caption).startswith("✅ גיבוי נוצר בהצלחה")


@pytest.mark.asyncio
async def test_download_by_id_success_and_refresh_handling(tmp_path, monkeypatch):
    import backup_menu_handler as bmh

    handler = bmh.BackupMenuHandler()

    # Create a temp file to represent the backup zip
    p = tmp_path / "backup_5_x.zip"
    p.write_bytes(b"zip bytes here")

    infos = [_make_backup_info(backup_id="backup_5_x", file_path=str(p), total_size=p.stat().st_size)]

    class _Mgr:
        def list_backups(self, user_id):
            return infos
    monkeypatch.setattr(bmh, "backup_manager", _Mgr())

    # Raise 'message is not modified' on refresh
    async def _show_list(*a, **k):
        raise Exception("Message is not modified")
    monkeypatch.setattr(handler, "_show_backups_list", _show_list)

    class _Q:
        def __init__(self):
            self.data = "backup_download_id:backup_5_x"
            self.from_user = types.SimpleNamespace(id=5)
            self.message = types.SimpleNamespace()
            self.sent = []
            async def _reply_document(document=None, caption=None, **kwargs):
                self.sent.append((document, caption))
            self.message.reply_document = _reply_document
        async def answer(self, *a, **k):
            return None
        async def edit_message_text(self, text, **kwargs):
            # called on error path, not here
            return None

    upd = types.SimpleNamespace(callback_query=_Q(), effective_user=types.SimpleNamespace(id=5))
    ctx = types.SimpleNamespace(user_data={})

    await handler.handle_callback_query(upd, ctx)
    assert upd.callback_query.sent and upd.callback_query.sent[-1][0] is not None


@pytest.mark.asyncio
async def test_download_and_restore_not_found(monkeypatch):
    import backup_menu_handler as bmh

    handler = bmh.BackupMenuHandler()

    infos = [_make_backup_info(backup_id="b0", file_path="/nope/path.zip")]

    class _Mgr:
        def list_backups(self, user_id):
            return infos
        def restore_from_backup(self, *a, **k):
            return {"restored_files": 0, "errors": []}
    monkeypatch.setattr(bmh, "backup_manager", _Mgr())

    class _Q:
        def __init__(self):
            self.data = "backup_download_id:b0"
            self.from_user = types.SimpleNamespace(id=8)
            self.last_text = None
        async def answer(self, *a, **k):
            return None
        async def edit_message_text(self, text, **kwargs):
            self.last_text = text

    upd = types.SimpleNamespace(callback_query=_Q(), effective_user=types.SimpleNamespace(id=8))
    ctx = types.SimpleNamespace(user_data={})

    # download path -> not found
    await handler.handle_callback_query(upd, ctx)
    assert "לא נמצא" in upd.callback_query.last_text

    # restore path -> not found
    upd.callback_query.data = "backup_restore_id:b0"
    upd.callback_query.last_text = None
    await handler.handle_callback_query(upd, ctx)
    assert "לא נמצא" in upd.callback_query.last_text


@pytest.mark.asyncio
async def test_show_backup_details_and_note_prompt(monkeypatch):
    import backup_menu_handler as bmh

    handler = bmh.BackupMenuHandler()

    info = _make_backup_info(backup_id="bkD", file_count=2, total_size=10)

    class _Mgr:
        def list_backups(self, user_id):
            return [info]
    monkeypatch.setattr(bmh, "backup_manager", _Mgr())

    class _DB:
        def get_backup_rating(self, user_id, bid):
            return "🏆 מצוין"
        def get_backup_note(self, user_id, bid):
            return "note!"
    import database as _database
    monkeypatch.setattr(_database, "db", _DB(), raising=False)
    monkeypatch.setattr(bmh, "db", _database.db, raising=False)

    class _Q:
        def __init__(self):
            self.data = "backup_details:bkD"
            self.from_user = types.SimpleNamespace(id=17)
            self.edits = []
        async def answer(self, *a, **k):
            return None
        async def edit_message_text(self, text, reply_markup=None):
            self.edits.append((text, reply_markup))

    upd = types.SimpleNamespace(callback_query=_Q(), effective_user=types.SimpleNamespace(id=17))
    ctx = types.SimpleNamespace(user_data={})

    await handler.handle_callback_query(upd, ctx)
    text, markup = upd.callback_query.edits[-1]
    assert "🏷" in text and "📝" in text

    # Ask for note
    upd.callback_query.data = "backup_add_note:bkD"
    upd.callback_query.edits.clear()
    await handler.handle_callback_query(upd, ctx)
    text, _ = upd.callback_query.edits[-1]
    assert "הקלד/י הערה" in text


@pytest.mark.asyncio
async def test_show_backup_menu_and_rating_prompt(monkeypatch):
    import backup_menu_handler as bmh

    handler = bmh.BackupMenuHandler()

    # show_backup_menu via callback_query
    class _Q:
        def __init__(self):
            self.from_user = types.SimpleNamespace(id=34)
            self.last_text = None
        async def answer(self, *a, **k):
            return None
        async def edit_message_text(self, text, reply_markup=None):
            self.last_text = text

    upd = types.SimpleNamespace(callback_query=_Q(), message=None, effective_user=types.SimpleNamespace(id=34))
    ctx = types.SimpleNamespace(user_data={})

    await handler.show_backup_menu(upd, ctx)
    assert "בחר פעולה" in upd.callback_query.last_text

    # send_rating_prompt
    sent = {}
    class _Bot:
        async def send_message(self, chat_id, text, reply_markup=None):
            sent["ok"] = (chat_id, text, reply_markup)
    upd2 = types.SimpleNamespace(effective_chat=types.SimpleNamespace(id=55))
    ctx2 = types.SimpleNamespace(bot=_Bot())

    await handler.send_rating_prompt(upd2, ctx2, "b1")
    assert sent and sent["ok"][0] == 55
