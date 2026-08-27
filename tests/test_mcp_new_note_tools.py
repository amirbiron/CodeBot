"""טסטים לארבע ההשלמות ב-MCP: שיוך לאוסף, מפת פתקי ריפו, חיפוש תוכן, היסטוריה.

הכול הרמטי — fakes ידניים, בלי Mongo ובלי Flask, בתבנית
``test_mcp_notes_handlers.py``. **יעד הטסטים הוא שכבת ה-handlers**, ולכן
כל מה שנבדק כאן הוא הלוגיקה הטהורה: מה מגיע ל-backend, מה נחסם לפניו,
ואיזו שגיאה חוזרת. השאילתות עצמן נבדקות מול מונגו אמיתי בנפרד.
"""

import pytest

from mcp_server import handlers
from mcp_server.handlers import MAX_NOTE_CONTENT
from sticky_notes_target import (
    MAX_NOTE_TITLE,
    note_search_filter,
    repo_note_paths_pipeline,
    title_search_filter,
)

_OID = "a" * 24


class _Recorder:
    """Fake שמקליט kwargs ומחזיר תשובה שניתן להזריק."""

    def __init__(self, **returns):
        self.calls = []
        self.returns = returns

    def _record(self, name, user_id, kwargs):
        self.calls.append((name, user_id, dict(kwargs)))
        return self.returns.get(name, {"ok": True})

    def add_to_collection(self, user_id, *, collection_id, file_name, folder=None, note=None):
        return self._record("add_to_collection", user_id, {
            "collection_id": collection_id, "file_name": file_name,
            "folder": folder, "note": note,
        })

    def list_repo_note_paths(self, user_id, *, repo_name):
        return self._record("list_repo_note_paths", user_id, {"repo_name": repo_name})

    def search_notes(self, user_id, *, query, limit, search_content=False):
        return self._record("search_notes", user_id, {
            "query": query, "limit": limit, "search_content": search_content,
        })

    def get_note(self, user_id, *, note_id):
        return self._record("get_note", user_id, {"note_id": note_id})

    def update_note(self, user_id, *, note_id, fields):
        return self._record("update_note", user_id, {"note_id": note_id, "fields": dict(fields)})

    def list_note_versions(self, user_id, *, note_id):
        return self._record("list_note_versions", user_id, {"note_id": note_id})

    def get_note_version(self, user_id, *, note_id, version):
        return self._record("get_note_version", user_id, {"note_id": note_id, "version": version})

    @property
    def last(self):
        return self.calls[-1][2]


# ── 1. שיוך לאוסף ──────────────────────────────────────────────────────


@pytest.mark.parametrize("bad", ["", "   ", "not-an-oid", "a" * 23, "a" * 25, "ZZZ" + "a" * 21])
def test_an_invalid_collection_id_never_reaches_the_backend(bad):
    b = _Recorder()
    assert handlers.add_to_collection(b, 7, collection_id=bad, file_name="a.py") == {
        "ok": False, "error": "invalid_collection_id",
    }
    assert b.calls == []


def test_a_blank_file_name_never_reaches_the_backend():
    b = _Recorder()
    assert handlers.add_to_collection(b, 7, collection_id=_OID, file_name="  ")["error"] == (
        "missing_file_name"
    )
    assert b.calls == []


def test_the_file_name_is_trimmed_and_options_pass_through():
    b = _Recorder()
    handlers.add_to_collection(
        b, 7, collection_id=_OID, file_name="  a.py  ", folder="docs", note="hi"
    )
    assert b.last == {"collection_id": _OID, "file_name": "a.py", "folder": "docs", "note": "hi"}


# ── 2. מפת נתיבי פתקי הריפו ────────────────────────────────────────────


@pytest.mark.parametrize("bad", ["", "   ", "amirbiron/CodeBot"])
def test_an_invalid_repo_name_never_reaches_the_backend(bad):
    """אותה ולידציה כמו ``list_repo_notes`` — שם עם ``/`` לא יימצא לעולם."""
    b = _Recorder()
    assert handlers.list_repo_note_paths(b, 7, repo_name=bad) == {
        "ok": False, "error": "invalid_repo_name",
    }
    assert b.calls == []


