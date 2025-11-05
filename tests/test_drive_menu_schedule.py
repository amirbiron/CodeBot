import asyncio
import types
import pytest


@pytest.mark.asyncio
async def test_ensure_schedule_job_sets_next_and_emits_events(monkeypatch):
    import handlers.drive.menu as dm

    # stub emit_event to capture calls
    events = []
    monkeypatch.setattr(dm, "emit_event", lambda e, severity="info", **f: events.append((e, severity, f)), raising=True)

    # stub db prefs storage
    class _DB:
        def __init__(self):
            self.saved = []
            self.prefs = {"schedule": "daily"}
        def get_drive_prefs(self, user_id):
            return dict(self.prefs)
        def save_drive_prefs(self, user_id, prefs):
            self.saved.append(dict(prefs))
            self.prefs.update(prefs)
            return True

    db = _DB()
    monkeypatch.setattr(dm, "db", db, raising=True)

    # job queue stub that records the scheduled callback and returns a job object
    scheduled = {}
    class _JQ:
        def run_repeating(self, cb, interval, first, name=None, data=None):
            scheduled.update({"cb": cb, "interval": interval, "first": first, "name": name, "data": data})
            return types.SimpleNamespace(schedule_removal=lambda: None)

    class _App:
        def __init__(self):
            self.job_queue = _JQ()

    ctx = types.SimpleNamespace(application=_App(), bot_data={})

    handler = dm.GoogleDriveMenuHandler()
    await handler._ensure_schedule_job(ctx, user_id=123, sched_key="daily")

    # schedule_next_at should be persisted
    assert any("schedule_next_at" in d for d in db.saved)
    # job stored in bot_data and next_t set
    job = ctx.bot_data.get("drive_schedule_jobs", {}).get(123)
    assert job is not None
    # event about job creation should be emitted
    assert any(ev[0] == "drive_schedule_job_set" for ev in events)


@pytest.mark.asyncio
async def test_scheduled_backup_callback_success_updates_prefs_and_emits(monkeypatch):
    import handlers.drive.menu as dm

    # stub emit_event to capture calls
    events = []
    monkeypatch.setattr(dm, "emit_event", lambda e, severity="info", **f: events.append((e, severity, f)), raising=True)

    # stub db prefs
    class _DB:
        def __init__(self):
            self.saved = []
            self.prefs = {"schedule": "daily"}
        def get_drive_prefs(self, user_id):
            return dict(self.prefs)
        def save_drive_prefs(self, user_id, prefs):
            self.saved.append(dict(prefs))
            self.prefs.update(prefs)
            return True
    db = _DB()
    monkeypatch.setattr(dm, "db", db, raising=True)

    # stub Drive scheduled backup to succeed
    monkeypatch.setattr(dm.gdrive, "perform_scheduled_backup", lambda uid: True, raising=True)

    # prepare a scheduled callback via _ensure_schedule_job
    scheduled = {}
    class _JQ:
        def run_repeating(self, cb, interval, first, name=None, data=None):
            scheduled.update({"cb": cb, "interval": interval, "first": first, "name": name, "data": data})
            return types.SimpleNamespace(schedule_removal=lambda: None)
    class _App:
        def __init__(self):
            self.job_queue = _JQ()
    ctx = types.SimpleNamespace(application=_App(), bot_data={})

    handler = dm.GoogleDriveMenuHandler()
    await handler._ensure_schedule_job(ctx, user_id=7, sched_key="daily")

    # invoke the scheduled callback once with a minimal ctx
    sent = {"count": 0}
    class _Bot:
        async def send_message(self, **_k):
            sent["count"] += 1
    cb_ctx = types.SimpleNamespace(job=types.SimpleNamespace(data={"user_id": 7}), bot=_Bot())
    await scheduled["cb"](cb_ctx)

    # prefs updated include schedule_next_at and last_backup_at
    merged = {}
    for p in db.saved:
        merged.update(p)
    assert "schedule_next_at" in merged and "last_backup_at" in merged
    # events around start/result/update_prefs were emitted
    ev_names = [e[0] for e in events]
    assert "drive_scheduled_backup_start" in ev_names
    assert "drive_scheduled_backup_result" in ev_names
    assert "drive_scheduled_backup_update_prefs" in ev_names


