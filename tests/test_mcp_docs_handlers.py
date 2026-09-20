"""טסטים ל-handler של docs_get_section — עם fake backend שקורא RST אמיתי מ-docs/."""

import inspect
from pathlib import Path

import pytest

from mcp_server import docs_handlers
from services import rst_parser

_ROOT = Path(__file__).resolve().parents[1]


class _FsBackend:
    """מחקה RepoBackend.get_file: קורא קובץ אמיתי מהריפו (filesystem, לא mirror)."""

    def __init__(self, ref="refs/heads/main"):
        self._ref = ref
        self.calls = []

    def get_file(self, *, repo, path, ref=None, lines=None):
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

    def get_file(self, *, repo, path, ref=None, lines=None):
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


def _identified_rst(*headings):
    """עמוד RST סינתטי שכל כותרת בו היא כותרת רמה 2 עם גוף בן שורה."""
    body = "Doc\n===\n\n"
    for h in headings:
        body += f"{h}\n{'-' * max(len(h), 4)}\n\nגוף\n\n"
    return body


def test_an_identifier_query_reaches_the_section_through_the_tool():
    """הזרימה המרכזית, דרך הכלי ולא דרך הפונקציה.

    עד היום ``section="K11"`` החזיר ``section_not_found`` עם הצעות ריקות,
    וזה בדיוק מה שהסוכנים מקלידים. כאן נבדק שהתשובה היא הסעיף עצמו, עם
    הכותרת המלאה — כדי שהקורא יראה מה הוא קיבל.
    """
    rst = _identified_rst("K11. כשל שמדווח בערך החזרה נבלע", "K12. דגל שמרחיב הרשאה")
    out = docs_handlers.docs_get_section(_TextBackend(rst), path="x", section="K11")

    assert out["ok"] and out["mode"] == "section"
    assert out["section"] == "K11. כשל שמדווח בערך החזרה נבלע"
    assert "גוף" in out["content"]


def test_an_identifier_that_repeats_is_ambiguous_and_not_a_guess():
    rst = _identified_rst("P3 — ראשון", "אחר", "P3 — שני")
    out = docs_handlers.docs_get_section(_TextBackend(rst), path="x", section="P3")

    assert out["ok"] is False and out["error"] == "ambiguous_section"
    assert [c["title"] for c in out["candidates"]] == ["P3 — ראשון", "P3 — שני"]


def test_the_suggestions_field_is_a_list_of_strings_and_not_the_namedtuple():
    """‏``suggest`` מחזיר ``NamedTuple``, והתשובה חייבת לשאת את ``titles`` בלבד.

    מי שישכח את ``.titles`` ישלח לקורא ``[["K11"], false]`` — JSON תקין
    לגמרי, בלי שום שגיאה, ועם דגל שמתחזה להצעה.
    """
    rst = _identified_rst("K11. כשל", "K12. דגל")
    out = docs_handlers.docs_get_section(_TextBackend(rst), path="x", section="K99")

    assert out["error"] == "section_not_found"
    assert out["suggestions"] == ["K11", "K12"]
    assert all(isinstance(s, str) for s in out["suggestions"])


def test_suggestions_truncated_appears_only_when_the_list_was_cut():
    """הדגל קיים רק כשהוא נכון — וזה מה ששומר על אפס-דיף בכל שאר התשובות."""
    few = docs_handlers.docs_get_section(
        _TextBackend(_identified_rst("K1. א", "K2. ב")), path="x", section="K99")
    assert "suggestions_truncated" not in few

    many = docs_handlers.docs_get_section(
        _TextBackend(_identified_rst(*[f"K{i}. טקסט" for i in range(1, 52)])),
        path="x", section="Z9")
    assert many["suggestions_truncated"] is True
    assert len(many["suggestions"]) == 50


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


# ---- הקשחת אבטחה (סבב review) ----

def test_explicit_repo_not_in_allowlist_rejected(monkeypatch):
    monkeypatch.delenv("MCP_DOCS_REPO", raising=False)  # allowlist = [CodeBot]
    be = _FsBackend()
    out = docs_handlers.docs_get_section(be, path="environment-variables", repo="SomeOtherRepo")
    assert out["ok"] is False and out["error"] == "repo_not_allowed"
    assert be.calls == []  # ה-backend לא נקרא כלל (IDOR נחסם)


