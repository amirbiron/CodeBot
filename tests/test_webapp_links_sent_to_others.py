"""קישור לוובאפ שנשלח בטלגרם למישהו אחר נבנה מ-``WEBAPP_URL`` בלבד — לא מהכתובת שהבקשה הגיעה אליה.

**למה הקובץ הזה קיים.** ``webapp_base_url_for_request`` נופל, בלי ``WEBAPP_URL`` תקין, לכתובת שהבקשה הגיעה אליה
(``request.url_root``), שנגזרת מכותרת ``Host`` של מי ששלח את הבקשה. זה מתאים לקישור שחוזר אליו בתשובה. שלוש הודעות
טלגרם בוובאפ הולכות לאדם אחר — הודעת האישור למי שהגיש סניפט או פריט לאוסף הקהילה, וההתראה לאדמינים על סניפט חדש —
והן נבנו מהכתובת הזו. עכשיו הן נבנות מ-``webapp_url.webapp_base_url``, ובלי כתובת יוצאות בלי קישור. בהתראה לאדמינים
זה גם מה שמונע כשל שלם: כפתור עם כתובת יחסית גורם לטלגרם לדחות את כל ההודעה.
"""

from __future__ import annotations

import types

import pytest
from flask import Flask

GOOD = "https://webapp.test"
FORGED = "evil.test"


# ---------------------------------------------------------------------------
# ההתראה לאדמינים על סניפט חדש (``webapp/snippet_library_api.py``)
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_messages(monkeypatch):
    import webapp.snippet_library_api as api

    sent = []

    def _capture(method, url, json=None, timeout=None):
        sent.append(json)
        return types.SimpleNamespace(status_code=200, text='{"ok": true}', json=lambda: {"ok": True})

    class _NowThread:
        def __init__(self, target, daemon=None):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(api, "_http_request", _capture)
    monkeypatch.setattr(api, "_threading", types.SimpleNamespace(Thread=_NowThread))
    monkeypatch.setenv("BOT_TOKEN", "123:abc")
    monkeypatch.setenv("ADMIN_USER_IDS", "7")
    return sent


def _urls(payload):
    return [b.get("url") for row in payload["reply_markup"]["inline_keyboard"] for b in row if "url" in b]


def test_without_an_address_the_admin_message_has_no_view_button(admin_messages):
    import webapp.snippet_library_api as api

    api._notify_admins_new_snippet("s1", title="t", language="python", username="u", base_url=None)

    assert len(admin_messages) == 1
    assert _urls(admin_messages[0]) == []
    callbacks = [b["callback_data"] for row in admin_messages[0]["reply_markup"]["inline_keyboard"] for b in row]
    assert callbacks == ["snippet_approve:s1", "snippet_reject:s1"]


def test_with_an_address_the_view_button_points_to_it(admin_messages):
    import webapp.snippet_library_api as api

    api._notify_admins_new_snippet("s1", title="t", language="python", username="u", base_url=GOOD)

    assert _urls(admin_messages[0]) == [f"{GOOD}/admin/snippets/view?id=s1"]


@pytest.mark.parametrize("configured", [None, GOOD], ids=["no-webapp-url", "webapp-url"])
def test_a_submission_with_a_forged_host_does_not_put_it_in_the_admin_message(admin_messages, monkeypatch, configured):
    import webapp.snippet_library_api as api

    if configured:
        monkeypatch.setenv("WEBAPP_URL", configured)
    else:
        monkeypatch.delenv("WEBAPP_URL", raising=False)
    monkeypatch.setattr(api, "_svc_submit", lambda **kw: {"ok": True, "id": "s1"})
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(api.snippets_bp)
    client = app.test_client()
    with client.session_transaction(base_url=f"http://{FORGED}") as sess:  # העוגייה לאותה כתובת
        sess["user_id"] = 42
        sess["user_data"] = {"username": "u"}

    resp = client.post(
        "/api/snippets/submit",
        json={"title": "t", "description": "d", "code": "print(1)", "language": "python"},
        base_url=f"http://{FORGED}",
    )

    assert resp.status_code == 200
    assert FORGED not in repr(admin_messages)
    assert _urls(admin_messages[0]) == ([f"{GOOD}/admin/snippets/view?id=s1"] if configured else [])


# ---------------------------------------------------------------------------
# הודעת האישור למי שהגיש (``webapp/app.py`` ו-``conversation_handlers``, דרך ``approval_notice``)
# ---------------------------------------------------------------------------


def test_the_approval_notice_has_a_link_only_with_an_address(monkeypatch):
    from webapp_url import approval_notice

    monkeypatch.delenv("WEBAPP_URL", raising=False)
    assert approval_notice("אושר.", "/snippets") == "אושר."

    monkeypatch.setenv("WEBAPP_URL", GOOD)
    assert approval_notice("אושר.", "/snippets") == f"אושר.\nאפשר לצפות כאן: {GOOD}/snippets"


@pytest.mark.parametrize("configured", [None, GOOD], ids=["no-webapp-url", "webapp-url"])
def test_the_webapp_approval_message_ignores_the_host_of_the_admin_request(monkeypatch, configured):
    """``/admin/snippets/approve`` שולח למי שהגיש. בלי ``WEBAPP_URL`` ההודעה יוצאת בלי קישור, ולא עם הכתובת של הבקשה."""
    import database
    import http_sync
    import webapp.app as webapp_app

    if configured:
        monkeypatch.setenv("WEBAPP_URL", configured)
    else:
        monkeypatch.delenv("WEBAPP_URL", raising=False)
    monkeypatch.setenv("BOT_TOKEN", "123:abc")
    sent = []

    def _capture(method, url, json=None, timeout=None):
        sent.append(json)
        return types.SimpleNamespace(status_code=200, text='{"ok": true}', json=lambda: {"ok": True})

    monkeypatch.setattr(http_sync, "request", _capture)
    monkeypatch.setattr(webapp_app, "is_admin", lambda uid: True)
    monkeypatch.setattr(webapp_app, "_snip_service", types.SimpleNamespace(approve_snippet=lambda item_id, admin: True))
    fake_db = types.SimpleNamespace(
        snippets_collection=types.SimpleNamespace(find_one=lambda q: {"user_id": 99}),
        _get_repo=lambda: types.SimpleNamespace(_normalize_snippet_identifier=lambda i: i),
    )
    monkeypatch.setattr(database, "db", fake_db)

    client = webapp_app.app.test_client()
    with client.session_transaction(base_url=f"http://{FORGED}") as sess:  # העוגייה לאותה כתובת
        sess["user_id"] = 1

    resp = client.get("/admin/snippets/approve?id=s1", base_url=f"http://{FORGED}")

    assert resp.status_code in (200, 302)
    assert [p["chat_id"] for p in sent] == [99]
    assert FORGED not in sent[0]["text"]
    expected_link = f"\nאפשר לצפות כאן: {GOOD}/snippets" if configured else ""
    assert sent[0]["text"] == "🎉 איזה כיף! הסניפט שלך אושר והתווסף לספריית הסניפטים." + expected_link
