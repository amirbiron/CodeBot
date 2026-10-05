"""תקרת התיאור של קובץ (#3489, חלק א) — נאכפת בכל כלי MCP שמקבל תיאור מבחוץ, ונכתבת
בתיאורי הכלים מאותו קבוע.

**מה נבדק, ומאיזה ממשק.** הכלים נקראים דרך ``mcp.call_tool`` על שרת MCP אמיתי
(``build_mcp``), מעל ``ProductionBackend`` ו-``Repository`` אמיתיים — המסלול שסוכן מפעיל
(כלל 1 ב-``claude-md-snippets/testing.md``). שלוש קבוצות של מסד:

1. **הדמה המשותפת** (``tests/_fake_mongo.py``, דרך ``tests/_save_layer_harness.py``) —
   ``codekeeper_save_file`` ושלושת כלי העריכה, שכולם עוברים ב-``insert_one``. רצים ב-CI.
2. **אוסף מקליט** — מה ש-``update_file_metadata_in`` שולח למונגו כשהתיאור ארוך מהתקרה,
   ואיך התשובה נגזרת מהמסמך שהכתיבה ראתה. רץ ב-CI. הדמה המשותפת אינה יודעת pipeline,
   ולכן אינה יכולה לשמש כאן.
3. **``mongod`` אמיתי** (``wired_mongo``) — מה ש-``$cond`` באמת עושה במסד: שכשהתיאור
   השמור אחר שום שדה אינו זז ושום שדה אינו נוסף, ושההשוואה היא מול הגרסה האחרונה ולא
   מול כל גרסה שנושאת את הטקסט. **בלי ``NOTE_FONTS_TEST_MONGO_URI`` הם מדולגים, וב-CI הם
   מדולגים** (ראו ``docs/testing.rst``); הפלט של ההרצה המקומית בגוף ה-PR.

**התיאורים נבנים מהקבוע**, וזה נבדק בשתי דרכים: התחלת תיאור הפרמטר בשני הכלים, ושינוי
של הקבוע בזמן ריצה שמזיז גם את התיאור וגם את האכיפה באותו מספר.

אין כאן קלט או פלט לדיסק.

הרצה מקומית של כל הקבוצות — ``MONGODB_URL`` לאותו שרת, מאותה סיבה שכתובה ב-
``tests/test_mcp_content_sha256_real_mongo.py``::

    MONGODB_URL='mongodb://127.0.0.1:27017/cktest_import' \\
    NOTE_FONTS_TEST_MONGO_URI='mongodb://127.0.0.1:27017' \\
        pytest tests/test_mcp_description_ceiling.py -v
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

# ‏``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _save_layer_harness import clear_local_cache, install_fake_collections, latest, load_production_config

pytest.importorskip("mcp")

from file_description import (  # noqa: E402
    DESCRIPTION_SET_AT_VERSION_FIELD,
    FILE_DESCRIPTION_MAX_CHARS,
)

USER = 3489
NAME = "description-ceiling.md"
ROOT = Path(__file__).resolve().parents[1]

def _agent_report_text() -> str:
    """הטקסט מהדיווח של הסוכן: 413 תווים ו-625 בתים.

    עברית היא שני בתים לאות ורווחים וסימנים בית אחד, ולכן 212 אותיות ו-201 תווי ASCII
    נותנים בדיוק את שני המספרים — שנבדקים בטסט הראשון, כדי שהנחה שגויה כאן תיפול בשמה.
    """
    hebrew = "אבגדהוזחטיכלמנסעפצקרשת" * 10  # 220 אותיות
    ascii_part = "v2 fix: " * 26  # 208 תווים
    return hebrew[:212] + ascii_part[:201]


AGENT_REPORT_TEXT = _agent_report_text()
LONG = "ת" * 800  # תיאור שנשמר לפני שהתקרה נאכפה — ארוך ממנה
OTHER_LONG = "ש" * 600
STAMP_TIME = datetime(2019, 3, 7, 9, 15, tzinfo=timezone.utc)


def test_the_agent_report_text_is_what_the_report_described():
    """הנחת הטסטים: 413 תווים, 625 בתים — בעברית, יותר בתים מתווים."""
    assert len(AGENT_REPORT_TEXT) == 413
    assert len(AGENT_REPORT_TEXT.encode("utf-8")) == 625


# ---------------------------------------------------------------------------
# 1. הפונקציה הטהורה — הכלל עצמו
# ---------------------------------------------------------------------------


def test_the_ceiling_counts_characters_not_bytes():
    """413 תווים שהם 625 בתים — בתקרה. בתקרה בדיוק — מותר; תו אחד מעל — לא.

    הייבוא בתוך הטסט ולא בראש הקובץ: כך שאר הקובץ נאסף ורץ גם על הקוד שלפני
    השינוי, ונופל שם על ההתנהגות ולא על ייבוא.
    """
    from file_description import description_length_error

    assert description_length_error(AGENT_REPORT_TEXT) is None
    assert description_length_error("א" * FILE_DESCRIPTION_MAX_CHARS) is None
    assert description_length_error("א" * (FILE_DESCRIPTION_MAX_CHARS + 1)) == {
        "max_chars": FILE_DESCRIPTION_MAX_CHARS,
        "actual_chars": FILE_DESCRIPTION_MAX_CHARS + 1,
    }
    assert description_length_error("") is None


def test_text_identical_to_the_previous_description_passes_at_any_length():
    """העתקה אינה תיאור חדש: זהה לקודם — מותר בכל אורך. כל השאר נמדד."""
    from file_description import description_length_error

    assert description_length_error(LONG, LONG) is None
    refusal = {"max_chars": FILE_DESCRIPTION_MAX_CHARS, "actual_chars": len(LONG)}
    assert description_length_error(LONG, OTHER_LONG) == refusal
    assert description_length_error(LONG, None) == refusal
    assert description_length_error(LONG, 42) == refusal, "תיאור קודם פגום אינו 'זהה'"


@pytest.mark.parametrize("value", [["x" * 900], 42, None])
def test_a_description_that_is_not_text_is_a_bug_in_the_caller(value):
    """``TypeError`` ולא "מותר": רשימה של מחרוזת אחת ארוכה הייתה עוברת את ``len`` כ"קצרה"."""
    from file_description import description_length_error

    with pytest.raises(TypeError):
        description_length_error(value)


# ---------------------------------------------------------------------------
# 2. ``codekeeper_save_file`` — הקובץ נשמר, התיאור שמעל התקרה לא
# ---------------------------------------------------------------------------


@pytest.fixture
def store(monkeypatch):
    load_production_config(monkeypatch)
    yield install_fake_collections(monkeypatch)
    clear_local_cache()


def _authenticated(monkeypatch, srv):
    """הזהות והרשאת הכתיבה, כפי שהכלי קורא אותן — כמו ב-``tests/test_mcp_content_sha256.py``."""
    import mcp.server.auth.middleware.auth_context as auth_context

    # ``build_mcp`` קורא ל-``instrument_mcp_server``, שזורק מחוץ לפרודקשן בלי PostHog.
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(srv, "current_user_id", lambda ctx=None: USER)
    monkeypatch.setattr(auth_context, "get_access_token", lambda: SimpleNamespace(scopes=["read", "write"]))


@pytest.fixture
def mcp(monkeypatch, store):
    import mcp_server.server as srv
    from mcp_server.backend import ProductionBackend

    _authenticated(monkeypatch, srv)
    return srv.build_mcp(ProductionBackend(db_manager=store.dbm, mongo_db=store.raw))


def _call(mcp, tool: str, **args) -> dict:
    """התשובה כפי שהלקוח מקבל אותה: בלוק הטקסט של ``call_tool``, מפוענח."""
    result = asyncio.run(mcp.call_tool(tool, args))
    blocks = result[0] if isinstance(result, tuple) else result
    return json.loads(blocks[0].text)


def test_save_file_keeps_the_file_and_drops_a_description_over_the_ceiling(mcp, store):
    """תו אחד מעל התקרה: הקובץ נשמר **בלי** התיאור, והתשובה אומרת זאת בכל השדות.

    ``ok: true`` — הכתיבה קרתה, ו-``ok: false`` היה שולח את הסוכן לשלוח שוב את כל
    התוכן. ``description_saved: false`` הוא מה שאי אפשר לפספס, ולצידו המספרים
    והיחידה, וההפניה לכלי שמעדכן תיאור בלבד. האוסף נקרא ישירות: לא נשמר תיאור,
    ולכן גם לא חותמת. נופלת על הקוד שלפני: שם התיאור נשמר במלואו, בלי שום שדה.
    """
    too_long = "א" * (FILE_DESCRIPTION_MAX_CHARS + 1)
    res = _call(mcp, "codekeeper_save_file", file_name=NAME, code="# גוף\n", description=too_long)

    stored = latest(store.code_snippets, USER, NAME)
    assert stored["code"] == "# גוף\n", "הקובץ עצמו לא נשמר"
    assert stored["description"] == "", "תיאור מעל התקרה נשמר"
    assert DESCRIPTION_SET_AT_VERSION_FIELD not in stored, "חותמת על תיאור שלא נשמר"

    assert res["ok"] is True and res["created"] is True, res
    assert res["description_saved"] is False, res
    assert res["max_chars"] == FILE_DESCRIPTION_MAX_CHARS
    assert res["actual_chars"] == FILE_DESCRIPTION_MAX_CHARS + 1
    assert "characters, not bytes" in res["message"], res
    assert "codekeeper_update_file_description" in res["hint"], res
    assert res["file"]["description"] == "", "התשובה מתארת תיאור שלא נשמר"


@pytest.mark.parametrize("description", [
    "א" * FILE_DESCRIPTION_MAX_CHARS,
    AGENT_REPORT_TEXT,
], ids=["exactly_the_ceiling", "agent_report_413_chars_625_bytes"])
def test_save_file_stores_a_description_within_the_ceiling_and_says_so(mcp, store, description):
    """בתקרה בדיוק, ו-413 תווים שהם 625 בתים — נשמרים, ו-``description_saved: true``.

    ``true`` נגזר ממה שנקרא חזרה מהאוסף, ולא מהבקשה: האוסף כאן הוא מקור האמת, והתשובה
    חייבת להסכים איתו. נופלת על הקוד שלפני: שם אין ``description_saved``.
    """
    res = _call(mcp, "codekeeper_save_file", file_name=NAME, code="# גוף\n", description=description)

    stored = latest(store.code_snippets, USER, NAME)
    assert stored["description"] == description
    assert res["ok"] is True and res["description_saved"] is True, res
    assert "max_chars" not in res and "hint" not in res, res


@pytest.mark.parametrize("description", ["", "   \n"], ids=["empty", "whitespace"])
def test_save_file_without_a_description_says_nothing_about_one(mcp, store, description):
    """לא נשלח תיאור (או רק רווחים, שה-``strip`` מרוקן) — אין על מה לדווח, ואין שדה."""
    res = _call(mcp, "codekeeper_save_file", file_name=NAME, code="# גוף\n", description=description)

    assert res["ok"] is True, res
    assert "description_saved" not in res, res


def test_a_failed_read_back_leaves_description_saved_unknown(mcp, store, monkeypatch):
    """הקריאה החוזרת נכשלה — ``description_saved: null``, ולא ``true`` מהבקשה.

    אותו "לא ידוע" של ``content_changed: null``: הכתיבה קרתה, אבל אין בידינו את מה
    שנשמר, ותשובה שאומרת "נשמר" על סמך מה שביקשנו היא הד של הבקשה (K11).
    """
    from pymongo.errors import AutoReconnect

    real_find_one = store.code_snippets.find_one

    def find_one(query=None, *args, **kwargs):
        if isinstance(query, dict) and set(query) == {"_id", "user_id"}:
            raise AutoReconnect("connection reset during read-back")
        return real_find_one(query, *args, **kwargs)

    monkeypatch.setattr(store.code_snippets, "find_one", find_one)
    res = _call(mcp, "codekeeper_save_file", file_name=NAME, code="# גוף\n", description="קצר")

    assert latest(store.code_snippets, USER, NAME)["description"] == "קצר", "הנחת המקרה: נכתב"
    assert res["ok"] is True and res["content_changed"] is None, res
    assert res["description_saved"] is None, res


def test_description_saved_is_what_was_stored_not_what_was_sent(mcp, store, monkeypatch):
    """מה שנקרא חזרה שונה ממה שנשלח — ``description_saved: false``, בלי שדות התקרה.

    שכבה בדרך שמשנה את התיאור (כאן — דמה שמוסיפה תו לפני הכתיבה; בעולם — עדכון
    תיאור מקביל שנוחת בין הכתיבה לקריאה החוזרת) היא בדיוק מה ש-"קרא את המצב" בא
    לתפוס: ``true`` שנגזר מהבקשה היה מאשר תיאור שלא נשמר. ``file.description`` אומר מה
    כן נשמר, ואין ``max_chars``, כי זו לא התקרה.
    """
    real_save = store.dbm.save_code_snippet_returning_id

    def save_with_a_changed_description(snippet):
        snippet.description = snippet.description + "!"
        return real_save(snippet)

    monkeypatch.setattr(store.dbm, "save_code_snippet_returning_id", save_with_a_changed_description)
    res = _call(mcp, "codekeeper_save_file", file_name=NAME, code="# גוף\n", description="קצר")

    assert latest(store.code_snippets, USER, NAME)["description"] == "קצר!", "הנחת המקרה"
    assert res["ok"] is True and res["description_saved"] is False, res
    assert res["file"]["description"] == "קצר!"
    assert "max_chars" not in res and "hint" not in res, res


def test_a_failed_save_says_nothing_about_the_description(mcp, store, monkeypatch):
    """שמירה שנכשלה — ``ok: false`` כבר אומר ששום דבר לא נשמר, גם לא התיאור."""
    monkeypatch.setattr(store.dbm, "save_code_snippet_returning_id", lambda snippet: None)
    res = _call(mcp, "codekeeper_save_file", file_name=NAME, code="# גוף\n",
                description="א" * (FILE_DESCRIPTION_MAX_CHARS + 1))

    assert res == {"ok": False, "error": "save_failed"}, res


# ---------------------------------------------------------------------------
# 3. העתקה לעולם אינה נחסמת
# ---------------------------------------------------------------------------


def _seed_long_description(store, *, version=2, stamp=1):
    """קובץ שנשמר עם תיאור ארוך מהתקרה — כמו שהבוט ושמירות ישנות עדיין יכולים לכתוב."""
    store.code_snippets.insert_one({
        "user_id": USER, "file_name": NAME, "code": "# כותרת\nשורה\n",
        "programming_language": "markdown", "description": LONG, "tags": [],
        "version": version, "is_active": True, DESCRIPTION_SET_AT_VERSION_FIELD: stamp,
        "created_at": STAMP_TIME, "updated_at": STAMP_TIME,
    })


@pytest.mark.parametrize("tool, args", [
    ("codekeeper_edit_file", {"old_string": "שורה", "new_string": "שורה ערוכה"}),
    ("codekeeper_append_file", {"content": "תוספת\n"}),
    ("codekeeper_multi_edit_file", {"edits": [{"old_string": "שורה", "new_string": "אחרת"}]}),
], ids=["edit_file", "append_file", "multi_edit_file"])
def test_editing_a_file_whose_stored_description_is_over_the_ceiling_keeps_it(mcp, store, tool, args):
    """כלי העריכה מעתיקים תיאור של 800 תווים לגרסה החדשה — ואינם נחסמים בגללו.

    התיאור אינו מגיע מבחוץ, ולכן התקרה אינה חלה עליו (``description_length_error``,
    "זהה לקודם"). והחותמת עוברת כמות שהיא — העתקה אינה "התיאור נבדק". זה שומר ולא
    תיקון: על הקוד שלפני הוא עובר, כי שם לא נאכף דבר; מה שהוכיח שהוא מסוגל ליפול
    הוא מוטציה שאוכפת את התקרה גם על העתקה (בגוף ה-PR).
    """
    _seed_long_description(store)

    res = _call(mcp, tool, file_name=NAME, **args)

    assert res["ok"] is True, res
    stored = latest(store.code_snippets, USER, NAME)
    assert stored["version"] == 3
    assert stored["description"] == LONG, "התיאור שהועתק נחתך, נמחק או נחסם"
    assert stored[DESCRIPTION_SET_AT_VERSION_FIELD] == 1, "העתקה איפסה את החותמת"


# ---------------------------------------------------------------------------
# 4. ``codekeeper_update_file_description`` — מה נשלח למונגו, ואיך התשובה נגזרת
# ---------------------------------------------------------------------------


class _RecordingCollection:
    """collection שמקליט את הכתיבה ומחזיר מסמך "לפני" שנקבע מראש.

    היא מחליפה **רק** את מונגו: הקריאה עדיין נכנסת דרך ``mcp.call_tool`` ועוברת את
    ``handlers`` ואת ``update_file_metadata_in``. ``before`` הוא המסמך שהכתיבה ראתה —
    ולכן גם מה שהתשובה חייבת להיגזר ממנו.
    """

    def __init__(self, before_description):
        self.calls = []
        self.before_description = before_description

    def find_one_and_update(self, query, update, **kwargs):
        self.calls.append({"query": query, "update": update, **kwargs})
        return {"_id": "x", "file_name": NAME, "version": 7,
                "description": self.before_description, "tags": []}


class _ManagerOnCollection:
    """``DatabaseManager`` שמאציל ל-``Repository`` האמיתי, מעל האוסף שהטסט נותן."""

    def __init__(self, collection):
        self.collection = collection

    def _repo(self):
        from database.repository import Repository

        return Repository(self)

    def update_file_metadata(self, user_id, **kwargs):
        return self._repo().update_file_metadata(user_id, **kwargs)

    def save_code_snippet_returning_id(self, snippet):
        return self._repo().save_code_snippet_returning_id(snippet)

    def find_version_by_id(self, doc_id, user_id):
        return self._repo().find_version_by_id(doc_id, user_id)

    def get_latest_version_fresh(self, user_id, file_name):
        return self._repo()._fetch_latest_version(user_id, file_name)

    def get_version(self, user_id, file_name, version):
        return self._repo().get_version(user_id, file_name, version)

    def get_file_by_id(self, file_id):
        return self._repo().get_file_by_id(file_id)


def _recording_mcp(monkeypatch, before_description):
    import mcp_server.server as srv
    from mcp_server.backend import ProductionBackend

    _authenticated(monkeypatch, srv)
    collection = _RecordingCollection(before_description)
    return srv.build_mcp(ProductionBackend(db_manager=_ManagerOnCollection(collection))), collection


def test_a_long_description_is_written_only_on_condition_that_it_is_the_stored_text(monkeypatch):
    """תיאור ארוך מהתקרה — **כל** שדה בכתיבה עטוף באותו ``$cond`` על ``$description``.

    זה מה שמחזיק את "זהה לקודם עובר" בלי קריאה לפני הכתיבה: ההשוואה יושבת בתוך
    הפעולה האטומית, מול המסמך שמתעדכן. הענף השני של כל שדה הוא השדה עצמו
    (``"$" + שם``), כלומר "אל תזיז". הטקסט עצמו ב-``$literal``, כי מחרוזת שמתחילה ב-
    ``$`` היא נתיב שדה בתוך pipeline. נופלת על הקוד שלפני: שם הבקשה נדחתה לפני
    שנשלחה למונגו, ולא הייתה כתיבה בכלל. מה ש-``$cond`` עושה במסד — בקבוצה 5.
    """
    mcp, collection = _recording_mcp(monkeypatch, before_description=LONG)

    _call(mcp, "codekeeper_update_file_description", file_name=NAME, description=LONG)

    assert len(collection.calls) == 1, collection.calls
    update = collection.calls[0]["update"]
    assert isinstance(update, list) and len(update) == 1 and set(update[0]) == {"$set"}, update
    stage = update[0]["$set"]
    condition = {"$eq": ["$description", {"$literal": LONG}]}
    assert set(stage) == {"description", "updated_at", DESCRIPTION_SET_AT_VERSION_FIELD}, stage
    for field, value in stage.items():
        assert value["$cond"][0] == condition, (field, value)
        assert value["$cond"][2] == "$" + field, (field, value)
    assert stage["description"]["$cond"][1] == {"$literal": LONG}
    assert stage[DESCRIPTION_SET_AT_VERSION_FIELD]["$cond"][1] == "$version"
    assert isinstance(stage["updated_at"]["$cond"][1], datetime)


def test_a_description_within_the_ceiling_is_written_without_a_condition(monkeypatch):
    """בתקרה — אותה כתיבה כמו עד היום, בלי ``$cond``: התנאי שמור לתיאור ארוך בלבד."""
    mcp, collection = _recording_mcp(monkeypatch, before_description="ישן")

    res = _call(mcp, "codekeeper_update_file_description", file_name=NAME,
                description="א" * FILE_DESCRIPTION_MAX_CHARS)

    assert res["ok"] is True, res
    stage = collection.calls[0]["update"][0]["$set"]
    assert stage["description"] == {"$literal": "א" * FILE_DESCRIPTION_MAX_CHARS}
    assert stage[DESCRIPTION_SET_AT_VERSION_FIELD] == "$version"


def test_the_answer_follows_the_document_the_write_saw(monkeypatch):
    """התשובה נגזרת מהמסמך ש-``find_one_and_update`` החזיר — אותו מסמך שה-``$cond`` נבדק מולו.

    תיאור שמור זהה ← ``ok`` ו-``unchanged: true``. תיאור שמור אחר ← ``description_too_long``
    עם ``max_chars`` ו-``actual_chars`` והודעה ביחידות. נופלת על הקוד שלפני: שם שני
    המקרים נדחו, והסירוב נשא רק ``max``.
    """
    same, _ = _recording_mcp(monkeypatch, before_description=LONG)
    res = _call(same, "codekeeper_update_file_description", file_name=NAME, description=LONG)
    assert res["ok"] is True and res["unchanged"] is True, res
    assert res["description"] == LONG and res["previous_description"] == LONG

    other, _ = _recording_mcp(monkeypatch, before_description=OTHER_LONG)
    res = _call(other, "codekeeper_update_file_description", file_name=NAME, description=LONG)
    assert set(res) == {"ok", "error", "max_chars", "actual_chars", "message"}, res
    assert res["ok"] is False and res["error"] == "description_too_long", res
    assert res["max_chars"] == FILE_DESCRIPTION_MAX_CHARS and res["actual_chars"] == len(LONG)
    assert "characters, not bytes" in res["message"] and "Nothing was written" in res["message"]


# ---------------------------------------------------------------------------
# 5. מול ``mongod`` אמיתי — מה ש-``$cond`` עושה במסד
# ---------------------------------------------------------------------------


@pytest.fixture
def mongo_mcp(monkeypatch, wired_mongo):
    """שרת MCP מעל מסד בדיקה אמיתי; האוסף מתרוקן בכל טסט."""
    import mcp_server.server as srv
    from mcp_server.backend import ProductionBackend

    load_production_config(monkeypatch)
    clear_local_cache()
    db = wired_mongo.get_db()
    db.code_snippets.delete_many({})
    _authenticated(monkeypatch, srv)
    yield srv.build_mcp(ProductionBackend(db_manager=_ManagerOnCollection(db.code_snippets),
                                          mongo_db=db)), db.code_snippets
    clear_local_cache()


def _insert_version(collection, version, description, stamp=None):
    doc = {
        "user_id": USER, "file_name": NAME, "code": f"# גרסה {version}\n",
        "programming_language": "markdown", "description": description, "tags": ["review"],
        "version": version, "is_active": True,
        "created_at": STAMP_TIME, "updated_at": STAMP_TIME,
    }
    if stamp is not None:
        doc[DESCRIPTION_SET_AT_VERSION_FIELD] = stamp
    collection.insert_one(doc)


def _versions(collection):
    return {d["version"]: d for d in collection.find({"user_id": USER, "file_name": NAME})}


def test_real_mongo_at_the_ceiling_passes_and_one_over_writes_nothing(mongo_mcp):
    """בתקרה — נכתב. תו אחד מעל, כשהשמור אחר — **שום שדה** לא זז במסד.

    המסמך כולו מושווה לפני ואחרי: לא התיאור, לא ``updated_at``, לא החותמת, ולא שדה
    חדש שנוסף כ-``null`` מענף ה"אל תזיז" של ``$cond`` (נמדד: לא נוסף). נופלת על הקוד
    שלפני רק בצורת התשובה (``max``), כי שם הבקשה נדחתה לפני הכתיבה.
    """
    mcp, collection = mongo_mcp
    _insert_version(collection, 1, "ישן", stamp=1)

    at_ceiling = "א" * FILE_DESCRIPTION_MAX_CHARS
    assert _call(mcp, "codekeeper_update_file_description", file_name=NAME,
                 description=at_ceiling)["ok"] is True
    before = _versions(collection)[1]
    assert before["description"] == at_ceiling

    res = _call(mcp, "codekeeper_update_file_description", file_name=NAME,
                description=at_ceiling + "ב")
    assert res["ok"] is False and res["error"] == "description_too_long", res
    assert res["max_chars"] == FILE_DESCRIPTION_MAX_CHARS
    assert res["actual_chars"] == FILE_DESCRIPTION_MAX_CHARS + 1
    assert _versions(collection)[1] == before, "סירוב שינה את המסמך"


def test_real_mongo_resending_a_long_stored_description_marks_it_checked(mongo_mcp):
    """800 תווים ששמורים — אותו טקסט חוזר: ``unchanged: true``, והחותמת מתאפסת לגרסה הנוכחית.

    זה מה ש"זהה לקודם עובר" שומר: הכלי מסמן תיאור כנבדק גם כשהוא ארוך מהתקרה, כי הוא
    נכתב לפני שהתקרה נאכפה. הגיל נקרא בחזרה מ-``codekeeper_get_file`` — אפס. נופלת על
    הקוד שלפני: שם אותו טקסט נדחה ב-``description_too_long``.
    """
    mcp, collection = mongo_mcp
    _insert_version(collection, 1, LONG, stamp=1)
    _insert_version(collection, 2, LONG, stamp=1)

    res = _call(mcp, "codekeeper_update_file_description", file_name=NAME, description=LONG)

    assert res["ok"] is True and res["unchanged"] is True, res
    versions = _versions(collection)
    assert versions[2][DESCRIPTION_SET_AT_VERSION_FIELD] == 2, "החותמת לא התאפסה"
    assert versions[2]["updated_at"] != STAMP_TIME.replace(tzinfo=None)
    assert versions[1][DESCRIPTION_SET_AT_VERSION_FIELD] == 1, "גרסה קודמת זזה"
    read = _call(mcp, "codekeeper_get_file", file_name=NAME)["file"]
    assert read["description_age_versions"] == 0


def test_real_mongo_a_different_long_description_is_refused_even_over_a_long_one(mongo_mcp):
    """שמור 800, נשלח טקסט **אחר** בן 600 — ``description_too_long``, ושום דבר לא זז."""
    mcp, collection = mongo_mcp
    _insert_version(collection, 1, LONG, stamp=1)
    before = _versions(collection)

    res = _call(mcp, "codekeeper_update_file_description", file_name=NAME, description=OTHER_LONG)

    assert res["ok"] is False and res["error"] == "description_too_long", res
    assert res["actual_chars"] == len(OTHER_LONG)
    assert _versions(collection) == before


def test_real_mongo_identical_to_an_older_version_is_not_identical(mongo_mcp):
    """הטקסט נשמר בגרסה 1, והאחרונה נושאת אחר — סירוב, ושתי הגרסאות לא זזות.

    זה ההבדל בין ``$cond`` בתוך הכתיבה לבין "זהה" בפילטר: עם המיון לפי גרסה, פילטר
    על התיאור היה תופס את גרסה 1 ומאפס את החותמת **שלה** — מסמך שאינו הקובץ שהמשתמש
    רואה. המוטציה שמעבירה את התנאי לפילטר מפילה את הטסט הזה (בגוף ה-PR).
    """
    mcp, collection = mongo_mcp
    _insert_version(collection, 1, LONG, stamp=1)
    _insert_version(collection, 2, "קצר ואחר", stamp=2)
    before = _versions(collection)

    res = _call(mcp, "codekeeper_update_file_description", file_name=NAME, description=LONG)

    assert res["ok"] is False and res["error"] == "description_too_long", res
    assert _versions(collection) == before


def test_real_mongo_the_agent_report_text_is_accepted_by_the_update(mongo_mcp):
    """413 תווים שהם 625 בתים — עובר, כי התקרה בתווים. זה הדיווח שהוליד את השינוי."""
    mcp, collection = mongo_mcp
    _insert_version(collection, 1, "ישן", stamp=1)

    res = _call(mcp, "codekeeper_update_file_description", file_name=NAME,
                description=AGENT_REPORT_TEXT)

    assert res["ok"] is True, res
    assert _versions(collection)[1]["description"] == AGENT_REPORT_TEXT


# ---------------------------------------------------------------------------
# 6. מה שהסוכן קורא לפני הקריאה — תיאורי הכלים, והתיעוד
# ---------------------------------------------------------------------------


def _schemas(mcp) -> dict:
    tools = {tool.name: tool for tool in mcp._tool_manager.list_tools()}
    return {name: tools[name] for name in
            ("codekeeper_save_file", "codekeeper_update_file_description")}


def _description_param(tool) -> str:
    return tool.parameters["properties"]["description"]["description"]


def test_both_tools_open_their_description_parameter_with_the_ceiling(mcp):
    """הדיווח: הסכימה לא אמרה שיש תקרה, וגילו אותה מקריאה שנכשלה.

    **המשפט הראשון** של תיאור הפרמטר נושא את המספר ואת היחידה, כי לקוח שמקצר תיאור
    פרמטר לכ-120 תווים רואה רק אותו. ותיאור ``codekeeper_update_file_description`` נוקב
    בשני שדות הסירוב. נופלת על הקוד שלפני: לפרמטר לא היה תיאור בכלל.
    """
    tools = _schemas(mcp)
    opening = f"At most {FILE_DESCRIPTION_MAX_CHARS:,} characters (characters, not bytes)."
    for name, tool in tools.items():
        text = _description_param(tool)
        assert text.startswith(opening), (name, text)
        assert len(opening) <= 120
    assert "description_saved: false" in _description_param(tools["codekeeper_save_file"])
    update = tools["codekeeper_update_file_description"]
    assert "description_too_long" in _description_param(update)
    for field in ("description_too_long", "max_chars", "actual_chars"):
        assert field in update.description, (field, update.description)


def test_the_descriptions_are_built_from_the_constant_the_tools_enforce(monkeypatch, store):
    """הקבוע זז — התיאורים **והאכיפה** זזים איתו, לאותו מספר.

    זה מה שמבדיל תיאור שנבנה מהקבוע מתיאור שבו מישהו הקליד 500: אחרי השינוי, מספר
    מוקלד היה משקר, וכאן הוא נופל מיד ולא רק ביום שמישהו משנה את הקבוע. השמירה עוברת
    באותו מסלול כמו בקבוצה 2, והתקרה שהיא מדווחת היא הקבוע שזז.
    """
    import file_description
    import mcp_server.server as srv
    from mcp_server.backend import ProductionBackend

    monkeypatch.setattr(file_description, "FILE_DESCRIPTION_MAX_CHARS", 7)
    _authenticated(monkeypatch, srv)
    mcp = srv.build_mcp(ProductionBackend(db_manager=store.dbm, mongo_db=store.raw))

    for name, tool in _schemas(mcp).items():
        assert _description_param(tool).startswith(
            "At most 7 characters (characters, not bytes)."), name

    res = _call(mcp, "codekeeper_save_file", file_name=NAME, code="# גוף\n", description="12345678")
    assert res["description_saved"] is False and res["max_chars"] == 7, res


def test_the_documented_ceiling_is_the_code_ceiling():
    """טבלת הקבועים ב-``docs/mcp-server.rst`` נוקבת ב-``FILE_DESCRIPTION_MAX_CHARS`` ובמודול שלו.

    קובץ RST אינו יכול לגזור דבר (``prose-restates-code-fact``), ולכן הערך המצופה מחושב
    כאן מהקבוע, באותה צורה שהטבלה כותבת — כמו הטסט על ``MAX_EDIT_PAIRS`` ב-
    ``tests/test_mcp_multi_edit.py``. מוטציה שמפילה: לשנות את הקבוע בלי הטבלה, או להפך.
    """
    lines = (ROOT / "docs" / "mcp-server.rst").read_text(encoding="utf-8").splitlines()
    row = lines.index("   * - ``FILE_DESCRIPTION_MAX_CHARS``")
    assert lines[row + 1].strip() == f"- {FILE_DESCRIPTION_MAX_CHARS:,}"
    assert "``file_description.py``" in lines[row + 2], lines[row + 2]
