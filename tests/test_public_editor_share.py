"""הקישור הציבורי מהעורך (``/markdown-editor``, "צור קישור"): מה השרת שומר, מה הוא דוחה, העמוד, והמחיקות.

- **היצירה** (``markdown_editor_create_share``) — בלי התחברות. נשמרים הטקסט כמו שהוא והערכה כמו ש-``get_export_theme``
  החזיר אותה (``markdown_share_fields``, אותה פונקציה של הכותב של המחוברים), עם ``origin`` של העורך, בלי תוקף, ועם
  ה-hash של מפתח המחיקה — לא המפתח. כל סירוב בקוד משלו, ואף סירוב אינו שומר דבר.
- **העמוד** (``public_shared_styled``) — אותו מנוע ואותו CSP של קישור המחוברים, ובלי באנר של שם קובץ, עם ההודעה שהתוכן
  של גולש ועם ``noindex``.
- **המחיקה** — של היוצר במפתח, ושל אדמין בקישור שהודבק.

הרינדור בדפדפן, ושהטקסט לא יוצא בלי לחיצה — ב-``tests/test_public_editor_share_browser.py``.
"""

from __future__ import annotations

import ast
import hashlib
import itertools
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

pytest.importorskip("flask")

from services.styled_export_service import (  # noqa: E402
    EDITOR_EXPORT_DEFAULT_TITLE,
    get_export_theme,
    styled_share_page_csp,
)
from styled_shares import STYLED_SHARE_TOKEN_RE, markdown_share_fields  # noqa: E402

CREATE = "/api/markdown-editor/share"
DELETE = "/api/markdown-editor/share/delete"
ADMIN_DELETE = "/admin/styled-shares/delete"
DOC = "# מדריך קצר\n\nטקסט עם ==מארקר== ו-$x^2$\n\n</script><script>alert(1)</script>\n"
REPO_ROOT = Path(__file__).resolve().parent.parent

# כתובת IP משלו לכל client: מגבלת הקצב לכל גולש (``PUBLIC_SHARE_RATE_LIMIT``) סופרת לפי ``_client_rate_key``, והאחסון
# שלה משותף לכל הטסטים בתהליך — כמו ב-``tests/test_markdown_editor_export_browser.py``
_ADDRESSES = itertools.count(1)
_IDS = itertools.count(1)


class _Shares:
    """אוסף ``styled_shares`` מדומה: שוויון על כל שדה, ו-``$gte`` — מה שהראוטים כאן שואלים."""

    def __init__(self):
        self.docs: list[dict] = []
        self.count_error: Exception | None = None
        self.read_back = True

    @staticmethod
    def _matches(doc, query):
        for key, want in query.items():
            if isinstance(want, dict) and "$gte" in want:
                if doc.get(key) is None or doc[key] < want["$gte"]:
                    return False
            elif doc.get(key) != want:
                return False
        return True

    @staticmethod
    def _project(doc, projection):
        if not projection:
            return dict(doc)
        return {k: v for k, v in doc.items() if projection.get(k)}

    def count_documents(self, query):
        if self.count_error is not None:
            raise self.count_error
        return sum(1 for d in self.docs if self._matches(d, query))

    def insert_one(self, doc):
        stored = dict(doc, _id=f"id{next(_IDS)}")
        self.docs.append(stored)
        return SimpleNamespace(inserted_id=stored["_id"])

    def find_one(self, query, projection=None):
        if "_id" in query and not self.read_back:
            return None
        doc = next((d for d in self.docs if self._matches(d, query)), None)
        return None if doc is None else self._project(doc, projection)

    def update_one(self, *args, **kwargs):
        return None

    def delete_one(self, query):
        doc = next((d for d in self.docs if self._matches(d, query)), None)
        if doc is None:
            return SimpleNamespace(deleted_count=0)
        self.docs.remove(doc)
        return SimpleNamespace(deleted_count=1)

    def find_one_and_delete(self, query, projection=None):
        doc = next((d for d in self.docs if self._matches(d, query)), None)
        if doc is None:
            return None
        self.docs.remove(doc)
        return self._project(doc, projection)


