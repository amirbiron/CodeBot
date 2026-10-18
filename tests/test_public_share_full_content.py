"""קישור שיתוף ציבורי מציג את כל הקובץ — לא רק את תחילתו, ולא עמוד ריק.

**למה הקובץ הזה קיים.** מ-#2235 (דצמבר 2025) ועד התיקון הזה, ``POST /api/share/<id>``
שמר בשיתוף רק את 2000 התווים הראשונים של הקובץ, ו-``/share/<id>`` קרא את
המסמך בלי ``code`` והציג אותם. כל כפתורי השיתוף בוובאפ — הזמני, הקבוע, "שתף
בטלגרם" — הובילו לקובץ שנקטע אחרי כמה עשרות שורות, וגם ``/share/welcome``,
מצב הקריאה ו"שמור לקבצים שלי". שיתוף שנוצר בבוט שומר את התוכן המלא ואין בו
תצוגה מקדימה, ולכן הוא הוצג **ריק**.

**למה הטסטים הקיימים לא תפסו את זה.** הם זרעו במסד שיתוף שכבר מכיל רק את
התצוגה המקדימה (כלומר קיבעו את הבאג כצורה התקינה), ודמת המונגו התעלמה מהיטלת
החרגה — ``{"code": 0}`` החזיר את ``code`` — כך שמול הדמה שיתוף הבוט נראה מלא.
לכן כאן כל שיתוף מהוובאפ **נוצר דרך הראוט עצמו**, עם אותו גוף בקשה שהכפתורים
שולחים (``requestShareLink`` ב-``view_file.html``, ``requestShareLinkMd`` ב-
``md_preview.html``), ושיתוף הבוט נוצר דרך הכותב האמיתי שלו
(``CodeSharingService._create_internal_share``). את אותה זרימה מול מונגו אמיתי
מריץ ``tests/test_snippet_hebrew_offsets_mongo.py``, שמדלג ב-CI.

מוסכמת הריפו: דמה בעבודת יד (``_fake_mongo``), בלי mongomock.
"""

from __future__ import annotations

import json
import re
import types
from urllib.parse import urlparse

import pytest
from bson import ObjectId

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _fake_mongo import FakeDB

from webapp import app as webapp_app

OWNER_ID = 5150
VISITOR_ID = 5151
FILE_OID = ObjectId("0123456789abcdef0123ab01")

#: מסמך מארקדאון ארוך פי כמה מהתקרה הישנה (2000 תווים), בעברית, כדי שחיתוך
#: כלשהו — בתווים או בבייטים — יראה מיד. הכותרת האחרונה היא הסימן שהגענו לסוף.
LONG_MD = "".join(f"## כותרת {i}\nשורה עם תוכן בעברית מספר {i}\n\n" for i in range(300))
LAST_HEADING = "כותרת 299"
LONG_PY = "".join(f"value_{i} = {i}\n" for i in range(300))


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(webapp_app, "get_db", lambda: fake)
    return fake


def _seed_file(db, file_name: str, code: str, language: str) -> str:
    db["code_snippets"].insert_one({
        "_id": FILE_OID,
        "user_id": OWNER_ID,
        "file_name": file_name,
        "code": code,
        "programming_language": language,
        "version": 1,
        "is_active": True,
    })
    return str(FILE_OID)


def _client_as(user_id: int):
    client = webapp_app.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_data"] = {"id": user_id, "first_name": "Test"}
    return client


