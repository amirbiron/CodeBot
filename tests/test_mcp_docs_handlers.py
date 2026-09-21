"""טסטים ל-handler של docs_get_section — עם fake backend שקורא RST אמיתי מ-docs/."""

import functools
import inspect
from pathlib import Path

import pytest

from mcp_server import docs_handlers
from services import doc_sections, md_parser, rst_parser

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


def test_candidates_are_capped_and_the_flag_appears_only_when_they_were_cut(monkeypatch):
    """‏``candidates`` היה השדה היחיד בתשובה בלי תקרה (#3426).

    מזהה שחוזר בעמוד החזיר את **כל** המופעים — נמדד 13,030 מועמדים ו-1.39MB
    על שאילתה בת שלושה תווים. עכשיו הוא חסום כמו ``toc`` ו-``suggestions``,
    והדגל קיים רק כשהוא נכון, כדי שכל תשובת ``ambiguous_section`` על עמוד
    רגיל תישאר זהה בית-בית (אפס-דיף). התקרה נקראת מהמודול בזמן הקריאה
    ומוקטנת כאן ל-2, במקום לבנות חמישים ואחת כותרות — אותו נימוק כמו בטסט
    תקרת הסקשנים.
    """
    monkeypatch.setattr(docs_handlers, "_CANDIDATES_MAX", 2)

    at_the_cap = docs_handlers.docs_get_section(
        _TextBackend(_identified_rst("P3 — ראשון", "P3 — שני")), path="x", section="P3")
    assert at_the_cap["error"] == "ambiguous_section"
    assert [c["title"] for c in at_the_cap["candidates"]] == ["P3 — ראשון", "P3 — שני"]
    assert "candidates_truncated" not in at_the_cap, "עמוד שבדיוק בתקרה נענה במלואו, בלי דגל"

    over = docs_handlers.docs_get_section(
        _TextBackend(_identified_rst("P3 — ראשון", "P3 — שני", "P3 — שלישי")),
        path="x", section="P3")
    assert over["error"] == "ambiguous_section"
    assert [c["title"] for c in over["candidates"]] == ["P3 — ראשון", "P3 — שני"], "בסדר הופעה"
    assert over["candidates_truncated"] is True


def test_the_candidates_cap_is_the_suggestions_inventory_number():
    """שני מלאים לא-מדורגים באותה תשובה — מספר אחד, כמו שני גבולות האאוטליין והפארסר."""
    assert docs_handlers._CANDIDATES_MAX == doc_sections.MAX_IDENTIFIER_SUGGESTIONS


def test_suggestions_on_a_markdown_page_are_a_list_of_strings_too(both_repos):
    """הצרכן שנוסף ב-#3428 הוא אותו אתר קריאה לשני הפורמטים, והוא כותב ``.titles``.

    ‏#3426 ביקש שזה ייקבע בטסט ולא רק ב-docstring של ``Suggestions``: מי שישכח
    את ``.titles`` ישלח ``[["K11"], false]`` — JSON תקין בלי שום שגיאה — וגם
    במסלול ה-Markdown איש לא היה תופס את זה.
    """
    md = "# K11. כשל\n\nטקסט\n\n# K12. דגל\n\nטקסט\n"
    out = docs_handlers.docs_get_section(_TextBackend(md), path="x.md",
                                         repo="amir-bug-patterns", section="K99")
    assert out["error"] == "section_not_found"
    assert out["suggestions"] == ["K11", "K12"]
    assert all(isinstance(s, str) for s in out["suggestions"])


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


