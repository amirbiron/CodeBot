"""קוד ה-state של חיבור ה-Drive בוובאפ: נשמר בשרת, לשימוש אחד, עם תוקף — ולוג לכל דחייה.

**מה נשבר.** ה-state נשמר ב-session, וה-session הוא cookie. ב-session קבוע Flask שולח את ה-cookie מחדש בכל תשובה (``SessionInterface.should_set_cookie``, Flask 3.1.2), ולכן בקשה שיצאה במקביל ללחיצה על "חבר" — שמירת מצב העבודה ב-``beforeunload`` — החזירה את ה-cookie שלפני הלחיצה, אחרי ההפניה לגוגל. הדפדפן שומר את מה שהגיע אחרון, ה-state נמחק, והחזרה מגוגל נדחתה עם ``csrf`` בלי שורה אחת בלוג.

**איך זה נבדק.** האפליקציה כאן היא Flask אמיתי עם ה-blueprint האמיתי (``webapp.drive_auth.drive_auth_bp``), **בתצורה שהייצור רץ בה**: ``session.permanent`` כמו בכל מסלולי ההתחברות של הוובאפ, ו-``SESSION_REFRESH_EACH_REQUEST`` בברירת המחדל. ``/api/ui_prefs`` כאן קורא את ה-session ולא כותב אליו, כמו ``work_state`` ב-``webapp/app.py``. ה-cookie מועבר ביד, כדי לקבוע באיזה סדר התשובות "הגיעו לדפדפן" — זה החלק שהדפדפן מחליט עליו, והבדיקה מקבעת את הסדר שנראה בלוגים של Render ב-4.10.2026, 21:47 UTC (``ui_prefs`` הסתיימה כ-100ms אחרי ``/api/drive/auth``).

המסד הוא ``Repository`` האמיתי מעל ``tests._fake_mongo``, ולכן מה שנבדק הוא גם מה שנכתב בפועל — לא רק מה שנענה. הקריאות לגוגל מוחלפות בדמויות.
"""

from __future__ import annotations

import ast
import logging
import re
import sys
import threading
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from flask import Flask, jsonify, session
from freezegun import freeze_time
from pymongo.errors import ServerSelectionTimeoutError

from _fake_mongo import FakeDB

REPO_ROOT = Path(__file__).resolve().parent.parent
USER_ID = 4242
ACCESS_TOKEN = "ya29.webapp-access-token-for-tests"
REFRESH_TOKEN = "1//webapp-refresh-token-for-tests"
AUTH_CODE = "4/0AQSTgQ-auth-code-for-tests"


class _DBM:
    """הצורה של ``DatabaseManager`` שהוובאפ ושירות ה-Drive פונים אליה — מעל ``Repository`` אמיתי ודמות מונגו."""

    def __init__(self):
        from database.repository import Repository

        self.db = FakeDB()
        self._repo = Repository(SimpleNamespace(db=self.db))

    def get_drive_tokens(self, user_id, *, owner):
        return self._repo.get_drive_tokens(user_id, owner=owner)

    def save_drive_tokens(self, user_id, token_data, *, owner):
        return self._repo.save_drive_tokens(user_id, token_data, owner=owner)

    def delete_drive_tokens(self, user_id, *, owner, prefs=None):
        return self._repo.delete_drive_tokens(user_id, owner=owner, prefs=prefs)

    def get_drive_prefs(self, user_id, *, owner):
        return self._repo.get_drive_prefs(user_id, owner=owner)

    def save_drive_prefs(self, user_id, prefs, *, owner):
        return self._repo.save_drive_prefs(user_id, prefs, owner=owner)

    def user_doc(self):
        return self.db.users.find_one({"user_id": USER_ID})


class _GoogleResponse:
    """החלק של ``requests.Response`` שהקוד נוגע בו: ``status_code``, ``json()`` ו-``raise_for_status()``."""

    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error", response=self)


