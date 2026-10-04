"""‏``md_parser`` מול cmark-gfm — טבלת אמת מחוללת.

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

**למה טבלה מחוללת ולא קורפוס של קבצים אמיתיים.** נמדד על
``amir-bug-patterns``: כל 30 מופעי ה-``#``-שאינו-כותרת שם יושבים בגדרות
קוד — אפס בקוד מוזח, אפס בבלוקי HTML, אפס ב-front matter. כלומר פארסר
שימדל **מחלקת אזור אחת בלבד** יקבל 100% על קורפוס אמיתי ויישבר על
הקובץ הבא. הצורות המחוללות הן הראיה.

**ומה שהקובץ הזה אינו עושה, כדי שזה לא ייקרא כהשמטה:** הוא **אינו משווה
מפה של אף קובץ אמיתי**. זו החלטה. קורפוס אמיתי הוא בדיקת שפיות חד-פעמית
ולא רשת שתופסת רגרסיה עתידית, והוא היה דורש להחזיק בריפו הזה עותק של
תוכן שאינו שלו. ההרצה על קורפוס אמיתי נעשית על פי דרישה, עם
``scripts/compare_md_parser_to_cmark.py`` — לפני שלב 2, אחרי שדרוג של
``markdown-it-py``, וכשנוגעים בפארסר. **החריג היחיד, וצר:** עמודי ה-``.md``
תחת ``docs/`` של הריפו הזה נסרקים — לא להשוואת מפה, אלא לשורות שמפעילות
את אחד הפערים הידועים (``_divergence_trigger_lines``). הם בריפו, ולכן אין
כאן עותק של תוכן זר.

**מה בדיוק מושווה, כדי שהתוצאה לא תיקרא רחבה ממה שהיא.** ההשוואה
הראשית — ``_compare`` — היא על **הרמה ומספר השורה** של כל כותרת ברמת
המסמך, ולא על טקסט הכותרת. "אפס אי-הסכמות" היא לכן טענה על **גבולות**:
היכן מתחיל סעיף ואיזו רמה הוא. טקסט הכותרת מושווה בנפרד, ב-
``_compare_titles``, ורק על תת-קבוצה — ההנמקה שם.

**ולטענה יש חריגים ידועים, והם מקובעים ולא מושתקים — בטבלה אחת,**
``_KNOWN_DIVERGENCES``. כל שורה שם היא **סיבה** ולא רשימת מופעים, ולצידה
המשפחה שנמדדה עליה. הצורות החולקות **אינן** עוברות ב-``_compare`` — הן עוברות
בטסט שמאשר את הפער המדוד, צורה-צורה. לכל שורה בטבלה: הסיבה, צורה לדוגמה ומה
כל צד מחזיר עליה, על מה ומתי נמדדה, וקישור ל-upstream כשיש. ``docs/mcp-server.rst``
מעתיק ממנה, ו-``test_the_documentation_table_is_this_table`` משווה בכל שורה את
הסיבה, את "N מתוך M", את הגרסאות והתאריך ואת הקישור — **לא** את מה שכל צד
מחזיר; את זה בודקות הדוגמאות עצמן, מול שני הפארסרים.

**והחלוקה לכמה טסטים אינה קוסמטית:** ``pytest.ini`` קובע
``timeout = 60`` לכל טסט, וטבלה אחת גדולה הייתה מתקרבת לשם.
"""

from __future__ import annotations

import collections
import itertools
import re
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

import cmarkgfm
import pytest
from cmarkgfm.cmark import Options
from markdown_it import MarkdownIt
from markdown_it.common.html_blocks import block_names as _MARKDOWN_IT_BLOCK_TAGS
from mdit_py_plugins.front_matter import front_matter_plugin

from services.md_parser import parse_document

#: הקובץ כולו במסלול ``md-heavy`` של ``unit-tests`` ב-``.github/workflows/ci.yml``: הוא
#: מפרסר את משפחות הצורות של האורקל בשני הפארסרים, כולל טבלאות בתקרת ההשלמה של
#: ``markdown-it-py``. הסימון מוגדר ב-``pytest.ini``.
pytestmark = pytest.mark.md_heavy

_REPO = Path(__file__).resolve().parents[1]

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
        # ‏**רשימה מקבילה ולא שדה רביעי בטאפל.** ``headings`` נצרך בשלושה
        # מקומות שמפרקים אותו לשלושה, והרחבה שם הייתה גוררת את כולם בלי
        # שהטקסט מעניין אף אחד מהם. כאן האינדקסים מקבילים, וזה כל הקשר.
        self.texts: list[str] = []
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("hr", "br", "img"):
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            source_pos = dict(attrs).get("data-sourcepos")
            assert source_pos, "cmark הורץ בלי CMARK_OPT_SOURCEPOS"
            line = int(source_pos.split(":", 1)[0])
            inside = any(t in _CONTAINER_TAGS for t in self.open_tags)
            self.headings.append((int(tag[1]), line, inside))
            self.texts.append("")
            self._depth = 1
        elif self._depth:
            # תגית שנפתחה **בתוך** הכותרת — ``<code>``, ``<em>``, ``<a>``.
            # הטקסט שלה נאסף כמו כל טקסט אחר, אבל הסימון שהוליד אותה
            # כבר אבד, ובדיוק לכן הכותרות האלה מוחרגות מהשוואת הטקסט.
            self._depth += 1
        self.open_tags.append(tag)

    def handle_data(self, data):
        if self._depth:
            self.texts[-1] += data

    def handle_endtag(self, tag):
        # אותה החרגה כמו בפתיחה, ומאותה סיבה: ``<br>`` מגיע כ-
        # ``handle_startendtag``, כלומר פתיחה **וסגירה** — בלי ההחרגה
        # הזאת הוא היה מוריד את המונה בלי שהעלה אותו.
        if tag in ("hr", "br", "img"):
            return
        if self._depth:
            self._depth -= 1
        if tag in self.open_tags:
            # סגירה של התגית הפתוחה האחרונה מאותו שם
            del self.open_tags[len(self.open_tags) - 1 - self.open_tags[::-1].index(tag)]


#: פארסר עזר לשתי שאלות מבניות בלבד, ולא למפה עצמה: איפה נגמר ה-front
#: matter (בשביל האורקל, ``_without_front_matter``), ואיפה יושבים אזורי קוד
#: (בשביל סריקת הטריגרים, ``_divergence_trigger_lines``). זו הספרייה עצמה
#: ולא כלל שכתבתי, ולכן האורקל נשאר בלתי תלוי במימוש — ואין שני מופעים
#: באותה תצורה בקובץ הזה.
_BLOCK_PROBE = MarkdownIt("commonmark").use(front_matter_plugin).disable("inline")


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
    for token in _BLOCK_PROBE.parse(text, {}):
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
    """‏(רמה, שורה) לכל סעיף — **בלי תקרת השורות ותקרת הטוקנים**, בכוונה (#3391).

    האורקל שואל איך הפרסר מבין את הטקסט, והתקרות הן מדיניות משאבים: הן קובעות
    אם הכלי מפרסר קובץ בכלל, ולא מה הוא רואה בו. השוואה עם התקרות הייתה הופכת את
    משפחת השורה השלישית ב-``_KNOWN_DIVERGENCES`` לסירוב מול כותרות, ומסתירה את
    הפער שהיא מתעדת. מה שהכלי עושה עם אותן צורות — מסרב לכולן — נבדק לחוד, ב-
    ``test_the_table_cap_gap_is_unreachable_through_the_tool``. ``max_sections``
    נשארת על ברירת המחדל, כמו בכלי: היא אינה נוגעת באף צורה כאן.
    """
    doc = parse_document(text, max_lines=None, max_tokens=None)
    return [(s.level, s.heading_line) for s in doc.sections]


#: תווים שפותחים סימון פנימי ב-CommonMark, או שמייצגים משהו שעבר
#: רינדור בדרך ל-HTML. כותרת שהמקור שלה נקי מכולם חוזרת מ-cmark
#: **כטקסט זהה**, ולכן אפשר להשוות אותה מילה במילה.
_INLINE_MARKUP = frozenset("`*_[]<>&\\")


def _has_inline_markup(title: str) -> bool:
    return any(ch in _INLINE_MARKUP for ch in title)


def _oracle_titles(text: str) -> list[tuple[int, int, str]]:
    """‏(רמה, שורה, **טקסט**) לכל כותרת ברמת המסמך, לפי cmark-gfm."""
    collector = _HeadingCollector()
    collector.feed(
        cmarkgfm.github_flavored_markdown_to_html(
            _without_front_matter(text), options=Options.CMARK_OPT_SOURCEPOS
        )
    )
    collector.close()
    return [
        (level, line, title)
        for (level, line, inside), title in zip(collector.headings, collector.texts)
        if not inside
    ]


def _compare_titles(shapes) -> int:
    """משווה את **טקסט** הכותרת, ורק על הכותרות שאפשר להשוות.

    **למה בכלל תת-קבוצה, ולא כל הכותרות.** אצלנו ``title`` הוא המקור
    הגולמי כפי שנכתב בקובץ — ``inline`` מכובה, ולכן ``` `code` ``` נשאר
    ``` `code` ```. מ-cmark חוזר **HTML מרונדר**, ושם אותה כותרת היא
    ``<code>code</code>``; אחרי שמסירים את התגיות נשאר ``code``, בלי
    הבקטיקים. השוואה ישירה בין השניים הייתה נכשלת על כל כותרת שיש בה
    סימון — לא כי מישהו טועה, אלא כי הם מתארים שני דברים שונים. לכן
    מושווה רק מה שאין בו סימון פנימי בכלל, ושם **אין** למה להיות פער.

    **וזו פונקציה נפרדת ולא הרחבה של** ``_ours``/``_oracle_sections``.
    הטאפל ``(רמה, שורה)`` שלהן נצרך בשישה מקומות ובסקריפט ההשוואה
    החיצוני; הרחבה שלו הייתה גוררת את כולם בשביל שדה שרובם אינם
    בודקים.

    :returns: כמה כותרות באמת הושוו. המתקשר מוודא שזה אינו אפס — "אפס
        אי-הסכמות" על אפס השוואות הוא אישור שקרי, אותו נימוק שכתוב
        ב-``scripts/compare_md_parser_to_cmark.py`` על ריצה בלי קבצים.
    """
    compared = 0
    mismatches = []
    for text in shapes:
        ours = [(s.level, s.heading_line, s.title) for s in parse_document(text).sections]
        theirs = _oracle_titles(text)
        # **לא ``continue`` על פער מיקום.** הצורות האלה הן אותן צורות
        # ש-``_compare`` כבר מאשר עליהן הסכמה מלאה על רמה ושורה, ולכן
        # פער כאן פירושו שמשהו אחר נשבר — ודילוג שקט היה מסתיר אותו.
        assert [(lvl, ln) for lvl, ln, _ in ours] == [
            (lvl, ln) for lvl, ln, _ in theirs
        ], f"פער מיקום שאמור להיתפס ב-_compare: {text!r}"
        for (lvl, line, mine), (_, _, rendered) in zip(ours, theirs):
            if _has_inline_markup(mine):
                continue
            compared += 1
            if mine != rendered:
                mismatches.append((text, mine, rendered))
    assert not mismatches, (
        f"{len(mismatches)} כותרות שטקסטן נבדל מ-cmark-gfm. הראשונות:\n"
        + "\n".join(
            f"  קלט={text!r}\n    שלנו={mine!r}\n    cmark={rendered!r}"
            for text, mine, rendered in mismatches[:5]
        )
    )
    return compared


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
# טבלאות — המחלקה שהמטריצה למעלה אינה מייצרת
# ════════════════════════════════════════════════════════════════════
#
# **למה משפחה נפרדת ולא עוד שורה באוצר המילים.** טבלה היא **שתי שורות
# צמודות** — שורת תאים ומיד אחריה שורת מפריד — והמטריצה למעלה בונה כל
# צורה משורה קודמת, שורת מוקד ושורה עוקבת, ולכן היא לעולם אינה מציבה
# את השתיים זו אחרי זו. זה בדיוק החור שדרכו עברה רגרסיה אמיתית: בלי
# ``enable("table")`` הטבלה היא פסקה, ו-``---`` שאחריה הופך אותה לכותרת
# setext.


def _table_shapes():
    """טבלה × מה שבא אחריה × האם יש שורת גוף, ואחריה כותרת."""
    followers = ("---", "===", "", "## כותרת אחרי", "text", "|---|---|", "-")
    for follower, with_body, blank_before in itertools.product(
        followers, (True, False), (True, False)
    ):
        body = "| 1 | 2 |\n" if with_body else ""
        gap = "\n" if blank_before else ""
        tail = f"{follower}\n" if follower else ""
        yield f"## לפני\n\n| a | b |\n|---|---|\n{body}{gap}{tail}\n## הסעיף הבא\n"


