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

**ומה שהקובץ הזה אינו עושה, כדי שזה לא ייקרא כהשמטה:** הוא **אינו מריץ
אף קובץ אמיתי**. זו החלטה. קורפוס אמיתי הוא בדיקת שפיות חד-פעמית ולא
רשת שתופסת רגרסיה עתידית, והוא היה דורש להחזיק בריפו הזה עותק של תוכן
שאינו שלו. ההרצה על קורפוס אמיתי נעשית על פי דרישה, עם
``scripts/compare_md_parser_to_cmark.py`` — לפני שלב 2, אחרי שדרוג של
``markdown-it-py``, וכשנוגעים בפארסר.

**מה בדיוק מושווה, כדי שהתוצאה לא תיקרא רחבה ממה שהיא.** ההשוואה
הראשית — ``_compare`` — היא על **הרמה ומספר השורה** של כל כותרת ברמת
המסמך, ולא על טקסט הכותרת. "אפס אי-הסכמות" היא לכן טענה על **גבולות**:
היכן מתחיל סעיף ואיזו רמה הוא. טקסט הכותרת מושווה בנפרד, ב-
``_compare_titles``, ורק על תת-קבוצה — ההנמקה שם.

**ולטענה יש חריג אחד ידוע, והוא מקובע ולא מושתק:** תגית HTML מסוג 7
שצמודה לשורת מכל — פריט רשימה או ציטוט. שם ``markdown-it`` סוטה
מ-cmark-gfm וממימוש הייחוס של המפרט, והצורות האלה **אינן** עוברות
ב-``_compare`` — הן עוברות בטסט שמאשר את הפער המדוד, ובטסט שמאשר
שהמוחרג הוא בדיוק הן ולא יותר. ``_type7_after_container_shapes`` מנמק.

**והחלוקה לכמה טסטים אינה קוסמטית:** ``pytest.ini`` קובע
``timeout = 60`` לכל טסט, וטבלה אחת גדולה הייתה מתקרבת לשם.
"""

from __future__ import annotations

import itertools
from html.parser import HTMLParser

import cmarkgfm
import pytest
from cmarkgfm.cmark import Options
from markdown_it import MarkdownIt
from mdit_py_plugins.front_matter import front_matter_plugin

from services.md_parser import parse_document

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
# הפער הידוע היחיד — תגית HTML מסוג 7 צמודה לשורת מכל (פריט רשימה או ציטוט)
# ════════════════════════════════════════════════════════════════════

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

    **זו המחלקה היחידה שידועה בה אי-הסכמה**, והיא נמדדה: כשהתגית
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
    ולא לכלל שנכתוב ביד. **מתועד upstream** — טקסט האישו המלא, עם שלושת המימושים והצורה המינימלית,
    בגוף PR #3418; הוא נפתח מסשן שיש לו גישה ל-``executablebooks/markdown-it-py``
    ומספרו יוכנס כאן.
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
       עוברת לחצי המסכים של המשפחה, והמשפט על "המחלקה הידועה היחידה"
       ב-``services/md_parser.py`` נמחק יחד איתה. אל "תתקן" את הטסט
       הזה כאילו היה באג.
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
    חדשה שתישכח כאן תוריד את הסכום ותפיל — וזו התוצאה הרצויה.
    """
    import re
    from pathlib import Path

    type7 = list(_type7_after_container_shapes())
    total = (
        len(list(_context_shapes()))
        + len(list(_fence_nesting_shapes()))
        + len(list(_html_shapes()))
        + len(_HTML_EDGE_CASES)
        + len(list(_table_shapes()))
        + len(_CONTAINER_SHAPES)
        + sum(1 for _text, agrees in type7 if agrees)
        + len(_TYPE7_INDENTED_AGREEING)
    )
    excluded = sum(1 for _text, agrees in type7 if not agrees)
    assert total > 10_000, f"מחולל נשמט מהספירה — {total} צורות בלבד"
    assert excluded > 0, "המחלקה המוחרגת ריקה — הפרוזה על 'מחלקה ידועה אחת' כבר אינה נכונה"

    source = (Path(__file__).resolve().parents[1] / "services" / "md_parser.py").read_text(
        encoding="utf-8"
    )
    quoted = re.search(r"על \*\*([\d,]+) צורות מחוללות\*\*", source)
    assert quoted, "המשפט על מספר הצורות אינו במקומו ב-``md_parser`` docstring"
    assert quoted.group(1) == f"{total:,}", (
        f"הדוקסטרינג אומר {quoted.group(1)} והמחוללים מייצרים {total:,}. "
        "עדכן את שני המקומות שמצטטים אותו — ``services/md_parser.py`` "
        "ו-``requirements/base.txt``."
    )
    # **וגם המספר של המחלקה המוחרגת נגזר, לא מוקלד.** אותה סחיפה בדיוק
    # מחכה לו: תגית שתתווסף ל-``_TYPE7_TAGS`` בלי עדכון המשפט.
    quoted_excluded = re.search(r"מחלקה אחת ידועה ומקובעת של \*\*(\d+) צורות\*\*", source)
    assert quoted_excluded, "המשפט על המחלקה המוחרגת אינו במקומו ב-``md_parser`` docstring"
    assert quoted_excluded.group(1) == str(excluded)

    base = (Path(__file__).resolve().parents[1] / "requirements" / "base.txt").read_text(
        encoding="utf-8"
    )
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
