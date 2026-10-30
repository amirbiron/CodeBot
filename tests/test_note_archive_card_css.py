"""צבע הכרטיס בעמוד הארכיון — צבע הפתק, בכל ערכה.

הכרטיס הוא ``<button>`` (נגיש במקלדת), וקבצי הערכות צובעים ``button`` כאלמנט:
``[data-theme="high-contrast"] button`` ב-``high-contrast.css`` צובע כל כפתור שחור, ב-``!important``.
הצבע של כל כרטיס הוא צבע הפתק שלו, ולכן הוא מוצב על הכרטיס כטוקן (``--archive-card-color``,
ב-``notes-archive.js``) ונקרא בכלל של ``note-boards.css`` — סגנון inline בלי ``!important`` מפסיד
לכלל ערכה כזה. נמדד בכרומיום לפני התיקון: הכרטיס יצא שחור, והדיו ``#2b3f6a`` עליו.

**הבדיקה טקסטואלית, והיריבים נגזרים מקבצי הערכות עצמם** — אותה גישה של
``tests/test_sticky_notes_link_color.py``: כלל ערכה חדש על ``button`` נכנס לבדיקה מאליו ומכריח
החלטה. בין שתי הצהרות ``!important`` מאותו מקור מכריעה הספציפיות (CSS Cascade 5, §6.1), וסדר
הטעינה אינו אמור להכריע — ולכן הניצחון נדרש **ממש**, לא בשוויון. המדידה בדפדפן, בכל ערכה:
``tests/test_note_archive_browser.py``.

**ובסוף הקובץ — כתב היד בשם הכרטיס.** השם בכתב יד תמיד, ולא רק כשההגדרה של הלוחות דלוקה
(הכרעת המשתמש), ולכן הגופן מוצהר בכלל אחד על ``.archive-card-title`` בלי ``.sticky-handwriting``
מעליו. מה שהדפדפן עושה עם זה — בהגדרה כבויה ודלוקה — נמדד ב-``tests/test_note_archive_browser.py``.
"""

from __future__ import annotations

from pathlib import Path

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _css_rules import IMPORTANT, beats, classes_of, css_rules, subject_of, theme_rules_on, weight

REPO_ROOT = Path(__file__).resolve().parent.parent
CSS_DIR = REPO_ROOT / "webapp/static/css"
BOARDS_CSS = CSS_DIR / "note-boards.css"
_BACKGROUND = ("background-color", "background")


def _theme_backgrounds_on_a_button() -> list[tuple[str, str, str]]:
    """``(קובץ, בורר, ערך)`` לכל כלל ערכה שצובע רקע של ``button`` ושחל גם על הכרטיס."""
    return [
        (name, selector, decls[prop])
        for name, selector, decls in theme_rules_on("button", {"archive-card"})
        for prop in _BACKGROUND
        if prop in decls
    ]


def _card_backgrounds() -> list[tuple[str, str]]:
    return [
        (selector, decls[prop])
        for selector, decls in css_rules(BOARDS_CSS.read_text(encoding="utf-8"))
        if "archive-card" in classes_of(subject_of(selector))
        for prop in _BACKGROUND
        if prop in decls and "--archive-card-color" in decls[prop]
    ]


def test_there_is_a_theme_rule_to_beat():
    """בלי יריב הבדיקה הבאה הייתה עוברת על כלום. נופל אם הכלל של הערכה ישנה צורה."""
    rivals = _theme_backgrounds_on_a_button()
    assert any(name == "high-contrast.css" and IMPORTANT.search(value) for name, _s, value in rivals), rivals


def test_the_card_colour_is_one_token_read_in_one_rule():
    """הצבע נקרא ממקום אחד, בלי fallback — הכרטיס תמיד מקבל צבע מהשרת (``_as_archive_card``)."""
    ours = _card_backgrounds()
    assert ours == [(".archive-grid button.archive-card", "var(--archive-card-color) !important")], ours


def test_the_card_colour_beats_every_theme_rule_on_a_button():
    [(selector, value)] = _card_backgrounds()
    ours = weight(selector, value)
    for name, rival_selector, rival_value in _theme_backgrounds_on_a_button():
        assert beats(ours, weight(rival_selector, rival_value)), (
            f"{name}: {rival_selector} {{ {rival_value} }} גובר על {selector}"
        )


# ── כתב היד בשם הכרטיס ─────────────────────────────────────────────────────────────────

#: שני הקבצים שעמוד הארכיון טוען ושמגדירים גופן לפתקים — שם יכול לשבת כלל שגובר על הכרטיס.
NOTE_CSS = (CSS_DIR / "sticky-notes.css", BOARDS_CSS)


def _title_fonts() -> list[tuple[str, str, str]]:
    """``(קובץ, בורר, ערך)`` לכל כלל שמציב ``font-family`` על שם הכרטיס עצמו."""
    return [
        (path.name, selector, decls["font-family"])
        for path in NOTE_CSS
        for selector, decls in css_rules(path.read_text(encoding="utf-8"))
        if "archive-card-title" in classes_of(subject_of(selector)) and "font-family" in decls
    ]


def test_the_card_name_is_handwritten_in_one_rule_without_a_condition():
    """כלל אחד, בבורר של השם בלבד. ``.sticky-handwriting`` מעליו היה מחזיר את כתב היד להיות תלוי
    בהגדרה — שם היה עד אוקטובר 2026 — וכלל שני על השם היה מתחרה בו בספציפיות."""
    assert _title_fonts() == [("note-boards.css", ".archive-card-title", "'Gveret Levin', cursive")]
