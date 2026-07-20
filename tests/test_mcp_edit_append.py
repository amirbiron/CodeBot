"""Unit tests for the server-side edit/append handlers (find-replace + append).

These cover the pure `_apply_edit` semantics and the full handler flows
(fetch -> apply -> size gate -> metadata-preserving save) with a fake backend.
"""

from mcp_server import handlers
from mcp_server.handlers import _apply_edit


class _EditBackend:
    """Fake backend holding one file; records the save kwargs for assertions."""

    def __init__(self, doc=None):
        self.doc = doc
        self.saved = None

    def get_file(self, user_id, *, file_name, file_id=None, version=None):
        return self.doc

    def save_file(self, user_id, *, file_name, code, programming_language, description, tags=None):
        self.saved = {
            "file_name": file_name,
            "code": code,
            "programming_language": programming_language,
            "description": description,
            "tags": tags,
        }
        return {"ok": True, "created": False, "file": {"file_name": file_name, "version": 4}}


def _doc(code="alpha\nbeta\ngamma\n", lang="markdown", desc="notes", tags=("t1",)):
    return {
        "file_name": "notes.md",
        "code": code,
        "programming_language": lang,
        "description": desc,
        "tags": list(tags),
    }


# -- _apply_edit (pure semantics) -----------------------------------------


def test_apply_edit_single_replacement():
    new, n, err = _apply_edit("a b c", "b", "B", False)
    assert (new, n, err) == ("a B c", 1, None)


def test_apply_edit_no_match():
    new, n, err = _apply_edit("a b c", "zzz", "B", False)
    assert new is None and err == "no_match"


def test_apply_edit_ambiguous_without_replace_all():
    new, n, err = _apply_edit("x y x", "x", "z", False)
    assert new is None and err == "ambiguous_match" and n == 2


def test_apply_edit_replace_all():
    new, n, err = _apply_edit("x y x", "x", "z", True)
    assert (new, n, err) == ("z y z", 2, None)


def test_apply_edit_rejects_empty_old():
    assert _apply_edit("abc", "", "z", False)[2] == "empty_old_string"


def test_apply_edit_rejects_identical_strings():
    assert _apply_edit("abc", "b", "b", False)[2] == "old_and_new_identical"


# -- edit_file --------------------------------------------------------------


def test_edit_file_replaces_and_preserves_metadata():
    be = _EditBackend(_doc())
    out = handlers.edit_file(be, 7, file_name="notes.md", old_string="beta", new_string="BETA")
    assert out["ok"] is True and out["replacements"] == 1
    assert out["file"]["version"] == 4
    assert be.saved["code"] == "alpha\nBETA\ngamma\n"
    # Metadata is carried over from the fetched version, never reset.
    assert be.saved["programming_language"] == "markdown"
    assert be.saved["description"] == "notes"
    assert be.saved["tags"] == ["t1"]


def test_edit_file_ambiguous_reports_occurrences_and_saves_nothing():
    be = _EditBackend(_doc(code="x\nx\n"))
    out = handlers.edit_file(be, 7, file_name="notes.md", old_string="x", new_string="y")
    assert out["ok"] is False and out["error"] == "ambiguous_match"
    assert out["occurrences"] == 2 and "hint" in out
    assert be.saved is None


def test_edit_file_replace_all_counts_replacements():
    be = _EditBackend(_doc(code="x\nx\n"))
    out = handlers.edit_file(
        be, 7, file_name="notes.md", old_string="x", new_string="y", replace_all=True
    )
    assert out["ok"] is True and out["replacements"] == 2
    assert be.saved["code"] == "y\ny\n"


def test_edit_file_not_found():
    be = _EditBackend(None)
    out = handlers.edit_file(be, 7, file_name="ghost.md", old_string="a", new_string="b")
    assert out == {"ok": False, "error": "not_found"}
    assert be.saved is None


def test_edit_file_missing_name_short_circuits():
    be = _EditBackend(_doc())
    out = handlers.edit_file(be, 7, file_name="  ", old_string="a", new_string="b")
    assert out == {"ok": False, "error": "missing_file_name"}
    assert be.saved is None


def test_edit_file_size_gate_blocks_oversize_result():
    be = _EditBackend(_doc(code="SMALL"))
    out = handlers.edit_file(
        be, 7, file_name="notes.md", old_string="SMALL", new_string="y" * 100_001
    )
    assert out["ok"] is False and out["error"] == "code_too_large"
    assert be.saved is None


# -- append_file ------------------------------------------------------------


def test_append_inserts_newline_separator_when_missing():
    be = _EditBackend(_doc(code="line one"))
    out = handlers.append_file(be, 7, file_name="notes.md", content="line two")
    assert out["ok"] is True and out["appended_chars"] == len("line two")
    assert be.saved["code"] == "line one\nline two"


def test_append_no_double_newline_when_body_ends_with_one():
    be = _EditBackend(_doc(code="line one\n"))
    handlers.append_file(be, 7, file_name="notes.md", content="line two")
    assert be.saved["code"] == "line one\nline two"


def test_append_preserves_metadata():
    be = _EditBackend(_doc())
    handlers.append_file(be, 7, file_name="notes.md", content="tail")
    assert be.saved["programming_language"] == "markdown"
    assert be.saved["tags"] == ["t1"]


def test_append_not_found_and_empty_content():
    assert handlers.append_file(_EditBackend(None), 7, file_name="g.md", content="x") == {
        "ok": False,
        "error": "not_found",
    }
    be = _EditBackend(_doc())
    assert handlers.append_file(be, 7, file_name="notes.md", content="")["error"] == (
        "empty_content"
    )
    assert be.saved is None


def test_append_size_gate():
    be = _EditBackend(_doc(code="x"))
    out = handlers.append_file(be, 7, file_name="notes.md", content="y" * 100_001)
    assert out["ok"] is False and out["error"] == "code_too_large"
    assert be.saved is None
