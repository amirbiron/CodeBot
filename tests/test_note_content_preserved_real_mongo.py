"""הטקסט שהוקלד בפתק — מול ``mongod`` אמיתי, בוובאפ וב-MCP, כולל מה שהדמויות לא מפרשות.

``tests/test_note_content_preserved_mcp.py`` ו-``tests/test_note_boards_api.py`` רצים על
דמויות, ולכן אינם רואים את BSON, את ``$regex`` של החיפוש, את ``aggregate`` של רשימות
ה-MCP ואת מסלול התזכורות. כאן אותו טקסט עובר דרך מסד אמיתי:

- **וובאפ** (``wired_mongo.app``): יצירה בלוח עם ``content_b64``, כמו ש-``sticky-notes.js``
  שולח; ``PUT``; ``batch``; רשימת הלוח; החיפוש; והתצוגה המקדימה של התזכורות.
- **MCP** (``mcp.call_tool`` מעל אותו מסד): חיפוש תוכן וכלי הרשימה.

עד אוקטובר 2026 כל אחד מהמסלולים האלה פענח ישויות — בכתיבה, בקריאה, או בשתיהן.

**בלי ``NOTE_FONTS_TEST_MONGO_URI`` הקובץ מדולג** (``wired_mongo`` ב-``tests/conftest.py``),
ו-CI מדלג עליו היום (ההערה ליד המשתנה ב-``.github/workflows/ci.yml``). הפלט של ההרצה
המקומית בגוף ה-PR. אין כאן קלט או פלט לדיסק; כל מה שנכתב הולך למסד הזמני של הפיקסצ'ר.

הרצה מקומית, כמו ב-``tests/test_mcp_content_sha256_real_mongo.py``::

    MONGODB_URL='mongodb://127.0.0.1:27017/cktest_import' \\
    NOTE_FONTS_TEST_MONGO_URI='mongodb://127.0.0.1:27017' \\
        pytest tests/test_note_content_preserved_real_mongo.py -v
"""

from __future__ import annotations

import asyncio
import base64
import datetime as dt
import json
from types import SimpleNamespace
from urllib.parse import quote

import pytest

pytest.importorskip("mcp")

USER = 8181

#: מה שמשתמש מקליד בפתק: ישויות בטקסט, בקוד בשורה ובבלוק קוד, ו-URL עם שם legacy.
TYPED = (
    "&amp; &lt;div&gt; &quot;\n"
    "`&amp; &lt;div&gt; &quot;`\n"
    "```\n&amp; &lt;div&gt; &quot;\n```\n"
    "https://x.test/?a=1&copy=2"
)


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


@pytest.fixture
def db(wired_mongo):
    database = wired_mongo.get_db()
    for name in ("sticky_notes", "note_boards", "note_reminders", "sticky_note_versions"):
        database[name].delete_many({})
    return database


@pytest.fixture
def web(wired_mongo, db):
    client = wired_mongo.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = USER
    return client


@pytest.fixture
def board(web):
    res = web.post("/api/note-boards", json={"name": "לוח בדיקה"})
    assert res.status_code == 201, res.get_json()
    return res.get_json()["board"]["id"]


@pytest.fixture
def mcp(monkeypatch, db):
    import mcp.server.auth.middleware.auth_context as auth_context

    import mcp_server.server as srv
    from mcp_server.backend import ProductionBackend

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(srv, "current_user_id", lambda ctx=None: USER)
    monkeypatch.setattr(auth_context, "get_access_token", lambda: SimpleNamespace(scopes=["read", "write"]))
    return srv.build_mcp(ProductionBackend(mongo_db=db))


def _call(mcp, tool: str, **args) -> dict:
    result = asyncio.run(mcp.call_tool(tool, args))
    blocks = result[0] if isinstance(result, tuple) else result
    return json.loads(blocks[0].text)


def _create(web, board_id: str, text: str) -> str:
    res = web.post(f"/api/sticky-notes/board/{board_id}", json={"content_b64": _b64(text)})
    assert res.status_code == 201, res.get_json()
    body = res.get_json()
    return body.get("id") or body["note"]["id"]


def _stored(db, note_id: str) -> str:
    from bson import ObjectId

    return db.sticky_notes.find_one({"_id": ObjectId(note_id)})["content"]


