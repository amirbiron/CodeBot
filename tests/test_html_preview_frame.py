"""‏``/raw_html/<id>`` ו-``/html/<id>`` — מדווח הגלילה שהפתקים על תצוגת ה-HTML נשענים עליו.

מה השרת שולח: ה-CSP של כל אחד משלושת המצבים (``webapp/html_preview_frame.py``), המדווח שמצורף רק עם
``REPORT_SCROLL_PARAM``, וה-``nonce`` שמחבר ביניהם. מה הדפדפן **עושה** עם זה — שהמדווח רץ, שהסקריפטים של הקובץ
נחסמים, ושהפתקים נעים עם הגלילה — נבדק ב-``tests/test_html_preview_notes_browser.py``: בדיקת שרת אינה אוכפת CSP.
"""

from __future__ import annotations

import re

from bson import ObjectId

from webapp import app as webapp_app
from webapp import html_preview_frame

OWNER_ID = 7151
FILE_OID = ObjectId("0123456789abcdef0123ab08")
USER_HTML = "<!doctype html><html><body><p>שלום</p><script>window.userRan = 1;</script></body></html>"

#: ה-CSP ש-``/raw_html`` שלח לפני שהמדווח נוסף — "חלון חדש" חייב לקבל בדיוק אותו.
CSP_BEFORE_THE_REPORTER = (
    "sandbox; default-src 'none'; base-uri 'none'; form-action 'none'; connect-src 'none'; img-src data:; "
    "style-src 'unsafe-inline'; font-src data:; object-src 'none'; frame-ancestors 'self'; script-src 'none'"
)
CSP_SCRIPTS_BEFORE_THE_REPORTER = (
    "sandbox allow-scripts; default-src 'none'; base-uri 'none'; form-action 'none'; connect-src 'none'; "
    "img-src data:; style-src 'unsafe-inline'; font-src data:; object-src 'none'; frame-ancestors 'self'; "
    "script-src 'unsafe-inline'"
)

#: ‏``base64-value`` של CSP מקבל ``A-Za-z0-9+/-_``; ‏``secrets.token_urlsafe`` מייצר תת-קבוצה שלו.
NONCE_RE = re.compile(r"[A-Za-z0-9_-]{16,}")


def _client(monkeypatch, *, file_name="page.html", language="html"):
    doc = {"_id": FILE_OID, "user_id": OWNER_ID, "file_name": file_name, "code": USER_HTML,
           "programming_language": language, "is_active": True}
    monkeypatch.setattr(webapp_app, "get_db", lambda: object())
    monkeypatch.setattr(webapp_app, "_get_user_any_file_by_id", lambda db_ref, user_id, file_id: (doc, "regular"))
    client = webapp_app.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = OWNER_ID
        sess["user_data"] = {"id": OWNER_ID, "first_name": "Test"}
    return client


def _raw(client, query=""):
    resp = client.get(f"/raw_html/{FILE_OID}{query}")
    assert resp.status_code == 200
    return resp.headers["Content-Security-Policy"], resp.get_data(as_text=True)


def test_the_new_window_gets_the_file_as_it_is_with_the_policy_it_had(monkeypatch):
    csp, body = _raw(_client(monkeypatch))
    assert csp == CSP_BEFORE_THE_REPORTER
    assert body == USER_HTML


def test_scripts_without_the_reporter_keep_the_policy_they_had(monkeypatch):
    csp, body = _raw(_client(monkeypatch), "?allow=scripts")
    assert csp == CSP_SCRIPTS_BEFORE_THE_REPORTER
    assert body == USER_HTML


def test_the_preview_frame_gets_the_reporter_locked_to_a_nonce_of_this_response(monkeypatch):
    csp, body = _raw(_client(monkeypatch), f"?{html_preview_frame.REPORT_SCROLL_PARAM}=1")

    nonces = re.findall(r"script-src 'nonce-([^']+)'", csp)
    assert len(nonces) == 1, csp
    nonce = nonces[0]
    assert NONCE_RE.fullmatch(nonce), nonce
    # רק המדווח: אין 'unsafe-inline' שהיה מתיר גם את הסקריפטים של הקובץ.
    assert "'unsafe-inline'" not in csp.split("script-src", 1)[1]
    assert csp.startswith("sandbox allow-scripts; ")
    # שאר ההנחיות — כמו בחלון חדש.
    assert csp.replace("sandbox allow-scripts; ", "sandbox; ").replace(f"'nonce-{nonce}'", "'none'") == (
        CSP_BEFORE_THE_REPORTER
    )
    # הקובץ כמו שהוא, והמדווח אחריו — עם אותו nonce.
    assert body.startswith(USER_HTML)
    assert re.findall(r"<script nonce=\"([^\"]+)\">", body) == [nonce]
    assert html_preview_frame.SCROLL_MESSAGE_TYPE in body


def test_every_response_gets_its_own_nonce(monkeypatch):
    client = _client(monkeypatch)
    query = f"?{html_preview_frame.REPORT_SCROLL_PARAM}=1"
    first, _ = _raw(client, query)
    second, _ = _raw(client, query)
    assert first != second


def test_with_scripts_the_reporter_runs_without_a_nonce_that_would_block_them(monkeypatch):
    """‏``nonce`` לצד ``'unsafe-inline'`` מבטל את ``'unsafe-inline'`` — נמדד בכרומיום."""
    csp, body = _raw(_client(monkeypatch), f"?allow=scripts&{html_preview_frame.REPORT_SCROLL_PARAM}=1")
    assert csp == CSP_SCRIPTS_BEFORE_THE_REPORTER
    assert "nonce" not in csp
    assert body.startswith(USER_HTML)
    assert "<script>" in body[len(USER_HTML):]
    assert "nonce=" not in body


def test_any_other_value_of_the_parameter_does_not_add_the_reporter(monkeypatch):
    csp, body = _raw(_client(monkeypatch), f"?{html_preview_frame.REPORT_SCROLL_PARAM}=yes")
    assert csp == CSP_BEFORE_THE_REPORTER
    assert body == USER_HTML


# -- הכלל "יש לקובץ תצוגת דפדפן": ``_is_html_file``, האחד לראוט, לתבניות ולקישור הקבוע --


def test_the_html_rule_is_language_or_extension_and_survives_missing_fields():
    is_html = html_preview_frame.is_html_file
    assert is_html("html", "x")
    assert is_html("HTML", None)
    assert is_html(None, "Page.HTML")
    assert is_html("", "a.htm")
    assert not is_html("markdown", "a.md")
    assert not is_html(None, None)
    assert not is_html(5, ["a.html"])


def test_the_templates_and_the_routes_get_the_same_rule():
    """הראוט, הקישור הקבוע והתבניות — כולם אותה פונקציה, וטסט שמרנדר תבנית בסביבה משלו מוסיף אותה מאותו מקום."""
    for name, func in html_preview_frame.TEMPLATE_GLOBALS.items():
        assert webapp_app.app.jinja_env.globals.get(name) is func, name
    assert webapp_app._is_html_file is html_preview_frame.is_html_file


def test_a_file_that_is_not_html_is_sent_to_its_page(monkeypatch):
    resp = _client(monkeypatch, file_name="a.md", language="markdown").get(f"/html/{FILE_OID}")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(f"/file/{FILE_OID}")
