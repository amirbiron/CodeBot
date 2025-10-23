import types
from datetime import datetime, timezone, timedelta

import pytest

from reminders.handlers import ReminderHandlers, RemindersDB, ReminderValidator


class _User:
    def __init__(self, uid=5555):
        self.id = uid


class _Chat:
    def __init__(self, cid=5555):
        self.id = cid


class _Message:
    def __init__(self):
        self.text = ""
        self.replies = []

    async def reply_text(self, text, **kwargs):  # noqa: D401
        self.replies.append((text, kwargs))
        return None


class _CallbackQuery:
    def __init__(self, data, chat_id=5555):
        self.data = data
        self.message = types.SimpleNamespace(chat_id=chat_id)
        self._edits = []
        self._answers = []

    async def answer(self, text=None, **kwargs):  # noqa: D401
        self._answers.append((text, kwargs))
        return None

    async def edit_message_text(self, text, **kwargs):  # noqa: D401
        self._edits.append((text, kwargs))
        return None


class _Update:
    def __init__(self, uid=5555, cid=5555):
        self.effective_user = _User(uid)
        self.effective_chat = _Chat(cid)
        self.message = _Message()
        self.callback_query = None
        self.update_id = 1


class _JobQ:
    def __init__(self):
        self.calls = []

    def run_once(self, fn, when=0, name=None, data=None, chat_id=None, user_id=None):  # noqa: ARG002
        self.calls.append((fn, when, name, data, chat_id, user_id))
        return None

    def get_jobs_by_name(self, name):  # noqa: ARG002
        class _J:
            def schedule_removal(self):
                return None
        return [_J()]

    def jobs(self):
        return []


@pytest.mark.asyncio
async def test_handle_edit_input_title_empty_and_illegal():
    from database import db as _dbm
    db = RemindersDB(_dbm)
    h = ReminderHandlers(db, ReminderValidator())

    # Empty title
    upd = _Update()
    upd.message.text = ""
    ctx = types.SimpleNamespace(user_data={"edit_rid": "r2", "edit_field": "title"}, job_queue=_JobQ())
    await h.handle_edit_input(upd, ctx)
    assert upd.message.replies and any("לא יכולה" in t for t, _ in upd.message.replies)

    # Illegal characters
    upd = _Update()
    upd.message.text = "<bad>"
    ctx = types.SimpleNamespace(user_data={"edit_rid": "r2", "edit_field": "title"}, job_queue=_JobQ())
    await h.handle_edit_input(upd, ctx)
    assert upd.message.replies and any("לא תקינה" in t for t, _ in upd.message.replies)


@pytest.mark.asyncio
async def test_handle_edit_input_desc_success_invalid_and_clear_and_empty():
    from database import db as _dbm
    db = RemindersDB(_dbm)
    h = ReminderHandlers(db, ReminderValidator())

    # Success path
    called = {"updates": None}
    h.db.update_reminder = lambda user_id, rid, updates: called.update({"updates": updates}) or True  # type: ignore

    upd = _Update()
    upd.message.text = "תיאור חדש"
    ctx = types.SimpleNamespace(user_data={"edit_rid": "r3", "edit_field": "description"}, job_queue=_JobQ())
    await h.handle_edit_input(upd, ctx)
    assert called["updates"]["description"] == "תיאור חדש"
    assert upd.message.replies and any("עודכן" in t for t, _ in upd.message.replies)

    # Invalid description (illegal char)
    upd = _Update()
    upd.message.text = "bad<desc>"
    ctx = types.SimpleNamespace(user_data={"edit_rid": "r3", "edit_field": "description"}, job_queue=_JobQ())
    await h.handle_edit_input(upd, ctx)
    assert upd.message.replies and any("לא תקין" in t for t, _ in upd.message.replies)

    # Clear description via /clear
    called2 = {"updates": None}
    h.db.update_reminder = lambda user_id, rid, updates: called2.update({"updates": updates}) or True  # type: ignore
    upd = _Update()
    upd.message.text = "/clear"
    ctx = types.SimpleNamespace(user_data={"edit_rid": "r3", "edit_field": "description"}, job_queue=_JobQ())
    await h.handle_edit_input(upd, ctx)
    assert called2["updates"]["description"] == ""

    # Clear description via empty input
    called3 = {"updates": None}
    h.db.update_reminder = lambda user_id, rid, updates: called3.update({"updates": updates}) or True  # type: ignore
    upd = _Update()
    upd.message.text = ""
    ctx = types.SimpleNamespace(user_data={"edit_rid": "r3", "edit_field": "description"}, job_queue=_JobQ())
    await h.handle_edit_input(upd, ctx)
    assert called3["updates"]["description"] == ""


