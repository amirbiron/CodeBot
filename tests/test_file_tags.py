"""החיתוך והנרמול של תגיות — ``file_tags``.

המודול טהור, ולכן הבדיקות כאן אינן צריכות מסד. ההתנהגות שהן מקבעות היא
מה שעריכה, העלאה ועדכון מהיר שומרים כשמקלידים שורת תגיות; בדיקות הראוט
עצמו ב-``tests/test_webapp_quick_update_tags.py``.
"""

from __future__ import annotations

import pytest

from file_tags import (
    QUICK_UPDATE_MAX_TAG_CHARS,
    QUICK_UPDATE_MAX_TAGS,
    normalize_quick_update_tags,
    split_tags_text,
)


@pytest.mark.parametrize("raw, expected", [
    ("utils, api", ["utils", "api"]),
    # ``#`` הוא מפריד — כך מקלידים תגיות, וזה ה-placeholder של עמוד העריכה
    ("#utils, #repo:owner/name", ["utils", "repo:owner/name"]),
    ("#utils#api", ["utils", "api"]),
    ("utils\napi", ["utils", "api"]),
    (" , ,, ", []),
    ("", []),
])
def test_split_tags_text_cuts_on_comma_hash_and_newline(raw, expected):
    assert split_tags_text(raw) == expected


def test_split_tags_text_keeps_case_and_duplicates():
    """החיתוך אינו מנרמל: עריכה והעלאה שומרות רישיות וכפילויות כפי שהוקלדו."""
    assert split_tags_text("Python, Python, API") == ["Python", "Python", "API"]


def test_quick_update_lowercases_and_drops_the_hash():
    assert normalize_quick_update_tags("Python, #API, Utils") == ["python", "api", "utils"]


def test_quick_update_accepts_a_list_of_strings_and_none():
    assert normalize_quick_update_tags([" A ", "b", "A"]) == ["a", "b"]
    assert normalize_quick_update_tags(None) == []
    assert normalize_quick_update_tags("") == []


def test_quick_update_cuts_a_long_tag_to_the_ceiling():
    long_tag = "x" * (QUICK_UPDATE_MAX_TAG_CHARS + 10)
    assert normalize_quick_update_tags([long_tag]) == ["x" * QUICK_UPDATE_MAX_TAG_CHARS]


def test_duplicates_do_not_use_up_the_tag_ceiling():
    """הכפילויות נזרקות לפני הספירה.

    עד שהנרמול עבר ל-``file_tags`` הראוט חתך את הקלט הגולמי לפני שזרק
    כפולות, ולכן עשרים חזרות על אותה תגית השאירו תגית אחת — גם כשאחריהן
    הייתה עוד תגית שונה.
    """
    raw = ["a"] * QUICK_UPDATE_MAX_TAGS + ["b"]
    assert normalize_quick_update_tags(raw) == ["a", "b"]


def test_no_more_than_the_ceiling_of_distinct_tags_is_kept():
    raw = [f"t{i}" for i in range(QUICK_UPDATE_MAX_TAGS + 5)]
    assert normalize_quick_update_tags(raw) == raw[:QUICK_UPDATE_MAX_TAGS]


@pytest.mark.parametrize("raw", [
    {"a": 1},
    7,
    ["ok", 3],
    ["ok", None],
    ("a", "b"),
])
def test_a_value_that_is_not_text_or_a_list_of_strings_is_refused(raw):
    """``None`` הוא ערוץ הכשל — ולא המרה שקטה ב-``str``."""
    assert normalize_quick_update_tags(raw) is None