def test_explicit_repo_in_allowlist_allowed(monkeypatch):
    monkeypatch.setenv("MCP_DOCS_REPO", "CodeBot, other-docs")
    out = docs_handlers.docs_get_section(_FsBackend(), path="environment-variables", repo="CodeBot")
    assert out["ok"] and out["repo"] == "CodeBot"


@pytest.mark.parametrize("bad_path", [
    "webapp/config",       # מחוץ ל-docs/ עם slash
    "../../etc/passwd",    # traversal
    "docs/../secrets",     # traversal שרזולב החוצה מ-docs/
    "/etc/hosts",          # נתיב מוחלט
])
def test_path_outside_docs_rejected(bad_path):
    be = _FsBackend()
    out = docs_handlers.docs_get_section(be, path=bad_path)
    assert out["ok"] is False and out["error"] == "missing_path"
    assert be.calls == []  # נחסם ב-handler לפני ה-backend


# ---- מסלול הצרכן לתיקוני ההיררכיה ב-rst_parser ----
#
# ``TESTING-PATTERNS.md`` T1: הבדיקה עוברת דרך אותו ממשק שהצרכן נוגע בו.
# הצרכן של ``rst_parser`` בייצור הוא ``docs_get_section``, ולכן שלושת התיקונים
# שמוסיפים סעיף ושהאחד שמסיר אותו נבדקים כאן דרך ה-handler ולא דרך הפארסר.
# כל הצורות שלמטה נמדדו בהרצה של docutils 0.23 עצמו.


class TestSectionsDocutilsAcceptsAreFindable:
    """סעיף שקיים בקובץ וש-docutils מקבל — חייב להיות נגיש דרך הכלי.

    לפני התיקון שלושת המקרים האלה החזירו ``section_not_found`` על סעיף
    שכתוב בקובץ, כלומר השמטה שקטה: הקורא רואה "לא נמצא" ולא "לא נתמך".
    """

    def test_a_section_whose_underline_is_short_but_at_least_four(self):
        rst = "Doc\n===\n\nכותרת ארוכה מאוד\n----\n\nגוף הסעיף\n"
        out = docs_handlers.docs_get_section(_TextBackend(rst), path="x",
                                             section="כותרת ארוכה מאוד")
        assert out["ok"], out.get("error")
        assert "גוף הסעיף" in out["content"]

    def test_a_hebrew_title_with_nikud_measured_by_display_width(self):
        """הכותרת היא 14 תווים ו-9 עמודות; הקו הוא 10.

        ``column_width`` מחסר תווים משולבים, ולכן הקו ארוך מהרוחב וקצר
        מ-``len``. ההשוואה הישנה, שהייתה על ``len``, הסתירה את הסעיף.
        """
        title = "שָׁלוֹם עוֹלָם"
        assert len(title) == 14, "ה-fixture נשען על הניקוד — אין לנרמל אותו"
        rst = f"Doc\n===\n\n{title}\n{'-' * 10}\n\nגוף הסעיף\n"
        out = docs_handlers.docs_get_section(_TextBackend(rst), path="x", section=title)
        assert out["ok"], out.get("error")
        assert "גוף הסעיף" in out["content"]

    def test_a_section_adorned_with_commas(self):
        """',' ו-';' הם תווי adornment חוקיים — 32 במקור, 30 ברשימה הישנה."""
        rst = "Doc\n===\n\nסעיף בפסיקים\n,,,,,,,,,,,,\n\nגוף הסעיף\n"
        out = docs_handlers.docs_get_section(_TextBackend(rst), path="x",
                                             section="סעיף בפסיקים")
        assert out["ok"], out.get("error")
        assert "גוף הסעיף" in out["content"]


