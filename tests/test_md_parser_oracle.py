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
``_KNOWN_DIVERGENCES``**:** תגית HTML מסוג 7 שצמודה לשורת מכל (שם
``markdown-it`` סוטה מ-cmark-gfm וממימוש הייחוס של המפרט; האישו upstream
הוא executablebooks/markdown-it-py#434), ורשימת תגיות הבלוק של CommonMark
0.31.2 — ``source``/``search`` — ש-``markdown-it-py`` עובד לפיה מאז 4.0.0
ו-cmark-gfm עוד לא. הצורות החולקות **אינן** עוברות ב-``_compare`` — הן
עוברות בטסט שמאשר את הפער המדוד, ובטסט שמאשר שהמוחרג הוא בדיוק הן ולא
יותר. לכל שורה בטבלה: הסיבה, צורה לדוגמה ומה כל צד מחזיר עליה, על מה ומתי
נמדדה, וקישור ל-upstream כשיש; ``docs/mcp-server.rst`` מעתיק ממנה, וטסט
משווה.

**והחלוקה לכמה טסטים אינה קוסמטית:** ``pytest.ini`` קובע
``timeout = 60`` לכל טסט, וטבלה אחת גדולה הייתה מתקרבת לשם.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

import cmarkgfm
import pytest
from cmarkgfm.cmark import Options
from markdown_it import MarkdownIt
from mdit_py_plugins.front_matter import front_matter_plugin

from services.md_parser import parse_document

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
    return [(s.level, s.heading_line) for s in parse_document(text).sections]


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
# הפערים הידועים מ-GitHub — שתי משפחות, טבלה אחת (``_KNOWN_DIVERGENCES``)
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
    אפס מופעים ב-521 הקבצים האמיתיים שנמדדו (93 + 428).
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
    שיכולה להפעיל את הפער (ראו ``_divergence_trigger_lines``), ו-``closed`` —
    צורות שבהן פער **נסגר**, כלומר שני הצדדים מסכימים היום על מה שבגרסה
    קודמת חלקו עליו: מידע למי שיקרא את זה בעוד חצי שנה, ומקובע בטסט.
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


#: על מה נמדדה הטבלה. אותו מחרוזת בשתי השורות ובתיעוד, וטסט משווה.
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
        # תנאי הפתיחה של סוג 6 במפרט: עד שלושה רווחים, ``<`` או ``</``, השם,
        # ואחריו רווח, ``>``, ``/>`` או סוף שורה — בלי תלות ברישיות. השמות
        # נלקחים מ-``_BLOCK_TAG_LIST_TAGS`` ולא מוקלדים פעם שנייה.
        trigger=re.compile(
            r"^ {0,3}</?(?:" + "|".join(_BLOCK_TAG_LIST_TAGS) + r")(?=[ \t]|/?>|$)", re.IGNORECASE
        ),
        closed=(
            _Example("## לפני\n\n- פריט\n<search>\n## אחרי\n", github=((2, 1),), ours=((2, 1),)),
        ),
    ),
)


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


# ─── הטענה "אף קובץ אמיתי לא מושפע", מקובעת ולא רק נמדדת ───

#: סוגי הטוקנים שבתוכם שורה **אינה** יכולה לפתוח בלוק HTML באף פארסר: גדר קוד,
#: קוד מוזח ו-front matter.
_CODE_REGIONS = frozenset({"fence", "code_block", "front_matter"})

_DOCS_ROOT = _REPO / "docs"


def _divergence_trigger_lines(text: str) -> list[tuple[int, str]]:
    """‏(שורה, מפתח השורה בטבלה) לכל שורה בקובץ שיכולה להפעיל פער ידוע.

    **לפי הפארסר ולא לפי כלל שנכתב ביד.** שורה בתוך גדר קוד, קוד מוזח או
    front matter אינה נספרת, ומה שקובע איפה האזורים האלה נמצאים הוא
    ``markdown-it`` עצמו (``_BLOCK_PROBE``) ולא סורק גדרות שכתבתי. זה ההבדל
    בין הבדיקה הזאת לסריקת שורות פשוטה: נמדד (2026-09-27) שבקבצים השמורים
    יש שורה ``<source src=...>`` בתוך בלוק ```` ```markdown ```` — המפה שלה
    אינה מושפעת, וסריקה פשוטה הייתה מדווחת עליה.

    **ומה שהיא כן סופרת, בכוונה:** שורה שהיא המשך של בלוק HTML שנפתח
    בתגית אחרת. שם שני הפארסרים כבר בתוך אותו בלוק ולכן מסכימים — אבל
    הקביעה הזאת תלויה בתגית שפתחה אותו, והבדיקה מעדיפה דיווח שיש לבדוק
    על השמטה שקטה.
    """
    lines = text.replace("\r\n", "\n").split("\n")
    excluded: set[int] = set()
    for token in _BLOCK_PROBE.parse("\n".join(lines), {}):
        if token.type in _CODE_REGIONS and token.map is not None:
            excluded.update(range(token.map[0], token.map[1]))
    hits = []
    for index, line in enumerate(lines):
        if index in excluded:
            continue
        for row in _KNOWN_DIVERGENCES:
            if row.trigger is not None and row.trigger.search(line):
                hits.append((index + 1, row.key))
    return hits


