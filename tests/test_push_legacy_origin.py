"""מנויי push אחרי מעבר כתובת: כל מנוי שומר מאיזו כתובת ומאיזה דפדפן נרשם, ומנוי מכתובת ישנה מאותו דפדפן נמחק.

הכלל וההנמקה — בהערה שמעל ``_LEGACY_RETIRED_EVENT`` ב-``webapp/push_api.py``. כאן נבדקים שני הצדדים שלו: ההפעלה בכתובת
הקנונית (``POST /api/push/subscribe``), והדיווח של ה-Service Worker מהכתובת הישנה (``POST /api/push/sw-report``), שמשלים
את השדות למנוי שנרשם לפני שהם נוספו. המסד הוא ``tests/_fake_mongo.py``: הוא מממש את ``$in``, ``$ne`` ו-``$exists``
כמו מונגו, כולל ``$ne`` ששדה חסר עונה עליו. מול מונגו אמיתי הקובץ לא רץ.
"""

from __future__ import annotations

import hashlib

import pytest

pytest.importorskip("flask")

from flask import Flask  # noqa: E402

import webapp.push_api as push_mod  # noqa: E402
from _fake_mongo import FakeDB  # noqa: E402

NEW_HOST = "codekeeper.dev"
OLD_HOST = "codekeeper-webapp.onrender.com"
USER = 777
UA_TABLET = "Mozilla/5.0 (Linux; Android 14; Tablet) Chrome/131.0 Safari/537.36"
UA_PHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) Safari/604.1"
KEYS = {"p256dh": "k", "auth": "a"}


def _hash(endpoint: str) -> str:
    # אותו חישוב כמו ``_sha256Hex12`` ב-``webapp/static/sw.js`` וכמו ``_hash_endpoint`` בשרת
    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()[:12]


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(push_mod, "get_db", lambda: fake)
    monkeypatch.setenv("WEBAPP_URL", f"https://{NEW_HOST}")
    return fake


@pytest.fixture
def events(monkeypatch):
    import observability

    seen = []
    monkeypatch.setattr(observability, "emit_event", lambda name, **fields: seen.append((name, fields)))
    return seen


@pytest.fixture
def client(db):
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(push_mod.push_bp)
    c = app.test_client()
    # ה-session הוא עוגייה, ועוגייה שייכת למארח: המשתמש מחובר בשתי הכתובות, כל אחת עם עוגייה משלה — כמו בדפדפן
    for host in (NEW_HOST, OLD_HOST):
        with c.session_transaction(base_url=f"https://{host}") as sess:
            sess["user_id"] = USER
    return c


def _sub(db, endpoint, **fields):
    doc = {"user_id": USER, "endpoint": endpoint, "keys": KEYS, "subscription": {"endpoint": endpoint, "keys": KEYS}}
    doc.update(fields)
    db.push_subscriptions.insert_one(doc)


def _endpoints(db):
    return sorted(d["endpoint"] for d in db.push_subscriptions.docs)


def _subscribe(client, endpoint, *, host, ua):
    return client.post(
        "/api/push/subscribe",
        json={"endpoint": endpoint, "keys": KEYS},
        base_url=f"https://{host}",
        headers={"User-Agent": ua},
    )


# --- הפעלה בכתובת הקנונית ------------------------------------------------------------------------------------------


def test_a_subscription_records_its_origin_and_user_agent(client, db):
    resp = _subscribe(client, "https://push.example/new", host=NEW_HOST, ua=UA_TABLET)

    assert resp.status_code == 201
    (doc,) = db.push_subscriptions.docs
    assert doc["origin_host"] == NEW_HOST
    assert doc["user_agent"] == UA_TABLET


def test_the_host_is_recorded_in_lower_case(client, db):
    _subscribe(client, "https://push.example/new", host=NEW_HOST.upper(), ua=UA_TABLET)

    assert db.push_subscriptions.docs[0]["origin_host"] == NEW_HOST


def test_enabling_on_the_new_host_retires_only_the_old_subscription_of_the_same_browser(client, db, events):
    _sub(db, "https://push.example/old-tablet", origin_host=OLD_HOST, user_agent=UA_TABLET)
    _sub(db, "https://push.example/old-phone", origin_host=OLD_HOST, user_agent=UA_PHONE)
    _sub(db, "https://push.example/unknown", user_agent=UA_TABLET)  # בלי origin_host — לא ידוע מאיפה
    _sub(db, "https://push.example/other-user", user_id=888, origin_host=OLD_HOST, user_agent=UA_TABLET)

    resp = _subscribe(client, "https://push.example/new", host=NEW_HOST, ua=UA_TABLET)

    assert resp.status_code == 201
    assert resp.get_json() == {"ok": True, "legacy_retired": 1, "legacy_remaining": 2}
    assert _endpoints(db) == [
        "https://push.example/new",
        "https://push.example/old-phone",
        "https://push.example/other-user",
        "https://push.example/unknown",
    ]
    assert ("push_legacy_subscriptions_retired", {"severity": "info", "user_id": str(USER), "retired": 1, "trigger": "subscribe"}) in events