def test_tables_agree_with_cmark():
    shapes = list(_table_shapes())
    assert len(shapes) > 20, "טבלת הטבלאות התכווצה"
    _compare(shapes)


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
# הפערים הידועים מ-GitHub — משפחה לכל שורה, טבלה אחת (``_KNOWN_DIVERGENCES``)
# ════════════════════════════════════════════════════════════════════
#
# כל פער ידוע יושב בשורה אחת בטבלה שלמטה, והיא המקור: ``docs/mcp-server.rst``
# (:ref:`mcp-md-known-divergences`) מעתיק ממנה, וטסט משווה ביניהן. מעל הטבלה —
# משפחת הצורות של כל שורה, כלומר מה שבאמת נמדד.
#
# ─── שורה 1: תגית HTML מסוג 7 צמודה לשורת מכל (פריט רשימה או ציטוט) ───

#: תגיות שאינן ברשימת ה-block של CommonMark ולכן נופלות ל**סוג 7**: תג
#: פתיחה שלם (לא ``pre``/``script``/``style``/``textarea``) או תג סגירה
#: שלם, לבדו בשורה. ``</pre>`` הוא סוג 7 כי הוא **סגירה**: הכלל של סוג 1
#: תופס רק פתיחה.
_TYPE7_TAGS = ("<br>", "<span>", "</pre>", '<img src="x">')
#: שורת המכל שהתגית צמודה אליה. **הציטוט הגיע מהתגובה באישו ה-upstream**
#: ולא מהמדידה המקורית, שכיסתה רק רשימות — ונמדד שהוא מתנהג **זהה**
#: לשני סמני הרשימה: צמוד = פער באותה צורה בדיוק, מופרד = הסכמה. כלל
#: הציטוט של ``markdown-it`` מסמן המשכים לא-בדוקים בהזחה שלילית, ולכן
#: תיקון upstream שיבדוק רק רשימות לא יכסה אותו — וזו סיבה נוספת
#: שהמחלקה מוגדרת כ"מכל" ולא כ"פריט".
_CONTAINER_MARKERS = ("- ", "1. ", "> ")

#: שני מקרי גבול **מסכימים** מהדיון ב-upstream, מקובעים כלשונם: תגית
#: מסוג 7 מוזחת ארבעה רווחים נשארת בפסקת הפריט — בשלושת המימושים —
#: גם כשיש שני אבות. תיקון נאיבי ב-``markdown-it`` (לאפשר סיום סוג 7
#: בכל פעם ש-``sCount < blkIndent``) שובר בדיוק את אלה, ולכן הם
#: יושבים כאן: אם ספרייה עתידית תסטה בהם, ``_compare`` יתפוס אצלנו
#: לפני שמישהו יבחין ברינדור.
_TYPE7_INDENTED_AGREEING = [
    "-    a\n    <br>\n## Next\n",
    "100. a\n     - b\n    <br>\n## Next\n",
]


def _type7_after_container_shapes():
    """‏(טקסט, האם שני הפארסרים מסכימים) — תגית מסוג 7 אחרי שורת מכל.

    **זו השורה הראשונה ב-``_KNOWN_DIVERGENCES``**, והיא נמדדה: כשהתגית
    **צמודה** לשורת המכל — פריט רשימה או ציטוט — ``markdown-it`` (הפורט
    ל-Python **וגם** המקור ב-JS, 14.3.2 — נמדד, הפורט נאמן) רואה בה
    המשך עצל של פסקת המכל, ולכן ``## אחרי`` שאחריה הוא כותרת; cmark-gfm
    סוגר את המכל, פותח בלוק HTML, והבלוק בולע את ``## אחרי`` עד שורה
    ריקה. **מימוש הייחוס של המפרט** (``commonmark.py`` 0.9.2, פורט של
    commonmark.js) מסכים עם cmark — כלומר זו סטייה של ``markdown-it``
    ולא שלנו, ולא של GitHub.

    עם **שורה ריקה** בין המכל לתגית שני הצדדים מסכימים, וזה מה שהופך
    את החצי הזה למקרה בקרה: הוא עובר ב-``_compare`` כמו כל משפחה אחרת.
    ובאותו מעמד ``_TYPE7_INDENTED_AGREEING`` — התגית מוזחת לתוך הפריט.

    **ולמה זה לא מתוקן אצלנו.** התיקון המתבקש — להפוך את דגל
    ה-terminate של סוג 7 ב-``rules_block/html_block.py`` — נמדד ונדחה:
    הוא גורם ל-``<br>`` להפריע לפסקה גם **בלי** רשימה, ושם שני הצדדים
    מסכימים היום. כלומר הוא מחליף אי-הסכמה אחת באחרת. התיקון הנכון
    הוא בדיקה מודעת-מכל כמו של cmark, והוא שייך ל-``markdown-it-py``
    ולא לכלל שנכתוב ביד. **מתועד upstream:** executablebooks/markdown-it-py#434
    (https://github.com/executablebooks/markdown-it-py/issues/434) — הצורה
    המינימלית, שלושת המימושים, והמנגנון. התגובה הראשונה שם הביאה את
    שלושת מקרי הגבול שמקובעים כאן: הציטוט (הצטרף למחלקה המוחרגת) ושתי
    הצורות המוזחות (``_TYPE7_INDENTED_AGREEING``). ביום שהאישו ייסגר
    בתיקון, ``test_a_type7_tag_glued_to_a_container_still_disagrees_as_measured``
    ייפול על הגרסה החדשה — וזה הסימן למחוק את ההחרגה, לא להרפות אותו.

    **ובקבצים אמיתיים — אפס מופעים, במדידה ולא בטסט.** לשורה הזאת אין טריגר (הנימוק
    ליד השורה ב-``_KNOWN_DIVERGENCES``), ולכן מה שתופס אותה בקובץ אמיתי הוא השוואת
    המפות של ``scripts/compare_md_parser_to_cmark.py``: אפס אי-הסכמות בכל קורפוס שנמדד.
    המספרים, הקומיט והתאריך כתובים במקום אחד, ב-:ref:`mcp-md-known-divergences`.
    """
    for tag, marker, adjacent in itertools.product(
        _TYPE7_TAGS, _CONTAINER_MARKERS, (True, False)
    ):
        gap = "" if adjacent else "\n"
        yield f"## לפני\n\n{marker}פריט\n{gap}{tag}\n## אחרי\n", not adjacent


def test_the_type7_family_agrees_when_a_blank_line_separates_it():
    """חצי הבקרה של המשפחה עובר דרך אותה ``_compare`` כמו כולם.

    ואיתו שני מקרי הגבול המוזחים — הם מסכימים היום, וזה מה שנטען.
    """
    agreeing = [text for text, agrees in _type7_after_container_shapes() if agrees]
    assert len(agreeing) == len(_TYPE7_TAGS) * len(_CONTAINER_MARKERS)
    _compare(agreeing + _TYPE7_INDENTED_AGREEING)


@pytest.mark.parametrize(
    "text", [text for text, agrees in _type7_after_container_shapes() if not agrees]
)
def test_a_type7_tag_glued_to_a_container_still_disagrees_as_measured(text):
    """**הטסט הזה מקבע פער מדוד, ולא התנהגות רצויה.**

    אצלנו שני סעיפים — ``## לפני`` ו-``## אחרי`` — ואצל cmark-gfm אחד,
    כי ``## אחרי`` נבלע לתוך בלוק ה-HTML. הצורה המדויקת נטענת כאן
    בשני הצדדים, כדי שהפער לא יוכל להיסחף לכיוון שלישי בשקט.

    .. warning::

       **נפילה של הטסט הזה היא תוצאה מכוונת**, ופירושה ש-``markdown-it``
       תיקנה את ההתנהגות (או ש-cmark שינתה את שלה). אז הצורה הזאת
       עוברת לחצי המסכים של המשפחה, והשורה שלה ב-``_KNOWN_DIVERGENCES``
       — ובסעיף :ref:`mcp-md-known-divergences` בתיעוד — מתעדכנת יחד
       איתה. אל "תתקן" את הטסט הזה כאילו היה באג.
    """
    ours, theirs = _ours(text), _oracle_sections(text)
    assert theirs == [(2, 1)], ("cmark-gfm שינה את התנהגותו", text, theirs)
    assert [lvl for lvl, _ in ours] == [2, 2] and ours[0] == (2, 1), (
        "markdown-it שינה את התנהגותו — ראו את האזהרה", text, ours,
    )


def test_the_excluded_class_is_exactly_the_glued_shapes_and_nothing_more():
    """ההחרגה נאמרת בקול: מה שלא נכנס ל-``_compare`` — ולמה.

    כמו ``compared > 100`` ב-``_compare_titles``: החרגה שקטה יכולה
    להתרחב בלי שאיש ישים לב. כאן נטען שהקבוצה המוחרגת היא **בדיוק**
    הצורות הצמודות, לא ריקה ולא רחבה מזה — ושכל אחת מהן באמת חלוקה,
    כלומר ההחרגה מוצדקת מופע-מופע ולא כהנחה.
    """
    excluded = [text for text, agrees in _type7_after_container_shapes() if not agrees]
    # תגיות × מכלים — כל תגית מול כל מכל, ורק הצורה הצמודה של כל זוג.
    assert len(excluded) == len(_TYPE7_TAGS) * len(_CONTAINER_MARKERS)
    # שורת המכל היא תמיד ``<סמן>פריט``, גם לציטוט (``> פריט``), ולכן
    # הפיצול על ``"פריט\n"`` תופס את מה שבין שורת המכל לכותרת שאחריה.
    assert all("\n\n" not in text.split("פריט\n", 1)[1].split("\n## אחרי")[0] for text in excluded), (
        "צורה מופרדת נכנסה לקבוצה המוחרגת"
    )
    for text in excluded:
        assert _ours(text) != _oracle_sections(text), ("מוחרגת אבל מסכימה — ההחרגה רחבה מדי", text)


def _type7_family():
    """כל מה שנמדד בשורה של סוג 7: המשפחה הצמודה/המופרדת, ושני מקרי הגבול המוזחים."""
    yield from _type7_after_container_shapes()
    for text in _TYPE7_INDENTED_AGREEING:
        yield text, True


# ─── שורה 2: רשימת תגיות הבלוק של CommonMark 0.31.2 — source/search ───

#: שתי התגיות שרשימת תגיות הבלוק שינתה ב-CommonMark 0.31: ``source`` יצאה
#: ממנה ("Remove `source` element as HTML block start condition" ב-changelog
#: של המפרט), ו-``search`` נמצאת בה (תנאי פתיחה 6 ב-
#: https://spec.commonmark.org/0.31.2/#html-blocks — נקרא ב-2026-09-27).
#: ``markdown-it-py`` עובד לפי הרשימה הזאת מאז 4.0.0 ("Comply with Commonmark
#: 0.31.2", #362; ``markdown_it/common/html_blocks.py`` ב-4.2.0), ו-cmark-gfm —
#: הפארסר ש-GitHub מריץ — לפי הקודמת. שם שיושב ברשימה פותח בלוק HTML מסוג 6;
#: שם שאינו בה יכול לפתוח רק סוג 7.
_BLOCK_TAG_LIST_TAGS = ("source", "search")

#: צורות הכתיבה של שורת התגית: ``{t}`` הוא השם, ``{T}`` השם באותיות גדולות.
#: ההבחנה שמכריעה היא בין ארבע הראשונות — תגית **שלמה ולבדה בשורה**, שבצד
#: שאינו מכיר את השם היא סוג 7 — לבין שתי האחרונות, שאינן סוג 7 באף צד.
_BLOCK_TAG_LIST_FORMS = {
    "open": "<{t}>",
    "close": "</{t}>",
    "attribute": '<{t} src="x">',
    "upper": "<{T}>",
    "trailing_text": "<{t}> טקסט",
    "unclosed": "<{t}",
}

#: היכן שורת התגית יושבת. ``## אחרי`` הוא תמיד השורה האחרונה, והפער — כשהוא
#: קיים — הוא בדיוק השאלה אם הכותרת הזאת נבלעת בבלוק HTML או נשארת כותרת.
_BLOCK_TAG_LIST_CONTEXTS = {
    "glued_after_paragraph": "## לפני\n\nטקסט\n{line}\n## אחרי\n",
    "after_blank_line": "## לפני\n\nטקסט\n\n{line}\n## אחרי\n",
    "right_after_heading": "## לפני\n{line}\n## אחרי\n",
    "glued_after_list_item": "## לפני\n\n- פריט\n{line}\n## אחרי\n",
    "inside_blockquote": "## לפני\n\n> טקסט\n> {line}\n\n## אחרי\n",
}


