import types
import pytest

from reminders.handlers import ReminderHandlers, RemindersDB, ReminderValidator


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


class _CQ:
    def __init__(self, data, store):
        self.data = data
        self.message = types.SimpleNamespace(chat_id=1)
        self._store = store

    async def answer(self, *a, **k):  # noqa: ARG002
        return None

    async def edit_message_text(self, text, **kwargs):  # noqa: D401
        self._store.append((text, kwargs))
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

    def get_jobs_by_name(self, name):  # noqa: ARG002
        return []


@pytest.mark.asyncio
async def test_receive_description_hebrew_skip_and_prompt(monkeypatch):
    from database import db as _dbm
    db = RemindersDB(_dbm)
    h = ReminderHandlers(db, ReminderValidator())

    upd = _Update()
    ctx = types.SimpleNamespace(args=[], job_queue=_JobQ())

    # Prepare title and time
    upd.message.text = "כותרת"
    await h.receive_title(upd, ctx)
    upd.callback_query = _CQ("time_1h", [])
    await h.receive_time(upd, ctx)

    # Desc add -> should prompt with 'או שלח `דלג`'
    store = []
    upd.callback_query = _CQ("desc_add", store)
    state = await h.receive_description(upd, ctx)
    assert state == h.REMINDER_DESCRIPTION if hasattr(h, 'REMINDER_DESCRIPTION') else 2
    assert any("או שלח `דלג`" in m[0] for m in store)

    # Now send Hebrew 'דלג' as free text to skip description
    upd.callback_query = None
    upd.message.text = "דלג"
    state2 = await h.receive_description(upd, ctx)
    from telegram.ext import ConversationHandler
    assert state2 == ConversationHandler.END


@pytest.mark.asyncio
async def test_reminder_delete_success_text(monkeypatch):
    # Ensure delete path yields the updated success message
    from database import db as _dbm
    db = RemindersDB(_dbm)
    h = ReminderHandlers(db, ReminderValidator())

    # Monkeypatch delete_reminder to return True without DB
    monkeypatch.setattr(h.db, "delete_reminder", lambda user_id, rid: True, raising=True)

    upd = _Update()
    ctx = types.SimpleNamespace(job_queue=_JobQ())
    store = []
    upd.callback_query = _CQ("confirm_del_abc", store)
    await h.reminder_callback(upd, ctx)

    assert any("התזכורת נמחקה" in m[0] and "✅" in m[0] for m in store)