@pytest.fixture
def harness(monkeypatch):
    import services.google_drive_service as gds
    import webapp.drive_auth as da

    dbm = _DBM()
    events = []
    google = {
        "token": _GoogleResponse(200, {
            "access_token": ACCESS_TOKEN,
            "refresh_token": REFRESH_TOKEN,
            "expires_in": 3599,
            "token_type": "Bearer",
            "scope": "https://www.googleapis.com/auth/drive.file",
        }),
        "userinfo": _GoogleResponse(200, {"email": "someone@example.com"}),
        "token_calls": 0,
    }

    def _post(url, data=None, timeout=None, **_kw):
        assert url == da.GOOGLE_TOKEN_URL
        google["token_calls"] += 1
        token = google["token"]
        if isinstance(token, Exception):
            raise token
        return token

    def _get(url, headers=None, timeout=None, **_kw):
        assert url == da.GOOGLE_USERINFO_URL
        return google["userinfo"]

    monkeypatch.setattr(requests, "post", _post)
    monkeypatch.setattr(requests, "get", _get)
    monkeypatch.setattr(da, "GOOGLE_CLIENT_ID", "client-id.apps.googleusercontent.com")
    monkeypatch.setattr(da, "GOOGLE_CLIENT_SECRET", "client-secret-for-tests")
    monkeypatch.setattr(da, "_get_db", lambda: dbm)
    monkeypatch.setattr(da, "emit_event", lambda event, severity="info", **fields: events.append((event, severity, fields)))
    monkeypatch.setattr(gds, "db", dbm)
    monkeypatch.setenv("WEBAPP_URL", "https://webapp.example")

    app = Flask(__name__)
    app.secret_key = "test-only-secret"
    app.permanent_session_lifetime = timedelta(days=30)
    app.register_blueprint(da.drive_auth_bp)

    @app.route("/test-login")
    def _login():
        session["user_id"] = USER_ID
        session.permanent = True  # כמו כל מסלולי ההתחברות של הוובאפ
        return "ok"

    @app.route("/test-login-other")
    def _login_other():
        session["user_id"] = USER_ID + 1
        session.permanent = True
        return "ok"

    @app.route("/api/ui_prefs", methods=["POST"])
    def _ui_prefs():
        # כמו work_state ב-webapp/app.py: קורא את ה-session ולא כותב אליו
        _ = session.get("user_id")
        return jsonify(ok=True)

    h = SimpleNamespace(app=app, client=app.test_client(use_cookies=False), dbm=dbm, events=events, google=google, da=da, issued_states=[])
    yield h
    # "לא נרשמים state, code או טוקנים" (ה-docstring של webapp/drive_auth.py) היא טענה על כל דחייה,
    # ולכן היא נבדקת כאן, אחרי כל טסט בקובץ — ולא רק בטסטים שזוכרים לקרוא ל-_assert_no_secrets.
    _assert_no_secrets(h, AUTH_CODE, ACCESS_TOKEN, REFRESH_TOKEN, *h.issued_states)


def _session_cookie(resp):
    for header in resp.headers.getlist("Set-Cookie"):
        if header.startswith("session="):
            return header.split(";", 1)[0].split("=", 1)[1]
    return None


def _cookie(value):
    return {"Cookie": f"session={value}"}


def _login(h):
    cookie = _session_cookie(h.client.get("/test-login"))
    assert cookie
    return cookie


def _start_auth(h, cookie):
    resp = h.client.get("/api/drive/auth", headers=_cookie(cookie))
    assert resp.status_code == 302, resp.get_data(as_text=True)
    query = parse_qs(urlparse(resp.headers["Location"]).query)
    state = query["state"][0]
    h.issued_states.append(state)
    return resp, state


