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


def _note_doc(store, note_id: str) -> dict:
    from bson import ObjectId

    return store.raw["sticky_notes"].find_one({"_id": ObjectId(note_id)})


def _stored(store, note_id: str) -> str:
    return _note_doc(store, note_id)["content"]


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


#: כלי כתיבה שיש בשמם ``note`` ואינם כותבים **גוף של פתק** — שם ← הנימוק. מי שמוסיף כאן
#: שם כותב לידו למה, ומצביע על הטסט שמכסה את הכלל שלו במקום הטסט הזה.
_NOT_A_NOTE_BODY = {
    "codekeeper_comment_note": (
        "כותב תגובה לאוסף note_threads ואינו נוגע בגוף הפתק. לגוף התגובה כלל משלו, באותה "
        "צורה (בלי ניקוי, ריקנות על עותק בלי רווחים, סירוב ולא חיתוך) ובתקרה אחרת — "
        "note_threads.comment_body_error; ראו test_the_comment_tool_checks_its_body_in_comment_body_error"
    ),
}


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
        # השמירה מהתצוגה בתוך Claude — ה-hash של הגוף שבמסד, כדי שהסירוב יגיע מהבדיקה ולא מ-``conflict``.
        "codekeeper_note_view_save": {"note_id": note_id, "content": "body", "expected_content_sha256": _sha("MARK")},
    }
    assert set(sent) == _note_write_tools(admin_mcp) - set(_NOT_A_NOTE_BODY)

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


def test_the_comment_tool_checks_its_body_in_comment_body_error(monkeypatch, admin_mcp, store):
    """המקביל של הטסט שמעל, לגוף **תגובה**: כל מסלול של ``codekeeper_comment_note`` שכותב גוף
    — שרשור חדש, תשובה, וסגירה עם סיכום — עובר בבדיקה המשותפת ``comment_body_error``,
    והסירוב שלה חוזר לפני שנכתב דבר (לפני השער של הפתק ולפני המסד).

    התוכן עצמו — שגוף נשמר בדיוק כפי שנשלח — נבדק מול מונגו אמיתי ב-
    ``tests/test_note_threads_mcp.py``: הדמה המשותפת אינה מפרשת ``find_one_and_update``
    עם ``$push`` ו-``$slice``.
    """
    from mcp_server import handlers

    board = _board(admin_mcp)
    note_id = _call(admin_mcp, "codekeeper_create_board_note", board_id=board, content="MARK")["note"]["id"]
    checked = []

    def refuse(body):
        checked.append(body)
        return {"ok": False, "error": "refused_by_the_shared_check"}

    monkeypatch.setattr(handlers, "comment_body_error", refuse)
    paths = (
        {"body": "body"},
        {"body": "body", "thread_id": "a" * 24},
        {"body": "body", "thread_id": "a" * 24, "resolve": True},
    )
    for args in paths:
        res = _call(admin_mcp, "codekeeper_comment_note", note_id=note_id, working_on="task", **args)
        assert res == {"ok": False, "error": "refused_by_the_shared_check"}, args
    assert checked == ["body"] * len(paths)
    assert store.raw["note_threads"].count_documents({}) == 0
    assert _stored(store, note_id) == "MARK"


# ---------------------------------------------------------------------------
# השער של escape של יוניקוד בכלי הפתקים — ``expected_unicode_escapes`` (#3692)
#
# לכלי הפתקים אין מסלול קובץ, ולכן השער הוא ההגנה היחידה שלהם — והמקרה שפתח את כל הנושא
# היה פתק: ``codekeeper_note_str_replace`` שמר תו בלתי-נראה עם ``content_changed: false``.
# כאן: מה שנשמר, דרך ``call_tool`` מעל ``ProductionBackend`` והדמה. מה שמשותף לשמונת כלי
# הכתיבה (התיאור, סירוב שאינו נוגע ב-backend, ערך פגום) — ב-``tests/test_mcp_multi_edit.py``.
# ---------------------------------------------------------------------------

#: לוכסן אחד, נבנה ב-``chr``: escape שנכתב בקובץ כ-escape עלול להישמר כתו (ההערה מעל ``_BS``
#: ב-``tests/test_mcp_multi_edit.py``). ``AS_TEXT`` הוא escape של יוניקוד כששה תווים, ו-``RLM``
#: (למעלה) הוא התו שהוא נהיה כשלקוח ממיר אותו.
_BS = chr(92)
AS_TEXT = _BS + "u200F"


class _RepoListing(_ObjectIdCollection):
    """``distinct`` — מה ש-``mirrored_repo_names`` קורא, ושהדמה המשותפת אינה מממשת."""

    def distinct(self, key):
        return sorted({d.get(key) for d in self.docs if d.get(key)})


