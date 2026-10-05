"""לכל שירות חיבור Drive משלו: מה שהוובאפ עושה לא נוגע בבוט, ולהפך.

**מה נשבר.** הבוט והוובאפ קראו וכתבו את אותם שדות במסמך המשתמש — עם OAuth clients שונים, ו-refresh token עובד רק מול ה-client שהנפיק אותו (RFC 6749, סעיף 6). מי שהתחבר אחרון "ניצח", והשני נכשל בשקט בגיבוי הבא. הסורק של הוובאפ גם תפס תזמונים שהבוט כתב, ושני המתזמנים כתבו את אותו מועד גיבוי הבא.

**מה נבדק כאן.** ההתנהגות — מה נכתב בפועל במסמך המשתמש בכל מסלול (``Repository`` אמיתי מעל ``_fake_mongo``) — וגם המבנה: כל קריאה בריפו לאחסון של Drive או לפונקציה בשירות שדורשת ``owner`` אכן מעבירה אותו, וכל שירות נוקב רק בשמות השדות שלו. הבדיקה המבנית קיימת כי קריאה בלי ``owner`` נכשלת רק בזמן ריצה, ובתפריט הבוט רוב הקריאות עטופות ב-``try/except`` — שם ה-``TypeError`` היה נבלע ונראה כמו "אין חיבור".
"""

from __future__ import annotations

import ast
import copy
import functools
import inspect
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from flask import Flask, session

import drive_owner
from _fake_mongo import FakeDB

REPO_ROOT = Path(__file__).resolve().parent.parent
USER_ID = 5150
BOT_TOKENS = {"access_token": "ya29.bot-access", "refresh_token": "1//bot-refresh", "token_type": "Bearer"}
BOT_PREFS = {"schedule": "weekly", "schedule_next_at": "2026-10-01T00:00:00+00:00", "target_folder_id": "bot-folder", "last_backup_at": "2026-09-30T00:00:00+00:00"}


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

    def user_doc(self, user_id=USER_ID):
        return self.db.users.find_one({"user_id": user_id})


@pytest.fixture
def dbm():
    d = _DBM()
    assert d.save_drive_tokens(USER_ID, dict(BOT_TOKENS), owner=drive_owner.BOT)
    assert d.save_drive_prefs(USER_ID, dict(BOT_PREFS), owner=drive_owner.BOT)
    return d


def _bot_snapshot(dbm, user_id=USER_ID):
    doc = dbm.user_doc(user_id) or {}
    return copy.deepcopy({"drive_tokens": doc.get("drive_tokens"), "drive_prefs": doc.get("drive_prefs")})


# --- שכבת המסד ---


def test_saving_prefs_writes_only_the_given_keys_and_never_rewrites_the_rest(dbm, monkeypatch):
    """``save_drive_prefs`` כותב רק את המפתחות שקיבל. כאן קריאה של מסמך המשתמש מחזירה תמונה ישנה — כמו קריאה שרצה רגע לפני שנקבע תזמון — והתזמון שבמסד נשאר כמו שהוא."""
    schedule = {"schedule_key": "daily", "schedule_next_at": "2026-10-06T00:00:00+00:00"}
    assert dbm.save_drive_prefs(USER_ID, dict(schedule), owner=drive_owner.WEBAPP)
    stale = copy.deepcopy(dbm.user_doc())
    stale.pop("webapp_drive_prefs")
    real_find_one = dbm.db.users.find_one
    monkeypatch.setattr(dbm.db.users, "find_one", lambda *a, **k: copy.deepcopy(stale))

    assert dbm.save_drive_prefs(USER_ID, {"target_folder_id": "web-folder"}, owner=drive_owner.WEBAPP)

    monkeypatch.setattr(dbm.db.users, "find_one", real_find_one)
    assert dbm.get_drive_prefs(USER_ID, owner=drive_owner.WEBAPP) == {**schedule, "target_folder_id": "web-folder"}


@pytest.mark.parametrize("bad_key", ["schedule.key", "$set", "", 7])
def test_a_prefs_key_that_would_become_a_path_or_an_operator_is_refused_before_anything_is_written(dbm, bad_key):
    """המפתח נכנס לנתיב העדכון (``<field>.<key>``): נקודה הייתה הופכת אותו לנתיב מקונן, ו-``$`` לאופרטור. הוא נדחה לפני הכתיבה — גם שאר המפתחות לא נכתבים."""
    before = copy.deepcopy(dbm.user_doc())

    with pytest.raises(ValueError):
        dbm.save_drive_prefs(USER_ID, {"schedule_key": "daily", bad_key: "x"}, owner=drive_owner.WEBAPP)

    assert dbm.user_doc() == before


