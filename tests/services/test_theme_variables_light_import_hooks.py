"""ווי הדריסה לערכה מיובאת בהירה: שדות טופס, הפיד והפוש בדשבורד, שורת החיפוש, "שולחן עבודה", הכפתורים
שמעל העורך, וסרגל החיפוש ומלבני הפרטים בתצוגת הקוד.

כל ערכה מיובאת מקבלת את העיצוב של הערכות הכהות, וזה נשאר כך בכוונה. כמה רכיבים צבועים שם בצבעים
קבועים לרקע כהה — לבן שקוף לגבולות ולרקעים, טקסט כמעט לבן בתגים ובכפתורים — ובערכה מיובאת בהירה הם
לא נראים: השדות בעמודי העריכה וההעלאה ושדות הסינון בעמוד הקבצים, הבלוקים, התגים והבאדג' של הפוש
בדשבורד, הגבול של שורת החיפוש בתצוגת ה-Markdown ובתצוגת הקוד, הכפתורים שמעל העורך, וסרגל החיפוש
ומלבני הפרטים בתצוגת הקוד. "שולחן עבודה" בעמוד הקבצים צבוע במעבר צבע שמסתיים ב-``--secondary``, שהמייבא
אינו לוקח מקובץ VS Code. כל אחד מהם קורא עכשיו וו דריסה בכלל שצובע אותו היום, וערכה בהירה מצהירה עליו
בבלוק ``variables`` שלה.

הבדיקות טקסטואליות, כמו אלה של שאר ווי הדריסה: הן שומרות על החוזה — רשימה לבנה, בלי ברירת מחדל בשום
מקום, ו-fallback שהוא בדיוק מה שנצבע היום — ולא מודדות את המפל מחדש. בדיקת הייבוא עוברת דרך ה-endpoint
עצמו וקוראת את מה שנשמר במסד. הרקע: ``docs/webapp/custom_themes_guide.rst``,
``theme-variables-light-import-hooks``.
"""

import json
import re
from pathlib import Path

import pytest

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _css_rules import css_rules, template_css
from _fake_mongo import FakeDB

from services.theme_parser_service import (
    ALLOWED_VARIABLES_WHITELIST,
    FALLBACK_DARK,
    FALLBACK_LIGHT,
    VSCODE_TO_CSS_MAP,
    validate_theme_json,
)
from webapp import app as webapp_app

FIELD_BORDER = "--form-field-border-override"
FIELD_BG = "--form-field-bg-override"
FIELD_FOCUS_BORDER = "--form-field-focus-border-override"
BLOCK_BG = "--timeline-block-bg-override"
ITEM_BORDER = "--timeline-item-border-override"
BADGE_TEXT = "--timeline-badge-text-override"
PILL_TEXT = "--status-pill-text-override"
CAPSULE_BORDER = "--md-search-capsule-border-override"
WORKSPACE_BG = "--workspace-btn-bg-override"
WORKSPACE_BORDER = "--workspace-btn-border-override"
EDITOR_BTN_TEXT = "--editor-btn-text-override"
EDITOR_BTN_BG = "--editor-btn-bg-override"
EDITOR_BTN_BORDER = "--editor-btn-border-override"
EDITOR_BTN_HOVER_BG = "--editor-btn-hover-bg-override"
EDITOR_SWITCH_BG = "--editor-switch-btn-bg-override"
EDITOR_SWITCH_HOVER_BG = "--editor-switch-btn-hover-bg-override"
CODE_TOOLBAR_BG = "--code-toolbar-bg-override"
CODE_TOOLBAR_BORDER = "--code-toolbar-border-override"
CODE_TOOLBAR_HOVER_BG = "--code-toolbar-hover-bg-override"
CODE_TOOLBAR_TEXT = "--code-toolbar-text-override"
CODE_CAPSULE_BG = "--code-search-capsule-bg-override"
CODE_CAPSULE_FOCUS_BORDER = "--code-search-capsule-focus-border-override"
META_ITEM_BG = "--file-meta-item-bg-override"
NESTED_CARD_BG = "--nested-card-bg-override"
TOKENS = (
    FIELD_BORDER,
    FIELD_BG,
    FIELD_FOCUS_BORDER,
    BLOCK_BG,
    ITEM_BORDER,
    BADGE_TEXT,
    PILL_TEXT,
    CAPSULE_BORDER,
    WORKSPACE_BG,
    WORKSPACE_BORDER,
    EDITOR_BTN_TEXT,
    EDITOR_BTN_BG,
    EDITOR_BTN_BORDER,
    EDITOR_BTN_HOVER_BG,
    EDITOR_SWITCH_BG,
    EDITOR_SWITCH_HOVER_BG,
    CODE_TOOLBAR_BG,
    CODE_TOOLBAR_BORDER,
    CODE_TOOLBAR_HOVER_BG,
    CODE_TOOLBAR_TEXT,
    CODE_CAPSULE_BG,
    CODE_CAPSULE_FOCUS_BORDER,
    META_ITEM_BG,
    NESTED_CARD_BG,
)
#: משתנה הביניים של המסגרת של "שולחן עבודה" — לא וו. ראו ``WORKSPACE_HOOKS``.
WORKSPACE_RING = "--workspace-btn-ring"

