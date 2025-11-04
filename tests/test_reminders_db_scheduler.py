import asyncio
import types
import uuid
from datetime import datetime, timezone, timedelta

import pytest

from reminders.database import RemindersDB, DuplicateKeyError
from reminders.scheduler import ReminderScheduler


class _App:
    class _JobQ:
        def __init__(self):
            self.invoked = []
        def run_once(self, fn, when=0, name=None, data=None, chat_id=None, user_id=None):  # noqa: ARG002
            # execute immediately when 'when' is now/past
            if when and isinstance(when, datetime) and when <= datetime.now(timezone.utc):
                return fn(types.SimpleNamespace(job=types.SimpleNamespace(data=data, chat_id=chat_id)))
            self.invoked.append((fn, when, name, data, chat_id, user_id))
        def get_jobs_by_name(self, name):  # noqa: ARG002
            return []
        def run_repeating(self, *a, **k):  # noqa: ARG002
            return None
        def jobs(self):
            return []
    class _Bot:
        async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None):  # noqa: ARG002
            return None
    def __init__(self):
        self.job_queue = _App._JobQ()
        self.bot = _App._Bot()
        self.bot_data = {}


def test_db_mark_sent_error_path(monkeypatch):
    from database import db as _dbm
    db = RemindersDB(_dbm)

    # Simulate failure updating DB
    called = {"upd": False}
    def boom_update(*a, **k):  # noqa: ARG002
        called["upd"] = True
        raise Exception("DB down")
    db.reminders_collection.update_one = boom_update  # type: ignore[attr-defined]

    # Should not raise on success path (just updates is_sent)
    db.mark_reminder_sent("rid1", success=True)
    assert called["upd"] is True

    # Should not raise on error path either
    called["upd"] = False
    db.mark_reminder_sent("rid1", success=False, error="x")
    assert called["upd"] is True


def test_db_create_duplicate(monkeypatch):
    from database import db as _dbm
    db = RemindersDB(_dbm)

    def boom_insert(doc):  # noqa: ARG002
        raise DuplicateKeyError("dup")
    db.reminders_collection.insert_one = boom_insert  # type: ignore[attr-defined]

    ok, err = db.create_reminder(types.SimpleNamespace(
        validate=lambda: (True, ""),
        to_dict=lambda: {},
        user_id=1,
    ))
    assert ok is False and "קיימת" in err


def test_scheduler_checks_recurring(monkeypatch):
    from database import db as _dbm
    app = _App()
    rdb = RemindersDB(_dbm)
    sched = ReminderScheduler(app, rdb)

    # Should not raise and should call handle_recurring_reminders via job
    rdb.handle_recurring_reminders()


@pytest.mark.asyncio
async def test_scheduler_reload_schedules_future_and_sends_due(monkeypatch):
    from reminders.scheduler import ReminderScheduler

    sent_messages = []

    class _JobQueue:
        def __init__(self):
            self.scheduled = []
            self.immediate_tasks = []

        def run_once(self, fn, when=0, name=None, data=None, chat_id=None, user_id=None):  # noqa: ARG002
            if when and isinstance(when, datetime) and when <= datetime.now(timezone.utc):
                task = asyncio.create_task(fn(types.SimpleNamespace(job=types.SimpleNamespace(data=data, chat_id=chat_id))))
                self.immediate_tasks.append(task)
                return task
            self.scheduled.append({
                "fn": fn,
                "when": when,
                "name": name,
                "data": data,
                "chat_id": chat_id,
                "user_id": user_id,
            })
            return None

        def get_jobs_by_name(self, name):  # noqa: ARG002
            return []

        def run_repeating(self, *a, **k):  # noqa: ARG002
            return None

        def jobs(self):
            return []

    class _Bot:
        async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None):  # noqa: ARG002
            sent_messages.append({"chat_id": chat_id, "text": text})
            return None

    class _AppStub:
        def __init__(self):
            self.job_queue = _JobQueue()
            self.bot = _Bot()
            self.bot_data = {}

    class _DBStub:
        def __init__(self, due_items, future_items):
            self._due = due_items
            self._future = future_items
            self.sent_status = []

        def get_pending_reminders(self, batch_size=1000):  # noqa: ARG002
            return list(self._due)

        def get_future_reminders(self, batch_size=1000):  # noqa: ARG002
            return list(self._future)

        def mark_reminder_sent(self, reminder_id, success=True, error=None):  # noqa: ARG002
            self.sent_status.append((reminder_id, success))

    now = datetime.now(timezone.utc)
    due_time = now - timedelta(minutes=10)
    future_time = now + timedelta(minutes=15)

    due_reminder = {
        "reminder_id": "due-1",
        "user_id": 42,
        "title": "Due",
        "description": "",
        "remind_at": due_time,
    }
    future_reminder = {
        "reminder_id": "future-1",
        "user_id": 42,
        "title": "Future",
        "description": "",
        "remind_at": future_time,
    }

    app_stub = _AppStub()
    db_stub = _DBStub([due_reminder], [future_reminder])
    sched = ReminderScheduler(app_stub, db_stub)

    await sched._load_existing_reminders()
    if app_stub.job_queue.immediate_tasks:
        await asyncio.gather(*app_stub.job_queue.immediate_tasks)

    # Due reminder should be sent immediately
    assert any(entry[0] == "due-1" and entry[1] is True for entry in db_stub.sent_status)
    assert any(msg["chat_id"] == 42 for msg in sent_messages)

    # Future reminder should be scheduled (not sent yet)
    assert len(app_stub.job_queue.scheduled) == 1
    scheduled_entry = app_stub.job_queue.scheduled[0]
    assert scheduled_entry["name"] == "reminder_future-1"
    assert scheduled_entry["when"] == future_time