def _share_from_the_webapp(file_id: str, *, permanent: bool) -> str:
    """יוצר שיתוף בדיוק כמו הכפתורים, ומחזיר את הנתיב שהקישור מוביל אליו."""
    resp = _client_as(OWNER_ID).post(
        f"/api/share/{file_id}",
        json={"type": "permanent" if permanent else "temporary", "permanent": permanent},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    payload = resp.get_json()
    assert payload["ok"] is True
    return urlparse(payload["url"]).path


def _md_text(html: str):
    """התוכן שהעמוד מעביר לרינדור בצד הלקוח — בדיוק מה שהדפדפן יציג."""
    match = re.search(r'<script type="application/json" id="mdText">(.*?)</script>', html, re.S)
    assert match, "העמוד לא נשא את בלוק ה-mdText"
    return json.loads(match.group(1))


@pytest.mark.parametrize("permanent", [False, True], ids=["temporary", "permanent"])
def test_a_markdown_share_from_the_webapp_shows_the_whole_file(db, permanent):
    path = _share_from_the_webapp(_seed_file(db, "guide.md", LONG_MD, "markdown"), permanent=permanent)

    # הכפתורים ב-md_preview מוסיפים ?view=md לקישור שהשרת החזיר
    resp = webapp_app.app.test_client().get(path + "?view=md")

    assert resp.status_code == 200
    assert _md_text(resp.get_data(as_text=True)) == LONG_MD


def test_the_share_document_holds_the_whole_file_and_no_preview(db):
    path = _share_from_the_webapp(_seed_file(db, "guide.md", LONG_MD, "markdown"), permanent=True)
    share_id = path.rsplit("/", 1)[-1]

    stored = db["internal_shares"].find_one({"share_id": share_id})

    assert stored["code"] == LONG_MD
    assert "snippet_preview" not in stored
    assert stored["source_file_id"] == FILE_OID


def test_the_code_view_of_a_shared_file_reaches_the_last_line(db):
    path = _share_from_the_webapp(_seed_file(db, "values.py", LONG_PY, "python"), permanent=False)

    html = webapp_app.app.test_client().get(path).get_data(as_text=True)

    assert "value_299" in html


def test_reader_mode_of_a_shared_markdown_file_reaches_the_end(db):
    path = _share_from_the_webapp(_seed_file(db, "guide.md", LONG_MD, "markdown"), permanent=False)
    share_id = path.rsplit("/", 1)[-1]

    resp = webapp_app.app.test_client().get(f"/read/share/{share_id}")

    assert resp.status_code == 200
    assert LAST_HEADING in resp.get_data(as_text=True)


def test_saving_a_shared_file_to_my_files_saves_the_whole_file(db, monkeypatch):
    monkeypatch.setattr(webapp_app, "cache", types.SimpleNamespace(
        invalidate_user_cache=lambda *_a, **_k: 0,
        invalidate_file_related=lambda *_a, **_k: 0,
    ))
    path = _share_from_the_webapp(_seed_file(db, "guide.md", LONG_MD, "markdown"), permanent=True)
    share_id = path.rsplit("/", 1)[-1]

    resp = _client_as(VISITOR_ID).post("/api/shared/save", json={"share_id": share_id})

    assert resp.status_code == 200, resp.get_json()
    saved = db["code_snippets"].find_one({"user_id": VISITOR_ID})
    assert saved["code"] == LONG_MD


def test_a_share_made_by_the_bot_is_not_an_empty_page(db, monkeypatch):
    """הבוט שומר ``code`` מלא בלי תצוגה מקדימה — העמוד הציג אותו ריק עד התיקון."""
    import database
    import integrations

    monkeypatch.setattr(
        database, "db",
        types.SimpleNamespace(internal_shares_collection=db["internal_shares"]),
        raising=False,
    )
    result = integrations.CodeSharingService()._create_internal_share(
        "guide.md", LONG_MD, "markdown", "שיתוף פנימי של guide.md",
    )

    resp = webapp_app.app.test_client().get(urlparse(result["url"]).path + "?view=md")

    assert resp.status_code == 200
    assert _md_text(resp.get_data(as_text=True)) == LONG_MD


def test_the_welcome_guide_is_shown_whole():
    guide = webapp_app.USER_GUIDE_PATH.read_text(encoding="utf-8")

    resp = webapp_app.app.test_client().get(f"/share/{webapp_app.WELCOME_GUIDE_PRIMARY_SHARE_ID}?view=md")

    assert resp.status_code == 200
    assert _md_text(resp.get_data(as_text=True)) == guide


def test_a_share_without_content_is_a_404_and_is_counted(db, monkeypatch):
    """לא עמוד ריק עם 200 — כך בדיוק הוסתרו שיתופי הבוט. ובלי ``share_id`` באירוע:
    זה הטוקן שפותח את הקישור."""
    events = []
    monkeypatch.setattr(webapp_app, "emit_event", lambda name, *_a, **fields: events.append((name, fields)))
    db["internal_shares"].insert_one({
        "share_id": "nocontent01",
        "file_name": "guide.md",
        "language": "markdown",
        "mode": "preview",
        "source_file_id": FILE_OID,
    })
    client = webapp_app.app.test_client()

    assert client.get("/share/nocontent01?view=md").status_code == 404
    assert client.get("/read/share/nocontent01").status_code == 404

    counted = [fields for name, fields in events if name == "share_without_content"]
    assert len(counted) == 2
    assert all("nocontent01" not in json.dumps(fields, default=str) for fields in counted)


def test_an_empty_file_is_shared_as_empty_not_as_missing(db):
    path = _share_from_the_webapp(_seed_file(db, "empty.md", "", "markdown"), permanent=False)

    resp = webapp_app.app.test_client().get(path + "?view=md")

    assert resp.status_code == 200
    assert _md_text(resp.get_data(as_text=True)) == ""


# --------------------------------------------------------------------------
# משך הקישור הזמני במודאל השיתוף
# --------------------------------------------------------------------------

TEMPORARY_BUTTON = re.compile(r'data-testid="share-link-temporary">\s*<i[^>]*></i>\s*([^<]*?)\s*</button>')


@pytest.mark.parametrize(
    "days, label",
    [(7, "7 ימים"), (1, "יום אחד"), (2, "יומיים"), (30, "30 ימים")],
)
@pytest.mark.parametrize("page", ["/md/{}", "/file/{}"], ids=["md_preview", "view_file"])
def test_the_temporary_link_button_says_how_long_it_lasts(db, monkeypatch, page, days, label):
    """התווית נגזרת מ-``PUBLIC_SHARE_TTL_DAYS`` — אותו קבוע שקובע את ``expires_at``."""
    monkeypatch.setattr(webapp_app, "PUBLIC_SHARE_TTL_DAYS", days)
    file_id = _seed_file(db, "guide.md", LONG_MD, "markdown")

    resp = _client_as(OWNER_ID).get(page.format(file_id) + "?nc=1")

    assert resp.status_code == 200, resp.status_code
    html = resp.get_data(as_text=True)
    match = TEMPORARY_BUTTON.search(html)
    assert match, "כפתור הקישור הזמני לא נמצא במודאל"
    assert match.group(1) == f"קישור זמני ({label})"
    assert f"פג תוקף אחרי {label}" in html


def test_the_temporary_link_lasts_what_the_button_says(db, monkeypatch):
    monkeypatch.setattr(webapp_app, "PUBLIC_SHARE_TTL_DAYS", 3)
    path = _share_from_the_webapp(_seed_file(db, "guide.md", LONG_MD, "markdown"), permanent=False)

    stored = db["internal_shares"].find_one({"share_id": path.rsplit("/", 1)[-1]})

    assert (stored["expires_at"] - stored["created_at"]).total_seconds() == 3 * 24 * 3600
