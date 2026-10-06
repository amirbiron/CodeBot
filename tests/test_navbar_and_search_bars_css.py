"""שומר בלי דפדפן על ההחלטות של תיקון תפריטי הסרגל העליון וסרגלי החיפוש.

את ההתנהגות עצמה מודדים ``tests/test_navbar_menus_browser.py`` ו-
``tests/test_view_file_scroll_browser.py``, בכרומיום אמיתי ובמגע. הם מדולגים כשאין Chromium
— וב-CI אין — ולכן הקובץ הזה קורא את בלוקי ה-``<style>`` של התבניות ומוודא שההחלטות לא
בוטלו. הוא שומר על המסקנה של המדידה; הוא לא מודד מחדש.

ההחלטות. ההסבר המלא של כל אחת יושב ליד הכלל שלה בתבנית:

1. ``.navbar`` עולה מעל תוכן העמוד רק בזמן שאחד מהתפריטים שלו פתוח (``.navbar:has(...)``
   ב-``base.html``) — ולא לתמיד: הרמה קבועה הסתירה את 🔖 ואת כותרת פאנל הסימניות.
2. ``.fun-mode-dropdown`` מעוגן ב-``left``. מעוגן ב-``right`` הוא יצא מהמסך, ו-
   ``inset-inline-end`` מתורגם אצלו ל-``right`` בגלל ``direction: ltr`` שלו.
3. ``.nav-menu.active`` אינו חותך, כדי שחלונית האפקטים תצא ממנו.
4. ``.editor-toolbar`` ו-``.md-editor-toolbar`` נצמדים רק כשיש טקסט בתיבה, והרווח מעל
   כותרות ה-Markdown חל רק באותו תנאי. התנאי נשען על ה-``placeholder`` של התיבה.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _css_rules import css_rules, template_css

_TEMPLATES = Path(__file__).resolve().parent.parent / "webapp/templates"
BASE_HTML = _TEMPLATES / "base.html"
VIEW_FILE_HTML = _TEMPLATES / "view_file.html"
MD_PREVIEW_HTML = _TEMPLATES / "md_preview.html"

#: התפריטים שנפתחים מהסרגל. תפריט צף חדש בסרגל נכנס גם לכלל ב-``base.html`` וגם לכאן.
NAVBAR_MENUS = (".nav-menu.active", ".quick-access-dropdown.active", ".fun-mode-dropdown.active")

#: הסרגלים שנצמדים רק בזמן חיפוש: שם קבוע התבנית, הסרגל, והתיבה שהתנאי נשען עליה.
SEARCH_BARS = {
    "view_file": ("VIEW_FILE_HTML", ".editor-toolbar", "codeSearchInput"),
    "md_preview": ("MD_PREVIEW_HTML", ".md-editor-toolbar", "mdSearchInput"),
}


def _rules(path: Path) -> list[tuple[str, dict[str, str]]]:
    """כללי ה-CSS שבבלוקי ה-``<style>`` של התבנית. ההערות מוסרות לפני הפרסור: ההסברים
    בתבניות מזכירים בכוונה את הצורות הפסולות (``right``, ``inset-inline-end``)."""
    return css_rules(template_css(path))


def _declarations_of(path: Path, selector: str) -> list[dict[str, str]]:
    return [decls for sel, decls in _rules(path) if sel == selector]


def _z_index_of_main_content() -> int:
    values = [decls["z-index"] for decls in _declarations_of(BASE_HTML, ".main-content") if "z-index" in decls]
    assert values, "ל-``.main-content`` אין ``z-index`` ב-base.html — בדקו מחדש מה מצויר מעל הסרגל"
    return int(values[-1])


def test_the_templates_exist():
    for path in (BASE_HTML, VIEW_FILE_HTML, MD_PREVIEW_HTML):
        assert path.is_file(), f"לא נמצא {path}"


def test_the_navbar_rises_while_one_of_its_menus_is_open():
    """כל תפריט של הסרגל מרים אותו, לשכבה שמעל ``.main-content``."""
    raising = [
        (sel, decls) for sel, decls in _rules(BASE_HTML)
        if sel.startswith(".navbar:has(") and decls.get("position") == "relative" and "z-index" in decls
    ]
    assert raising, "חסר הכלל ``.navbar:has(...)`` שמרים את הסרגל כשתפריט שלו פתוח"
    covered = {menu for sel, _ in raising for menu in NAVBAR_MENUS if menu in sel}
    missing = [menu for menu in NAVBAR_MENUS if menu not in covered]
    assert not missing, f"תפריטים שאינם מרימים את הסרגל כשהם פתוחים — הנגיעות בהם ילכו לתוכן: {missing}"
    main_z = _z_index_of_main_content()
    low = [(sel, decls["z-index"]) for sel, decls in raising if int(decls["z-index"]) <= main_z]
    assert not low, f"הסרגל הפתוח אינו מעל ``.main-content`` (z-index {main_z}): {low}"


def test_the_navbar_is_not_raised_while_its_menus_are_closed():
    """הכלל הבסיסי של ``.navbar`` אינו נושא ``z-index``.

    על סרגל ``static`` הוא מת ומטעה, ועם ``position`` אחר הוא הרמה קבועה — שנמדד שמסתירה
    את 🔖 ואת כותרת פאנל הסימניות בראש עמוד קובץ.
    """
    offenders = [decls for decls in _declarations_of(BASE_HTML, ".navbar") if "z-index" in decls]
    assert not offenders, f"``.navbar`` נושא ``z-index`` גם כשהתפריטים סגורים: {offenders}"


def test_the_effects_panel_opens_toward_the_screen():
    """``.fun-mode-dropdown`` מעוגן ב-``left``, ולא ב-``right`` או בצד לוגי."""
    rules = _declarations_of(BASE_HTML, ".fun-mode-dropdown")
    assert rules, "לא נמצא הכלל ``.fun-mode-dropdown``"
    anchors = {prop: value for decls in rules for prop, value in decls.items()
               if prop in ("left", "right") or prop.startswith("inset")}
    assert anchors.get("left") == "0" and set(anchors) == {"left"}, (
        "חלונית האפקטים חייבת להיות מעוגנת בצד שמאל של השרביט בלבד. ``right`` פותח אותה "
        "אל מחוץ למסך, וצד לוגי מתורגם אצלה ל-``right`` כי היא ``direction: ltr``. "
        f"נמצא: {anchors}"
    )


def test_the_open_hamburger_list_does_not_clip():
    """``.nav-menu.active`` אינו חותך — חלונית האפקטים יוצאת ממנו."""
    values = [decls.get("overflow") for decls in _declarations_of(BASE_HTML, ".nav-menu.active")]
    assert "visible" in values, f"``.nav-menu.active`` חותך את חלונית האפקטים: overflow={values}"


def _placeholder_of(path: Path, input_id: str) -> str:
    html = path.read_text(encoding="utf-8")
    # ``(?<![-\w])`` ולא ``\b``: מקף הוא גבול מילה, ולכן ``\bid`` תופס גם ``data-id``.
    tag = re.search(r"<input\b[^>]*(?<![-\w])id=\"" + re.escape(input_id) + r"\"[^>]*>", html)
    assert tag, f"לא נמצא <input id=\"{input_id}\"> ב-{path.name}"
    placeholder = re.search(r"(?<![-\w])placeholder=\"([^\"]*)\"", tag.group(0))
    return placeholder.group(1) if placeholder else ""


@pytest.mark.parametrize("bar", list(SEARCH_BARS))
def test_the_search_bar_pins_only_while_the_box_has_text(bar):
    """הסרגל צמוד רק תחת ``:has(#תיבה:not(:placeholder-shown))``, ולתיבה יש placeholder."""
    template_name, toolbar, input_id = SEARCH_BARS[bar]
    path = globals()[template_name]
    always = [decls for decls in _declarations_of(path, toolbar) if decls.get("position") == "sticky"]
    assert not always, f"``{toolbar}`` צמוד גם בלי חיפוש, ומסתיר את ראש התוכן לאורך כל הגלילה"
    condition = f"{toolbar}:has(#{input_id}:not(:placeholder-shown))"
    assert any(decls.get("position") == "sticky" for decls in _declarations_of(path, condition)), (
        f"חסר הכלל ``{condition}`` שמצמיד את הסרגל בזמן חיפוש"
    )
    assert _placeholder_of(path, input_id).strip(), (
        f"ל-``#{input_id}`` אין placeholder. ``:placeholder-shown`` לא מתקיים בלעדיו, "
        "ולכן התנאי היה מצמיד את הסרגל תמיד"
    )


def test_the_markdown_heading_gap_applies_only_while_searching():
    """הרווח מעל כותרות (``--md-toolbar-h``) רק כשהסרגל צמוד, באותו תנאי שלו."""
    condition = "#mdCard:has(#mdSearchInput:not(:placeholder-shown))"
    gaps = [sel for sel, decls in _rules(MD_PREVIEW_HTML)
            if "--md-toolbar-h" in decls.get("scroll-margin-top", "")]
    assert gaps, "לא נמצא הרווח מעל כותרות ה-Markdown"
    unconditional = [sel for sel in gaps if not sel.startswith(condition)]
    assert not unconditional, f"רווח מעל כותרות שחל גם בלי חיפוש, כשהסרגל אינו צמוד: {unconditional}"


#: מוטציות: (הקבוע של התבנית, הקטע המקורי, הקטע אחרי המוטציה, השומר שחייב להיכשל).
#: כל אחת מהן היא תיקון אמיתי שנשקל ונפסל, או ביטול של ההחלטה.
MUTATIONS = {
    "הרמה קבועה": (
        "BASE_HTML",
        "            position: static;\n            top: auto;\n            transform: translateY(0);",
        "            position: relative;\n            top: auto;\n"
        "            z-index: 1000;\n            transform: translateY(0);",
        test_the_navbar_is_not_raised_while_its_menus_are_closed),
    "בלי הרמה בפתיחה": (
        "BASE_HTML", ".navbar:has(.nav-menu.active, .quick-access-dropdown.active, .fun-mode-dropdown.active) {",
        ".navbar-unused {", test_the_navbar_rises_while_one_of_its_menus_is_open),
    "תפריט שנשמט מההרמה": (
        "BASE_HTML", ", .fun-mode-dropdown.active) {", ") {", test_the_navbar_rises_while_one_of_its_menus_is_open),
    "אפקטים מעוגנים לימין": (
        "BASE_HTML", "(נמדד). */\n            left: 0;", "(נמדד). */\n            right: 0;",
        test_the_effects_panel_opens_toward_the_screen),
    "אפקטים בצד לוגי": (
        "BASE_HTML", "(נמדד). */\n            left: 0;", "(נמדד). */\n            inset-inline-end: 0;",
        test_the_effects_panel_opens_toward_the_screen),
    "רשימת ההמבורגר חותכת": (
        "BASE_HTML", "                overflow: visible;\n            }", "            }",
        test_the_open_hamburger_list_does_not_clip),
    "סרגל קוד צמוד תמיד": (
        "VIEW_FILE_HTML", ".editor-toolbar:has(#codeSearchInput:not(:placeholder-shown)) {", ".editor-toolbar {",
        lambda: test_the_search_bar_pins_only_while_the_box_has_text("view_file")),
    "תיבת קוד בלי placeholder": (
        "VIEW_FILE_HTML", 'placeholder="🔍 חפש בקוד..."', "",
        lambda: test_the_search_bar_pins_only_while_the_box_has_text("view_file")),
    "סרגל Markdown צמוד תמיד": (
        "MD_PREVIEW_HTML", ".md-editor-toolbar:has(#mdSearchInput:not(:placeholder-shown)) {", ".md-editor-toolbar {",
        lambda: test_the_search_bar_pins_only_while_the_box_has_text("md_preview")),
    "רווח כותרות תמיד": (
        "MD_PREVIEW_HTML", "#mdCard:has(#mdSearchInput:not(:placeholder-shown)) #md-content :is(",
        "#md-content :is(", test_the_markdown_heading_gap_applies_only_while_searching),
}


@pytest.mark.parametrize("name", list(MUTATIONS))
def test_the_guards_can_actually_fail(name, tmp_path, monkeypatch):
    """שומר שלא מסוגל להיכשל אינו שומר. המוטציה מאומתת קודם: הקטע נמצא פעם אחת בדיוק."""
    template_name, original, mutated, guard = MUTATIONS[name]
    path = globals()[template_name]
    source = path.read_text(encoding="utf-8")
    assert source.count(original) == 1, f"המוטציה '{name}' לא תפסה: הקטע נמצא {source.count(original)} פעמים"
    fake = tmp_path / path.name
    fake.write_text(source.replace(original, mutated), encoding="utf-8")
    monkeypatch.setattr(f"{__name__}.{template_name}", fake)
    with pytest.raises(AssertionError):
        guard()
