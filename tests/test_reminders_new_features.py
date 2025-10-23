import types
from datetime import datetime, timezone, timedelta

import pytest

from reminders.handlers import ReminderHandlers, RemindersDB, ReminderValidator


class _User:
    def __init__(self, uid=1234):
        self.id = uid


class _Chat:
    def __init__(self, cid=1234):
        self.id = cid


class _Message:
    def __init__(self):
        self.text = ""
        self.replies = []

    async def reply_text(self, text, **kwargs):  # noqa: D401
        self.replies.append((text, kwargs))
        return None


class _CallbackQuery:
    def __init__(self, data, chat_id=1234):
        self.data = data
        self.message = types.SimpleNamespace(chat_id=chat_id)
        self._edits = []

    async def answer(self, *a, **k):  # noqa: ARG002
        return None

    async def edit_message_text(self, text, **kwargs):  # noqa: D401
        self._edits.append((text, kwargs))
        return None


class _Update:
    def __init__(self, uid=1234, cid=1234):
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
        # For tests we just say there are no existing jobs
        return []

    def jobs(self):
        return []


class _Bot:
    def __init__(self, sink):
        self.sink = sink

    async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None):  # noqa: ARG002
        self.sink.append((chat_id, text, reply_markup))
        return None


@pytest.mark.asyncio
async def test_reminders_list_buttons(monkeypatch):
    from database import db as _dbm
    db = RemindersDB(_dbm)
    h = ReminderHandlers(db, ReminderValidator())

    # DB returns a single pending reminder
    now = datetime.now(timezone.utc) + timedelta(hours=1)
    h.db.get_user_reminders = lambda user_id, status=None, limit=10, skip=0: [  # type: ignore
        {"reminder_id": "r1", "title": "בדיקה", "remind_at": now}
    ]

    upd = _Update()
    ctx = types.SimpleNamespace(args=[], job_queue=_JobQ())

    await h.reminders_list(upd, ctx)

    # Ensure a reply was sent with action buttons for the reminder
    assert upd.message.replies, "Expected a list reply with inline buttons"
    _, kwargs = upd.message.replies[-1]
    markup = kwargs.get("reply_markup")
    assert markup is not None and getattr(markup, "inline_keyboard", None), "Inline keyboard missing"

    # Flatten buttons and collect callback_data
    callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert any(cb == "rem_complete_r1" for cb in callbacks)
    assert any(cb == "rem_edit_r1" for cb in callbacks)
    assert any(cb == "rem_delete_r1" for cb in callbacks)


@pytest.mark.asyncio
async def test_reminder_edit_flow_menu(monkeypatch):
    from database import db as _dbm
    db = RemindersDB(_dbm)
    h = ReminderHandlers(db, ReminderValidator())

    upd = _Update()
    upd.callback_query = _CallbackQuery("rem_edit_r1")

    await h.reminder_callback(upd, types.SimpleNamespace(job_queue=_JobQ()))

    # Verify edit menu was shown with options
    assert upd.callback_query._edits, "Expected an edit message with options"
    _, kwargs = upd.callback_query._edits[-1]
    markup = kwargs.get("reply_markup")
    callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "edit_title_r1" in callbacks
    assert "edit_desc_r1" in callbacks
    assert "edit_time_r1" in callbacks


@pytest.mark.asyncio
async def test_reminder_delete_prompt(monkeypatch):
    from database import db as _dbm
    db = RemindersDB(_dbm)
    h = ReminderHandlers(db, ReminderValidator())

    upd = _Update()
    upd.callback_query = _CallbackQuery("rem_delete_r1")

    await h.reminder_callback(upd, types.SimpleNamespace(job_queue=_JobQ()))

    assert upd.callback_query._edits, "Expected a confirmation prompt"
    text, kwargs = upd.callback_query._edits[-1]
    assert "למחוק" in text
    markup = kwargs.get("reply_markup")
    callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert any(cb == "confirm_del_r1" for cb in callbacks)