def _note_writers(server, store) -> dict:
    """לכל כלי פתק שכותב גוף ונושא את השער: ``(ארגומנטים לפי הטקסט, איפה הגוף נשמר)``.

    "איפה" הוא פונקציה מתשובת ההצלחה למזהה הפתק: ביצירה — הפתק החדש; בעדכון — הפתק שנפתח
    ב-``MARK``. ``codekeeper_note_str_replace`` מחליף את ``MARK`` כולו, ולכן בכל הכלים מה שנשמר
    הוא הטקסט עצמו.
    """
    board = _board(server)
    assert _call(server, "codekeeper_save_file", file_name="a.md", code="x").get("ok") is True
    store.raw.c["repo_metadata"] = _RepoListing()
    store.raw["repo_metadata"].insert_one({"repo_name": "repo"})
    store.raw["repo_files"].insert_one({"repo_name": "repo", "path": "a.py"})
    note_id = _call(server, "codekeeper_create_board_note", board_id=board, content="MARK")["note"]["id"]

    def created(res):
        return res["note"]["id"]

    def the_note(_res):
        return note_id

    return {
        "codekeeper_create_note": (lambda text: {"file_name": "a.md", "content": text}, created),
        "codekeeper_create_board_note": (lambda text: {"board_id": board, "content": text}, created),
        "codekeeper_create_repo_note": (
            lambda text: {"repo_name": "repo", "repo_path": "a.py", "content": text}, created),
        "codekeeper_update_note": (lambda text: {"note_id": note_id, "content": text}, the_note),
        "codekeeper_note_str_replace": (
            lambda text: {"note_id": note_id, "old_string": "MARK", "new_string": text}, the_note),
    }


#: הכלים שכותבים גוף של פתק ונושאים את השער — המפתחות של :func:`_note_writers`.
_NOTE_WRITERS = ("codekeeper_create_note", "codekeeper_create_board_note", "codekeeper_create_repo_note",
                 "codekeeper_update_note", "codekeeper_note_str_replace")


def _notes_state(store) -> tuple:
    """מה שחייב להישאר זהה כש"שום דבר לא נכתב": כל הגופים, כמה פתקים, וכמה גרסאות בהיסטוריה."""
    notes = store.raw["sticky_notes"].docs
    return (sorted((str(d["_id"]), d.get("content")) for d in notes), len(notes),
            len(store.raw["sticky_note_versions"].docs))


@pytest.mark.parametrize("tool", _NOTE_WRITERS)
def test_a_note_write_whose_escape_arrived_as_its_character_is_refused_and_writes_nothing(admin_mcp, store, tool):
    """escape אחד הוצהר, והכלי קיבל את התו: ``unicode_escapes_mismatch``, ושום דבר לא נכתב.

    ביצירה — לא נוצר פתק; בעדכון — הגוף לא השתנה, ואין גרסה בהיסטוריה. בלי השער אותה קריאה
    נשמרת עם ``content_changed: false`` — הכלי שמר בדיוק מה שהגיע (המקרה שפתח את הנושא).

    **המוטציות שחייבות להפיל אותו — ביטול הספירה בכלי אחד, והבדיקה אחרי הכתיבה:** בשתיהן
    הפתק נכתב.
    """
    arguments, _ = _note_writers(admin_mcp, store)[tool]
    before = _notes_state(store)

    res = _call(admin_mcp, tool, **arguments("x " + RLM), expected_unicode_escapes=1)

    assert (res["ok"], res["error"], res["expected"], res["received"]) == (
        False, "unicode_escapes_mismatch", 1, 0), res
    assert _notes_state(store) == before


@pytest.mark.parametrize("tool", _NOTE_WRITERS)
def test_a_note_write_whose_escapes_arrived_as_text_passes_and_saves_the_text(admin_mcp, store, tool):
    """שני escapes הוצהרו, ושניהם הגיעו כששה תווים: הכתיבה עוברת, והטקסט הוא שנשמר."""
    arguments, stored_in = _note_writers(admin_mcp, store)[tool]
    text = f"x {AS_TEXT} y {AS_TEXT}"

    res = _call(admin_mcp, tool, **arguments(text), expected_unicode_escapes=2)

    assert res.get("ok") is True and res["content_changed"] is False, res
    assert _stored(store, stored_in(res)) == text
    assert res["note"]["content_sha256"] == _sha(text)


@pytest.mark.parametrize("sent", [AS_TEXT, RLM], ids=["as_text", "as_character"])
@pytest.mark.parametrize("tool", _NOTE_WRITERS)
def test_without_the_declaration_a_note_write_is_what_it_was(admin_mcp, store, tool, sent):
    """בלי הפרמטר — אפס דיף: אין בדיקה, והגוף נשמר כמו שהגיע, בשתי הצורות."""
    arguments, stored_in = _note_writers(admin_mcp, store)[tool]

    res = _call(admin_mcp, tool, **arguments("x " + sent))

    assert res.get("ok") is True, res
    assert _stored(store, stored_in(res)) == "x " + sent