def _block_tag_list_agrees(tag: str, form: str, context: str) -> bool:
    """המטריצה שנמדדה, כחוק אחד: האם שני הפארסרים מסכימים על הצורה.

    **נמדד ב-2026-09-27**, markdown-it-py 4.2.0 מול cmarkgfm 2025.10.22, על כל
    הצורות שהמחולל מייצר (2 תגיות × 6 צורות כתיבה × 5 הקשרים). החוק כתוב לפי
    המנגנון ולא כרשימת מופעים, כדי שיהיה אפשר לקרוא אותו — ו-
    ``test_the_block_tag_list_matrix_is_exactly_as_measured`` משווה אותו
    לשני הפארסרים בכל ריצה, ולכן הוא אינו יכול להתיישן בשקט:

    - **בתוך ציטוט אין פער**: ``## אחרי`` יושב אחרי שורה ריקה שסוגרת את
      הציטוט בשני הצדדים.
    - **תגית עם טקסט אחריה, או לא סגורה** — בצד שהשם ברשימה שלו היא בלוק
      HTML (סוג 6 אינו דורש תגית שלמה), ובצד השני היא פסקה (סוג 7 דורש).
      לכן פער בכל הקשר אחר.
    - **תגית שלמה ולבדה בשורה** היא בלוק HTML בשני הצדדים — סוג 6 בצד
      אחד, סוג 7 בשני — וההבדל הוא רק כשהיא **צמודה** לשורה שלפניה: סוג 6
      קוטע פסקה, סוג 7 אינו קוטע. לכן פער מיד אחרי שורת פסקה; ומיד אחרי
      שורת פריט ברשימה — רק ל-``source``: אצלנו היא סוג 7, וזה בדיוק
      המנגנון של השורה הראשונה בטבלה (#434). ``search`` אצלנו סוג 6,
      קוטעת את פסקת הפריט, ולכן מסכימה עם cmark — **וזה פער שנסגר**
      בשדרוג: ב-markdown-it-py 3.0.0, שבו ``search`` לא הייתה ברשימה, זה
      היה מופע של #434 (``closed`` בשורה בטבלה).
    """
    if context == "inside_blockquote":
        return True
    if form in ("trailing_text", "unclosed"):
        return False
    if context == "glued_after_paragraph":
        return False
    if context == "glued_after_list_item":
        return tag == "search"
    return True


def _block_tag_list_cells():
    """‏(תגית, צורה, הקשר, טקסט) לכל תא במטריצה — בסדר קבוע, כדי שדוח פער יהיה בר-השוואה."""
    for tag, (form, template), (context, frame) in itertools.product(
        _BLOCK_TAG_LIST_TAGS, _BLOCK_TAG_LIST_FORMS.items(), _BLOCK_TAG_LIST_CONTEXTS.items()
    ):
        yield tag, form, context, frame.format(line=template.format(t=tag, T=tag.upper()))


def _block_tag_list_family():
    """‏(טקסט, האם מסכימים) לכל תא — הצורה שכל משפחה בטבלה מחזירה."""
    for tag, form, context, text in _block_tag_list_cells():
        yield text, _block_tag_list_agrees(tag, form, context)


# ─── שורה 3: טבלה שעוברת את תקרת התאים המשלימים של markdown-it-py 4.x ───

#: תקרת התאים המשלימים בטבלה אחת. ‏markdown-it-py מוסיף אותה מ-4.0.0 (#364,
#: https://github.com/executablebooks/markdown-it-py/pull/364), כקבוע
#: ``MAX_AUTOCOMPLETED_CELLS`` ב-``markdown_it/rules_block/table.py``. **הוא מוקלד כאן
#: ולא מיובא**, כי הקובץ הזה נטען גם על 3.0.0, שבה הקבוע אינו קיים:
#: ``scripts/md_parser_upgrade_zero_diff.py`` מריץ את המחוללים על שתי הגרסאות.
#: ‏``test_the_table_cap_is_the_librarys_constant`` משווה אותו לספרייה המותקנת.
_TABLE_AUTOCOMPLETE_CAP = 0x10000

#: מה בא אחרי שורות הגוף, ואיזו כותרת הוא יוצר כשהטבלה נחתכה. ‏``---`` ו-``===``
#: הם קו setext: השורות שנשארו מחוץ לטבלה הן פסקה, והקו הופך אותה לכותרת. שני
#: האחרונים הם בקרה, ואחריהם אין כותרת באף צד.
_TABLE_CAP_FOLLOWERS = {"---": 2, "===": 1, "": None, "טקסט": None}

#: רוחב הטבלה במשפחה. בשורת גוף עם תא אחד יש ``עמודות - 1`` תאים משלימים, כלומר
#: 256 לשורה, ולכן 256 שורות הן **בדיוק** התקרה ו-257 הן שורה אחת מעליה.
_TABLE_CAP_COLUMNS = 257


def _wide_table(columns: int, rows: int, follower: str) -> str:
    """כותרת, טבלה ברוחב ``columns`` עם ``rows`` שורות גוף של תא אחד, ואחריה ``follower``."""
    tail = f"{follower}\n" if follower else ""
    header = "|a" * columns + "|\n" + "|-" * columns + "|\n"
    return "# כותרת\n\n" + header + "x\n" * rows + tail


def _table_cap_rows_that_fit(columns: int) -> int:
    """כמה שורות גוף של תא אחד נכנסות לטבלה לפני שהתקרה חותכת אותה.

    הכלל הוא של ``markdown_it/rules_block/table.py`` (4.2.0): הספירה מצטברת שורה
    אחר שורה, והשורה שמעבירה אותה **מעל** התקרה כבר אינה בטבלה. כלומר השורה
    הראשונה שבחוץ היא ``_table_cap_rows_that_fit(columns) + 1``, והיא יושבת בשורה
    ``4 + זה`` בקובץ: כותרת, שורה ריקה, שורת כותרות ושורת מפריד.
    """
    return _TABLE_AUTOCOMPLETE_CAP // (columns - 1)


def _table_cap_cells():
    """‏(שורות, עוקב, טקסט) — טבלה בדיוק בתקרה, ושורה אחת מעליה, עם כל עוקב."""
    fit = _table_cap_rows_that_fit(_TABLE_CAP_COLUMNS)
    for rows, follower in itertools.product((fit, fit + 1), _TABLE_CAP_FOLLOWERS):
        yield rows, follower, _wide_table(_TABLE_CAP_COLUMNS, rows, follower)


def _table_cap_agrees(rows: int, follower: str) -> bool:
    """החוק שנמדד: פער רק כשהטבלה נחתכה **וגם** קו setext בא אחריה.

    **נמדד ב-2026-09-27**, markdown-it-py 4.2.0 מול cmarkgfm 2025.10.22. ב-3.0.0 כל
    הצורות מסכימות, כי אין שם תקרה. cmark-gfm אינו חותך: כל השורות בטבלה, והקו
    שאחריה אינו יוצר כותרת. אצלנו השורות שמעל התקרה הן פסקה, והקו הופך אותה
    לכותרת — ברמה 2 אחרי ``---`` וברמה 1 אחרי ``===``.
    """
    cut = (_TABLE_CAP_COLUMNS - 1) * rows > _TABLE_AUTOCOMPLETE_CAP
    return not (cut and _TABLE_CAP_FOLLOWERS[follower] is not None)


def _table_cap_family():
    """‏(טקסט, האם מסכימים) לכל תא במשפחה של השורה השלישית."""
    for rows, follower, text in _table_cap_cells():
        yield text, _table_cap_agrees(rows, follower)


# ─── שורה 4: כותרת setext שצמודה להגדרת קישור ───


@dataclass(frozen=True)
class _ReferenceVariant:
    """צורה אחת של הגדרת קישור, ומה שני הפארסרים רואים בשורה האחרונה שלה.

    ``ends_with_definition`` — השורה האחרונה סוגרת הגדרה ששני הפארסרים מקבלים.
    ``ends_with_paragraph`` — השורה האחרונה היא שורת פסקה שבאה **מיד** אחרי הגדרה.
    ``missing_destination`` — ``[a]:`` בלי יעד, שיכול להגיע בשורה הבאה.
    ``indent`` — רווחים לפני ההגדרה: 3 עוד מותר ברמת המסמך, 4 הם קוד מוזח.
    """

    text: str
    ends_with_definition: bool = False
    ends_with_paragraph: bool = False
    missing_destination: bool = False
    indent: int = 0


#: מה בא **לפני** ההגדרה, מופרד בשורה ריקה. שני האחרונים הם פריט רשימה, ואז
#: הגדרה מוזחת נמשכת לתוכו.
_REFERENCE_PREVIOUS = ("", "טקסט", "# h", "> q", "- item", "1. item")
_REFERENCE_LIST_PREVIOUS = ("- item", "1. item")

_REFERENCE_VARIANTS = (
    _ReferenceVariant("[a]: /u", ends_with_definition=True),
    _ReferenceVariant("[a]: /u 'title'", ends_with_definition=True),
    _ReferenceVariant("[a]:\n/u", ends_with_definition=True),
    _ReferenceVariant("[a]: /u\n'title'", ends_with_definition=True),
    _ReferenceVariant("[a]: /u 'multi\nline'", ends_with_definition=True),
    _ReferenceVariant("[a]: /u 'unclosed"),
    _ReferenceVariant("[a]:", missing_destination=True),
    _ReferenceVariant("[a]: <>", ends_with_definition=True),
    _ReferenceVariant("[a]:\n\n/u"),
    _ReferenceVariant('[a]: /u "t" junk'),
    _ReferenceVariant("[\na]: /u", ends_with_definition=True),
    _ReferenceVariant("[a\\]]: /u", ends_with_definition=True),
    _ReferenceVariant("   [a]: /u", ends_with_definition=True, indent=3),
    _ReferenceVariant("    [a]: /u", ends_with_definition=True, indent=4),
    _ReferenceVariant("[a]: /u\n[b]: /v", ends_with_definition=True),
    _ReferenceVariant("[a]: /u 'x'\n'y'", ends_with_paragraph=True),
    _ReferenceVariant("[a]: /u\n## בתוך"),
    _ReferenceVariant("[a]:\n## בתוך"),
    _ReferenceVariant("[a]: /u '\n## בתוך\n'"),
    # ‏``cmarkgfm.github_flavored_markdown_to_html`` אינו מפעיל הערות שוליים, ולכן
    # זו הגדרת קישור רגילה בשני הצדדים — ראו ``_build_parser`` ב-``md_parser``.
    _ReferenceVariant("[^1]: note", ends_with_definition=True),
)

#: מה בא **אחרי** ההגדרה, צמוד אליה. ‏``אחרי`` ואז ``---`` הוא כותרת setext.
_REFERENCE_NEXT = ("## אחרי", "אחרי\n---", "===", "---", "", "טקסט\n## אחרי")


def _reference_kind(previous: str, variant: _ReferenceVariant, following: str) -> str | None:
    """החוק שנמדד: ``None`` כשהמפות מסכימות, ואחרת סוג הפער.

    **נמדד ב-2026-09-27**, על 720 הצורות של המחולל, markdown-it-py 4.2.0 מול cmarkgfm
    2025.10.22 — **וזהה על 3.0.0**: הפער קדם לשדרוג, והשכתוב של כלל ההגדרות ב-4.0.0
    (#367) לא הזיז אף צורה. שלושה סוגים:

    - ``"line"`` — אותה כותרת, מספר שורה אחר. כותרת setext שמתחילה מיד אחרי הגדרה:
      cmark-gfm מדווח את השורה שבה ההגדרה מתחילה, כי ההגדרה והכותרת הן אצלו אותה
      פסקה עד שהיא נסגרת; אנחנו מדווחים את השורה של הכותרת עצמה.
    - ``"github_only"`` — ``[a]:`` ומיד ``===``: ‏``markdown-it`` קורא את ``===`` כיעד של
      ההגדרה, ו-cmark-gfm קורא את השתיים ככותרת setext.
    - ``"ours_only"`` — הגדרה מוזחת לתוך פריט רשימה, ואחריה פסקה וקו setext בלי
      הזחה: אצלנו הפריט נגמר אחרי ההגדרה והקו הופך את הפסקה לכותרת ברמת המסמך;
      cmark-gfm ממשיך את הפסקה בתוך הפריט, והקו הוא קו מפריד.
    """
    inside_item = previous in _REFERENCE_LIST_PREVIOUS and variant.indent > 0
    if variant.indent >= 4 and not inside_item:
        return None  # קוד מוזח ברמת המסמך — אין כאן הגדרה בכלל
    if variant.ends_with_paragraph and following in ("אחרי\n---", "===", "---"):
        return "line"
    if variant.ends_with_definition and following == "אחרי\n---":
        return "ours_only" if inside_item else "line"
    if variant.missing_destination and following == "===":
        return "github_only"
    return None


def _reference_cells():
    """‏(לפני, הגדרה, אחרי, טקסט) לכל צורה — בסדר קבוע."""
    for previous, variant, following in itertools.product(
        _REFERENCE_PREVIOUS, _REFERENCE_VARIANTS, _REFERENCE_NEXT
    ):
        head = f"{previous}\n\n" if previous else ""
        yield previous, variant, following, f"{head}{variant.text}\n{following}\n"