REPO_ROOT = Path(__file__).resolve().parents[2]
FILE_EDITOR_CSS = REPO_ROOT / "webapp/static/css/file-editor.css"
FILES_HTML = REPO_ROOT / "webapp/templates/files.html"
DASHBOARD_HTML = REPO_ROOT / "webapp/templates/dashboard.html"
MD_PREVIEW_HTML = REPO_ROOT / "webapp/templates/md_preview.html"
BASE_HTML = REPO_ROOT / "webapp/templates/base.html"
CODEMIRROR_CUSTOM_CSS = REPO_ROOT / "webapp/static/css/codemirror-custom.css"
MARKDOWN_TOOLBAR_CSS = REPO_ROOT / "webapp/static/css/markdown-toolbar.css"
VIEW_FILE_HTML = REPO_ROOT / "webapp/templates/view_file.html"
CUSTOM_THEMES_GUIDE = REPO_ROOT / "docs/webapp/custom_themes_guide.rst"
SETTINGS_HTML = REPO_ROOT / "webapp/templates/settings.html"
SETTINGS_PUSH_DEBUG_HTML = REPO_ROOT / "webapp/templates/settings_push_debug.html"

#: מה שכל כלל צבע לפני הווו (``main`` ב-2a3dec3c). ה-fallback חייב להיות בדיוק הערך הזה, אחרת ערכה
#: שאינה מצהירה — כל ערכה מובנית, וכל ערכה מיובאת כהה — זזה.
FILE_EDITOR_HOOKS = {
    (".form-field", "border"): f"1px solid var({FIELD_BORDER}, rgba(255, 255, 255, 0.2))",
    (".form-field", "background"): f"var({FIELD_BG}, rgba(255, 255, 255, 0.08))",
    (".form-field:focus", "border-color"): f"var({FIELD_FOCUS_BORDER}, rgba(255, 255, 255, 0.5))",
}
DASHBOARD_HOOKS = {
    (".timeline-item", "background"): f"var({BLOCK_BG}, rgba(255,255,255,0.02))",
    (".timeline-item", "border-right"): f"3px solid var({ITEM_BORDER}, rgba(255,255,255,0.08))",
    (".timeline-group", "background"): f"var({BLOCK_BG}, rgba(255,255,255,0.02))",
    (".timeline-badge-code", "color"): f"var({BADGE_TEXT}, #f3e8ff)",
    (".timeline-badge-info", "color"): f"var({BADGE_TEXT}, #dbeafe)",
    (".timeline-badge-warning", "color"): f"var({BADGE_TEXT}, #fef9c3)",
    (".timeline-badge-neutral", "color"): f"var({BADGE_TEXT}, #e2e8f0)",
    (".status-success", "color"): f"var({PILL_TEXT}, #bbf7d0)",
    (".status-warning", "color"): f"var({PILL_TEXT}, #fef3c7)",
    (".status-danger", "color"): f"var({PILL_TEXT}, #fecaca)",
    (".status-neutral", "color"): f"var({PILL_TEXT}, #e2e8f0)",
}
#: "שולחן עבודה" (``.workspace-btn`` ב-``base.html``). הגבול נשאר ``none`` — גבול היה מגדיל את הכפתור בכל ערכה —
#: והמסגרת היא ``box-shadow`` דרך משתנה ביניים בלי fallback: כשהווו אינו מוגדר, המשתנה לא תקף (W3C
#: css-variables-1, סעיף 3.1), ו-``box-shadow`` נופל ל-``none``, הערך של הכלל עד היום.
WORKSPACE_HOOKS = {
    (".workspace-btn", "background"): (
        f"var({WORKSPACE_BG}, linear-gradient(135deg, var(--primary) 0%, var(--secondary) 100%))"
    ),
    (".workspace-btn", "border"): "none",
    (".workspace-btn", WORKSPACE_RING): f"inset 0 0 0 1px var({WORKSPACE_BORDER})",
    (".workspace-btn", "box-shadow"): f"var({WORKSPACE_RING}, none)",
}
#: הכפתורים שמעל העורך — "עורך פשוט"/"עורך מתקדם", "בטל", "בצע שוב", "בחר הכל", "העתק" ו"הדבק".
EDITOR_HOOKS = {
    (".btn-switch-editor", "background"): f"var({EDITOR_SWITCH_BG}, rgba(100,100,255,0.2))",
    (".btn-switch-editor", "border"): f"1px solid var({EDITOR_BTN_BORDER}, rgba(100,100,255,0.5))",
    (".btn-switch-editor", "color"): f"var({EDITOR_BTN_TEXT}, #fff)",
    (".btn-switch-editor:hover", "background"): f"var({EDITOR_SWITCH_HOVER_BG}, rgba(100,100,255,0.3))",
    (".btn-editor-clip", "border"): f"1px solid var({EDITOR_BTN_BORDER}, rgba(255,255,255,0.25))",
    (".btn-editor-clip", "background"): f"var({EDITOR_BTN_BG}, rgba(255,255,255,0.08))",
    (".btn-editor-clip", "color"): f"var({EDITOR_BTN_TEXT}, #fff)",
    (".btn-editor-clip:hover", "background"): f"var({EDITOR_BTN_HOVER_BG}, rgba(255,255,255,0.15))",
    (".btn-editor-clip:hover", "border-color"): f"var({EDITOR_BTN_BORDER}, rgba(255,255,255,0.4))",
}
#: כפתור ה-MD באותה שורה, בקובץ אחר.
MD_TRIGGER_HOOKS = {
    (".md-toolbar-trigger", "color"): f"var({EDITOR_BTN_TEXT}, var(--text-color, #e0e0e0))",
}
#: סרגל החיפוש ומלבני הפרטים בתצוגת הקוד (``view_file.html``). הגבול של שורת החיפוש קורא את הווו של שורת
#: החיפוש בתצוגת ה-Markdown — אותו רכיב בשני עותקים.
VIEW_FILE_HOOKS = {
    (".editor-toolbar", "background"): f"var({CODE_TOOLBAR_BG}, rgba(255, 255, 255, 0.08))",
    (".editor-toolbar", "border"): f"1px solid var({CODE_TOOLBAR_BORDER}, rgba(255, 255, 255, 0.18))",
    (".search-capsule", "background"): f"var({CODE_CAPSULE_BG}, rgba(0, 0, 0, 0.25))",
    (".search-capsule", "border"): f"1px solid var({CAPSULE_BORDER}, transparent)",
    (".search-capsule:focus-within", "border-color"): (
        f"var({CODE_CAPSULE_FOCUS_BORDER}, rgba(255, 255, 255, 0.5))"
    ),
    (".search-capsule:focus-within", "background"): f"var({CODE_CAPSULE_BG}, rgba(0, 0, 0, 0.4))",
    (".search-count", "color"): f"var({CODE_TOOLBAR_TEXT}, rgba(255, 255, 255, 0.85))",
    (".divider", "background"): f"var({CODE_TOOLBAR_BORDER}, rgba(255, 255, 255, 0.25))",
    (".icon-btn", "color"): f"var({CODE_TOOLBAR_TEXT}, rgba(255, 255, 255, 0.9))",
    (".icon-btn:hover", "background"): f"var({CODE_TOOLBAR_HOVER_BG}, rgba(255, 255, 255, 0.15))",
    (".icon-btn:focus-visible", "background"): f"var({CODE_TOOLBAR_HOVER_BG}, rgba(255, 255, 255, 0.15))",
    (".fullscreen-btn", "border"): f"1px solid var({CODE_TOOLBAR_BORDER}, rgba(255, 255, 255, 0.25))",
    (".fullscreen-btn", "background"): f"var({CODE_TOOLBAR_BG}, rgba(255, 255, 255, 0.12))",
    (".fullscreen-btn:hover", "background"): f"var({CODE_TOOLBAR_HOVER_BG}, rgba(255, 255, 255, 0.22))",
    (".fullscreen-btn:hover", "border-color"): f"var({CODE_TOOLBAR_BORDER}, rgba(255, 255, 255, 0.4))",
    (".fullscreen-btn:focus-visible", "background"): (
        f"var({CODE_TOOLBAR_HOVER_BG}, rgba(255, 255, 255, 0.22))"
    ),
    (".fullscreen-btn:focus-visible", "border-color"): (
        f"var({CODE_TOOLBAR_BORDER}, rgba(255, 255, 255, 0.4))"
    ),
    (".meta-item", "background"): f"var({META_ITEM_BG}, rgba(255,255,255,0.05))",
}
#: שדות הסינון בעמוד הקבצים — צבועים רק ב-``style`` שבתגית, ולכן הווו נקרא שם.
FILES_FILTER_FIELDS = ('input type="text" name="q"', 'select name="lang"', 'select name="sort"')
FILES_FILTER_STYLE = {
    "border": f"1px solid var({FIELD_BORDER}, rgba(255,255,255,0.2))",
    "background": f"var({FIELD_BG}, rgba(255,255,255,0.1))",
}
#: השדות בעמוד ההגדרות — צבועים רק ב-``style`` שבתגית, כמו שדות הסינון בעמוד הקבצים, ולכן קוראים את אותם ווים.
#: ה-``id`` של כל שדה, עם הערכים שצבעו אותו עד היום: לשדה של "הוראות לסוכן" רקע 0.08, ולתיבות הבחירה 0.1.
SETTINGS_FIELD_STYLES = {
    "agentInstructions": {
        "border": f"1px solid var({FIELD_BORDER}, rgba(255, 255, 255, 0.2))",
        "background": f"var({FIELD_BG}, rgba(255, 255, 255, 0.08))",
    },
    **{
        field_id: {
            "border": f"1px solid var({FIELD_BORDER}, rgba(255,255,255,0.2))",
            "background": f"var({FIELD_BG}, rgba(255,255,255,0.1))",
        }
        for field_id in (
            "themeSelect",
            "themeScopeSelect",
            "noteFont-{{ surface }}",
            "noteFontsScopeSelect",
            "settingsNoteFontSizeSelect",
            "settingsNoteFontSizeScopeSelect",
        )
    },
}
#: הרקע של כרטיס בתוך כרטיס — ה-fallback הוא הלבן השקוף שצבע אותו עד היום. הרווחים נמחקים לפני ההשוואה,
#: כי בתבניות הערך כתוב גם ``rgba(255, 255, 255, 0.05)`` וגם ``rgba(255,255,255,0.05)``.
NESTED_CARD_BACKGROUND = f"var({NESTED_CARD_BG},rgba(255,255,255,0.05))"
#: הכלל שצובע את שורת החיפוש בערכה מיובאת או משותפת. הווו נקרא בו ולא בכלל חדש.
CAPSULE_SCOPES = (':root[data-theme="custom"]', ':root[data-theme^="shared:"]')