def test_a_note_replace_counts_old_string_too_and_says_which_string_changed(admin_mcp, store):
    """``codekeeper_note_str_replace`` סופר את ``old_string`` ואת ``new_string`` יחד, כמו ``codekeeper_edit_file``.

    הפתק מחזיק את ה-escape כטקסט, וגם את התו עצמו במקום אחר. ``old_string`` שה-escape שלו
    הומר מחפש את התו — וכשהוא קיים, ההחלפה נעשית במקום הלא נכון, ומצליחה. עם ההצהרה: סירוב,
    ``received_in_old_string: 0``, והגוף לא השתנה. ו-``old_string`` שהגיע כטקסט עובר, ומחליף
    את הטקסט ולא את התו.

    **המוטציה שחייבת להפיל אותו — ספירה של ``new_string`` בלבד:** אז הקריאה השנייה נענית
    בסירוב, כי ב-``new_string`` אין escape וההצהרה היא 1.
    """
    body = f"the char {RLM} and the text {AS_TEXT}"
    note_id = _call(admin_mcp, "codekeeper_create_board_note", board_id=_board(admin_mcp), content=body)["note"]["id"]
    versions = len(store.raw["sticky_note_versions"].docs)

    refused = _call(admin_mcp, "codekeeper_note_str_replace", note_id=note_id, old_string=RLM,
                    new_string="X", expected_unicode_escapes=1)

    assert (refused["ok"], refused["error"]) == (False, "unicode_escapes_mismatch"), refused
    assert (refused["expected"], refused["received"]) == (1, 0)
    assert (refused["received_in_old_string"], refused["received_in_new_string"]) == (0, 0)
    assert _stored(store, note_id) == body
    assert len(store.raw["sticky_note_versions"].docs) == versions

    passed = _call(admin_mcp, "codekeeper_note_str_replace", note_id=note_id, old_string=AS_TEXT,
                   new_string="X", expected_unicode_escapes=1)

    assert passed.get("ok") is True, passed
    assert _stored(store, note_id) == f"the char {RLM} and the text X"


def test_a_declaration_without_content_in_update_note_is_its_own_refusal(admin_mcp, store):
    """``codekeeper_update_note`` עם ``expected_unicode_escapes`` ובלי ``content``: קוד משלו, ושום שדה לא נכתב.

    לא ``unicode_escapes_mismatch``: ה-``hint`` שלו אומר לשלוח שוב, וכאן אין מה לשלוח. והצבע
    שנשלח באותה קריאה אינו מוחל — הסוכן התכוון לגוף, והקריאה אינה מה שהתכוון אליו.
    """
    note_id = _call(admin_mcp, "codekeeper_create_board_note", board_id=_board(admin_mcp), content="MARK")["note"]["id"]
    before = _note_doc(store, note_id)["color"]

    res = _call(admin_mcp, "codekeeper_update_note", note_id=note_id, color="green", expected_unicode_escapes=0)

    assert (res["ok"], res["error"]) == (False, "expected_unicode_escapes_without_content"), res
    assert "Nothing was written" in res["hint"] and "without expected_unicode_escapes" in res["hint"]
    after = _note_doc(store, note_id)
    assert after["color"] == before and after["content"] == "MARK"


def test_a_comment_whose_escape_arrived_as_its_character_is_refused_and_writes_nothing(admin_mcp, store):
    """``codekeeper_comment_note``: escape הוצהר, והתו הגיע — סירוב, ואין שרשור באוסף.

    התגובה שעוברת את השער ונשמרת נבדקת מול מונגו אמיתי ב-``tests/test_note_threads_mcp.py``:
    הדמה אינה מפרשת ``find_one_and_update`` עם ``$push``.
    """
    note_id = _call(admin_mcp, "codekeeper_create_board_note", board_id=_board(admin_mcp), content="MARK")["note"]["id"]

    res = _call(admin_mcp, "codekeeper_comment_note", note_id=note_id, working_on="task",
                body="x " + RLM, expected_unicode_escapes=1)

    assert (res["ok"], res["error"], res["expected"], res["received"]) == (
        False, "unicode_escapes_mismatch", 1, 0), res
    assert store.raw["note_threads"].count_documents({}) == 0


def test_a_declaration_on_a_close_without_body_is_its_own_refusal(admin_mcp, store):
    """סגירת שרשור בלי ``body``, עם ``expected_unicode_escapes``: ``expected_unicode_escapes_without_body``.

    לפני השער של הפתק ולפני המסד — ``thread_id`` כאן אינו קיים, והסירוב הוא של ההצהרה ולא
    ``thread_not_found``.
    """
    note_id = _call(admin_mcp, "codekeeper_create_board_note", board_id=_board(admin_mcp), content="MARK")["note"]["id"]

    res = _call(admin_mcp, "codekeeper_comment_note", note_id=note_id, working_on="task", thread_id="a" * 24,
                resolve=True, expected_unicode_escapes=0)

    assert (res["ok"], res["error"]) == (False, "expected_unicode_escapes_without_body"), res
    assert store.raw["note_threads"].count_documents({}) == 0