def test_restoring_drive_prefs_with_a_key_that_is_not_a_plain_name_is_reported_as_an_error(dbm):
    """ההעדפות בגיבוי אישי הן קלט חיצוני (קובץ ZIP). מפתח לא תקין שם לא נכתב, והשחזור מדווח שגיאה במקום "שוחזר"."""
    from services.personal_backup_service import PersonalBackupService

    errors = []

    assert PersonalBackupService(dbm)._restore_drive_prefs(USER_ID, {"schedule_key": "daily", "x.y": 1}, errors) is False

    assert errors == ["שגיאה בשחזור העדפות Drive"]
    assert dbm.get_drive_prefs(USER_ID, owner=drive_owner.WEBAPP) is None


def test_each_owner_reads_and_writes_only_its_own_fields(dbm):
    assert dbm.save_drive_tokens(USER_ID, {"access_token": "ya29.web-access"}, owner=drive_owner.WEBAPP)
    assert dbm.save_drive_prefs(USER_ID, {"schedule_key": "daily"}, owner=drive_owner.WEBAPP)

    assert dbm.get_drive_tokens(USER_ID, owner=drive_owner.BOT)["access_token"] == "ya29.bot-access"
    assert dbm.get_drive_tokens(USER_ID, owner=drive_owner.WEBAPP)["access_token"] == "ya29.web-access"
    assert dbm.get_drive_prefs(USER_ID, owner=drive_owner.BOT) == BOT_PREFS
    assert dbm.get_drive_prefs(USER_ID, owner=drive_owner.WEBAPP) == {"schedule_key": "daily"}

    assert dbm.delete_drive_tokens(USER_ID, owner=drive_owner.WEBAPP)
    assert dbm.get_drive_tokens(USER_ID, owner=drive_owner.WEBAPP) is None
    assert dbm.get_drive_tokens(USER_ID, owner=drive_owner.BOT)["access_token"] == "ya29.bot-access"


def test_a_call_without_owner_fails_loudly_and_an_unknown_owner_is_not_swallowed(dbm):
    import services.google_drive_service as gds
    from src.infrastructure.composition.files_facade import FilesFacade

    with pytest.raises(TypeError):
        dbm.get_drive_tokens(USER_ID)
    with pytest.raises(TypeError):
        gds.upload_bytes(USER_ID, "f.zip", b"x")
    with pytest.raises(TypeError):
        FilesFacade().get_drive_prefs(USER_ID)
    # owner לא מוכר הוא באג של הקורא — ValueError, ולא "אין טוקנים" מתוך ה-except של שכבת המסד
    with pytest.raises(ValueError):
        dbm.get_drive_tokens(USER_ID, owner="nobody")
    with pytest.raises(ValueError):
        dbm.save_drive_prefs(USER_ID, {}, owner="Bot")


# --- שירות ה-Drive ---


def test_the_service_loads_the_tokens_of_the_owner_it_was_asked_for(dbm, monkeypatch):
    import services.google_drive_service as gds

    monkeypatch.setattr(gds, "db", dbm)
    assert dbm.save_drive_tokens(USER_ID, {"access_token": "ya29.web-access"}, owner=drive_owner.WEBAPP)

    assert gds._load_tokens(USER_ID, owner=drive_owner.WEBAPP)["access_token"] == "ya29.web-access"
    assert gds._load_tokens(USER_ID, owner=drive_owner.BOT)["access_token"] == "ya29.bot-access"