def test_every_web_app_write_stores_the_typed_text_and_the_board_returns_it(web, db, board):
    """יצירה, ``PUT`` ו-``batch`` — שלושת המסלולים שהלוח כותב בהם. עד אוקטובר 2026 כל אחד מהם
    שמר ``& <div> "``, כבר בשמירה הראשונה."""
    note_id = _create(web, board, TYPED)
    assert _stored(db, note_id) == TYPED

    listed = web.get(f"/api/sticky-notes/board/{board}").get_json()["notes"]
    assert [n["content"] for n in listed if n["id"] == note_id] == [TYPED]

    edited = TYPED + "\n&lt;edit&gt;"
    assert web.put(f"/api/sticky-notes/note/{note_id}", json={"content_b64": _b64(edited)}).status_code == 200
    assert _stored(db, note_id) == edited

    res = web.post("/api/sticky-notes/batch", json={"updates": [{"id": note_id, "content_b64": _b64(TYPED)}]})
    assert res.get_json()["results"][0]["ok"] is True, res.get_json()
    assert _stored(db, note_id) == TYPED


def test_the_search_matches_and_previews_the_text_as_typed(web, db, board):
    """המחט והגוף כמו שהוקלדו: ``&amp;lt;`` מוצא, והצורה המפוענחת אינה מוצאת דבר."""
    note_id = _create(web, board, TYPED)

    hits = web.get("/api/sticky-notes/search?q=" + quote("&lt;div&gt;")).get_json()
    assert [h["id"] for h in hits["results"]] == [note_id], hits
    assert "&amp; &lt;div&gt; &quot;" in hits["results"][0]["preview"]

    decoded = web.get("/api/sticky-notes/search?q=" + quote("& <div>")).get_json()
    assert decoded["results"] == [], decoded


def test_a_needle_with_a_nul_or_over_the_ceiling_is_refused_not_cut(web, db, board):
    """NUL: מונגו דוחה ``$regex`` כזה בחריגה — כאן ``invalid_query``. ארוכה מהתקרה:
    ``query_too_long``, ולא חיפוש של הקידומת שלה."""
    from webapp.sticky_notes_api import NOTE_SEARCH_MAX_NEEDLE

    _create(web, board, TYPED)

    nul = web.get("/api/sticky-notes/search?q=" + quote("a\x00b"))
    assert (nul.status_code, nul.get_json()) == (400, {"ok": False, "error": "invalid_query"})

    long = web.get("/api/sticky-notes/search?q=" + "x" * (NOTE_SEARCH_MAX_NEEDLE + 1))
    assert long.status_code == 400
    assert long.get_json() == {"ok": False, "error": "query_too_long", "max": NOTE_SEARCH_MAX_NEEDLE}


def test_the_reminder_preview_is_the_text_as_stored(web, db, board):
    """התצוגה המקדימה בחלונית התזכורות — שש המילים הראשונות, בלי פענוח. עד אוקטובר 2026
    היא פענחה פעמיים (``_coerce_content_from_doc`` ואז ``_first_n_words``)."""
    from note_reminder_state import armed_fields

    note_id = _create(web, board, TYPED)
    now = dt.datetime.now(dt.timezone.utc)
    db.note_reminders.insert_one({
        "user_id": USER, "note_id": note_id, "file_id": "", "board_id": board,
        "created_at": now, **armed_fields(now - dt.timedelta(minutes=5), now),
    })

    items = web.get("/api/sticky-notes/reminders/list").get_json()["items"]

    words = TYPED.split()
    assert [i["preview"] for i in items] == [" ".join(words[:6]) + "…"]


def test_the_mcp_lists_and_content_search_return_the_text_as_typed(web, db, board, mcp):
    """הצד של הסוכן על אותו פתק: ``list_board_notes`` (``aggregate`` וכתיבה רזה), ``get_note``
    ו-``search_notes`` עם ``search_content``."""
    note_id = _create(web, board, TYPED)

    listed = _call(mcp, "codekeeper_list_board_notes", board_id=board)
    assert [n["content"] for n in listed["notes"] if n["id"] == note_id] == [TYPED], listed

    assert _call(mcp, "codekeeper_get_note", note_id=note_id)["note"]["content"] == TYPED

    found = _call(mcp, "codekeeper_search_notes", query="&lt;div&gt;", search_content=True)
    assert found["ok"] is True, found
    hits = found.get("notes", found.get("results", []))
    assert [h["id"] for h in hits] == [note_id], found
