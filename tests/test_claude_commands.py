"""בדיקות ל-claude_task_handlers.py — שער הכניסה של ‎/claude‎.

הדגש כאן הוא אבטחה: אדמין בלבד, צ'אט פרטי בלבד, ואי אפשר לפתוח שני Issues
מאותה בקשה. ה-stubs ידניים לפי מוסכמת הריפו (ראו tests/test_chatops_mvp.py).
"""

import types

import pytest

import claude_task_handlers as handlers
from services import claude_tasks_store as store
from tests.test_claude_tasks_store import _FakeDBManager


# ── stubs ──────────────────────────────────────────────────────────────────

class _Msg:
    def __init__(self, message_id=10):
        self.message_id = message_id
        self.texts = []
        self.markups = []

    async def reply_text(self, text, *a, **k):
        self.texts.append(text)
        self.markups.append(k.get("reply_markup"))
        return types.SimpleNamespace(message_id=self.message_id + 1)


class _Update:
    def __init__(self, user_id=1, chat_type="private"):
        self.message = _Msg()
        self.effective_message = self.message
        self.effective_user = types.SimpleNamespace(id=user_id)
        self.effective_chat = types.SimpleNamespace(id=user_id, type=chat_type)
        self.callback_query = None


class _Query:
    def __init__(self, data, user_id=1):
        self.data = data
        self.from_user = types.SimpleNamespace(id=user_id)
        self.answers = []
        self.edits = []

    async def answer(self, text=None, **k):
        self.answers.append(text)

    async def edit_message_text(self, text, **k):
        self.edits.append(text)


class _CallbackUpdate:
    def __init__(self, data, user_id=1):
        self.callback_query = _Query(data, user_id)
        self.message = None
        self.effective_message = None
        self.effective_user = types.SimpleNamespace(id=user_id)
        self.effective_chat = types.SimpleNamespace(id=user_id, type="private")


class _Context:
    def __init__(self):
        self.args = []
        self.user_data = {}
        self.scheduled = []
        job_queue = types.SimpleNamespace(
            run_once=lambda cb, **k: self.scheduled.append(k.get("name"))
        )
        self.application = types.SimpleNamespace(job_queue=job_queue)
        self.bot = types.SimpleNamespace(send_message=self._send)
        self.sent = []

    async def _send(self, **kwargs):
        self.sent.append(kwargs)


# ── fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def db(monkeypatch):
    """מפנה את החנות ל-fake DB במקום ל-Mongo אמיתי."""
    fake = _FakeDBManager()
    real_collection = store._collection

    def patched(db_manager=None):
        return real_collection(fake)

    monkeypatch.setattr(store, "_collection", patched)
    return fake


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("ADMIN_USER_IDS", "1")
    monkeypatch.delenv("CHATOPS_ALLOW_ALL_IF_NO_ADMINS", raising=False)
    monkeypatch.setenv("CLAUDE_DISPATCH_ENABLED", "true")
    monkeypatch.setenv("CLAUDE_DISPATCH_REPO", "owner/repo")
    monkeypatch.setenv("CLAUDE_DISPATCH_TOKEN", "ghp_test")
    # ה-cooldown של limit_sensitive הוא singleton משותף — מאפסים בין טסטים
    from chatops import ratelimit

    ratelimit.sensitive_limiter._last_call_ts.clear()


@pytest.fixture
def no_dispatch(monkeypatch):
    """מונע כל קריאת רשת ומתעד את הקריאות ל-dispatch."""
    calls = []

    async def fake_dispatch(**kwargs):
        calls.append(kwargs)
        return {"success": True, "issue_number": 77, "issue_url": "https://gh/77"}

    monkeypatch.setattr(handlers.dispatch, "dispatch_claude_task", fake_dispatch)
    return calls


# ── בקרת גישה ──────────────────────────────────────────────────────────────

