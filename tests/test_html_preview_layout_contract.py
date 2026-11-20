"""החוזה הטקסטואלי של הפריסה בתצוגת הדפדפן לקובץ HTML (``html_preview.html``) — רץ גם ב-CI, שאין בו דפדפן.

המדידה עצמה ב-``tests/test_html_preview_layout_browser.py``, ושם היא מדולגת כשאין Chromium — כלומר תמיד ב-CI
(``docs/testing.rst``, הסעיף "בדיקות דפדפן, ותקרת הזמן"). הקובץ הזה לא מודד מחדש. הוא שומר שההחלטות שהמדידה אישרה
לא בוטלו בשקט:

- הכרטיס הוא עמודה, ואין לו ``overflow``: הוא אינו קופסת גלילה, ולכן קוד לא יכול לגלול אותו, וגם לא מסתיר בשקט מה
  שגולש ממנו.
- משטח הפתקים (``.html-preview-surface``), שהמסגרת ממלאת, הוא פריט ה-flex שגדל אל כל מה שנשאר אחרי שורת הכלים, ויכול
  להתכווץ מתחת לגובה התוכן שלו (``min-height: 0``).
- כל הרווחים סביב התצוגה וחישוב הגובה של הכרטיס נקבעים מ-``--html-preview-gutter``, ולא כל אחד בערך משלו.

לכל החלטה יש מוטציה למטה, שמוכיחה שהבדיקה מסוגלת להיכשל עליה.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).resolve().parent.parent / "webapp" / "templates" / "html_preview.html"

CARD = ".main-content .preview-container.glass-card"
SURFACE = ".html-preview-surface"
GUTTER = "var(--html-preview-gutter)"


def _rules(source: str) -> dict[str, list[str]]:
    """הכללים בבלוק ``extra_css`` של התבנית: בורר ← ההצהרות שלו, בלי הערות."""
    block = re.search(r"\{% block extra_css %\}\s*<style>(.*?)</style>", source, re.S)
    assert block, "בלוק ה-<style> של extra_css לא נמצא בתבנית"
    css = re.sub(r"/\*.*?\*/", "", block.group(1), flags=re.S)
    rules: dict[str, list[str]] = {}
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        decls = [d.strip() for d in body.split(";") if d.strip()]
        rules.setdefault(" ".join(selector.split()), []).extend(decls)
    return rules


def _violations(source: str) -> list[str]:
    rules = _rules(source)
    card = rules.get(CARD)
    surface = rules.get(SURFACE)
    assert card is not None and surface is not None, f"הבוררים {CARD!r} / {SURFACE!r} לא נמצאו: {sorted(rules)}"
    found = []
    if "display: flex" not in card or "flex-direction: column" not in card:
        found.append("card-not-a-column")
    if any(d.startswith("overflow") for d in card):
        found.append("card-has-overflow")
    if "flex: 1 1 auto" not in surface:
        found.append("surface-does-not-grow")
    if "min-height: 0" not in surface:
        found.append("surface-cannot-shrink")
    heights = [d for d in card if d.startswith("height:")]
    if not heights or not all(f"2 * {GUTTER}" in d for d in heights):
        found.append("card-height-not-from-gutter")
    if not any(d.startswith("margin-block:") and GUTTER in d for d in card):
        found.append("card-margin-not-from-gutter")
    if f"padding-bottom: {GUTTER}" not in rules.get(".main-content", []):
        found.append("page-bottom-not-from-gutter")
    if f"padding-inline: {GUTTER}" not in rules.get(".main-content > .container", []):
        found.append("sides-not-from-gutter")
    return found


#: שמות ההפרות, לשמות המקרים במוטציות.
_VIOLATION_IDS = {
    "card-not-a-column", "card-has-overflow", "surface-does-not-grow", "surface-cannot-shrink",
    "card-height-not-from-gutter", "card-margin-not-from-gutter", "page-bottom-not-from-gutter", "sides-not-from-gutter",
}


def test_the_template_keeps_the_layout_decisions():
    assert _violations(TEMPLATE.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("old, new, expected", [
    ("    flex-direction: column;\n    gap: var(--html-preview-gutter);",
     "    gap: var(--html-preview-gutter);", "card-not-a-column"),
    ("    padding: var(--html-preview-gutter);\n    border-radius: 12px;\n}",
     "    padding: var(--html-preview-gutter);\n    border-radius: 12px;\n    overflow: hidden;\n}", "card-has-overflow"),
    ("    position: relative;\n    flex: 1 1 auto;\n    min-height: 0;",
     "    position: relative;\n    min-height: 0;", "surface-does-not-grow"),
    ("    position: relative;\n    flex: 1 1 auto;\n    min-height: 0;",
     "    position: relative;\n    flex: 1 1 auto;", "surface-cannot-shrink"),
    ("    height: calc(100dvh - 2 * var(--html-preview-gutter));", "    height: 70dvh;", "card-height-not-from-gutter"),
    ("margin-block: calc(var(--html-preview-gutter) + 1px) 0;", "margin-block: 1rem 0;", "card-margin-not-from-gutter"),
    ("    padding-bottom: var(--html-preview-gutter);", "    padding-bottom: 2rem;", "page-bottom-not-from-gutter"),
    ("    padding-inline: var(--html-preview-gutter);", "    padding-inline: 20px;", "sides-not-from-gutter"),
], ids=lambda v: v if v in _VIOLATION_IDS else "")
def test_each_decision_can_fail(old, new, expected):
    source = TEMPLATE.read_text(encoding="utf-8")
    assert source.count(old) == 1, f"המוטציה לא תפסה: {old!r}"
    mutated = source.replace(old, new)
    assert mutated != source
    assert expected in _violations(mutated)