def _style_declarations(tag):
    """המאפיינים שב-``style`` של תגית אחת, כמילון — ערך עם רווחים מנורמלים. ריק כשאין ``style``."""
    style = re.search(r'style="([^"]*)"', tag)
    declarations = {}
    for declaration in (style.group(1) if style else "").split(";"):
        prop, sep, value = declaration.partition(":")
        if sep:
            declarations[prop.strip()] = " ".join(value.split())
    return declarations


def _declaration(rules, selector, prop):
    """הערך של ``prop`` בכלל היחיד שהבורר שלו הוא בדיוק ``selector``."""
    found = [decl[prop] for sel, decl in rules if sel == selector and prop in decl]
    assert len(found) == 1, f"{selector} {{{prop}}}: {found}"
    return found[0]


def test_tokens_are_whitelisted():
    """בלי זה הטוקנים מסוננים בשקט בייבוא ולא מגיעים ל-CSS."""
    for token in TOKENS:
        assert token in ALLOWED_VARIABLES_WHITELIST, token


def test_tokens_are_not_in_the_fallback_dicts():
    """``parse_vscode_theme`` מעתיק את מילון ה-FALLBACK לכל ערכה מיובאת לפני המיפוי.

    טוקן שיושב שם מוגדר בכל ערכה מיובאת, ה-fallback ב-CSS לא רץ אף פעם, והווו הופך לשינוי גורף.
    """
    for token in TOKENS:
        assert token not in FALLBACK_DARK, token
        assert token not in FALLBACK_LIGHT, token