def test_the_rst_reader_is_capped_by_the_parser_default_and_refuses_above_it(monkeypatch):
    """הצרכן בייצור אינו מעביר תקרה, וברירת המחדל של הפרסר **היא** התקרה (#3420).

    הגלגול השלישי של הבדיקה שיושבת כאן. #3378: "הצרכן בייצור אינו מוגבל
    בתקרה". סקירת #3429 הפכה אותה: הכלי מעביר את ``_ceiling.MAX_SYMBOLS``
    במפורש, כי ברירת המחדל של ``rst_parser`` הייתה ``None`` וכל קורא אחר
    נשאר בלי הגנה. #3420 יישר את ברירת המחדל ל-``MAX_SECTIONS`` של
    ``doc_sections`` — אחרי מדידה על כל 208 קובצי ה-RST (הקובץ העשיר ביותר
    נושא 50 סקשנים, אחד לאלף מהתקרה) ואפס-דיף על פלט הכלי — ומאז הכלי
    אינו מעביר דבר, בדיוק כמו במסלול ה-Markdown: העברה מפורשת מכאן הייתה
    עותק שני של החלטה שהפארסר כבר הכריע.

    **ומה שנשמר משתי הגרסאות הקודמות:** הסירוב מעל התקרה בא כ-``error``
    ולא כחריגה שבורחת, קובץ שיושב בדיוק על התקרה עובר במלואו, ו-``"max"``
    בתשובה הוא המספר שהפרסר השתמש בו. מה שהתקרה עוצרת — כותרת בת תו אחד
    בכל שורה, 44.0MiB לפרסור של 500KB בלעדיה ו-20.1MiB איתה — נמדד בסקירת
    #3429 ולא זז.

    **ונבדק בלי להציף את התקרה, מאותה סיבה שנימקו שתי הקודמות:** בניית
    ``MAX_SECTIONS + 1`` סקשנים אמיתיים קושרת את מחיר הבדיקה לקבוע שהיא
    מגנה עליו. ברירת המחדל קפואה בחתימה, ולכן היא מוקטנת ב-``partial``
    על הפרסר עצמו — וזה עובד רק מפני שהכלי אינו מעביר ארגומנט שדורס
    אותה, שזו הטענה הראשונה כאן.
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
    assert passed == {}, f"הכלי העביר תקרה לפרסור: {passed}"
    assert (inspect.signature(real).parameters["max_sections"].default
            is doc_sections.MAX_SECTIONS), (
        "ברירת המחדל של max_sections ב-rst_parser אינה MAX_SECTIONS — "
        "ההגנה במסלול הזה באה מהפרסר, וכשהיא זזה שם היא זזה גם כאן")

    monkeypatch.setattr(docs_handlers.rst_parser, "parse_document",
                        functools.partial(real, max_sections=2))

    at_the_ceiling = docs_handlers.docs_get_section(_TextBackend("א\n=\n\nב\n=\n\n"), path="x")
    assert at_the_ceiling["ok"] and at_the_ceiling["section_count"] == 2, (
        "קובץ עם בדיוק התקרה עובר במלואו — אותו גבול כמו בפרסר ובסורק"
    )

    three = "א\n=\n\nב\n=\n\nג\n=\n\n"
    above = docs_handlers.docs_get_section(_TextBackend(three), path="x")
    assert {k: above[k] for k in ("ok", "error", "max", "repo", "path", "ref",
                                  "resolved_commit")} == {
        "ok": False, "error": "too_many_sections", "max": doc_sections.MAX_SECTIONS,
        "repo": "CodeBot", "path": "docs/x.rst", "ref": "HEAD", "resolved_commit": "c0ffee",
    }
    # ``"max"`` הוא הקבוע ולא ה-2 של ה-``partial``: הכלי מדווח את התקרה
    # שהפרסר מצהיר עליה, והטסט הוא שהנמיך אותה מאחורי גבו.
    #
    # **ואין ``line``, וזה לא חסר אלא נכון.** ``rst_parser`` מרים
    # ``TooManySections`` בלי ארגומנט (``raise TooManySections``, נמדד), בעוד
    # ``md_parser`` מרים אותה עם השורה. ``_line_of`` מוסיף את השדה רק כשיש
    # מה לשים בו, ולכן סירוב RST בא בלעדיו — לא עם ``null``. הטסט ל-Markdown
    # הוא שמוכיח שהמספר עובר כשהפארסר מספק אותו.
    with pytest.raises(doc_sections.TooManySections) as raised:
        real(three, max_sections=2)
    assert raised.value.args == (), "rst_parser התחיל לשאת שורה — עדכן את התיעוד ואת הטסט הזה"
    assert "line" not in above


# ===========================================================================
# חיווט ה-Markdown: מדיניות נתיבים לכל ריפו, ניתוב לפי סיומת, ומיפוי סירובים
# ===========================================================================


class _RecordingBackend:
    """מחזיר טקסט נתון, ושומר את הארגומנטים **כפי שהועברו**.

    ``**kwargs`` ולא חתימה מפורטת, וזה כל העניין: ``_FsBackend`` ו-
    ``_TextBackend`` למעלה מצהירים ``lines=None``, כלומר הם **בולעים** את
    הפרמטר ואינם מסוגלים לטעון שלא הועבר. דמה שמצהירה מראש על מה שהיא
    מצפה לקבל אינה יכולה לבדוק מה באמת נשלח — היא יכולה רק לא ליפול.
    """

    def __init__(self, text="כותרת\n======\n\nגוף\n"):
        self._text = text
        self.kwargs: list[dict] = []

    def get_file(self, **kwargs):
        self.kwargs.append(dict(kwargs))
        return {
            "ok": True, "status": "ok",
            "file": {"path": kwargs.get("path"), "ref": "HEAD",
                     "resolved_commit": "c0ffee"},
            "content": self._text,
        }

    @property
    def paths(self) -> list:
        return [k.get("path") for k in self.kwargs]


class _CountingMirror:
    """מראה שסופרת מה נקרא ממנה, כדי שאפשר יהיה להוכיח ש**לא נגעו בה**.

    ``RepoBackend.get_file`` עוטף את הקריאה למראה ב-``except Exception``,
    ולכן מראה שמרימה חריגה הייתה מתורגמת ל-``read_failed`` — תוצאה
    שנראית כמו כשל קריאה ולא כמו חסימה. ספירה מבדילה בין השניים בלי
    להישען על סמנטיקה של חריגות.
    """

    def __init__(self, text="# כותרת\n\nגוף\n"):
        self._text = text
        self.reads: list[str] = []

    def get_file_at_commit(self, repo, path, commit, **k):
        self.reads.append(path)
        return {
            "success": True, "file_path": path, "resolved_commit": "abc123",
            "is_binary": False, "content": self._text, "encoding": "utf-8",
            "size": len(self._text), "lines": self._text.count("\n") + 1,
        }

    def get_default_branch(self, repo):
        return "main"


def _real_backend(mirror):
    """``RepoBackend`` אמיתי מעל מראה נתונה — התקדים: ``tests/test_mcp_outline.py``."""
    from mcp_server.repo_backend import RepoBackend

    return RepoBackend(mirror=mirror)


@pytest.fixture
def both_repos(monkeypatch):
    """שני הריפואים ברשימת ההיתר — התצורה שהפיצ'ר הזה מתאר.

    ``MCP_DOCS_REPO`` הוא גבול אבטחה שנקרא בכל קריאה, ולכן הוא נקבע
    במפורש בכל טסט שנוגע בריפו ה-Markdown ולא ב-``autouse`` על הקובץ:
    fixture גורף היה משנה בשקט את המשמעות של הטסטים הקיימים, שחלקם
    בודקים דווקא את **ברירת המחדל**.
    """
    monkeypatch.setenv("MCP_DOCS_REPO", "CodeBot,amir-bug-patterns")


@pytest.fixture
def md_repo(monkeypatch):
    """הריפו של ה-Markdown כברירת המחדל, בלי לנקוב בו בכל קריאה."""
    monkeypatch.setenv("MCP_DOCS_REPO", "amir-bug-patterns,CodeBot")


# ---- מדיניות נתיבים לכל ריפו ----


def test_a_bare_slug_in_the_markdown_repo_lands_at_the_repo_root(both_repos):
    """slug בלי ``/`` מקבל את השורש והסיומת של **הריפו שנקבו בו**."""
    be = _RecordingBackend()
    out = docs_handlers.docs_get_section(be, path="CRITICAL-PATTERNS",
                                         repo="amir-bug-patterns")
    assert out["ok"] and be.paths == ["CRITICAL-PATTERNS.md"]


def test_a_nested_slug_in_the_markdown_repo_is_taken_as_written(both_repos):
    """slug שכבר יש בו ``/`` אינו נעגן — רק הסיומת מתווספת.

    זו ההתנהגות של היום ב-CodeBot (``observability/error_codes`` אינו
    הופך ל-``docs/observability/...``), והיא נשמרת כמות שהיא. בריפו
    שהשורש שלו ריק זה פשוט אומר שהנתיב המקונן עובד מאליו.
    """
    be = _RecordingBackend()
    out = docs_handlers.docs_get_section(be, path="bugbot-rules/race-toctou",
                                         repo="amir-bug-patterns")
    assert out["ok"] and be.paths == ["bugbot-rules/race-toctou.md"]


@pytest.mark.parametrize("repo,path,allowed", [
    ("CodeBot", "CRITICAL-PATTERNS.md", [".rst"]),
    ("amir-bug-patterns", "mcp-server.rst", [".md"]),
])
def test_asking_a_repo_for_a_format_it_does_not_serve_is_refused_by_name(
        monkeypatch, repo, path, allowed):
    """פורמט שהכלי מכיר אך הריפו אינו מגיש → ``suffix_not_allowed``, לא ``not_found``.

    **בלי הסירוב המפורש זו הייתה השמטה שקטה:** הסיומת הייתה מתווספת
    מעל הקיימת (``CRITICAL-PATTERNS.md.rst``), הקובץ לא היה נמצא,
    והקורא היה מקבל "לא קיים" על קובץ שקיים — כלומר מחפש את הבאג
    בקובץ במקום במדיניות.
    """
    monkeypatch.setenv("MCP_DOCS_REPO", "CodeBot,amir-bug-patterns")
    be = _RecordingBackend()
    out = docs_handlers.docs_get_section(be, path=path, repo=repo)
    assert out["ok"] is False and out["error"] == "suffix_not_allowed"
    assert out["allowed_suffixes"] == allowed
    assert out["requested_path"] == path
    assert be.kwargs == []  # נחסם ב-handler, לפני ה-backend


def test_an_unknown_suffix_is_part_of_the_slug_and_not_a_format(both_repos):
    """סיומת שהכלי אינו מכיר אינה סירוב — היא חלק מהשם, והסיומת מתווספת מעליה.

    ``python-3.13`` הוא slug לגיטימי ש-``splitext`` רואה בו סיומת
    ``.13`` (נמדד), ולכן דחייה של כל סיומת לא-מוכרת הייתה חוסמת שמות
    תקינים. התשובה **מהדהדת את הנתיב שחיפשנו**, ולכן אין כאן הפתעה
    שקטה: הקורא רואה בדיוק מה ביקשנו מהמראה.
    """
    be = _RecordingBackend()
    docs_handlers.docs_get_section(be, path=".claude/settings.json",
                                   repo="amir-bug-patterns")
    assert be.paths == [".claude/settings.json.md"]


def test_a_dotfile_directory_is_reachable_in_a_repo_rooted_at_its_top(both_repos):
    """קובץ ``.md`` תחת ``.claude/`` **נגיש**, וזו החלטה ולא תאונה.

    שורש ריק פירושו כל הריפו, בכל עומק. נספר לפני ההחלטה: ב-
    ``amir-bug-patterns`` יש 95 קבצים, 93 מהם ``.md`` וכולם מסמכי
    דפוסים שנועדו לקריאה על ידי סוכן, והריפו ציבורי ב-GitHub. שני
    הקבצים שאינם ``.md`` — ``.claude/settings.json`` ו-``.sh`` —
    מסוננים ממילא על ידי הסיומת.

    **הטסט קיים כדי שההחלטה תהיה נראית.** מי שיחליט מחר שזה לא רצוי
    ישנה את ``root``, יראה את הטסט הזה נופל, ויידע שהוא משנה הכרעה
    ולא מתקן באג.
    """
    be = _RecordingBackend()
    out = docs_handlers.docs_get_section(be, path=".claude/notes.md",
                                         repo="amir-bug-patterns")
    assert out["ok"] and be.paths == [".claude/notes.md"]


# ---- fail-closed ----


def test_a_repo_on_the_allowlist_without_a_path_policy_is_refused(monkeypatch):
    """ה-ENV מתיר, והקוד אינו יודע איפה התיעוד שם → ``repo_not_configured``.

    **ולא נפילה לברירת מחדל מתירנית.** ריפו שמישהו הוסיף ל-ENV בלי
    להוסיף לו מדיניות היה מוגש תחת המדיניות של CodeBot — כלומר קריאת
    ``docs/*.rst`` מריפו שאיש לא החליט עליו. זה fail-closed מאותו
    נימוק שבגללו ``is_denied`` נכשל-סגור.
    """
    monkeypatch.setenv("MCP_DOCS_REPO", "CodeBot,ghost-repo")
    be = _RecordingBackend()
    out = docs_handlers.docs_get_section(be, path="anything", repo="ghost-repo")
    assert out == {"ok": False, "error": "repo_not_configured", "repo": "ghost-repo"}
    assert be.kwargs == []


def test_the_first_entry_of_the_env_decides_both_the_repo_and_its_path_rules(md_repo):
    """הכניסה הראשונה ב-``MCP_DOCS_REPO`` קובעת גם את הפורמט, לא רק את השם.

    זו התנהגות חדשה שנובעת ממדיניות פר-ריפו, והיא נכתבת כאן במפורש כי
    שינוי **סדר** ב-ENV הפך להיות שינוי התנהגות ולא סידור.
    """
    be = _RecordingBackend()
    out = docs_handlers.docs_get_section(be, path="CRITICAL-PATTERNS")
    assert out["ok"] and out["repo"] == "amir-bug-patterns"
    assert be.paths == ["CRITICAL-PATTERNS.md"]


def test_a_repo_outside_the_allowlist_is_refused_before_the_path_is_examined(monkeypatch):
    """ריפו אסור נדחה **לפני** הנתיב, גם כששניהם פגומים.

    אחרת קורא שנקב בריפו שאינו רשאי לגעת בו היה לומד ממנו משהו:
    ``suffix_not_allowed`` מול ``missing_path`` מספר לו מה הפורמט שהריפו
    ההוא מגיש.
    """
    monkeypatch.delenv("MCP_DOCS_REPO", raising=False)
    be = _RecordingBackend()
    out = docs_handlers.docs_get_section(be, path="x.md", repo="not-allowed")
    assert out["ok"] is False and out["error"] == "repo_not_allowed"
    assert be.kwargs == []


# ---- הגבול: traversal, נרמול, ויחידה-ולא-קידומת ----


def test_the_root_anchor_is_decided_before_normalisation():
    """``docs/../secrets`` נדחה — והסדר הוא מה שדוחה אותו.

    הקלט נושא ``/``, ולכן אינו נעגן; אחרי הנרמול הוא ``secrets.rst``,
    שאינו תחת ``docs/``. מי שיקדים את ``normpath`` לעגינה יקבל
    ``secrets.rst`` בלי ``/``, יעגן אותו ל-``docs/secrets.rst``,
    **ויגיש אותו**.
    """
    be = _RecordingBackend()
    out = docs_handlers.docs_get_section(be, path="docs/../secrets", repo="CodeBot")
    assert out == {"ok": False, "error": "missing_path"}
    assert be.kwargs == []


@pytest.mark.parametrize("bad_path", [
    "../README.md",
    "../../etc/passwd.md",
    "bugbot-rules/../../escape.md",
])
def test_traversal_out_of_the_repo_is_refused_even_at_the_repo_root(both_repos, bad_path):
    """שורש ריק אינו "הכול" — הוא "כל דבר **בתוך** הריפו"."""
    be = _RecordingBackend()
    out = docs_handlers.docs_get_section(be, path=bad_path, repo="amir-bug-patterns")
    assert out == {"ok": False, "error": "missing_path"}
    assert be.kwargs == []


@pytest.mark.parametrize("dots", ["..", "."])
def test_a_path_that_is_only_dots_becomes_a_harmless_name_and_not_an_escape(
        both_repos, dots):
    """``".."`` אינו טיפוס מעל הריפו — הסיומת הופכת אותו לשם קובץ שאינו קיים.

    **וזה ההתנהגות של היום, לא הכרעה חדשה:** גם ב-CodeBot ``path=".."``
    הופך ל-``docs/...rst`` ומחזיר ``not_found``. מה שנבדק כאן הוא
    שהשורש הריק לא הפך את המקרה הזה למשהו אחר.

    **ובדרך הוא גם מקבע את מה שהפיל אותנו:** ``splitext("...md")`` מחזיר
    סיומת **ריקה**, ולכן גזירה שנייה של הסיומת מהנתיב המוגמר הייתה
    מפילה ``KeyError`` מתוך בקשה. הטסט הזה נפל בדיוק כך לפני התיקון.
    """
    be = _RecordingBackend()
    out = docs_handlers.docs_get_section(be, path=dots, repo="amir-bug-patterns")
    assert out["ok"]
    assert be.paths == [dots + ".md"]


def test_a_traversal_that_stays_inside_the_repo_resolves_to_what_it_points_at(both_repos):
    """``..`` אינו מילה אסורה — הוא נרמול. מה שנבדק הוא **לאן** הוא מגיע."""
    be = _RecordingBackend()
    out = docs_handlers.docs_get_section(be, path="bugbot-rules/../README",
                                         repo="amir-bug-patterns")
    assert out["ok"] and be.paths == ["README.md"]


def test_a_root_is_matched_as_a_path_unit_and_not_as_a_prefix(monkeypatch):
    """``docsecret/x`` אינו תחת ``docs/`` — זו מחלקת הבאג ``K16``.

    נבדק על ריפו סינתטי ולא על CodeBot, כי הדוגמה צריכה להיות נתיב
    שמתחיל **באותם תווים** בלי שום קשר היררכי, ובקורפוס האמיתי אין
    כזה. ``norm.startswith("docs")`` בלי המפריד מקבל אותו.
    """
    monkeypatch.setenv("MCP_DOCS_REPO", "CodeBot,synthetic")
    monkeypatch.setitem(docs_handlers.DOCS_PATH_POLICY, "synthetic",
                        docs_handlers._DocsPathPolicy(root="docs", suffix=".rst"))
    be = _RecordingBackend()
    out = docs_handlers.docs_get_section(be, path="docsecret/x", repo="synthetic")
    assert out == {"ok": False, "error": "missing_path"}
    assert be.kwargs == []


def test_a_leading_slash_is_tolerated_and_the_answer_says_what_was_looked_up(both_repos):
    """נתיב שמתחיל ב-``/`` מקוצץ ולא נדחה — ההתנהגות של היום, מקובעת.

    סוכן שמדביק ``/docs/mcp-server.rst`` מקבל תשובה במקום סירוב, והנתיב
    בתשובה אומר לו בדיוק מה נקרא.
    """
    be = _RecordingBackend()
    out = docs_handlers.docs_get_section(be, path="/CRITICAL-PATTERNS",
                                         repo="amir-bug-patterns")
    assert out["ok"] and out["path"] == "CRITICAL-PATTERNS.md"


# ---- מדיניות הסודות, דרך ה-RepoBackend האמיתי ----


@pytest.mark.parametrize("repo,path,normalised", [
    ("CodeBot", "credentials", "docs/credentials.rst"),
    ("CodeBot", "secrets", "docs/secrets.rst"),
    ("amir-bug-patterns", "secrets", "secrets.md"),
    ("amir-bug-patterns", "config/.env", "config/.env.md"),
    # שם רגיש כ**תיקייה** ולא כקובץ. שורש ריק פירושו כל הריפו בכל עומק,
    # ולכן דווקא כאן הצורה הזאת נגישה — ודווקא כאן היא הייתה עוברת לפני
    # שהמדיניות למדה להשוות מול כל רכיב בנתיב.
    ("amir-bug-patterns", "config/.env/README.md", "config/.env/README.md"),
    ("amir-bug-patterns", "certs/server.pem/notes.md", "certs/server.pem/notes.md"),
    ("CodeBot", "docs/.env/README", "docs/.env/README.rst"),
])
def test_the_secrets_denylist_reaches_this_tool_through_the_real_backend(
        monkeypatch, repo, path, normalised):
    """נתיב שתואם דפוס סוד נחסם גם בכלי הציבורי, **והמראה לא נגעה**.

    **דרך ``RepoBackend`` האמיתי ולא דרך דמה.** ``_FsBackend`` ו-
    ``_TextBackend`` שבראש הקובץ קוראים מהדיסק ישירות ולעולם אינם
    עוברים דרך ``is_denied`` — טסט סודות שנכתב מולם היה עובר בלי לבדוק
    שום דבר. זו בדיוק מחלקת הכשל ``T1`` ב-``amir-bug-patterns``: הבדיקה
    עוברת בממשק שאף צרכן אינו משתמש בו.

    **ו-``mirror.reads == []`` ולא רק קוד השגיאה:** הוא מוכיח שהחסימה
    קרתה **לפני** נגיעה במראה, שזו כל הנקודה של מדיניות שנכשלת-סגור.
    """
    monkeypatch.setenv("MCP_DOCS_REPO", "CodeBot,amir-bug-patterns")
    mirror = _CountingMirror()
    out = docs_handlers.docs_get_section(_real_backend(mirror), path=path, repo=repo)
    assert out["ok"] is False and out["error"] == "path_denied"
    assert out["path"] == normalised
    assert mirror.reads == []


def test_an_ordinary_page_does_reach_the_mirror_through_the_same_backend(monkeypatch):
    """ריצת הבקרה לטסט שמעליו: בלי אותו נתיב, המראה **כן** נקראת.

    בלי השורה הזאת ``mirror.reads == []`` היה יכול להיות נכון מסיבה
    אחרת לגמרי — backend שבור, ref שגוי, או מראה שלא חוברה בכלל.
    """
    monkeypatch.setenv("MCP_DOCS_REPO", "amir-bug-patterns")
    mirror = _CountingMirror()
    out = docs_handlers.docs_get_section(_real_backend(mirror), path="README",
                                         repo="amir-bug-patterns")
    assert out["ok"] and mirror.reads == ["README.md"]


# ---- ניתוב לפי סיומת ----


def test_a_markdown_page_is_parsed_by_the_markdown_parser(both_repos):
    """``# כותרת`` הוא סעיף ב-Markdown — וב-RST הוא הערה, כלומר אפס סעיפים."""
    text = "# כותרת\n\nגוף\n"
    md = docs_handlers.docs_get_section(_TextBackend(text), path="x.md",
                                        repo="amir-bug-patterns")
    assert [t["title"] for t in md["toc"]] == ["כותרת"]
    assert rst_parser.parse_document(text).sections == []


def test_an_rst_page_is_still_parsed_by_the_rst_parser():
    """``~~~~~~`` הוא קו כותרת ב-RST — וב-Markdown הוא גדר קוד, כלומר אפס כותרות."""
    text = "כותרת\n~~~~~~\n\nגוף\n"
    out = docs_handlers.docs_get_section(_TextBackend(text), path="x.rst",
                                         repo="CodeBot")
    assert [t["title"] for t in out["toc"]] == ["כותרת"]
    assert md_parser.parse_document(text).sections == []


def test_the_parser_table_holds_modules_so_a_monkeypatch_on_the_module_is_seen(
        monkeypatch):
    """הטבלה מחזיקה **מודולים**, ולכן החלפת ``parse_document`` עליהם נתפסת.

    **וזה מה ש-``test_the_rst_reader_is_capped_by_the_parser_default_and_refuses_above_it`` אינו
    תופס.** אילו הטבלה הייתה מחזיקה את הפונקציה עצמה, היא הייתה קופאת
    על המקורית, ה-spy היה נעקף **בשקט**, ו-``passed`` שם היה נשאר ריק —
    כלומר ``passed == {}`` היה ממשיך לעבור. שומר שעובר משתי סיבות שונות
    אינו שומר.
    """
    calls = []
    real = rst_parser.parse_document

    def spy(text, **kwargs):
        calls.append(text)
        return real(text, **kwargs)

    monkeypatch.setattr(docs_handlers.rst_parser, "parse_document", spy)
    docs_handlers.docs_get_section(_TextBackend("א\n=\n"), path="x.rst", repo="CodeBot")
    assert len(calls) == 1, "הפארסר נקרא דרך הפניה שהוקפאה, וה-monkeypatch נעקף"


# ---- מיפוי שתי חריגות הסירוב ----


def test_a_lone_cr_in_markdown_is_refused_by_name_with_the_file_it_came_from(both_repos):
    """``\\r`` בודד → ``inconsistent_line_endings``, עם ההקשר שמאפשר לפתוח את הקובץ.

    **הפארסר האמיתי, החריגה האמיתית.** הקלט הוא הצורה שבה ``split("\\n")``
    ו-``splitlines()`` נותנים אותו מספר שורות ובכל זאת המפה זזה — כלומר
    שומר שמשווה ספירות היה עובר אותו.
    """
    out = docs_handlers.docs_get_section(
        _TextBackend("# א\n\n## ב\rטקסט\n\n## ג\n"),
        path="x.md", repo="amir-bug-patterns")
    assert out["ok"] is False and out["error"] == "inconsistent_line_endings"
    assert out["repo"] == "amir-bug-patterns" and out["path"] == "x.md"
    assert out["resolved_commit"] == "c0ffee"


def test_a_markdown_file_over_the_heading_ceiling_is_refused_by_name(both_repos, monkeypatch):
    """חריגה מהתקרה → ``too_many_sections``, ולא חריגה שבורחת מהכלי.

    **התקרה מוקטנת במקום להגדיל את הקלט, וזה נימוק ולא נוחות.** קלט
    של ``MAX_SECTIONS + 1`` כותרות אמיתיות הוא מאות מגה-בייט בכל ריצת
    CI, והמחיר שלו צמוד לקבוע שהוא מגן עליו — כלומר הוא מתדרדר בדיוק
    כשהמערכת גדלה. אותו נימוק בדיוק כתוב ב-
    ``test_the_rst_reader_is_capped_by_the_parser_default_and_refuses_above_it`` שמעליו.
    """
    real = md_parser.parse_document
    monkeypatch.setattr(md_parser, "parse_document",
                        functools.partial(real, max_sections=5))
    text = "".join(f"# כותרת {i}\n\n" for i in range(6))
    out = docs_handlers.docs_get_section(_TextBackend(text), path="x.md",
                                         repo="amir-bug-patterns")
    assert out["ok"] is False and out["error"] == "too_many_sections"
    assert out["path"] == "x.md"


def test_the_two_refusals_are_mapped_whichever_parser_raised_them(monkeypatch):
    """ה-``except`` אינו מותנה בפארסר שפרסר, וגם RST מקבל את אותו קוד.

    התניה על ``parser is md_parser`` הייתה רשימה שנייה לסנכרן: כשהתקרה
    נוספה למסלול ה-RST (#3429), הסירוב היה בורח מהכלי כחריגה גולמית.

    **התקרה מונמכת ב-``partial`` על הפרסר, כמו במסלול ה-Markdown.** בין
    #3429 ל-#3420 זה לא עבד כאן — הכלי העביר ``max_sections`` במפורש,
    וארגומנט מפורש בקריאה דורס את זה שב-``partial`` — ולכן הטסט הנמיך אז
    את ``_ceiling.MAX_SYMBOLS``. מאז #3420 הכלי אינו מעביר דבר לאף פארסר,
    וה-``partial`` הוא הדרך היחידה להנמיך, בשני המסלולים.
    """
    monkeypatch.setattr(docs_handlers.rst_parser, "parse_document",
                        functools.partial(rst_parser.parse_document, max_sections=1))
    out = docs_handlers.docs_get_section(_TextBackend("א\n=\n\nב\n=\n"),
                                         path="x.rst", repo="CodeBot")
    assert out["ok"] is False and out["error"] == "too_many_sections"


# ---- תקרות: צורת הקריאה, והתקרה האפקטיבית של Markdown ----


def test_the_reader_asks_for_the_whole_file_and_so_keeps_the_display_ceiling(both_repos):
    """הקריאה ל-backend נושאת בדיוק ``repo``, ``path`` ו-``ref`` — ותו לא.

    **הטענה היא על הצורה ולא על המספר.** ``lines`` או ``outline`` היו
    מעבירים את ``RepoBackend`` ל-``RANGE_READ_MAX_BYTES`` (10MB) במקום
    ל-500KB של שירות המראה, כלומר פי עשרים קלט לפרסור — ושום מספר
    בקוד הזה לא היה משתנה כדי להסגיר את זה.
    """
    be = _RecordingBackend()
    docs_handlers.docs_get_section(be, path="x.md", repo="amir-bug-patterns")
    assert set(be.kwargs[0]) == {"repo", "path", "ref"}


def test_the_markdown_reader_is_capped_by_the_parser_default(both_repos, monkeypatch):
    """התקרה האפקטיבית של מסלול ה-Markdown היא ``MAX_SECTIONS``.

    **אותה תמונה כמו ``test_the_rst_reader_is_capped_by_the_parser_default_and_refuses_above_it``**,
    ושתי הטענות מאותו סוג: הכלי אינו מעביר תקרה, וברירת המחדל בחתימה
    **היא** התקרה. העברה מפורשת של ``md_parser.MAX_SECTIONS`` מה-handler
    הייתה עותק שני של אותה החלטה, ו-PR הפארסר כבר הכריע אותה — ומאז
    #3420 גם מסלול ה-RST על אותה ברירת מחדל בדיוק.
    """
    passed: dict = {}
    real = md_parser.parse_document

    def spy(text, **kwargs):
        passed.update(kwargs)
        return real(text, **kwargs)

    monkeypatch.setattr(docs_handlers.md_parser, "parse_document", spy)
    out = docs_handlers.docs_get_section(_TextBackend("# א\n"), path="x.md",
                                         repo="amir-bug-patterns")

    assert out["ok"] and out["section_count"] == 1
    assert passed == {}, f"הכלי העביר תקרה לפרסור: {passed}"
    assert (inspect.signature(real).parameters["max_sections"].default
            is md_parser.MAX_SECTIONS), (
        "ברירת המחדל של max_sections ב-md_parser אינה MAX_SECTIONS, "
        "ולכן מסלול ה-Markdown רץ בלי תקרה")


# ---- סנכרון שתי הטבלאות ----


def test_every_suffix_a_repo_policy_names_has_a_parser(monkeypatch):
    """הטבלה שאומרת מה מוגש והטבלה שאומרת מה נפרסר אינן יכולות להיסחף בשקט.

    **שני חצאים.** הראשון על הטבלה החיה; השני מוכיח שהשומר עצמו מסוגל
    ליפול — בלעדיו "הכול מקיים את היחס" היה יכול להיות נכון גם אם
    הבדיקה נמחקה מ-``_validate_policy_tables``.
    """
    for repo, policy in docs_handlers.DOCS_PATH_POLICY.items():
        assert policy.suffix in docs_handlers._PARSERS, f"{repo}: {policy.suffix}"

    monkeypatch.setitem(docs_handlers.DOCS_PATH_POLICY, "broken",
                        docs_handlers._DocsPathPolicy(root="", suffix=".txt"))
    with pytest.raises(RuntimeError, match="_PARSERS"):
        docs_handlers._validate_policy_tables()


def test_the_default_repo_has_a_path_policy():
    """הריפו שמוגש כשאיש לא נקב בריפו חייב להיות כזה שהכלי יודע לקרוא.

    בלי זה, פריסה שמנקה את ``MCP_DOCS_REPO`` הייתה מחזירה
    ``repo_not_configured`` על **כל** קריאה — כלומר הכלי מת בשקט
    בהגדרה שנראית כמו ברירת מחדל.
    """
    assert docs_handlers.DEFAULT_DOCS_REPO in docs_handlers.DOCS_PATH_POLICY


# ---- includes ----


def test_a_markdown_answer_carries_an_empty_includes_and_not_a_missing_field(both_repos):
    """``includes`` נשאר בתשובה, וב-Markdown הוא ריק.

    אפס כאן אינו "לא בדקנו" אלא "אין מה לבדוק" — ל-Markdown אין צורה
    של ``.. include::``. השמטת השדה הייתה שוברת קורא שכותב
    ``res["includes"]``, ומוסיפה מקום שלישי שבו סמנטיקת הסיומת חיה.
    """
    out = docs_handlers.docs_get_section(_TextBackend("# א\n"), path="x.md",
                                         repo="amir-bug-patterns")
    assert out["includes"] == []


def test_an_rst_answer_still_lists_its_includes():
    """ריצת הבקרה: בפורמט שיש לו הכללות, השדה עדיין מתמלא."""
    out = docs_handlers.docs_get_section(
        _TextBackend("א\n=\n\n.. include:: other.rst\n"), path="x.rst", repo="CodeBot")
    assert out["includes"] == ["other.rst"]


def test_the_page_states_the_validation_order_the_code_actually_runs():
    """העמוד אומר את סדר הפעולות שהקוד מריץ, ולא את ההפך ממנו.

    **הפרוזה כבר סטתה כאן פעם אחת, ולכן יש עליה שומר.** הניסוח הקודם אמר
    "הגבול נבדק כיחידת נתיב, **והנרמול קורה אחריו**" — כלומר הפוך מהקוד,
    שבו הסדר הוא עגינה ← נרמול ← גבול. זה לא ניסוח מסורבל אלא הפוך:
    קורא שיסמוך עליו ילמד שהנרמול אינו קודם לגבול, וה"תיקון" שינבע מזה
    הוא להקדים את ``normpath`` לעגינה — בדיוק מה שמגיש
    ``docs/../secrets``.

    **הסמן הוא הטענה ולא המשפט המלא**, כדי שמי שישפר סגנון לא יפיל את
    הטסט ומי שיהפוך את המשמעות כן. אותה צורה בדיוק כמו
    ``_SUGGESTION_RULE_SURFACES`` ב-``tests/test_mcp_server_build.py``,
    ומאותה סיבה.
    """
    page = (_ROOT / "docs" / "mcp-server.rst").read_text(encoding="utf-8")
    assert "עגינה, אחריה נרמול" in page, (
        "העמוד אינו אומר עוד שהנרמול בא אחרי העגינה ולפני הגבול")

    # ושהקוד עצמו עדיין מריץ את הסדר הזה — הפרוזה מתארת משהו, וזה הוא.
    order = inspect.getsource(docs_handlers._resolve_docs_path)
    anchor_at = order.index("policy.root and")
    norm_at = order.index("posixpath.normpath(p)")
    bound_at = order.index("_is_under(norm, policy.root)")
    assert anchor_at < norm_at < bound_at, (
        "סדר הפעולות בקוד השתנה, והעמוד מתאר את הישן")


# ===========================================================================
# תקרת אורך ל-``path`` — הקלט החיצוני היחיד כאן שלא הייתה עליו תקרה
# ===========================================================================


def test_a_path_over_the_ceiling_is_refused_before_the_secrets_policy_reads_it(
        monkeypatch, both_repos):
    """נתיב ארוך מדי נדחה בשלב 1, ו-``is_denied`` **אינו נקרא עליו כלל**.

    **זו הטענה, ולא "זה מהיר".** מה שהפך נתיב ארוך ליקר הוא ש-
    ``repo_policy.is_denied`` — ההוראה הראשונה ב-``RepoBackend.get_file``
    — סורקת כל רכיב בנתיב מול כל תבנית, כלומר עבודה שגדלה עם הקלט. נמדד
    לפני התקרה: נתיב של 400KB עלה 608ms לעומת 2.4ms לפני שסריקת הרכיבים
    נוספה. הדרך הדטרמיניסטית להוכיח שהמחיר נעלם היא שהפונקציה היקרה לא
    רצה, ולא שעון קיר — שהוא מדיד אבל מתעטש תחת עומס.

    ``RepoBackend`` אמיתי ומראה אמיתית, כי ``is_denied`` אינו נקרא
    מה-handler אלא מה-backend: דמה של backend לא הייתה מוכיחה דבר.

    **והנתיב פי שניים מהתקרה ולא תו אחד מעליה** — זו הבדיקה ש-
    ``silent-truncation-at-sink`` דורש: מה קורה לערך שגדול פי שניים
    מהתקרה, נדחה או נחתך בשקט.
    """
    from mcp_server import repo_backend, repo_policy

    seen: list[str] = []
    real = repo_policy.is_denied
    monkeypatch.setattr(repo_backend, "is_denied",
                        lambda p: (seen.append(p), real(p))[1])

    mirror = _CountingMirror()
    long_path = "docs/" + "a/" * docs_handlers.MAX_PATH_CHARS + "x.rst"
    assert len(long_path) > 2 * docs_handlers.MAX_PATH_CHARS

    out = docs_handlers.docs_get_section(_real_backend(mirror), path=long_path)

    assert out["ok"] is False and out["error"] == "path_too_long"
    assert seen == [], "הנתיב הארוך הגיע ל-is_denied — התקרה לא חסמה אותו"
    assert mirror.reads == [], "המראה נקראה על נתיב שנדחה"


def test_the_refusal_says_what_the_ceiling_is_and_what_was_sent(both_repos):
    """הסירוב נוקב בשני המספרים, אחרת הקורא אינו יודע כמה לקצר.

    ``blanket-policy-silent-block`` הוא בדיוק המקרה שבו מדיניות חוסמת
    ומבחוץ זה נראה כמו נתיב שגוי. קוד משלו **ועוד** שני המספרים הם מה
    שהופך את החסימה לגלויה.
    """
    be = _RecordingBackend()
    long_path = "x" * (docs_handlers.MAX_PATH_CHARS + 1) + ".rst"
    out = docs_handlers.docs_get_section(be, path=long_path)

    assert out["error"] == "path_too_long"
    assert out["max_chars"] == docs_handlers.MAX_PATH_CHARS
    assert out["actual_chars"] == len(long_path)
    assert out["error"] != "missing_path"  # לא מתחזה לנתיב שגוי
    assert be.kwargs == []


def test_the_longest_real_path_in_every_served_repo_is_far_under_the_ceiling():
    """התקרה אינה חוסמת אף קובץ אמיתי — נמדד, לא הונח.

    ``blanket-policy-silent-block`` דורש את המדידה הזאת לפני מדיניות
    שמרחיבה חסימה. הריפו הזה הוא היחיד שאפשר למדוד מכאן; המספרים לשתי
    המראות האחרות נמדדו ונכתבו ב-``MAX_PATH_CHARS``, והשומר כאן הוא על
    הסדר גודל: הכי ארוך שיש רחוק מהתקרה ולא צמוד לה.
    """
    import subprocess

    proc = subprocess.run(["git", "ls-files", "-z"], cwd=str(_ROOT),
                          capture_output=True, text=True)
    if proc.returncode != 0:
        pytest.skip("אין git או שזו אינה עבודה מגיט")
    paths = [p for p in proc.stdout.split("\0") if p]
    longest = max(len(p) for p in paths)
    assert longest * 4 < docs_handlers.MAX_PATH_CHARS, (
        f"הנתיב הארוך בריפו הוא {longest} תווים, והתקרה {docs_handlers.MAX_PATH_CHARS} "
        f"כבר אינה רחוקה ממנו — מדוד מחדש לפני שמשאירים אותה")


# ===========================================================================
# מספר השורה שהפארסר ייצר מגיע לקורא
# ===========================================================================


@pytest.mark.parametrize("text,kwargs,error,exc_type", [
    ("# א\nשורה\nרע\rזנב\n", {}, "inconsistent_line_endings",
     doc_sections.InconsistentLineEndings),
    ("\n\n".join(f"# H{i}" for i in range(40)), {"max_sections": 5},
     "too_many_sections", doc_sections.TooManySections),
])
def test_the_line_the_caller_gets_is_the_line_the_parser_produced(
        both_repos, monkeypatch, text, kwargs, error, exc_type):
    """המספר בתשובה **נגזר מהפארסר** ולא מוקלד בטסט.

    טסט שכותב ``assert out["line"] == 3`` מקבע מספר קסם: הוא יעבור גם
    אם ה-handler יחזיר קבוע, וייפול על כל שינוי לגיטימי בפארסר. כאן
    הפארסר מורץ תחילה כדי **לשאול אותו** מה המספר, ואז נבדק שאותו מספר
    בדיוק עבר דרך שתי שכבות אל הקורא.
    """
    with pytest.raises(exc_type) as raised:
        md_parser.parse_document(text, **kwargs)
    expected = raised.value.args[0]
    assert isinstance(expected, int) and expected > 0

    if kwargs:
        monkeypatch.setattr(
            docs_handlers._PARSERS[".md"], "parse_document",
            functools.partial(md_parser.parse_document, **kwargs))

    out = docs_handlers.docs_get_section(_TextBackend(text), path="x.md",
                                         repo="amir-bug-patterns")
    assert out["ok"] is False and out["error"] == error
    assert out["line"] == expected, "המספר בתשובה אינו זה שהפארסר ייצר"
    # וההקשר לא הלך לאיבוד בדרך — סירוב בלי קובץ אינו ניתן לפעולה.
    assert out["repo"] == "amir-bug-patterns" and out["path"] == "x.md"


def test_a_refusal_with_no_line_number_omits_the_field_instead_of_sending_null(
        both_repos, monkeypatch):
    """חריגה בלי ארגומנט אינה מפילה את הבקשה, ואינה שולחת ``line: null``.

    שדה שקיים תמיד מלמד את הקורא ש-``null`` הוא מצב אפשרי, והוא אינו.
    ובלי בדיקת הטיפוס ב-``_line_of``, ``args[0]`` על חריגה ריקה היה
    ``IndexError`` באמצע בקשה — כלומר 500 במקום סירוב.
    """
    def _bare(text, **k):
        raise doc_sections.TooManySections()

    monkeypatch.setattr(docs_handlers._PARSERS[".md"], "parse_document", _bare)
    out = docs_handlers.docs_get_section(_TextBackend("# א\n"), path="x.md",
                                         repo="amir-bug-patterns")
    assert out["error"] == "too_many_sections"
    assert "line" not in out


# ===========================================================================
# ההחלטה לתת ל-TypeError ול-RuntimeError לעבור — מקובעת, לא רק מנומקת
# ===========================================================================


@pytest.mark.parametrize("exc", [TypeError("חוזה נשבר"), RuntimeError("אסימון בלי map")])
def test_a_broken_contract_propagates_and_is_not_dressed_up_as_a_refusal(
        both_repos, monkeypatch, exc):
    """``TypeError`` ו-``RuntimeError`` עולים הלאה, ואינם הופכים לקוד סירוב.

    **ההחלטה הזאת מנומקת באריכות בהערה שמעל ה-``try`` ולא נשמרה בשום
    מקום.** מי שירחיב את ה-``except`` כדי להשתיק טסט נופל היה עובר CI,
    והופך חוזה שבור לסירוב שנראה תקין — זה ``widened-exception-scope``
    בצורתו המדויקת. הטסט הזה הוא מה שהופך את ההרחבה לכשל CI.

    ומה שהקורא מקבל בפועל נמדד ואינו הנחה: המסגרת ממירה חריגה שעולה
    ל-``ToolError`` מובנה, כלומר שגיאה נקייה ולא קריסה — ולכן ההחלטה
    לתת לה לעבור אינה מחיר ללקוח.
    """
    def _boom(text, **k):
        raise exc

    monkeypatch.setattr(docs_handlers._PARSERS[".md"], "parse_document", _boom)
    with pytest.raises(type(exc)):
        docs_handlers.docs_get_section(_TextBackend("# א\n"), path="x.md",
                                       repo="amir-bug-patterns")


# ===========================================================================
# שתי התקרות של שני המסלולים — מספר אחד, בשני מודולים, וטסט שמחזיק אותן שוות
# ===========================================================================


def test_the_two_section_ceilings_are_the_same_number():
    """``_ceiling.MAX_SYMBOLS`` ו-``doc_sections.MAX_SECTIONS`` הם אותו מספר.

    שני הפארסרים מקבלים את התקרה מברירת המחדל שלהם — ``MAX_SECTIONS`` של
    ``doc_sections``, אותו אובייקט בדיוק דרך שני הייצואים-מחדש — וסורק
    האאוטליין מ-``_ceiling.MAX_SYMBOLS``. שני מודולים, מספר אחד, בלי ייבוא
    ביניהם — זה ``duplicate-rule-second-copy`` §2 בצורתו המדויקת, והתיקון
    שהכלל מבקש כשהכפילות מוצדקת בגבול מודול הוא **טסט שקורא את שני
    המקורות ומשווה**. מה שנשען על השוויון: התיעוד שאומר "50,000 בשני
    המסלולים ובסורק", והמדידות ב-``_ceiling`` שקבעו את המספר לשניהם.
    """
    from mcp_server.outline_scanners import _ceiling

    assert rst_parser.MAX_SECTIONS is md_parser.MAX_SECTIONS is doc_sections.MAX_SECTIONS
    assert _ceiling.MAX_SYMBOLS == doc_sections.MAX_SECTIONS
