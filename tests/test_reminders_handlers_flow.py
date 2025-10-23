import importlib
import types
import asyncio
from datetime import datetime, timezone, timedelta

import pytest

from reminders.handlers import (
    ReminderHandlers,
    RemindersDB,
    ReminderValidator,
    REMINDER_TITLE,
    REMINDER_TIME,
    REMINDER_DESCRIPTION,
)


class _User:
    def __init__(self, uid=1001):
        self.id = uid


class _Chat:
    def __init__(self, cid=1001):
        self.id = cid


class _Message:
    def __init__(self):
        self.text = ""
        self._replies = []

    async def reply_text(self, text, **kwargs):  # noqa: D401
        self._replies.append((text, kwargs))
        return None


class _CallbackQuery:
    def __init__(self, data, chat_id=1001):
        self.data = data
        self.message = types.SimpleNamespace(chat_id=chat_id)

    async def answer(self, *a, **k):  # noqa: ARG002
        return None

    async def edit_message_text(self, text, **kwargs):  # noqa: D401
        return None


class _Update:
    def __init__(self, user_id=1001, chat_id=1001):
        self.effective_user = _User(user_id)
        self.effective_chat = _Chat(chat_id)
        self.message = _Message()
        self.callback_query = None
        self.update_id = 1


class _JobQ:
    def __init__(self):
        self.calls = []

    def run_once(self, fn, when=0, name=None, data=None, chat_id=None, user_id=None):  # noqa: ARG002
        self.calls.append((fn, when, name, data, chat_id, user_id))
        # execute immediately in tests
        if asyncio.iscoroutinefunction(fn):
            return asyncio.get_event_loop().create_task(fn(types.SimpleNamespace(job=types.SimpleNamespace(data=data, chat_id=chat_id))))
        return fn(types.SimpleNamespace(job=types.SimpleNamespace(data=data, chat_id=chat_id)))

    def get_jobs_by_name(self, name):
        return [types.SimpleNamespace(schedule_removal=lambda: None)] if any(c[2] == name for c in self.calls) else []

    def run_repeating(self, *a, **k):  # noqa: ARG002
        return None

    def jobs(self):
        return []


class _Bot:
    def __init__(self, sink):
        self.sink = sink

    async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None):  # noqa: ARG002
        self.sink.append((chat_id, text))
        return None

    async def delete_my_commands(self):
        return None

    async def set_my_commands(self, *a, **k):  # noqa: ARG002
        return None


class _App:
    def __init__(self, sink):
        self.bot = _Bot(sink)
        self.job_queue = _JobQ()
        self.bot_data = {}

    def add_handler(self, *a, **k):  # noqa: ARG002
        return None


@pytest.mark.asyncio
async def test_interactive_flow_time_presets(monkeypatch):
    # Silence observability
    monkeypatch.setitem(importlib.sys.modules, 'observability', types.SimpleNamespace(emit_event=lambda *a, **k: None))

    sent = []
    app = _App(sent)

    # Prepare handlers with DB (noop DB under tests)
    from database import db as _dbm
    app.bot_data['db_manager'] = _dbm
    db = RemindersDB(app.bot_data.get('db_manager'))
    h = ReminderHandlers(db, ReminderValidator())

    # Start conversation
    upd = _Update()
    ctx = types.SimpleNamespace(args=[], job_queue=app.job_queue)
    state = await h.remind_command(upd, ctx)
    assert state == REMINDER_TITLE

    # Provide title
    upd.message.text = "כותרת"
    state = await h.receive_title(upd, ctx)
    assert state == REMINDER_TIME

    # Pick "tomorrow morning"
    upd.callback_query = _CallbackQuery("time_tomorrow_9")
    state = await h.receive_time(upd, ctx)
    assert state == REMINDER_DESCRIPTION

    # Skip description and finalize
    upd.callback_query = _CallbackQuery("desc_skip")
    state = await h.receive_description(upd, ctx)
    assert state == ConversationHandler.END

    # Ensure a job was scheduled or a message sent
    assert app.job_queue.calls or sent


@pytest.mark.asyncio
async def test_receive_time_custom_branch(monkeypatch):
    monkeypatch.setitem(importlib.sys.modules, 'observability', types.SimpleNamespace(emit_event=lambda *a, **k: None))
    app = _App([])
    from database import db as _dbm
    db = RemindersDB(_dbm)
    h = ReminderHandlers(db, ReminderValidator())

    upd = _Update()
    ctx = types.SimpleNamespace(args=[], job_queue=app.job_queue)
    upd.message.text = "כותרת"
    await h.receive_title(upd, ctx)

    upd.callback_query = _CallbackQuery("time_custom")
    state = await h.receive_time(upd, ctx)
    assert state == REMINDER_TIME  # stays in time state awaiting user input


@pytest.mark.asyncio
async def test_callback_complete_and_snooze(monkeypatch):
    monkeypatch.setitem(importlib.sys.modules, 'observability', types.SimpleNamespace(emit_event=lambda *a, **k: None))
    sent = []
    app = _App(sent)
    from database import db as _dbm
    db = RemindersDB(_dbm)
    h = ReminderHandlers(db, ReminderValidator())

    # Monkeypatch db methods
    h.db.complete_reminder = lambda user_id, rid: True  # type: ignore
    h.db.snooze_reminder = lambda user_id, rid, minutes: True  # type: ignore
    h.db.reminders_collection.find_one = lambda q: {  # type: ignore[attr-defined]
        'reminder_id': list(q.values())[0],
        'user_id': 1001,
        'title': 'טסט',
        'remind_at': datetime.now(timezone.utc) + timedelta(minutes=10),
    }

    # Complete
    upd = _Update()
    upd.callback_query = _CallbackQuery("rem_complete_abc")
    await h.reminder_callback(upd, types.SimpleNamespace(job_queue=app.job_queue))

    # Snooze -> minutes selection UI
    upd.callback_query = _CallbackQuery("rem_snooze_abc")
    await h.reminder_callback(upd, types.SimpleNamespace(job_queue=app.job_queue))

    # Execute snooze
    upd.callback_query = _CallbackQuery("snooze_abc_60")
    await h.reminder_callback(upd, types.SimpleNamespace(job_queue=app.job_queue))

    # Delete confirm
    h.db.delete_reminder = lambda user_id, rid: True  # type: ignore
    upd.callback_query = _CallbackQuery("confirm_del_abc")
    await h.reminder_callback(upd, types.SimpleNamespace(job_queue=app.job_queue))