def _reference_family():
    """‏(טקסט, האם מסכימים) לכל תא במשפחה של השורה הרביעית."""
    for previous, variant, following, text in _reference_cells():
        yield text, _reference_kind(previous, variant, following) is None


def _divergence_kind(ours, theirs) -> str | None:
    """איזה פער יש בין שתי מפות: ``None``, ``"line"``, ``"github_only"``, ``"ours_only"``.

    ‏``"other"`` הוא כל מה שאינו אחד מהשלושה — ואין לו מקום בחוק, כך שהופעה שלו
    נופלת בטסט ולא נבלעת.
    """
    if ours == theirs:
        return None
    if [level for level, _ in ours] == [level for level, _ in theirs]:
        return "line"
    if set(ours) < set(theirs):
        return "github_only"
    if set(theirs) < set(ours):
        return "ours_only"
    return "other"


# ─── רשימות התגיות של שני הפארסרים ───

#: תגיות הבלוק של cmark-gfm 0.29.0.gfm.13 — הגרסה ש-cmarkgfm 2025.10.22 עוטף
#: (``generated/unix/cmark-gfm_version.h``) — כלשונן ב-``blocktagname`` ב-``src/scanners.re``
#: (https://github.com/github/cmark-gfm/blob/0.29.0.gfm.13/src/scanners.re). **מוקלדות
#: ולא נגזרות**, כי הרשימה חיה בקוד C. ‏``title`` מופיעה שם פעמיים, וגם כאן — ההעתקה
#: נשארת מילה במילה, כדי שבשדרוג הבא אפשר יהיה להשוות אותה למקור בעין — ולכן
#: ``frozenset``, ו-``noqa: B033`` על השורה של המופע השני.
#: ‏``test_each_tag_list_is_what_its_parser_does`` מודד את ההתנהגות של cmark-gfm
#: בפועל מול הרשימה הזאת, כך שהיא אינה יכולה להתיישן בשקט.
_CMARK_GFM_BLOCK_TAGS = frozenset({
    "address", "article", "aside", "base", "basefont", "blockquote", "body", "caption",
    "center", "col", "colgroup", "dd", "details", "dialog", "dir", "div", "dl", "dt",
    "fieldset", "figcaption", "figure", "footer", "form", "frame", "frameset", "h1", "h2",
    "h3", "h4", "h5", "h6", "head", "header", "hr", "html", "iframe", "legend", "li",
    "link", "main", "menu", "menuitem", "nav", "noframes", "ol", "optgroup", "option", "p",
    "param", "section", "source", "title", "summary", "table", "tbody", "td", "tfoot", "th",
    "thead", "title", "tr", "track", "ul",  # noqa: B033 — המופע השני של title, כמו במקור
})

#: תגיות בלוק מסוג 1 — נסגרות רק בתגית הסוגרת שלהן, לא בשורה ריקה. זהות בשני
#: הפארסרים: ``HTML_SEQUENCES[0]`` ב-``markdown_it/rules_block/html_block.py`` (3.0.0
#: ו-4.2.0), ו-``_scan_html_block_start`` ב-``scanners.re`` של cmark-gfm.
_TYPE1_TAGS = ("script", "pre", "style", "textarea")

#: כל שם שאחד הפארסרים מכיר כתגית בלוק (סוג 6), חוץ מהשמות של השורה השנייה
#: בטבלה. **הרשימה של markdown-it נקראת מהספרייה בזמן ריצה** (``block_names`` ב-
#: ``markdown_it/common/html_blocks.py``), ולכן שם שגרסה עתידית תוסיף ייכנס למשפחה
#: מעצמו — ושם שהיא תוציא נשאר בה דרך הרשימה של cmark-gfm. בשני המקרים הצורות שלו
#: יחלקו, והשדרוג יגלה את זה בלי שמישהו יחשוד מראש.
_HTML_BLOCK_TAGS = tuple(
    sorted((set(_MARKDOWN_IT_BLOCK_TAGS) | _CMARK_GFM_BLOCK_TAGS) - set(_BLOCK_TAG_LIST_TAGS))
)

#: שמות שאינם ברשימה של אף פארסר, ולכן יכולים לפתוח רק בלוק מסוג 7: תגית שלמה
#: ולבדה בשורה, שאינה קוטעת פסקה.
_NOT_BLOCK_TAG_NAMES = ("span", "video", "img", "br", "custom-el")


# ─── משפחה קבועה: שורה שמתחילה בכל תגית בלוק ───

#: צורות הכתיבה במשפחה: אלה של השורה השנייה, ועוד תגית שנסגרת בעצמה ושלושת
#: הרווחים ש-``\s`` של פייתון ו-``spacechar`` של cmark-gfm מסכימים עליהם.
_HTML_TAG_FORMS = {
    **_BLOCK_TAG_LIST_FORMS,
    "self_closing": "<{t}/>",
    "tab": "<{t}\t>",
    "vertical_tab": "<{t}\v>",
    "form_feed": "<{t}\f>",
}

#: אצל תגית מסוג 1 שתי הצורות האלה כבר אינן סוג 1 אלא סוג 7, ו**צמודות לפריט
#: רשימה** הן המחלקה של השורה הראשונה בטבלה (``</pre>`` כבר יושבת שם).
_TYPE7_FORMS_OF_A_TYPE1_TAG = ("close", "self_closing")


def _html_tag_shapes():
    """כל תגית בלוק × כל צורת כתיבה × כל הקשר — וכולן מסכימות.

    **למה המשפחה הזאת קיימת:** הפער של ``source``/``search`` ברח מכל הצורות
    המחוללות, כי אף מחולל לא בנה שורה שמתחילה בתגית שאינה אחת משש התגיות של
    ``_html_shapes``. כאן כל שם שאחד הפארסרים מכיר עובר באותן צורות ובאותם
    הקשרים של השורה השנייה, ולכן שינוי ברשימה של אחד מהם מפיל את ``_compare``
    בשדרוג הבא, בלי שמישהו יחשוד בו מראש.
    """
    for tag in _HTML_BLOCK_TAGS + _TYPE1_TAGS:
        for (form, template), (context, frame) in itertools.product(
            _HTML_TAG_FORMS.items(), _BLOCK_TAG_LIST_CONTEXTS.items()
        ):
            if (
                tag in _TYPE1_TAGS
                and form in _TYPE7_FORMS_OF_A_TYPE1_TAG
                and context == "glued_after_list_item"
            ):
                continue
            yield frame.format(line=template.format(t=tag, T=tag.upper()))


# ─── שורה 5: תו רווח ש-\s של פייתון מזהה ו-cmark-gfm לא, בתוך תגית ───

#: ‏``spacechar`` של cmark-gfm 0.29.0.gfm.13, כלשונו ב-``src/scanners.re``: התווים
#: שהוא מקבל אחרי שם תגית, בין מאפיינים ולפני ``>``.
_CMARK_SPACECHAR = " \t\v\f\r\n"

#: התווים ש-``\s`` של ``re`` מזהה ו-``spacechar`` של cmark-gfm לא. ‏``markdown-it-py``
#: כותב ב-``\s`` גם את תנאי הפתיחה של בלוק HTML (``HTML_SEQUENCES`` ב-
#: ``rules_block/html_block.py``) וגם את התגית עצמה (``common/html_re.py``) — ב-3.0.0
#: וב-4.2.0 — ולכן רווח כזה בתוך תגית פותח אצלנו בלוק HTML ואצל GitHub לא. **נגזר ולא
#: מוקלד.** ``str.isspace`` מהיר פי שלושה מסריקה ב-``re``, ו-
#: ``test_the_python_only_spaces_are_what_re_calls_whitespace`` בודק שזו בדיוק אותה קבוצה.
_PYTHON_ONLY_SPACES = "".join(
    char
    for char in map(chr, range(sys.maxunicode + 1))
    if char.isspace() and char not in _CMARK_SPACECHAR
)
_PYTHON_ONLY_SPACE_SET = frozenset(_PYTHON_ONLY_SPACES)

#: איפה בתגית יושב הרווח. בשלוש הראשונות הוא צמוד לשם; בשתי האחרונות רווח ASCII
#: כבר הפריד את השם, והרווח החריג יושב בין מאפיינים או לפני ``>``.
_SPACE_FORMS = {
    "after_name": "<{t}{s}>",
    "before_attribute": '<{t}{s}class="x">',
    "closing": "</{t}{s}>",
    "between_attributes": '<{t} class="x"{s}id="y">',
    "before_gt": '<{t} class="x"{s}>',
}

#: כל השמות במשפחה. ‏``source``/``search`` אינם כאן — צורה ששורתה מתחילה בהם שייכת
#: לשורה השנייה, לפי כלל השיוך.
_SPACE_TAGS = _HTML_BLOCK_TAGS + _TYPE1_TAGS + _NOT_BLOCK_TAG_NAMES

#: המשפחה מכסה **כל תו מול שלוש תגיות** (אחת לכל סוג) **וכל תגית מול שני תווים**
#: (NBSP, הנפוץ בהעתקה מדפי אינטרנט, ו-U+3000). המכפלה המלאה הייתה פי עשרה
#: בגודלה בלי להוסיף מקרה: כל התווים מתנהגים אותו דבר, וכל התגיות מאותו סוג גם.
_SPACE_REPRESENTATIVE_TAGS = ("div", "pre", "span")
_SPACE_REPRESENTATIVE_CHARS = ("\xa0", "　")


def _space_kind(tag: str) -> str:
    if tag in _TYPE1_TAGS:
        return "type1"
    if tag in _NOT_BLOCK_TAG_NAMES:
        return "other"
    return "block"


def _space_in_tag_agrees(tag: str, form: str, context: str) -> bool:
    """החוק שנמדד: האם שני הפארסרים מסכימים כשרווח כזה יושב בתוך התגית.

    **נמדד ב-2026-09-27**, markdown-it-py 4.2.0 מול cmarkgfm 2025.10.22 — **וזהה על
    3.0.0**. אצל cmark-gfm הרווח הזה אינו רווח. כשהוא צמוד לשם התגית, או כשרק בזכותו
    התגית שלמה, השורה אינה פותחת אצלו בלוק HTML: היא פסקה, ו-``## אחרי`` שאחריה הוא
    כותרת. אצלנו היא כן פותחת בלוק, והבלוק בולע את ``## אחרי``. לכן בכל פער הכיוון
    אחד: כותרת שיש ב-GitHub ואין אצלנו. מה שמשתנה בין הצורות הוא **אם** יש פער:

    - **בתוך ציטוט אין פער** — השורה הריקה שלפני ``## אחרי`` סוגרת את הכול.
    - **תגית בלוק או סוג 1, והרווח צמוד לשם** — אצלנו תנאי הפתיחה של סוג 6 או 1,
      שקוטע פסקה, ולכן פער בכל הקשר אחר. (תגית סגירה של סוג 1 אינה פותחת סוג 1.)
    - **תגית בלוק או סוג 1, ורווח ASCII כבר הפריד את השם** — שני הצדדים פתחו בלוק
      על הרווח הרגיל, ואין פער.
    - **כל השאר** — אצלנו תגית שלמה מסוג 7, שאינה קוטעת פסקה: פער רק כשאין פסקה
      לפניה, כלומר אחרי שורה ריקה או מיד אחרי כותרת.
    """
    if context == "inside_blockquote":
        return True
    kind = _space_kind(tag)
    right_after_name = form in ("after_name", "before_attribute", "closing")
    if kind == "block" and right_after_name:
        return False
    if kind == "type1" and form in ("after_name", "before_attribute"):
        return False
    if kind in ("block", "type1") and not right_after_name:
        return True
    return context in ("glued_after_paragraph", "glued_after_list_item")


def _space_cells():
    """‏(תגית, תו, צורה, הקשר, טקסט) לכל תא — כל זוג (תגית, תו) פעם אחת, בסדר קבוע."""
    pairs = [(tag, space) for tag in _SPACE_REPRESENTATIVE_TAGS for space in _PYTHON_ONLY_SPACES]
    pairs += [(tag, space) for tag in _SPACE_TAGS for space in _SPACE_REPRESENTATIVE_CHARS]
    for tag, space in dict.fromkeys(pairs):
        for (form, template), (context, frame) in itertools.product(
            _SPACE_FORMS.items(), _BLOCK_TAG_LIST_CONTEXTS.items()
        ):
            yield tag, space, form, context, frame.format(line=template.format(t=tag, s=space))


def _space_family():
    """‏(טקסט, האם מסכימים) לכל תא במשפחה של השורה החמישית."""
    for tag, _space, form, context, text in _space_cells():
        yield text, _space_in_tag_agrees(tag, form, context)


# ─── הטבלה ───