class TestAccessControl:
    @pytest.mark.asyncio
    async def test_non_admin_is_blocked(self, db, no_dispatch):
        update, context = _Update(user_id=999), _Context()
        context.args = ["תקן", "את", "הבאג", "בשמירה"]
        await handlers.claude_command(update, context)
        assert "מנהלים בלבד" in update.message.texts[0]
        assert no_dispatch == []

    @pytest.mark.asyncio
    async def test_empty_admin_list_blocks_even_with_allow_all_flag(
        self, db, no_dispatch, monkeypatch
    ):
        """הרגרסיה החשובה: ‎CHATOPS_ALLOW_ALL_IF_NO_ADMINS‎ לא פותח את /claude לכולם."""
        monkeypatch.setenv("ADMIN_USER_IDS", "")
        monkeypatch.setenv("CHATOPS_ALLOW_ALL_IF_NO_ADMINS", "1")
        update, context = _Update(user_id=12345), _Context()
        context.args = ["תקן", "את", "הבאג", "בשמירה"]
        await handlers.claude_command(update, context)
        assert "ADMIN_USER_IDS" in update.message.texts[0]
        assert no_dispatch == []

    @pytest.mark.asyncio
    async def test_group_chat_is_blocked(self, db, no_dispatch):
        update = _Update(user_id=1, chat_type="supergroup")
        context = _Context()
        context.args = ["תקן", "את", "הבאג", "בשמירה"]
        await handlers.claude_command(update, context)
        assert "פרטי בלבד" in update.message.texts[0]
        assert no_dispatch == []

    @pytest.mark.asyncio
    async def test_feature_flag_off_blocks(self, db, no_dispatch, monkeypatch):
        monkeypatch.setenv("CLAUDE_DISPATCH_ENABLED", "false")
        update, context = _Update(), _Context()
        context.args = ["תקן", "את", "הבאג", "בשמירה"]
        await handlers.claude_command(update, context)
        assert "כבוי" in update.message.texts[0]
        assert no_dispatch == []


# ── /claude ────────────────────────────────────────────────────────────────

class TestClaudeCommand:
    @pytest.mark.asyncio
    async def test_no_args_shows_usage(self, db, no_dispatch):
        update, context = _Update(), _Context()
        await handlers.claude_command(update, context)
        assert "לא נשלח טקסט" in update.message.texts[0]
        assert no_dispatch == []

    @pytest.mark.asyncio
    async def test_preview_is_shown_and_nothing_dispatched_yet(self, db, no_dispatch):
        update, context = _Update(), _Context()
        context.args = ["תקן", "את", "הבאג", "בשמירת", "קבצים"]
        await handlers.claude_command(update, context)

        assert "לאשר?" in update.message.texts[0]
        assert update.message.markups[0]["inline_keyboard"]
        assert no_dispatch == []
        # נשמרה בקשה ממתינה
        tasks = store._collection().docs
        assert len(tasks) == 1
        assert tasks[0]["status"] == "pending_confirm"

    @pytest.mark.asyncio
    async def test_secret_in_prompt_is_refused(self, db, no_dispatch):
        update, context = _Update(), _Context()
        context.args = ["תקן", "עם", "הטוקן", "ghp_" + "a" * 30]
        await handlers.claude_command(update, context)
        assert "סוד" in update.message.texts[0]
        assert no_dispatch == []

    @pytest.mark.asyncio
    async def test_daily_quota_blocks(self, db, no_dispatch, monkeypatch):
        monkeypatch.setenv("CLAUDE_MAX_TASKS_PER_DAY", "1")
        store.create_task(
            request_id="old",
            user_id=1,
            chat_id=1,
            message_id=1,
            prompt="קודמת",
            repo="owner/repo",
            status="dispatched",
        )
        update, context = _Update(), _Context()
        context.args = ["תקן", "את", "הבאג", "בשמירה"]
        await handlers.claude_command(update, context)
        assert "מכסה היומית" in update.message.texts[0]

    @pytest.mark.asyncio
    async def test_too_many_active_tasks_blocks(self, db, no_dispatch):
        for i in range(3):
            store.create_task(
                request_id=f"a{i}",
                user_id=1,
                chat_id=1,
                message_id=1,
                prompt="פעילה",
                repo="owner/repo",
                status="running",
            )
        update, context = _Update(), _Context()
        context.args = ["תקן", "את", "הבאג", "בשמירה"]
        await handlers.claude_command(update, context)
        assert "3 משימות פעילות" in update.message.texts[0]


