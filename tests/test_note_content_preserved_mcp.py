"""כלי הפתקים של ה-MCP שומרים בדיוק את מה שנשלח — אותו כלל של קבצים.

**דרך הממשק שהסוכן מפעיל:** ``mcp.call_tool`` על שרת MCP אמיתי (``build_mcp``), מעל
``ProductionBackend`` אמיתי. רק האוספים הם הדמה המשותפת (``tests/_fake_mongo.py``),
ומה שנשמר נקרא ישירות מהאוסף ולא מתשובת הכלי. אותה תבנית של
``tests/test_save_preserves_content_mcp.py``, ומאותה סיבה: בדיקה של ה-handler לבדו
הייתה עוברת גם אם שכבה אחרת בדרך הייתה משנה את הגוף.

עד אוקטובר 2026 כל גוף עבר ``html.unescape``, קיפול CRLF, מחיקת תווי בקרה ו-
``.strip()``: ``&amp;`` נשמר כ-``&``, ``&copy=`` בתוך כתובת הפך ל-``©=``, ו-
``note_str_replace`` כתב בחזרה את כל הפתק מפוענח. ``docs/quality/code-normalization.md``.

החיפוש והרשימות אינם כאן: הם עוברים ב-``$regex``, ``$or`` ו-``aggregate``, שהדמה אינה
מפרשת. הם נבדקים מול ``mongod`` אמיתי ב-``tests/test_note_content_preserved_real_mongo.py``.

תווי כיווניות כתובים רק כ-escapes (H1: תו כזה בקובץ מקור מפיל את bandit ב-B613).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _fake_mongo import FakeCollection
from _save_layer_harness import clear_local_cache, install_fake_collections, load_production_config

pytest.importorskip("mcp")

USER = 6161
RLM = "\u200f"

#: כל אחד מהם השתנה בשמירה עד אוקטובר 2026.
CASES = {
    "entities_in_text": "&amp; &lt;div&gt; &quot;",
    "entities_in_inline_code": "`&amp; &lt;div&gt; &quot;`",
    "entities_in_code_block": "```\n&amp; &lt;div&gt; &quot;\n```",
    "legacy_name_in_url": "https://x.test/?a=1&copy=2&params=3&notify=4",
    "numeric_reference": "&#39;quoted&#39; &#x27;hex&#x27;",
    "crlf": "line one\r\nline two\r\n",
    "control_character": "bell\x07 between words",
    "edge_whitespace": "  padded  \n\n",
    "rlm": "גרסה" + RLM + " 2.0",
}


class _ObjectIdCollection(FakeCollection):
    """``insert_one`` שנותן ``ObjectId``, כמו מונגו, ואינדקסים שאפשר לקרוא חזרה.

    הדמה המשותפת נותנת מספרים רצים, וכלי הפתקים דוחים מזהה פתק או לוח שאינו 24
    ספרות הקס (``invalid_note_id``, ``invalid_board_id``) — כלומר בלי זה הטסט היה
    נעצר בוולידציה ולא מגיע לשמירה. ה-``_id`` נוסף למסמך של הקורא, כמו ב-pymongo
    (4.15.3, ``synchronous/collection.py``, ``insert_one``).
    """

    def __init__(self):
        super().__init__()
        self.indexes = {}

    def insert_one(self, d):
        from bson import ObjectId

        d.setdefault("_id", ObjectId())
        return super().insert_one(d)

    def create_index(self, keys, name=None, unique=False, **kw):
        """נרשם, ו-``index_information`` מחזיר אותו — בלי לאכוף אותו.

        שער האינדקסים של ה-backend (``_ensure_enforced_index``) מאמת אינדקס ייחודי
        ב-``index_information``, וכשאין אימות הצילום של ``update_note`` מסרב
        (``snapshot_failed``). האכיפה עצמה נבדקת מול מונגו אמיתי ב-
        ``tests/test_note_boards_mongo.py``; כאן אין שתי כתיבות מקבילות שהיא הייתה עוצרת.
        """
        self.indexes[name] = {"key": list(keys), "unique": bool(unique)}
        return name

    def index_information(self):
        return dict(self.indexes)


@pytest.fixture
def store(monkeypatch):
    load_production_config(monkeypatch)
    installed = install_fake_collections(monkeypatch)
    for name in ("sticky_notes", "note_boards", "sticky_note_versions"):
        installed.raw.c[name] = _ObjectIdCollection()
    yield installed
    clear_local_cache()


@pytest.fixture
def mcp(monkeypatch, store):
    import mcp.server.auth.middleware.auth_context as auth_context

    import mcp_server.server as srv
    from mcp_server.backend import ProductionBackend

    # כמו ב-``tests/test_save_preserves_content_mcp.py``: ``build_mcp`` דורש ייצור או PostHog.
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(srv, "current_user_id", lambda ctx=None: USER)
    monkeypatch.setattr(auth_context, "get_access_token", lambda: SimpleNamespace(scopes=["read", "write"]))
    return srv.build_mcp(ProductionBackend(db_manager=store.dbm, mongo_db=store.raw))


def _call(mcp, tool: str, **args) -> dict:
    """``FastMCP.call_tool(name, arguments)`` — mcp 1.28.1; ראו ``tests/test_save_preserves_content_mcp.py``."""
    result = asyncio.run(mcp.call_tool(tool, args))
    blocks = result[0] if isinstance(result, tuple) else result
    return json.loads(blocks[0].text)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _board(mcp) -> str:
    boards = _call(mcp, "codekeeper_list_boards")
    assert boards.get("ok") is True, boards
    return boards["boards"][0]["id"]


def _stored(store, note_id: str) -> str:
    from bson import ObjectId

    return store.raw["sticky_notes"].find_one({"_id": ObjectId(note_id)})["content"]


@pytest.mark.parametrize("case", sorted(CASES))
def test_create_board_note_stores_exactly_what_was_sent(mcp, store, case):
    sent = CASES[case]
    res = _call(mcp, "codekeeper_create_board_note", board_id=_board(mcp), content=sent)

    assert res.get("ok") is True and res["content_changed"] is False, res
    assert _stored(store, res["note"]["id"]) == sent
    assert res["note"]["content"] == sent
    assert res["note"]["content_sha256"] == _sha(sent)


@pytest.mark.parametrize("case", sorted(CASES))
def test_update_note_stores_exactly_what_was_sent_and_get_note_returns_it(mcp, store, case):
    sent = CASES[case]
    created = _call(mcp, "codekeeper_create_board_note", board_id=_board(mcp), content="before")
    note_id = created["note"]["id"]

    res = _call(mcp, "codekeeper_update_note", note_id=note_id, content=sent)

    assert res.get("ok") is True and res["content_changed"] is False, res
    assert _stored(store, note_id) == sent
    read = _call(mcp, "codekeeper_get_note", note_id=note_id)
    assert read["note"]["content"] == sent
    assert read["note"]["content_sha256"] == _sha(sent)
    assert "stored_content" not in read


@pytest.mark.parametrize("case", sorted(CASES))
def test_note_str_replace_writes_new_string_as_sent_and_leaves_the_rest(mcp, store, case):
    """``new_string`` נכתב כמו שנשלח, וחלק שאיש לא נגע בו — עם ישויות — נשאר כמו שהיה."""
    sent = CASES[case]
    untouched = "keep: a &lt; b &amp;&amp; c"
    created = _call(mcp, "codekeeper_create_board_note", board_id=_board(mcp), content=untouched + "\nMARK")
    note_id = created["note"]["id"]

    res = _call(mcp, "codekeeper_note_str_replace", note_id=note_id, old_string="MARK", new_string=sent)

    assert res.get("ok") is True and res["content_changed"] is False, res
    assert _stored(store, note_id) == untouched + "\n" + sent
    assert res["note"]["content_sha256"] == _sha(untouched + "\n" + sent)


@pytest.mark.parametrize("case", ["entities_in_text", "crlf", "control_character", "rlm"])
def test_an_old_string_copied_from_the_body_finds_it(mcp, store, case):
    """עד אוקטובר 2026 ``old_string`` פוענח, ולכן ``&amp;`` שהועתק מהגוף לא תמיד תפס אותו."""
    sent = CASES[case]
    created = _call(mcp, "codekeeper_create_board_note", board_id=_board(mcp), content="<" + sent + ">")
    note_id = created["note"]["id"]
    body = _call(mcp, "codekeeper_get_note", note_id=note_id)["note"]["content"]

    res = _call(mcp, "codekeeper_note_str_replace", note_id=note_id, old_string=body[1:-1], new_string="done")

    assert res.get("ok") is True, res
    assert _stored(store, note_id) == "<done>"


def test_a_body_of_whitespace_only_is_refused_and_nothing_is_written(mcp, store):
    """הסייג: ריקנות נבדקת על עותק אחרי ``strip``, והמקור הוא מה שנשמר."""
    board = _board(mcp)
    created = _call(mcp, "codekeeper_create_board_note", board_id=board, content="real")
    note_id = created["note"]["id"]
    notes_before = store.raw["sticky_notes"].count_documents({})

    assert _call(mcp, "codekeeper_create_board_note", board_id=board, content=" \n\t ") == {
        "ok": False, "error": "empty_content",
    }
    assert _call(mcp, "codekeeper_update_note", note_id=note_id, content="\r\n  ") == {
        "ok": False, "error": "empty_content",
    }
    assert store.raw["sticky_notes"].count_documents({}) == notes_before
    assert _stored(store, note_id) == "real"


@pytest.fixture
def admin_mcp(monkeypatch, store):
    """כמו ``mcp``, עם כלי הריפו: ``repo_backend`` רשום, והקורא אדמין.

    ``codekeeper_create_repo_note`` נרשם רק כשיש ``repo_backend`` (``_REPO_BROWSER_TOOLS``
    ב-``mcp_server/server.py``), ונקרא רק לאדמין (``require_admin``). ``object()`` מספיק:
    ההרשמה בונה סגורים בלבד, והכלי כותב דרך ה-backend של הפתקים ולא דרך ``repo_backend``.
    """
    import mcp.server.auth.middleware.auth_context as auth_context

    import mcp_server.server as srv
    from mcp_server.backend import ProductionBackend

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(srv, "current_user_id", lambda ctx=None: USER)
    monkeypatch.setattr(srv, "require_admin", lambda ctx=None: USER)
    monkeypatch.setattr(auth_context, "get_access_token", lambda: SimpleNamespace(scopes=["read", "write"]))
    server = srv.build_mcp(ProductionBackend(db_manager=store.dbm, mongo_db=store.raw), repo_backend=object())
    server._request_is_admin = lambda: True
    return server


def _note_write_tools(server) -> set:
    """כל כלי פתק שאינו ``readOnlyHint`` — נגזר מהשרת, כדי שכלי כתיבה חדש לא יחמוק מהטסט."""
    names = set()
    for tool in asyncio.run(server.list_tools()):
        hints = tool.annotations
        read_only = hints.get("readOnlyHint") if isinstance(hints, dict) else getattr(hints, "readOnlyHint", None)
        if "note" in tool.name and read_only is False:
            names.add(tool.name)
    return names


def test_every_note_write_tool_checks_the_body_in_note_content_error(monkeypatch, admin_mcp, store):
    """כל כלי שכותב גוף של פתק עובר ב-``_note_content_error`` — גם ``note_str_replace``, על הגוף שבנה.

    ``docs/quality/code-normalization.md`` מבטיח את זה על כל כותבי הפתקים ב-MCP, ולכן
    הרשימה נגזרת מהשרת: כלי כתיבה חדש שלא נוסף ל-``sent`` מפיל את הטסט. הבדיקה עצמה
    מוחלפת בדמה שמסרבת, וכל כלי צריך להחזיר את הסירוב שלה בלי לכתוב דבר. עד שהממצא
    הזה תוקן, ``note_str_replace`` החזיק עותק משלו של בדיקת הריקנות ושל בדיקת האורך.
    """
    from mcp_server import handlers

    board = _board(admin_mcp)
    note_id = _call(admin_mcp, "codekeeper_create_board_note", board_id=board, content="MARK")["note"]["id"]
    assert _call(admin_mcp, "codekeeper_save_file", file_name="a.md", code="x").get("ok") is True
    sent = {
        "codekeeper_create_note": {"file_name": "a.md", "content": "body"},
        "codekeeper_create_board_note": {"board_id": board, "content": "body"},
        "codekeeper_create_repo_note": {"repo_name": "repo", "repo_path": "a.py", "content": "body"},
        "codekeeper_update_note": {"note_id": note_id, "content": "body"},
        "codekeeper_note_str_replace": {"note_id": note_id, "old_string": "MARK", "new_string": "body"},
    }
    assert set(sent) == _note_write_tools(admin_mcp)

    checked = []

    def refuse(content):
        checked.append(content)
        return {"ok": False, "error": "refused_by_the_shared_check"}

    monkeypatch.setattr(handlers, "_note_content_error", refuse)
    notes_before = store.raw["sticky_notes"].count_documents({})

    for tool, args in sent.items():
        assert _call(admin_mcp, tool, **args) == {"ok": False, "error": "refused_by_the_shared_check"}, tool
    assert checked == ["body"] * len(sent)
    assert store.raw["sticky_notes"].count_documents({}) == notes_before
    assert _stored(store, note_id) == "MARK"
