"""‏``codekeeper_multi_edit_file`` ושער ``expected_content_sha256`` — דרך ``mcp.call_tool``.

**הכלי:** כמה עריכות מדויקות בקובץ אחד, בגרסה אחת. הזוגות מוחלים בסדר שנשלחו,
כל זוג על התוצאה של קודמו, וכולם או כלום. **השער:** ``expected_content_sha256``
בשלושת כלי העריכה — הכתיבה מסורבת ב-``conflict`` כשהקובץ השתנה מאז שהסוכן קרא.

**כל בדיקה עוברת דרך ``call_tool``** על שרת MCP אמיתי (``build_mcp``), מעל
``ProductionBackend``, ``DatabaseManager`` ו-``Repository`` אמיתיים, עם ``config.py``
של הייצור (``tests/_save_layer_harness.py``) — כך ששתי השכבות של ה-SDK (הוולידציה של
pydantic ו-``pre_parse_json``) בדרך, והן נראות רק שם (``TESTING-PATTERNS`` T1). רק
האוספים מוחלפים בדמה המשותפת (``tests/_fake_mongo.py``); המסלול דרך BSON והדרייבר
נבדק מול ``mongod`` אמיתי ב-``tests/test_mcp_content_sha256_real_mongo.py``.

**ה-hash בכל בדיקה מחושב ביד** — ``hashlib`` על ``code`` כפי שהוא יושב באוסף — ולא
נלקח מתשובת הכלי: טסט שמאשר את הכלי בעזרת הכלי אינו מסוגל ליפול.

**"שום דבר לא נכתב" נמדד בשלושה מקומות**, כי כל אחד מהם יכול להישאר שלם בזמן
שהאחרים לא: מספר מסמכי הגרסה באוסף, ה-hash של הגרסה האחרונה, ומספר האירועים ב-
``push_events`` (ה-hook של ההתראה יושב ב-``ProductionBackend.save_file``).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import tracemalloc
from types import SimpleNamespace

import pytest

# ‏``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _save_layer_harness import clear_local_cache, install_fake_collections, latest, load_production_config

pytest.importorskip("mcp")

from mcp.server.fastmcp.exceptions import ToolError  # noqa: E402

USER = 6363
NAME = "handoff.md"
TOOL = "codekeeper_multi_edit_file"
EDIT_TOOLS = ("codekeeper_edit_file", "codekeeper_append_file", TOOL)
#: מחרוזת שמסמנת ערך שנשלח, כדי לבדוק שאף סירוב אינו מהדהד אותו.
SECRET = "SECRET-VALUE-7f3a"


# ---------------------------------------------------------------------------
# עזרים
# ---------------------------------------------------------------------------


@pytest.fixture
def store(monkeypatch):
    load_production_config(monkeypatch)
    yield install_fake_collections(monkeypatch)
    clear_local_cache()


@pytest.fixture
def backend(store):
    from mcp_server.backend import ProductionBackend

    return ProductionBackend(db_manager=store.dbm, mongo_db=store.raw)


def _build(monkeypatch, backend):
    """שרת MCP אמיתי, עם זהות מאומתת והרשאת כתיבה — כמו ב-``tests/test_mcp_content_sha256.py``."""
    import mcp.server.auth.middleware.auth_context as auth_context

    import mcp_server.server as srv

    # ``build_mcp`` קורא ל-``instrument_mcp_server``, שזורק מחוץ לפרודקשן בלי PostHog.
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(srv, "current_user_id", lambda ctx=None: USER)
    monkeypatch.setattr(auth_context, "get_access_token", lambda: SimpleNamespace(scopes=["read", "write"]))
    return srv.build_mcp(backend)


@pytest.fixture
def mcp(monkeypatch, backend):
    return _build(monkeypatch, backend)


def _call(mcp, tool: str, **args) -> dict:
    """התשובה כפי שהלקוח מקבל אותה: בלוק הטקסט של ``call_tool``, מפוענח."""
    result = asyncio.run(mcp.call_tool(tool, args))
    blocks = result[0] if isinstance(result, tuple) else result
    return json.loads(blocks[0].text)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _versions(store, name: str = NAME) -> list[dict]:
    return [d for d in store.code_snippets.docs if d.get("user_id") == USER and d.get("file_name") == name]


def _push_count(store) -> int:
    return len(store.raw["push_events"].docs)


def _snapshot(store) -> tuple[int, int, str]:
    """מה שחייב להישאר זהה כש"שום דבר לא נכתב": מספר הגרסאות, האחרונה, וה-hash שלה."""
    doc = latest(store.code_snippets, USER, NAME)
    return len(_versions(store)), int(doc["version"]), _sha(doc["code"])


def _seed(mcp, code: str, **extra) -> None:
    assert _call(mcp, "codekeeper_save_file", file_name=NAME, code=code, **extra)["ok"] is True


def _pair(old: str, new: str, **extra) -> dict:
    return {"old_string": old, "new_string": new, **extra}


# ---------------------------------------------------------------------------
# 1. כולם או כלום, וגרסה אחת
# ---------------------------------------------------------------------------


def test_a_pair_that_fails_leaves_the_file_exactly_as_it_was(mcp, store):
    """ארבעה זוגות, השלישי אינו מתאים: ``index: 2``, ובמסד אין שום עקבה.

    **המוטציה שחייבת להפיל אותו — שמירה גם כשזוג נכשל:** ``break`` במקום ``return``
    בלולאה. אז שני הזוגות הראשונים נשמרים כגרסה, וזה בדיוק העדכון החצי-מוחל שהכלי
    בא למנוע.
    """
    _seed(mcp, "alpha\nbeta\ngamma\ndelta\n")
    before, pushes = _snapshot(store), _push_count(store)

    res = _call(mcp, TOOL, file_name=NAME, edits=[
        _pair("alpha", "ALPHA"), _pair("beta", "BETA"), _pair("nope", "x"), _pair("delta", "DELTA"),
    ])

    assert res["ok"] is False and res["error"] == "no_match" and res["index"] == 2, res
    assert "nothing was written" in res["hint"]
    assert _snapshot(store) == before
    assert _push_count(store) == pushes


def test_a_batch_that_applies_is_one_version_one_notification_and_one_step_of_description_age(mcp, store):
    """גרסה אחת, אירוע התראה אחד, והתיאור מזדקן בגרסה אחת — לא בכמה.

    שלושתם נובעים מכך שהבאץ' עובר פעם אחת ב-``_resave_edited``, שקורא ל-
    ``ProductionBackend.save_file``: ה-hook של ההתראה יושב שם, והחותמת של התיאור נגזרת ב-``save_code_snippet``
    מהשוואה לתיאור הקודם (הכלי מעתיק אותו, ולכן היא עוברת כמו שהיא).
    """
    _seed(mcp, "alpha\nbeta\ngamma\n", description="מסמך מסירה")
    assert _call(mcp, "codekeeper_get_file", file_name=NAME, lines=[1, 1])["file"]["description_age_versions"] == 0
    count, version, _ = _snapshot(store)
    pushes = _push_count(store)

    res = _call(mcp, TOOL, file_name=NAME, edits=[
        _pair("alpha", "ALPHA"), _pair("beta", "BETA"), _pair("gamma", "GAMMA"),
    ])

    stored = latest(store.code_snippets, USER, NAME)
    assert res["ok"] is True, res
    assert res["edits_applied"] == 3 and res["replacements"] == 3
    assert stored["code"] == "ALPHA\nBETA\nGAMMA\n"
    assert res["file"]["content_sha256"] == _sha(stored["code"])
    assert res["content_changed"] is False
    assert len(_versions(store)) == count + 1 and int(stored["version"]) == version + 1
    assert _push_count(store) == pushes + 1
    assert stored["description"] == "מסמך מסירה"
    read = _call(mcp, "codekeeper_get_file", file_name=NAME, lines=[1, 1])["file"]
    assert read["description_age_versions"] == 1


# ---------------------------------------------------------------------------
# 2. הסדר, replace_all, ומה נספר
# ---------------------------------------------------------------------------


def test_each_pair_applies_to_the_result_of_the_pair_before_it(mcp, store):
    """``old_string`` שקיים רק בתוצאה של הזוג הקודם — עובר; אותו זוג לפני קודמו — ``no_match``.

    **המוטציה שחייבת להפיל אותו — החלת הזוגות על המקור:** ``_apply_edit(stored, ...)``
    במקום ``_apply_edit(code, ...)``. אז הזוג השני אינו מוצא את ``bar``.
    """
    _seed(mcp, "foo\n")
    before = _snapshot(store)

    wrong_order = _call(mcp, TOOL, file_name=NAME, edits=[_pair("bar", "baz"), _pair("foo", "bar")])
    assert wrong_order["ok"] is False and wrong_order["error"] == "no_match"
    assert wrong_order["index"] == 0
    assert _snapshot(store) == before

    res = _call(mcp, TOOL, file_name=NAME, edits=[_pair("foo", "bar"), _pair("bar", "baz")])
    assert res["ok"] is True, res
    assert latest(store.code_snippets, USER, NAME)["code"] == "baz\n"


def test_replace_all_belongs_to_its_own_pair(mcp, store):
    """זוג אחד עם ``replace_all: true`` וזוג אחד בלעדיו, באותו באץ'.

    והזוג בלי ``replace_all`` נשפט לבדו: שני מופעים שלו הם ``ambiguous_match``, גם
    כשזוג אחר באותו באץ' ביקש ``replace_all``.
    """
    _seed(mcp, "x x x\ny\nq q\n")
    before = _snapshot(store)

    ambiguous = _call(mcp, TOOL, file_name=NAME, edits=[
        _pair("x", "z", replace_all=True), _pair("q", "w"),
    ])
    assert ambiguous["ok"] is False and ambiguous["error"] == "ambiguous_match"
    assert ambiguous["index"] == 1 and ambiguous["occurrences"] == 2
    assert "replace_all" in ambiguous["hint"]
    assert _snapshot(store) == before

    res = _call(mcp, TOOL, file_name=NAME, edits=[
        _pair("x", "z", replace_all=True), _pair("y", "w", replace_all=False),
    ])
    assert res["ok"] is True, res
    assert latest(store.code_snippets, USER, NAME)["code"] == "z z z\nw\nq q\n"


def test_replacements_counts_replacements_and_edits_applied_counts_pairs(mcp, store):
    """``replace_all`` על שבעה מופעים ועוד זוג רגיל: ``replacements: 8``, ``edits_applied: 2``."""
    _seed(mcp, "a " * 7 + "\nb\n")

    res = _call(mcp, TOOL, file_name=NAME, edits=[_pair("a", "c", replace_all=True), _pair("b", "d")])

    assert res["ok"] is True, res
    assert res["replacements"] == 8
    assert res["edits_applied"] == 2
    assert latest(store.code_snippets, USER, NAME)["code"] == "c " * 7 + "\nd\n"


# ---------------------------------------------------------------------------
# 3. האבחון בכשל — שני מוני המופעים
# ---------------------------------------------------------------------------


def test_no_match_says_when_an_earlier_pair_changed_the_text(mcp, store):
    """זוג 0 מחליף ``foo`` ב-``bar``, זוג 1 מחפש ``foo``: 0 בטקסט, 1 בגרסה השמורה.

    **המוטציה שחייבת להפיל אותו — השמטת השדה השני** (``occurrences_in_stored_version``).
    """
    _seed(mcp, "foo\n")

    res = _call(mcp, TOOL, file_name=NAME, edits=[_pair("foo", "bar"), _pair("foo", "baz")])

    assert res["ok"] is False and res["error"] == "no_match" and res["index"] == 1
    assert res["occurrences"] == 0
    assert res["occurrences_in_stored_version"] == 1
    assert "earlier pair" in res["hint"]


def test_ambiguous_match_says_when_an_earlier_pair_made_the_second_copy(mcp, store):
    """זוג 0 יוצר עותק שני של מה שזוג 1 מחפש: 2 בטקסט, 1 בגרסה השמורה."""
    _seed(mcp, "one foo\n")

    res = _call(mcp, TOOL, file_name=NAME, edits=[_pair("one", "foo"), _pair("foo", "x")])

    assert res["ok"] is False and res["error"] == "ambiguous_match" and res["index"] == 1
    assert res["occurrences"] == 2
    assert res["occurrences_in_stored_version"] == 1
    assert "earlier pair" in res["hint"]


def test_when_the_two_counts_agree_the_text_is_simply_not_in_the_file(mcp, store):
    """מונים שווים — אין זוג קודם אשם, והרמז אינו טוען שיש."""
    _seed(mcp, "foo\n")

    res = _call(mcp, TOOL, file_name=NAME, edits=[_pair("foo", "bar"), _pair("nope", "x")])

    assert res["error"] == "no_match" and res["index"] == 1
    assert res["occurrences"] == res["occurrences_in_stored_version"] == 0
    assert "earlier pair" not in res["hint"]


@pytest.mark.parametrize(
    ("pair", "error"),
    [(_pair("", "x"), "empty_old_string"), (_pair("foo", "foo"), "old_and_new_identical")],
    ids=["empty_old_string", "old_and_new_identical"],
)
def test_the_other_edit_codes_carry_the_index_too(mcp, store, pair, error):
    """הקודים של ``codekeeper_edit_file`` עוברים כמו שהם, עם ``index`` ובלי מוני מופעים."""
    _seed(mcp, "foo\n")
    before = _snapshot(store)

    res = _call(mcp, TOOL, file_name=NAME, edits=[_pair("foo", "bar"), pair])

    assert res["ok"] is False and res["error"] == error and res["index"] == 1
    assert "occurrences" not in res
    assert _snapshot(store) == before


# ---------------------------------------------------------------------------
# 4. מה שה-SDK עושה לארגומנטים בדרך
# ---------------------------------------------------------------------------


def test_edits_sent_as_json_text_is_parsed_like_any_list(mcp, store):
    """Claude Desktop שולח רשימות כמחרוזת JSON; ``edits`` אינו מוצהר ``str`` ולכן מתפרסר."""
    _seed(mcp, "alpha\nbeta\n")

    res = _call(mcp, TOOL, file_name=NAME,
                edits=json.dumps([_pair("alpha", "ALPHA"), _pair("beta", "BETA")]))

    assert res["ok"] is True, res
    assert latest(store.code_snippets, USER, NAME)["code"] == "ALPHA\nBETA\n"


@pytest.mark.parametrize("as_json_text", [False, True], ids=["list", "json_text"])
def test_strings_that_look_like_json_inside_a_pair_arrive_as_strings(mcp, store, as_json_text):
    """``"null"`` ו-``"[1, 2]"`` בתוך זוג מגיעים כמחרוזות, והחיפוש מוצא אותן.

    ``pre_parse_json`` רץ על ארגומנטים ברמה העליונה בלבד (``FuncMetadata.pre_parse_json``,
    ``mcp 1.28.1``), ולכן מה שבתוך הזוג אינו מפוענח — גם כשהרשימה כולה נשלחה כמחרוזת.
    """
    _seed(mcp, 'value = null\nitems = [1, 2]\nobj = {"a": 1}\n')
    edits = [_pair("null", "None"), _pair("[1, 2]", "[3]"), _pair('{"a": 1}', "{}")]

    res = _call(mcp, TOOL, file_name=NAME, edits=json.dumps(edits) if as_json_text else edits)

    assert res["ok"] is True, res
    assert latest(store.code_snippets, USER, NAME)["code"] == "value = None\nitems = [3]\nobj = {}\n"


# ---------------------------------------------------------------------------
# 5. זוג פגום, רשימה ריקה, ומעל התקרה — נענים לפני שדבר נקרא
# ---------------------------------------------------------------------------

#: זוגות פגומים, כל אחד עם ה-``loc`` שהסירוב חייב לשאת. ``SECRET`` יושב בערכים ובשם
#: המפתח הזר — המפתח עצמו **כן** יוצא (הבריף: "שם השדה והבעיה"), ולכן הוא נבדק לחוד.
MALFORMED = {
    "unknown_key": ({"old_string": SECRET, "new_string": "x", "colour": SECRET}, ["colour"]),
    "replace_all_not_a_json_boolean": (_pair(SECRET, "x", replace_all="true"), ["replace_all"]),
    "replace_all_one": (_pair(SECRET, "x", replace_all=1), ["replace_all"]),
    "missing_new_string": ({"old_string": SECRET}, ["new_string"]),
    "old_string_not_a_string": ({"old_string": [SECRET], "new_string": "x"}, ["old_string"]),
    "pair_not_an_object": (SECRET, []),
}


@pytest.mark.parametrize("as_json_text", [False, True], ids=["list", "json_text"])
@pytest.mark.parametrize("case", sorted(MALFORMED))
def test_a_malformed_pair_is_invalid_edit_with_its_index_and_without_its_value(mcp, store, case, as_json_text):
    """תשובת כלי ``invalid_edit`` — לא ``ToolError`` של סכימה — עם הזוג והשדה, בלי הערך.

    הזוג הפגום יושב במקום 3, אחרי שלושה תקינים: הוולידציה המבנית עוברת על כל הרשימה
    לפני שזוג ראשון מוחל, ולכן הסירוב מצביע עליו מיד ושום דבר אינו נכתב.

    **המוטציה שחייבת להפיל אותו — ``include_input=True`` ב-``validation_problems``:** אז
    ה-``problems`` נושא את הערך שנשלח, וה-``SECRET`` מופיע בתשובה.
    """
    _seed(mcp, "a\nb\nc\n")
    before = _snapshot(store)
    bad, field = MALFORMED[case]
    edits = [_pair("a", "A"), _pair("b", "B"), _pair("c", "C"), bad]

    res = _call(mcp, TOOL, file_name=NAME, edits=json.dumps(edits) if as_json_text else edits)

    assert res["ok"] is False and res["error"] == "invalid_edit", res
    assert res["index"] == 3
    assert all(problem["loc"][0] == 3 for problem in res["problems"]), res["problems"]
    assert [problem["loc"][1:] for problem in res["problems"]] == [field], res["problems"]
    assert all(isinstance(problem["msg"], str) and problem["msg"] for problem in res["problems"])
    assert SECRET not in json.dumps(res)
    assert _snapshot(store) == before


def test_every_malformed_pair_is_reported_at_once_and_index_is_the_first(mcp, store):
    """כל הבעיות המבניות חוזרות בתשובה אחת — כל אחת עם הזוג שלה — ו-``index`` הוא הראשון."""
    _seed(mcp, "a\n")

    res = _call(mcp, TOOL, file_name=NAME, edits=[
        _pair("a", "A"), {"old_string": "a"}, _pair("a", "b", replace_all="yes"),
    ])

    assert res["error"] == "invalid_edit" and res["index"] == 1
    assert sorted(problem["loc"] for problem in res["problems"]) == [[1, "new_string"], [2, "replace_all"]]


@pytest.mark.parametrize("edits", ["not json", {"old_string": "a", "new_string": "b"}],
                         ids=["text", "object"])
def test_edits_that_is_not_a_list_is_the_sdks_validation_error(mcp, store, edits):
    """``edits`` שאינו רשימה נדחה בוולידציה של ה-SDK, לפני הגוף — כמו ``items`` של הבאץ'.

    ה-``match`` מבדיל בין השניים: גם ה-``TypeError`` של הגוף היה מגיע כ-``ToolError``,
    אבל ההודעה של pydantic על מודל הארגומנטים היא שמוכיחה שהגוף לא רץ.
    """
    _seed(mcp, "a\n")
    before = _snapshot(store)

    with pytest.raises(ToolError, match=r"(?s)multi_edit_fileArguments.*Input should be a valid list"):
        asyncio.run(mcp.call_tool(TOOL, {"file_name": NAME, "edits": edits}))
    assert _snapshot(store) == before


def test_an_empty_list_is_missing_edits(mcp, store):
    _seed(mcp, "a\n")
    before = _snapshot(store)

    assert _call(mcp, TOOL, file_name=NAME, edits=[]) == {"ok": False, "error": "missing_edits"}
    assert _snapshot(store) == before


def test_one_pair_over_the_cap_is_refused_whole_and_the_cap_itself_passes(mcp, store):
    """``MAX_EDIT_PAIRS + 1`` זוגות — ``too_many_edits`` עם ``max``, ושום זוג אינו מוחל.

    **המוטציה שחייבת להפיל אותו — חיתוך שקט:** ``edits = edits[:MAX_EDIT_PAIRS]`` במקום
    הסירוב. אז חמישים הזוגות הראשונים נשמרים והקריאה מדווחת הצלחה.
    """
    from mcp_server.handlers import MAX_EDIT_PAIRS

    tokens = [f"<{i}>" for i in range(MAX_EDIT_PAIRS + 1)]
    _seed(mcp, " ".join(tokens) + "\n")
    before = _snapshot(store)

    over = _call(mcp, TOOL, file_name=NAME, edits=[_pair(t, t.upper() + "!") for t in tokens])
    assert over == {"ok": False, "error": "too_many_edits", "count": MAX_EDIT_PAIRS + 1,
                    "max": MAX_EDIT_PAIRS}
    assert _snapshot(store) == before

    at_cap = _call(mcp, TOOL, file_name=NAME, edits=[_pair(t, t + "!") for t in tokens[:MAX_EDIT_PAIRS]])
    assert at_cap["ok"] is True and at_cap["edits_applied"] == MAX_EDIT_PAIRS, at_cap


class _CountingBackend:
    """backend שסופר קריאות. אם הגוף מגיע אליו, הקלט הפגום עלה קריאה מהמסד."""

    def __init__(self) -> None:
        self.reads = 0
        self.saves = 0

    def get_file(self, *_args, **_kwargs):
        self.reads += 1
        return {"code": "a\n", "content_sha256": _sha("a\n"), "version": 1}

    def save_file(self, *_args, **_kwargs):
        self.saves += 1
        return {"ok": True, "file": {}}


@pytest.mark.parametrize(
    ("arguments", "error"),
    [
        ({"edits": [_pair("a", "A")] * 3 + [{"old_string": "a", "new_string": "b", "x": 1}]}, "invalid_edit"),
        ({"edits": []}, "missing_edits"),
        ({"edits": [_pair("a", "A")] * 51}, "too_many_edits"),
        ({"edits": [_pair("a", "A")], "expected_content_sha256": "not-a-hash"},
         "invalid_expected_content_sha256"),
    ],
    ids=["malformed_pair_3", "empty", "over_the_cap", "malformed_hash"],
)
def test_what_is_wrong_with_the_request_itself_costs_no_read(monkeypatch, arguments, error):
    """כל מה שזול ומקומי נבדק לפני ``_load_editable``: אפס קריאות מהמסד, אפס שמירות.

    **המוטציה שחייבת להפיל אותו — הזזת הוולידציה לאחרי ``_load_editable``.**
    """
    counting = _CountingBackend()
    mcp = _build(monkeypatch, counting)

    res = _call(mcp, TOOL, file_name=NAME, **arguments)

    assert res["ok"] is False and res["error"] == error, res
    if error == "invalid_edit":
        assert res["index"] == 3
    assert counting.reads == 0 and counting.saves == 0


# ---------------------------------------------------------------------------
# 6. כולם או כלום — גם בשמירה, אחרי שכל הזוגות הוחלו
# ---------------------------------------------------------------------------


def test_a_save_that_refuses_after_every_pair_applied_is_returned_as_is(mcp, store, backend, monkeypatch):
    """``save_file`` שמחזיר ``{"ok": false, "error": "db_error"}`` — הסירוב עובר כמו שהוא.

    ומה שנשלח לשמירה הוא הקובץ אחרי **כל** הזוגות — שמירה אחת, לא אחת לכל זוג.
    """
    _seed(mcp, "alpha\nbeta\n")
    before, pushes = _snapshot(store), _push_count(store)
    sent: list[str] = []

    def refusing_save(user_id, **kwargs):
        sent.append(kwargs["code"])
        return {"ok": False, "error": "db_error"}

    monkeypatch.setattr(backend, "save_file", refusing_save)
    res = _call(mcp, TOOL, file_name=NAME, edits=[_pair("alpha", "ALPHA"), _pair("beta", "BETA")])

    assert res == {"ok": False, "error": "db_error"}
    assert sent == ["ALPHA\nBETA\n"]
    assert _snapshot(store) == before
    assert _push_count(store) == pushes


def test_a_result_over_the_size_ceiling_is_refused_and_writes_nothing(mcp, store, monkeypatch):
    """התקרה מוקטנת ב-monkeypatch — לא קובץ אמיתי בגודל התקרה, שעלותו הייתה צמודה לקבוע.

    הסירוב מגיע מהזוג שהתוצאה שלו חוצה את התקרה — ``code_too_large`` עם ``max`` ועם
    ``index`` — בדיוק כמו שקריאות עוקבות ל-``codekeeper_edit_file`` היו נעצרות בה.
    """
    from mcp_server import handlers

    _seed(mcp, "x" * 40 + "\n")
    before, pushes = _snapshot(store), _push_count(store)
    monkeypatch.setattr(handlers, "max_code_size", lambda: 60)

    res = _call(mcp, TOOL, file_name=NAME, edits=[_pair("x" * 40, "y" * 50), _pair("y" * 50, "z" * 70)])

    assert res["ok"] is False and res["error"] == "code_too_large", res
    assert res["index"] == 1 and res["max"] == 60
    assert _snapshot(store) == before
    assert _push_count(store) == pushes


def _peak_bytes(fn) -> int:
    """שיא ההקצאה של ``fn`` — ``tracemalloc`` רואה את כל החוטים, גם את עובד הכתיבה."""
    tracemalloc.start()
    try:
        fn()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def test_edits_that_grow_the_text_are_stopped_before_the_text_is_built(mcp, store, monkeypatch):
    """זוג שמחליף את ``"a"`` ב-``"aa"`` עם ``replace_all`` כופל את הטקסט — בלי בדיקה בין הזוגות,
    שישה-עשר זוגות על אלף תווים הם 65 מיליון תווים בזיכרון לפני שמשהו נמדד.

    כאן הזוג שהתוצאה שלו הייתה חוצה את התקרה (הזוג ה-7: ‏128,000 מול 100,000) נעצר,
    ושיא ההקצאה של כל הקריאה נשאר קטן בסדר גודל ממה שהתוצאה הייתה.

    **המוטציה שחייבת להפיל אותו — הסרת הבדיקה החזויה ב-``_apply_edit``.**
    """
    from mcp_server import handlers

    _seed(mcp, "a" * 1000)
    before = _snapshot(store)
    monkeypatch.setattr(handlers, "max_code_size", lambda: 100_000)
    doubling = [_pair("a", "aa", replace_all=True)] * 16

    answers: list[dict] = []
    peak = _peak_bytes(lambda: answers.append(_call(mcp, TOOL, file_name=NAME, edits=doubling)))

    assert answers[0]["error"] == "code_too_large" and answers[0]["index"] == 6, answers[0]
    assert peak < 5_000_000, f"שיא הקצאה של {peak:,} בתים — הטקסט נבנה לפני שנבדק"
    assert _snapshot(store) == before


def test_a_single_replace_all_is_checked_before_its_result_is_built(mcp, store, monkeypatch):
    """אותה בדיקה ב-``codekeeper_edit_file``: ``replace_all`` עם ``new_string`` ארוך.

    בלי הבדיקה החזויה, 2,000 מופעים כפול 10,000 תווים הם 20 מיליון תווים שנבנים לפני
    ש-``_resave_edited`` דוחה אותם — הקוד בתשובה זהה, וההבדל הוא רק בזיכרון.
    """
    from mcp_server import handlers

    _seed(mcp, "a" * 2000)
    monkeypatch.setattr(handlers, "max_code_size", lambda: 100_000)

    answers: list[dict] = []
    peak = _peak_bytes(lambda: answers.append(_call(
        mcp, "codekeeper_edit_file", file_name=NAME, old_string="a", new_string="b" * 10_000,
        replace_all=True)))

    assert answers[0] == {"ok": False, "error": "code_too_large", "max": 100_000}
    assert peak < 5_000_000, f"שיא הקצאה של {peak:,} בתים — התוצאה נבנתה לפני שנבדקה"


# ---------------------------------------------------------------------------
# 7. השער — ``expected_content_sha256`` בשלושת כלי העריכה
# ---------------------------------------------------------------------------


def _edit_arguments(tool: str) -> dict:
    """עריכה תקינה של ``"alpha\\nbeta\\n"`` בכל אחד מכלי העריכה."""
    if tool == "codekeeper_edit_file":
        return {"old_string": "beta", "new_string": "BETA"}
    if tool == "codekeeper_append_file":
        return {"content": "gamma\n"}
    return {"edits": [_pair("beta", "BETA")]}


@pytest.mark.parametrize("tool", EDIT_TOOLS)
@pytest.mark.parametrize("case", ["lower", "upper"])
def test_the_hash_that_was_read_lets_the_write_through(mcp, store, tool, case):
    """ה-hash של מה שבאוסף — מחושב כאן ב-``hashlib`` — פותח את הכתיבה, בשתי הרישיות."""
    _seed(mcp, "alpha\nbeta\n")
    read = _sha(latest(store.code_snippets, USER, NAME)["code"])
    count = len(_versions(store))

    res = _call(mcp, tool, file_name=NAME, expected_content_sha256=read.upper() if case == "upper" else read,
                **_edit_arguments(tool))

    assert res["ok"] is True, res
    assert len(_versions(store)) == count + 1


@pytest.mark.parametrize("tool", EDIT_TOOLS)
def test_a_hash_from_before_the_last_write_is_conflict_and_writes_nothing(mcp, store, tool):
    """ה-hash של הגרסה הקודמת — ``conflict`` עם ``file.version`` ו-``file.content_sha256``
    הנוכחיים, ובמסד אותו מספר גרסה ואפס אירועי התראה חדשים.

    **המוטציה שחייבת להפיל אותו — ביטול ההשוואה** (``_changed_since_read`` מחזיר ``None``).
    """
    _seed(mcp, "alpha\nbeta\n")
    stale = _sha(latest(store.code_snippets, USER, NAME)["code"])
    assert _call(mcp, "codekeeper_edit_file", file_name=NAME, old_string="alpha", new_string="ALPHA")["ok"]
    before, pushes = _snapshot(store), _push_count(store)
    current = latest(store.code_snippets, USER, NAME)

    res = _call(mcp, tool, file_name=NAME, expected_content_sha256=stale, **_edit_arguments(tool))

    assert res["ok"] is False and res["error"] == "conflict", res
    assert res["file"]["version"] == int(current["version"])
    assert res["file"]["content_sha256"] == _sha(current["code"])
    assert "code" not in res["file"]
    assert "codekeeper_get_file" in res["hint"]
    assert _snapshot(store) == before
    assert _push_count(store) == pushes


@pytest.mark.parametrize("tool", EDIT_TOOLS)
def test_a_write_in_place_that_added_no_version_is_caught_too(mcp, store, tool):
    """כתיבה במקום, בלי גרסה חדשה — כמו ``check_file_sync`` ב-``database/bookmarks_manager.py``.

    זו הסיבה שהשער הוא hash ולא ``version``: המספר לא זז, התוכן כן.
    """
    _seed(mcp, "alpha\nbeta\n")
    doc = latest(store.code_snippets, USER, NAME)
    read = _sha(doc["code"])
    doc["code"] = "alpha\nbeta\nsynced\n"  # אותו מסמך, אותה גרסה

    res = _call(mcp, tool, file_name=NAME, expected_content_sha256=read, **_edit_arguments(tool))

    assert res["ok"] is False and res["error"] == "conflict", res
    assert res["file"]["version"] == int(doc["version"])
    assert res["file"]["content_sha256"] == _sha("alpha\nbeta\nsynced\n")


@pytest.mark.parametrize("tool", EDIT_TOOLS)
def test_without_the_parameter_the_write_goes_through_as_before(mcp, store, tool):
    """הפרמטר תוספתי: בלעדיו אין בדיקה, גם אחרי שהקובץ השתנה."""
    _seed(mcp, "alpha\nbeta\n")
    assert _call(mcp, "codekeeper_edit_file", file_name=NAME, old_string="alpha", new_string="ALPHA")["ok"]

    assert _call(mcp, tool, file_name=NAME, **_edit_arguments(tool))["ok"] is True


@pytest.mark.parametrize("tool", EDIT_TOOLS)
@pytest.mark.parametrize(
    "value",
    ["", "abc", "g" * 64, "0" * 63, "0" * 65, " " + "0" * 63, "٠" * 64],
    ids=["empty", "short", "not_hex", "63", "65", "space", "arabic_indic_digits"],
)
def test_a_value_that_is_not_a_sha256_hex_is_its_own_refusal(mcp, store, tool, value):
    """ערך שאינו 64 ספרות הקס — ``invalid_expected_content_sha256``, ולעולם לא ``conflict``.

    שגיאת כתיב שנענית ``conflict`` הייתה שולחת את הסוכן לקרוא מחדש ולשלוח שוב את אותו
    ערך. ספרות שאינן ASCII נדחות: הטווחים ב-``_SHA256_HEX`` מפורשים, לא ``\\d``.
    """
    _seed(mcp, "alpha\nbeta\n")
    before = _snapshot(store)

    res = _call(mcp, tool, file_name=NAME, expected_content_sha256=value, **_edit_arguments(tool))

    assert res["ok"] is False and res["error"] == "invalid_expected_content_sha256", res
    assert _snapshot(store) == before


# ---------------------------------------------------------------------------
# 8. התיעוד נוקב בתקרה שהקוד אוכף
# ---------------------------------------------------------------------------


def test_the_documented_cap_is_the_code_cap():
    """טבלת הקבועים ב-``docs/mcp-server.rst`` נוקבת ב-``MAX_EDIT_PAIRS``.

    קובץ RST אינו יכול לגזור דבר (``prose-restates-code-fact``), ולכן הערך המצופה
    מחושב כאן מהקבוע, באותה צורה שהטבלה כותבת — כמו הטסט המקביל על
    ``MAX_BATCH_ITEMS`` ב-``tests/test_mcp_read_batch.py``. תיאור הפרמטר ``edits``
    אינו צריך טסט כזה: הוא נבנה מהקבוע עצמו (``_build_multi_edit_docs``).

    מוטציה שמפילה: לשנות את ``MAX_EDIT_PAIRS`` בלי הטבלה, או להפך.
    """
    from pathlib import Path

    from mcp_server.handlers import MAX_EDIT_PAIRS

    page = (Path(__file__).resolve().parent.parent / "docs" / "mcp-server.rst").read_text(encoding="utf-8")
    lines = page.splitlines()
    row = lines.index("   * - ``MAX_EDIT_PAIRS``")
    assert lines[row + 1].strip() == f"- {MAX_EDIT_PAIRS:,}"
