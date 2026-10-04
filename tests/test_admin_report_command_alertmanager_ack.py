import types
import pytest


@pytest.mark.asyncio
async def test_admin_report_ack_only_on_alertmanager_success(monkeypatch):
    import main as main_mod

    class Msg:
        def __init__(self):
            self.replies = []

        async def reply_text(self, text):
            self.replies.append(text)

    msg = Msg()
    upd = types.SimpleNamespace(
        message=msg,
        effective_message=msg,
        effective_user=types.SimpleNamespace(id=123, username="alice", full_name="Alice"),
    )
    ctx = types.SimpleNamespace(args=["יש", "בעיה"])

    async def _am_ok(*_a, **_k):
        return True

    async def _direct_should_not_run(*_a, **_k):
        raise AssertionError("_send_direct_admins should not be called when Alertmanager succeeds")

    monkeypatch.setattr(main_mod, "_send_admin_report_via_alertmanager", _am_ok)
    monkeypatch.setattr(main_mod, "_send_direct_admins", _direct_should_not_run)

    await main_mod.admin_report_command(upd, ctx)
    assert msg.replies and msg.replies[-1] == "תודה! הדיווח נשלח לאדמין."


@pytest.mark.asyncio
async def test_admin_report_fallback_message_when_alertmanager_fails(monkeypatch):
    import main as main_mod

    class Msg:
        def __init__(self):
            self.replies = []

        async def reply_text(self, text):
            self.replies.append(text)

    msg = Msg()
    upd = types.SimpleNamespace(
        message=msg,
        effective_message=msg,
        effective_user=types.SimpleNamespace(id=7, username=None, full_name="Bob"),
    )
    ctx = types.SimpleNamespace(args=["הודעה"])

    async def _am_fail(*_a, **_k):
        return False

    async def _direct_ok(*_a, **_k):
        return True

    monkeypatch.setattr(main_mod, "_send_admin_report_via_alertmanager", _am_fail)
    monkeypatch.setattr(main_mod, "_send_direct_admins", _direct_ok)

    await main_mod.admin_report_command(upd, ctx)
    assert msg.replies
    assert "Alertmanager לא זמין" in msg.replies[-1]


@pytest.mark.asyncio
async def test_admin_report_failure_when_both_paths_fail(monkeypatch):
    import main as main_mod

    class Msg:
        def __init__(self):
            self.replies = []

        async def reply_text(self, text):
            self.replies.append(text)

    msg = Msg()
    upd = types.SimpleNamespace(
        message=msg,
        effective_message=msg,
        effective_user=types.SimpleNamespace(id=7, username="u", full_name="U"),
    )
    ctx = types.SimpleNamespace(args=["הודעה"])

    async def _am_fail(*_a, **_k):
        return False

    async def _direct_fail(*_a, **_k):
        return False

    monkeypatch.setattr(main_mod, "_send_admin_report_via_alertmanager", _am_fail)
    monkeypatch.setattr(main_mod, "_send_direct_admins", _direct_fail)

    await main_mod.admin_report_command(upd, ctx)
    assert msg.replies and msg.replies[-1] == "לא הצלחתי לשלוח את הדיווח כרגע."

