"""צבע הקישורים במסמך Markdown (``md_preview.html``) — הצבע של הערכה, ולא צבע קבוע.

עד אוקטובר 2026 הכללים של ``#md-content a`` כתבו כחול קבוע, ולכן ערכה מיובאת שיש לה צבע קישורים
משלה (``textLink.foreground``, שממופה ל-``--link-color`` ב-``services/theme_parser_service.py``) קיבלה
את אותו כחול. מאז הכללים קוראים את ``--link-color``, וכל ערכה מובנית מצהירה עליו בבלוק שלה.

**ובניגודיות גבוהה זה לא מספיק.** ``high-contrast.css`` צובע כל ``a`` ב-``!important``, בצבע שנבחר
לרקע השחור של הערכה, והדף של המסמך נשאר לבן גם שם. כלל רגיל מפסיד להצהרת ``!important`` בכל
ספציפיות, ובין שתי הצהרות ``!important`` מאותו מקור מכריעה הספציפיות (MDN, "!important"). לכן
היריבים **נגזרים מקבצי הערכות עצמם** (``THEME_CSS`` ב-``tests/_css_rules.py``), כמו ב-
``tests/test_sticky_notes_link_color.py``: כלל ערכה חדש על ``a`` נכנס לבדיקה מאליו ומכריח החלטה.

**לא נבדק כאן:** ``opacity`` של ``a:hover`` ב-``dark-mode.css``. הוא חל על הקישור במסמך בערכות
הכהות, והשינוי הזה לא נגע בו.

**ובסוף הקובץ — רשימת הטוקנים של High Contrast בעמוד התיעוד**, שמשווה את הפרוזה לבלוק עצמו.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import pytest

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _css_rules import (
    beats,
    classes_of,
    compounds,
    css_rules,
    state_of,
    subject_of,
    template_css,
    theme_rules_on,
    weight,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "webapp/templates/md_preview.html"
#: הצבעים של המסמך — כולל כללי הקישורים — יושבים כאן, ו-``md_preview.html`` טוען את הקובץ בראש
#: ``extra_css``. אותו קובץ נטען גם בתצוגה החיה, ושם הכללים חלים על ה-canvas (``id="md-content"``).
DOCUMENT_COLORS_CSS = REPO_ROOT / "webapp/static/css/md-content-colors.css"
BASE_TEMPLATE = REPO_ROOT / "webapp/templates/base.html"
HIGH_CONTRAST_CSS = REPO_ROOT / "webapp/static/css/high-contrast.css"
THEMING_DOC = REPO_ROOT / "docs/webapp/theming_and_css.rst"

_COLOUR_PROPS = ("color", "background", "background-color")
#: ערך שאינו צבע קבוע: נקרא מטוקן, או מילת מפתח שנגזרת מהאלמנט.
_NOT_FIXED = re.compile(r"(var\(--|currentColor\b|transparent\b|inherit\b)")
_THEME_ATTRIBUTE = re.compile(r'\[data-theme\^?="[^"]*"\]')


def _document_link_rules() -> list[tuple[str, dict[str, str]]]:
    """כללי המסמך שהנושא שלהם קישור בתוך ``#md-content`` — בלי מחלקה, כמו קישור במסמך.

    נקראים משני המקורות של המסמך: ``md-content-colors.css``, שבו כללי הקישורים, וה-``<style>`` של
    ``md_preview.html`` — כך שכלל קישור שיתווסף בתבנית עצמה ייבדק גם הוא.
    """
    out = []
    sources = DOCUMENT_COLORS_CSS.read_text(encoding="utf-8") + "\n" + template_css(TEMPLATE)
    for selector, decls in css_rules(sources):
        parts = compounds(selector)
        subject = parts[-1]
        if not any(re.match(r"#md-content(?![\w-])", part) for part in parts[:-1]):
            continue
        if not re.match(r"a(?![\w-])", subject) or classes_of(subject):
            continue
        out.append((selector, decls))
    return out


def _theme_of(selector: str) -> str | None:
    """הבורר של ``data-theme`` שהכלל דורש, או ``None`` לכלל שחל בכל ערכה."""
    found = _THEME_ATTRIBUTE.findall(selector)
    return found[0] if found else None


def test_no_link_rule_in_the_document_paints_a_fixed_colour():
    rules = _document_link_rules()
    # בלי כללים, הבדיקה הייתה עוברת בלי לבדוק דבר.
    assert rules, "לא נמצא כלל של קישור תחת #md-content ב-md-content-colors.css או ב-md_preview.html"
    fixed = [
        f"{selector} {{{prop}: {decls[prop]}}}"
        for selector, decls in rules
        for prop in _COLOUR_PROPS
        if prop in decls and not _NOT_FIXED.match(decls[prop])
    ]
    assert not fixed, "\n".join(fixed)


def test_the_link_reads_the_theme_link_colour_first():
    """``--link-color`` קודם, ובריחוף ``--primary-hover`` (``textLink.activeForeground``) לפניו."""
    colours = {selector: decls["color"] for selector, decls in _document_link_rules() if "color" in decls}
    assert colours["#md-content a"].startswith("var(--link-color,"), colours
    assert colours["#md-content a:hover"].startswith("var(--primary-hover, var(--link-color,"), colours


def _builtin_theme_ids() -> list[str]:
    """הערכות המובנות שבוחר הערכות מציע — ``BUILTIN_THEMES`` ב-``base.html``."""
    block = re.search(r"const BUILTIN_THEMES = \[(.*?)\];", BASE_TEMPLATE.read_text(encoding="utf-8"), re.DOTALL)
    assert block, "לא נמצא BUILTIN_THEMES ב-base.html"
    ids = re.findall(r"\bid:\s*'([\w-]+)'", block.group(1))
    assert ids, "BUILTIN_THEMES ריק — או שהצורה שלו השתנתה"
    return ids


def _theme_blocks() -> dict[str, dict[str, str]]:
    """ההצהרות של ``:root`` ושל ``:root[data-theme="…"]``, מ-``base.html`` ומ-``high-contrast.css``."""
    blocks: dict[str, dict[str, str]] = defaultdict(dict)
    rules = css_rules(template_css(BASE_TEMPLATE)) + css_rules(HIGH_CONTRAST_CSS.read_text(encoding="utf-8"))
    for selector, decls in rules:
        if re.fullmatch(r':root(\[data-theme="[\w-]+"\])?', selector):
            blocks[selector].update(decls)
    return blocks


@pytest.mark.parametrize("theme", [None, *_builtin_theme_ids()])
def test_every_builtin_theme_declares_a_link_colour(theme):
    """בלי הצהרה בבלוק של הערכה, הקישור יורש את הערך של ``:root`` — שנבחר לדף לבן."""
    selector = ":root" if theme is None else f':root[data-theme="{theme}"]'
    assert _theme_blocks()[selector].get("--link-color"), f"{selector} אינו מצהיר על --link-color"


@pytest.mark.parametrize("prop", ["color", "text-decoration"])
def test_no_theme_rule_on_a_reaches_the_document_link(prop):
    """כל כלל ערכה על ``a`` מפסיד לכללי המסמך שחלים באותה ערכה ובאותו מצב.

    כלל ערכה עם ``:hover`` חל רק בריחוף, ושם מתחרים בו הכללים של המסמך שחלים באותו מצב. כלל
    של המסמך שדורש ``data-theme`` מתחרה רק בכללים של אותה ערכה, וכלל בלי ``data-theme`` — בכולם.
    """
    rivals = [(name, sel, decls) for name, sel, decls in theme_rules_on("a") if prop in decls]
    assert rivals, f"לא נמצא כלל ערכה על a שמצהיר {prop}"
    # בלי זה, פרסור ששכח את ``!important`` היה מעביר את הבדיקה מהסיבה הלא נכונה.
    assert any(weight(sel, decls[prop])[0] for _, sel, decls in rivals), rivals
    # ``::after`` צובע את הפסאודו-אלמנט, לא את הקישור.
    ours = [(sel, d) for sel, d in _document_link_rules() if prop in d and "::" not in subject_of(sel)]
    offenders = []
    for name, selector, decls in rivals:
        rival = weight(selector, decls[prop])
        state = state_of(subject_of(selector))
        candidates = [
            weight(sel, d[prop])
            for sel, d in ours
            if state_of(subject_of(sel)) <= state and _theme_of(sel) in (None, _theme_of(selector))
        ]
        best = max(candidates) if candidates else None
        if best is None or not beats(best, rival):
            offenders.append(f"{name}: {selector} {rival} מול {best or 'אין כלל של המסמך במצב הזה'}")
    assert not offenders, "\n".join(offenders)


# ── רשימת הטוקנים של High Contrast בעמוד התיעוד ─────────────────────────────────────────


def test_the_theming_page_lists_the_high_contrast_tokens():
    """``theming_and_css.rst`` מונה את הטוקנים שהבלוק של High Contrast מצהיר עליהם.

    רשימה בפרוזה נשארת מאחור ביום שמוסיפים טוקן לבלוק, בלי שום כשל. הבדיקה גוזרת את שתי הרשימות
    ומשווה.
    """
    sentence = re.search(
        r'``:root\[data-theme="high-contrast"\]`` רק את הטוקנים (.+?) — ',
        THEMING_DOC.read_text(encoding="utf-8"),
    )
    assert sentence, "לא נמצא המשפט שמונה את הטוקנים של High Contrast ב-theming_and_css.rst"
    listed = set(re.findall(r"``(--[\w-]+)``", sentence.group(1)))
    declared = {
        prop
        for selector, decls in css_rules(HIGH_CONTRAST_CSS.read_text(encoding="utf-8"))
        if selector == ':root[data-theme="high-contrast"]'
        for prop in decls
        if prop.startswith("--")
    }
    assert listed == declared, f"בעמוד: {sorted(listed)}\nבבלוק: {sorted(declared)}"