def _callback(h, cookie, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return h.client.get(f"/api/drive/callback?{query}", headers=_cookie(cookie) if cookie else {})


def _outcome(resp):
    """``connected`` או קוד השגיאה שהוובאפ מעביר לעמוד ההגדרות."""
    assert resp.status_code == 302
    query = parse_qs(urlparse(resp.headers["Location"]).query)
    if query.get("drive_connected") == ["1"]:
        return "connected"
    return query.get("drive_error", ["?"])[0]


def _rejections(h):
    return [fields for event, _sev, fields in h.events if event == "webapp_drive_callback_rejected"]


def test_a_background_request_that_returns_the_old_cookie_no_longer_loses_the_state(harness):
    h = harness
    before_click = _login(h)

    # הלחיצה: הניווט ל-/api/drive/auth ובקשת beforeunload יוצאות שתיהן עם ה-cookie שלפני הלחיצה
    auth, state = _start_auth(h, before_click)
    background = h.client.post("/api/ui_prefs", headers=_cookie(before_click))

    # הקדם-תנאי של המרוץ: Flask שולח את ה-cookie הישן מחדש גם בתשובה שלא נגעה ב-session
    returned = _session_cookie(background)
    assert returned is not None
    assert _session_cookie(auth) is not None

    # תשובת ui_prefs הגיעה אחרונה — וזה ה-cookie שהדפדפן מחזיק כשגוגל מחזיר אותו
    resp = _callback(h, returned, state=state, code=AUTH_CODE)

    assert _outcome(resp) == "connected"
    assert not _rejections(h)


def test_the_same_state_connects_once_even_when_callbacks_race(harness):
    """שימוש אחד נבדק במקביל ולא ברצף (``TESTING-PATTERNS.md`` T1(d)).

    ``sys.setswitchinterval(1e-6)`` מקצר את הזמן שחוט רץ לפני שהמפרש מבקש להחליף חוט (התיעוד של ``sys`` בפייתון), וכך החלון בין "בדקתי" ל"מחקתי" נפתח באמת. ב-5.10.2026 הטסט הורץ מול מוטציה שמחליפה את הצריכה ב-``find_one`` ואחריו ``update_one``: סבב בודד תפס אותה רק בחלק מההרצות, ולכן הטסט מריץ כמה סבבים: מימוש לא אטומי עובר רק אם אף אחד מהם לא תפס אותו.
    """
    h = harness
    cookie = _login(h)
    racers, rounds = 8, 5

    # כל מה שהחוט צריך עובר כארגומנט ולא נלכד מהלולאה: חוט שלא הסתיים בזמן לא יקרא את ה-state של הסבב הבא
    def _racer(barrier, state, after_auth, outcomes, lock):
        client = h.app.test_client(use_cookies=False)
        barrier.wait()
        resp = client.get(f"/api/drive/callback?state={state}&code={AUTH_CODE}", headers=_cookie(after_auth))
        with lock:
            outcomes.append(_outcome(resp))

    previous = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        for _ in range(rounds):
            auth, state = _start_auth(h, cookie)
            after_auth = _session_cookie(auth)
            barrier = threading.Barrier(racers)
            outcomes = []
            lock = threading.Lock()
            args = (barrier, state, after_auth, outcomes, lock)

            threads = [threading.Thread(target=_racer, args=args) for _ in range(racers)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)

            assert sorted(outcomes) == ["connected"] + ["csrf"] * (racers - 1)
    finally:
        sys.setswitchinterval(previous)

    # רק החזרה שזכתה בכל סבב הגיעה לגוגל עם ה-code
    assert h.google["token_calls"] == rounds
    assert [r["reason"] for r in _rejections(h)] == ["state_not_found_or_expired"] * ((racers - 1) * rounds)


def test_a_state_older_than_ten_minutes_is_rejected(harness):
    h = harness
    with freeze_time("2026-10-05 05:00:00", tz_offset=0) as clock:
        cookie = _login(h)
        auth, state = _start_auth(h, cookie)
        clock.tick(timedelta(minutes=10, seconds=1))
        resp = _callback(h, _session_cookie(auth), state=state, code=AUTH_CODE)

    assert _outcome(resp) == "csrf"
    assert [r["reason"] for r in _rejections(h)] == ["state_not_found_or_expired"]
    assert h.google["token_calls"] == 0


def test_a_state_inside_its_ten_minutes_connects(harness):
    # הבקרה של הטסט שמעל: אותו מסלול, לפני שהתוקף עבר
    h = harness
    with freeze_time("2026-10-05 05:00:00", tz_offset=0) as clock:
        cookie = _login(h)
        auth, state = _start_auth(h, cookie)
        clock.tick(timedelta(minutes=9, seconds=59))
        resp = _callback(h, _session_cookie(auth), state=state, code=AUTH_CODE)

    assert _outcome(resp) == "connected"


def test_a_new_click_replaces_the_previous_state(harness):
    h = harness
    cookie = _login(h)
    _first_auth, first_state = _start_auth(h, cookie)
    second_auth, second_state = _start_auth(h, cookie)

    assert _outcome(_callback(h, _session_cookie(second_auth), state=first_state, code=AUTH_CODE)) == "csrf"
    assert _outcome(_callback(h, _session_cookie(second_auth), state=second_state, code=AUTH_CODE)) == "connected"


def test_only_a_hash_of_the_state_is_stored(harness):
    h = harness
    cookie = _login(h)
    _auth, state = _start_auth(h, cookie)

    record = h.dbm.user_doc()["webapp_drive_oauth"]
    assert set(record) == {"state_hash", "expires_at"}
    assert state not in str(record)


def test_the_state_of_one_user_does_not_connect_another(harness):
    # מי שמתחיל חיבור לעצמו לא יכול לשלוח למישהו אחר קישור שיחבר את הדרייב של השני (RFC 6749, סעיף 10.12)
    h = harness
    attacker_cookie = _login(h)
    _auth, attacker_state = _start_auth(h, attacker_cookie)

    victim_cookie = _session_cookie(h.client.get("/test-login-other"))
    resp = _callback(h, victim_cookie, state=attacker_state, code=AUTH_CODE)

    assert _outcome(resp) == "csrf"
    assert _rejections(h) == [{"reason": "state_not_found_or_expired", "user_id": USER_ID + 1}]
    victim = h.dbm.db.users.find_one({"user_id": USER_ID + 1})
    assert victim is None or "webapp_drive_tokens" not in victim
    assert h.google["token_calls"] == 0


# --- כל דחייה נרשמת, עם סיבה, בלי סודות ---


def _assert_no_secrets(h, *secrets_):
    for _event, _sev, fields in h.events:
        dumped = repr(fields)
        for secret in secrets_:
            assert secret not in dumped, f"{secret!r} נרשם באירוע: {dumped}"


def test_callback_without_a_session_is_logged(harness):
    h = harness
    cookie = _login(h)
    _auth, state = _start_auth(h, cookie)

    resp = _callback(h, None, state=state, code=AUTH_CODE)

    assert _outcome(resp) == "session_expired"
    assert [r["reason"] for r in _rejections(h)] == ["session_missing"]
    _assert_no_secrets(h, state, AUTH_CODE)


def test_callback_without_a_state_is_logged(harness):
    h = harness
    cookie = _login(h)
    _start_auth(h, cookie)

    resp = _callback(h, cookie, code=AUTH_CODE)

    assert _outcome(resp) == "csrf"
    assert _rejections(h) == [{"reason": "state_missing", "user_id": USER_ID}]


def test_a_state_check_that_fails_on_the_database_is_logged_as_such(harness, monkeypatch):
    h = harness
    cookie = _login(h)
    _auth, state = _start_auth(h, cookie)

    def _boom(*_a, **_k):
        raise ServerSelectionTimeoutError("no primary")

    monkeypatch.setattr(h.dbm.db.users, "find_one_and_update", _boom)
    resp = _callback(h, cookie, state=state, code=AUTH_CODE)

    assert _outcome(resp) == "state_check_failed"
    assert [r["reason"] for r in _rejections(h)] == ["state_check_failed"]
    _assert_no_secrets(h, state, AUTH_CODE)


@pytest.mark.parametrize(
    "google_error, logged",
    [
        ("access_denied", "access_denied"),
        ("unsupported_response_type", "unsupported_response_type"),
        ("Access%20Denied%3Cscript%3E", "unrecognized"),
        ("a" * 51, "unrecognized"),
    ],
)
def test_an_error_from_google_is_logged_with_a_safe_code(harness, google_error, logged):
    h = harness
    cookie = _login(h)
    _auth, state = _start_auth(h, cookie)

    resp = _callback(h, cookie, state=state, error=google_error)

    assert _rejections(h) == [{"reason": "google_error", "user_id": USER_ID, "google_error": logged}]
    assert resp.status_code == 302
    _assert_no_secrets(h, state)


def test_callback_without_a_code_is_logged(harness):
    h = harness
    cookie = _login(h)
    _auth, state = _start_auth(h, cookie)

    resp = _callback(h, cookie, state=state)

    assert _outcome(resp) == "no_code"
    assert _rejections(h) == [{"reason": "code_missing", "user_id": USER_ID}]


def test_a_token_endpoint_that_cannot_be_reached_is_logged(harness):
    h = harness
    h.google["token"] = requests.ConnectionError("connection refused by https://oauth2.googleapis.com/token")
    cookie = _login(h)
    _auth, state = _start_auth(h, cookie)

    resp = _callback(h, cookie, state=state, code=AUTH_CODE)

    assert _outcome(resp) == "token_exchange"
    assert _rejections(h) == [{"reason": "token_exchange_failed", "user_id": USER_ID, "error_type": "ConnectionError"}]
    _assert_no_secrets(h, state, AUTH_CODE)


def test_a_token_endpoint_error_is_logged_with_status_and_code_only(harness):
    h = harness
    h.google["token"] = _GoogleResponse(400, {"error": "invalid_grant", "error_description": f"Bad Request for {AUTH_CODE}"})
    cookie = _login(h)
    _auth, state = _start_auth(h, cookie)

    resp = _callback(h, cookie, state=state, code=AUTH_CODE)

    assert _outcome(resp) == "token_exchange"
    assert _rejections(h) == [{"reason": "token_exchange_failed", "user_id": USER_ID, "http_status": 400, "google_error": "invalid_grant"}]
    _assert_no_secrets(h, state, AUTH_CODE, "Bad Request")


def test_a_token_response_that_is_not_json_is_logged(harness):
    h = harness
    h.google["token"] = _GoogleResponse(200, requests.exceptions.JSONDecodeError("Expecting value", "<html>", 0))
    cookie = _login(h)
    _auth, state = _start_auth(h, cookie)

    resp = _callback(h, cookie, state=state, code=AUTH_CODE)

    assert _outcome(resp) == "token_exchange"
    assert _rejections(h) == [{"reason": "token_response_invalid", "user_id": USER_ID, "http_status": 200}]


def test_a_token_response_without_an_access_token_is_logged(harness):
    h = harness
    h.google["token"] = _GoogleResponse(200, {"refresh_token": REFRESH_TOKEN})
    cookie = _login(h)
    _auth, state = _start_auth(h, cookie)

    resp = _callback(h, cookie, state=state, code=AUTH_CODE)

    assert _outcome(resp) == "no_token"
    assert _rejections(h) == [{"reason": "no_access_token", "user_id": USER_ID}]
    _assert_no_secrets(h, REFRESH_TOKEN)


def test_tokens_that_were_not_saved_are_logged_and_not_reported_as_connected(harness, monkeypatch):
    h = harness
    monkeypatch.setattr(h.dbm, "save_drive_tokens", lambda *a, **k: False)
    cookie = _login(h)
    _auth, state = _start_auth(h, cookie)

    resp = _callback(h, cookie, state=state, code=AUTH_CODE)

    assert _outcome(resp) == "save_failed"
    assert _rejections(h) == [{"reason": "save_failed", "user_id": USER_ID}]
    assert not any(event == "webapp_drive_connected" for event, _s, _f in h.events)
    _assert_no_secrets(h, ACCESS_TOKEN, REFRESH_TOKEN)


def test_a_successful_connect_logs_no_rejection_and_no_secret(harness):
    h = harness
    cookie = _login(h)
    _auth, state = _start_auth(h, cookie)

    resp = _callback(h, cookie, state=state, code=AUTH_CODE)

    assert _outcome(resp) == "connected"
    assert not _rejections(h)
    assert [e for e, _s, _f in h.events] == ["webapp_drive_connected"]
    _assert_no_secrets(h, state, AUTH_CODE, ACCESS_TOKEN, REFRESH_TOKEN)


def test_an_error_answer_for_the_account_email_is_logged_with_its_status(harness, caplog):
    """המייל לתצוגה בלבד, ולכן כשל בו לא מבטל את החיבור — אבל תשובת שגיאה מגוגל נרשמת עם הסטטוס שלה, ולא נקראת כאילו היא פרטי החשבון."""
    h = harness
    h.google["userinfo"] = _GoogleResponse(401, {"error": {"code": 401, "status": "UNAUTHENTICATED"}})
    cookie = _login(h)
    _auth, state = _start_auth(h, cookie)

    with caplog.at_level(logging.WARNING, logger="webapp.drive_auth"):
        resp = _callback(h, cookie, state=state, code=AUTH_CODE)

    assert _outcome(resp) == "connected"
    assert "drive_email" not in (h.dbm.get_drive_prefs(USER_ID, owner="webapp") or {})
    logged = [r.getMessage() for r in caplog.records if r.name == "webapp.drive_auth"]
    assert logged == ["webapp_drive_userinfo_failed error_type=HTTPError http_status=401"]


def test_auth_does_not_send_the_user_to_google_when_the_state_was_not_stored(harness, monkeypatch):
    h = harness

    def _boom(*_a, **_k):
        raise ServerSelectionTimeoutError("no primary")

    monkeypatch.setattr(h.dbm.db.users, "update_one", _boom)
    cookie = _login(h)
    resp = h.client.get("/api/drive/auth", headers=_cookie(cookie))

    # בלי state שמור החזרה מגוגל הייתה נדחית בוודאות — אז לא שולחים לשם בכלל
    assert resp.status_code == 500
    assert "Location" not in resp.headers
    assert [(e, f["reason"]) for e, _s, f in h.events] == [("webapp_drive_auth_failed", "state_store_failed")]


# --- קטלוג האירועים מול הקוד ---


def _calls(path, name):
    tree = ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"))
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name]