class _Db:
    def __init__(self):
        self.styled_shares = _Shares()

    def __getitem__(self, name):
        return getattr(self, name)


@pytest.fixture
def wa(monkeypatch):
    import webapp.app as webapp_app

    db = _Db()
    events: list[tuple] = []
    monkeypatch.setattr(webapp_app, "get_db", lambda: db)
    monkeypatch.setattr(webapp_app, "is_admin", lambda uid: uid == 1)
    monkeypatch.setattr(webapp_app, "emit_event", lambda name, severity="info", **f: events.append((name, severity, f)))
    webapp_app._test_db = db
    webapp_app._test_events = events
    yield webapp_app
    del webapp_app._test_db
    del webapp_app._test_events


def _guest(wa):
    c = wa.app.test_client()
    c.environ_base["HTTP_X_FORWARDED_FOR"] = f"192.0.2.{next(_ADDRESSES) % 250 + 1}"
    return c


def _admin(wa, uid=1):
    c = _guest(wa)
    with c.session_transaction() as sess:
        sess["user_id"] = uid
    return c


def _create(wa, client=None, **body):
    return (client or _guest(wa)).post(CREATE, json={"markdown": DOC, "theme": "morass", **body})


def _created(wa, **body):
    resp = _create(wa, **body)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    data = resp.get_json()
    token, key = urlsplit(data["delete_url"]).fragment.removeprefix("delete=").split(".")
    return data, token, key


def _delete(wa, token, key, client=None):
    """מחיקה כמו שהעורך שולח אותה: המזהה בגוף, והמפתח בכותרת ``Authorization`` (``markdown_editor_delete_share``)."""
    return (client or _guest(wa)).post(DELETE, json={"token": token}, headers={"Authorization": f"Bearer {key}"})


def _source(html: str) -> dict:
    match = re.search(r'<script type="application/json" id="ckShareSource">(.*?)</script>', html, re.S)
    assert match, "אין את הטקסט בעמוד"
    return json.loads(match.group(1))


# ---------------------------------------------------------------------------
# היצירה
# ---------------------------------------------------------------------------


def test_a_guest_creates_a_permanent_link_and_only_the_key_hash_is_stored(wa):
    data, token, key = _created(wa)

    [doc] = wa._test_db.styled_shares.docs
    assert doc["origin"] == "public_editor"
    # הצורה השנייה, מאותה פונקציה של הכותב של המחוברים: הטקסט כמו שהוא, והערכה כמו ש-``get_export_theme`` החזיר אותה
    assert {k: doc[k] for k in ("format", "markdown", "theme")} == markdown_share_fields(DOC, get_export_theme("morass"))
    assert doc["theme_id"] == "morass"
    # קבוע: ``None`` ולא תאריך, כדי שה-TTL ידלג עליו
    assert doc["expires_at"] is None and doc["is_permanent"] is True
    assert "user_id" not in doc and "file_name" not in doc
    assert isinstance(doc["created_at"], datetime) and doc["created_at"].tzinfo is not None
    # המפתח עצמו אינו במסד — רק ה-hash שלו
    assert doc["delete_key_sha256"] == hashlib.sha256(key.encode()).hexdigest()
    assert key not in json.dumps(doc, default=str)
    assert doc["token"] == token and STYLED_SHARE_TOKEN_RE.fullmatch(token) and STYLED_SHARE_TOKEN_RE.fullmatch(key)
    assert token != key

    assert urlsplit(data["share_url"]).path == f"/shared/styled/{token}"
    assert urlsplit(data["delete_url"]).path == "/markdown-editor"


