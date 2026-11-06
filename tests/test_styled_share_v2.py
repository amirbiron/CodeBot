"""קישור השיתוף המעוצב בצורה השנייה (``styled_shares.py``): הטקסט ותמונה של הערכה, ורינדור בדפדפן של מי שפותח.

- **היצירה** שומרת את הטקסט של הגרסה כמו שהוא ואת הערכה כמו ש-``get_export_theme`` החזיר אותה; טקסט מעל
  ``STYLED_SHARE_MAX_MARKDOWN_BYTES`` (בבתים) נדחה ב-413 ולא נשמר; ``STYLED_EXPORT_BROWSER_RENDER`` כבוי שומר את הצורה
  הראשונה, כמו קודם; וגוף בקשה שגוי הוא 400.
- **העמוד** מגיש את הצורה השנייה עם ה-CSP שלה, את הטקסט כ-JSON שאינו יכול לסגור את התגית, את KaTeX רק כשיש ``$``, ואת
  הצורה הראשונה כמו שנשמרה. שתיהן ``no-cache``, כדי שקישור שבוטל לא ייפתח מעותק שמור.
- **הרשימה והביטול** — לפי הישות (שם הקובץ), ורק לבעל הקישור.

הרינדור עצמו, תחת ה-CSP האמיתי — ב-``tests/test_styled_share_browser.py``.
"""

from __future__ import annotations

import itertools
import json
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

pytest.importorskip("flask")

from services.styled_export_service import (  # noqa: E402
    COPY_CODE_SCRIPT,
    EDITOR_EXPORT_CONTENT_MARKER_TEXT,
    get_export_theme,
    styled_share_csp,
    styled_share_page_csp,
)

FILE_ID = "e" * 24
_USER_IDS = itertools.count(940_000)

MD_FILE = {
    "_id": FILE_ID,
    "file_name": "מסמך.md",
    "programming_language": "markdown",
    "code": "# כותרת\n\nטקסט עם ==מארקר==\n\n</script><script>alert(1)</script>\n",
}


class _Shares:
    def __init__(self):
        self.docs: list[dict] = []
        self.find_calls: list[tuple] = []
        self.delete_calls: list[dict] = []

    def insert_one(self, doc):
        self.docs.append(doc)
        return SimpleNamespace(inserted_id="x")

    def find_one(self, query, *args, **kwargs):
        return next((d for d in self.docs if d.get("token") == query.get("token")), None)

    def update_one(self, *args, **kwargs):
        return None

    def find(self, query, projection=None):
        self.find_calls.append((query, projection))
        matched = [dict(d) for d in self.docs if all(d.get(k) == v for k, v in query.items())]
        return _Cursor(matched)

    def delete_one(self, query):
        self.delete_calls.append(query)
        for d in list(self.docs):
            if all(d.get(k) == v for k, v in query.items()):
                self.docs.remove(d)
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)


class _Cursor(list):
    def sort(self, key, direction):
        super().sort(key=lambda d: d.get(key), reverse=direction == -1)
        return self

    def limit(self, n):
        del self[n:]
        return self


class _Db:
    def __init__(self, user_themes=None):
        self.styled_shares = _Shares()
        self.users = SimpleNamespace(find_one=lambda *a, **k: {"custom_themes": user_themes or []})

    def __getitem__(self, name):
        return getattr(self, name)


@pytest.fixture
def wa(monkeypatch):
    import webapp.app as webapp_app

    db = _Db()
    monkeypatch.setattr(webapp_app, "get_db", lambda: db)
    monkeypatch.setattr(webapp_app, "is_admin", lambda uid: False)
    monkeypatch.setattr(webapp_app, "is_premium", lambda uid: True)
    monkeypatch.setattr(webapp_app, "_get_user_any_file_by_id", lambda d, uid, fid: (dict(MD_FILE), "regular"))
    webapp_app._test_db = db
    yield webapp_app
    del webapp_app._test_db


def _client(wa, uid=None):
    c = wa.app.test_client()
    with c.session_transaction() as sess:
        sess["user_id"] = uid if uid is not None else next(_USER_IDS)
    return c


def _share(wa, client, **body):
    resp = client.post(f"/api/export/styled/{FILE_ID}/share", json={"theme": "morass", **body})
    return resp


