"""‏``md_parser`` מול cmark-gfm — טבלת אמת מחוללת, והקורפוס.

**האורקל הוא ספרייה אחרת בשפה אחרת.** ``cmarkgfm`` עוטף את cmark-gfm,
הפארסר ש-GitHub מריץ בפועל, והוא נקרא כאן ברינדור ל-HTML עם
``CMARK_OPT_SOURCEPOS`` — כלומר הרמה, מספר השורה, **וגם** התשובה על
"בתוך איזה מכל השורה הזאת יושבת" מגיעים ממנו ולא מסורק שכתבתי. הקובץ
הזה **אינו מייבא שום דבר מ-``md_parser``** מלבד ``parse_document``
עצמה, כי אורקל שגוזר את הציפייה מאותו מקור שהוא בודק אינו אורקל.

**והייבוא ישיר ולא ב-``importorskip``.** ``cmarkgfm`` נעוץ ב-
``requirements/development.txt``, ו-CI מתקין אותו; היעלמות שלו היא
הרגרסיה, לא סיבה לדלג בשקט. אותו נימוק שכתוב ב-
``tests/test_mcp_analytics_privacy.py`` על ``posthog``.

**למה טבלה מחוללת ולא קובץ סטטי.** כל 30 מופעי ה-``#``-שאינו-כותרת
בקורפוס יושבים בגדרות קוד — אפס בקוד מוזח, אפס בבלוקי HTML, אפס
ב-front matter. כלומר פארסר שימדל **מחלקת אזור אחת בלבד** יקבל 100%
על הקורפוס ויישבר על הקובץ הבא. הצורות המחוללות, ולא הקורפוס, הן
הראיה — והקורפוס הוא בדיקת שפיות עליהן.

**והחלוקה לכמה טסטים אינה קוסמטית:** ``pytest.ini`` קובע
``timeout = 60`` לכל טסט, וטבלה אחת גדולה הייתה מתקרבת לשם.
"""

from __future__ import annotations

import itertools
import re
from html.parser import HTMLParser
from pathlib import Path

import cmarkgfm
import pytest
from cmarkgfm.cmark import Options
from markdown_it import MarkdownIt
from mdit_py_plugins.front_matter import front_matter_plugin

from services.md_parser import parse_document

_CORPUS = Path(__file__).resolve().parent / "fixtures" / "md_corpus"

#: מכלים שכותרת בתוכם אינה סעיף במסמך. ``blockquote`` ו-``li`` הם מה
#: ש-cmark מסמן בפועל; ``level`` של ``markdown-it`` מתאר את אותו דבר
#: בדיוק, ונמדד: 0 ברמת המסמך, 1 בציטוט, 2 בפריט רשימה.
_CONTAINER_TAGS = frozenset({"blockquote", "li"})