def test_the_creation_answer_is_not_cached_and_the_event_carries_no_secret(wa):
    resp = _create(wa)
    data = resp.get_json()
    token, key = urlsplit(data["delete_url"]).fragment.removeprefix("delete=").split(".")

    assert resp.headers["Cache-Control"] == "no-store"
    [(name, severity, fields)] = [e for e in wa._test_events if e[0] == "public_editor_share_created"]
    assert severity == "info" and fields == {"theme_id": "morass", "markdown_bytes": len(DOC.encode("utf-8"))}
    assert token not in repr(wa._test_events) and key not in repr(wa._test_events)


def test_a_form_post_is_refused(wa):
    """טופס מאתר אחר לא יכול לשלוח ``Content-Type`` של JSON — ולכן גם לא ליצור קישור מהדפדפן של מבקר."""
    resp = _guest(wa).post(CREATE, data={"markdown": DOC, "theme": "morass"})
    assert resp.status_code == 415 and resp.get_json() == {"ok": False, "error": "json_required"}
    assert wa._test_db.styled_shares.docs == []


@pytest.mark.parametrize(
    "body",
    [
        [DOC],
        "just a string",
        {"markdown": ["not", "text"], "theme": "morass"},
        {"markdown": DOC, "theme": ["morass"]},
        {"markdown": DOC, "theme": {"id": "morass"}},
        {"theme": "morass"},
    ],
)
def test_a_malformed_body_is_a_bad_request(wa, body):
    resp = _guest(wa).post(CREATE, json=body)
    assert resp.status_code == 400 and resp.get_json() == {"ok": False, "error": "invalid_request"}
    assert wa._test_db.styled_shares.docs == []


def test_a_theme_outside_the_closed_list_is_refused(wa):
    resp = _create(wa, theme="tech-guide-dark")  # ערכת ייצוא אמיתית, אבל לא של העורך
    assert resp.status_code == 400 and resp.get_json()["error"] == "unknown_theme"
    assert wa._test_db.styled_shares.docs == []


def test_an_empty_document_is_refused(wa):
    resp = _create(wa, markdown="  \n\t ")
    assert resp.status_code == 400 and resp.get_json()["error"] == "empty_document"


def test_a_lone_surrogate_is_a_bad_request_and_not_a_server_error(wa):
    resp = _guest(wa).post(CREATE, data='{"markdown": "\\ud800", "theme": "morass"}', content_type="application/json")
    assert resp.status_code == 400 and resp.get_json()["error"] == "invalid_request"


def test_the_text_ceiling_is_in_utf8_bytes_and_refuses_instead_of_cutting(wa, monkeypatch):
    """עברית היא שני בתים לאות: טקסט שעובר את התקרה בבתים ולא בתווים נדחה. ובקרה: אותו מספר תווים ב-ASCII עובר."""
    monkeypatch.setattr(wa, "STYLED_SHARE_MAX_MARKDOWN_BYTES", 10)
    hebrew = "שלום עולם"  # 9 תווים, 17 בתים
    resp = _create(wa, markdown=hebrew)
    assert resp.status_code == 413 and resp.get_json()["error"] == "document_too_large"
    assert wa._test_db.styled_shares.docs == []

    assert _create(wa, markdown="a" * 10).status_code == 200


def test_a_body_over_its_ceiling_is_refused_before_it_is_read(wa, monkeypatch):
    monkeypatch.setattr(wa, "MARKDOWN_EDITOR_PUBLIC_SHARE_MAX_BODY_BYTES", 100)
    resp = _create(wa, markdown="x" * 200)
    assert resp.status_code == 413 and resp.get_json() == {"ok": False, "error": "document_too_large"}
    assert wa._test_db.styled_shares.docs == []