def test_resaving_the_same_subscription_on_the_new_host_keeps_it(client, db):
    # ה-endpoint של המנוי עצמו לא נמחק, גם כשהוא נשמר שוב מאותו דפדפן
    _subscribe(client, "https://push.example/new", host=NEW_HOST, ua=UA_TABLET)

    resp = _subscribe(client, "https://push.example/new", host=NEW_HOST, ua=UA_TABLET)

    assert resp.get_json()["legacy_retired"] == 0
    assert _endpoints(db) == ["https://push.example/new"]


def test_enabling_on_the_old_host_retires_nothing(client, db):
    _sub(db, "https://push.example/new-tablet", origin_host=NEW_HOST, user_agent=UA_TABLET)

    resp = _subscribe(client, "https://push.example/old-tablet", host=OLD_HOST, ua=UA_TABLET)

    assert resp.get_json() == {"ok": True}
    assert _endpoints(db) == ["https://push.example/new-tablet", "https://push.example/old-tablet"]


def test_without_webapp_url_nothing_is_retired(client, db, monkeypatch):
    monkeypatch.delenv("WEBAPP_URL")
    _sub(db, "https://push.example/old-tablet", origin_host=OLD_HOST, user_agent=UA_TABLET)

    resp = _subscribe(client, "https://push.example/new", host=NEW_HOST, ua=UA_TABLET)

    assert resp.get_json() == {"ok": True}
    assert len(db.push_subscriptions.docs) == 2


# --- הדיווח של ה-Service Worker מהכתובת הישנה ----------------------------------------------------------------------


def _report(client, endpoint, *, host=OLD_HOST, ua=UA_TABLET):
    return client.post(
        "/api/push/sw-report",
        json={"event": "push_received", "status": "ok", "endpoint_hash": _hash(endpoint)},
        base_url=f"https://{host}",
        headers={"User-Agent": ua},
    )


def test_a_report_fills_in_the_origin_and_user_agent_of_an_old_subscription(client, db):
    _sub(db, "https://push.example/old-tablet")  # נרשם לפני שהשדות נוספו

    assert _report(client, "https://push.example/old-tablet").status_code == 200

    (doc,) = db.push_subscriptions.docs
    assert doc["origin_host"] == OLD_HOST
    assert doc["user_agent"] == UA_TABLET


def test_a_report_updates_a_user_agent_that_changed_but_never_the_origin(client, db):
    _sub(db, "https://push.example/old-tablet", origin_host=OLD_HOST, user_agent="Chrome/130")

    _report(client, "https://push.example/old-tablet", host=NEW_HOST, ua=UA_TABLET)

    (doc,) = db.push_subscriptions.docs
    assert doc["user_agent"] == UA_TABLET
    assert doc["origin_host"] == OLD_HOST


def test_a_report_from_an_old_subscription_retires_it_when_the_same_browser_moved(client, db, events):
    _sub(db, "https://push.example/new-tablet", origin_host=NEW_HOST, user_agent=UA_TABLET)
    _sub(db, "https://push.example/old-tablet")  # עוד לא ידוע מאיפה — הדיווח משלים, ואז הכלל חל

    _report(client, "https://push.example/old-tablet")

    assert _endpoints(db) == ["https://push.example/new-tablet"]
    assert ("push_legacy_subscriptions_retired", {"severity": "info", "user_id": str(USER), "retired": 1, "trigger": "sw_report"}) in events


def test_a_report_from_another_device_keeps_its_subscription(client, db):
    _sub(db, "https://push.example/new-tablet", origin_host=NEW_HOST, user_agent=UA_TABLET)
    _sub(db, "https://push.example/old-phone")

    _report(client, "https://push.example/old-phone", ua=UA_PHONE)

    assert _endpoints(db) == ["https://push.example/new-tablet", "https://push.example/old-phone"]


def test_a_report_from_the_new_host_never_retires_its_own_subscription(client, db):
    _sub(db, "https://push.example/new-tablet", origin_host=NEW_HOST, user_agent=UA_TABLET)

    _report(client, "https://push.example/new-tablet", host=NEW_HOST)

    assert _endpoints(db) == ["https://push.example/new-tablet"]


def _anonymous_client():
    """בלי session — ה-session של הכתובת הישנה פג: מכשיר שלא קיבל התראה חודש, בלי התחברות קבועה."""
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(push_mod.push_bp)
    return app.test_client()