def _scan_for_divergence_triggers(root: Path) -> list[tuple[str, int, str]]:
    """‏(נתיב יחסי, שורה, מפתח) לכל טריגר בכל קובץ ``.md`` תחת ``root``."""
    hits = []
    for path in sorted(root.rglob("*.md")):
        text = path.read_bytes().decode("utf-8")
        for line, key in _divergence_trigger_lines(text):
            hits.append((path.relative_to(root).as_posix(), line, key))
    return hits


def test_no_markdown_page_under_docs_holds_a_known_divergence_trigger():
    """עמודי ה-Markdown תחת ``docs/`` אינם מכילים שורה שמפעילה פער ידוע.

    **למה ``docs/`` בלבד:** זה הקורפוס היחיד שה-CI רואה. ``amir-bug-patterns``
    נבדק ב-``scripts/compare_md_parser_to_cmark.py`` — אותה פונקציה, על פי
    דרישה — והקבצים השמורים נמדדו פעם אחת במסד; שתי התוצאות מתוארכות ב-
    :ref:`mcp-md-known-divergences`.
    """
    hits = _scan_for_divergence_triggers(_DOCS_ROOT)
    causes = {row.key: row.cause for row in _KNOWN_DIVERGENCES}
    assert not hits, (
        "שורה בעמוד תיעוד מפעילה פער ידוע מ-GitHub — מפת הסעיפים שלנו יכולה "
        "לחלוק כאן על GitHub ועל MyST:\n"
        + "\n".join(f"  docs/{path}:{line} — {causes[key]}" for path, line, key in hits)
        + "\nאם השורה נחוצה: עטפו אותה בבלוק קוד, או הפרידו אותה בשורה ריקה "
        "וכתבו את התגית שלמה ולבדה בשורה (החוק ב-_block_tag_list_agrees)."
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


def test_the_documentation_table_is_this_table():
    """הסעיף ב-``docs/mcp-server.rst`` מעתיק מהטבלה — וזה נבדק, לא מקווה.

    לכל שורה: הסיבה, "N מתוך M צורות שנמדדו", על מה ומתי נמדד, והקישור
    ל-upstream כשיש. המספרים נגזרים מהמשפחות ולא מוקלדים כאן פעם נוספת.
    """
    rst = (_REPO / "docs" / "mcp-server.rst").read_text(encoding="utf-8")
    start = rst.index(".. _mcp-md-known-divergences:")
    section = rst[start:rst.index("\n.. _", start + 1)]
    for row in _KNOWN_DIVERGENCES:
        measured, disagree = _row_counts(row)
        facts = [
            row.cause,
            f"{disagree} מתוך {measured} צורות שנמדדו",
            row.measured_on,
            row.measured_at,
        ]
        if row.upstream:
            facts.append(row.upstream)
        missing = [fact for fact in facts if fact not in section]
        assert not missing, (row.key, missing)


# ════════════════════════════════════════════════════════════════════
# המספר שבפרוזה נגזר מכאן, ולא מוקלד פעמיים
# ════════════════════════════════════════════════════════════════════

def test_the_generated_shape_count_matches_the_prose():
    """כמה צורות באמת מושוות, ומה הדוקסטרינג מצהיר.

    **זה כבר נסחף.** ``services/md_parser.py`` אמר 11,400,
    ``requirements/base.txt`` אמר 11,507, והמחוללים ייצרו מספר שלישי —
    כי משפחת הטבלאות נוספה בלי שאיש עדכן את המשפטים. מספר שמוקלד ביד
    מתיישן בשקט; מספר שנגזר מהקוד מפיל את החבילה.

    הספירה כאן חייבת לכלול **כל** משפחה שמגיעה ל-``_compare``. משפחה
    חדשה שתישכח כאן תוריד את הסכום ותפיל — וזו התוצאה הרצויה. החצי המסכים
    של כל שורה ב-``_KNOWN_DIVERGENCES`` נכנס לסכום, והחצי החולק — למספר
    המוחרגות; שניהם נגזרים מהטבלה, כך ששורה חדשה בה מזיזה את שניהם.
    """
    counts = [_row_counts(row) for row in _KNOWN_DIVERGENCES]
    total = (
        len(list(_context_shapes()))
        + len(list(_fence_nesting_shapes()))
        + len(list(_html_shapes()))
        + len(_HTML_EDGE_CASES)
        + len(list(_table_shapes()))
        + len(_CONTAINER_SHAPES)
        + sum(measured - disagree for measured, disagree in counts)
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
    quoted_excluded = re.search(r"\*\*(\d+) צורות\*\* בסך הכול", source)
    assert quoted_excluded, "המשפט על הצורות המוחרגות אינו במקומו ב-``md_parser`` docstring"
    assert quoted_excluded.group(1) == str(excluded)

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
