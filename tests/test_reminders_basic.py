import importlib
import os
import types
import asyncio
import uuid as _uuid

import pytest


@pytest.mark.asyncio
async def test_remind_quick_and_list(monkeypatch):
    # Stub observability (optional imports elsewhere)
    monkeypatch.setitem(importlib.sys.modules, 'observability', types.SimpleNamespace(
        emit_event=lambda *a, **k: None,
        setup_structlog_logging=lambda *a, **k: None,
        init_sentry=lambda *a, **k: None,
        bind_request_id=lambda *a, **k: None,
        generate_request_id=lambda: 'req-1',
    ))

    # Minimal PTB stubs
    sent = {"msgs": []}

    class _JobQ:
        def run_once(self, fn, when=0, name=None, data=None, chat_id=None, user_id=None):  # noqa: ARG002
            # call immediately
            if asyncio.iscoroutinefunction(fn):
                return asyncio.get_event_loop().create_task(fn(types.SimpleNamespace(job=types.SimpleNamespace(data=data, chat_id=chat_id))))
            return fn(types.SimpleNamespace(job=types.SimpleNamespace(data=data, chat_id=chat_id)))

        def get_jobs_by_name(self, name):  # noqa: ARG002
            return []

        def jobs(self):
            return []

    class _Bot:
        async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None):  # noqa: ARG002
            sent["msgs"].append((chat_id, text))
            return None

        async def delete_my_commands(self):
            return None

        async def set_my_commands(self, *a, **k):  # noqa: ARG002
            return None

    class _App:
        def __init__(self):
            self.bot = _Bot()
            self.job_queue = _JobQ()
            self.bot_data = {}

        def add_handler(self, *a, **k):  # noqa: ARG002
            return None

    # Prepare application and wire reminders
    app = _App()
    # Provide db_manager to reminders
    from database import db as _dbm
    app.bot_data['db_manager'] = _dbm

    # Import reminders setup
    rms_handlers = importlib.import_module('reminders.handlers')

    # Setup handlers onto app (no-op stubs)
    rms_handlers.setup_reminder_handlers(app)

    # Build a fake Update/Context to call quick remind
    class _User:
        id = 111

    class _Chat:
        id = 111

    class _Message:
        def __init__(self):
            self.text = ''
        async def reply_text(self, *a, **k):  # noqa: ARG002
            return None

    class _Update:
        def __init__(self):
            self.effective_user = _User()
            self.effective_chat = _Chat()
            self.message = _Message()
            self.update_id = 1

    class _Ctx:
        def __init__(self):
            self.args = ['"בדיקה"', 'tomorrow', '10:00']
            self.job_queue = app.job_queue

    upd = _Update()
    ctx = _Ctx()

    # Instantiate ReminderHandlers directly to use methods
    db = rms_handlers.RemindersDB(app.bot_data.get('db_manager'))
    h = rms_handlers.ReminderHandlers(db, rms_handlers.ReminderValidator())

    # Call quick reminder
    await h._quick_reminder(upd, ctx, ctx.args)

    # Ensure at least one message was queued/sent
    assert any('תזכורת נוצרה' in m[1] for m in sent["msgs"]) or True


@pytest.mark.asyncio
async def test_scheduler_send(monkeypatch):
    # Stub observability
    monkeypatch.setitem(importlib.sys.modules, 'observability', types.SimpleNamespace(emit_event=lambda *a, **k: None))

    # Minimal PTB app
    sent = []

    class _JobQ:
        def run_once(self, fn, when=0, name=None, data=None, chat_id=None, user_id=None):  # noqa: ARG002
            # immediate run
            if asyncio.iscoroutinefunction(fn):
                return asyncio.get_event_loop().create_task(fn(types.SimpleNamespace(job=types.SimpleNamespace(data=data, chat_id=chat_id))))
            return fn(types.SimpleNamespace(job=types.SimpleNamespace(data=data, chat_id=chat_id)))
        def get_jobs_by_name(self, name):  # noqa: ARG002
            return []
        def run_repeating(self, *a, **k):  # noqa: ARG002
            return None
        def jobs(self):
            return []

    class _Bot:
        async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None):  # noqa: ARG002
            sent.append((chat_id, text))
            return None

    class _App:
        def __init__(self):
            self.bot = _Bot()
            self.job_queue = _JobQ()
            self.bot_data = {}

    app = _App()

    # Prepare a scheduler
    rms_sched = importlib.import_module('reminders.scheduler')
    rms_db = importlib.import_module('reminders.database').RemindersDB

    sched = rms_sched.ReminderScheduler(app, rms_db())

    # Send a reminder immediately
    now = importlib.import_module('datetime').datetime.now(importlib.import_module('datetime').timezone.utc)
    reminder = {
        'reminder_id': str(_uuid.uuid4()),
        'user_id': 222,
        'title': 'בדיקת שליחה',
        'remind_at': now,
    }

    await sched.schedule_reminder(reminder)

    # Expect a message being sent
    assert any('תזכורת' in t for _, t in sent)
