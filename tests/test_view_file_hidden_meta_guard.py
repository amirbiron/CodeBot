"""שומר: ``hidden`` על פריט המטא בעמוד הקובץ באמת מסתיר.

**מה זה שומר ומה זה לא.** הבדיקה הזו אינה מודדת — היא שומרת על מסקנה
שנמדדה בדפדפן. ‏Playwright אינו בתלויות הפרויקט, ולכן ההארנס עצמו לא
נשאר בריפו; מה שנשאר הוא הקביעה שההחלטה לא בוטלה בעריכה עתידית.

**מה נמדד ולמה בדיקת שרת לא יכולה לתפוס את זה.** ‏``base.html`` טוען
את ``global_search.css`` בכל עמוד, ושם ``.meta-item{display:flex}``
מוגדר בלי תיחום לתוצאות החיפוש. הכרזת ``display`` של מחבר מנצחת את
``[hidden]{display:none}`` של ה-user-agent — גם בלי ספציפיות גבוהה.
נמדד ב-Chromium: הפריט נשא ``hidden``, ``getComputedStyle`` החזיר
``display:flex``, ו-``getBoundingClientRect`` החזיר 283×56. כלומר
"עודכן" הוצג גם על קובץ שמעולם לא נערך. בדיקה שקוראת את ה-HTML
שהשרת החזיר רואה ``hidden`` ועוברת — הפער חי רק בדפדפן.

הפתרון הוא באותה מוסכמה שכבר קיימת בריפו: ``note-boards.css`` מתעד
את הדפוס במפורש, ובקובץ הזה עצמו כבר יש
``.file-actions__dropdown[hidden]`` מאותה סיבה.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).resolve().parents[1] / "webapp" / "templates" / "view_file.html"


@pytest.fixture(scope="module")
def template_text() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def test_meta_item_has_an_explicit_hidden_rule(template_text):
    """בלי הכלל הזה, ``hidden`` על ``.meta-item`` הוא חסר משמעות."""
    assert re.search(
        r"\.meta-item\[hidden\]\s*\{[^}]*display\s*:\s*none", template_text
    ), (
        "הכלל .meta-item[hidden]{display:none} הוסר. "
        "‏global_search.css מגדיר .meta-item{display:flex} גלובלית, "
        "ובלי הכלל הזה 'עודכן' מוצג גם על קובץ שמעולם לא נערך."
    )


def test_updated_item_visibility_is_driven_by_the_data_layer_flag(template_text):
    """התבנית נשענת על ``has_update``, לא על השוואת מחרוזות מפורמטות.

    ‏``format_datetime_display`` מעגל לדקות, ולכן קובץ שנוצר ונערך באותה
    דקה נראה כאילו מעולם לא נערך. נמדד בדפדפן: עם ההשוואה הישנה +
    הכלל החדש, "עודכן" נעלם על קובץ שכן נערך.
    """
    assert "{% if not file.has_update %}hidden{% endif %}" in template_text, (
        "פריט 'עודכן' חזר להישען על משהו שאינו has_update"
    )
    assert "file.updated_at == file.created_at" not in template_text, (
        "חזרה להשוואת מחרוזות מפורמטות — היא מעגלת לדקות"
    )


def test_the_global_stylesheet_that_causes_this_is_still_loaded(template_text):
    """אם ``global_search.css`` יתוחם או יוסר, השומר הזה מאבד את הסיבה שלו.

    הבדיקה מתעדת את התלות במפורש כדי שמי שיתחם אותו יידע שהוא יכול
    לשקול להסיר את הכלל — ולא ימחק אותו בלי לדעת למה הוא שם.
    """
    base = TEMPLATE.parent / "base.html"
    loaded = "css/global_search.css" in base.read_text(encoding="utf-8")
    unscoped = re.search(
        r"^\s*\.meta-item\s*\{[^}]*display\s*:\s*flex",
        (TEMPLATE.parents[1] / "static" / "css" / "global_search.css").read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if not (loaded and unscoped):
        pytest.skip(
            "‏global_search.css כבר אינו נטען גלובלית או ש-.meta-item שלו תוחם — "
            "אפשר לשקול מחדש את .meta-item[hidden] בעמוד הקובץ"
        )
    assert loaded and unscoped