def test_no_vscode_key_maps_to_the_tokens():
    """אין מפתח VS Code שמוביל לטוקנים — ולכן הם מגיעים רק מבלוק ``variables`` מפורש."""
    targets = set()
    for css_vars in VSCODE_TO_CSS_MAP.values():
        targets.update(css_vars if isinstance(css_vars, list) else [css_vars])
    assert not targets.intersection(TOKENS)


def test_no_stylesheet_or_template_gives_the_tokens_a_value():
    """ערך ברירת מחדל בכל מקום — ``:root`` בתבנית, בלוק בקובץ CSS אחר — מבטל את ה-fallback."""
    sources = list((REPO_ROOT / "webapp/static").rglob("*.css"))
    sources += list((REPO_ROOT / "webapp/templates").rglob("*.html"))
    for path in sources:
        text = path.read_text(encoding="utf-8", errors="replace")
        for token in TOKENS:
            assert not re.search(
                re.escape(token) + r"\s*:", text
            ), f"{token} מקבל ערך ב-{path.name}"


def test_form_fields_read_the_tokens_with_todays_fallbacks():
    """השדות בעמודי העריכה וההעלאה — ``.form-field`` ב-``file-editor.css``, כולל הפוקוס."""
    rules = css_rules(FILE_EDITOR_CSS.read_text(encoding="utf-8"))
    for (selector, prop), expected in FILE_EDITOR_HOOKS.items():
        assert _declaration(rules, selector, prop) == expected, (selector, prop)


