"""סיום ההתחברות ל-Drive בבוט: "✅ הושלם" רק כשהטוקנים באמת נשמרו.

שלושה מסלולים מסיימים התחברות ב-Device Flow בתפריט (``handlers/drive/menu.py``): הבדיקה ברקע (``_poll_once``), הכפתור "🔄 בדוק חיבור" (``drive_poll_once``), והדבקת קוד (``handle_text``). ``gdrive.save_tokens`` לא זורק בכשל מסד — הוא מחזיר ``False`` (``Repository.save_drive_tokens``) — ושני המסלולים הראשונים לא בדקו את הערך: הם הודיעו "✅ חיבור ל‑Drive הושלם!" ועצרו את הבדיקה גם כשהשמירה נכשלה. המסלול השלישי שמר כטוקנים גם תשובת שגיאה של גוגל (``{"error": "access_denied"}``) והודיע "✅" עליה. והבדיקה ברקע התעלמה משגיאה סופית של גוגל — המשיכה לבדוק עד שתוקף הבקשה פג, בלי לומר כלום.

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


DEVICE_FLOW = {"device_code": "dc-1", "user_code": "ABCD", "verification_url": "https://www.google.com/device", "interval": 5, "expires_in": 1800}


async def _background_poll_once(monkeypatch, poll_result):
    """מתחיל התחברות בתפריט האמיתי, ומריץ סבב אחד של הבדיקה ברקע מול תשובה נתונה של גוגל."""
    monkeypatch.setattr(dm.gdrive, "start_device_authorization", lambda uid: dict(DEVICE_FLOW))
    monkeypatch.setattr(dm.gdrive, "poll_device_token", lambda dc: dict(poll_result))
    handler = GoogleDriveMenuHandler()
    queue = _JobQueue()
    context = _context(queue)
    await handler.handle_callback(types.SimpleNamespace(callback_query=_Query("drive_auth"), effective_user=types.SimpleNamespace(id=USER_ID)), context)
    (poll_once, job), = queue.callbacks
    bot = _Bot()
    await poll_once(types.SimpleNamespace(job=job, bot=bot, bot_data={}))
    return handler, context, job, bot


async def test_a_final_google_error_stops_the_background_check_and_shows_the_error(monkeypatch, saves):
    """RFC 8628 §3.5: על קוד שגיאה של OAuth שאינו ``authorization_pending`` / ``slow_down`` הלקוח *"MUST stop polling"*. הבדיקה ברקע התעלמה מתשובה כזו והמשיכה לפנות לגוגל עד שתוקף הבקשה פג — ואז הודיעה "פג תוקף" על בקשה שהמשתמש סירב לה."""
    denied = {"error": "access_denied", "error_description": "The user denied the request."}

    handler, context, job, bot = await _background_poll_once(monkeypatch, denied)

    assert job.removed is True
    assert "device_code" not in handler._session(USER_ID)
    assert USER_ID not in context.bot_data["drive_auth_jobs"]
    assert bot.edits == [dm._auth_error_text(denied)]
    assert bot.edits[0].startswith("❌ שגיאה: access_denied")
    assert saves.calls == []


async def test_a_temporary_google_error_keeps_the_background_check_running(monkeypatch, saves):
    """תשובת שגיאה בלי קוד של OAuth (``poll_device_token`` מסמן אותה ``http_<status>``) אינה הכרעה של גוגל: הבדיקה ממשיכה ושום דבר לא נסגר. בקרה לטסט שמעליו — מגינה מפני עצירה על כל שגיאה."""
    handler, context, job, bot = await _background_poll_once(monkeypatch, {"error": "http_503", "error_description": "token endpoint error"})

    assert job.removed is False
    assert handler._session(USER_ID).get("device_code") == "dc-1"
    assert context.bot_data["drive_auth_jobs"].get(USER_ID) is job
    assert bot.edits == []
    assert saves.calls == []


@pytest.mark.parametrize(
    "result, closes",
    [
        (None, False),
        ({}, False),
        ({"error": None}, False),
        ({"error": ["access_denied"]}, False),
        ({"error": "authorization_pending"}, False),
        ({"error": "slow_down"}, False),
        ({"error": "http_503", "error_description": "token endpoint error"}, False),
        ({"error": "access_denied"}, True),
        ({"error": "expired_token"}, True),
        ({"error": "invalid_grant"}, True),
        ({"error": "unsupported_grant_type"}, True),
    ],
)
def test_only_an_oauth_error_other_than_pending_or_slow_down_closes_the_request(result, closes):
    """RFC 8628 §3.5: ``authorization_pending`` ו-``slow_down`` אומרים להמשיך לבדוק, וכל קוד שגיאה אחר של OAuth סוגר את הבקשה. ערך שאינו מחרוזת אינו קוד."""
    assert dm.gdrive.is_terminal_device_flow_error(result) is closes