@dataclass(frozen=True)
class _Example:
    """צורה אחת ומה שכל צד מחזיר עליה: (רמה, שורה) לכל כותרת ברמת המסמך."""

    text: str
    github: tuple[tuple[int, int], ...]
    ours: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class _Divergence:
    """שורה אחת בטבלת הפערים הידועים מ-GitHub.

    ``cause`` הוא **הסיבה** בשמה, ולא ספירה של מופעים. ``examples`` הן הצורות
    שהתיעוד מציג, עם מה ש-cmark-gfm מחזיר (``github``) ומה שאנחנו מחזירים;
    ``family`` היא כל מה שנמדד — ממנה נגזר "N מתוך M צורות שנמדדו", שהוא
    **מדידה ולא גבול**, ולכן הוא נכתב תמיד עם ``measured_on`` ו-``measured_at``.
    ``upstream`` הוא קישור לאישו כשיש כזה. ``trigger`` הוא שורה בקובץ אמיתי
    שיכולה להפעיל את הפער (ראו ``_divergence_trigger_lines``) — **רק לשורה שיש
    לה צורה של שורה אחת שאפשר לסמן בלי לסמן עמודים רגילים**. לשורה שאין לה,
    ``trigger`` הוא ``None``, והנימוק כתוב ליד השורה; קובץ אמיתי שמפעיל אותה
    נתפס רק בהשוואת המפות של ``scripts/compare_md_parser_to_cmark.py``.
    ‏``closed`` — צורות שבהן פער **נסגר**, כלומר שני הצדדים מסכימים היום על מה
    שבגרסה קודמת חלקו עליו: מידע למי שיקרא את זה בעוד חצי שנה, ומקובע בטסט.
    ‏``unreachable`` — כשהפער קיים בפרסר אבל **אינו יכול להגיע ללקוח של הכלי**, למה.
    הוא כתוב בשורה עצמה ולא רק בתיעוד, כדי שמי שקורא את הטבלה לא יראה פער מקובע
    בלי לדעת שאיש לא יכול להגיע אליו; טסט בודק את הטענה, והתיעוד מעתיק אותה.
    """

    key: str
    cause: str
    examples: tuple[_Example, ...]
    measured_on: str
    measured_at: str
    upstream: str | None
    family: Callable[[], Iterable[tuple[str, bool]]]
    trigger: re.Pattern[str] | None = None
    closed: tuple[_Example, ...] = ()
    unreachable: str | None = None


#: על מה נמדדה הטבלה. אותה מחרוזת בכל השורות ובתיעוד, וטסט משווה.
_MEASURED_ON = "markdown-it-py 4.2.0, cmarkgfm 2025.10.22"

#: **כלל השיוך:** צורה ששורה בה מתחילה בתגית מ-``_BLOCK_TAG_LIST_TAGS`` שייכת
#: לשורה השנייה — גם כשהמנגנון בפועל הוא של הראשונה (``source`` צמודה לפריט
#: רשימה). כך כל צורה יושבת בשורה אחת בדיוק, ו-
#: ``test_every_measured_shape_belongs_to_one_row`` אוכף זאת.
_KNOWN_DIVERGENCES: tuple[_Divergence, ...] = (
    _Divergence(
        key="type7_glued_to_container",
        cause="תגית HTML מסוג 7 צמודה לשורת מכל (פריט רשימה או ציטוט)",
        examples=(
            _Example("## לפני\n\n- פריט\n<br>\n## אחרי\n", github=((2, 1),), ours=((2, 1), (2, 5))),
        ),
        measured_on=_MEASURED_ON,
        measured_at="2026-09-27",
        upstream="https://github.com/executablebooks/markdown-it-py/issues/434",
        family=_type7_family,
        # **בלי טריגר, בכוונה.** הפער תלוי בשתי שורות — שורת המכל והתגית שצמודה
        # אליה — ותגיות כמו ``<br>`` נפוצות בעמודים רגילים. טריגר על התגית לבדה היה
        # מסמן עמודים שאין בהם פער.
    ),
    _Divergence(
        key="commonmark_0_31_block_tag_list",
        cause="רשימת תגיות הבלוק של CommonMark 0.31.2: source/search",
        examples=(
            _Example(
                "## לפני\n\nטקסט\n<source>\n## אחרי\n", github=((2, 1),), ours=((2, 1), (2, 5))
            ),
            _Example(
                "## לפני\n\nטקסט\n<search>\n## אחרי\n", github=((2, 1), (2, 5)), ours=((2, 1),)
            ),
        ),
        measured_on=_MEASURED_ON,
        measured_at="2026-09-27",
        upstream=None,
        family=_block_tag_list_family,
        # תנאי הפתיחה של סוג 6 **כפי ש-markdown-it-py כותב אותו**: ‏
        # ``(?=(\s|/?>|$))`` אחרי השם, ב-``HTML_SEQUENCES`` ב-``rules_block/html_block.py``
        # (4.2.0), בלי תלות ברישיות. כלומר ``\s`` של פייתון, ולא רווח וטאב בלבד:
        # עם ``[ \t]``, ``<search`` ואחריה NBSP חלקה על GitHub והסריקה שתקה (נמדד).
        # השמות נלקחים מ-``_BLOCK_TAG_LIST_TAGS`` ולא מוקלדים פעם שנייה.
        trigger=re.compile(
            r"^ {0,3}</?(?:" + "|".join(_BLOCK_TAG_LIST_TAGS) + r")(?=\s|/?>|$)", re.IGNORECASE
        ),
        closed=(
            _Example("## לפני\n\n- פריט\n<search>\n## אחרי\n", github=((2, 1),), ours=((2, 1),)),
        ),
    ),
    _Divergence(
        key="table_over_autocomplete_cap",
        cause="טבלה שעוברת את תקרת התאים המשלימים של markdown-it-py 4.x",
        examples=(
            # 300 עמודות ו-230 שורות גוף של תא אחד: 68,770 תאים משלימים, מעל התקרה.
            # השורה ה-220 היא הראשונה שבחוץ, והיא יושבת בשורה 224 בקובץ.
            _Example(_wide_table(300, 230, "---"), github=((1, 1),), ours=((1, 1), (2, 224))),
        ),
        measured_on=_MEASURED_ON,
        measured_at="2026-09-27",
        upstream=None,
        family=_table_cap_family,
        # **בלי טריגר, בכוונה.** הפער תלוי בגודל הטבלה כולה ובקו שאחריה, ולא
        # בשורה אחת שאפשר לסמן.
        #
        # המספר הוא ``3 × _TABLE_AUTOCOMPLETE_CAP`` — כתוב כאן כמספר כדי שייקרא
        # בשורה, ונגזר ב-``test_the_table_cap_gap_is_unreachable_through_the_tool``.
        unreachable=(
            "אינו נגיש דרך הכלי: הפער מתחיל רק אחרי 196,608 טוקנים — שלושה לכל תא"
            " משלים עד התקרה — והכלי מסרב לכל מסמך שעובר את ``MAX_TOKENS``"
            " ב-``too_many_tokens``, לפני שהוא מגיע לשם."
        ),
    ),
    _Divergence(
        key="setext_after_link_reference",
        cause="כותרת setext שצמודה להגדרת קישור",
        examples=(
            _Example("[a]: /u\nאחרי\n---\n", github=((2, 1),), ours=((2, 2),)),
            _Example("[a]:\n===\n", github=((1, 1),), ours=()),
            _Example("- item\n\n   [a]: /u\nאחרי\n---\n", github=(), ours=((2, 4),)),
        ),
        measured_on=_MEASURED_ON,
        measured_at="2026-09-27",
        upstream=None,
        family=_reference_family,
        # **בלי טריגר, בכוונה.** הגדרות קישור נפוצות בעמודים רגילים, והפער תלוי
        # בשורה שאחריהן. טריגר על ההגדרה לבדה היה מסמן עמודים שאין בהם פער.
    ),
    _Divergence(
        key="python_only_space_in_tag",
        cause="תו רווח ש-markdown-it-py מזהה ו-cmark-gfm לא, אחרי שם תגית HTML",
        examples=(
            _Example(
                '## לפני\n\nטקסט\n<div\xa0class="x">\n## אחרי\n',
                github=((2, 1), (2, 5)),
                ours=((2, 1),),
            ),
            _Example("## לפני\n\n<span\xa0>\n## אחרי\n", github=((2, 1), (2, 4)), ours=((2, 1),)),
        ),
        measured_on=_MEASURED_ON,
        measured_at="2026-09-27",
        upstream=None,
        family=_space_family,
        # שורה שמתחילה בתגית, ומיד אחרי שם התגית תו מ-``_PYTHON_ONLY_SPACES``. אין לו
        # מופע בעמוד אמיתי, ולכן הטריגר אינו מסמן עמודים רגילים. **רק מיד אחרי השם:**
        # המשפחה מראה פער גם כשהתו יושב בין מאפיינים של תגית מסוג 7, אבל טריגר של
        # שורה אחת אינו יכול להבדיל שם בין רווח לבין תו בתוך ערך של מאפיין בלי לכתוב
        # מחדש את הדקדוק של תגית — כלל ביד, בדיוק מה שהקובץ הזה נמנע ממנו.
        # ‏``source``/``search`` מוחרגות: שורה שמתחילה בהן שייכת לשורה השנייה.
        trigger=re.compile(
            r"^ {0,3}</?(?!(?:" + "|".join(_BLOCK_TAG_LIST_TAGS) + r")(?![A-Za-z0-9-]))"
            r"[A-Za-z][A-Za-z0-9-]*[" + re.escape(_PYTHON_ONLY_SPACES) + "]",
            re.IGNORECASE,
        ),
    ),
)


_KNOWN_DIVERGENCES_BY_KEY = {row.key: row for row in _KNOWN_DIVERGENCES}


def _row_counts(row: _Divergence) -> tuple[int, int]:
    """‏(כמה צורות נמדדו, בכמה מהן יש פער) — הזוג שהתיעוד כותב כ-"N מתוך M"."""
    family = list(row.family())
    return len(family), sum(1 for _text, agrees in family if not agrees)


def _row_ids(rows):
    return [row.key for row in rows]


@pytest.mark.parametrize("row", _KNOWN_DIVERGENCES, ids=_row_ids(_KNOWN_DIVERGENCES))
def test_each_row_example_returns_what_the_table_says(row):
    """הצורות שהתיעוד מציג מחזירות בדיוק את מה שכתוב בטבלה — בשני הצדדים."""
    for example in row.examples + row.closed:
        assert _oracle_sections(example.text) == list(example.github), ("cmark-gfm", example.text)
        assert _ours(example.text) == list(example.ours), ("שלנו", example.text)
    for example in row.examples:
        assert example.github != example.ours, ("דוגמה לפער חייבת להיות פער", example.text)
    for example in row.closed:
        assert example.github == example.ours, ("פער שנסגר פירושו הסכמה היום", example.text)


@pytest.mark.parametrize("row", _KNOWN_DIVERGENCES, ids=_row_ids(_KNOWN_DIVERGENCES))
def test_the_agreeing_half_of_each_row_goes_through_compare(row):
    """מה שהמשפחה מצהירה עליו כהסכמה עובר ב-``_compare`` כמו כל משפחה אחרת."""
    agreeing = [text for text, agrees in row.family() if agrees]
    assert agreeing, "משפחה בלי חצי מסכים — אין מקרה בקרה"
    _compare(agreeing)


def test_the_block_tag_list_matrix_is_exactly_as_measured():
    """**כל** תא במטריצה, בשני הכיוונים — ומה בדיוק שונה כשיש פער.

    תא שמוצהר כהסכמה חייב להסכים, ותא שמוצהר כפער חייב לחלוק. **וכשיש
    פער, הוא אותו פער בכל התאים:** ``## לפני`` נשאר בשני הצדדים, וההבדל
    היחיד הוא ``## אחרי`` — כותרת בצד אחד, בלועה בבלוק HTML בצד השני. כך
    פער לא יכול להיסחף לכיוון שלישי בשקט.

    .. warning::

       **נפילה כאן פירושה שאחד הפארסרים שינה התנהגות** — markdown-it-py
       או cmark-gfm. לא "מתקנים" את החוק כדי שיעבור: מודדים מחדש, מעדכנים
       את ``measured_on`` ו-``measured_at``, ואת התיעוד שמעתיק מהטבלה.
    """
    wrong = []
    for tag, form, context, text in _block_tag_list_cells():
        ours, theirs = _ours(text), _oracle_sections(text)
        expected = _block_tag_list_agrees(tag, form, context)
        if (ours == theirs) != expected:
            wrong.append((tag, form, context, ours, theirs))
            continue
        if not expected:
            after_line = text.count("\n")  # ``## אחרי`` היא תמיד השורה האחרונה
            assert set(ours) ^ set(theirs) == {(2, after_line)}, (tag, form, context, ours, theirs)
            assert (2, 1) in ours and (2, 1) in theirs, (tag, form, context, ours, theirs)
    assert not wrong, f"{len(wrong)} תאים שאינם כפי שנמדדו:\n" + "\n".join(map(repr, wrong))


