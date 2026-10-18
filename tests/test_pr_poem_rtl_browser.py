"""הפואמה מוצגת בכיוון הנכון — בכרומיום אמיתי, ב-HTML ש-GitHub מקבל מהתגובה.

**הבאג.** ``format_comment`` עוטף את הפואמה ב-``<div dir="rtl">``. בשורה שכולה אנגלית, כמו החתימה
``CodeKeeper forever 💫``, האימוג'י הוא תו ניטרלי בקצה השורה. לכן הוא מקבל את הכיוון של הבלוק, ומוצג
משמאל לטקסט ולא אחריו. התיקון עוטף שורה כזו ב-``<span dir="ltr">`` (``_reads_left_to_right``).

**מה נמדד:** איפה הדפדפן צייר כל קטע (``Range.getBoundingClientRect``), ב-HTML ש-cmark-gfm מפיק
מגוף התגובה — הפארסר ש-GitHub מריץ לפני ה-sanitizer. שלוש שורות: החתימה, שבה האימוג'י חייב להיות
מימין ל-``forever``; שורה שמתחילה באנגלית ושאר המשפט בה עברי, שחייבת להישאר מימין לשמאל; ושורה
עברית שנגמרת באנגלית ובאימוג'י, שבה האימוג'י נשאר בסוף השורה העברית, כלומר הכי שמאלה.

**מה לא נבדק כאן:** ה-sanitizer של GitHub וה-CSS שלו. ש-``span`` ו-``dir`` עוברים את ה-sanitizer
נשען על רשימת ההיתר של ``html-pipeline`` (``span`` ברשימת התגיות, ``dir`` בתכונות של כל תגית),
ו-``<bdi>`` אינו ברשימה. ספארי ופיירפוקס — יש כאן רק כרומיום.

מדולג כשאין Chromium (וב-CI אין: ראו ``docs/testing.rst``).
"""

from __future__ import annotations

import cmarkgfm
import pytest
from cmarkgfm.cmark import Options

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _pr_poem_loader import load_pr_poem

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

SIGNATURE = "CodeKeeper forever 💫"
STARTS_IN_ENGLISH = "Claude Code מקבל הוראות חיבור משלו."
ENDS_IN_ENGLISH = "והקוד נשאר LTR ✨"

#: התיבה שבה הדפדפן צייר את המופע הראשון של ``needle`` בעמוד.
RECT_OF_JS = """(needle) => {
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const at = node.data.indexOf(needle);
    if (at < 0) continue;
    const range = document.createRange();
    range.setStart(node, at);
    range.setEnd(node, at + needle.length);
    const box = range.getBoundingClientRect();
    return {left: box.left, right: box.right};
  }
  return null;
}"""


@pytest.fixture
def page(chromium_executable):
    with sync_playwright() as pw:
        launch = {"executable_path": chromium_executable} if chromium_executable else {}
        browser = pw.chromium.launch(**launch)
        try:
            yield browser.new_page()
        finally:
            browser.close()


def _render(page, poem, lines):
    html = cmarkgfm.github_flavored_markdown_to_html(poem.format_comment(lines), options=Options.CMARK_OPT_UNSAFE)
    page.set_content(f"<!doctype html><html><body>{html}</body></html>")

    def rect(needle):
        box = page.evaluate(RECT_OF_JS, needle)
        assert box is not None, f"{needle!r} לא נמצא בעמוד"
        return box

    return rect


def test_the_signature_ends_with_its_emoji_and_stays_on_the_right(page, monkeypatch):
    poem = load_pr_poem(monkeypatch)
    rect = _render(page, poem, [STARTS_IN_ENGLISH, SIGNATURE])

    assert rect("💫")["left"] >= rect("forever")["right"], "האימוג'י קפץ לפני החתימה"
    block_right = page.evaluate("document.querySelector('div[dir=rtl]').getBoundingClientRect().right")
    assert abs(rect("💫")["right"] - block_right) < 1, "החתימה כבר לא צמודה לצד ימין של הבלוק"


def test_lines_with_hebrew_still_read_right_to_left(page, monkeypatch):
    poem = load_pr_poem(monkeypatch)
    rect = _render(page, poem, [STARTS_IN_ENGLISH, ENDS_IN_ENGLISH, SIGNATURE])

    assert rect("Claude")["left"] > rect("משלו")["right"], "שורה שמתחילה באנגלית הפכה לשורה משמאל לימין"
    assert rect("✨")["right"] <= rect("LTR")["left"], "בשורה עברית האימוג'י כבר לא בסוף השורה"