@pytest.mark.asyncio
async def test_handle_edit_input_title_success(monkeypatch):
    from database import db as _dbm
    db = RemindersDB(_dbm)
    h = ReminderHandlers(db, ReminderValidator())

    called = {"args": None}
    h.db.update_reminder = lambda user_id, rid, updates: called.update({"args": (user_id, rid, updates)}) or True  # type: ignore

    upd = _Update()
    upd.message.text = "כותרת חדשה"
    ctx = types.SimpleNamespace(user_data={"edit_rid": "r1", "edit_field": "title"}, job_queue=_JobQ())

    await h.handle_edit_input(upd, ctx)

    # DB called with title update
    assert called["args"][1] == "r1"
    assert "title" in called["args"][2]
    # Ack message sent back to user
    assert upd.message.replies and any("עודכנה" in t for t, _ in upd.message.replies)


@pytest.mark.asyncio
async def test_handle_edit_input_time_reschedules(monkeypatch):
    from database import db as _dbm
    db = RemindersDB(_dbm)
    h = ReminderHandlers(db, ReminderValidator())

    # Ensure DB update returns True and document can be fetched for reschedule
    h.db.update_reminder = lambda user_id, rid, updates: True  # type: ignore
    h.db.reminders_collection.find_one = lambda q: {
        "reminder_id": q.get("reminder_id"),
        "user_id": 1234,
        "title": "טסט",
        "remind_at": datetime.now(timezone.utc) + timedelta(hours=1),
    }  # type: ignore[attr-defined]

    upd = _Update()
    upd.message.text = "15:30"  # parse_time should accept this
    jobq = _JobQ()
    ctx = types.SimpleNamespace(user_data={"edit_rid": "r1", "edit_field": "remind_at"}, job_queue=jobq)

    await h.handle_edit_input(upd, ctx)

    # A new job should be scheduled with a name that includes the reminder id
    assert any(name == "reminder_r1" for _, _, name, *_ in jobq.calls)
    # Ack message back to user
    assert upd.message.replies and any("תוזמנה מחדש" in t for t, _ in upd.message.replies)


def test_db_update_reminder_filters_and_updates(monkeypatch):
    from database import db as _dbm
    db = RemindersDB(_dbm)

    holder = {"called": False, "set": None}

    def fake_update_one(q, upd):  # noqa: ARG002
        holder["called"] = True
        holder["set"] = upd.get("$set", {})
        class R:
            modified_count = 1
        return R()

    db.reminders_collection.update_one = fake_update_one  # type: ignore[attr-defined]

    in_future = datetime.now(timezone.utc) + timedelta(hours=1)
    ok = db.update_reminder(1, "r1", {"remind_at": in_future, "is_sent": False, "hacker": True})
    assert ok is True
    assert "remind_at" in holder["set"] and "is_sent" in holder["set"]

    # Only unsafe fields --> should be ignored and return False
    ok2 = db.update_reminder(1, "r1", {"hacker": True})
    assert ok2 is False


@pytest.mark.asyncio
async def test_send_notification_includes_delete_button(monkeypatch):
    from database import db as _dbm
    db = RemindersDB(_dbm)
    h = ReminderHandlers(db, ReminderValidator())

    # Avoid touching DB in this path
    h.db.mark_reminder_sent = lambda *a, **k: None  # type: ignore

    sink = []
    bot = _Bot(sink)
    doc = {
        "reminder_id": "rxx",
        "user_id": 1234,
        "title": "בדיקה",
        "description": "תיאור",
    }
    ctx = types.SimpleNamespace(job=types.SimpleNamespace(data=doc, chat_id=777), bot=bot)

    await h._send_reminder_notification(ctx)

    assert sink, "Expected a sent message"
    _, _, markup = sink[-1]
    callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert any(cb == "rem_delete_rxx" for cb in callbacks)  # includes delete button