@pytest.mark.asyncio
async def test_handle_edit_input_time_invalid_and_past():
    from database import db as _dbm
    db = RemindersDB(_dbm)
    h = ReminderHandlers(db, ReminderValidator())

    # Invalid format
    upd = _Update()
    upd.message.text = "not-a-time"
    ctx = types.SimpleNamespace(user_data={"edit_rid": "r4", "edit_field": "remind_at"}, job_queue=_JobQ())
    await h.handle_edit_input(upd, ctx)
    assert upd.message.replies and any("לא הבנתי" in t for t, _ in upd.message.replies)

    # Past time using ISO-like
    upd = _Update()
    upd.message.text = "2000-01-01 00:00"
    ctx = types.SimpleNamespace(user_data={"edit_rid": "r4", "edit_field": "remind_at"}, job_queue=_JobQ())
    await h.handle_edit_input(upd, ctx)
    assert upd.message.replies and any("בעתיד" in t for t, _ in upd.message.replies)


@pytest.mark.asyncio
async def test_handle_edit_input_no_state_noop():
    from database import db as _dbm
    db = RemindersDB(_dbm)
    h = ReminderHandlers(db, ReminderValidator())

    upd = _Update()
    upd.message.text = "something"
    ctx = types.SimpleNamespace(user_data={}, job_queue=_JobQ())
    await h.handle_edit_input(upd, ctx)
    # No replies as edit state is missing
    assert upd.message.replies == []


@pytest.mark.asyncio
async def test_reminder_confirm_delete_success():
    from database import db as _dbm
    db = RemindersDB(_dbm)
    h = ReminderHandlers(db, ReminderValidator())

    h.db.delete_reminder = lambda user_id, rid: True  # type: ignore

    upd = _Update()
    upd.callback_query = _CallbackQuery("confirm_del_r77")

    await h.reminder_callback(upd, types.SimpleNamespace(job_queue=_JobQ()))

    assert upd.callback_query._edits, "Expected deletion confirmation message"
    text, _ = upd.callback_query._edits[-1]
    assert "נמחקה" in text


@pytest.mark.asyncio
async def test_reminder_list_empty_message():
    from database import db as _dbm
    db = RemindersDB(_dbm)
    h = ReminderHandlers(db, ReminderValidator())

    h.db.get_user_reminders = lambda user_id, status=None, limit=10, skip=0: []  # type: ignore

    upd = _Update()
    ctx = types.SimpleNamespace(args=[], job_queue=_JobQ())
    await h.reminders_list(upd, ctx)

    assert upd.message.replies and any("אין לך" in t for t, _ in upd.message.replies)


def test_db_update_reminder_invalid_inputs():
    from database import db as _dbm
    db = RemindersDB(_dbm)

    assert db.update_reminder(1, "r1", None) is False  # type: ignore
    assert db.update_reminder(1, "r1", {}) is False


@pytest.mark.asyncio
async def test_time_edit_reschedules_in_original_chat():
    from database import db as _dbm
    db = RemindersDB(_dbm)
    h = ReminderHandlers(db, ReminderValidator())

    # DB returns doc with original chat_id 999 (different than current 5555)
    h.db.update_reminder = lambda user_id, rid, updates: True  # type: ignore
    original_chat = 999
    h.db.reminders_collection.find_one = lambda q: {
        "reminder_id": q.get("reminder_id"),
        "user_id": 5555,
        "title": "טסט",
        "remind_at": datetime.now(timezone.utc) + timedelta(hours=1),
        "chat_id": original_chat,
    }  # type: ignore[attr-defined]

    upd = _Update(cid=5555)  # current chat is 5555
    upd.message.text = "15:30"
    jobq = _JobQ()
    ctx = types.SimpleNamespace(user_data={"edit_rid": "rX", "edit_field": "remind_at"}, job_queue=jobq)

    await h.handle_edit_input(upd, ctx)

    # Ensure job scheduled to the original chat id, not current chat
    assert any(chat_id == original_chat for *_, chat_id, _ in jobq.calls)
