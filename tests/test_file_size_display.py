"""גודל קובץ בתצוגה: ספרה אחרי הנקודה רק כשהיא אומרת משהו.

``105.0 KB`` ו-``582.0 B`` הוסיפו תו לכל כרטיס קובץ בלי להוסיף מידע.
הבדיקות כאן נוגעות בשלושת הצרכנים — הפונקציה המשותפת, זו של ``webapp/app.py``
שמזינה את כרטיסי הקבצים, וזו של האוספים — כדי שהכלל לא ייסחף באחד מהם.
"""

from __future__ import annotations

import pytest

from webapp.size_format import format_file_size, format_size_number

KB = 1024
MB = 1024 * 1024
GB = 1024 * 1024 * 1024


@pytest.mark.parametrize(
    "size_bytes, expected",
    [
        # ערך שלם — בלי נקודה ובלי אפס אחריה
        (0, "0 B"),
        (3, "3 B"),
        (582, "582 B"),
        (4 * KB, "4 KB"),
        (105 * KB, "105 KB"),
        (MB, "1 MB"),
        (5 * GB, "5 GB"),
        # שבר אמיתי — נשאר
        (28569, "27.9 KB"),
        (1536 * KB, "1.5 MB"),
        # התקרה: מעל TB הערך גדל ואינו מקבל יחידה חדשה
        (2 * 1024 * GB, "2 TB"),
    ],
)
def test_size_is_formatted_without_a_trailing_zero(size_bytes, expected):
    assert format_file_size(size_bytes) == expected


def test_number_helper_trims_only_a_zero_fraction():
    assert format_size_number(105.0) == "105"
    assert format_size_number(27.94) == "27.9"
    # העיגול הוא של ``:.1f`` ונקבע לפי הערך הבינארי: 0.95 הוא בפועל 0.9499...
    # ולכן הוא יורד ל-0.9 ולא עולה ל-1. נמדד, לא הונח.
    assert format_size_number(0.95) == "0.9"
    # ערך שמתעגל כלפי מעלה אל שלם כן מאבד את השבר
    assert format_size_number(0.96) == "1"


def test_files_page_formatter_uses_the_shared_rule():
    """``webapp/app.py`` הוא מה שמזין את כרטיסי הקבצים בתבנית."""
    from webapp.app import format_file_size as page_formatter

    assert page_formatter(105 * KB) == "105 KB"
    assert page_formatter(582) == "582 B"
    assert page_formatter(28569) == "27.9 KB"


def test_collection_item_formatter_uses_the_shared_rule_and_keeps_none():
    """באוספים ``None`` הוא חוזה של הקוראים ולא כלל תצוגה — הוא נשמר."""
    from webapp.collections_api import _format_size

    assert _format_size(105 * KB) == "105 KB"
    assert _format_size(28569) == "27.9 KB"
    assert _format_size(None) is None
    assert _format_size("not-a-number") is None
