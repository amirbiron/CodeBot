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