def test_every_files_filter_field_reads_the_tokens_with_todays_fallbacks():
    """כל שדות הסינון בעמוד הקבצים, וכל אחד מהם — שדה שנשכח היה נשאר בלתי נראה בערכה שהצהירה."""
    html = FILES_HTML.read_text(encoding="utf-8")
    for field in FILES_FILTER_FIELDS:
        tag = re.search(r"<" + re.escape(field) + r"[^>]*>", html, re.DOTALL)
        assert tag, field
        declarations = _style_declarations(tag.group(0))
        assert declarations, field
        for prop, expected in FILES_FILTER_STYLE.items():
            assert declarations.get(prop) == expected, (field, prop, declarations.get(prop))


def test_files_page_has_no_unhooked_copy_of_the_filter_style():
    """שדה רביעי עם אותו ``style`` בלי הווו — העתק שנסחף — היה נשאר בלתי נראה בערכה שהצהירה."""
    html = FILES_HTML.read_text(encoding="utf-8")
    assert "border: 1px solid rgba(255,255,255,0.2)" not in html
    assert "background: rgba(255,255,255,0.1)" not in html


def test_every_settings_field_reads_the_form_field_tokens_with_todays_fallbacks():
    """השדה של "הוראות לסוכן" וכל תיבות הבחירה בעמוד ההגדרות — אותו סוג רכיב כמו שדות הסינון בעמוד הקבצים."""
    html = SETTINGS_HTML.read_text(encoding="utf-8")
    for field_id, expected_style in SETTINGS_FIELD_STYLES.items():
        tag = re.search(r'<(?:select|textarea)\b[^>]*\bid="' + re.escape(field_id) + r'"[^>]*>', html, re.DOTALL)
        assert tag, field_id
        declarations = _style_declarations(tag.group(0))
        for prop, expected in expected_style.items():
            assert declarations.get(prop) == expected, (field_id, prop, declarations.get(prop))