def _json_source(html: str) -> dict:
    match = re.search(r'<script type="application/json" id="ckShareSource">(.*?)</script>', html, re.S)
    assert match, "אין את הטקסט בעמוד"
    return json.loads(match.group(1))


# ---------------------------------------------------------------------------
# היצירה
# ---------------------------------------------------------------------------

def test_a_share_stores_the_text_and_the_theme_as_they_are(wa):
    resp = _share(wa, _client(wa))

    assert resp.status_code == 200, resp.get_data(as_text=True)
    [doc] = wa._test_db.styled_shares.docs
    assert doc["format"] == 2
    assert doc["markdown"] == MD_FILE["code"]
    assert doc["theme"] == get_export_theme("morass")
    assert "styled_html" not in doc


def test_a_user_theme_is_stored_with_its_rebased_highlight_rules(wa, monkeypatch):
    theme = {"id": "mine", "name": "שלי", "variables": {"--bg-primary": "#fafafa"},
             "syntax_css": ':root[data-theme-type="custom"] .hljs-keyword { color: #c0ffee; }'}
    db = _Db(user_themes=[theme])
    monkeypatch.setattr(wa, "get_db", lambda: db)

    assert _share(wa, _client(wa), theme="mine").status_code == 200
    [doc] = db.styled_shares.docs
    assert "#c0ffee" in doc["theme"]["hljs_css"]
    assert doc["theme"]["variables"]["--bg-primary"] == "#fafafa"


def test_the_size_cap_is_in_bytes_and_refuses_instead_of_cutting(wa, monkeypatch):
    """עשרה בתים: חמש אותיות עבריות (שני בתים כל אחת) עוברות, ושש — 413, ושום דבר לא נשמר."""
    monkeypatch.setattr(wa, "STYLED_SHARE_MAX_MARKDOWN_BYTES", 10)
    client = _client(wa)

    monkeypatch.setattr(wa, "_get_user_any_file_by_id", lambda d, uid, fid: (dict(MD_FILE, code="אבגדה"), "regular"))
    assert _share(wa, client).status_code == 200

    monkeypatch.setattr(wa, "_get_user_any_file_by_id", lambda d, uid, fid: (dict(MD_FILE, code="אבגדהו"), "regular"))
    resp = _share(wa, client)
    assert resp.status_code == 413
    assert resp.get_json()["code"] == "file_too_large_to_share"
    assert [d["markdown"] for d in wa._test_db.styled_shares.docs] == ["אבגדה"]


def test_with_the_switch_off_the_share_is_built_on_the_server_as_before(wa, monkeypatch):
    monkeypatch.setattr(wa, "STYLED_EXPORT_BROWSER_RENDER", False)
    monkeypatch.setattr(wa, "STYLED_SHARE_MAX_MARKDOWN_BYTES", 1)  # התקרה היא של הצורה השנייה בלבד

    assert _share(wa, _client(wa)).status_code == 200
    [doc] = wa._test_db.styled_shares.docs
    assert "מארקר" in doc["styled_html"]
    assert "markdown" not in doc and "format" not in doc and "theme" not in doc


@pytest.mark.parametrize("body", [
    ["morass"],
    {"theme": ["morass"]},
    {"theme": "morass", "vscode_json": 5},
    # ``bool("false")`` הוא ``True``: מחרוזת הייתה הופכת קישור זמני לקבוע
    {"theme": "morass", "permanent": "false"},
    {"theme": "morass", "permanent": 1},
])
def test_a_malformed_body_is_400(wa, body):
    resp = _client(wa).post(f"/api/export/styled/{FILE_ID}/share", json=body)
    assert resp.status_code == 400
    assert resp.get_json()["code"] == "invalid_request"
    assert wa._test_db.styled_shares.docs == []


@pytest.mark.parametrize("permanent, expires", [(True, False), (False, True)])
def test_permanent_is_taken_as_the_boolean_that_was_sent(wa, permanent, expires):
    assert _share(wa, _client(wa), permanent=permanent).status_code == 200
    [doc] = wa._test_db.styled_shares.docs
    assert doc["is_permanent"] is permanent
    assert (doc["expires_at"] is not None) is expires


# ---------------------------------------------------------------------------
# העמוד
# ---------------------------------------------------------------------------