@pytest.mark.asyncio
async def test_manual_all_updates_next_and_triggers_reschedule(monkeypatch):
    import handlers.drive.menu as dm

    # stub db prefs with active schedule
    class _DB:
        def __init__(self):
            self.saved = []
            self.prefs = {"schedule": "daily"}
        def get_drive_prefs(self, user_id):
            return dict(self.prefs)
        def save_drive_prefs(self, user_id, prefs):
            self.saved.append(dict(prefs))
            self.prefs.update(prefs)
            return True
    db = _DB()
    monkeypatch.setattr(dm, "db", db, raising=True)

    # stub Drive service and upload path
    monkeypatch.setattr(dm.gdrive, "get_drive_service", lambda uid: object(), raising=True)
    monkeypatch.setattr(dm.gdrive, "create_full_backup_zip_bytes", lambda uid, category="all": ("f.zip", b"ZIP"), raising=True)
    monkeypatch.setattr(dm.gdrive, "compute_friendly_name", lambda uid, cat, label, content_sample=None: "BKP.zip", raising=True)
    monkeypatch.setattr(dm.gdrive, "compute_subpath", lambda cat: "all", raising=True)
    monkeypatch.setattr(dm.gdrive, "upload_bytes", lambda uid, filename, data, folder_id=None, sub_path=None: "fid", raising=True)

    # make to_thread run inline
    async def _inline(fn, *a, **k):
        return fn(*a, **k)
    monkeypatch.setattr(dm.asyncio, "to_thread", _inline, raising=True)

    # build Update/Context stubs
    class _Msg:
        def __init__(self):
            self.text = None
        async def reply_text(self, text, **kwargs):
            self.text = text
            return self
        async def edit_text(self, text, **kwargs):
            self.text = text
            return self
    class _Query:
        def __init__(self):
            self.message = _Msg()
            self.data = "drive_simple_confirm"
            self.from_user = types.SimpleNamespace(id=5)
        async def edit_message_text(self, text, **kwargs):
            self.message.text = text
            return self.message
        async def answer(self, *args, **kwargs):
            return None
    class _Update:
        def __init__(self):
            self.callback_query = _Query()
            self.effective_user = types.SimpleNamespace(id=5)
    class _JQ:
        def __init__(self):
            self.calls = 0
        def run_repeating(self, *a, **k):
            self.calls += 1
            return types.SimpleNamespace(schedule_removal=lambda: None)
    class _App:
        def __init__(self):
            self.job_queue = _JQ()
    class _Context:
        def __init__(self):
            self.user_data = {}
            self.bot_data = {}
            self.application = _App()

    handler = dm.GoogleDriveMenuHandler()
    # simulate prior selection of 'all'
    handler._session(5)["selected_category"] = "all"

    upd, ctx = _Update(), _Context()
    await handler.handle_callback(upd, ctx)

    # verify schedule_next_at persisted and job rescheduled once
    merged = {}
    for p in db.saved:
        merged.update(p)
    assert "schedule_next_at" in merged
    assert ctx.application.job_queue.calls >= 1


@pytest.mark.asyncio
async def test_adv_by_repo_updates_next_when_uploaded(monkeypatch):
    import handlers.drive.menu as dm

    class _DB:
        def __init__(self):
            self.saved = []
            self.prefs = {"schedule": "daily"}
        def get_drive_prefs(self, user_id):
            return dict(self.prefs)
        def save_drive_prefs(self, user_id, prefs):
            self.saved.append(dict(prefs))
            self.prefs.update(prefs)
            return True
    db = _DB()
    monkeypatch.setattr(dm, "db", db, raising=True)

    # stub Drive
    monkeypatch.setattr(dm.gdrive, "get_drive_service", lambda uid: object(), raising=True)
    monkeypatch.setattr(dm.gdrive, "create_repo_grouped_zip_bytes", lambda uid: [("repo1", "name.zip", b"data")], raising=True)
    monkeypatch.setattr(dm.gdrive, "compute_friendly_name", lambda uid, cat, name, content_sample=None: "name.zip", raising=True)
    monkeypatch.setattr(dm.gdrive, "compute_subpath", lambda cat, repo=None: "by_repo/repo1", raising=True)
    monkeypatch.setattr(dm.gdrive, "upload_bytes", lambda *a, **k: "fid", raising=True)

    # Update/Context stubs
    class _Msg:
        def __init__(self):
            self.text = None
        async def edit_text(self, text, **kwargs):
            self.text = text
            return self
    class _Query:
        def __init__(self):
            self.message = _Msg()
            self.data = "drive_adv_by_repo"
            self.from_user = types.SimpleNamespace(id=11)
        async def edit_message_text(self, text, **kwargs):
            self.message.text = text
            return self.message
        async def answer(self, *args, **kwargs):
            return None
    class _Update:
        def __init__(self):
            self.callback_query = _Query()
            self.effective_user = types.SimpleNamespace(id=11)
    class _Ctx:
        def __init__(self):
            self.user_data = {}
            self.bot_data = {}
            self.application = types.SimpleNamespace(job_queue=types.SimpleNamespace(run_repeating=lambda *a, **k: types.SimpleNamespace(schedule_removal=lambda: None)))

    handler = dm.GoogleDriveMenuHandler()
    upd, ctx = _Update(), _Ctx()

    await handler.handle_callback(upd, ctx)

    merged = {}
    for p in db.saved:
        merged.update(p)
    assert "schedule_next_at" in merged
