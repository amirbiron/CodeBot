"""סיום ההתחברות ל-Drive בבוט: "✅ הושלם" רק כשהטוקנים באמת נשמרו.

שלושה מסלולים מסיימים התחברות ב-Device Flow בתפריט (``handlers/drive/menu.py``): הבדיקה ברקע (``_poll_once``), הכפתור "🔄 בדוק חיבור" (``drive_poll_once``), והדבקת קוד (``handle_text``). ``gdrive.save_tokens`` לא זורק בכשל מסד — הוא מחזיר ``False`` (``Repository.save_drive_tokens``) — ושני המסלולים הראשונים לא בדקו את הערך: הם הודיעו "✅ חיבור ל‑Drive הושלם!" ועצרו את הבדיקה גם כשהשמירה נכשלה. המסלול השלישי שמר כטוקנים גם תשובת שגיאה של גוגל (``{"error": "access_denied"}``) והודיע "✅" עליה. והבדיקה ברקע התעלמה משגיאה סופית של גוגל — המשיכה לבדוק עד שתוקף הבקשה פג, בלי לומר כלום. ושני המסלולים הידניים הציגו שגיאה סופית בלי לסגור את הבקשה, והדבקת קוד לא סגרה אותה גם כשהטוקנים התקבלו: הבדיקה ברקע נשארה מתוזמנת, ובסבב הבא פנתה שוב לגוגל עם הקוד הסגור.

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
        self.markups = []
        self.message = types.SimpleNamespace(chat_id=USER_ID, message_id=1)
        self.from_user = types.SimpleNamespace(id=USER_ID)

    async def answer(self, *a, **k):
        return None

    async def edit_message_text(self, text, **kwargs):
        self.edits.append(text)
        self.markups.append(kwargs.get("reply_markup"))


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
        self.markups = []

    async def edit_message_text(self, chat_id=None, message_id=None, text=None, **kwargs):
        self.edits.append(text)
        self.markups.append(kwargs.get("reply_markup"))


def _context(job_queue):
    return types.SimpleNamespace(user_data={}, bot_data={}, application=types.SimpleNamespace(job_queue=job_queue))


def _job_context(job, bot, context):
    """ההקשר שה-job מקבל. ``bot_data`` שלו הוא אותו מילון כמו בהקשר של הכפתורים — ``application.bot_data`` (python-telegram-bot 22.5, ``CallbackContext.bot_data``)."""
    return types.SimpleNamespace(job=job, bot=bot, bot_data=context.bot_data)


def _update(query):
    return types.SimpleNamespace(callback_query=query, effective_user=types.SimpleNamespace(id=USER_ID))


def _buttons(markup):
    return [button.callback_data for row in markup.inline_keyboard for button in row]


def _registered_background_check(context):
    """בדיקה ברקע שרשומה למשתמש, כמו ש-"התחבר ל‑Drive" רושם אותה ב-``drive_auth_jobs``."""
    job = types.SimpleNamespace(removed=False)
    job.schedule_removal = lambda: setattr(job, "removed", True)
    context.bot_data.setdefault("drive_auth_jobs", {})[USER_ID] = job
    return job


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
    context = _context(queue)
    await handler.handle_callback(types.SimpleNamespace(callback_query=_Query("drive_auth"), effective_user=types.SimpleNamespace(id=USER_ID)), context)
    (poll_once, job), = queue.callbacks
    bot = _Bot()
    saves.result = False

    await poll_once(_job_context(job, bot, context))

    assert saves.calls == [(USER_ID, TOKENS, "bot")]
    assert bot.edits == [dm._AUTH_NOT_SAVED_TEXT]
    # ה-device code נוצל, ולכן הבדיקה ברקע נעצרת גם בכשל
    assert job.removed is True


async def test_background_poll_reports_success_when_the_tokens_were_saved(monkeypatch, saves):
    monkeypatch.setattr(dm.gdrive, "start_device_authorization", lambda uid: {"device_code": "dc-1", "user_code": "ABCD", "verification_url": "https://www.google.com/device", "interval": 5, "expires_in": 1800})
    monkeypatch.setattr(dm.gdrive, "poll_device_token", lambda dc: dict(TOKENS))
    handler = GoogleDriveMenuHandler()
    queue = _JobQueue()
    context = _context(queue)
    await handler.handle_callback(types.SimpleNamespace(callback_query=_Query("drive_auth"), effective_user=types.SimpleNamespace(id=USER_ID)), context)
    (poll_once, job), = queue.callbacks
    bot = _Bot()

    await poll_once(_job_context(job, bot, context))

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
    ctx = types.SimpleNamespace(user_data={"waiting_for_drive_code": True}, bot_data={})

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
    await poll_once(_job_context(job, bot, context))
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
    assert _buttons(bot.markups[0]) == ["drive_auth"]
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


# --- סגירת הבקשה בכל המסלולים (``_close_auth_request``) ---

DENIED = {"error": "access_denied", "error_description": "The user denied the request."}


async def test_a_final_google_error_on_check_connection_stops_the_background_check(monkeypatch, saves):
    """על "🔄 בדוק חיבור" שגיאה סופית מגוגל הוצגה בלי לסגור את הבקשה: ה-job נשאר מתוזמן וה-device code נשאר בסשן, ולכן בסבב הבא הבדיקה ברקע פנתה שוב לגוגל עם הקוד הסגור — בניגוד ל-RFC 8628 §3.5. וגם הכפתור "בדוק חיבור", שהוצג עם השגיאה, הזמין עוד פנייה כזו."""
    polls = []

    def _poll(dc):
        polls.append(dc)
        return dict(DENIED)

    monkeypatch.setattr(dm.gdrive, "start_device_authorization", lambda uid: dict(DEVICE_FLOW))
    monkeypatch.setattr(dm.gdrive, "poll_device_token", _poll)
    handler = GoogleDriveMenuHandler()
    queue = _JobQueue()
    context = _context(queue)
    await handler.handle_callback(_update(_Query("drive_auth")), context)
    (poll_once, job), = queue.callbacks
    query = _Query("drive_poll_once")

    await handler.handle_callback(_update(query), context)
    # כמו ב-JobQueue של python-telegram-bot: job שהוסר לא רץ שוב (``Job.schedule_removal``)
    if not job.removed:
        await poll_once(_job_context(job, _Bot(), context))

    assert polls == ["dc-1"]
    assert job.removed is True
    assert "device_code" not in handler._session(USER_ID)
    assert USER_ID not in context.bot_data["drive_auth_jobs"]
    assert query.edits == [dm._auth_error_text(DENIED)]
    assert _buttons(query.markups[-1]) == ["drive_auth"]
    assert saves.calls == []


async def test_a_temporary_google_error_on_check_connection_keeps_the_request_open(monkeypatch, saves):
    """בקרה לטסט שמעליו: תשובת שגיאה בלי קוד של OAuth (``http_503``) אינה הכרעה של גוגל. הבקשה נשארת פתוחה, הבדיקה ברקע ממשיכה, ו"בדוק חיבור" נשאר."""
    monkeypatch.setattr(dm.gdrive, "poll_device_token", lambda dc: {"error": "http_503", "error_description": "token endpoint error"})
    handler = GoogleDriveMenuHandler()
    handler._session(USER_ID)["device_code"] = "dc-1"
    context = _context(_JobQueue())
    background = _registered_background_check(context)
    query = _Query("drive_poll_once")

    await handler.handle_callback(_update(query), context)

    assert background.removed is False
    assert handler._session(USER_ID)["device_code"] == "dc-1"
    assert context.bot_data["drive_auth_jobs"][USER_ID] is background
    assert _buttons(query.markups[-1]) == ["drive_poll_once", "drive_cancel_auth"]


def _pasted_code_update(replies):
    async def _reply(text, **kwargs):
        replies.append(text)

    return types.SimpleNamespace(message=types.SimpleNamespace(text="ABCD-EFGH", reply_text=_reply), effective_user=types.SimpleNamespace(id=USER_ID))


async def test_pasting_the_code_closes_the_request_on_a_final_google_error(monkeypatch, saves):
    monkeypatch.setattr(dm.gdrive, "poll_device_token", lambda dc: dict(DENIED))
    handler = GoogleDriveMenuHandler()
    handler._session(USER_ID)["device_code"] = "dc-1"
    context = types.SimpleNamespace(user_data={"waiting_for_drive_code": True}, bot_data={})
    background = _registered_background_check(context)
    replies = []

    assert await handler.handle_text(_pasted_code_update(replies), context) is True

    assert background.removed is True
    assert "device_code" not in handler._session(USER_ID)
    assert USER_ID not in context.bot_data["drive_auth_jobs"]
    assert replies == [dm._auth_error_text(DENIED)]


@pytest.mark.parametrize("saved", [True, False])
async def test_pasting_the_code_closes_the_request_once_the_tokens_arrive(monkeypatch, saves, saved):
    """ה-device code נוצל ברגע שהטוקנים התקבלו, ולכן הבקשה נסגרת גם כשהשמירה נכשלה. עד היום הבדיקה ברקע המשיכה, ובסבב הבא פנתה לגוגל עם קוד שכבר נוצל."""
    monkeypatch.setattr(dm.gdrive, "poll_device_token", lambda dc: dict(TOKENS))
    saves.result = saved
    handler = GoogleDriveMenuHandler()
    handler._session(USER_ID)["device_code"] = "dc-1"
    context = types.SimpleNamespace(user_data={"waiting_for_drive_code": True}, bot_data={})
    background = _registered_background_check(context)
    replies = []

    assert await handler.handle_text(_pasted_code_update(replies), context) is True

    assert background.removed is True
    assert "device_code" not in handler._session(USER_ID)
    assert USER_ID not in context.bot_data["drive_auth_jobs"]
    assert len(replies) == 1 and replies[0].startswith("✅") is saved


async def test_an_expired_request_stops_the_background_check_without_calling_google(monkeypatch, saves):
    polls = []
    monkeypatch.setattr(dm.gdrive, "start_device_authorization", lambda uid: dict(DEVICE_FLOW))
    monkeypatch.setattr(dm.gdrive, "poll_device_token", lambda dc: polls.append(dc))
    handler = GoogleDriveMenuHandler()
    queue = _JobQueue()
    context = _context(queue)
    await handler.handle_callback(_update(_Query("drive_auth")), context)
    (poll_once, job), = queue.callbacks
    handler._session(USER_ID)["auth_expires_at"] = 1
    bot = _Bot()

    await poll_once(_job_context(job, bot, context))

    assert polls == []
    assert job.removed is True
    assert "device_code" not in handler._session(USER_ID)
    assert USER_ID not in context.bot_data["drive_auth_jobs"]
    assert len(bot.edits) == 1 and bot.edits[0].startswith("⌛")


async def test_cancel_closes_the_request(monkeypatch, saves):
    handler = GoogleDriveMenuHandler()
    handler._session(USER_ID)["device_code"] = "dc-1"
    context = _context(_JobQueue())
    background = _registered_background_check(context)

    await handler.handle_callback(_update(_Query("drive_cancel_auth")), context)

    assert background.removed is True
    assert "device_code" not in handler._session(USER_ID)
    assert USER_ID not in context.bot_data["drive_auth_jobs"]


async def test_connecting_again_stops_the_previous_background_check(monkeypatch, saves):
    codes = iter(["dc-1", "dc-2"])
    monkeypatch.setattr(dm.gdrive, "start_device_authorization", lambda uid: {**DEVICE_FLOW, "device_code": next(codes)})
    handler = GoogleDriveMenuHandler()
    queue = _JobQueue()
    context = _context(queue)

    await handler.handle_callback(_update(_Query("drive_auth")), context)
    await handler.handle_callback(_update(_Query("drive_auth")), context)

    (_, first), (_, second) = queue.callbacks
    assert first.removed is True and second.removed is False
    assert context.bot_data["drive_auth_jobs"][USER_ID] is second
    assert handler._session(USER_ID)["device_code"] == "dc-2"
