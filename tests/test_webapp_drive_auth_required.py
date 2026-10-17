"""גיבוי Drive של הוובאפ כשגוגל דוחה את החיבור: עוצרים, אומרים למשתמש, וחוזרים אחרי חיבור מחדש.

**מה נשבר.** הגיבוי המתוזמן בנה ZIP של כל הקבצים, ורק אז ניסה להעלות. כשה-refresh token מת, ההעלאה נכשלה ב-``RefreshError`` (``op=ensure_folder``), והסורק קבע ניסיון חוזר לסריקה הבאה, בלי סוף: מ-12.10.2026 נבנה גיבוי מלא כל 5 דקות ו-20 שניות בערך, ושאילתת הייצוא נרשמה ב-``slow_queries_log`` 1,237 פעמים בשבוע. מסך ההגדרות המשיך להציג "מחובר" בירוק.

**מה נבדק כאן, ולמה דרך הדלתות האלה.**

- ``check_connection`` נבדק דרך google-auth **האמיתי** (2.41.1): רק שרת הטוקנים מוחלף, ב-transport שמחזיר את התשובות שגוגל מחזיר. דמה של ``Credentials`` הייתה בודקת את הסיווג מול הנחה על הצורה של ``RefreshError``, ולא מול מה שהספרייה זורקת בפועל.
- המתזמן נבדק דרך ``_scan_drive_backups`` מעל ``_fake_mongo``, שמסנן כמו מונגו — ``{field: None}`` תואם גם שדה חסר, ו-``$ne: None`` מחריג אותו (תיעוד MongoDB, "Query for Null or Missing Fields").
- הממשק נבדק דרך נקודות הקצה ש-``settings.html`` קורא להן: ``/api/drive/status``, ``/api/drive/backup-status`` ו-``/api/drive/callback``.
"""

from __future__ import annotations

import io
import json
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from flask import Flask, session

import drive_owner
from _fake_mongo import FakeDB

USER_ID = 6060
WEB_TOKENS = {"access_token": "ya29.stale-access", "refresh_token": "1//web-refresh", "token_type": "Bearer", "expires_in": 3599}
LOGGER = "services.google_drive_service"

#: מה ששרת הטוקנים של גוגל מחזיר על refresh token שבוטל או פג (RFC 6749, סעיף 5.2).
EXPIRED_GRANT = {"error": "invalid_grant", "error_description": "Token has been expired or revoked."}


class _DBM:
    """הצורה של ``DatabaseManager`` שהקוד פונה אליה — מעל ``Repository`` אמיתי ודמות מונגו."""

    def __init__(self):
        from database.repository import Repository

        self.db = FakeDB()
        self._repo = Repository(SimpleNamespace(db=self.db))

    def __getattr__(self, name):
        if name in {"get_drive_tokens", "save_drive_tokens", "delete_drive_tokens", "get_drive_prefs", "save_drive_prefs"}:
            return getattr(self._repo, name)
        raise AttributeError(name)

    def web_prefs(self):
        return self.get_drive_prefs(USER_ID, owner=drive_owner.WEBAPP) or {}


@pytest.fixture
def dbm():
    d = _DBM()
    assert d.save_drive_tokens(USER_ID, dict(WEB_TOKENS), owner=drive_owner.WEBAPP)
    return d


# --- check_connection, דרך google-auth האמיתי ---


