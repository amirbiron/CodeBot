"""
גזירת טוקני --glass* לערכות בהירות מיובאות.

רקע: הממשק מצייר כרטיסים, badges, navbar וכפתורים משניים עם --glass ו---glass-border.
אף מפתח ב-VSCODE_TO_CSS_MAP לא ממלא אותם, ולכן ערכה מיובאת מקבלת את ערכי ה-FALLBACK.
ערכי ה-FALLBACK הם גוונים לבנים — נכונים לערכה כהה, ובערכה בהירה הם 2%/5% שחור.
נמדד בכרומיום מול השרת האמיתי: כרטיס מול רקע = 1.053, כלומר בלתי נראה.
"""
import pytest

from services.theme_parser_service import (
    FALLBACK_DARK,
    composite_over,
    contrast_ratio,
    normalize_color_to_rgba,
    parse_vscode_theme,
)

LIGHT = {
    "name": "Light Fixture", "type": "light",
    "colors": {"editor.background": "#f8f6f1", "editor.foreground": "#2b3f6a",
               "sideBar.background": "#ebe8df", "activityBar.background": "#e0dad3"},
}
DARK = {
    "name": "Dark Fixture", "type": "dark",
    "colors": {"editor.background": "#313a36", "editor.foreground": "#e4e3e1",
               "sideBar.background": "#3d4843", "activityBar.background": "#36403b"},
}
# ה-body צבוע linear-gradient(--bg-primary → --bg-secondary), אז המשטח
# חייב להיבדל משני הקצוות — לא רק מהבהיר.
MIN_SURFACE_CONTRAST = 1.10
MIN_BORDER_CONTRAST = 1.25
MIN_HOVER_CONTRAST = 1.05


def _vars(theme):
    return parse_vscode_theme(theme)["variables"]


def _painted(color: str, over: str) -> str:
    """
    הצבע שהדפדפן מצייר בפועל: מרכיב צבע (אולי שקוף למחצה) מעל רקע אטום.

    בלי זה הבדיקה חסרת ערך — contrast_ratio מתעלם מ-alpha, ולכן
    rgba(0, 0, 0, 0.02) נמדד כשחור מלא ומחזיר ניגודיות גבוהה מדומה.
    """
    painted = composite_over(color, over)
    assert painted is not None, f"צבע לא ניתן לפרסור: {color} / {over}"
    return painted


def test_light_theme_surface_separates_from_both_gradient_ends():
    v = _vars(LIGHT)
    for end in (v["--bg-primary"], v["--bg-secondary"]):
        painted = _painted(v["--glass"], end)
        assert contrast_ratio(painted, end) >= MIN_SURFACE_CONTRAST, (
            f"--glass={v['--glass']} מצויר {painted} מול {end}"
        )


def test_light_theme_border_is_visible_on_the_surface():
    v = _vars(LIGHT)
    surface = _painted(v["--glass"], v["--bg-primary"])
    border = _painted(v["--glass-border"], surface)
    assert contrast_ratio(border, surface) >= MIN_BORDER_CONTRAST, (
        f"קו {v['--glass-border']} מצויר {border} על משטח {surface}"
    )


def test_light_theme_hover_differs_perceptibly_from_resting_surface():
    """ערך שונה אינו מספיק — ההבדל חייב להיות נראה אחרי הציור."""
    v = _vars(LIGHT)
    resting = _painted(v["--glass"], v["--bg-primary"])
    hover = _painted(v["--glass-hover"], v["--bg-primary"])
    assert contrast_ratio(hover, resting) >= MIN_HOVER_CONTRAST, (
        f"hover {hover} מול משטח {resting}"
    )


def test_derived_glass_values_survive_the_whitelist_sanitizer():
    from services.theme_parser_service import validate_and_sanitize_theme_variables
    v = _vars(LIGHT)
    clean = validate_and_sanitize_theme_variables(v)
    for key in ("--glass", "--glass-border", "--glass-hover"):
        assert key in clean, f"{key} סונן על ידי ה-whitelist"


def test_dark_theme_glass_is_left_untouched():
    """ערכה כהה נראית טוב היום — הגזירה לא אמורה לגעת בה בכלל."""
    v = _vars(DARK)
    for key in ("--glass", "--glass-border", "--glass-hover"):
        assert v[key] == FALLBACK_DARK[key], f"{key} השתנה בערכה כהה"


@pytest.mark.parametrize("a,b,expected", [("#ffffff", "#000000", 21.0), ("#ffffff", "#ffffff", 1.0)])
def test_contrast_ratio_helper(a, b, expected):
    assert contrast_ratio(a, b) == pytest.approx(expected, abs=0.01)


# ---------------------------------------------------------------------------
# ממצאים שהתגלו בסקירה
# ---------------------------------------------------------------------------

RGB_LIGHT = {
    "name": "rgb light", "type": "light",
    "colors": {"editor.background": "rgb(248, 246, 241)",
               "editor.foreground": "rgb(43, 63, 106)",
               "sideBar.background": "rgb(235, 232, 223)"},
}
# ה-body צבוע linear-gradient(--bg-primary → --bg-secondary). כאן הרקע המשני
# בהיר מהראשי, ולכן הכהיה ממנו עלולה לנחות בדיוק על הראשי.
INVERTED_LIGHT = {
    "name": "inverted light", "type": "light",
    "colors": {"editor.background": "#f0f0f0", "sideBar.background": "#ffffff",
               "editor.foreground": "#222222"},
}


def test_light_theme_declared_in_rgb_is_recognised_as_light():
    """VALID_COLOR_REGEX מאשר rgb()/rgba(), ולכן גם הם חייבים להיכנס לגזירה."""
    v = _vars(RGB_LIGHT)
    assert v["--glass"] != FALLBACK_DARK["--glass"]
    for end in (v["--bg-primary"], v["--bg-secondary"]):
        painted = _painted(v["--glass"], end)
        assert contrast_ratio(painted, end) >= MIN_SURFACE_CONTRAST


def test_surface_separates_even_when_secondary_is_lighter_than_primary():
    v = _vars(INVERTED_LIGHT)
    for end in (v["--bg-primary"], v["--bg-secondary"]):
        painted = _painted(v["--glass"], end)
        assert contrast_ratio(painted, end) >= MIN_SURFACE_CONTRAST, (
            f"--glass={v['--glass']} מול {end}"
        )


def test_contrast_ratio_refuses_to_answer_for_a_translucent_colour():
    """
    ההתעלמות מ-alpha החזירה 19.44 עבור rgba(0,0,0,0.02) מעל נייר בהיר,
    בעוד הצבע המצויר בפועל נותן 1.045. ערך כזה נראה אמין ואינו נכון.
    """
    assert contrast_ratio("rgba(0, 0, 0, 0.02)", "#f8f6f1") is None


def test_composite_over_matches_the_painted_colour():
    assert composite_over("rgba(0, 0, 0, 0.02)", "#f8f6f1") == "#f3f1ec"
    assert composite_over("#ffffff", "#000000") == "#ffffff"
    assert composite_over("not-a-colour", "#000000") is None