def test_the_body_ceiling_fits_the_worst_json_expansion_of_the_text_ceiling(wa):
    """``JSON.stringify`` כותב תו בקרה כ-``\\u0001`` — שישה בתים לבית אחד, היחס הגבוה ביותר. טקסט בתקרה שכולו תווי
    בקרה עדיין נכנס בגוף."""
    from webapp.markdown_editor import PUBLIC_SHARE_MAX_BODY_BYTES
    from styled_shares import STYLED_SHARE_MAX_MARKDOWN_BYTES

    worst = json.dumps({"markdown": "\u0001" * STYLED_SHARE_MAX_MARKDOWN_BYTES, "theme": "pen-paper-coffee"})
    assert len(worst.encode("utf-8")) <= PUBLIC_SHARE_MAX_BODY_BYTES


def test_the_daily_ceiling_counts_only_recent_links_from_the_editor(wa):
    from webapp.markdown_editor import PUBLIC_SHARE_DAILY_LIMIT

    now = datetime.now(timezone.utc)
    shares = wa._test_db.styled_shares
    # מתחת לתקרה באחד, ולצידם קישורים שאינם נספרים: ישנים מ-24 שעות, ושל משתמשים מחוברים
    shares.docs.extend({"origin": "public_editor", "created_at": now - timedelta(hours=1)} for _ in range(PUBLIC_SHARE_DAILY_LIMIT - 1))
    shares.docs.extend({"origin": "public_editor", "created_at": now - timedelta(hours=25)} for _ in range(5))
    shares.docs.extend({"user_id": 7, "created_at": now} for _ in range(5))

    assert _create(wa).status_code == 200  # האחרון שנכנס
    before = len(shares.docs)
    resp = _create(wa)
    assert resp.status_code == 429 and resp.get_json() == {"ok": False, "error": "daily_limit_reached"}
    assert len(shares.docs) == before
    assert ("public_editor_share_rejected", "warning") in [(n, s) for n, s, _f in wa._test_events]


def test_a_failed_count_creates_nothing(wa):
    """בלי הספירה אין תקרה — ולכן לא יוצרים (fail-closed), ולא ממשיכים כאילו הספירה החזירה אפס."""
    wa._test_db.styled_shares.count_error = RuntimeError("db down")
    resp = _create(wa)
    assert resp.status_code == 500 and resp.get_json()["error"] == "server_error"
    assert wa._test_db.styled_shares.docs == []


def test_a_link_that_cannot_be_read_back_is_not_handed_out(wa):
    wa._test_db.styled_shares.read_back = False
    resp = _create(wa)
    assert resp.status_code == 500 and "share_url" not in resp.get_json()


def test_the_per_visitor_limit_is_wired_to_the_route(wa):
    """המגבלה לכל גולש היא של Flask-Limiter. כאן נבדק החיווט — מה שהמגביל עצמו שואל על הראוט — ולא הספירה: ב-CI
    האחסון שלו הוא Redis, וזו התנהגות של הספרייה. ``override_defaults`` (ברירת המחדל של ``limit``) — המגבלה הגורפת
    לא נוספת עליה."""
    from limits import parse_many
    from webapp.markdown_editor import PUBLIC_SHARE_RATE_LIMIT

    assert wa.limiter is not None
    with wa.app.test_request_context(CREATE, method="POST"):
        defaults, decorated = wa.limiter.limit_manager.resolve_limits(wa.app, "markdown_editor_create_share", None)
    assert defaults == []
    assert sorted(str(limit.limit) for limit in decorated) == sorted(str(item) for item in parse_many(PUBLIC_SHARE_RATE_LIMIT))
    assert all(limit.key_func is wa._client_rate_key for limit in decorated)
    assert parse_many(PUBLIC_SHARE_RATE_LIMIT) == parse_many("3 per hour;9 per day")