def test_the_paths_pipeline_is_scoped_and_groups_without_touching_content():
    """הצינור חייב להישאר מפה: קיבוץ וספירה, בלי לגעת בגוף הפתק."""
    stages = repo_note_paths_pipeline("7", "CodeBot")
    assert stages[0]["$match"] == {"user_id": 7, "repo_name": "CodeBot"}
    assert stages[1]["$group"] == {"_id": "$repo_path", "count": {"$sum": 1}}
    assert "content" not in repr(stages)


def test_the_match_stage_is_the_prefix_of_the_existing_index():
    """‏``user_repo_idx`` הוא ``(user_id, repo_name, repo_path)`` — אפס אינדקסים חדשים."""
    assert list(repo_note_paths_pipeline(7, "r")[0]["$match"]) == ["user_id", "repo_name"]


# ── 3. חיפוש בתוכן ─────────────────────────────────────────────────────


def test_by_default_the_filter_asks_about_the_title_only():
    flt = note_search_filter(7, "x")
    assert "$or" not in flt and "content" not in flt
    assert flt == title_search_filter(7, "x")  # המעטפת אינה מוסיפה התנהגות


def test_with_the_flag_the_filter_also_asks_about_the_content():
    flt = note_search_filter(7, "x", search_content=True)
    clauses = flt["$or"]
    assert flt["user_id"] == 7
    assert {"title": {"$exists": True, "$regex": "x", "$options": "i"}} in clauses
    assert {"content": {"$regex": "x", "$options": "i"}} in clauses


def test_the_content_clause_does_not_require_a_title_to_exist():
    """הדגל קיים בשביל פתק בלי שם — תנאי ``$exists`` היה מוציא אותו החוצה."""
    content_clause = next(
        c for c in note_search_filter(7, "x", search_content=True)["$or"] if "content" in c
    )
    assert "$exists" not in content_clause["content"]


@pytest.mark.parametrize("needle", ["config.py", "a(", "a|b", "[x]", "a\\b", "x.*y"])
def test_both_predicates_escape_regex_metacharacters(needle):
    """‏``re.escape`` הוא חלק מהחוזה — ובשני הפרדיקטים, לא רק בראשון."""
    import re

    flt = note_search_filter(7, needle, search_content=True)
    for clause in flt["$or"]:
        field = "title" if "title" in clause else "content"
        assert clause[field]["$regex"] == re.escape(needle)


def test_the_needle_keeps_its_whitespace_when_searching_content():
    """**אי-סימטריה שהייתה שקטה.** שם עובר כיווץ רווחים בכתיבה; תוכן לא.

    קנוניזציית-שם על מחרוזת תוכן הופכת ``"a  b"`` ל-``"a b"`` ומאחדת
    שאילתה רב-שורתית לשורה — שאילתה שלעולם לא תתפוס את מה שנשמר,
    ומחזירה אפס בלי שום שגיאה.
    """
    b = _Recorder()
    handlers.search_notes(b, 7, query="a  b", search_content=True)
    assert b.last["query"] == "a  b"
    handlers.search_notes(b, 7, query="שורה\nשנייה", search_content=True)
    assert b.last["query"] == "שורה\nשנייה"


def test_the_title_path_still_canonicalizes():
    b = _Recorder()
    handlers.search_notes(b, 7, query="  5   PR \n ")
    assert b.last["query"] == "5 PR"
    assert b.last["search_content"] is False


def test_the_length_cap_follows_the_field_being_searched():
    """תקרת השם נגזרת משם אפשרי; היא אינה חלה על גוף הפתק."""
    b = _Recorder()
    long_needle = "x" * (MAX_NOTE_TITLE + 1)
    assert handlers.search_notes(b, 7, query=long_needle)["error"] == "query_too_long"
    assert b.calls == []
    assert handlers.search_notes(b, 7, query=long_needle, search_content=True)["ok"] is True
    assert handlers.search_notes(
        b, 7, query="x" * (MAX_NOTE_CONTENT + 1), search_content=True
    )["error"] == "query_too_long"