class _TokenEndpoint:
    """שרת הטוקנים של גוגל, כ-transport של google-auth: מקבל את הבקשה ומחזיר ``status`` ו-``data``, כמו ``google.auth.transport.Response``."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = 0

    def __call__(self, url, method="GET", body=None, headers=None, timeout=None, **_kw):
        answer = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        if isinstance(answer, BaseException):
            raise answer
        status, payload = answer
        return SimpleNamespace(status=status, headers={}, data=json.dumps(payload).encode("utf-8"))


@pytest.fixture
def token_server(dbm, monkeypatch):
    import google.auth._exponential_backoff as backoff
    import services.google_drive_service as gds

    endpoint = _TokenEndpoint((200, {"access_token": "ya29.fresh", "expires_in": 3599, "token_type": "Bearer"}))
    sleeps = []
    monkeypatch.setattr(gds, "db", dbm)
    monkeypatch.setattr(gds, "Request", lambda: endpoint)
    monkeypatch.setattr(gds.config, "GOOGLE_CLIENT_ID", "client-id", raising=False)
    monkeypatch.setattr(gds.config, "GOOGLE_CLIENT_SECRET", "client-secret", raising=False)
    # google-auth ממתין בין ניסיונות חוזרים מול שרת הטוקנים (``ExponentialBackoff``) — כאן ההמתנה רק נספרת
    monkeypatch.setattr(backoff, "time", SimpleNamespace(sleep=sleeps.append))
    return SimpleNamespace(gds=gds, endpoint=endpoint, sleeps=sleeps)


def test_a_refresh_token_google_rejects_needs_a_reconnect_and_is_not_retried(token_server, dbm, caplog):
    t = token_server
    t.endpoint.answers = [(400, dict(EXPIRED_GRANT))]

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        check = t.gds.check_connection(USER_ID, owner=drive_owner.WEBAPP)

    assert check == t.gds.ConnectionCheck(t.gds.CONNECTION_AUTH_REQUIRED, "invalid_grant")
    # invalid_grant חוזר על עצמו לכל ניסיון — google-auth לא מנסה שוב, וגם אנחנו לא
    assert t.endpoint.calls == 1
    assert dbm.get_drive_tokens(USER_ID, owner=drive_owner.WEBAPP)["access_token"] == WEB_TOKENS["access_token"]
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("drive_call_failed")]
    assert lines == [f"drive_call_failed op=check_connection.refresh owner=webapp user_id={USER_ID} error_type=RefreshError http_status=None drive_reason=None oauth_error=invalid_grant"]
    assert "Token has been expired" not in "\n".join(lines)


def test_a_working_connection_is_ok_and_the_fresh_token_is_saved(token_server, dbm):
    t = token_server

    check = t.gds.check_connection(USER_ID, owner=drive_owner.WEBAPP)

    assert check == t.gds.ConnectionCheck(t.gds.CONNECTION_OK)
    saved = dbm.get_drive_tokens(USER_ID, owner=drive_owner.WEBAPP)
    # הטוקן החדש נשמר, ולכן get_drive_service שאחרי הבדיקה בונה שירות מטוקן טרי; ה-refresh token נשמר כמו שהיה
    assert saved["access_token"] == "ya29.fresh"
    assert saved["refresh_token"] == WEB_TOKENS["refresh_token"]


def test_a_client_google_rejects_is_unknown_and_never_asks_the_user_to_reconnect(token_server):
    """``invalid_client`` הוא תקלת הגדרות (RFC 6749, סעיף 5.2): חיבור מחדש של המשתמש לא יתקן אותה, ולכן היא אינה ``CONNECTION_AUTH_REQUIRED``."""
    t = token_server
    t.endpoint.answers = [(401, {"error": "invalid_client", "error_description": "The OAuth client was not found."})]

    check = t.gds.check_connection(USER_ID, owner=drive_owner.WEBAPP)

    assert check == t.gds.ConnectionCheck(t.gds.CONNECTION_UNKNOWN, "invalid_client")


def test_a_token_server_that_is_temporarily_down_is_transient(token_server):
    t = token_server
    t.endpoint.answers = [(503, {"error": "backendError"})]

    check = t.gds.check_connection(USER_ID, owner=drive_owner.WEBAPP)

    assert check.status == t.gds.CONNECTION_TRANSIENT
    # 503 הוא retryable אצל google-auth: הוא ניסה שוב בעצמו, עם המתנה בין הניסיונות, לפני שוויתר
    assert t.endpoint.calls == 3 and len(t.sleeps) == 2


def test_a_network_failure_is_transient(token_server):
    from google.auth.exceptions import TransportError

    t = token_server
    t.endpoint.answers = [TransportError("connection reset by peer")]

    assert t.gds.check_connection(USER_ID, owner=drive_owner.WEBAPP) == t.gds.ConnectionCheck(t.gds.CONNECTION_TRANSIENT)


def test_no_stored_tokens_is_unknown_because_it_can_also_be_a_database_failure(token_server, dbm):
    """``get_drive_tokens`` מחזיר ``None`` גם בלי חיבור וגם בכשל מסד — ותקלת מסד חולפת אסור שתבקש מהמשתמש להתחבר מחדש."""
    t = token_server
    assert dbm.delete_drive_tokens(USER_ID, owner=drive_owner.WEBAPP)

    assert t.gds.check_connection(USER_ID, owner=drive_owner.WEBAPP) == t.gds.ConnectionCheck(t.gds.CONNECTION_UNKNOWN)
    assert t.endpoint.calls == 0


def test_a_connection_without_a_refresh_token_needs_a_reconnect(token_server, dbm):
    t = token_server
    assert dbm.delete_drive_tokens(USER_ID, owner=drive_owner.WEBAPP)
    assert dbm.save_drive_tokens(USER_ID, {**WEB_TOKENS, "refresh_token": ""}, owner=drive_owner.WEBAPP)

    assert t.gds.check_connection(USER_ID, owner=drive_owner.WEBAPP) == t.gds.ConnectionCheck(t.gds.CONNECTION_AUTH_REQUIRED)
    assert t.endpoint.calls == 0


def test_an_error_that_is_not_google_auth_is_not_classified(token_server):
    """באג (כאן ``KeyError`` מתוך ה-transport) אינו מצב של החיבור — הוא עולה, ולא מקבל תווית של "תקלה חולפת" או "להתחבר מחדש"."""
    t = token_server
    t.endpoint.answers = [KeyError("bug")]

    with pytest.raises(KeyError):
        t.gds.check_connection(USER_ID, owner=drive_owner.WEBAPP)


# --- המתזמן: חיבור שמת הוא מצב סופי ---


@pytest.fixture
def scheduler(dbm, monkeypatch):
    import services.google_drive_service as gds
    import services.personal_backup_service as pbs
    import webapp.backup_scheduler as bs

    calls = SimpleNamespace(checks=[], exports=[], uploads=[], events=[])
    answer = {"check": gds.ConnectionCheck(gds.CONNECTION_OK)}

    def _check(uid, *, owner):
        calls.checks.append((uid, owner))
        result = answer["check"]
        return result(uid) if callable(result) else result

    monkeypatch.setattr(gds, "check_connection", _check)
    monkeypatch.setattr(pbs.PersonalBackupService, "export_user_data", lambda self, uid: calls.exports.append(uid) or io.BytesIO(b"PK-zip"))
    monkeypatch.setattr(gds, "upload_bytes", lambda uid, filename, data, folder_id=None, sub_path=None, *, owner: calls.uploads.append(owner) or "file-id")
    monkeypatch.setattr(bs, "emit_event", lambda event, severity="info", **fields: calls.events.append((event, fields)))
    monkeypatch.setitem(__import__("sys").modules, "database", SimpleNamespace(db=dbm))

    def _due(**extra):
        due = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        assert dbm.save_drive_prefs(USER_ID, {"schedule_key": "weekly", "schedule_next_at": due, **extra}, owner=drive_owner.WEBAPP)

    def _scan():
        bs._scan_drive_backups(dbm, datetime.now(timezone.utc).isoformat())

    return SimpleNamespace(bs=bs, gds=gds, calls=calls, answer=answer, due=_due, scan=_scan)


def test_a_rejected_connection_pauses_the_schedule_without_building_a_zip(scheduler, dbm):
    s = scheduler
    s.answer["check"] = s.gds.ConnectionCheck(s.gds.CONNECTION_AUTH_REQUIRED, "invalid_grant")
    s.due()

    s.scan()

    assert s.calls.exports == [] and s.calls.uploads == []
    prefs = dbm.web_prefs()
    assert prefs["schedule_next_at"] is None
    assert prefs["schedule_key"] == "weekly"
    assert prefs["auth_required_at"]
    assert s.calls.events == [("webapp_drive_backup_failed", {"user_id": USER_ID, "reason": "auth_required", "oauth_error": "invalid_grant"})]

    # הסריקה הבאה לא תופסת אותו שוב: אין עוד ניסיון כל חמש דקות
    s.scan()
    assert len(s.calls.checks) == 1


def test_a_schedule_the_user_changed_during_the_check_is_not_paused(scheduler, dbm):
    """ההשהיה מותנית בסנטינל שהסריקה כתבה: תזמון שהמשתמש קבע בזמן שהבדיקה רצה נשאר כמו שהוא."""
    s = scheduler
    user_choice = "2099-01-01T00:00:00+00:00"

    def _user_changes_the_schedule_then_google_rejects(uid):
        dbm.db.users.update_one({"user_id": uid}, {"$set": {"webapp_drive_prefs.schedule_next_at": user_choice}})
        return s.gds.ConnectionCheck(s.gds.CONNECTION_AUTH_REQUIRED, "invalid_grant")

    s.answer["check"] = _user_changes_the_schedule_then_google_rejects
    s.due()

    s.scan()

    assert dbm.web_prefs()["schedule_next_at"] == user_choice
    assert dbm.web_prefs()["auth_required_at"]


def test_a_connection_check_that_fails_for_another_reason_is_retried_and_does_not_ask_to_reconnect(scheduler, dbm):
    s = scheduler
    s.answer["check"] = s.gds.ConnectionCheck(s.gds.CONNECTION_TRANSIENT)
    s.due()

    s.scan()

    assert s.calls.exports == []
    prefs = dbm.web_prefs()
    assert prefs["schedule_next_at"] > datetime.now(timezone.utc).isoformat()
    assert not prefs.get("auth_required_at")
    assert s.calls.events == [("webapp_drive_backup_failed", {"user_id": USER_ID, "reason": "connection_failed", "connection_status": "transient"})]


def test_a_check_that_passes_clears_an_old_reconnect_mark(scheduler, dbm):
    s = scheduler
    s.due(auth_required_at="2026-10-12T12:37:45+00:00")

    s.scan()

    assert s.calls.exports == [USER_ID] and s.calls.uploads == [drive_owner.WEBAPP]
    prefs = dbm.web_prefs()
    assert prefs["auth_required_at"] is None
    assert prefs["last_backup_at"]


def test_the_first_rejection_keeps_its_time(scheduler, dbm):
    """``auth_required_at`` הוא זמן הדחייה הראשונה: דחייה נוספת (למשל מ"גבה עכשיו") לא מזיזה אותו."""
    s = scheduler
    first = "2026-10-12T12:37:45+00:00"
    s.due(auth_required_at=first)
    s.answer["check"] = s.gds.ConnectionCheck(s.gds.CONNECTION_AUTH_REQUIRED, "invalid_grant")

    assert s.bs.trigger_drive_backup_now(USER_ID) == {"ok": False, "failure": "auth_required"}

    assert dbm.web_prefs()["auth_required_at"] == first


def _fail_writes(dbm, monkeypatch, should_fail):
    """כתיבה ל-``users`` שנכשלת בשגיאת מסד כש-``should_fail(filter, update)`` — כל השאר עובר לדמות כרגיל."""
    from pymongo.errors import AutoReconnect

    real_update_one = dbm.db.users.update_one

    def _update_one(q, u, *args, **kwargs):
        if should_fail(q, u):
            raise AutoReconnect("primary stepped down")
        return real_update_one(q, u, *args, **kwargs)

    monkeypatch.setattr(dbm.db.users, "update_one", _update_one)


MARK = "webapp_drive_prefs.auth_required_at"
NEXT_AT = "webapp_drive_prefs.schedule_next_at"


def test_a_pause_is_never_written_without_the_reconnect_mark(scheduler, dbm, monkeypatch):
    """הסימון נכתב קודם בכתיבה משלו (``_record_drive_auth_required``), שכשל בה רק נרשם. עד כאן ההשהיה נכתבה בכל זאת: התזמון נעצר, ``needs_reconnect`` נשאר כבוי, והמסך הציג "מחובר" על גיבוי שלא ירוץ עד חיבור מחדש שאיש לא ידע שצריך."""
    s = scheduler
    _fail_writes(dbm, monkeypatch, lambda q, u: set(u.get("$set", {})) == {MARK})
    s.answer["check"] = s.gds.ConnectionCheck(s.gds.CONNECTION_AUTH_REQUIRED, "invalid_grant")
    s.due()

    s.scan()

    prefs = dbm.web_prefs()
    assert prefs["schedule_next_at"] is None
    assert prefs.get("auth_required_at"), "התזמון הושהה בלי הסימון שהממשק קורא"


def test_a_pause_keeps_the_time_of_the_first_rejection(scheduler, dbm):
    s = scheduler
    first = "2026-10-12T12:37:45+00:00"
    s.due(auth_required_at=first)
    s.answer["check"] = s.gds.ConnectionCheck(s.gds.CONNECTION_AUTH_REQUIRED, "invalid_grant")

    s.scan()

    prefs = dbm.web_prefs()
    assert prefs["schedule_next_at"] is None
    assert prefs["auth_required_at"] == first


def test_a_reconnect_between_the_two_pause_writes_does_not_leave_a_silent_pause(scheduler, dbm, monkeypatch):
    """ההשהיה היא שתי כתיבות מותנות: בלי סימון — משהה ומסמנת; עם סימון — משהה ודורשת שהוא עדיין שם. כאן הסימון קיים בכתיבה הראשונה, וחיבור מחדש מוחק אותו לפני השנייה. השנייה לא תואמת, והתזמון לא מושהה: הסנטינל נשאר עד שהוא פג, והבדיקה הבאה רואה חיבור חי. השהיה כאן הייתה תזמון עצור בלי ``needs_reconnect`` — ואחרי חיבור מחדש שכבר קרה, שום דבר לא היה מחזיר אותו."""
    s = scheduler
    s.due(auth_required_at="2026-10-12T12:37:45+00:00")
    s.answer["check"] = s.gds.ConnectionCheck(s.gds.CONNECTION_AUTH_REQUIRED, "invalid_grant")
    real_update_one = dbm.db.users.update_one

    def _update_one(q, u, *args, **kwargs):
        res = real_update_one(q, u, *args, **kwargs)
        if MARK in q and q[MARK] is None and NEXT_AT in q:
            # החיבור מחדש של המשתמש נוחת בדיוק כאן, אחרי הכתיבה הראשונה של ההשהיה
            real_update_one({"user_id": USER_ID}, {"$set": {MARK: None}})
        return res

    monkeypatch.setattr(dbm.db.users, "update_one", _update_one)

    s.scan()

    prefs = dbm.web_prefs()
    assert not (prefs["schedule_next_at"] is None and not prefs.get("auth_required_at")), "תזמון מושהה בלי סימון"
    assert prefs["schedule_next_at"] is not None


def test_a_reconnect_during_the_check_is_not_paused(scheduler, dbm, monkeypatch):
    """המשתמש מתחבר מחדש בזמן שהסורק בודק את הטוקנים הישנים: ה-callback שומר טוקנים חדשים, ``resume_drive_schedule_after_reconnect`` לא מוצא תזמון מושהה (הסנטינל עוד שם) ומוחק את הסימון. עד כאן ההשהיה נכתבה אחריו, עם סימון חדש — תזמון עצור ובקשה להתחבר שוב, על חיבור שכבר חי. עכשיו ההשהיה מותנית ב-``obtained_at`` של הטוקנים שהסריקה תפסה."""
    s = scheduler
    s.answer["check"] = s.gds.ConnectionCheck(s.gds.CONNECTION_AUTH_REQUIRED, "invalid_grant")
    s.due()
    real_record = s.bs._record_drive_auth_required

    def _record_then_the_user_reconnects(db, uid):
        real_record(db, uid)
        assert dbm.save_drive_tokens(uid, {"access_token": "ya29.reconnected", "refresh_token": "1//new-refresh", "expires_in": 3599}, owner=drive_owner.WEBAPP)
        s.bs.resume_drive_schedule_after_reconnect(db, uid)

    monkeypatch.setattr(s.bs, "_record_drive_auth_required", _record_then_the_user_reconnects)

    s.scan()

    prefs = dbm.web_prefs()
    assert prefs["schedule_next_at"] is not None, "חיבור שכבר חודש הושהה"
    assert not prefs.get("auth_required_at"), "המשתמש מתבקש להתחבר שוב אחרי שהתחבר"


def test_a_resume_that_fails_to_write_keeps_the_reconnect_mark(scheduler, dbm, monkeypatch):
    """אם החזרת התזמון אחרי חיבור מחדש נכשלת והסימון נמחק בכל זאת, התזמון נשאר מושהה, המסך מציג "מחובר", ושום דבר לא מחזיר אותו. הסימון נשאר, והמסך ממשיך לבקש חיבור מחדש."""
    s = scheduler
    marked = "2026-10-12T12:37:45+00:00"
    assert dbm.save_drive_prefs(USER_ID, {"schedule_key": "weekly", "schedule_next_at": None, "auth_required_at": marked}, owner=drive_owner.WEBAPP)
    _fail_writes(dbm, monkeypatch, lambda q, u: NEXT_AT in q and q[NEXT_AT] is None and "webapp_drive_prefs.schedule_key" in q)

    s.bs.resume_drive_schedule_after_reconnect(dbm, USER_ID)

    prefs = dbm.web_prefs()
    assert prefs["schedule_next_at"] is None
    assert prefs["auth_required_at"] == marked


def test_a_pause_that_fails_to_write_leaves_the_claim_to_expire(scheduler, dbm, monkeypatch):
    """כשל בכתיבת ההשהיה אינו כשל של הגיבוי. עד כאן הוא נפל ל-``except`` הכללי של הסורק, שתזמן ניסיון חוזר בעוד ``SCAN_INTERVAL_SECONDS`` — עוד בדיקת חיבור מול גוגל ועוד אירוע כשל, על חיבור שכבר ידוע שמת. עכשיו הסנטינל נשאר עד שהוא פג (``SENTINEL_TTL_SECONDS``)."""
    s = scheduler
    _fail_writes(dbm, monkeypatch, lambda q, u: u.get("$set", {}).get(NEXT_AT, "x") is None)
    s.answer["check"] = s.gds.ConnectionCheck(s.gds.CONNECTION_AUTH_REQUIRED, "invalid_grant")
    s.due()
    before = datetime.now(timezone.utc)

    s.scan()

    held_until = datetime.fromisoformat(dbm.web_prefs()["schedule_next_at"])
    assert held_until >= before + timedelta(seconds=s.bs.SENTINEL_TTL_SECONDS - 60), "הסנטינל הוחלף בניסיון חוזר"
    s.scan()
    assert len(s.calls.checks) == 1
    assert [event for event, _ in s.calls.events] == ["webapp_drive_backup_failed"]


# --- מה שהממשק רואה: הסטטוס, "גבה עכשיו", וחיבור מחדש ---


@pytest.fixture
def webapp(dbm, scheduler, monkeypatch):
    import webapp.drive_auth as da
    import webapp.drive_backup_api as dba

    class _Resp:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError(f"{self.status_code} Client Error", response=self)

    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp(200, {"access_token": "ya29.reconnected", "refresh_token": "1//new-refresh", "expires_in": 3599}))
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(200, {"email": "web@example.com"}))
    monkeypatch.setattr(da, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(da, "_get_db", lambda: dbm)
    monkeypatch.setattr(dba, "_get_db", lambda: dbm)
    monkeypatch.setattr(scheduler.gds, "db", dbm)
    # "גבה עכשיו" רץ כאן בלי ה-thread, כדי שהבדיקה תקרא את הסטטוס אחרי שהוא נכתב
    monkeypatch.setattr(dba._backup_executor, "submit", lambda fn, *a, **k: fn(*a, **k))

    app = Flask(__name__)
    app.secret_key = "test-only-secret"
    app.register_blueprint(da.drive_auth_bp)
    app.register_blueprint(dba.drive_backup_bp)

    @app.route("/test-login")
    def _login():
        session["user_id"] = USER_ID
        session.permanent = True
        return "ok"

    client = app.test_client()
    client.get("/test-login")
    return client


def test_the_status_asks_to_reconnect_only_after_google_rejected_the_connection(webapp, scheduler, dbm):
    assert webapp.get("/api/drive/status").get_json()["needs_reconnect"] is False

    scheduler.answer["check"] = scheduler.gds.ConnectionCheck(scheduler.gds.CONNECTION_AUTH_REQUIRED, "invalid_grant")
    scheduler.due()
    scheduler.scan()

    status = webapp.get("/api/drive/status").get_json()
    assert status["connected"] is True
    assert status["needs_reconnect"] is True


def test_backup_now_says_a_reconnect_is_needed(webapp, scheduler):
    scheduler.answer["check"] = scheduler.gds.ConnectionCheck(scheduler.gds.CONNECTION_AUTH_REQUIRED, "invalid_grant")

    assert webapp.post("/api/drive/backup-now").get_json() == {"ok": True, "status": "running"}

    status = webapp.get("/api/drive/backup-status").get_json()
    assert status["manual_backup_status"] == "error"
    assert status["manual_backup_error"] == "auth_required"
    assert scheduler.calls.exports == []
    assert webapp.get("/api/drive/status").get_json()["needs_reconnect"] is True


def test_a_backup_now_that_succeeds_leaves_no_error_behind(webapp, scheduler, dbm):
    assert dbm.save_drive_prefs(USER_ID, {"manual_backup_error": "auth_required"}, owner=drive_owner.WEBAPP)

    webapp.post("/api/drive/backup-now")

    status = webapp.get("/api/drive/backup-status").get_json()
    assert status["manual_backup_status"] == "done"
    assert status["manual_backup_error"] is None


def test_reconnecting_clears_the_mark_and_resumes_the_paused_schedule(webapp, scheduler, dbm):
    s = scheduler
    s.answer["check"] = s.gds.ConnectionCheck(s.gds.CONNECTION_AUTH_REQUIRED, "invalid_grant")
    s.due()
    s.scan()
    assert dbm.web_prefs()["schedule_next_at"] is None

    auth = webapp.get("/api/drive/auth")
    state = parse_qs(urlparse(auth.headers["Location"]).query)["state"][0]
    resp = webapp.get(f"/api/drive/callback?state={state}&code=4/code")
    assert "drive_connected=1" in resp.headers["Location"]

    prefs = dbm.web_prefs()
    assert prefs["auth_required_at"] is None
    assert prefs["schedule_next_at"] is not None and prefs["schedule_next_at"] <= datetime.now(timezone.utc).isoformat()
    assert webapp.get("/api/drive/status").get_json()["needs_reconnect"] is False

    # והסריקה הבאה מריצה את הגיבוי שלא רץ
    s.answer["check"] = s.gds.ConnectionCheck(s.gds.CONNECTION_OK)
    s.scan()
    assert s.calls.exports == [USER_ID]


def test_reconnecting_does_not_turn_on_a_schedule_that_is_off(webapp, dbm):
    assert dbm.save_drive_prefs(USER_ID, {"schedule_key": "off", "schedule_next_at": None, "auth_required_at": "2026-10-12T12:37:45+00:00"}, owner=drive_owner.WEBAPP)

    auth = webapp.get("/api/drive/auth")
    state = parse_qs(urlparse(auth.headers["Location"]).query)["state"][0]
    webapp.get(f"/api/drive/callback?state={state}&code=4/code")

    prefs = dbm.web_prefs()
    assert prefs["schedule_next_at"] is None
    assert prefs["auth_required_at"] is None


def test_disconnecting_clears_the_mark(webapp, dbm):
    assert dbm.save_drive_prefs(USER_ID, {"auth_required_at": "2026-10-12T12:37:45+00:00"}, owner=drive_owner.WEBAPP)

    assert webapp.post("/api/drive/disconnect").get_json() == {"ok": True}

    assert dbm.web_prefs()["auth_required_at"] is None


@pytest.mark.parametrize(
    "prefs_key, write",
    [
        ("webapp_drive_prefs", lambda c: c.post("/api/drive/schedule", json={"schedule": "off"})),
        ("webapp_drive_prefs", lambda c: c.post("/api/drive/schedule", json={"schedule": "daily"})),
        ("webapp_drive_prefs", lambda c: c.post("/api/drive/disconnect")),
        ("disk_backup_prefs", lambda c: c.post("/api/disk-backup/schedule", json={"schedule": "off"})),
        ("disk_backup_prefs", lambda c: c.post("/api/disk-backup/schedule", json={"schedule": "daily"})),
    ],
    ids=["drive-off", "drive-on", "disconnect", "disk-off", "disk-on"],
)
def test_writing_a_schedule_starts_the_failure_count_from_zero(webapp, dbm, prefs_key, write):
    """המונה סופר כשלים רצופים של התזמון הנוכחי. עד כאן כיבוי, שינוי או ניתוק השאירו אותו, ואחרי הפעלה מחדש הכשלים הישנים נספרו — והגיבוי ויתר אחרי פחות מ-``RETRY_MAX_ATTEMPTS`` ניסיונות."""
    dbm.db.users.update_one({"user_id": USER_ID}, {"$set": {f"{prefs_key}.consecutive_failures": 4}})

    assert write(webapp).get_json()["ok"] is True

    doc = dbm.db.users.find_one({"user_id": USER_ID}) or {}
    assert (doc.get(prefs_key) or {}).get("consecutive_failures") == 0


# --- שומר טקסטואלי על מסך ההגדרות ---
#
# ההתנהגות בדפדפן נמדדה ב-Playwright מול הוובאפ האמיתי ומונגו מקומי (תיאור ה-PR): האזהרה מוצגת והשורה הירוקה
# מוסתרת כש-``needs_reconnect``, ו"גבה עכשיו" אומר "נדרש להתחבר מחדש". ל-CI אין דפדפן (``docs/testing.rst``),
# ולכן מה שנשאר בריפו הוא שומר על ההחלטות עצמן — לא מדידה חוזרת.


def _reconnect_ui_problems(html):
    import re

    problems = []
    if 'id="drive-reconnect-warning"' not in html or 'class="drive-reconnect-warning"' not in html:
        problems.append("אין אזהרת חיבור מחדש")
    if "/api/drive/auth" not in html.split('id="drive-reconnect-warning"', 1)[-1].split("</div>", 1)[0]:
        problems.append("לאזהרה אין כפתור חיבור מחדש")
    if "okLine.style.display = data.needs_reconnect ? 'none'" not in html:
        problems.append("השורה הירוקה לא מוסתרת כשצריך להתחבר מחדש")
    if "reconnectWarning.style.display = data.needs_reconnect ? 'flex'" not in html:
        problems.append("האזהרה לא מוצגת לפי needs_reconnect")
    if "statusData.manual_backup_error === 'auth_required'" not in html:
        problems.append('"גבה עכשיו" לא מבדיל בין חיבור שפג לכשל אחר')
    rule = re.search(r"\.drive-reconnect-warning\s*\{(.*?)\}", html, re.S)
    if not rule:
        problems.append("אין כלל CSS לאזהרה")
    else:
        body = rule.group(1)
        if "var(--danger-bg)" not in body or "var(--danger-border)" not in body:
            problems.append("האזהרה לא משתמשת בטוקני הסכנה")
        if re.search(r"#[0-9a-fA-F]{3,8}\b", body):
            problems.append("צבע קשיח בכלל של האזהרה (docs/webapp/theming_and_css.rst)")
    return problems


def _settings_html():
    from pathlib import Path

    return (Path(__file__).resolve().parents[1] / "webapp/templates/settings.html").read_text(encoding="utf-8")


def test_the_settings_page_shows_the_reconnect_warning_from_the_status():
    assert _reconnect_ui_problems(_settings_html()) == []


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("      if (okLine) okLine.style.display = data.needs_reconnect ? 'none' : 'flex';\n", "", "השורה הירוקה לא מוסתרת כשצריך להתחבר מחדש"),
        ("statusData.manual_backup_error === 'auth_required'", "false", '"גבה עכשיו" לא מבדיל בין חיבור שפג לכשל אחר'),
        ("      background: var(--danger-bg);\n", "      background: #ffe4e6;\n", "האזהרה לא משתמשת בטוקני הסכנה"),
    ],
)
def test_the_guard_catches_a_reverted_decision(old, new, expected):
    """השומר עצמו מסוגל להיכשל: כל מוטציה מבטלת החלטה אחת, והשומר נוקב בה."""
    html = _settings_html()
    assert html.count(old) == 1, "המוטציה לא תפסה — השומר התיישן מול התבנית"
    mutated = html.replace(old, new, 1)
    assert mutated != html
    assert expected in _reconnect_ui_problems(mutated)
