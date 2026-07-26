"""טסטים ל-handler של docs_get_section — עם fake backend שקורא RST אמיתי מ-docs/."""

from pathlib import Path

from mcp_server import docs_handlers

_ROOT = Path(__file__).resolve().parents[1]


class _FsBackend:
    """מחקה RepoBackend.get_file: קורא קובץ אמיתי מהריפו (filesystem, לא mirror)."""

    def __init__(self, ref="refs/heads/main"):
        self._ref = ref
        self.calls = []

    def get_file(self, *, repo, path, ref=None):
        self.calls.append((repo, path, ref))
        f = _ROOT / path
        if not f.exists():
            return {"ok": False, "error": "not_found"}
        text = f.read_text(encoding="utf-8")
        return {
            "ok": True, "status": "ok",
            "file": {"path": path, "ref": ref or self._ref,
                     "resolved_commit": "deadbeef", "lines": text.count("\n") + 1},
            "content": text,
        }


class _TextBackend:
    """מחזיר טקסט RST נתון (למקרי קצה סינתטיים)."""

    def __init__(self, text):
        self._text = text

    def get_file(self, *, repo, path, ref=None):
        return {"ok": True, "status": "ok",
                "file": {"path": path, "ref": "HEAD", "resolved_commit": "c0ffee"},
                "content": self._text}


def test_no_section_returns_toc_without_content():
    out = docs_handlers.docs_get_section(_FsBackend(), path="environment-variables")
    assert out["ok"] and out["mode"] == "toc"
    assert "טבלה מרכזית" in [t["title"] for t in out["toc"]]
    assert "content" not in out


def test_default_repo_is_codebot():
    be = _FsBackend()
    docs_handlers.docs_get_section(be, path="environment-variables")
    assert be.calls[0][0] == "CodeBot"
    assert be.calls[0][1] == "docs/environment-variables.rst"


def test_slug_and_full_path_equivalent():
    a = docs_handlers.docs_get_section(_FsBackend(), path="environment-variables", section="טבלה מרכזית")
    b = docs_handlers.docs_get_section(_FsBackend(), path="docs/environment-variables.rst", section="טבלה מרכזית")
    assert a["ok"] and b["ok"]
    assert a["content"] == b["content"]
    assert a["path"] == b["path"] == "docs/environment-variables.rst"


def test_big_table_truncates_with_valid_offset():
    """הטבלה המרכזית גדולה — נחתכת עם truncated + next_offset תקין, וההמשך שונה."""
    be = _FsBackend()
    out = docs_handlers.docs_get_section(be, path="environment-variables",
                                         section="טבלה מרכזית", max_chars=4000)
    assert out["ok"] and out["mode"] == "section"
    assert out["truncated"] is True
    assert out["next_offset"] == len(out["content"]) > 0
    assert out["remaining_chars"] > 0
    assert ".. list-table:: Environment Variables" in out["content"]
    out2 = docs_handlers.docs_get_section(be, path="environment-variables",
                                          section="טבלה מרכזית", max_chars=4000,
                                          offset=out["next_offset"])
    assert out2["content"] and out2["content"] != out["content"]


def test_section_not_found_returns_toc_and_suggestions():
    out = docs_handlers.docs_get_section(_FsBackend(), path="environment-variables",
                                         section="סקשן שלא קיים בכלל 123")
    assert out["ok"] is False and out["error"] == "section_not_found"
    assert out["toc"]  # TOC מלא, לא רק שגיאה
    assert "suggestions" in out


def test_ambiguous_section_returns_candidates_with_breadcrumb():
    rst = "Doc\n===\n\nAlpha\n-----\n\nמטרה\n~~~~\n\nx\n\nBeta\n----\n\nמטרה\n~~~~\n\ny\n"
    out = docs_handlers.docs_get_section(_TextBackend(rst), path="x", section="מטרה")
    assert out["ok"] is False and out["error"] == "ambiguous_section"
    assert len(out["candidates"]) == 2
    crumbs = [c["breadcrumb"] for c in out["candidates"]]
    assert crumbs[0] != crumbs[1]  # Alpha vs Beta


def test_include_subsections_false_smaller_than_true():
    full = docs_handlers.docs_get_section(_FsBackend(), path="environment-variables",
                                          section="משתני סביבה - רפרנס", include_subsections=True)
    partial = docs_handlers.docs_get_section(_FsBackend(), path="environment-variables",
                                             section="משתני סביבה - רפרנס", include_subsections=False)
    assert full["ok"] and partial["ok"]
    assert len(partial["content"]) < len(full["content"])


def test_missing_file_propagates_not_found():
    out = docs_handlers.docs_get_section(_FsBackend(), path="no-such-doc-xyz")
    assert out["ok"] is False and out["error"] == "not_found"
    assert out["repo"] == "CodeBot"
