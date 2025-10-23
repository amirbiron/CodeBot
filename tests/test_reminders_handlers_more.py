import types
import uuid
from datetime import datetime, timezone

import pytest

from reminders.handlers import ReminderHandlers, RemindersDB, ReminderValidator, REMINDER_TIME, REMINDER_DESCRIPTION


class _User:
    def __init__(self, uid=1):
        self.id = uid


class _Chat:
    def __init__(self, cid=1):
        self.id = cid


class _Message:
    def __init__(self):
        self.text = ""
        self.replies = []

    async def reply_text(self, text, **kwargs):  # noqa: D401
        self.replies.append((text, kwargs))


class _CallbackQuery:
    def __init__(self, data, chat_id=1):
        self.data = data
        self.message = types.SimpleNamespace(chat_id=chat_id)

    async def answer(self, *a, **k):  # noqa: ARG002
        return None

    async def edit_message_text(self, *a, **k):  # noqa: D401
        return None


class _Update:
    def __init__(self, uid=1, cid=1):
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
        # do nothing else

    def get_jobs_by_name(self, name):  # noqa: ARG002
        return []


@pytest.mark.asyncio
async def test_receive_time_custom_text_success(monkeypatch):
    # Use real db manager (noop under tests)
    from database import db as _dbm
    db = RemindersDB(_dbm)
    h = ReminderHandlers(db, ReminderValidator())

    upd = _Update()
    ctx = types.SimpleNamespace(args=[], job_queue=_JobQ())

    # Set title state
    upd.message.text = "כותרת"
    await h.receive_title(upd, ctx)

    # Provide custom time as text
    upd.callback_query = None
    upd.message.text = "15:30"
    state = await h.receive_time(upd, ctx)
    assert state == REMINDER_DESCRIPTION
    # A prompt for description should be sent (either edited message or reply). We check that state proceeded.


@pytest.mark.asyncio
async def test_receive_time_custom_text_invalid(monkeypatch):
    from database import db as _dbm
    db = RemindersDB(_dbm)
    h = ReminderHandlers(db, ReminderValidator())

    upd = _Update()
    ctx = types.SimpleNamespace(args=[], job_queue=_JobQ())

    upd.message.text = "כותרת"
    await h.receive_title(upd, ctx)

    upd.callback_query = None
    upd.message.text = "not-a-time"
    state = await h.receive_time(upd, ctx)
    assert state == REMINDER_TIME


@pytest.mark.asyncio
async def test_receive_description_skip_paths(monkeypatch):
    from database import db as _dbm
    db = RemindersDB(_dbm)
    h = ReminderHandlers(db, ReminderValidator())

    upd = _Update()
    ctx = types.SimpleNamespace(args=[], job_queue=_JobQ())

    # Prepare title and time
    upd.message.text = "כותרת"
    await h.receive_title(upd, ctx)
    upd.callback_query = _CallbackQuery("time_1h")
    await h.receive_time(upd, ctx)

    # Skip with callback path
    upd.callback_query = _CallbackQuery("desc_skip")
    state = await h.receive_description(upd, ctx)
    from telegram.ext import ConversationHandler
    assert state == ConversationHandler.END

    # Prepare again and skip via text /skip
    upd = _Update()
    ctx = types.SimpleNamespace(args=[], job_queue=_JobQ())
    upd.message.text = "כותרת"
    await h.receive_title(upd, ctx)
    upd.callback_query = _CallbackQuery("time_1h")
    await h.receive_time(upd, ctx)

    upd.callback_query = None
    upd.message.text = "/skip"
    state = await h.receive_description(upd, ctx)
    assert state == ConversationHandler.END


@pytest.mark.asyncio
async def test_quick_reminder_invalid_format(monkeypatch):
    from database import db as _dbm
    db = RemindersDB(_dbm)
    h = ReminderHandlers(db, ReminderValidator())

    upd = _Update()
    ctx = types.SimpleNamespace(args=["לתקן", "באג"], job_queue=_JobQ())

    # Invalid because title must be in quotes
    state = await h._quick_reminder(upd, ctx, ctx.args)
    from telegram.ext import ConversationHandler
    assert state == ConversationHandler.END


@pytest.mark.asyncio
async def test_reminder_callback_rem_list(monkeypatch):
    from database import db as _dbm
    db = RemindersDB(_dbm)
    h = ReminderHandlers(db, ReminderValidator())

    upd = _Update()
    upd.callback_query = _CallbackQuery("rem_list")

    # context with job_queue providing required methods
    ctx = types.SimpleNamespace(job_queue=_JobQ())

    # Should not raise
    await h.reminder_callback(upd, ctx)