class _HeadingCollector(HTMLParser):
    """כותרות מתוך ה-HTML ש-cmark-gfm מייצר, עם השורה והמכל שמעליהן."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.open_tags: list[str] = []
        self.headings: list[tuple[int, int, bool]] = []  # (רמה, שורה, בתוך מכל)

    def handle_starttag(self, tag, attrs):
        if tag in ("hr", "br", "img"):
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            source_pos = dict(attrs).get("data-sourcepos")
            assert source_pos, "cmark הורץ בלי CMARK_OPT_SOURCEPOS"
            line = int(source_pos.split(":", 1)[0])
            inside = any(t in _CONTAINER_TAGS for t in self.open_tags)
            self.headings.append((int(tag[1]), line, inside))
        self.open_tags.append(tag)

    def handle_endtag(self, tag):
        if tag in self.open_tags:
            # סגירה של התגית הפתוחה האחרונה מאותו שם
            del self.open_tags[len(self.open_tags) - 1 - self.open_tags[::-1].index(tag)]


#: הפארסר ששימש **אך ורק** כדי לאתר את גבול ה-front matter באורקל. זו
#: הספרייה עצמה ולא כלל שכתבתי, ולכן האורקל נשאר בלתי תלוי במימוש.
_FRONT_MATTER_PROBE = MarkdownIt("commonmark").use(front_matter_plugin).disable("inline")


def _without_front_matter(text: str) -> str:
    """מחזיר את הטקסט כשה-front matter הוחלף בשורות ריקות.

    **זו השכבה שחסרה ל-cmark-gfm, וזה נמדד ולא הונח.** GitHub מטפל
    ב-front matter בשכבה נפרדת **מעל** cmark, ולכן ההתנהגות של cmark
    לבדו על קובץ שפותח ב-``---`` אינה "מה ש-GitHub עושה": היא מה
    ש-GitHub עושה **אחרי** שהשכבה שמעליו כבר הסירה את הבלוק. בלי
    ההשלמה הזאת האורקל מדווח כותרת על שורה שיושבת בתוך ה-front matter
    — נמדד על ``---\n### רמה 3\n---\n``, שבו cmark לבדו מחזיר ``h3``
    בשורה 2.

    ההחלפה היא בשורות ריקות ולא במחיקה, כדי שמספרי השורות של כל
    השאר יישארו זהים — וזו בדיוק ההתאמה למה שהפארסר שנבדק רואה, שם
    התוסף בולע את הבלוק והשאר נשאר במקומו.
    """
    for token in _FRONT_MATTER_PROBE.parse(text, {}):
        if token.type == "front_matter" and token.map is not None:
            lines = text.split("\n")
            start, end = token.map
            return "\n".join([""] * (end - start) + lines[end:])
    return text


def _oracle_all_headings(text: str) -> list[tuple[int, int, bool]]:
    """כל הכותרות לפי cmark-gfm: (רמה, שורה, בתוך מכל)."""
    html = cmarkgfm.github_flavored_markdown_to_html(
        _without_front_matter(text), options=Options.CMARK_OPT_SOURCEPOS
    )
    collector = _HeadingCollector()
    collector.feed(html)
    collector.close()
    return collector.headings


def _oracle_sections(text: str) -> list[tuple[int, int]]:
    """‏(רמה, שורה) לכל כותרת **ברמת המסמך**."""
    return [(level, line) for level, line, inside in _oracle_all_headings(text) if not inside]


def _ours(text: str) -> list[tuple[int, int]]:
    return [(s.level, s.heading_line) for s in parse_document(text).sections]


def _compare(shapes) -> None:
    """מריץ את שני הצדדים על כל צורה, ומדווח את **כל** הפערים.

    לא ``assert`` בתוך הלולאה: פער יחיד היה מסתיר את השאר, ומספר
    הפערים הוא מה שמבדיל בין באג נקודתי למחלקה שלמה שנשברה.
    """
    mismatches = []
    for text in shapes:
        ours, theirs = _ours(text), _oracle_sections(text)
        if ours != theirs:
            mismatches.append((text, ours, theirs))
    assert not mismatches, (
        f"{len(mismatches)} אי-הסכמות מול cmark-gfm. הראשונות:\n"
        + "\n".join(
            f"  קלט={text!r}\n    שלנו={ours}\n    cmark={theirs}"
            for text, ours, theirs in mismatches[:5]
        )
    )


# ════════════════════════════════════════════════════════════════════
# אוצר השורות — הצורות מהמדידה, כולל כאלה שאין להן מופע בקורפוס
# ════════════════════════════════════════════════════════════════════

_RLM = "‏"

_PREVIOUS_LINES = [
    "",
    "טקסט רגיל",
    "# כותרת קודמת",
    "> ציטוט",
    "- פריט",
    "```",
    "~~~",
    "    קוד מוזח",
    "\tקוד בטאב",
    "| a | b |",
    "|---|---|",
    "---",
    "===",
    ":::",
    "<div>",
]

_FOCUS_LINES = [
    "# רמה 1",
    "## רמה 2",
    "### רמה 3",
    "#### רמה 4",
    "##### רמה 5",
    "###### רמה 6",
    "####### שבע סולמיות",
    "#בלי רווח",
    "## סולמית סוגרת ##",
    "###",
    f"## {_RLM}כותרת עם RLM",
    "## כותרת עם `בקטיקים`",
    "## **מודגש**",
    "## [קישור](https://example.com)",
    "## כותרת עם \\# escape",
    "טקסט שעשוי להיות setext",
    "---",
    "===",
    "```",
    "```python",
    "~~~",
    ":::",
    "\tכותרת בטאב",
    "    # כותרת מוזחת",
    "> # כותרת בציטוט",
    "- # כותרת בפריט",
    "<div>",
    "<!-- הערה -->",
]

_NEXT_LINES = [
    "",
    "===",
    "---",
    "טקסט אחרי",
    "# כותרת אחרי",
    "```",
    "    קוד מוזח",
    "\tקוד בטאב",
    "|---|---|",
    ":::",
    "<div>",
    "</div>",
    "> ציטוט אחרי",
]

_ENDINGS = ["\n", ""]


def _context_shapes():
    for previous, focus, following, ending in itertools.product(
        _PREVIOUS_LINES, _FOCUS_LINES, _NEXT_LINES, _ENDINGS
    ):
        yield f"{previous}\n{focus}\n{following}{ending}"


@pytest.mark.parametrize("bucket", range(6))
def test_the_context_matrix_agrees_with_cmark(bucket):
    """המכפלה הקרטזית: שורה קודמת × שורת מוקד × שורה עוקבת × צורת סיום.

    מחולקת לשישה דליים כדי שאף טסט לא יתקרב לתקרת הזמן של ``pytest``.
    """
    shapes = [s for i, s in enumerate(_context_shapes()) if i % 6 == bucket]
    assert len(shapes) > 500, "הטבלה התכווצה — זו רגרסיה בכיסוי"
    _compare(shapes)


# ════════════════════════════════════════════════════════════════════
# קינון גדרות — השורש של הבאג האמיתי שנמצא בקורפוס
# ════════════════════════════════════════════════════════════════════

def _fence_nesting_shapes():
    """חיצונית × פנימית × הזחות × תו, ואחרי כל אחת כותרות.

    **הצורה שמכילה את הבאג:** גדר פנימית עם שם שפה ובאותו אורך
    כחיצונית. היא אינה יכולה לסגור — לסוגרת אסור שיהיה טקסט אחריה —
    ולכן ה-``\\`\\`\\``` הבא סוגר דווקא את ה**חיצונית**, ומשם הזוגיות
    הפוכה עד סוף הקובץ. זו בדיוק המחלקה שלא הייתה בטבלה של הסבב
    הראשון.
    """
    for outer_len, inner_len, inner_indent, closing_indent, char in itertools.product(
        (3, 4, 5), (3, 4, 5), (0, 2, 3, 4), (0, 3), ("`", "~")
    ):
        outer, inner = char * outer_len, char * inner_len
        pad, close_pad = " " * inner_indent, " " * closing_indent
        for inner_info in ("", "python"):
            yield (
                f"{outer}\n"
                f"{pad}{inner}{inner_info}\n"
                f"code\n"
                f"{close_pad}{inner}\n"
                f"{outer}\n"
                f"\n## אחרי\n"
                f"\n### עמוק יותר\n"
            )


