"""שומר על כלל אחד ב-``webapp/static/css/sticky-notes.css``.

``touch-action`` נחתכת עם האבות: התנהגות מגע מותרת רק אם היא מותרת בכל
אלמנט בשרשרת עד מיכל הגלילה. לכן ``touch-action: none`` על
``.sticky-note-header`` — שנראה מתבקש, כי הכותרת כולה היא ידית הגרירה —
משתק בשקט את כל מה שבתוכה: הכפתורים מפסיקים לגלול את העמוד, ושדה השם
בזמן עריכה מאבד את התנהגות המגע שלו. ``auto``/``manipulation`` על צאצא
אינם מחזירים כלום.

נמדד בכרומיום בקלט מגע דרך CDP (אירוע סינתטי אינו מפעיל גלילה מקורית
ולכן אינו יכול לבדוק את זה): אב ``none`` וצאצא ``auto`` — לא גלל; אותו אב
עם ``manipulation`` בצאצא — לא גלל; בקרה auto/auto — גללה 195 פיקסלים.

חסימת הגלילה בגרירה נעשית ב-``e.preventDefault()`` שב-``onDown`` של
``_enableDrag``, שרץ **אחרי** ``_isDragExempt`` ולכן מדלג על כפתורים ועל
שדה שם בעריכה.

הבדיקה טקסטואלית ולא מריצה דפדפן — היא שומרת על ההחלטה, לא מודדת אותה
מחדש. אותה גישה כמו ``test_note_boards_api`` שקורא את קובץ ה-JS כטקסט.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

CSS_PATH = Path(__file__).resolve().parent.parent / "webapp/static/css/sticky-notes.css"

# מסירים הערות לפני הפרסור: ההסבר בקובץ מזכיר את הצירוף האסור בכוונה,
# ובלי ההסרה הבדיקה הייתה נכשלת על התיעוד של עצמה.
_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.DOTALL)


def _rules_declaring_touch_action():
    css = _COMMENT.sub("", CSS_PATH.read_text(encoding="utf-8"))
    out = []
    for selector, body in _RULE.findall(css):
        for decl in body.split(";"):
            if ":" not in decl:
                continue
            prop, _, value = decl.partition(":")
            if prop.strip() == "touch-action":
                out.append((" ".join(selector.split()), value.strip()))
    return out


def test_css_file_exists():
    assert CSS_PATH.is_file(), f"לא נמצא {CSS_PATH}"


def test_no_touch_action_none_on_the_note_header():
    """``none`` על הכותרת משתק את הכפתורים ואת שדה השם שבתוכה."""
    offenders = [
        (sel, val)
        for sel, val in _rules_declaring_touch_action()
        if val != "auto" and ".sticky-note-header" in sel
    ]
    assert not offenders, (
        "touch-action שאינו ``auto`` הוצהר על ``.sticky-note-header`` או על "
        "צאצאיה. הוא נחתך עם האבות, ולכן משתק את הכפתורים ואת שדה השם "
        f"שבתוכה — כולל את ``.is-editing-title``. הכללים: {offenders}"
    )


def test_editing_title_still_clears_the_drag_handle():
    """הכלל שמחזיר מגע לשדה השם בעריכה — מנקה את **האב**, ולכן עובד."""
    rules = _rules_declaring_touch_action()
    freeing = [
        sel for sel, val in rules
        if val == "auto" and "is-editing-title" in sel and ".sticky-note-drag" in sel
    ]
    assert freeing, (
        "חסר כלל שמחזיר ``touch-action: auto`` ל-``.sticky-note-drag`` "
        "במצב ``is-editing-title``. בלעדיו מיקום הסמן בשם נשבר במובייל. "
        f"מה שנמצא: {rules}"
    )


def test_the_drag_handle_itself_blocks_touch_scrolling():
    """הידית כן חוסמת — היא אינה אב של אף כפתור."""
    blocking = [
        sel for sel, val in _rules_declaring_touch_action()
        if val == "none" and sel.strip() == ".sticky-note-drag"
    ]
    assert blocking, "``.sticky-note-drag`` אמור להצהיר ``touch-action: none``"


@pytest.mark.parametrize(
    "bad_css",
    [
        ".sticky-note-header{ touch-action: none; }",
        ".sticky-note-header, .sticky-note-header *{ touch-action: none; }",
        ".sticky-note-header .sticky-note-btn{ touch-action: manipulation; }",
    ],
)
def test_the_guard_can_actually_fail(bad_css, tmp_path, monkeypatch):
    """בדיקה שלא מסוגלת להיכשל אינה בדיקה.

    כל אחת מהצורות כאן היא ניסוח אמיתי שנכתב בסבב הקודם ונפסל במדידה.
    """
    fake = tmp_path / "sticky-notes.css"
    fake.write_text(CSS_PATH.read_text(encoding="utf-8") + "\n" + bad_css, encoding="utf-8")
    monkeypatch.setattr(f"{__name__}.CSS_PATH", fake)
    with pytest.raises(AssertionError):
        test_no_touch_action_none_on_the_note_header()
