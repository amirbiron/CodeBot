"""אזהרה לצד קוד שמוצג בוובאפ, כשיש בו תווים שמשנים את סדר התצוגה.

תווי embedding, override ו-isolate (תשעת התווים של Trojan Source) נשמרים כמו
שנשלחו, ולכן העמוד שמציג את הקוד הוא זה שצריך להזהיר עליהם — לא רק הודעת
השמירה בבוט. הטסט עובר דרך ה-HTTP client: העמוד הציבורי ``/share/<id>``
(בלי התחברות) ותצוגת הבעלים ``/file/<id>``, שתיהן מרנדרות ``view_file.html``.
האזהרה נמצאת לפי ``data-testid`` (המצב שרונדר), ומספרי השורות לפי הטקסט.

מוסכמת הריפו: דמה בעבודת יד, בלי mongomock (``wired_mongo`` מדלג ב-CI כשאין
מונגו). תווי כיווניות כתובים רק כ-escapes (H1).
"""

from __future__ import annotations

import re
from typing import Any, Dict

import pytest
from bson import ObjectId

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _fake_mongo import FakeDB

from webapp import app as webapp_app

USER_ID = 616
FILE_OID = ObjectId("0123456789abcdef0123bd01")
WARNING_MARKER = 'data-testid="bidi-warning"'

RLO, LRO, LRI, PDI = "\u202e", "\u202d", "\u2066", "\u2069"
RLM, LRM, ALM = "\u200f", "\u200e", "\u061c"


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(webapp_app, "get_db", lambda: fake)
    return fake


def _share(db, share_id: str, code: str, file_name: str = "shared.py") -> None:
    db["internal_shares"].insert_one({
        "share_id": share_id,
        "file_name": file_name,
        "language": "python",
        "description": "",
        "snippet_preview": code,
        "mode": "preview",
    })


def test_the_public_share_page_warns_next_to_the_code(db):
    code = (
        "ok = True\n"
        'name = "' + LRI + "x" + PDI + '"\n'
        "x = 1\n"
        "# " + RLO + "comment\n"
    )
    _share(db, "bidishare01", code)

    resp = webapp_app.app.test_client().get("/share/bidishare01")

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert WARNING_MARKER in html
    assert "בשורות 2 ו-4 יש תווים שמשנים את סדר התצוגה" in html


def test_marks_that_hebrew_text_needs_do_not_raise_the_warning(db):
    """LRM, RLM ו-ALM הם סימני כיוון תמימים — לא הם הסכנה, ובלעדיהם אין אזהרה."""
    code = "title = 'גרסה" + RLM + " 2.0'\nlabel = '" + LRM + "LTR" + LRM + "'\narabic = 'عربي" + ALM + "'\n"
    _share(db, "bidishare02", code)

    resp = webapp_app.app.test_client().get("/share/bidishare02")

    assert resp.status_code == 200
    assert WARNING_MARKER not in resp.get_data(as_text=True)


def _displayed_line_of(html: str, char: str) -> int:
    """מספר השורה שהעמוד מציג ליד התו — לפי העוגנים ש-Pygments כותב לכל שורה
    (``lineanchors='line'``), בתוך בלוק הקוד בלבד."""
    start = html.index('<a id="line-1"')
    code_html = html[start:html.index("</pre>", start)]
    parts = re.split(r'<a id="line-(\d+)"', code_html)
    for number, segment in zip(parts[1::2], parts[2::2]):
        if char in segment:
            return int(number)
    raise AssertionError("התו לא נמצא בקוד שהעמוד מציג")


@pytest.mark.parametrize(
    "case, code",
    [
        # ``stripall`` חותך את שתי השורות הריקות: השורה הרביעית בקובץ היא השנייה בעמוד.
        ("leading_blank_lines", "\n\nx = 1\ny = '" + RLO + "'\n"),
        # CR בודד הוא ירידת שורה אצל Pygments, ואינו ירידת שורה ב-split על LF.
        ("lone_cr", "x = 1\ry = '" + RLO + "'\n"),
    ],
)
def test_the_warning_names_the_line_number_the_page_shows(db, case, code):
    """מספר השורה באזהרה הוא המספר שליד השורה בעמוד, ולא המספר בקוד הגולמי."""
    _share(db, "bidishare-" + case, code)

    html = webapp_app.app.test_client().get("/share/bidishare-" + case).get_data(as_text=True)

    shown = _displayed_line_of(html, RLO)
    assert shown == 2  # בקרה: העמוד באמת מציג את התו בשורה 2
    assert f"בשורה {shown} יש תווים שמשנים את סדר התצוגה" in html


def _owner_doc(code: str) -> Dict[str, Any]:
    return {
        "_id": FILE_OID,
        "user_id": USER_ID,
        "file_name": "owned.py",
        "programming_language": "python",
        "code": code,
        "description": "",
        "tags": [],
        "version": 1,
        "is_active": True,
    }


def test_the_owner_view_warns_too(monkeypatch, db):
    """אותה תבנית, ולכן אותה אזהרה — גם לקובץ שנשמר דרך ה-MCP, שלא עבר בבוט."""
    doc = _owner_doc("a = 1\nb = 2\nc = '" + LRO + "abc'\n")
    db["code_snippets"].insert_one(dict(doc))
    monkeypatch.setattr(
        webapp_app,
        "_get_user_any_file_by_id",
        lambda db_ref, user_id, file_id: (dict(doc), "regular"),
    )
    client = webapp_app.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = USER_ID
        sess["user_data"] = {"id": USER_ID, "first_name": "Test", "is_admin": False, "is_premium": False}

    resp = client.get(f"/file/{FILE_OID}")

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert WARNING_MARKER in html
    assert "בשורה 3 יש תווים שמשנים את סדר התצוגה" in html