def test_every_measured_shape_belongs_to_one_row():
    """כלל השיוך: צורה ששורה בה מפעילה טריגר של שורה בטבלה אינה נמצאת בשורה אחרת."""
    for row in _KNOWN_DIVERGENCES:
        for other in _KNOWN_DIVERGENCES:
            if other is row or other.trigger is None:
                continue
            for text, _agrees in row.family():
                assert not any(other.trigger.search(line) for line in text.split("\n")), (
                    f"צורה של {row.key} מפעילה את הטריגר של {other.key}", text,
                )


def test_the_table_cap_family_is_exactly_as_measured():
    """**כל** תא במשפחה של השורה השלישית, בשני הכיוונים — ואיפה בדיוק הכותרת העודפת.

    תא שמוצהר כהסכמה חייב להסכים, ותא שמוצהר כפער חייב לחלוק. בכל פער ל-GitHub יש
    רק ``# כותרת``, ואצלנו יש בנוסף כותרת אחת: ברמה שהקו קובע, בשורה של שורת הגוף
    הראשונה שנשארה מחוץ לטבלה. הטבלה שבדיוק בתקרה היא הבקרה, והיא מסכימה, כי התקרה
    חותכת רק מה שמעליה.

    .. warning::

       **נפילה כאן פירושה שאחד הפארסרים שינה התנהגות**, או שהתקרה של markdown-it-py
       זזה — ואז נופל גם ``test_the_table_cap_is_the_librarys_constant``. מודדים מחדש,
       ולא "מתקנים" את החוק כדי שיעבור.
    """
    first_out = 4 + _table_cap_rows_that_fit(_TABLE_CAP_COLUMNS) + 1
    wrong = []
    for rows, follower, text in _table_cap_cells():
        ours, theirs = _ours(text), _oracle_sections(text)
        expected = _table_cap_agrees(rows, follower)
        if (ours == theirs) != expected:
            wrong.append((rows, follower, ours, theirs))
            continue
        if not expected:
            level = _TABLE_CAP_FOLLOWERS[follower]
            assert theirs == [(1, 1)], (rows, follower, theirs)
            assert ours == [(1, 1), (level, first_out)], (rows, follower, ours)
    assert not wrong, f"{len(wrong)} תאים שאינם כפי שנמדדו:\n" + "\n".join(map(repr, wrong))


def test_the_table_cap_is_the_librarys_constant():
    """התקרה שהמשפחה בנויה סביבה היא הקבוע של הספרייה המותקנת, ולא עותק שהתיישן.

    **הייבוא כאן ולא בראש הקובץ:** ב-3.0.0 הקבוע אינו קיים, והקובץ הזה חייב להיטען
    גם שם (ראו ``_TABLE_AUTOCOMPLETE_CAP``). על 3.0.0 הטסט הזה נופל ב-``ImportError``,
    וזה נכון: על הגרסה ההיא אין שורה שלישית בטבלה.
    """
    from markdown_it.rules_block.table import MAX_AUTOCOMPLETED_CELLS

    assert MAX_AUTOCOMPLETED_CELLS == _TABLE_AUTOCOMPLETE_CAP


def test_the_table_cap_gap_is_unreachable_through_the_tool(monkeypatch):
    """מה שכתוב ב-``unreachable`` של השורה השלישית — כבדיקה, ולא רק כמשפט.

    שלושה חלקים. **המספר נגזר:** כל תא בשורת גוף — גם תא משלים — הוא שלושה טוקנים,
    ולכן טבלה נחתכת רק אחרי ``3 × _TABLE_AUTOCOMPLETE_CAP`` טוקנים, וזה המספר שכתוב
    בשורה. **הוא מעל ``MAX_TOKENS``.** ו**הכלי עצמו** — ``docs_get_section`` על
    ברירות המחדל של הפרסר, כמו בייצור — מסרב לכל צורה במשפחה ב-``too_many_tokens``,
    גם לחצי שמסכים עם GitHub: הוא אינו מגיע לאף אחת מהן.

    הייבוא כאן ולא בראש הקובץ: הקובץ נטען גם על ידי ``scripts/compare_md_parser_to_cmark.py``,
    ששם אין צורך בשכבת ה-MCP.
    """
    from mcp_server import docs_handlers
    from services import md_parser

    row = _KNOWN_DIVERGENCES_BY_KEY["table_over_autocomplete_cap"]
    gap_tokens = 3 * _TABLE_AUTOCOMPLETE_CAP
    assert row.unreachable and f"{gap_tokens:,}" in row.unreachable, row.unreachable

    columns = _TABLE_CAP_COLUMNS
    one_body_row = (md_parser.token_count(_wide_table(columns, 2, ""))
                    - md_parser.token_count(_wide_table(columns, 1, "")))
    assert one_body_row == 2 + 3 * columns, "תא בשורת גוף — גם משלים — אינו שלושה טוקנים"
    assert gap_tokens > md_parser.MAX_TOKENS

    class _Backend:
        def __init__(self, text: str) -> None:
            self._text = text

        def get_file(self, *, repo, path, ref=None, lines=None):
            return {"ok": True, "status": "ok", "content": self._text,
                    "file": {"path": path, "ref": "HEAD", "resolved_commit": "c0ffee"}}

    monkeypatch.setenv("MCP_DOCS_REPO", "amir-bug-patterns")
    answers = [
        docs_handlers.docs_get_section(_Backend(text), path="x.md", repo="amir-bug-patterns")
        for text, _agrees in row.family()
    ]
    assert len(answers) == 8
    assert {(a["ok"], a["error"], a["max"]) for a in answers} == {
        (False, "too_many_tokens", md_parser.MAX_TOKENS)}


def test_the_reference_family_is_exactly_as_measured():
    """**כל** צורה במשפחה של השורה הרביעית — ולא רק אם יש פער, אלא איזה פער.

    ‏``_divergence_kind`` מסווג כל אי-הסכמה לאחד משלושת הסוגים שבחוק, ול-``"other"``
    אין מקום בחוק. כלומר פער מסוג רביעי נופל כאן, ולא נבלע בתוך סוג קיים.
    """
    wrong = []
    for previous, variant, following, text in _reference_cells():
        expected = _reference_kind(previous, variant, following)
        actual = _divergence_kind(_ours(text), _oracle_sections(text))
        if actual != expected:
            wrong.append((previous, variant.text, following, expected, actual))
    assert not wrong, f"{len(wrong)} צורות שאינן כפי שנמדדו:\n" + "\n".join(map(repr, wrong))


def test_the_space_family_is_exactly_as_measured():
    """**כל** תא במשפחה של השורה החמישית, בשני הכיוונים — ומה בדיוק שונה כשיש פער.

    בכל פער הכיוון אחד: ``## אחרי`` הוא כותרת ב-GitHub ונבלע אצלנו, ו-``## לפני``
    נשאר בשני הצדדים. כך פער לא יכול להתהפך או להיסחף לכיוון שלישי בשקט.
    """
    wrong = []
    for tag, space, form, context, text in _space_cells():
        ours, theirs = _ours(text), _oracle_sections(text)
        expected = _space_in_tag_agrees(tag, form, context)
        if (ours == theirs) != expected:
            wrong.append((tag, f"U+{ord(space):04X}", form, context, ours, theirs))
            continue
        if not expected:
            after_line = text.count("\n")  # ``## אחרי`` היא תמיד השורה האחרונה
            assert set(theirs) - set(ours) == {(2, after_line)}, (tag, form, context, ours, theirs)
            assert set(ours) < set(theirs) and (2, 1) in ours, (tag, form, context, ours, theirs)
    assert not wrong, f"{len(wrong)} תאים שאינם כפי שנמדדו:\n" + "\n".join(map(repr, wrong))


def test_the_python_only_spaces_are_what_re_calls_whitespace():
    """‏``_PYTHON_ONLY_SPACES`` נגזר מ-``str.isspace``, ו-markdown-it-py כותב ``\\s`` של ``re``.

    זו בדיוק ההנחה שהגזירה המהירה נשענת עליה, והיא נבדקת כאן מול ``re`` עצמו, על כל
    טווח התווים. ובאותה הזדמנות: כל תו של ``spacechar`` הוא גם ``\\s`` — כלומר הקבוצה
    שלנו היא באמת ההפרש בכיוון אחד — ושני התווים שהמשפחה בוחרת כנציגים שייכים לה.
    """
    everything = "".join(map(chr, range(sys.maxunicode + 1)))
    by_re = "".join(char for char in re.findall(r"\s", everything) if char not in _CMARK_SPACECHAR)
    assert by_re == _PYTHON_ONLY_SPACES
    assert all(re.fullmatch(r"\s", char) for char in _CMARK_SPACECHAR)
    assert set(_SPACE_REPRESENTATIVE_CHARS) <= set(_PYTHON_ONLY_SPACES)


def test_every_html_block_tag_agrees_with_cmark():
    """המשפחה הקבועה של תגיות הבלוק: כל הצורות מסכימות, ואף שורה בה אינה טריגר.

    השורות שיש להן טריגר שייכות לשורות בטבלה, ולא למשפחה שמוצהרת כמסכימה — ולכן
    הבדיקה השנייה. והמספר נגזר מההגדרה של המחולל, כדי שהמשפחה לא תתכווץ בשקט.
    """
    shapes = list(_html_tag_shapes())
    per_tag = len(_HTML_TAG_FORMS) * len(_BLOCK_TAG_LIST_CONTEXTS)
    skipped = len(_TYPE1_TAGS) * len(_TYPE7_FORMS_OF_A_TYPE1_TAG)
    assert len(shapes) == (len(_HTML_BLOCK_TAGS) + len(_TYPE1_TAGS)) * per_tag - skipped
    triggers = [row.trigger for row in _KNOWN_DIVERGENCES if row.trigger is not None]
    triggered = [
        s for s in shapes if any(t.search(line) for t in triggers for line in s.split("\n"))
    ]
    assert not triggered, triggered[:3]
    _compare(shapes)


def test_the_two_block_tag_lists_differ_only_by_the_known_row():
    """הרשימה של markdown-it-py, כפי שהיא נקראת בזמן ריצה, מול זו של cmark-gfm.

    ההפרש ביניהן הוא בדיוק השמות של השורה השנייה בטבלה.

    .. warning::

       **נפילה כאן היא מה שהמשפחה של תגיות הבלוק נבנתה כדי לתפוס:** אחד הפארסרים
       הוסיף שם לרשימה או הוציא ממנה. זו מחלקת פער חדשה. מודדים אותה, ומוסיפים שורה
       לטבלה או מרחיבים את השנייה. לא מוסיפים את השם כאן רק כדי שהטסט יעבור.
    """
    assert set(_MARKDOWN_IT_BLOCK_TAGS) ^ _CMARK_GFM_BLOCK_TAGS == set(_BLOCK_TAG_LIST_TAGS)


def test_each_tag_list_is_what_its_parser_does():
    """כל רשימה נבדקת מול ההתנהגות של הפארסר שלה, ולא רק מול הטקסט שלה.

    תגית בלוק (סוג 6) או תגית מסוג 1 **קוטעת פסקה**, ושם אחר אינו קוטע. לכן ``<שם>``
    שצמודה לפסקה בולעת את ``## אחרי`` אם ורק אם השם ברשימה. זה מה שהופך את הרשימה
    המוקלדת של cmark-gfm למדידה ולא להעתקה: אם cmarkgfm ישודרג והרשימה שלו תשתנה,
    הטסט הזה ייפול על השם עצמו.
    """
    candidates = sorted(
        set(_MARKDOWN_IT_BLOCK_TAGS)
        | _CMARK_GFM_BLOCK_TAGS
        | set(_TYPE1_TAGS)
        | set(_NOT_BLOCK_TAG_NAMES)
    )

    def interrupting(sections_of):
        return {
            name
            for name in candidates
            if (2, 5) not in sections_of(f"## לפני\n\nטקסט\n<{name}>\n## אחרי\n")
        }

    assert interrupting(_oracle_sections) == _CMARK_GFM_BLOCK_TAGS | set(_TYPE1_TAGS)
    assert interrupting(_ours) == set(_MARKDOWN_IT_BLOCK_TAGS) | set(_TYPE1_TAGS)


# ─── הטענה "אף קובץ אמיתי לא מושפע", מקובעת ולא רק נמדדת ───

#: סוגי הטוקנים שבתוכם שורה **אינה** יכולה לפתוח בלוק HTML באף פארסר: גדר קוד,
#: קוד מוזח ו-front matter.
_CODE_REGIONS = frozenset({"fence", "code_block", "front_matter"})

_DOCS_ROOT = _REPO / "docs"


