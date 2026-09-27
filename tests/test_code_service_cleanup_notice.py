"""הודעת השקיפות של הבוט, והדלת של ה-handlers לניקוי (``services/code_service.py``).

הנוסחים כאן אושרו בתוכנית, ולכן הם נבדקים מילה במילה. תווי כיווניות כתובים
רק כ-escapes (H1).
"""

from __future__ import annotations

import pytest

from services import code_service
from src.domain.services.code_normalizer import PasteCleanup

RLO, LRI, PDI = "\u202e", "\u2066", "\u2069"


def test_the_approved_cleanup_line():
    cleanup = code_service.clean_pasted_code("a\r\nb\r\nc\r\n" + "\u200b" + "d", "x.py")
    assert code_service.format_cleanup_notice(cleanup) == "🧹 ניקיתי מהקוד: 3 סופי שורה של Windows ו-ZWSP אחד"


def test_the_approved_warning_line():
    lines = ["x = 1"] * 9
    lines[3] = 'y = "' + LRI + "a" + PDI + '"'
    lines[8] = "# " + RLO + "z"
    cleanup = code_service.clean_pasted_code("\n".join(lines), "x.py")
    assert code_service.format_cleanup_notice(cleanup) == (
        "⚠️ בשורות 4 ו-9 יש תווים שמשנים את סדר התצוגה. "
        "הם לא נראים, ויכולים לגרום לקוד להיראות אחרת ממה שהוא עושה. לא נגעתי בהם."
    )


def test_a_single_line_is_named_in_the_singular():
    cleanup = code_service.clean_pasted_code("a\n" + RLO + "b\n", "x.py")
    assert code_service.format_cleanup_notice(cleanup).startswith("⚠️ בשורה 2 יש תווים")


def test_a_long_list_of_lines_is_capped_in_the_message():
    text = "\n".join(LRI + "x" + PDI for _ in range(13))
    notice = code_service.format_cleanup_notice(code_service.clean_pasted_code(text, "x.py"))
    assert notice.startswith("⚠️ בשורות 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 ועוד 3 שורות יש תווים")


def test_nothing_to_say_means_an_empty_string():
    assert code_service.format_cleanup_notice(code_service.clean_pasted_code("x = 1\n", "x.py")) == ""


def test_the_hebrew_conjunction_attaches_to_a_hebrew_word():
    cleanup = PasteCleanup(text="", crlf=2, trailing_whitespace_lines=2)
    assert code_service.format_cleanup_notice(cleanup) == (
        "🧹 ניקיתי מהקוד: 2 סופי שורה של Windows ורווחים בסוף 2 שורות"
    )


def test_the_notice_is_safe_for_markdown_and_html_parse_modes():
    """ההודעה נכנסת להודעות עם parse_mode של Markdown וגם של HTML."""
    everything = PasteCleanup(
        text="",
        crlf=2,
        lone_cr=1,
        bom=True,
        special_spaces=3,
        zwsp=2,
        trailing_whitespace_lines=4,
        bidi_control_lines=tuple(range(1, 15)),
    )
    notice = code_service.format_cleanup_notice(everything)
    assert notice
    assert not set("_*`[]<>&") & set(notice)


@pytest.mark.parametrize(
    "file_name, expected",
    [
        ("notes.md", "a  \nb\u00a0\u200b\n"),  # Markdown: רק CRLF
        ("notes.py", "a\nb\n"),  # קוד: גם Zs, ZWSP ורווחים בסוף שורה
    ],
)
def test_markdown_is_decided_by_the_file_name(file_name, expected):
    cleanup = code_service.clean_pasted_code("a  \r\nb\u00a0\u200b\r\n", file_name)
    assert cleanup.text == expected


def test_missing_code_is_an_empty_text_not_an_error():
    """``context.user_data`` יכול לאבד את הקוד בין שלבי השיחה."""
    assert code_service.clean_pasted_code(None, "x.py").text == ""