def test_the_share_page_carries_the_text_the_engine_and_its_policy(wa):
    client = _client(wa)
    token = _share(wa, client).get_json()["token"]

    resp = wa.app.test_client().get(f"/shared/styled/{token}")  # מי שפותח אינו מחובר

    assert resp.status_code == 200
    assert resp.headers["Content-Security-Policy"] == styled_share_page_csp()
    assert resp.headers["Cache-Control"] == "no-cache"
    html = resp.get_data(as_text=True)
    source = _json_source(html)
    # הטקסט מגיע כמו שהוא — גם ``</script>`` שבתוכו — ואינו סוגר את התגית
    assert source == {"markdown": MD_FILE["code"], "mermaidTheme": "dark", "marker": EDITOR_EXPORT_CONTENT_MARKER_TEXT}
    assert "</script><script>alert(1)" not in html
    assert f"<!--{EDITOR_EXPORT_CONTENT_MARKER_TEXT}-->" in html
    assert "<title>מסמך</title>" in html
    assert 'http-equiv="Content-Security-Policy"' not in html
    for script in ("js/md_preview.bundle.js", "js/live-preview.js", "js/utils/styled-export-core.js", "js/styled-share-view.js"):
        assert script in html, script
    # בלי ``$`` אין נוסחה, ולכן אין CSS של KaTeX
    assert wa.markdown_editor_katex_css() not in html


def test_katex_css_comes_only_with_a_dollar_sign(wa, monkeypatch):
    monkeypatch.setattr(wa, "_get_user_any_file_by_id", lambda d, uid, fid: (dict(MD_FILE, code="נוסחה $x^2$"), "regular"))
    token = _share(wa, _client(wa)).get_json()["token"]
    html = wa.app.test_client().get(f"/shared/styled/{token}").get_data(as_text=True)
    assert wa.markdown_editor_katex_css() in html


def test_the_share_page_policy():
    csp = dict(d.strip().split(" ", 1) for d in styled_share_page_csp().split(";"))
    assert csp["default-src"] == "'none'"
    assert csp["script-src"].split() == ["'self'", f"'{_copy_hash()}'"]
    assert csp["form-action"] == "'none'" and csp["frame-ancestors"] == "'none'" and csp["base-uri"] == "'none'"
    assert "unsafe-inline" not in csp["script-src"] and "unsafe-eval" not in csp["script-src"]


def _copy_hash():
    from services.styled_export_service import COPY_CODE_SCRIPT_CSP_HASH

    return COPY_CODE_SCRIPT_CSP_HASH


def test_a_first_form_share_is_served_as_it_was_stored(wa):
    wa._test_db.styled_shares.docs.append({"token": "old", "is_permanent": True, "styled_html": "<html>הישן</html>"})
    resp = wa.app.test_client().get("/shared/styled/old")
    assert resp.status_code == 200
    assert resp.get_data(as_text=True) == "<html>הישן</html>"
    assert resp.headers["Content-Security-Policy"] == styled_share_csp()
    assert resp.headers["Cache-Control"] == "no-cache"


@pytest.mark.parametrize("broken", [{"theme": "morass"}, {"markdown": None}, {"format": 3}])
def test_a_document_of_neither_form_is_404(wa, broken):
    doc = {"token": "bad", "is_permanent": True, "format": 2, "markdown": "# x", "theme": get_export_theme("morass")}
    doc.update(broken)
    wa._test_db.styled_shares.docs.append(doc)
    assert wa.app.test_client().get("/shared/styled/bad").status_code == 404


def test_an_expired_share_is_404(wa):
    wa._test_db.styled_shares.docs.append({
        "token": "gone", "is_permanent": False, "expires_at": datetime.now(timezone.utc) - timedelta(minutes=1),
        "format": 2, "markdown": "# x", "theme": get_export_theme("morass"),
    })
    assert wa.app.test_client().get("/shared/styled/gone").status_code == 404


def test_the_copy_script_attaches_to_content_that_arrives_later():
    """עמוד הקישור מכניס את המסמך אחרי שסקריפט ההעתקה רץ, ולכן הסקריפט משאיר פונקציה שמוסיפה כפתורים מאוחר יותר —
    ולא מוסיף כפתור שני לבלוק שכבר יש לו. ההתנהגות עצמה בדפדפן: ``tests/test_styled_share_browser.py``."""
    assert "window.ckAttachCopyButtons = attach;" in COPY_CODE_SCRIPT
    assert "if (codeBlock.querySelector(':scope > .copy-btn')) return;" in COPY_CODE_SCRIPT


