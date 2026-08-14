"""טסטים לתצוגת ה-SVG ב-WebApp (הראוטים /svg ו-/raw_svg)."""

from bson import ObjectId

from webapp import app as webapp_app

FILE_OID = ObjectId("0123456789abcdef01234567")
FILE_ID = str(FILE_OID)

SIMPLE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    '<circle cx="12" cy="12" r="10" fill="currentColor"/>'
    "</svg>"
)


def _make_doc(file_name="icon.svg", code=SIMPLE_SVG, language="xml"):
    return {
        "_id": FILE_OID,
        "user_id": 123,
        "file_name": file_name,
        "programming_language": language,
        "code": code,
        "is_active": True,
    }


def _client(monkeypatch, doc):
    """מחזיר test client מחובר, שכל שליפת קובץ בו מחזירה את doc."""
    monkeypatch.setattr(webapp_app, "get_db", lambda: object())
    monkeypatch.setattr(
        webapp_app,
        "_get_user_any_file_by_id",
        lambda db_ref, user_id, file_id: ((doc, "regular") if doc else (None, "")),
    )
    client = webapp_app.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 123
        sess["user_data"] = {"id": 123, "first_name": "Test"}
    return client


# --- זיהוי קובץ SVG ---------------------------------------------------------


def test_is_svg_file_matches_extension_only():
    assert webapp_app._is_svg_file("icon.svg") is True
    assert webapp_app._is_svg_file("ICON.SVG") is True
    assert webapp_app._is_svg_file("  spaced.svg  ") is True
    assert webapp_app._is_svg_file("data.xml") is False
    assert webapp_app._is_svg_file("svg") is False
    assert webapp_app._is_svg_file(None) is False


# --- השלמת xmlns ------------------------------------------------------------


def test_ensure_svg_xmlns_adds_missing_namespace():
    out = webapp_app._ensure_svg_xmlns('<svg viewBox="0 0 24 24"><path d="M0 0"/></svg>')
    assert 'xmlns="http://www.w3.org/2000/svg"' in out
    # שאר התגית נשמרת כמו שהיא
    assert 'viewBox="0 0 24 24"' in out
    assert '<path d="M0 0"/>' in out


def test_ensure_svg_xmlns_keeps_existing_namespace():
    assert webapp_app._ensure_svg_xmlns(SIMPLE_SVG) == SIMPLE_SVG
    # לא מוסיפים פעמיים
    assert webapp_app._ensure_svg_xmlns(SIMPLE_SVG).count("xmlns=") == 1


def test_ensure_svg_xmlns_ignores_input_without_svg_tag():
    assert webapp_app._ensure_svg_xmlns("not svg at all") == "not svg at all"
    assert webapp_app._ensure_svg_xmlns("") == ""


# --- עמוד התצוגה ------------------------------------------------------------


def test_svg_preview_renders_page_for_svg_file(monkeypatch):
    client = _client(monkeypatch, _make_doc())
    resp = client.get(f"/svg/{FILE_ID}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "icon.svg" in html
    # התמונה נטענת מהראוט הגולמי, לא מוטמעת בדף
    assert f"/raw_svg/{FILE_ID}" in html
    # כפתורי הרקעים קיימים
    assert 'data-bg="dark"' in html
    assert 'data-bg="light"' in html
    assert 'data-bg="grid"' in html


def test_svg_preview_redirects_for_non_svg_file(monkeypatch):
    client = _client(monkeypatch, _make_doc(file_name="script.py", language="python"))
    resp = client.get(f"/svg/{FILE_ID}")
    assert resp.status_code == 302
    assert f"/file/{FILE_ID}" in resp.headers.get("Location", "")


def test_svg_preview_returns_404_when_file_missing(monkeypatch):
    client = _client(monkeypatch, None)
    resp = client.get(f"/svg/{FILE_ID}")
    assert resp.status_code == 404


def test_svg_preview_warns_about_sprite_files(monkeypatch):
    sprite = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<symbol id="a" viewBox="0 0 24 24"><path d="M0 0"/></symbol>'
        "</svg>"
    )
    client = _client(monkeypatch, _make_doc(file_name="sprite.svg", code=sprite))
    resp = client.get(f"/svg/{FILE_ID}")
    assert resp.status_code == 200
    assert "ספרייט" in resp.get_data(as_text=True)


def test_svg_preview_has_no_sprite_warning_for_plain_icon(monkeypatch):
    client = _client(monkeypatch, _make_doc())
    resp = client.get(f"/svg/{FILE_ID}")
    assert "ספרייט" not in resp.get_data(as_text=True)


# --- הראוט הגולמי -----------------------------------------------------------


def test_raw_svg_serves_image_with_hardened_headers(monkeypatch):
    client = _client(monkeypatch, _make_doc())
    resp = client.get(f"/raw_svg/{FILE_ID}")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith("image/svg+xml")
    csp = resp.headers["Content-Security-Policy"]
    assert "sandbox;" in csp
    assert "script-src 'none'" in csp
    assert "default-src 'none'" in csp
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.get_data(as_text=True) == SIMPLE_SVG


def test_raw_svg_completes_missing_namespace(monkeypatch):
    client = _client(monkeypatch, _make_doc(code='<svg viewBox="0 0 10 10"></svg>'))
    resp = client.get(f"/raw_svg/{FILE_ID}")
    assert resp.status_code == 200
    assert 'xmlns="http://www.w3.org/2000/svg"' in resp.get_data(as_text=True)


def test_raw_svg_rejects_non_svg_file(monkeypatch):
    """הראוט מגיש image/svg+xml, ולכן אסור לו להגיש תוכן שאינו SVG."""
    doc = _make_doc(file_name="page.html", code="<h1>hi</h1>", language="html")
    client = _client(monkeypatch, doc)
    resp = client.get(f"/raw_svg/{FILE_ID}")
    assert resp.status_code == 404


def test_raw_svg_returns_404_when_file_missing(monkeypatch):
    client = _client(monkeypatch, None)
    resp = client.get(f"/raw_svg/{FILE_ID}")
    assert resp.status_code == 404


# --- הכפתור בעמוד הקובץ -----------------------------------------------------


def test_view_file_shows_svg_button(monkeypatch):
    client = _client(monkeypatch, _make_doc(file_name="Programming.svg"))
    resp = client.get(f"/file/{FILE_ID}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert f"/svg/{FILE_ID}" in html
    assert "תצוגת SVG" in html


def test_view_file_has_no_svg_button_for_other_files(monkeypatch):
    client = _client(monkeypatch, _make_doc(file_name="notes.md", code="# hi", language="markdown"))
    resp = client.get(f"/file/{FILE_ID}")
    assert resp.status_code == 200
    assert f"/svg/{FILE_ID}" not in resp.get_data(as_text=True)