def test_both_writers_build_the_markdown_shape_in_the_shared_function():
    """שני כותבים לאוסף (``derived-field-added-to-one-writer``): כל פונקציה בקוד שכותבת ל-``styled_shares`` חייבת לבנות
    את הצורה השנייה ב-``markdown_share_fields``. הסריקה על כל קובצי הפייתון ולא על רשימת כותבים, כדי שכותב שלישי לא
    יעבור בלי שאיש ידע. הבדיקה ההתנהגותית של כל כותב — כאן ובטסט של המחוברים (``tests/test_styled_share_v2.py``).

    **הכותב מזוהה בצורת הקריאה, ורק אחר כך נקרא הגוף שלו** — כמו ב-``_functions_inserting_versions``
    (``tests/test_mcp_description_age.py``). ``ast.get_source_segment`` מפצל את כל הקובץ לשורות בכל קריאה, וקריאה שלו
    לכל פונקציה ב-``webapp/app.py`` לקחה 8.5 שניות (נמדד מקומית ב-8.11.2026), וב-CI, תחת xdist, עברה את תקרת ה-60. לכן הגוף נחתך מרשימת שורות
    שמפוצלת פעם אחת לכל קובץ, ורק לפונקציות שיש בהן ``insert_one``."""
    writers = []
    for path in REPO_ROOT.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT)
        if rel.parts[0] in {"tests", "node_modules", ".git"} or "site-packages" in rel.parts:
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        if "STYLED_SHARES_COLLECTION" not in source:
            continue
        lines = source.splitlines()
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            inserts = any(
                isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute) and inner.func.attr == "insert_one"
                for inner in ast.walk(node)
            )
            if not inserts:
                continue
            body = "\n".join(lines[node.lineno - 1:node.end_lineno])
            if "STYLED_SHARES_COLLECTION" in body:
                writers.append((rel.as_posix(), node.name, "markdown_share_fields" in body))
    assert {(p, n) for p, n, _ in writers} == {
        ("webapp/app.py", "api_create_styled_share"),
        ("webapp/app.py", "markdown_editor_create_share"),
    }, writers
    assert all(uses for _p, _n, uses in writers), writers


# ---------------------------------------------------------------------------
# העמוד
# ---------------------------------------------------------------------------


def test_the_page_carries_the_notice_and_noindex_under_the_share_policy(wa):
    data, token, _key = _created(wa)
    resp = _guest(wa).get(urlsplit(data["share_url"]).path)
    html = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert resp.headers.get_all("Content-Security-Policy") == [styled_share_page_csp()]
    assert resp.headers["X-Robots-Tag"] == "noindex, nofollow"
    assert resp.headers["Cache-Control"] == "no-cache"
    assert '<meta name="robots" content="noindex, nofollow">' in html
    assert 'data-testid="public-editor-share-notice"' in html
    # בלי באנר של שם קובץ (אין קובץ), ובלי תגיות של תצוגה מקדימה
    assert "<header>" not in html and "og:" not in html
    assert f"<title>{EDITOR_EXPORT_DEFAULT_TITLE}</title>" in html
    source = _source(html)
    assert source["markdown"] == DOC and source["publicEditor"] is True and source["mermaidTheme"] == "dark"
    # ``$`` בטקסט — ה-CSS של KaTeX נכנס
    assert "KaTeX_Math" in html


def test_a_share_from_a_signed_in_user_keeps_its_page(wa):
    """בקרה לדגל: קישור של מחובר (בלי ``origin``) נשאר בלי ההודעה ובלי ``noindex``, עם הבאנר של שם הקובץ."""
    wa._test_db.styled_shares.docs.append({
        "token": "t" * 43, "user_id": 7, "file_name": "מסמך.md", "is_permanent": True, "expires_at": None,
        **markdown_share_fields("# שלום\n", get_export_theme("morass")),
    })
    resp = _guest(wa).get(f"/shared/styled/{'t' * 43}")
    html = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert "X-Robots-Tag" not in resp.headers
    assert 'name="robots"' not in html and "public-editor-share-notice" not in html
    assert "<header>" in html and "publicEditor" not in _source(html)


def test_a_public_editor_document_without_the_markdown_shape_is_not_found(wa):
    wa._test_db.styled_shares.docs.append({
        "token": "u" * 43, "origin": "public_editor", "is_permanent": True, "styled_html": "<p>x</p>",
    })
    assert _guest(wa).get(f"/shared/styled/{'u' * 43}").status_code == 404