# ---------------------------------------------------------------------------
# הרשימה והביטול
# ---------------------------------------------------------------------------

def _seed(wa, uid, **fields):
    doc = {"token": fields.pop("token"), "user_id": uid, "file_name": "מסמך.md", "is_permanent": False,
           "created_at": datetime.now(timezone.utc), "expires_at": datetime.now(timezone.utc) + timedelta(days=7),
           "view_count": 0, "format": 2, "markdown": "# סוד", "theme": {"name": "x"}}
    doc.update(fields)
    wa._test_db.styled_shares.docs.append(doc)
    return doc


def test_the_list_is_by_file_name_newest_first_without_heavy_fields(wa, monkeypatch):
    monkeypatch.setattr(wa, "is_premium", lambda uid: False)  # מי שכבר אינו פרימיום עדיין רואה את הקישורים שלו
    uid = next(_USER_IDS)
    now = datetime.now(timezone.utc)
    _seed(wa, uid, token="older", created_at=now - timedelta(days=2), view_count=3)
    _seed(wa, uid, token="newer", created_at=now - timedelta(hours=1), is_permanent=True, expires_at=None)
    _seed(wa, uid, token="expired", expires_at=now - timedelta(minutes=1))
    _seed(wa, uid, token="other-file", file_name="אחר.md")
    _seed(wa, uid + 1, token="other-user")

    resp = _client(wa, uid).get(f"/api/export/styled/{FILE_ID}/shares")

    assert resp.status_code == 200, resp.get_data(as_text=True)
    shares = resp.get_json()["shares"]
    assert [s["token"] for s in shares] == ["newer", "older"]
    assert shares[0]["is_permanent"] is True and shares[0]["expires_label"] is None
    assert shares[1]["expires_label"] == "עוד 7 ימים" and shares[1]["view_count"] == 3
    assert shares[1]["share_url"].endswith("/shared/styled/older")
    [(query, projection)] = wa._test_db.styled_shares.find_calls
    assert query == {"user_id": uid, "file_name": "מסמך.md"}
    assert not {"markdown", "styled_html", "theme"} & {k for k, v in projection.items() if v}


def test_the_list_requires_a_login(wa):
    resp = wa.app.test_client().get(f"/api/export/styled/{FILE_ID}/shares")
    assert resp.status_code in (301, 302, 401)


def test_revoking_deletes_only_the_owners_link(wa):
    owner = next(_USER_IDS)
    _seed(wa, owner, token="mine")

    assert _client(wa).post("/api/export/styled/shares/mine/revoke", json={}).status_code == 404  # משתמש אחר
    resp = _client(wa, owner).post("/api/export/styled/shares/mine/revoke", json={})
    assert resp.status_code == 200 and resp.get_json()["ok"] is True
    assert wa._test_db.styled_shares.docs == []
    assert wa._test_db.styled_shares.delete_calls[-1] == {"token": "mine", "user_id": owner}
    # ומי שפותח את הקישור מקבל 404
    assert wa.app.test_client().get("/shared/styled/mine").status_code == 404


def test_revoking_a_missing_link_is_404(wa):
    resp = _client(wa).post("/api/export/styled/shares/nothing/revoke", json={})
    assert resp.status_code == 404 and resp.get_json()["code"] == "not_found"


def test_revoke_is_not_a_get(wa):
    owner = next(_USER_IDS)
    _seed(wa, owner, token="safe")
    assert _client(wa, owner).get("/api/export/styled/shares/safe/revoke").status_code == 405
    assert [d["token"] for d in wa._test_db.styled_shares.docs] == ["safe"]


@pytest.mark.parametrize("form", [None, {"x": "1"}])
def test_revoke_requires_json_so_a_form_from_another_site_cannot_send_it(wa, form):
    """הקישור ציבורי. טופס מאתר אחר (``application/x-www-form-urlencoded``, או בלי גוף) שנשלח בזמן שבעליו מחובר — 415,
    והקישור נשאר."""
    owner = next(_USER_IDS)
    _seed(wa, owner, token="kept")
    resp = _client(wa, owner).post("/api/export/styled/shares/kept/revoke", data=form)
    assert resp.status_code == 415 and resp.get_json()["error"] == "json_required"
    assert [d["token"] for d in wa._test_db.styled_shares.docs] == ["kept"]