# ── אישור בכפתור ───────────────────────────────────────────────────────────

class TestConfirmationCallback:
    def _pending(self, request_id="rid1", user_id=1):
        store.create_task(
            request_id=request_id,
            user_id=user_id,
            chat_id=user_id,
            message_id=10,
            prompt="תקן את הבאג",
            repo="owner/repo",
        )

    @pytest.mark.asyncio
    async def test_approve_dispatches_once(self, db, no_dispatch):
        self._pending()
        context = _Context()
        update = _CallbackUpdate("claude_ok:rid1")
        await handlers.claude_callback(update, context)

        assert len(no_dispatch) == 1
        task = store.get_by_request_id("rid1")
        assert task["status"] == "dispatched"
        assert task["issue_number"] == 77
        assert context.scheduled == ["claude_wd_rid1"]

    @pytest.mark.asyncio
    async def test_double_click_does_not_dispatch_twice(self, db, no_dispatch):
        self._pending()
        context = _Context()
        await handlers.claude_callback(_CallbackUpdate("claude_ok:rid1"), context)
        second = _CallbackUpdate("claude_ok:rid1")
        await handlers.claude_callback(second, context)

        assert len(no_dispatch) == 1
        assert "כבר טופלה" in (second.callback_query.answers[0] or "")

    @pytest.mark.asyncio
    async def test_other_users_request_is_rejected(self, db, no_dispatch, monkeypatch):
        monkeypatch.setenv("ADMIN_USER_IDS", "1,2")
        self._pending(user_id=2)
        update = _CallbackUpdate("claude_ok:rid1", user_id=1)
        await handlers.claude_callback(update, _Context())
        assert "משתמש אחר" in (update.callback_query.answers[0] or "")
        assert no_dispatch == []

    @pytest.mark.asyncio
    async def test_non_admin_callback_is_rejected(self, db, no_dispatch):
        self._pending()
        update = _CallbackUpdate("claude_ok:rid1", user_id=999)
        await handlers.claude_callback(update, _Context())
        assert "מנהלים בלבד" in (update.callback_query.answers[0] or "")
        assert no_dispatch == []

    @pytest.mark.asyncio
    async def test_unknown_request_id(self, db, no_dispatch):
        update = _CallbackUpdate("claude_ok:nope")
        await handlers.claude_callback(update, _Context())
        assert "כבר לא זמינה" in (update.callback_query.answers[0] or "")
        assert no_dispatch == []

    @pytest.mark.asyncio
    async def test_cancel_marks_task_cancelled(self, db, no_dispatch):
        self._pending()
        update = _CallbackUpdate("claude_no:rid1")
        await handlers.claude_callback(update, _Context())
        assert store.get_by_request_id("rid1")["status"] == "cancelled"
        assert no_dispatch == []

    @pytest.mark.asyncio
    async def test_failed_dispatch_marks_failed(self, db, monkeypatch):
        self._pending()

        async def failing(**kwargs):
            return {"success": False, "error": "GitHub אמר לא"}

        monkeypatch.setattr(handlers.dispatch, "dispatch_claude_task", failing)
        update = _CallbackUpdate("claude_ok:rid1")
        context = _Context()
        await handlers.claude_callback(update, context)

        task = store.get_by_request_id("rid1")
        assert task["status"] == "failed"
        assert "GitHub אמר לא" in task["error"]
        assert context.scheduled == []  # אין טעם ב-watchdog כשלא נפתח Issue


# ── watchdog ───────────────────────────────────────────────────────────────