def test_settings_page_has_no_unhooked_field():
    """שדה שנוסף לעמוד ההגדרות עם ``style`` לבן קבוע, בלי הווו, היה נשאר בלתי נראה בערכה שהצהירה."""
    html = SETTINGS_HTML.read_text(encoding="utf-8")
    offenders = []
    for tag in re.findall(r"<(?:select|textarea|input)\b[^>]*>", html, re.DOTALL):
        declarations = _style_declarations(tag)
        for prop in ("background", "border"):
            value = declarations.get(prop, "")
            if "rgba(255" in value and "var(--form-field-" not in value:
                offenders.append(f"{prop}: {value} — {' '.join(tag.split())[:80]}")
    assert not offenders, "\n".join(offenders)


def _glass_card_tags(html):
    """כל תגית פתיחה של ``.glass-card`` בתבנית, גם כזו שנבנית במחרוזת של JavaScript."""
    return re.findall(r"<div\b[^>]*\bclass=\"glass-card\b[^\"]*\"[^>]*>", html, re.DOTALL)


@pytest.mark.parametrize("template", [SETTINGS_HTML, SETTINGS_PUSH_DEBUG_HTML], ids=lambda p: p.name)
def test_every_nested_card_with_an_inline_background_reads_the_token(template):
    """כל כרטיס עם רקע ב-``style`` שבתגית — בעמודים האלה כולם כרטיסים שבתוך כרטיס — קורא את הווו, עם הערך של היום."""
    html = template.read_text(encoding="utf-8")
    backgrounds = [
        _style_declarations(tag)["background"]
        for tag in _glass_card_tags(html)
        if "background" in _style_declarations(tag)
    ]
    assert backgrounds, f"לא נמצאו כרטיסים עם רקע ב-{template.name} — הבדיקה לא בודקת כלום"
    offenders = [bg for bg in backgrounds if bg.replace(" ", "") != NESTED_CARD_BACKGROUND]
    assert not offenders, offenders


def test_dashboard_feed_and_push_read_the_tokens_with_todays_fallbacks():
    """הבלוקים בפיד, וכל סוגי התג והבאדג' — כל אחד עם הערך שצבע עד היום."""
    rules = css_rules(template_css(DASHBOARD_HTML))
    for (selector, prop), expected in DASHBOARD_HOOKS.items():
        assert _declaration(rules, selector, prop) == expected, (selector, prop)


def test_dashboard_has_no_unhooked_badge_or_pill_variant():
    """כל סוג של תג או באדג' בכלל הכללי קורא את הטוקן — סוג חדש בלי הווו היה נשאר בלתי קריא."""
    rules = css_rules(template_css(DASHBOARD_HTML))
    token_of = {"timeline-badge": BADGE_TEXT, "status": PILL_TEXT}
    offenders = []
    for selector, decl in rules:
        variant = re.fullmatch(r"\.(timeline-badge|status)-[a-z]+", selector)
        if variant and "color" in decl and token_of[variant.group(1)] not in decl["color"]:
            offenders.append(f"{selector} {{color: {decl['color']}}}")
    assert not offenders, "\n".join(offenders)


def test_workspace_button_reads_the_tokens_with_todays_values():
    """הרקע — מעבר הצבע של היום כ-fallback; הגבול נשאר ``none``; המסגרת דרך משתנה ביניים."""
    rules = css_rules(template_css(BASE_HTML))
    for (selector, prop), expected in WORKSPACE_HOOKS.items():
        assert _declaration(rules, selector, prop) == expected, (selector, prop)


def test_workspace_ring_is_not_a_theme_token():
    """משתנה הביניים אינו ברשימה הלבנה: ערכה שהייתה קובעת אותו ישירות הייתה עוקפת את ``inset 0 0 0 1px``."""
    assert WORKSPACE_RING not in ALLOWED_VARIABLES_WHITELIST