def test_a_report_without_a_session_completes_and_retires_a_pre_change_subscription(db, events):
    """התרחיש מהריוויו: המנוי הישן נרשם לפני השינוי, ה-session שלו פג, ואותו דפדפן כבר נרשם בכתובת הקנונית."""
    _sub(db, "https://push.example/new-tablet", origin_host=NEW_HOST, user_agent=UA_TABLET)
    _sub(db, "https://push.example/old-tablet")

    resp = _report(_anonymous_client(), "https://push.example/old-tablet")

    assert resp.status_code == 200
    assert _endpoints(db) == ["https://push.example/new-tablet"]
    assert ("push_legacy_subscriptions_retired", {"severity": "info", "user_id": str(USER), "retired": 1, "trigger": "sw_report"}) in events


def test_a_report_without_a_session_only_fills_missing_fields(db):
    _sub(db, "https://push.example/old-phone")  # אין מנוי קנוני מאותו דפדפן — רק משלימים

    _report(_anonymous_client(), "https://push.example/old-phone", ua=UA_PHONE)

    (doc,) = db.push_subscriptions.docs
    assert doc["origin_host"] == OLD_HOST
    assert doc["user_agent"] == UA_PHONE


def test_a_report_without_a_session_never_overwrites_a_user_agent(db):
    # מנוי שכבר נושא user agent אינו מנוי מלפני השינוי, ובלי session לא נוגעים בו
    _sub(db, "https://push.example/new-tablet", origin_host=NEW_HOST, user_agent=UA_TABLET)
    _sub(db, "https://push.example/old-tablet", origin_host=OLD_HOST, user_agent="Chrome/130")

    _report(_anonymous_client(), "https://push.example/old-tablet")

    assert {d["endpoint"]: d["user_agent"] for d in db.push_subscriptions.docs} == {
        "https://push.example/new-tablet": UA_TABLET,
        "https://push.example/old-tablet": "Chrome/130",
    }


def test_a_report_without_a_session_to_the_canonical_host_writes_nothing(db):
    # מנוי מלפני השינוי נרשם בהכרח בכתובת קודמת; דיווח בלי session שמגיע לכתובת הקנונית אינו שלו
    _sub(db, "https://push.example/old-tablet")

    _report(_anonymous_client(), "https://push.example/old-tablet", host=NEW_HOST)

    assert "user_agent" not in db.push_subscriptions.docs[0]
    assert "origin_host" not in db.push_subscriptions.docs[0]


def test_another_device_with_the_same_user_agent_is_treated_as_the_same_device(client, db):
    """ההחלטה של בעל הפרויקט ב-PR: user agent זהה נחשב לאותו דפדפן באותו מכשיר. שני מכשירים זהים — אותו דגם ואותה
    גרסת דפדפן — הם המחיר: המנוי הישן של השני נמחק כשהראשון נרשם בכתובת הקנונית, ומפעילים בו מחדש. הטסט מקבע את
    ההחלטה, כדי ששינוי שלה יהיה מכוון."""
    _sub(db, "https://push.example/old-second-tablet", origin_host=OLD_HOST, user_agent=UA_TABLET)

    _subscribe(client, "https://push.example/new-first-tablet", host=NEW_HOST, ua=UA_TABLET)

    assert _endpoints(db) == ["https://push.example/new-first-tablet"]


def test_webapp_url_with_the_default_port_is_the_same_canonical_host(client, db, monkeypatch):
    # ``https://host:443`` תקין ב-``WEBAPP_URL``, ו-Werkzeug משמיט את 443 מ-``request.host`` (RFC 9110, 4.2.3)
    monkeypatch.setenv("WEBAPP_URL", f"https://{NEW_HOST}:443")
    _sub(db, "https://push.example/old-tablet", origin_host=OLD_HOST, user_agent=UA_TABLET)

    resp = _subscribe(client, "https://push.example/new", host=NEW_HOST, ua=UA_TABLET)

    assert resp.get_json()["legacy_retired"] == 1
    assert _endpoints(db) == ["https://push.example/new"]
    assert db.push_subscriptions.docs[0]["origin_host"] == NEW_HOST


def test_a_report_whose_hash_matches_nothing_writes_nothing(client, db):
    _sub(db, "https://push.example/old-tablet")

    _report(client, "https://push.example/somewhere-else")

    assert "user_agent" not in db.push_subscriptions.docs[0]


def test_the_retire_event_is_in_the_events_catalog():
    from pathlib import Path

    catalog = (Path(__file__).resolve().parents[1] / "docs/observability/events_catalog.rst").read_text(encoding="utf-8")

    assert f"``{push_mod._LEGACY_RETIRED_EVENT}``" in catalog