class TestWatchdog:
    def _dispatched(self):
        store.create_task(
            request_id="rid1",
            user_id=1,
            chat_id=1,
            message_id=10,
            prompt="משימה",
            repo="owner/repo",
        )
        store.update_task("rid1", {"status": "dispatched", "issue_number": 77})

    @pytest.mark.asyncio
    async def test_warns_when_no_run_found(self, db, monkeypatch):
        self._dispatched()

        async def no_run(_issue):
            return None

        monkeypatch.setattr(handlers.dispatch, "find_workflow_run_for_issue", no_run)
        context = _Context()
        context.job = types.SimpleNamespace(data={"request_id": "rid1"})
        await handlers._claude_watchdog(context)

        assert store.get_by_request_id("rid1")["status"] == "timeout"
        assert "לא זוהתה ריצה" in context.sent[0]["text"]

    @pytest.mark.asyncio
    async def test_marks_running_when_run_found(self, db, monkeypatch):
        self._dispatched()

        async def found(_issue):
            return {"run_id": 5, "run_url": "https://gh/run/5"}

        monkeypatch.setattr(handlers.dispatch, "find_workflow_run_for_issue", found)
        context = _Context()
        context.job = types.SimpleNamespace(data={"request_id": "rid1"})
        await handlers._claude_watchdog(context)

        task = store.get_by_request_id("rid1")
        assert task["status"] == "running"
        assert task["run_url"] == "https://gh/run/5"
        assert context.sent == []  # אין למה להטריד את המשתמש

    @pytest.mark.asyncio
    async def test_silent_when_task_already_progressed(self, db, monkeypatch):
        self._dispatched()
        store.update_task("rid1", {"status": "completed"})
        context = _Context()
        context.job = types.SimpleNamespace(data={"request_id": "rid1"})
        await handlers._claude_watchdog(context)
        assert context.sent == []


# ── פקודות מידע ────────────────────────────────────────────────────────────

class TestStatusAndCancel:
    @pytest.mark.asyncio
    async def test_status_without_tasks(self, db):
        update, context = _Update(), _Context()
        await handlers.claude_status_command(update, context)
        assert "לא נמצאה משימה" in update.message.texts[0]

    @pytest.mark.asyncio
    async def test_tasks_list_without_tasks(self, db):
        update, context = _Update(), _Context()
        await handlers.claude_tasks_command(update, context)
        assert "אין עדיין משימות" in update.message.texts[0]

    @pytest.mark.asyncio
    async def test_status_shows_issue(self, db, monkeypatch):
        store.create_task(
            request_id="rid1",
            user_id=1,
            chat_id=1,
            message_id=1,
            prompt="תקן את הבאג",
            repo="owner/repo",
        )
        store.update_task(
            "rid1", {"status": "running", "issue_number": 77, "issue_url": "https://gh/77"}
        )

        async def no_pr(_issue):
            return None

        monkeypatch.setattr(handlers.dispatch, "find_pr_for_issue", no_pr)
        update, context = _Update(), _Context()
        await handlers.claude_status_command(update, context)
        assert "#77" in update.message.texts[0]

    @pytest.mark.asyncio
    async def test_cancel_closes_issue(self, db, monkeypatch):
        store.create_task(
            request_id="rid1",
            user_id=1,
            chat_id=1,
            message_id=1,
            prompt="תקן את הבאג",
            repo="owner/repo",
        )
        store.update_task("rid1", {"status": "running", "issue_number": 77})

        async def ok(_issue):
            return {"success": True}

        monkeypatch.setattr(handlers.dispatch, "cancel_claude_task", ok)
        update, context = _Update(), _Context()
        await handlers.claude_cancel_command(update, context)

        assert "נסגר" in update.message.texts[0]
        assert store.get_by_request_id("rid1")["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_without_task(self, db):
        update, context = _Update(), _Context()
        await handlers.claude_cancel_command(update, context)
        assert "לא נמצאה משימה" in update.message.texts[0]


# ── רישום ──────────────────────────────────────────────────────────────────

def test_setup_registers_all_handlers():
    class _App:
        def __init__(self):
            self.handlers = []

        def add_handler(self, handler, *a, **k):
            self.handlers.append(handler)

    app = _App()
    handlers.setup_claude_handlers(app)
    commands = {
        cmd
        for handler in app.handlers
        for cmd in (getattr(handler, "commands", None) or set())
    }
    assert {"claude", "claude_status", "claude_tasks", "claude_cancel"} <= commands
    assert len(app.handlers) == 5  # 4 פקודות + callback
