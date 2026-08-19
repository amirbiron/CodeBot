"""אוכף מיעון עמיד של הטמעות קוד בתיעוד.

הבאג שהבדיקות כאן מונעות: בלוקי ``literalinclude`` שמוענו לפי מספרי
שורות (``:lines:``) המשיכו להציג את הטווח הישן אחרי שהקוד זז — שמונה
מתוך עשרה בלוקים הציגו קוד לא קשור, אחד מהם במרחק 2,900 שורות מהיעד
המוצהר בכיתוב. זה דפוס ``line-number-coupling`` (amir-bug-patterns).

שני כללים נאכפים:

1. אין ``:lines:`` תחת ``literalinclude`` — במקומו ``:pyobject:`` לפונקציה
   שלמה, או ``:start-after:``/``:end-before:`` עם הערות סימון לקטע.
2. כל סימון שהתיעוד מפנה אליו קיים בקובץ המקור **פעם אחת בדיוק** —
   marker חסר מפיל את הבנייה ברעש (אזהרת docutils תחת ``-W``), אבל
   marker כפול היה מרנדר את הקטע מהמופע הראשון בלי שום אזהרה.

מה לא מכוסה כאן, בכוונה: הפניות שורה בפרוזה ("ראו ``main.py:739``").
אלה נשארות בטריגר של ``line-number-coupling`` לקריאה אנושית.
"""

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

# בלוק literalinclude שלם: שורת הפתיחה + כל שורות האופציות המוזחות אחריה
# ``[ \t]*`` ולא ``\s*``: עם MULTILINE, ``\s*`` בולע את שורת הריק שלפני
# הבלוק, ה-indent נלכד כ-"\n", וההפניה-לאחור דורשת שכל שורת אופציה תתחיל
# בירידת שורה — כלומר opts יוצא ריק תמיד והבדיקה עוברת על כלום.
# ובאופציות ``[ \t]+`` ולא שלושה רווחים בדיוק: RST מקבל כל הזחה עקבית,
# ובלוק עם ארבעה רווחים היה חומק מהבדיקה כולה.
_BLOCK_RE = re.compile(
    r"^(?P<indent>[ \t]*)\.\. literalinclude:: (?P<target>\S+)\n"
    r"(?P<opts>(?:(?P=indent)[ \t]+:.*\n)*)",
    re.MULTILINE,
)


def _blocks(root=None):
    for rst in sorted((root or DOCS).rglob("*.rst")):
        if "_build" in rst.parts:
            continue
        text = rst.read_text(encoding="utf-8")
        for m in _BLOCK_RE.finditer(text):
            yield rst, m.group("target"), m.group("opts")


def test_no_line_number_addressing():
    """אף בלוק לא ממוען לפי מספרי שורות."""
    offenders = [
        f"{rst.relative_to(ROOT)} ← {target}"
        for rst, target, opts in _blocks()
        if ":lines:" in opts
    ]
    assert not offenders, (
        "בלוקים ממוענים לפי מספרי שורות — הקוד יזוז והתיעוד יציג קוד שגוי "
        "בלי אזהרה. השתמשו ב-:pyobject: לפונקציה שלמה, או בהערות סימון "
        "docs:<שם>:start/end עם :start-after:/:end-before: לקטע. "
        "ראו docs/doc-authoring.rst.\n" + "\n".join(offenders)
    )


def test_nonstandard_option_indent_is_still_caught(tmp_path):
    """בלוק שהאופציות שלו מוזחות בארבעה רווחים לא חומק מהסריקה.

    רגרסיה: הגרסה הראשונה של ה-regex דרשה שלושה רווחים בדיוק, ולכן
    ``:lines:`` בהזחה אחרת עבר את test_no_line_number_addressing בשקט.
    """
    (tmp_path / "page.rst").write_text(
        "כותרת\n======\n\n"
        ".. literalinclude:: ../x.py\n"
        "    :language: python\n"
        "    :lines: 1-5\n",
        encoding="utf-8",
    )
    found = [(t, o) for _, t, o in _blocks(root=tmp_path)]
    assert found and ":lines:" in found[0][1], (
        "בלוק בהזחת 4 רווחים לא זוהה — ה-regex התכווץ בחזרה"
    )


def _referenced_markers():
    """כל (קובץ מקור, marker) שהתיעוד מפנה אליו."""
    refs = []
    for rst, target, opts in _blocks():
        src = (rst.parent / target).resolve()
        for line in opts.splitlines():
            m = re.match(r"\s*:(start-after|end-before): (.+)", line)
            if m:
                refs.append((rst, src, m.group(2).strip()))
    return refs


def test_documentation_uses_anchored_sections_somewhere():
    """אם כל ה-markers ייעלמו מהתיעוד יחד עם הכלל — שהבדיקה לא תעבור על ריק."""
    assert _referenced_markers(), (
        "אין אף בלוק ממוען-סימון בתיעוד; אם זו כוונה, עדכנו גם בדיקה זו"
    )


@pytest.mark.parametrize(
    "rst, src, marker",
    [(r, s, m) for r, s, m in _referenced_markers()],
    ids=[m for _, _, m in _referenced_markers()],
)
def test_every_referenced_marker_exists_exactly_once(rst, src, marker):
    """ה-marker קיים בקובץ המקור, ופעם אחת בדיוק.

    חסר — הבנייה נופלת ברעש ממילא, אבל הבדיקה תופסת את זה בלי לבנות.
    כפול — Sphinx היה חותך מהמופע הראשון בלי אזהרה, וזה שקט ומסוכן.
    """
    assert src.exists(), f"{rst.name} מפנה לקובץ שאינו קיים: {src}"
    count = src.read_text(encoding="utf-8").count(marker)
    assert count == 1, (
        f"הסימון {marker!r} מופיע {count} פעמים ב-{src.name} — נדרש בדיוק "
        f"אחד. חסר: הבנייה תיפול תחת -W. כפול: הבלוק ירונדר מהמופע הראשון "
        f"בשקט."
    )