def _first_str_arg(call):
    if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
        return call.args[0].value
    return None


def _catalog():
    return (REPO_ROOT / "docs/observability/events_catalog.rst").read_text(encoding="utf-8")


def test_the_events_catalog_lists_exactly_the_rejection_reasons_in_the_code():
    """רשימת הסיבות בקטלוג היא עותק של עובדה מהקוד, ולכן היא נגזרת ומושווית בשני הכיוונים: סיבה חדשה בלי שורה בקטלוג, ושורה בקטלוג לסיבה שכבר לא קיימת, נכשלות שתיהן."""
    in_code = {_first_str_arg(call) for call in _calls("webapp/drive_auth.py", "_reject")}
    assert in_code and None not in in_code, "לא כל קריאה ל-_reject נושאת סיבה קבועה — הסריקה צריכה עדכון"

    catalog = _catalog()
    assert catalog.count(".. drive-rejection-reasons:start") == 1 and catalog.count(".. drive-rejection-reasons:end") == 1
    block = catalog.split(".. drive-rejection-reasons:start", 1)[1].split(".. drive-rejection-reasons:end", 1)[0]
    in_catalog = set(re.findall(r"^- ``([a-z_]+)``", block, re.MULTILINE))

    assert in_catalog == in_code


#: כל הקבצים שפולטים אירועי Drive — של הבוט ושל הוובאפ. קובץ חדש שפולט אירוע כזה נכנס לכאן.
_DRIVE_EVENT_SOURCES = (
    "webapp/drive_auth.py",
    "webapp/drive_backup_api.py",
    "webapp/backup_scheduler.py",
    "database/repository.py",
    "handlers/drive/menu.py",
    "main.py",
)