# ---------------------------------------------------------------------------
# המחיקה של היוצר
# ---------------------------------------------------------------------------


def test_the_creator_deletes_with_the_key_and_the_link_stops_opening(wa):
    data, token, key = _created(wa)
    page = urlsplit(data["share_url"]).path
    assert _guest(wa).get(page).status_code == 200  # בקרה

    resp = _delete(wa, token, key)
    assert resp.status_code == 200 and resp.get_json() == {"ok": True}
    assert wa._test_db.styled_shares.docs == []
    assert _guest(wa).get(page).status_code == 404
    # שוב — כבר אין מה למחוק
    assert _delete(wa, token, key).status_code == 404


def test_a_wrong_key_deletes_nothing(wa):
    _data, token, key = _created(wa)
    other = ("A" if key[0] != "A" else "B") + key[1:]
    resp = _delete(wa, token, other)
    assert resp.status_code == 404 and resp.get_json()["error"] == "not_found"
    assert len(wa._test_db.styled_shares.docs) == 1


def test_a_key_cannot_delete_a_signed_in_users_link(wa):
    """המחיקה מסננת גם לפי ``origin``: גם מסמך של מחובר שבמקרה היה נושא hash תואם לא נמחק במסלול הזה."""
    key = "k" * 43
    wa._test_db.styled_shares.docs.append({
        "token": "v" * 43, "user_id": 7, "delete_key_sha256": hashlib.sha256(key.encode()).hexdigest(),
    })
    assert _delete(wa, "v" * 43, key).status_code == 404
    assert len(wa._test_db.styled_shares.docs) == 1


@pytest.mark.parametrize(
    "body, authorization",
    [
        ({"token": "x" * 43}, None),
        ({"token": "x" * 43}, "Bearer "),
        ({"token": "x" * 43}, "Basic " + "y" * 43),
        ({"token": "x" * 43}, "Bearer " + "y" * 42 + "!"),
        ({"token": "short"}, "Bearer " + "y" * 43),
        ({"token": 5}, "Bearer " + "y" * 43),
        (["x"], "Bearer " + "y" * 43),
    ],
)
def test_a_malformed_delete_is_a_bad_request(wa, body, authorization):
    headers = {"Authorization": authorization} if authorization is not None else {}
    resp = _guest(wa).post(DELETE, json=body, headers=headers)
    assert resp.status_code == 400 and resp.get_json()["error"] == "invalid_request"


def test_the_delete_key_is_not_taken_from_the_body(wa):
    """המפתח רק בכותרת ``Authorization``: את גוף ה-JSON Sentry מצרף לאירועים שבזמן הבקשה, ואת הכותרת הוא מסיר
    (``markdown_editor_delete_share``). מפתח נכון בגוף — לא מוחק."""
    _data, token, key = _created(wa)
    resp = _guest(wa).post(DELETE, json={"token": token, "key": key})
    assert resp.status_code == 400
    assert len(wa._test_db.styled_shares.docs) == 1


def test_a_delete_must_be_json(wa):
    resp = _guest(wa).post(DELETE, data={"token": "x" * 43}, headers={"Authorization": "Bearer " + "y" * 43})
    assert resp.status_code == 415


# ---------------------------------------------------------------------------
# המחיקה של אדמין
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "form",
    [
        lambda url, token: url,
        lambda url, token: token,
        lambda url, token: urlsplit(url).path,
        lambda url, token: f"  {urlsplit(url).netloc}{urlsplit(url).path}  ",
        lambda url, token: f"{url}#section",
    ],
)
def test_an_admin_deletes_a_reported_link_by_what_was_pasted(wa, form):
    data, token, _key = _created(wa)
    resp = _admin(wa).post(ADMIN_DELETE, json={"link": form(data["share_url"], token)})

    assert resp.status_code == 200 and resp.get_json() == {"ok": True, "origin": "public_editor"}
    assert wa._test_db.styled_shares.docs == []
    [(severity, fields)] = [(s, f) for n, s, f in wa._test_events if n == "styled_share_admin_deleted"]
    # בלי מזהה מפורש: מי מחק מגיע מההקשר של הבקשה, מטושטש (``bind_user_context``)
    assert severity == "warning" and fields == {"origin": "public_editor"}