@pytest.mark.parametrize("owner,other", [(drive_owner.WEBAPP, drive_owner.BOT), (drive_owner.BOT, drive_owner.WEBAPP)])
def test_save_tokens_keeps_the_refresh_token_of_the_same_owner_only(owner, other, monkeypatch):
    import services.google_drive_service as gds

    d = _DBM()
    monkeypatch.setattr(gds, "db", d)
    assert d.save_drive_tokens(USER_ID, {"access_token": "ya29.other-access", "refresh_token": "1//other-refresh"}, owner=other)

    # לשירות הזה אין חיבור; שמירה בלי refresh_token לא יכולה "לרשת" את זה של השירות האחר
    assert gds.save_tokens(USER_ID, {"access_token": "ya29.first-access"}, owner=owner)
    assert not d.get_drive_tokens(USER_ID, owner=owner).get("refresh_token")

    # מול החיבור של אותו שירות, refresh_token שלא חזר ברענון נשמר
    assert gds.save_tokens(USER_ID, {"access_token": "ya29.first-access", "refresh_token": "1//own-refresh"}, owner=owner)
    assert gds.save_tokens(USER_ID, {"access_token": "ya29.second-access"}, owner=owner)
    assert d.get_drive_tokens(USER_ID, owner=owner)["refresh_token"] == "1//own-refresh"
    assert d.get_drive_tokens(USER_ID, owner=other)["refresh_token"] == "1//other-refresh"


def test_the_service_cache_is_per_owner_and_a_forced_refresh_replaces_only_its_owners_entry(monkeypatch):
    import services.google_drive_service as gds

    def _build(*_a, credentials=None, **_k):
        return SimpleNamespace(token=credentials.token)

    class _Creds:
        token, refresh_token = "access", "refresh"

        def refresh(self, _request):
            self.token = "access-refreshed"

    monkeypatch.setattr(gds, "_SERVICE_CACHE", {})
    monkeypatch.setattr(gds, "build", _build)
    # השדות ש-get_drive_service קורא מ-Credentials; אותם טוקנים לשני השירותים, כדי שרק המפתח יפריד ביניהם
    monkeypatch.setattr(gds, "_ensure_valid_credentials", lambda uid, *, owner: SimpleNamespace(token="access", refresh_token="refresh"))

    bot_svc = gds.get_drive_service(USER_ID, owner=drive_owner.BOT)
    assert gds.get_drive_service(USER_ID, owner=drive_owner.BOT) is bot_svc
    web_svc = gds.get_drive_service(USER_ID, owner=drive_owner.WEBAPP)
    assert web_svc is not bot_svc

    # רענון כפוי של הוובאפ שלא נשמר: השירות המרוענן נכתב לרשומה של הוובאפ בלבד
    monkeypatch.setattr(gds, "_load_tokens", lambda uid, *, owner: {"access_token": "access", "refresh_token": "refresh"})
    monkeypatch.setattr(gds, "_credentials_from_tokens", lambda tokens: _Creds())
    monkeypatch.setattr(gds, "Request", lambda: None)
    monkeypatch.setattr(gds, "_save_refreshed_credentials", lambda uid, creds, *, owner: False)
    assert gds._force_refresh_credentials(USER_ID, owner=drive_owner.WEBAPP) is True

    assert gds.get_drive_service(USER_ID, owner=drive_owner.WEBAPP).token == "access-refreshed"
    assert gds.get_drive_service(USER_ID, owner=drive_owner.BOT) is bot_svc


# --- הוובאפ ---