def _reason_constants(call):
    return {kw.value.value for kw in call.keywords if kw.arg == "reason" and isinstance(kw.value, ast.Constant)}


def test_the_events_catalog_lists_every_drive_event_the_code_emits():
    import webapp.drive_auth as da

    names = {da._REJECTED_EVENT}
    reasons = set()
    for path in _DRIVE_EVENT_SOURCES:
        for call in _calls(path, "emit_event"):
            name = _first_str_arg(call)
            if name and "drive" in name:
                names.add(name)
                reasons |= _reason_constants(call)
        # עוטף שמקבל את הסיבה ומעביר אותה ל-emit_event
        for call in _calls(path, "_emit_drive_backup_failed"):
            reasons |= _reason_constants(call)
    assert {"drive_handler_ready", "webapp_drive_backup_failed"} <= names, "לא נמצאו אירועי Drive של הבוט ושל הוובאפ — הסריקה התיישנה"
    assert {"upload_failed", "exception"} <= reasons, "הסיבות של webapp_drive_backup_failed לא נמצאו — הסריקה התיישנה"

    catalog = _catalog()
    missing = sorted(n for n in names | reasons if f"``{n}``" not in catalog)
    assert not missing, f"אירועים או סיבות שהקוד פולט ואינם בקטלוג: {missing}"

