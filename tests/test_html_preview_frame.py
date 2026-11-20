"""‏``/raw_html/<id>`` ו-``/html/<id>`` — מדווח הגלילה שהפתקים על תצוגת ה-HTML נשענים עליו.

מה השרת שולח: ה-CSP של כל אחד משלושת המצבים (``webapp/html_preview_frame.py``), המדווח שמצורף רק עם
``REPORT_SCROLL_PARAM``, וה-``nonce`` שמחבר ביניהם. מה הדפדפן **עושה** עם זה — שהמדווח רץ, שהסקריפטים של הקובץ
נחסמים, ושהפתקים נעים עם הגלילה — נבדק ב-``tests/test_html_preview_notes_browser.py``: בדיקת שרת אינה אוכפת CSP.
"""

from __future__ import annotations

import re

import pytest

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


def _client(monkeypatch, *, file_name="page.html", language="html", code=USER_HTML):
    doc = {"_id": FILE_OID, "user_id": OWNER_ID, "file_name": file_name, "code": code,
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


def test_noscript_content_is_restored_only_while_the_files_scripts_are_off(monkeypatch):
    """בלי "אפשר JS" המדווח מציג את ``<noscript>`` (``_NOSCRIPT_JS``); עם — לא, כמו בדפדפן כשסקריפטים מותרים. מה
    הדפדפן מציג בפועל — ``test_noscript_content_shows_while_the_files_scripts_are_off`` בבדיקות הדפדפן."""
    client = _client(monkeypatch)
    _, default_body = _raw(client, f"?{html_preview_frame.REPORT_SCROLL_PARAM}=1")
    _, scripts_body = _raw(client, f"?allow=scripts&{html_preview_frame.REPORT_SCROLL_PARAM}=1")
    assert html_preview_frame._NOSCRIPT_JS in default_body[len(USER_HTML):]
    assert html_preview_frame._NOSCRIPT_JS not in scripts_body


def test_any_other_value_of_the_parameter_does_not_add_the_reporter(monkeypatch):
    csp, body = _raw(_client(monkeypatch), f"?{html_preview_frame.REPORT_SCROLL_PARAM}=yes")
    assert csp == CSP_BEFORE_THE_REPORTER
    assert body == USER_HTML


# -- קובץ עם CSP משלו: בלי "אפשר JS" — בלי מדווח, כמו ב"חלון חדש" (``declares_own_csp``) --

OWN_CSP_META = "<meta http-equiv=\"Content-Security-Policy\" content=\"script-src 'none'\">"
OWN_CSP_HTML = (f"<!doctype html><html><head>{OWN_CSP_META}</head>"
                "<body><noscript><p>בלי JS</p></noscript></body></html>")


def test_a_file_with_its_own_policy_is_served_without_the_reporter_while_its_scripts_are_off(monkeypatch):
    """המדיניות של הקובץ חוסמת את המדווח ממילא, ו-``allow-scripts`` היה מסתיר את ה-``<noscript>`` שלו. בלי מדווח
    ה-``sandbox`` של התשובה בלי ``allow-scripts``, והדפדפן מציג אותו —
    ``test_noscript_shows_in_a_file_with_its_own_policy`` בבדיקות הדפדפן."""
    csp, body = _raw(_client(monkeypatch, code=OWN_CSP_HTML), f"?{html_preview_frame.REPORT_SCROLL_PARAM}=1")
    assert csp == CSP_BEFORE_THE_REPORTER
    assert body == OWN_CSP_HTML


def test_with_scripts_a_file_with_its_own_policy_still_gets_the_reporter(monkeypatch):
    """במצב JS לא השתנה דבר: ``<noscript>`` מוסתר שם ממילא, והמדווח רץ כשהמדיניות של הקובץ מתירה אותו."""
    csp, body = _raw(_client(monkeypatch, code=OWN_CSP_HTML),
                     f"?allow=scripts&{html_preview_frame.REPORT_SCROLL_PARAM}=1")
    assert csp == CSP_SCRIPTS_BEFORE_THE_REPORTER
    assert body.startswith(OWN_CSP_HTML) and html_preview_frame.SCROLL_MESSAGE_TYPE in body[len(OWN_CSP_HTML):]


@pytest.mark.parametrize("html, expected", [
    (f"<!doctype html><html><head>{OWN_CSP_META}</head><body></body></html>", True),
    # בלי ``<head>`` כתוב, לפני כל תוכן — הדפדפן שם אותו בראש, והוא נאכף (נמדד)
    (f"<!doctype html>{OWN_CSP_META}<p>x</p>", True),
    # אחרי תחילת ה-body — לא נאכף (נמדד), ולכן המדווח נשאר
    (f"<!doctype html><p>x</p>{OWN_CSP_META}", False),
    (f"<!doctype html><html><head></head><body><p>x</p>{OWN_CSP_META}</body></html>", False),
    # אחרי ``</head>`` ולפני ``<body>`` — הדפדפן מחזיר אותו לראש, והוא נאכף (נמדד)
    (f"<!doctype html><html><head></head>{OWN_CSP_META}<body></body></html>", True),
    ('<META HTTP-EQUIV="content-security-policy" CONTENT="x">', True),
    # תו מקודד בערך — הדפדפן מפענח אותו לפני ההשוואה, והוא נאכף (נמדד)
    ('<meta http-equiv="Content&#45;Security-Policy" content="x">', True),
    ('<meta http-equiv="Content-Security-Policy-Report-Only" content="x">', False),
    ("<meta http-equiv>", False),
    ('<meta name="viewport" content="width=device-width">', False),
    ("", False),
], ids=["head", "first-without-head", "after-p", "in-body", "after-head-before-body", "upper-case", "char-ref",
        "report-only", "no-value", "other-meta", "empty"])
def test_the_own_policy_rule_looks_at_the_head_only(html, expected):
    assert html_preview_frame.declares_own_csp(html) is expected


def test_the_scan_stops_at_the_body_and_does_not_read_the_rest_of_the_file(monkeypatch):
    """העצירה בתחילת ה-body היא מה שהופך את הבדיקה לזולה בקובץ גדול: המפרסר מקבל רק את הנתחים עד שם."""
    fed: list[int] = []
    original = html_preview_frame._OwnCspScanner.feed

    def counting_feed(self, data):
        fed.append(len(data))
        return original(self, data)

    monkeypatch.setattr(html_preview_frame._OwnCspScanner, "feed", counting_feed)
    big = "<!doctype html><html><head><title>t</title></head><body>" + "<p>שורה</p>" * 100_000 + OWN_CSP_META
    assert html_preview_frame.declares_own_csp(big) is False
    assert fed == [html_preview_frame._SCAN_CHUNK]


def test_a_parser_failure_is_treated_as_an_own_policy_and_logged(monkeypatch, caplog):
    """``_markupbase`` של 3.11 מכיל ``raise AssertionError`` על הצהרות פגומות. כשל = הקובץ מוגש בלי סקריפטים, כמו ב"חלון
    חדש", ולא 500 — ונרשם, בלי תוכן מהקובץ."""
    def failing_feed(self, data):
        raise AssertionError("unexpected char in declaration: SECRET-FROM-THE-FILE")

    monkeypatch.setattr(html_preview_frame._OwnCspScanner, "feed", failing_feed)
    with caplog.at_level("WARNING", logger=html_preview_frame.__name__):
        assert html_preview_frame.declares_own_csp("<!x>") is True
    assert any("parser rejected" in r.getMessage() for r in caplog.records)
    assert "SECRET-FROM-THE-FILE" not in caplog.text


def test_any_other_parser_error_is_a_bug_and_propagates(monkeypatch):
    def broken_feed(self, data):
        raise TypeError("a bug")

    monkeypatch.setattr(html_preview_frame._OwnCspScanner, "feed", broken_feed)
    with pytest.raises(TypeError):
        html_preview_frame.declares_own_csp("<p>")


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