@pytest.mark.parametrize("bucket", range(2))
def test_fence_nesting_agrees_with_cmark(bucket):
    shapes = [s for i, s in enumerate(_fence_nesting_shapes()) if i % 2 == bucket]
    assert len(shapes) > 100, "טבלת הקינון התכווצה"
    _compare(shapes)


def test_a_fence_with_a_language_name_cannot_close_its_own_block():
    """המקרה הבודד שהיה באג אמיתי בקובץ בריפו, מקובע בנפרד.

    בלי הצורה הזאת בטבלה, שמונה שורות שנראות בדיוק כמו כותרות סעיף
    נבלעות בתוך בלוק קוד — ופארסר שמציג אותן היה מראה סעיפים
    ש-GitHub מסתיר.
    """
    text = "```\n```python\ncode\n```\n\n## נבלעת?\n"
    assert _ours(text) == _oracle_sections(text)


# ════════════════════════════════════════════════════════════════════
# בלוקי HTML — צמודים ומופרדים
# ════════════════════════════════════════════════════════════════════

def _html_shapes():
    """שש תגיות, צמודות ומופרדות, עם ובלי מאפיינים, והכותרת בשלושה מקומות.

    ``span`` ו-``unknown-tag`` כאן בכוונה: הן אינן ברשימת התגיות של
    CommonMark, ולכן הן נופלות למחלקת בלוק ה-HTML מסוג 7 — שהיא זו
    שדורשת שורה ריקה לפניה. ההבדל בין "צמוד" ל"מופרד" הוא בדיוק מה
    שמפעיל או מכבה את המחלקה הזאת.
    """
    tags = ("div", "details", "table", "p", "span", "unknown-tag")
    for tag, attributes, blank_before, blank_inside, position, blank_before_close in (
        itertools.product(
            tags, ("", ' class="x"'), (True, False), (True, False),
            ("inside", "after", "both"), (True, False),
        )
    ):
        opening = f"<{tag}{attributes}>"
        gap_before = "\n" if blank_before else ""
        gap_inside = "\n" if blank_inside else ""
        gap_close = "\n" if blank_before_close else ""
        body = "## בתוך הבלוק\n" if position in ("inside", "both") else "טקסט\n"
        tail = "\n## אחרי הבלוק\n" if position in ("after", "both") else ""
        yield (
            f"# לפני\n{gap_before}"
            f"{opening}\n{gap_inside}"
            f"{body}{gap_close}"
            f"</{tag}>\n"
            f"{tail}"
        )