def test_editor_buttons_read_the_tokens_with_todays_fallbacks():
    """``.btn-switch-editor`` ו-``.btn-editor-clip`` ב-``codemirror-custom.css``, כולל הריחוף."""
    rules = css_rules(CODEMIRROR_CUSTOM_CSS.read_text(encoding="utf-8"))
    for (selector, prop), expected in EDITOR_HOOKS.items():
        assert _declaration(rules, selector, prop) == expected, (selector, prop)


def test_md_trigger_reads_the_editor_text_token():
    """כפתור ה-MD יושב באותה שורה, ולכן קורא את אותו וו טקסט, עם הצבע שצבע עד היום כ-fallback."""
    rules = css_rules(MARKDOWN_TOOLBAR_CSS.read_text(encoding="utf-8"))
    for (selector, prop), expected in MD_TRIGGER_HOOKS.items():
        assert _declaration(rules, selector, prop) == expected, (selector, prop)


def test_code_view_toolbar_and_meta_read_the_tokens_with_todays_fallbacks():
    """סרגל החיפוש, שורת החיפוש (גם בפוקוס), הכפתורים שבה, "מסך מלא" ומלבני הפרטים ב-``view_file.html``."""
    rules = css_rules(template_css(VIEW_FILE_HTML))
    for (selector, prop), expected in VIEW_FILE_HOOKS.items():
        assert _declaration(rules, selector, prop) == expected, (selector, prop)


def test_search_capsule_reads_the_token_with_the_general_rules_border():
    """ה-fallback של הגבול הוא הצבע שהכלל הכללי ``.md-search-capsule`` צובע — כך שהוא לא זז."""
    rules = css_rules(template_css(MD_PREVIEW_HTML))
    general = _declaration(rules, ".md-search-capsule", "border")
    color = re.fullmatch(r"1px solid (.+)", general)
    assert color, general
    for scope in CAPSULE_SCOPES:
        hooked = _declaration(rules, f"{scope} .md-search-capsule", "border-color")
        assert hooked == f"var({CAPSULE_BORDER}, {color.group(1)})", (scope, hooked)


def test_search_capsule_focus_rule_still_overrides_the_hook():
    """בזמן הקלדה הגבול הוא של כלל ה-``:focus-within`` — הוא ספציפי יותר מהכלל שקורא את הווו."""
    rules = css_rules(template_css(MD_PREVIEW_HTML))
    for scope in CAPSULE_SCOPES:
        focus = _declaration(rules, f"{scope} .md-search-capsule:focus-within", "border-color")
        assert CAPSULE_BORDER not in focus, (scope, focus)


def _theme(variables=None):
    """הערכה שבדוגמה ב-``custom_themes_guide.rst`` — ערכה בהירה, עם הווים כפי שהם כתובים שם."""
    body = {
        "name": "Pen Paper Coffee UI",
        "type": "light",
        "colors": {
            "editor.background": "#f8f6f1",
            "editor.foreground": "#2b3f6a",
            "editorWidget.background": "#ebe8df",
        },
        "tokenColors": [],
    }
    if variables is not None:
        body["variables"] = variables
    return body


DOCUMENTED_VARIABLES = {
    FIELD_BORDER: "rgba(110, 78, 68, 0.35)",
    FIELD_BG: "rgba(255, 253, 249, 0.6)",
    FIELD_FOCUS_BORDER: "#6e4e44",
    BLOCK_BG: "rgba(110, 78, 68, 0.06)",
    ITEM_BORDER: "rgba(110, 78, 68, 0.35)",
    BADGE_TEXT: "#2b3f6a",
    PILL_TEXT: "#2b3f6a",
    CAPSULE_BORDER: "rgba(110, 78, 68, 0.3)",
    WORKSPACE_BG: "rgba(224, 218, 211, 0.55)",
    WORKSPACE_BORDER: "rgba(110, 78, 68, 0.3)",
    EDITOR_BTN_TEXT: "#2b3f6a",
    EDITOR_BTN_BG: "rgba(255, 253, 249, 0.6)",
    EDITOR_BTN_BORDER: "rgba(110, 78, 68, 0.3)",
    EDITOR_BTN_HOVER_BG: "rgba(110, 78, 68, 0.12)",
    EDITOR_SWITCH_BG: "#e4dcc8",
    EDITOR_SWITCH_HOVER_BG: "#d2b493",
    CODE_TOOLBAR_BG: "rgba(224, 218, 211, 0.55)",
    CODE_TOOLBAR_BORDER: "rgba(110, 78, 68, 0.3)",
    CODE_TOOLBAR_HOVER_BG: "rgba(110, 78, 68, 0.12)",
    CODE_TOOLBAR_TEXT: "#2b3f6a",
    CODE_CAPSULE_BG: "rgba(248, 246, 241, 0.25)",
    CODE_CAPSULE_FOCUS_BORDER: "#6e4e44",
    META_ITEM_BG: "rgba(255, 253, 249, 0.6)",
    NESTED_CARD_BG: "rgba(110, 78, 68, 0.06)",
}


