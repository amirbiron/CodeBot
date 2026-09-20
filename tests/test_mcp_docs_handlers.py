"""טסטים ל-handler של docs_get_section — עם fake backend שקורא RST אמיתי מ-docs/."""

import inspect
from pathlib import Path

import pytest

from mcp_server import docs_handlers
from services import doc_sections, rst_parser

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

    # **עמוד בגודל רגיל נענה במלואו, וזה העיקר כאן.** רשימת מזהים היא
    # מלאי ולא דירוג, ולכן ה-handler מבקש את התקרה במפורש. הקובץ העשיר
    # ביותר בקורפוס שהסוכנים קוראים נושא 16 מזהים — גרסה קודמת החזירה
    # עליו חמישה בסדר הופעה, כך שסוכן ששאל ``K11`` לא ראה אותו כלל.
    sixteen = docs_handlers.docs_get_section(
        _TextBackend(_identified_rst(*[f"K{i}. טקסט" for i in range(1, 17)])),
        path="x", section="Z9")
    assert len(sixteen["suggestions"]) == 16, "העמוד לא נענה במלואו"
    assert "K11" in sixteen["suggestions"]
    assert "suggestions_truncated" not in sixteen

    # והתקרה עדיין קיימת, ועדיין אומרת שהיא נגעה
    many = docs_handlers.docs_get_section(
        _TextBackend(_identified_rst(*[f"K{i}. טקסט" for i in range(1, 52)])),
        path="x", section="Z9")
    assert many["suggestions_truncated"] is True
    assert len(many["suggestions"]) == doc_sections.MAX_IDENTIFIER_SUGGESTIONS == 50


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


def test_the_docs_reader_passes_the_shared_section_ceiling_and_refuses_above_it(monkeypatch):
    """הצרכן בייצור מעביר את תקרת הסקשנים של הסורק, ומעליה מסרב — לא מפרסר את הכול.

    זה היפוך מכוון של הבדיקה שישבה כאן מ-#3378 ("הצרכן בייצור אינו מוגבל
    בתקרה"). הנימוק שלה — שקובץ תיעוד גדול לא ייחסם — נמדד ונמצא ריק
    בתקרת הקריאה של הכלי: 500KB של העמוד הצפוף ביותר בריפו (6.5 סקשנים
    ל-KB) הם כ-3,300 סקשנים, פי 15 מתחת לתקרה. מה שהתקרה כן עוצרת הוא
    הצורה העוינת — כותרת בת תו אחד בכל שורה — שבלעדיה עולה 44.0MiB לפרסור
    אחד של 500KB, יותר מ-35.2MiB שמאגר הקריאות מקצה לחוט
    (``_PARSE_COST_BYTES`` ב-``mcp_server/server.py``), ואיתה נעצרת
    ב-20.1MiB. סקירת #3429.

    **ונבדק בלי להציף את התקרה, מאותה סיבה שנימקה הבדיקה הקודמת:** בניית
    ``MAX_SYMBOLS + 1`` סקשנים אמיתיים קושרת את מחיר הבדיקה לקבוע שהיא
    מגנה עליו (819KB ו-71MB בכל ריצה, ופי עשר מזה כשהתקרה תעלה). הכלי
    קורא את התקרה מהמודול בזמן הקריאה, ולכן היא מוקטנת כאן ל-2, והפרסר
    האמיתי הוא שמרים את החריגה — על שלושה סקשנים. ברירת המחדל של הפרסר
    נשארת ``None``, וזה עדיין נבדק, כי קורא אחר שאינו מעביר תקרה חייב
    לדעת שאינו מוגן.
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
    assert passed.get("max_sections") == docs_handlers._ceiling.MAX_SYMBOLS, (
        f"הכלי לא העביר את תקרת הסורק לפרסור: {passed}"
    )
    assert inspect.signature(real).parameters["max_sections"].default is None, (
        "ברירת המחדל של max_sections השתנתה — ההגנה כאן באה מהכלי, לא מהפרסר"
    )

    monkeypatch.setattr(docs_handlers._ceiling, "MAX_SYMBOLS", 2)

    at_the_ceiling = docs_handlers.docs_get_section(_TextBackend("א\n=\n\nב\n=\n\n"), path="x")
    assert at_the_ceiling["ok"] and at_the_ceiling["section_count"] == 2, (
        "קובץ עם בדיוק התקרה עובר במלואו — אותו גבול כמו בפרסר ובסורק"
    )

    above = docs_handlers.docs_get_section(_TextBackend("א\n=\n\nב\n=\n\nג\n=\n\n"), path="x")
    assert above == {
        "ok": False, "error": "too_many_sections", "max": 2,
        "repo": "CodeBot", "path": "docs/x.rst",
        "file": {"path": "docs/x.rst", "ref": "HEAD", "resolved_commit": "c0ffee"},
    }
