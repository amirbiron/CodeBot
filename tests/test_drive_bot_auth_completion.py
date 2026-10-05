"""סיום ההתחברות ל-Drive בבוט: "✅ הושלם" רק כשהטוקנים באמת נשמרו.

שלושה מסלולים מסיימים התחברות ב-Device Flow בתפריט (``handlers/drive/menu.py``): הבדיקה ברקע (``_poll_once``), הכפתור "🔄 בדוק חיבור" (``drive_poll_once``), והדבקת קוד (``handle_text``). ``gdrive.save_tokens`` לא זורק בכשל מסד — הוא מחזיר ``False`` (``Repository.save_drive_tokens``) — ושני המסלולים הראשונים לא בדקו את הערך: הם הודיעו "✅ חיבור ל‑Drive הושלם!" ועצרו את הבדיקה גם כשהשמירה נכשלה. המסלול השלישי שמר כטוקנים גם תשובת שגיאה של גוגל (``{"error": "access_denied"}``) והודיע "✅" עליה.

התפריט אמיתי; גוגל והשמירה מוחלפים בדמויות.
"""

from __future__ import annotations

import types

import pytest

import handlers.drive.menu as dm
from handlers.drive.menu import GoogleDriveMenuHandler

USER_ID = 111
TOKENS = {"access_token": "ya29.bot-access", "refresh_token": "1//bot-refresh", "expires_in": 3599}
SUCCESS_TEXT = "✅ חיבור ל‑Drive הושלם!"


class _Query:
    def __init__(self, data):
        self.data = data
        self.edits = []
        self.message = types.SimpleNamespace(chat_id=USER_ID, message_id=1)
        self.from_user = types.SimpleNamespace(id=USER_ID)

    async def answer(self, *a, **k):
        return None

    async def edit_message_text(self, text, **kwargs):
        self.edits.append(text)


class _JobQueue:
    def __init__(self):
        self.callbacks = []

    def run_repeating(self, callback, interval=None, first=None, name=None, data=None, **kwargs):
        job = types.SimpleNamespace(data=data, removed=False)

        def _remove():
            job.removed = True

        job.schedule_removal = _remove
        self.callbacks.append((callback, job))
        return job


class _Bot:
    def __init__(self):
        self.edits = []

    async def edit_message_text(self, chat_id=None, message_id=None, text=None, **kwargs):
        self.edits.append(text)


def _context(job_queue):
    return types.SimpleNamespace(user_data={}, bot_data={}, application=types.SimpleNamespace(job_queue=job_queue))


@pytest.fixture
def saves(monkeypatch):
    """``save_tokens`` של השירות, עם ``owner`` חובה כמו בקוד האמיתי; ``result`` קובע מה הוא מחזיר."""
    calls = []
    state = types.SimpleNamespace(calls=calls, result=True)

    def _save_tokens(user_id, tokens, *, owner):
        calls.append((user_id, dict(tokens), owner))
        return state.result

    monkeypatch.setattr(dm.gdrive, "save_tokens", _save_tokens)
    return state


async def test_background_poll_does_not_report_success_when_the_tokens_were_not_saved(monkeypatch, saves):
    monkeypatch.setattr(dm.gdrive, "start_device_authorization", lambda uid: {"device_code": "dc-1", "user_code": "ABCD", "verification_url": "https://www.google.com/device", "interval": 5, "expires_in": 1800})
    monkeypatch.setattr(dm.gdrive, "poll_device_token", lambda dc: dict(TOKENS))
    handler = GoogleDriveMenuHandler()
    queue = _JobQueue()
    await handler.handle_callback(types.SimpleNamespace(callback_query=_Query("drive_auth"), effective_user=types.SimpleNamespace(id=USER_ID)), _context(queue))
    (poll_once, job), = queue.callbacks
    bot = _Bot()
    saves.result = False

    await poll_once(types.SimpleNamespace(job=job, bot=bot, bot_data={}))

    assert saves.calls == [(USER_ID, TOKENS, "bot")]
    assert bot.edits == [dm._AUTH_NOT_SAVED_TEXT]
    # ה-device code נוצל, ולכן הבדיקה ברקע נעצרת גם בכשל
    assert job.removed is True


async def test_background_poll_reports_success_when_the_tokens_were_saved(monkeypatch, saves):
    monkeypatch.setattr(dm.gdrive, "start_device_authorization", lambda uid: {"device_code": "dc-1", "user_code": "ABCD", "verification_url": "https://www.google.com/device", "interval": 5, "expires_in": 1800})
    monkeypatch.setattr(dm.gdrive, "poll_device_token", lambda dc: dict(TOKENS))
    handler = GoogleDriveMenuHandler()
    queue = _JobQueue()
    await handler.handle_callback(types.SimpleNamespace(callback_query=_Query("drive_auth"), effective_user=types.SimpleNamespace(id=USER_ID)), _context(queue))
    (poll_once, job), = queue.callbacks
    bot = _Bot()

    await poll_once(types.SimpleNamespace(job=job, bot=bot, bot_data={}))

    assert bot.edits == [SUCCESS_TEXT]
    assert job.removed is True


async def test_check_connection_button_does_not_report_success_when_the_tokens_were_not_saved(monkeypatch, saves):
    monkeypatch.setattr(dm.gdrive, "poll_device_token", lambda dc: dict(TOKENS))
    handler = GoogleDriveMenuHandler()
    handler._session(USER_ID)["device_code"] = "dc-1"
    menu_calls = []

    async def _menu(update, context):
        menu_calls.append(True)

    monkeypatch.setattr(handler, "menu", _menu)
    background = types.SimpleNamespace(removed=False)
    background.schedule_removal = lambda: setattr(background, "removed", True)
    ctx = _context(_JobQueue())
    ctx.bot_data["drive_auth_jobs"] = {USER_ID: background}
    query = _Query("drive_poll_once")
    saves.result = False

    await handler.handle_callback(types.SimpleNamespace(callback_query=query, effective_user=types.SimpleNamespace(id=USER_ID)), ctx)

    assert query.edits == [dm._AUTH_NOT_SAVED_TEXT]
    assert SUCCESS_TEXT not in query.edits
    # לא מציגים את תפריט "מחובר" על חיבור שלא נשמר
    assert menu_calls == []
    assert background.removed is True


async def test_pasting_the_code_does_not_save_an_error_answer_from_google_as_tokens(monkeypatch, saves):
    monkeypatch.setattr(dm.gdrive, "poll_device_token", lambda dc: {"error": "access_denied", "error_description": "The user denied the request."})
    handler = GoogleDriveMenuHandler()
    handler._session(USER_ID)["device_code"] = "dc-1"
    replies = []

    async def _reply(text, **kwargs):
        replies.append(text)

    update = types.SimpleNamespace(
        message=types.SimpleNamespace(text="ABCD-EFGH", reply_text=_reply),
        effective_user=types.SimpleNamespace(id=USER_ID),
    )
    ctx = types.SimpleNamespace(user_data={"waiting_for_drive_code": True})

    assert await handler.handle_text(update, ctx) is True

    assert saves.calls == []
    assert len(replies) == 1 and replies[0].startswith("❌ שגיאה: access_denied")
