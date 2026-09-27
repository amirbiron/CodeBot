"""``decode_form_newlines`` מבטל את הקידוד של שליחת טופס, ולא נוגע בשום דבר אחר.

דפדפן הופך כל LF בערך של textarea ל-CRLF לפני השליחה (HTML Living Standard,
סעיף 4.10.22.8; נמדד ב-Chromium 141), וערך של textarea אינו יכול להחזיק CR
(נמדד). לכן הפענוח הפוך בדיוק לקידוד על כל ערך שיכול היה להגיע מ-textarea.
"""

from __future__ import annotations

import re

import pytest

from services.line_endings import decode_form_newlines


def _browser_encodes(value: str) -> str:
    """סעיף 4.10.22.8: כל CR ו-LF בודדים הופכים ל-CRLF."""
    return re.sub(r"\r\n|\r|\n", "\r\n", value)


@pytest.mark.parametrize(
    "textarea_value",
    [
        "",
        "x = 1",
        "x = 1\n",
        "x = 1\n\n\n",
        "\n\nleading",
        "שורה" + "\u200f" + " עם RLM\nשורה עם שבירה  \n",
        'RLM = "\\u200f"\n',
    ],
)
def test_decoding_undoes_exactly_what_the_browser_encoded(textarea_value):
    assert decode_form_newlines(_browser_encodes(textarea_value)) == textarea_value


def test_a_lone_cr_is_not_touched():
    """טופס של דפדפן לא מייצר CR בודד. אם הגיע כזה, הוא לא בא מה-textarea — והוא נשאר."""
    assert decode_form_newlines("a\rb\r\nc") == "a\rb\nc"