_HTML_EDGE_CASES = [
    "<div>\n## בלי סגירה\n",
    "<!-- הערה -->\n\n## אחרי הערה\n",
    "<!-- הערה\nרב-שורתית -->\n## צמוד להערה\n",
    "<?php echo 1; ?>\n\n## אחרי processing instruction\n",
    "<div>\n\n## בלוק שנסגר בשורה ריקה\n",
]


def test_html_blocks_agree_with_cmark():
    _compare(list(_html_shapes()) + _HTML_EDGE_CASES)


# ════════════════════════════════════════════════════════════════════
# מכלים — cmark רואה את הכותרת, המפה שלנו לא
# ════════════════════════════════════════════════════════════════════

_CONTAINER_SHAPES = [
    "## לפני\n\n> ## בתוך ציטוט\n\n## אחרי\n",
    "## לפני\n\n- ## בתוך פריט\n\n## אחרי\n",
    "## לפני\n\n> > ## ציטוט בתוך ציטוט\n\n## אחרי\n",
    "## לפני\n\n1. ## בתוך פריט ממוספר\n\n## אחרי\n",
    "## לפני\n\n- - ## פריט בתוך פריט\n\n## אחרי\n",
    "> ## ציטוט בלבד\n",
]


@pytest.mark.parametrize("text", _CONTAINER_SHAPES)
def test_a_heading_inside_a_container_is_seen_by_cmark_and_excluded_by_us(text):
    """הסינון הוא חלק מההשוואה, לא חריגה ממנה.

    האורקל **כן** מזהה את הכותרת — היא כותרת, ו-GitHub מרנדר אותה —
    ולכן הטסט דורש את שני הדברים יחד: שהיא קיימת אצלו כשהיא בתוך מכל,
    ושהיא אינה במפה שלנו.
    """
    all_headings = _oracle_all_headings(text)
    assert any(inside for _lvl, _line, inside in all_headings), "הצורה אינה מכילה מכל"
    assert _ours(text) == _oracle_sections(text)


# ════════════════════════════════════════════════════════════════════
# הקורפוס
# ════════════════════════════════════════════════════════════════════

def _corpus_files():
    """תיקייה שקיימת ומחזירה אפס קבצים היא כישלון, לא דילוג.

    אותו כלל בדיוק כמו ``_rst_files`` ב-``tests/test_rst_parser.py``:
    טסט קורפוס שמדלג בשקט הוא טסט שלא רץ אף פעם.
    """
    assert _CORPUS.is_dir(), f"תיקיית הקורפוס חסרה: {_CORPUS}"
    # ``README.md`` שבתיקייה מתאר את הקורפוס ואינו חלק ממנו.
    files = sorted(p for p in _CORPUS.rglob("*.md") if p.name != "README.md")
    assert len(files) >= 8, f"רק {len(files)} קבצים תחת {_CORPUS}"
    return files


@pytest.mark.parametrize("path", _corpus_files(), ids=lambda p: p.name)
def test_every_corpus_file_matches_cmark(path):
    """רמה ומספר שורה זהים ל-cmark-gfm, בכל כותרת בכל קובץ."""
    text = path.read_text(encoding="utf-8")
    assert _ours(text) == _oracle_sections(text)


def test_the_corpus_covers_the_shapes_it_was_chosen_for():
    """הקורפוס נבחר לפי צורות, ולא לפי גודל — וזה נאכף.

    בלי הטסט הזה, קובץ שיוחלף בעתיד יכול להוציא מחלקה שלמה מהכיסוי
    בלי שאיש יראה.
    """
    texts = {path.name: path.read_text(encoding="utf-8") for path in _corpus_files()}
    everything = "\n".join(texts.values())
    assert "‏" in everything, "אין RLM באף קובץ"
    assert any("````" in text for text in texts.values()), "אין קינון גדרות"
    assert any(
        re.match(r"^[ ]{1,3}(```|~~~)", line)
        for text in texts.values()
        for line in text.split("\n")
    ), "אין גדר מוזחת"
    assert sum(text.count("\n## K1") for text in texts.values()) > 0, "אין מזהים"
    assert any("`" in line for text in texts.values()
               for line in text.split("\n") if line.startswith("#")), "אין בקטיקים בכותרות"
    total_headings = sum(len(_oracle_sections(text)) for text in texts.values())
    assert total_headings > 200, f"רק {total_headings} כותרות בקורפוס"