def _divergence_trigger_lines(text: str) -> list[tuple[int, str]]:
    """‏(שורה, מפתח השורה בטבלה) לכל שורה בקובץ שיכולה להפעיל פער ידוע.

    **רק שורות בטבלה שיש להן** ``trigger`` **נסרקות.** לשורות שאין להן, הנימוק כתוב
    ליד כל אחת ב-``_KNOWN_DIVERGENCES``, וקובץ שמפעיל אותן נתפס רק בהשוואת המפות של
    ``scripts/compare_md_parser_to_cmark.py``.

    **לפי הפארסר ולא לפי כלל שנכתב ביד.** שורה בתוך גדר קוד, קוד מוזח או
    front matter אינה נספרת, ומה שקובע איפה האזורים האלה נמצאים הוא
    ``markdown-it`` עצמו (``_BLOCK_PROBE``) ולא סורק גדרות שכתבתי. זה ההבדל
    בין הבדיקה הזאת לסריקת שורות פשוטה: נמדד (2026-09-27) שבקבצים השמורים
    יש שורה ``<source src=...>`` בתוך בלוק ```` ```markdown ```` — המפה שלה
    אינה מושפעת, וסריקה פשוטה הייתה מדווחת עליה.

    **וגם שורה בתוך בלוק HTML שנפתח בשורה קודמת אינה נספרת** — למשל ``<source>``
    בתוך ``<video>``. שני הפארסרים כבר בתוך אותו בלוק, והוא נגמר אצל שניהם באותה
    שורה, ולכן השורה לא יכולה לחלוק. גם את זה קובע הפארסר: הטווח הוא ה-``map``
    של טוקן ``html_block`` של ``_BLOCK_PROBE``, בלי השורה הראשונה שלו.

    **ושני חריגים, בכוונה — בשניהם הבלוק אולי קיים רק אצלנו, ואז שום שורה בו אינה
    מוחרגת.** לפי ההשוואה בין ``HTML_SEQUENCES`` ו-``common/html_re.py`` של
    markdown-it-py לבין ``scanners.re`` של cmark-gfm, יש בדיוק שתי דרכים שבהן אצלנו
    נפתח בלוק HTML ואצל cmark-gfm לא, וכל חריג סוגר אחת מהן:

    - **שורת הפתיחה היא בעצמה טריגר** — רשימת התגיות, השורה השנייה בטבלה.
    - **יש בשורת הפתיחה תו מ-``_PYTHON_ONLY_SPACES``, בכל מקום בה** — ``\\s``, השורה
      החמישית. הטריגר שלה מסמן רק תו שצמוד לשם התגית, ובלי החריג הזה ``<search>``
      בתוך ``<video a="1"`` + NBSP + ``b="2">`` הייתה מוחרגת — והמפות שם חלוקות (נמדד).

    בכיוון ההפוך, כש-cmark-gfm פותח בלוק ואנחנו לא, אין אצלנו ``html_block`` — ולכן
    גם אין החרגה. ‏``test_a_source_inside_a_video_block_is_not_a_trigger`` מראה ששני
    הפארסרים מסכימים על הבלוקים האמיתיים, ושההחרגה היא רק בתוכם.

    **ומה שהיא עדיין סופרת, בכוונה:** שורה שמסכימה היום. ‏``<source>`` שלמה אחרי
    שורה ריקה היא בלוק HTML בשני הצדדים, אבל עריכה אחת שתצמיד אותה לפסקה תהפוך
    אותה לפער — כי ההסכמה תלויה בשורה שלפניה.
    """
    lines = text.replace("\r\n", "\n").split("\n")
    excluded: set[int] = set()
    html_blocks: list[tuple[int, int]] = []
    for token in _BLOCK_PROBE.parse("\n".join(lines), {}):
        if token.map is None:
            continue
        if token.type in _CODE_REGIONS:
            excluded.update(range(token.map[0], token.map[1]))
        elif token.type == "html_block":
            html_blocks.append((token.map[0], token.map[1]))
    keys_by_line: dict[int, list[str]] = {}
    for index, line in enumerate(lines):
        if index in excluded:
            continue
        keys = [
            row.key
            for row in _KNOWN_DIVERGENCES
            if row.trigger is not None and row.trigger.search(line)
        ]
        if keys:
            keys_by_line[index] = keys
    for start, end in html_blocks:
        if start in keys_by_line or _PYTHON_ONLY_SPACE_SET.intersection(lines[start]):
            continue  # הבלוק אולי קיים רק אצלנו — ראו את שני החריגים ב-docstring
        for index in range(start + 1, end):
            keys_by_line.pop(index, None)
    return [(index + 1, key) for index in sorted(keys_by_line) for key in keys_by_line[index]]


def _scan_for_divergence_triggers(root: Path) -> list[tuple[str, int, str]]:
    """‏(נתיב יחסי, שורה, מפתח) לכל טריגר בכל קובץ ``.md`` תחת ``root``.

    ‏``docs/*.md`` הם UTF-8 — MyST קורא אותם כך, ובניית התיעוד נכשלת אחרת. עמוד שאינו
    UTF-8 מפיל את הסריקה **עם שם הקובץ**, ולא ב-traceback של פענוח שאינו אומר איפה.
    """
    hits = []
    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(root).as_posix()
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AssertionError(
                f"{relative}: אינו UTF-8 ({exc.reason}, בבית {exc.start})"
            ) from exc
        for line, key in _divergence_trigger_lines(text):
            hits.append((relative, line, key))
    return hits


def test_no_markdown_page_under_docs_holds_a_known_divergence_trigger():
    """עמודי ה-Markdown תחת ``docs/`` אינם מכילים שורה שמפעילה פער ידוע **שיש לו טריגר**.

    רק לחלק מהשורות בטבלה יש ``trigger``; לאחרות הנימוק כתוב ליד כל אחת ב-
    ``_KNOWN_DIVERGENCES``, והן נתפסות רק בהשוואת המפות של הסקריפט.

    **למה ``docs/`` בלבד:** מבין הקורפוסים שהטענה מדברת עליהם, זה היחיד שה-CI רואה.
    ‏``amir-bug-patterns`` נבדק ב-``scripts/compare_md_parser_to_cmark.py`` — אותה
    פונקציה, על פי דרישה — והקבצים השמורים נמדדו פעם אחת במסד; שתי התוצאות מתוארכות
    ב-:ref:`mcp-md-known-divergences`.

    **וסריקה של כלום אינה הצלחה.** אם עמודי ה-``.md`` יעברו מ-``docs/``, הבדיקה הייתה
    ממשיכה לעבור בלי לבדוק דבר, ולכן היא דורשת קודם שיש מה לסרוק.
    """
    assert any(_DOCS_ROOT.rglob("*.md")), (
        f"אפס עמודי .md תחת {_DOCS_ROOT} — סריקה של כלום אינה הצלחה"
    )
    hits = _scan_for_divergence_triggers(_DOCS_ROOT)
    causes = {row.key: row.cause for row in _KNOWN_DIVERGENCES}
    assert not hits, (
        "שורה בעמוד תיעוד מפעילה פער ידוע מ-GitHub — מפת הסעיפים שלנו יכולה "
        "לחלוק כאן על GitHub:\n"
        + "\n".join(f"  docs/{path}:{line} — {causes[key]}" for path, line, key in hits)
        + "\nכל שורה כזאת נספרת, בכוונה — גם כשהמפות מסכימות היום, כי ההסכמה תלויה "
        "בשורה שלפניה. לא נספרות רק שורות בתוך בלוק קוד, ושורות בתוך בלוק HTML שנפתח "
        "בשורה קודמת, כמו <source> בתוך <video> (ראו _divergence_trigger_lines). "
        "כדי לעבור: עטפו את השורה בבלוק קוד."
    )


def test_the_trigger_scan_catches_a_tag_outside_code_and_ignores_it_inside(tmp_path):
    """הבדיקה שלמעלה מסוגלת ליפול — ואינה נופלת על מה שאינו משפיע.

    קבצים שתולים, דרך אותה פונקציית סריקה בדיוק: תגית מחוץ לבלוק קוד
    נתפסת (בכל רישיות), ובתוך גדר קוד, קוד מוזח או front matter — לא.
    """
    planted = {
        "outside.md": "# א\n\nטקסט\n<source>\n## ב\n",
        "outside_upper.md": "# א\n\n<SEARCH> טקסט\n",
        "inside_fence.md": "# א\n\n```html\n<source src=\"x\">\n```\n",
        "inside_indented.md": "# א\n\n    <search>\n",
        "inside_front_matter.md": "---\n<source>\n---\n# א\n",
    }
    for name, text in planted.items():
        (tmp_path / name).write_text(text, encoding="utf-8")

    hits = _scan_for_divergence_triggers(tmp_path)

    key = "commonmark_0_31_block_tag_list"
    assert hits == [("outside.md", 4, key), ("outside_upper.md", 3, key)], hits


#: הטמעות וידאו, אודיו ותמונה מותאמת — הצורה שבה ``<source>`` מופיעה בעמודים
#: אמיתיים, כמו בהצעה ב-``FEATURE_SUGGESTIONS/COMPREHENSIVE_FEATURE_SUGGESTIONS_NOV_2025.md``.
#: ‏``## בתוך`` יושבת בתוך הבלוק בכוונה: אם אחד הפארסרים היה סוגר את הבלוק לפני
#: שורת ה-``<source>``, הכותרת הייתה מופיעה אצלו, והמפות היו חלוקות.
_EMBEDDED_SOURCES = {
    "video.md": (
        "# א\n\n<video controls width=\"100%\">\n"
        "  <source src=\"demo.mp4\" type=\"video/mp4\">\n## בתוך\n</video>\n"
    ),
    "audio.md": "# א\n\n<audio controls>\n<source src=\"a.ogg\">\n## בתוך\n</audio>\n",
    "picture.md": (
        "# א\n\n<picture>\n  <source srcset=\"a.webp\" type=\"image/webp\">\n"
        "## בתוך\n  <img src=\"a.png\">\n</picture>\n"
    ),
}


def test_a_source_inside_a_video_block_is_not_a_trigger(tmp_path):
    """‏``<source>`` בתוך בלוק HTML שנפתח בשורה קודמת אינה טריגר — ומחוצה לו, כן.

    שלושה דברים, וכל אחד מהם יכול ליפול בנפרד:

    1. **שני הפארסרים מסכימים על הטמעות אמיתיות**, כולל ``## בתוך`` שנבלעת אצל שניהם.
       זו ההנחה שההחרגה נשענת עליה, והיא נמדדת כאן ולא מונחת.
    2. **הסריקה אינה מדווחת עליהן.**
    3. **והיא עדיין מדווחת** על ``<source>`` שעומדת לבדה, ועל שורת טריגר בתוך בלוק
       שאולי קיים רק אצלנו: בלוק ששורת הפתיחה שלו היא בעצמה טריגר, ובלוק ששורת
       הפתיחה שלו נושאת NBSP בין מאפיינים — ושם המפות באמת חלוקות, וזה נבדק כאן.
    """
    for name, text in _EMBEDDED_SOURCES.items():
        assert _ours(text) == _oracle_sections(text) == [(1, 1)], (name, _ours(text))
        (tmp_path / name).write_text(text, encoding="utf-8")
    (tmp_path / "standalone.md").write_text("# א\n\nטקסט\n<source>\n## ב\n", encoding="utf-8")
    (tmp_path / "opened_by_a_trigger.md").write_text(
        "# א\n\n<search>\n<source>\n", encoding="utf-8"
    )
    only_ours = '# א\n\n<video a="1"\xa0b="2">\n<search>\n## ב\n'
    assert _ours(only_ours) != _oracle_sections(only_ours), "הבלוק אמור להיות רק אצלנו"
    (tmp_path / "opened_with_a_python_only_space.md").write_text(only_ours, encoding="utf-8")

    hits = _scan_for_divergence_triggers(tmp_path)

    key = "commonmark_0_31_block_tag_list"
    assert hits == [
        ("opened_by_a_trigger.md", 3, key),
        ("opened_by_a_trigger.md", 4, key),
        ("opened_with_a_python_only_space.md", 4, key),
        ("standalone.md", 4, key),
    ], hits


