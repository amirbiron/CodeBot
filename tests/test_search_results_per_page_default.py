"""ברירת המחדל של מספר תוצאות החיפוש הגלובלי — שלושה מקומות, שפה אחת לכל אחד.

הערך חי ב-HTML (``selected``), ב-JavaScript (``DEFAULT_RESULTS_PER_PAGE``)
וב-Python (ברירת המחדל של ``/api/search/global``). אי אפשר לחלוק ביניהם
קבוע, ולכן הבדיקה הזו היא הקישור: אם מישהו ישנה אחד מהם ויפספס אחר, המסך
יבטיח מספר אחד וה-API יחזיר אחר.

**כן, זו בדיקת טקסט על קוד מקור.** זה מכוון: אין דרך התנהגותית לאמת
שקובץ HTML, קובץ JS וקובץ Python מסכימים על מספר, בלי להרים דפדפן אמיתי.
המחיר ידוע — פירמוט מחדש יפיל אותה — והודעות הכשל מנוסחות כדי שיהיה ברור
מיד שזה מה שקרה.
"""

import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPECTED_DEFAULT = 10
EXPECTED_OPTIONS = [5, 10, 20, 50]


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def _select_block():
    html = _read("webapp/templates/files.html")
    m = re.search(
        r'<select id="resultsPerPage".*?</select>', html, re.S
    )
    assert m, "the resultsPerPage selector is gone from files.html"
    return m.group(0)


def test_the_options_offered_are_the_ones_we_decided_on():
    values = [int(v) for v in re.findall(r'<option value="(\d+)"', _select_block())]
    assert values == EXPECTED_OPTIONS


def test_the_html_marks_the_agreed_default_as_selected():
    block = _select_block()
    selected = re.findall(r'<option value="(\d+)"\s+selected', block)
    assert selected == [str(EXPECTED_DEFAULT)], (
        f"files.html marks {selected} as selected; expected only {EXPECTED_DEFAULT}"
    )


def test_the_javascript_constant_agrees_with_the_html():
    js = _read("webapp/static/js/global_search.js")
    m = re.search(r"const DEFAULT_RESULTS_PER_PAGE\s*=\s*'(\d+)'", js)
    assert m, "DEFAULT_RESULTS_PER_PAGE is gone from global_search.js"
    assert int(m.group(1)) == EXPECTED_DEFAULT


def test_the_javascript_has_no_leftover_hardcoded_default():
    """הערך היה משוכפל בשני אתרי קריאה; עותק שנשאר מאחור הוא איך שזה נסחף."""
    js = _read("webapp/static/js/global_search.js")
    assert "resultsPerPage')?.value || '" not in js, "a hardcoded fallback came back"
    assert js.count("DEFAULT_RESULTS_PER_PAGE") >= 3, (
        "the constant should be declared once and used at both call sites"
    )


def test_the_server_default_agrees_with_the_client():
    """הלקוח תמיד שולח ``limit``, אבל ברירת מחדל שאינה תואמת הייתה מחזירה
    מספר אחר למי שקורא ל-API ישירות."""
    py = _read("webapp/app.py")
    m = re.search(
        r"limit = min\(100, max\(1, int\(payload\.get\('limit'\) or (\d+)\)\)\)", py
    )
    assert m, "the /api/search/global limit clamp changed shape"
    assert int(m.group(1)) == EXPECTED_DEFAULT


@pytest.mark.parametrize("value", EXPECTED_OPTIONS)
def test_every_offered_option_survives_the_server_clamp(value):
    """5 הוא חדש — צריך לוודא שהשרת לא כולא אותו כלפי מעלה."""
    assert min(100, max(1, value)) == value
