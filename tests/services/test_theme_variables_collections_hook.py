"""וו הדריסה של --collections-link-color, ושומר הטיפוס לפני בדיקת החברות.

הבדיקות עוברות דרך אותו ממשק שהצרכן משתמש בו: הפונקציות שה-endpoint
של הייבוא קורא להן בפועל (themes_api.import_theme), ולא דרך מסלול עוקף.
"""

from services.theme_parser_service import (
    ALLOWED_VARIABLES_WHITELIST,
    parse_vscode_theme,
    validate_and_sanitize_theme_variables,
)

COBALT_LIKE = {
    "name": "Cobalt Next",
    "type": "dark",
    "colors": {
        "editor.background": "#1b2b34",
        "editor.foreground": "#d8dee9",
        "focusBorder": "#ffffff",
    },
    "tokenColors": [],
}


def test_collections_link_color_is_whitelisted():
    """בלי זה הטוקן מסונן בשקט ולא מגיע ל-CSS."""
    assert "--collections-link-color" in ALLOWED_VARIABLES_WHITELIST


def test_explicit_variables_block_survives_validation():
    """הערך שערכה מצהירה עליו עובר את הוולידציה ונשמר כמו שהוא."""
    result = validate_and_sanitize_theme_variables(
        {"--collections-link-color": "#2e6161"}
    )
    assert result["--collections-link-color"] == "#2e6161"


def test_vscode_parse_does_not_invent_the_token():
    """מיפוי VS Code לבדו אינו מייצר את הטוקן — לכן נדרש בלוק variables מפורש."""
    variables = parse_vscode_theme(COBALT_LIKE)["variables"]
    assert "--collections-link-color" not in variables
    # ובלעדיו, שם הקובץ נצבע ב---primary, שכאן הוא לבן — מקור הבאג.
    assert variables["--primary"] == "#ffffff"


def test_explicit_variables_override_parsed_value():
    """המיזוג שה-endpoint מבצע: ההצהרה המפורשת גוברת על התוצאה שנגזרה מהמיפוי."""
    parsed = parse_vscode_theme(COBALT_LIKE)["variables"]
    merged = validate_and_sanitize_theme_variables(parsed)
    merged.update(
        validate_and_sanitize_theme_variables(
            {"--collections-link-color": "#2e6161", "--primary": "#5fb3b3"}
        )
    )
    assert merged["--collections-link-color"] == "#2e6161"
    assert merged["--primary"] == "#5fb3b3"