def test_a_space_that_only_python_calls_a_space_is_a_trigger(tmp_path):
    """הטריגרים עוקבים אחרי ``\\s`` של הפארסר, ולא אחרי רווח וטאב שנבחרו ביד.

    ‏``<search`` ואחריה NBSP חולקת על GitHub, וכך גם ``<div`` ואחריה NBSP — בשתי שורות
    שונות בטבלה. ‏``<source`` ואחריה U+3000 שייכת לשורה השנייה בלבד, לפי כלל השיוך.
    והבקרה: ``<div`` עם רווח רגיל אינה טריגר בכלל.
    """
    planted = {
        "a_search_nbsp.md": "# א\n\nטקסט\n<search\xa0class=\"x\">\n## ב\n",
        "b_div_nbsp.md": "# א\n\nטקסט\n<div\xa0class=\"x\">\n## ב\n",
        "c_source_ideographic.md": "# א\n\n<source　>\n",
        "d_div_ascii.md": "# א\n\nטקסט\n<div class=\"x\">\n## ב\n",
    }
    for name, text in planted.items():
        (tmp_path / name).write_text(text, encoding="utf-8")

    hits = _scan_for_divergence_triggers(tmp_path)

    assert hits == [
        ("a_search_nbsp.md", 4, "commonmark_0_31_block_tag_list"),
        ("b_div_nbsp.md", 4, "python_only_space_in_tag"),
        ("c_source_ideographic.md", 3, "commonmark_0_31_block_tag_list"),
    ], hits


def test_a_page_that_is_not_utf8_fails_the_scan_by_name(tmp_path):
    """עמוד שאינו UTF-8 מפיל את הסריקה עם שם הקובץ, ולא ב-traceback של פענוח."""
    (tmp_path / "latin.md").write_bytes("# ä\n".encode("latin-1"))

    with pytest.raises(AssertionError, match="latin.md"):
        _scan_for_divergence_triggers(tmp_path)


def test_the_documentation_table_is_this_table():
    """הסעיף ב-``docs/mcp-server.rst`` מעתיק מהטבלה — וזה נבדק, לא מקווה.

    **בכל שורה בנפרד:** הסיבה, "N מתוך M צורות שנמדדו", על מה ומתי נמדד, והקישור
    ל-upstream כשיש. כל עובדה נחפשת **בתוך השורה שלה** בטבלה שבעמוד, ולא בכל הסעיף,
    אחרת החלפה של מספרים בין שתי שורות הייתה עוברת. מה שכל צד מחזיר **אינו** מושווה
    כאן: הדוגמאות עצמן נבדקות מול שני הפארסרים ב-
    ``test_each_row_example_returns_what_the_table_says``.

    **וגם המספרים בפסקאות שמתחת לטבלה נגזרים**, מאותן הגדרות שהמשפחות בנויות מהן:
    גודל המטריצה של ``source``/``search``, התקרה של השורה השלישית, והגודל והמידות
    של הטבלה לדוגמה שלה, שלושת הסוגים של הגדרות הקישור, ומספר התווים והתגיות של
    השורה החמישית. ``unreachable`` של כל שורה שיש לה מועתק כלשונו לפסקה שלה.
    """
    rst = (_REPO / "docs" / "mcp-server.rst").read_text(encoding="utf-8")
    start = rst.index(".. _mcp-md-known-divergences:")
    section = rst[start:rst.index("\n.. _", start + 1)]
    table_rows = [chunk.split("\n\n", 1)[0] for chunk in section.split("\n   * - ")[1:]]
    for row in _KNOWN_DIVERGENCES:
        own = [cells for cells in table_rows if cells.startswith(row.cause)]
        assert len(own) == 1, (row.key, "השורה בעמוד לא נמצאה, או נמצאה פעמיים")
        measured, disagree = _row_counts(row)
        facts = [
            row.cause,
            f"{disagree:,} מתוך {measured:,} צורות שנמדדו",
            row.measured_on,
            row.measured_at,
        ]
        if row.upstream:
            facts.append(row.upstream)
        missing = [fact for fact in facts if fact not in own[0]]
        assert not missing, (row.key, missing)

    tags, forms, contexts = (
        len(_BLOCK_TAG_LIST_TAGS), len(_BLOCK_TAG_LIST_FORMS), len(_BLOCK_TAG_LIST_CONTEXTS)
    )
    reference_kinds = collections.Counter(
        _reference_kind(previous, variant, following)
        for previous, variant, following, _text in _reference_cells()
    )
    (table_example,) = _KNOWN_DIVERGENCES_BY_KEY["table_over_autocomplete_cap"].examples
    # הרוחב והאורך של הטבלה לדוגמה, כפי שתא הצורה בשורה השלישית מתאר אותם — נקראים
    # מהטקסט של הדוגמה עצמה: שורת הכותרות היא השלישית, וכל שורת גוף היא ``x``.
    table_lines = table_example.text.split("\n")
    details = [
        f"נמדדו {tags * forms * contexts} צורות: {tags} תגיות, {forms} צורות כתיבה",
        f"ו-{contexts} הקשרים",
        f"``MAX_AUTOCOMPLETED_CELLS`` ({_TABLE_AUTOCOMPLETE_CAP:,})",
        f"{len(table_example.text.encode('utf-8')):,} בתים",
        f"טבלה ברוחב {table_lines[2].count('|a')} עמודות עם {table_lines.count('x')} שורות גוף",
        f"**{reference_kinds['line']} — אותה כותרת, בשורה אחרת.**",
        f"**{reference_kinds['github_only']} — כותרת שיש רק ב-GitHub.**",
        f"**{reference_kinds['ours_only']} — כותרת שיש רק אצלנו.**",
        f"ב-{len(_PYTHON_ONLY_SPACES)} תווים",
        f"ב-{len(_HTML_BLOCK_TAGS)} תגיות הבלוק",
        f"ב-{len(_TYPE1_TAGS)} התגיות מסוג 1",
    ]
    # ומה שכתוב בשורה עצמה על פער שאינו נגיש דרך הכלי — מועתק כלשונו.
    details += [row.unreachable for row in _KNOWN_DIVERGENCES if row.unreachable]
    missing = [fact for fact in details if fact not in section]
    assert not missing, missing


# ════════════════════════════════════════════════════════════════════
# המספר שבפרוזה נגזר מכאן, ולא מוקלד פעמיים
# ════════════════════════════════════════════════════════════════════

#: כל משפחה שעוברת **כולה** ב-``_compare``, בשמה. זו הרשימה היחידה שלהן: ממנה נגזר
#: המספר שבפרוזה (``test_the_generated_shape_count_matches_the_prose``), וממנה מצלם
#: ``scripts/md_parser_upgrade_zero_diff.py``. המשפחות של השורות בטבלה אינן כאן — הן
#: נגזרות מ-``_KNOWN_DIVERGENCES``. **משפחה חדשה נרשמת כאן**, ורק אז היא נספרת
#: ומצולמת; משפחה שלא נרשמה לא תיספר, והמספר בפרוזה ימשיך להתאים בלעדיה.
_COMPARED_FAMILIES: dict[str, Callable[[], Iterable[str]]] = {
    "context_matrix": _context_shapes,
    "fence_nesting": _fence_nesting_shapes,
    "html_blocks": _html_shapes,
    "html_edge_cases": lambda: iter(_HTML_EDGE_CASES),
    "tables": _table_shapes,
    "containers": lambda: iter(_CONTAINER_SHAPES),
    "html_block_tags": _html_tag_shapes,
}


def test_the_generated_shape_count_matches_the_prose():
    """כמה צורות באמת מושוות, ומה הדוקסטרינג מצהיר.

    **זה כבר נסחף.** ``services/md_parser.py`` אמר 11,400,
    ``requirements/base.txt`` אמר 11,507, והמחוללים ייצרו מספר שלישי —
    כי משפחת הטבלאות נוספה בלי שאיש עדכן את המשפטים. מספר שמוקלד ביד
    מתיישן בשקט; מספר שנגזר מהקוד מפיל את החבילה.

    הספירה היא על ``_COMPARED_FAMILIES``, ועוד החצי המסכים של כל שורה ב-
    ``_KNOWN_DIVERGENCES``; החצי החולק נכנס למספר המוחרגות. שניהם נגזרים
    מהטבלה, כך ששורה חדשה בה מזיזה את שניהם.
    """
    counts = [_row_counts(row) for row in _KNOWN_DIVERGENCES]
    total = sum(len(list(family())) for family in _COMPARED_FAMILIES.values()) + sum(
        measured - disagree for measured, disagree in counts
    )
    excluded = sum(disagree for _measured, disagree in counts)
    assert total > 10_000, f"מחולל נשמט מהספירה — {total} צורות בלבד"
    assert excluded > 0, "הטבלה ריקה מפערים — הפרוזה על 'הפערים הידועים' כבר אינה נכונה"

    source = (_REPO / "services" / "md_parser.py").read_text(encoding="utf-8")
    quoted = re.search(r"על \*\*([\d,]+) צורות מחוללות\*\*", source)
    assert quoted, "המשפט על מספר הצורות אינו במקומו ב-``md_parser`` docstring"
    assert quoted.group(1) == f"{total:,}", (
        f"הדוקסטרינג אומר {quoted.group(1)} והמחוללים מייצרים {total:,}. "
        "עדכן את שני המקומות שמצטטים אותו — ``services/md_parser.py`` "
        "ו-``requirements/base.txt``."
    )
    # **וגם מספר הצורות המוחרגות נגזר, לא מוקלד.** אותה סחיפה בדיוק מחכה
    # לו: תגית שתתווסף ל-``_TYPE7_TAGS``, או שורה חדשה בטבלה, בלי עדכון המשפט.
    quoted_excluded = re.search(r"\*\*([\d,]+) צורות\*\* בסך הכול", source)
    assert quoted_excluded, "המשפט על הצורות המוחרגות אינו במקומו ב-``md_parser`` docstring"
    assert quoted_excluded.group(1) == f"{excluded:,}"

    base = (_REPO / "requirements" / "base.txt").read_text(encoding="utf-8")
    assert f"{total:,} הצורות" in base, (
        f"``requirements/base.txt`` אינו אומר {total:,} — אותו מספר, שני מקומות."
    )


# ════════════════════════════════════════════════════════════════════
# טקסט הכותרת — התוספת של SUGG-010, על תת-קבוצה ובמפורש
# ════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("bucket", range(6))
def test_the_heading_text_agrees_with_cmark_where_it_can_be_compared(bucket):
    """אותה מטריצה בדיוק, והפעם על **הטקסט** ולא על המיקום.

    מושווה רק מה שאין בו סימון פנימי — ההנמקה המלאה ב-
    ``_compare_titles``. הדלי זהה לזה של מבחן המיקום, מאותה סיבה:
    ‏``pytest.ini`` קובע ``timeout = 60``.
    """
    shapes = [s for i, s in enumerate(_context_shapes()) if i % 6 == bucket]
    compared = _compare_titles(shapes)
    # ‏**"אפס אי-הסכמות" על אפס השוואות אינו הצלחה.** בלי השורה הזאת,
    # שינוי ב-``_has_inline_markup`` שיחריג בטעות את כל הכותרות היה
    # משאיר את הטסט ירוק בזמן שהוא כבר לא בודק דבר.
    assert compared > 100, f"רק {compared} כותרות הושוו — הסינון בלע את הטבלה"


#: הצורות שהמבחן למעלה מדלג עליהן, וכאן נאמר **למה**: לכל אחת, מה
#: אנחנו מחזירים מול מה ש-cmark מחזיר אחרי הרינדור.
_RENDERED_AWAY = [
    ("## כותרת עם `בקטיקים`", "כותרת עם `בקטיקים`", "כותרת עם בקטיקים"),
    ("## **מודגש**", "**מודגש**", "מודגש"),
    ("## [קישור](https://example.com)", "[קישור](https://example.com)", "קישור"),
    ("## כותרת עם \\# escape", "כותרת עם \\# escape", "כותרת עם # escape"),
]


@pytest.mark.parametrize("source, ours, cmark", _RENDERED_AWAY)
def test_a_heading_with_inline_markup_is_excluded_on_purpose(source, ours, cmark):
    """ההחרגה נאמרת בקול, כדי שלא תיראה כמו חור בכיסוי.

    לכל צורה כאן שלוש טענות: הכותרת שלנו היא המקור הגולמי, של cmark
    היא הטקסט אחרי הרינדור, **והשתיים באמת נבדלות**. זו הסיבה שהן
    מוחרגות — ולא הנחה על מה שאולי יקרה.

    .. note::

       **הטסט הזה אינו יכול ליפול על הקוד שלפני הסבב הזה, וזה מכוון.**
       הוא אינו שומר על תיקון אלא מקבע החלטה שלא השתנתה: שהכותרת אצלנו
       היא המקור הגולמי. מי ש"יתקן" את ``_title_of`` להסיר גם סימון —
       כלומר להחזיר טקסט מרונדר — יפיל אותו. ואת הכיוון ההפוך, צמצום
       של ``_has_inline_markup`` שיפסיק להחריג אחת מהצורות, מפיל מבחן
       הטקסט שלמעלה.
    """
    text = f"{source}\n"
    assert _has_inline_markup(ours), "הצורה הזאת אמורה להיות מוחרגת"
    assert [s.title for s in parse_document(text).sections] == [ours]
    assert [title for _, _, title in _oracle_titles(text)] == [cmark]
    assert ours != cmark, "אילו השתיים היו זהות, לא היה טעם להחריג"