def _documented_example():
    """בלוק ה-JSON הראשון בסעיף ``theme-variables-light-import-hooks`` ב-``custom_themes_guide.rst``, כפי שהוא כתוב."""
    text = CUSTOM_THEMES_GUIDE.read_text(encoding="utf-8")
    section = text.split(".. _theme-variables-light-import-hooks:", 1)[1]
    block = re.search(r"\.\. code-block:: json\n\n((?:   .*\n|\n)+)", section)
    assert block, "אין בלוק JSON בסעיף"
    return json.loads("\n".join(line[3:] for line in block.group(1).splitlines()))


def test_the_documented_example_declares_exactly_these_tokens():
    """הדוגמה בתיעוד והמילון כאן הם אותה דוגמה — ושום וו לא נשמט ממנה."""
    assert _documented_example()["variables"] == DOCUMENTED_VARIABLES
    assert set(DOCUMENTED_VARIABLES) == set(TOKENS)


def test_documented_example_passes_validation():
    """הדוגמה שבתיעוד (``custom_themes_guide.rst``) עוברת את הוולידציה כפי שהיא כתובה."""
    ok, error = validate_theme_json(json.dumps(_documented_example()))
    assert ok, error


@pytest.mark.parametrize("token", TOKENS)
def test_malformed_value_is_rejected_and_names_the_key(token):
    ok, error = validate_theme_json(json.dumps(_theme({token: "teal"})))
    assert not ok
    assert token in error


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(webapp_app, "get_db", lambda: db)
    return db


@pytest.fixture
def client(monkeypatch):
    # setitem ולא השמה ישירה: ‏webapp_app.app משותף לכל הסשן, ו-monkeypatch
    # משחזר את הערך הקודם בסיום ה-fixture במקום להשאיר אותו דלוף לטסטים הבאים.
    monkeypatch.setitem(webapp_app.app.config, "TESTING", True)
    with webapp_app.app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = 42
            sess["user_data"] = {"id": 42, "first_name": "Tester"}
        yield c


def _stored_variables(db):
    """המשתנים כפי שנשמרו במסד — לא כפי שהבקשה ביקשה."""
    user = db.users.find_one({"user_id": 42})
    assert user and len(user.get("custom_themes") or []) == 1, user
    return user["custom_themes"][0]["variables"]


def test_import_stores_every_declared_token(client, fake_db):
    """המסלול המרכזי: כל הטוקנים נשמרים, והצבעים שהערכה גוזרת מ-``colors`` לא זזים."""
    response = client.post(
        "/api/themes/import", json={"json_content": json.dumps(_theme(DOCUMENTED_VARIABLES))}
    )
    assert response.status_code == 200, response.get_data(as_text=True)[:300]

    stored = _stored_variables(fake_db)
    for key, value in DOCUMENTED_VARIABLES.items():
        assert stored.get(key) == value, (key, stored.get(key))
    assert stored.get("--bg-primary") == "#f8f6f1"


def test_import_without_the_block_leaves_the_tokens_unset(client, fake_db):
    """ערכה שאינה מצהירה — הטוקנים לא מוגדרים, וכל כלל נופל לערך שנצבע בו היום."""
    response = client.post("/api/themes/import", json={"json_content": json.dumps(_theme())})
    assert response.status_code == 200, response.get_data(as_text=True)[:300]
    stored = _stored_variables(fake_db)
    for token in TOKENS:
        assert token not in stored, token
