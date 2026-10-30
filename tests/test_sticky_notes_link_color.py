"""צבע הקישור בפתק דביק — ``--note-link``, אותו צבע בכל ערכה ובכל מצב.

קישור בפתק (``.sticky-md-link``) הוא ``<a>``, וקבצי הערכות צובעים ``<a>`` כאלמנט:
``[data-theme="dark"] a`` וחבריו ב-``dark-mode.css`` צובעים ב-``--primary``, ו-
``[data-theme="high-contrast"] a`` ב-``high-contrast.css`` צובע צהוב, ב-``!important``. הפתק
הוא נייר בהיר קבוע (ההערה בראש ``sticky-notes.css``), ולכן צבע שנבחר לרקע של הערכה יוצא
שגוי על הנייר — ובניגודיות גבוהה, צהוב על צהוב.

**למה ``!important`` לבדו אינו מספיק.** בין שתי הצהרות ``!important`` מאותו מקור מכריעה
הספציפיות (CSS Cascade 5, §6.1; MDN, "Specificity"). וסדר הטעינה אינו יכול להכריע: הלוח ודפדפן
הריפו טוענים את ``sticky-notes.css`` לפני קבצי הערכות, ותצוגת ה-Markdown אחריהם. לכן כל כלל
שלנו חייב לגבור **בספציפיות ממש**, ולא בשוויון.

**הבדיקות טקסטואליות, והיריבים נגזרים מקבצי הערכות עצמם** ולא מרשימה מוקלדת: כלל ערכה חדש
על ``a`` — מצב נוסף כמו ``:visited``, או ערכה נוספת — נכנס לבדיקה מאליו ומכריח החלטה. הן אינן
מריצות דפדפן. ב-12.10.2026 נקרא ``getComputedStyle`` של הקישור בכרומיום, בכל ערכה ובשני סדרי
הטעינה: לפני התיקון הקישור קיבל את ``--primary`` בכל ערכה ש-``dark-mode.css`` חל עליה וצהוב
בניגודיות גבוהה, ו-``!important`` על ``.sticky-md-link`` לבדו תיקן את הראשונות והשאיר את הצהוב.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _css_rules import (
    beats,
    classes_of,
    css_rules,
    specificity,
    state_of,
    subject_of,
    theme_rules_on,
    weight,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CSS_DIR = REPO_ROOT / "webapp/static/css"
STICKY_CSS = CSS_DIR / "sticky-notes.css"

#: הגוון נבחר בעין על הפתקים. הבדיקה מקבעת את ההחלטה, ולא תוצאה של חישוב ניגודיות.
NOTE_LINK = "#777abc"


def _theme_rules_on_the_link() -> list[tuple[str, str, dict[str, str]]]:
    """כללי הערכה שהנושא שלהם ``a`` ושחלים גם על קישור בפתק."""
    return theme_rules_on("a", {"sticky-md-link"})


def _note_rules_on_the_link() -> list[tuple[str, dict[str, str]]]:
    return [
        (selector, decls)
        for selector, decls in css_rules(STICKY_CSS.read_text(encoding="utf-8"))
        if "sticky-md-link" in classes_of(subject_of(selector))
    ]


def test_the_note_declares_the_link_colour_once_on_the_note():
    """``--note-link`` מוצהר על ``.sticky-note``, כמו ``--note-ink`` — לא כטוקן של ערכה."""
    declared = [
        (selector, decls["--note-link"])
        for selector, decls in css_rules(STICKY_CSS.read_text(encoding="utf-8"))
        if "--note-link" in decls
    ]
    assert declared == [(".sticky-note", NOTE_LINK)], declared


def test_every_colour_on_the_link_reads_the_token():
    """כל כלל שצובע את הקישור קורא את הטוקן, ב-``!important`` ובלי fallback.

    fallback היה עותק שני של הצבע. הוא לעולם אינו נכנס לפעולה — כל כלל כאן דורש
    ``.sticky-note``, שמצהיר על הטוקן — ולכן היה נראה כמו ברירת המחדל בלי להיות היא.
    """
    colours = {
        selector: decls["color"]
        for selector, decls in _note_rules_on_the_link()
        if "color" in decls
    }
    # בלי כלל כזה, כל הבדיקות בקובץ היו עוברות בלי לבדוק דבר.
    assert colours, "אף כלל ב-sticky-notes.css אינו צובע את הקישור"
    assert set(colours.values()) == {"var(--note-link) !important"}, colours


@pytest.mark.parametrize("prop", ["color", "opacity"])
def test_no_theme_rule_on_a_reaches_the_note_link(prop):
    """כל כלל ערכה על ``a`` מפסיד לכלל של הפתק, במצב שבו הוא חל.

    כלל ערכה עם ``:hover`` חל רק בריחוף, ושם מתחרים בו הכללים של הפתק שחלים באותו מצב —
    הכלל הרגיל וכלל ה-``:hover``. ``opacity`` נכלל כי ``a:hover`` של ``dark-mode.css`` מבהיר בו
    את הקישור, כלומר משנה את הצבע שנראה גם כש-``color`` עצמו נשאר.
    """
    rivals = [
        (name, sel, decls) for name, sel, decls in _theme_rules_on_the_link() if prop in decls
    ]
    assert rivals, f"לא נמצא כלל ערכה על a שמצהיר {prop} — אם הוא הוסר, הכלל המקביל בפתק מיותר"
    if prop == "color":
        # בלי זה, פרסור ששכח את ``!important`` היה מעביר את הבדיקה מהסיבה הלא נכונה.
        important = [sel for _, sel, decls in rivals if weight(sel, decls[prop])[0]]
        assert important, "אף כלל ערכה על a אינו !important — אולי ה-!important בפתק כבר מיותר"
    ours = _note_rules_on_the_link()
    offenders = []
    for name, selector, decls in rivals:
        rival = weight(selector, decls[prop])
        state = state_of(subject_of(selector))
        candidates = [
            weight(sel, d[prop]) for sel, d in ours if prop in d and state_of(subject_of(sel)) <= state
        ]
        best = max(candidates) if candidates else None
        if best is None or not beats(best, rival):
            offenders.append(f"{name}: {selector} {rival} מול {best or 'אין כלל של הפתק במצב הזה'}")
    assert not offenders, "\n".join(offenders)


def test_the_hover_underline_survives_the_high_contrast_shorthand():
    """העובי בריחוף חייב לגבור גם על הקיצור ``text-decoration`` של הערכה.

    הקיצור מאפס את ``text-decoration-thickness`` (CSS Text Decoration 4: "Omitted values are set
    to their initial values"), ובניגודיות גבוהה הוא ``!important``. הבדיקה בכיוון הזה בלבד: במצב
    הרגיל גם הקיצור של הערכה וגם שלנו נותנים קו רגיל, וניצחון של הערכה שם אינו משנה דבר.
    """
    ours = [
        (sel, decls)
        for sel, decls in _note_rules_on_the_link()
        if "text-decoration-thickness" in decls
    ]
    assert ours, "אין כלל שמעבה את הקו בריחוף"
    rivals = [
        (name, sel, decls)
        for name, sel, decls in _theme_rules_on_the_link()
        if {"text-decoration", "text-decoration-thickness"} & decls.keys()
    ]
    # כלל שהוסר משאיר את ה-``!important`` על העובי בלי סיבה — וזה צריך להיראות.
    assert rivals, "לא נמצא כלל ערכה על a שמצהיר text-decoration"
    offenders = []
    for selector, decls in ours:
        mine = weight(selector, decls["text-decoration-thickness"])
        state = state_of(subject_of(selector))
        for name, rival_sel, rival_decls in rivals:
            if not state_of(subject_of(rival_sel)) <= state:
                continue
            for prop in ("text-decoration", "text-decoration-thickness"):
                if prop in rival_decls and not beats(mine, weight(rival_sel, rival_decls[prop])):
                    offenders.append(
                        f"{name}: {rival_sel} {{{prop}: {rival_decls[prop]}}} מול {selector}"
                    )
    assert not offenders, "\n".join(offenders)


@pytest.mark.parametrize(
    "selector, expected",
    [
        ('[data-theme="high-contrast"] a', (0, 1, 1)),
        ('[data-theme="high-contrast"] a:hover', (0, 2, 1)),
        # ``:`` בתוך ערך המאפיין אינו פסאודו-מחלקה.
        ('[data-theme^="shared:"] a', (0, 1, 1)),
        # ``:where()`` שוקל אפס — זה כל העניין בווי הדריסה של ``dark-mode.css``.
        ('[data-theme="custom"] a:where(.btn-primary):hover', (0, 2, 1)),
        (".sticky-md-link", (0, 1, 0)),
        (".sticky-note .sticky-md-link", (0, 2, 0)),
        (".sticky-note .sticky-md-link:hover", (0, 3, 0)),
        ("#md-content a::after", (1, 0, 2)),
        ("a:before", (0, 0, 2)),
    ],
)
def test_specificity_weighs_the_forms_these_files_use(selector, expected):
    """המשקל לפי Selectors 4. טעות כאן הייתה מעבירה את הבדיקות שלמעלה מהסיבה הלא נכונה."""
    assert specificity(selector) == expected


@pytest.mark.parametrize("selector", ["a:not(.btn)", ".x:is(a, b)", "li:nth-child(2n of .y)"])
def test_specificity_refuses_what_it_cannot_weigh(selector):
    """משקל שגוי היה עובר בשקט. בורר שנדחה מכריח את מי שהוסיף אותו להחליט."""
    with pytest.raises(ValueError):
        specificity(selector)