# ── 4. היסטוריה ו-str_replace ──────────────────────────────────────────


def _with_note(body):
    return _Recorder(
        get_note={"ok": True, "note": {"id": _OID, "content": body}},
        update_note={"ok": True, "note": {"id": _OID, "content": "after"}},
    )


def test_a_replace_sends_only_the_new_body_and_reports_the_count():
    b = _with_note("alpha beta alpha")
    res = handlers.note_str_replace(
        b, 7, note_id=_OID, old_string="beta", new_string="gamma"
    )
    assert res["ok"] is True and res["replacements"] == 1
    assert b.last["fields"] == {"content": "alpha gamma alpha"}


def test_an_ambiguous_match_is_refused_with_the_count_and_a_hint():
    """אותם נוסחי שגיאה כמו ``edit_file`` — סוכן שלמד אחד מכיר את השני."""
    b = _with_note("x x")
    res = handlers.note_str_replace(b, 7, note_id=_OID, old_string="x", new_string="y")
    assert res == {
        "ok": False, "error": "ambiguous_match", "occurrences": 2,
        "hint": "pass a longer unique old_string, or set replace_all=true",
    }
    assert [c[0] for c in b.calls] == ["get_note"]  # לא נכתב דבר


def test_replace_all_lifts_the_refusal():
    b = _with_note("x x")
    res = handlers.note_str_replace(
        b, 7, note_id=_OID, old_string="x", new_string="y", replace_all=True
    )
    assert res["replacements"] == 2
    assert b.last["fields"] == {"content": "y y"}


@pytest.mark.parametrize(
    "old,new,err",
    [("", "y", "empty_old_string"), ("same", "same", "old_and_new_identical"), ("zz", "y", "no_match")],
)
def test_the_edit_errors_match_edit_file(old, new, err):
    b = _with_note("same body")
    assert handlers.note_str_replace(b, 7, note_id=_OID, old_string=old, new_string=new)[
        "error"
    ] == err


def test_an_edit_that_empties_the_note_is_refused():
    """פתק ריק אינו עדכון — זו מחיקה בתחפושת."""
    b = _with_note("only")
    assert handlers.note_str_replace(b, 7, note_id=_OID, old_string="only", new_string="")[
        "error"
    ] == "empty_content"
    assert [c[0] for c in b.calls] == ["get_note"]


def test_crlf_in_the_needle_still_matches_a_body_stored_with_newlines():
    """הקלט מנורמל כמו שהתוכן נורמל בכתיבה."""
    b = _with_note("a\nb")
    assert handlers.note_str_replace(
        b, 7, note_id=_OID, old_string="a\r\nb", new_string="c"
    )["ok"] is True


def test_a_missing_note_never_reaches_the_write():
    b = _Recorder(get_note={"ok": False, "error": "not_found"})
    assert handlers.note_str_replace(b, 7, note_id=_OID, old_string="a", new_string="b")[
        "error"
    ] == "not_found"
    assert [c[0] for c in b.calls] == ["get_note"]


@pytest.mark.parametrize("bad", ["", "nope", "a" * 23])
def test_every_note_id_gate_rejects_before_the_backend(bad):
    b = _Recorder()
    for res in (
        handlers.note_str_replace(b, 7, note_id=bad, old_string="a", new_string="b"),
        handlers.list_note_versions(b, 7, note_id=bad),
        handlers.get_note_version(b, 7, note_id=bad, version=1),
    ):
        assert res == {"ok": False, "error": "invalid_note_id"}
    assert b.calls == []


@pytest.mark.parametrize("bad", [0, -1, "x", None])
def test_an_invalid_version_number_never_reaches_the_backend(bad):
    b = _Recorder()
    assert handlers.get_note_version(b, 7, note_id=_OID, version=bad)["error"] == "invalid_version"
    assert b.calls == []


def test_the_version_number_is_coerced_to_int():
    b = _Recorder()
    handlers.get_note_version(b, 7, note_id=_OID, version="3")
    assert b.last["version"] == 3