@pytest.fixture
def webapp(dbm, monkeypatch):
    import services.google_drive_service as gds
    import webapp.drive_auth as da
    import webapp.drive_backup_api as dba

    class _Resp:
        """החלק של ``requests.Response`` שהקוד נוגע בו."""

        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError(f"{self.status_code} Client Error", response=self)

    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp(200, {"access_token": "ya29.web-access", "refresh_token": "1//web-refresh", "expires_in": 3599}))
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(200, {"email": "web@example.com"}))
    monkeypatch.setattr(da, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(da, "_get_db", lambda: dbm)
    monkeypatch.setattr(dba, "_get_db", lambda: dbm)
    monkeypatch.setattr(gds, "db", dbm)
    monkeypatch.setattr(dba._backup_executor, "submit", lambda *a, **k: None)

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


def _connect_webapp(client):
    auth = client.get("/api/drive/auth")
    state = parse_qs(urlparse(auth.headers["Location"]).query)["state"][0]
    resp = client.get(f"/api/drive/callback?state={state}&code=4/code")
    assert "drive_connected=1" in resp.headers["Location"]


def test_connecting_in_the_webapp_does_not_touch_the_bot_connection(webapp, dbm):
    before = _bot_snapshot(dbm)

    _connect_webapp(webapp)

    assert _bot_snapshot(dbm) == before
    assert dbm.get_drive_tokens(USER_ID, owner=drive_owner.WEBAPP)["access_token"] == "ya29.web-access"
    assert dbm.get_drive_prefs(USER_ID, owner=drive_owner.WEBAPP)["drive_email"] == "web@example.com"


def test_webapp_status_shows_only_the_webapp_connection(webapp, dbm):
    # לבוט יש חיבור ותזמון; לוובאפ — לא. הוובאפ מציג את המצב שלו בלבד
    status = webapp.get("/api/drive/status").get_json()
    assert status["connected"] is False
    assert status["schedule"] is None
    assert status["last_backup_at"] is None

    _connect_webapp(webapp)
    status = webapp.get("/api/drive/status").get_json()
    assert status["connected"] is True
    assert status["email"] == "web@example.com"


def test_webapp_schedule_and_backup_now_write_only_webapp_prefs(webapp, dbm):
    _connect_webapp(webapp)
    before = _bot_snapshot(dbm)

    assert webapp.post("/api/drive/schedule", json={"schedule": "daily"}).get_json()["ok"] is True
    assert webapp.post("/api/drive/backup-now").get_json()["status"] == "running"

    prefs = dbm.get_drive_prefs(USER_ID, owner=drive_owner.WEBAPP)
    assert prefs["schedule_key"] == "daily" and prefs["schedule_next_at"]
    assert prefs["manual_backup_status"] == "running"
    assert _bot_snapshot(dbm) == before


def test_webapp_schedule_rejects_a_value_that_is_not_a_known_string(webapp):
    for bad in (["daily"], {"k": 1}, 7, None):
        resp = webapp.post("/api/drive/schedule", json={"schedule": bad})
        assert resp.status_code == 400
    assert webapp.post("/api/drive/schedule", json=["daily"]).status_code == 400


def test_webapp_disconnect_removes_only_the_webapp_connection(webapp, dbm):
    _connect_webapp(webapp)
    assert webapp.post("/api/drive/schedule", json={"schedule": "daily"}).get_json()["ok"] is True
    before = _bot_snapshot(dbm)

    assert webapp.post("/api/drive/disconnect").get_json() == {"ok": True}

    assert dbm.get_drive_tokens(USER_ID, owner=drive_owner.WEBAPP) is None
    prefs = dbm.get_drive_prefs(USER_ID, owner=drive_owner.WEBAPP)
    assert prefs["schedule_key"] == "off" and prefs["schedule_next_at"] is None
    assert _bot_snapshot(dbm) == before


def test_a_schedule_is_not_written_for_a_user_who_is_not_connected_at_the_time_of_the_write(webapp, dbm, monkeypatch):
    """התנאי "מחובר" הוא חלק מהכתיבה עצמה. כאן קריאת החיבור עונה "מחובר" — כמו בדיקה שרצה רגע לפני ניתוק — ובמסמך אין חיבור של הוובאפ: התזמון לא נכתב, ולא נשאר תזמון בלי חיבור."""
    monkeypatch.setattr(dbm, "get_drive_tokens", lambda uid, *, owner: {"access_token": "ya29.web-access"}, raising=False)

    resp = webapp.post("/api/drive/schedule", json={"schedule": "daily"})

    assert resp.status_code == 400
    assert resp.get_json()["error"] == "יש לחבר Google Drive קודם"
    assert "schedule_key" not in (dbm._repo.get_drive_prefs(USER_ID, owner=drive_owner.WEBAPP) or {})


def test_turning_the_schedule_off_does_not_need_a_connection(webapp, dbm):
    assert webapp.post("/api/drive/schedule", json={"schedule": "off"}).get_json() == {"ok": True, "schedule": "off"}
    assert dbm.get_drive_prefs(USER_ID, owner=drive_owner.WEBAPP)["schedule_key"] == "off"


def test_backup_now_is_not_started_for_a_user_who_is_not_connected_at_the_time_of_the_write(webapp, dbm, monkeypatch):
    import webapp.drive_backup_api as dba

    submitted = []
    monkeypatch.setattr(dba._backup_executor, "submit", lambda *a, **k: submitted.append(a))
    monkeypatch.setattr(dbm, "get_drive_tokens", lambda uid, *, owner: {"access_token": "ya29.web-access"}, raising=False)

    resp = webapp.post("/api/drive/backup-now")

    assert resp.status_code == 400
    assert submitted == []
    assert "manual_backup_status" not in (dbm._repo.get_drive_prefs(USER_ID, owner=drive_owner.WEBAPP) or {})


def test_schedule_and_backup_now_answer_not_connected_when_the_database_is_in_noop_mode(webapp, monkeypatch):
    """במצב ``NoOpDB`` (מונגו לא זמין בעלייה) ``update_one`` לא כותב כלום. התזמון ו"גבה עכשיו" יודעים אם המשתמש מחובר לפי ``matched_count``, ולכן הם צריכים לענות "לא מחובר" — לא ליפול על תוצאה בלי השדה (בתזמון: 500 לא מטופל; ב"גבה עכשיו": שגיאה כללית)."""
    from database.manager import NoOpDB
    import webapp.drive_backup_api as dba

    submitted = []
    monkeypatch.setattr(dba, "_get_db", lambda: SimpleNamespace(db=NoOpDB()))
    monkeypatch.setattr(dba._backup_executor, "submit", lambda *a, **k: submitted.append(a))

    schedule = webapp.post("/api/drive/schedule", json={"schedule": "daily"})
    backup_now = webapp.post("/api/drive/backup-now")

    assert (schedule.status_code, (schedule.get_json() or {}).get("error")) == (400, dba._NOT_CONNECTED_ERROR)
    assert (backup_now.status_code, (backup_now.get_json() or {}).get("error")) == (400, dba._NOT_CONNECTED_ERROR)
    assert submitted == []


def test_webapp_disconnect_is_a_single_write(webapp, dbm, monkeypatch):
    """מחיקת הטוקנים וכיבוי התזמון יוצאים באותה כתיבה — אין רגע שבו אחד קרה והשני לא."""
    _connect_webapp(webapp)
    assert webapp.post("/api/drive/schedule", json={"schedule": "daily"}).get_json()["ok"] is True
    writes = []
    real_update_one = dbm.db.users.update_one

    def _recording_update_one(query, update, *args, **kwargs):
        writes.append(update)
        return real_update_one(query, update, *args, **kwargs)

    monkeypatch.setattr(dbm.db.users, "update_one", _recording_update_one)

    assert webapp.post("/api/drive/disconnect").get_json() == {"ok": True}

    assert len(writes) == 1
    assert writes[0]["$unset"] == {drive_owner.drive_fields(drive_owner.WEBAPP).tokens: ""}
    prefs_field = drive_owner.drive_fields(drive_owner.WEBAPP).prefs
    assert writes[0]["$set"][f"{prefs_field}.schedule_key"] == "off"


def test_a_failed_webapp_disconnect_leaves_the_connection_and_its_schedule_as_they_were(webapp, dbm, monkeypatch):
    """כשהכתיבה של הניתוק נכשלת לא משתנה כלום: המשתמש נשאר מחובר עם התזמון שלו. מה שאסור הוא חצי ניתוק — תזמון כבוי עם חיבור, או תזמון בלי חיבור."""
    from pymongo.errors import PyMongoError

    _connect_webapp(webapp)
    assert webapp.post("/api/drive/schedule", json={"schedule": "daily"}).get_json()["ok"] is True
    real_update_one = dbm.db.users.update_one

    def _failing_token_delete(query, update, *args, **kwargs):
        if "$unset" in update:
            raise PyMongoError("simulated write failure")
        return real_update_one(query, update, *args, **kwargs)

    monkeypatch.setattr(dbm.db.users, "update_one", _failing_token_delete)

    resp = webapp.post("/api/drive/disconnect")

    assert resp.status_code == 500
    assert dbm.get_drive_tokens(USER_ID, owner=drive_owner.WEBAPP)["access_token"] == "ya29.web-access"
    assert dbm.get_drive_prefs(USER_ID, owner=drive_owner.WEBAPP)["schedule_key"] == "daily"


# --- מתזמן הוובאפ ---


def test_the_webapp_scheduler_runs_only_webapp_schedules(dbm, monkeypatch):
    import webapp.backup_scheduler as bs

    due = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    # המשתמש של ה-fixture: תזמון של הבוט בלבד, בכל צורה שהבוט כותב — ושהגיע זמנו
    assert dbm.save_drive_prefs(USER_ID, {"schedule": "daily", "schedule_key": "daily", "schedule_next_at": due}, owner=drive_owner.BOT)
    # משתמש אחר: תזמון של הוובאפ שהגיע זמנו
    web_user = USER_ID + 1
    assert dbm.save_drive_prefs(web_user, {"schedule_key": "weekly", "schedule_next_at": due}, owner=drive_owner.WEBAPP)
    bot_before = _bot_snapshot(dbm)

    ran = []
    monkeypatch.setattr(bs, "_perform_drive_backup", lambda uid: ran.append(uid) or True)

    bs._scan_drive_backups(dbm, datetime.now(timezone.utc).isoformat())

    assert ran == [web_user]
    assert _bot_snapshot(dbm) == bot_before
    next_at = dbm.get_drive_prefs(web_user, owner=drive_owner.WEBAPP)["schedule_next_at"]
    assert next_at > datetime.now(timezone.utc).isoformat()


def test_a_scheduled_webapp_backup_uploads_with_the_webapp_connection(dbm, monkeypatch):
    import services.google_drive_service as gds
    import services.personal_backup_service as pbs
    import webapp.backup_scheduler as bs

    uploads = []
    monkeypatch.setattr(pbs.PersonalBackupService, "export_user_data", lambda self, uid: io.BytesIO(b"PK-zip"))
    monkeypatch.setattr(gds, "upload_bytes", lambda uid, filename, data, folder_id=None, sub_path=None, *, owner: uploads.append(owner) or "fid")
    monkeypatch.setitem(__import__("sys").modules, "database", SimpleNamespace(db=dbm))
    bot_before = _bot_snapshot(dbm)

    assert bs._perform_drive_backup(USER_ID) is True

    assert uploads == [drive_owner.WEBAPP]
    assert dbm.get_drive_prefs(USER_ID, owner=drive_owner.WEBAPP)["last_backup_at"]
    assert _bot_snapshot(dbm) == bot_before


@pytest.mark.parametrize("failure", ["upload_failed", "exception"])
def test_a_webapp_drive_backup_that_was_not_uploaded_is_sent_as_an_event(dbm, monkeypatch, failure):
    """כשל גיבוי של הוובאפ — מתוזמן או "גבה עכשיו", שניהם עוברים ב-``_perform_drive_backup`` — נשלח כאירוע, ולא רק כשורת לוג."""
    import services.google_drive_service as gds
    import services.personal_backup_service as pbs
    import webapp.backup_scheduler as bs

    events = []
    monkeypatch.setattr(bs, "emit_event", lambda event, severity="info", **fields: events.append((event, severity, fields)))
    monkeypatch.setattr(pbs.PersonalBackupService, "export_user_data", lambda self, uid: io.BytesIO(b"PK-zip"))
    monkeypatch.setitem(__import__("sys").modules, "database", SimpleNamespace(db=dbm))
    if failure == "upload_failed":
        monkeypatch.setattr(gds, "upload_bytes", lambda uid, filename, data, folder_id=None, sub_path=None, *, owner: None)
        expected = {"user_id": USER_ID, "reason": "upload_failed"}
    else:
        def _network_down(*_a, **_k):
            raise ConnectionError("network down")

        monkeypatch.setattr(gds, "upload_bytes", _network_down)
        expected = {"user_id": USER_ID, "reason": "exception", "error_type": "ConnectionError"}

    assert bs._perform_drive_backup(USER_ID) is False

    assert events == [("webapp_drive_backup_failed", "warn", expected)]


# --- הגיבוי האישי (רץ רק בוובאפ) ---


def test_the_personal_backup_exports_and_restores_the_webapp_drive_prefs():
    from services.personal_backup_service import PersonalBackupService

    db = MagicMock()
    db.get_drive_prefs.return_value = {"schedule_key": "weekly"}
    db.save_drive_prefs.return_value = True
    service = PersonalBackupService(db)

    assert service._export_drive_prefs(USER_ID) == {"schedule_key": "weekly"}
    assert service._restore_drive_prefs(USER_ID, {"schedule_key": "daily"}, []) is True

    db.get_drive_prefs.assert_called_once_with(USER_ID, owner=drive_owner.WEBAPP)
    db.save_drive_prefs.assert_called_once_with(USER_ID, {"schedule_key": "daily"}, owner=drive_owner.WEBAPP)


# --- המבנה: כל קורא נוקב ב-owner, וכל שירות בשדות שלו ---

#: שיטות האחסון של Drive — בשכבת המסד, במנהל וב-facade.
_STORAGE_METHODS = frozenset({"get_drive_tokens", "save_drive_tokens", "delete_drive_tokens", "get_drive_prefs", "save_drive_prefs"})

#: נקודות הכניסה שחייבות לדרוש owner. השאר נגזר מהחתימות בשירות — ראו ``_owner_functions``.
_REQUIRED_ENTRY_POINTS = frozenset({"save_tokens", "get_drive_service", "upload_bytes", "upload_file", "perform_scheduled_backup", "compute_friendly_name", "get_or_create_default_folder", "ensure_path"})


def _owner_functions():
    """הפונקציות בשירות שמקבלות ``owner`` כפרמטר keyword-only — נגזר מהקוד, לא רשימה ידנית שמתיישנת."""
    import services.google_drive_service as gds

    found = set()
    for name, fn in vars(gds).items():
        if inspect.isfunction(fn) and fn.__module__ == gds.__name__:
            param = inspect.signature(fn).parameters.get("owner")
            if param is not None and param.kind is inspect.Parameter.KEYWORD_ONLY and param.default is inspect.Parameter.empty:
                found.add(name)
    return found


@functools.lru_cache(maxsize=1)
def _production_sources():
    """(נתיב יחסי, עץ AST) לכל קובץ פייתון בריפו מחוץ לטסטים ולתיעוד — נקרא פעם אחת לשתי הבדיקות המבניות."""
    skip = {"tests", "venv", ".venv", "node_modules", ".git", ".restore", "docs"}
    out = []
    for path in sorted(REPO_ROOT.rglob("*.py")):
        rel = path.relative_to(REPO_ROOT)
        if skip.intersection(rel.parts):
            continue
        out.append((rel, ast.parse(path.read_text(encoding="utf-8"))))
    return tuple(out)


def test_the_drive_service_entry_points_require_an_owner():
    assert _REQUIRED_ENTRY_POINTS <= _owner_functions()


def test_every_drive_call_in_the_repo_names_its_owner():
    owner_fns = _owner_functions()
    service_aliases = {"gdrive", "google_drive_service", "gds"}
    missing = []
    for rel, tree in _production_sources():
        imported = {
            alias.asname or alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "services.google_drive_service"
            for alias in node.names
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            has_owner = any(kw.arg == "owner" for kw in node.keywords)
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
            is_storage = name in _STORAGE_METHODS
            is_service = (
                isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id in service_aliases and func.attr in owner_fns
            ) or (isinstance(func, ast.Name) and func.id in imported and func.id in owner_fns)
            # פונקציה שמועברת כהפניה — asyncio.to_thread(gdrive.upload_bytes, ..., owner=...)
            passed_ref = any(
                isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name) and arg.value.id in service_aliases and arg.attr in owner_fns
                for arg in node.args
            )
            if (is_storage or is_service or passed_ref) and not has_owner:
                missing.append(f"{rel}:{node.lineno} {name}")
    assert not missing, "קריאות ל-Drive בלי owner:\n" + "\n".join(missing)


def _string_constants(tree):
    return [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]


def _mentions_field(constants, field):
    return any(value == field or value.startswith(field + ".") for value in constants)


def test_each_service_names_only_its_own_drive_fields():
    bot_fields = drive_owner.drive_fields(drive_owner.BOT)
    web_fields = drive_owner.drive_fields(drive_owner.WEBAPP)
    offenders = []
    for rel, tree in _production_sources():
        constants = _string_constants(tree)
        if rel.parts[0] == "webapp":
            for field in (bot_fields.tokens, bot_fields.prefs):
                if _mentions_field(constants, field):
                    offenders.append(f"{rel}: הוובאפ נוקב בשדה של הבוט {field!r}")
        if rel.parts[0] == "handlers" or rel.name in {"main.py", "bot_handlers.py"}:
            for field in (web_fields.tokens, web_fields.prefs):
                if _mentions_field(constants, field):
                    offenders.append(f"{rel}: הבוט נוקב בשדה של הוובאפ {field!r}")
    assert not offenders, "\n".join(offenders)