class TestASectionDocutilsDropsIsNotInTheToc:
    """שומר הדילוג של ``check_subsection``, ומה שקורה לתוכן שמתחתיו."""

    _RST = "A\n===\n\nגוף א\n\nB\n---\n\nגוף ב\n\nC\n===\n\nגוף ג\n\nD\n~~~\n\nגוף ד\n"

    def test_the_dropped_heading_is_absent_from_the_toc(self):
        """'skip from level 1 to 3' — docutils אינו יוצר את הסקשן."""
        out = docs_handlers.docs_get_section(_TextBackend(self._RST), path="x")
        assert out["ok"] and out["mode"] == "toc"
        assert [t["title"] for t in out["toc"]] == ["A", "B", "C"]

    def test_asking_for_the_dropped_heading_says_not_found(self):
        out = docs_handlers.docs_get_section(_TextBackend(self._RST), path="x", section="D")
        assert out["ok"] is False and out["error"] == "section_not_found"

    def test_no_content_is_lost_it_folds_into_the_section_above(self):
        """העיקר: הכותרת יורדת מה-TOC, אבל הטקסט שמתחתיה עדיין נגיש.

        זה מה שמפריד "סעיף שאינו במפה" מ"תוכן שנעלם" — הטווח של C נמשך
        עד סוף הקובץ ולכן בולע גם את 'D' וגם את הגוף שלו.
        """
        out = docs_handlers.docs_get_section(_TextBackend(self._RST), path="x", section="C")
        assert out["ok"], out.get("error")
        assert "גוף ג" in out["content"]
        assert "גוף ד" in out["content"]


def test_an_overlined_heading_is_one_level_deeper_than_the_same_character_underlined():
    """'=' ו-('=','=') הם שני סגנונות, ולכן שתי רמות. נמדד ב-docutils."""
    rst = "כותרת א\n========\n\n========\nכותרת ב\n========\n\nגוף\n"
    out = docs_handlers.docs_get_section(_TextBackend(rst), path="x")
    assert out["ok"]
    assert [(t["title"], t["level"]) for t in out["toc"]] == [
        ("כותרת א", 1), ("כותרת ב", 2)]
    assert out["toc"][1]["breadcrumb"] == ["כותרת א", "כותרת ב"]


def test_the_docs_reader_parses_without_any_ceiling(monkeypatch):
    """הצרכן בייצור אינו מוגבל בתקרה, ונבדק על **התקרה האפקטיבית**.

    ``parse_document`` קיבל ``max_sections`` בשביל סורק האאוטליין, ושני
    דברים חייבים להישאר נכונים כדי שהכלי הזה לא ייחסם: שהוא **אינו
    מעביר** תקרה, ושברירת המחדל **אינה** תקרה. שניהם נבדקים כאן, כי כל
    אחד מהם לבדו מספיק כדי לחסום קובץ תיעוד גדול.

    **וזה נבדק כך במקום להציף את התקרה, בכוונה.** הגרסה הראשונה של
    הבדיקה בנתה ``MAX_SYMBOLS + 1`` סקשנים אמיתיים — 819KB, 0.40 שניות
    ו-71MB בכל ריצה — כלומר **המחיר שלה היה צמוד לקבוע שהיא מגנה עליו**.
    נמדד: בהעלאת התקרה פי עשר, מה שההערה ליד הקבוע מזמינה במפורש, אותה
    בדיקה הייתה בונה קלט של 8.9MB ו-500,001 סקשנים — 6.64 שניות ו-482MB
    בכל ריצת CI. בדיקה שמתדרדרת בדיוק כשהמערכת גדלה אינה הצורה הנכונה.

    **וליטרל קבוע לא היה מחליף אותה**, כי הוא מפסיק להוכיח משהו ברגע
    שהתקרה עולה מעליו. שתי הבדיקות כאן אינן תלויות בגודל התקרה בכלל.
    """
    passed: dict[str, object] = {}
    real = rst_parser.parse_document

    def spy(text, **kwargs):
        passed.update(kwargs)
        return real(text, **kwargs)

    monkeypatch.setattr(docs_handlers.rst_parser, "parse_document", spy)

    out = docs_handlers.docs_get_section(_TextBackend("א\n=\n\nב\n=\n\n"), path="x")

    assert out["ok"] and out["mode"] == "toc"
    assert out["section_count"] == 2
    assert passed.get("max_sections") is None, (
        f"הכלי העביר תקרה לפרסור: {passed}"
    )
    assert inspect.signature(real).parameters["max_sections"].default is None, (
        "ברירת המחדל של max_sections אינה None, ולכן הכלי חסום גם בלי להעביר כלום"
    )