def test_an_admin_also_deletes_a_signed_in_users_link(wa):
    wa._test_db.styled_shares.docs.append({"token": "w" * 43, "user_id": 7})
    resp = _admin(wa).post(ADMIN_DELETE, json={"link": f"https://ck.example/shared/styled/{'w' * 43}"})
    assert resp.status_code == 200 and resp.get_json()["origin"] == "file"


@pytest.mark.parametrize(
    "link",
    [
        "", "hello", "https://ck.example/markdown-editor", "https://ck.example/share/abc",
        "https://ck.example/shared/styled/short", ["x"],
        # ראוט אחר עם פרמטר באותו שם (``public_shared_files``) — המזהה שלו אינו של קישור מעוצב
        f"https://ck.example/shared/{'x' * 43}",
        # מארח פגום: ``urlparse`` זורק ``ValueError`` — סירוב, ולא 500
        f"https://[ck.example/shared/styled/{'x' * 43}",
        f"ck.example]/shared/styled/{'x' * 43}",
    ],
)
def test_an_admin_paste_that_is_not_a_styled_link_is_refused(wa, link):
    _created(wa)
    resp = _admin(wa).post(ADMIN_DELETE, json={"link": link})
    assert resp.status_code == 400 and resp.get_json()["error"] == "invalid_link"
    assert len(wa._test_db.styled_shares.docs) == 1


def test_an_admin_delete_of_a_missing_link_is_not_found(wa):
    resp = _admin(wa).post(ADMIN_DELETE, json={"link": "z" * 43})
    assert resp.status_code == 404 and resp.get_json()["error"] == "not_found"


def test_only_an_admin_deletes(wa):
    _data, token, _key = _created(wa)
    assert _guest(wa).post(ADMIN_DELETE, json={"link": token}).status_code == 401
    assert _admin(wa, uid=2).post(ADMIN_DELETE, json={"link": token}).status_code == 403
    assert len(wa._test_db.styled_shares.docs) == 1


def test_the_admin_page_is_for_admins(wa):
    assert _admin(wa).get("/admin/styled-shares").status_code == 200
    assert _admin(wa, uid=2).get("/admin/styled-shares").status_code == 403


# ---------------------------------------------------------------------------
# עמוד העורך
# ---------------------------------------------------------------------------


def test_the_editor_page_wires_the_share_button_to_the_routes_and_ceiling(wa):
    from styled_shares import STYLED_SHARE_MAX_MARKDOWN_BYTES

    html = _guest(wa).get("/markdown-editor").get_data(as_text=True)
    box = re.search(r"<div class=\"md-editor-share\"[^>]*>", html)
    assert box, "אין את האזור של הקישור"
    assert f'data-share-url="{CREATE}"' in box.group(0)
    assert f'data-delete-url="{DELETE}"' in box.group(0)
    assert f'data-max-bytes="{STYLED_SHARE_MAX_MARKDOWN_BYTES}"' in box.group(0)
    assert 'data-md-editor-share-action="create"' in html


def test_the_editor_heading_and_lead(wa):
    html = _guest(wa).get("/markdown-editor").get_data(as_text=True)
    assert re.search(r"<h1[^>]*>עורך Markdown בעברית</h1>", html)
    assert re.search(r'<p class="md-editor-page__lead">בלי הרשמה\. הטיוטה נשמרת בדפדפן, גם אם תצא ותחזור\.</p>', html)
    # ה-``<title>`` לא השתנה
    assert "<title>עורך Markdown אונליין עם תצוגה חיה — CodeKeeper</title>" in html
