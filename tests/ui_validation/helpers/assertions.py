"""
tests/ui_validation/helpers/assertions.py

Custom assertions for UI validation tests.
מכיל פונקציות בדיקה מותאמות לבדיקות UI.

כולל tolerances למדידות (±5px, ±2%) כנדרש.
"""

import math
import re
from typing import Optional, Tuple, Union

from playwright.sync_api import Page, Locator, expect


# ========== Layout Assertions ==========

def assert_no_horizontal_scroll(
    page: Page,
    tolerance_px: int = 5
) -> None:
    """
    בדיקה שאין גלילה אופקית.

    Args:
        page: הדף לבדיקה
        tolerance_px: סבילות בפיקסלים (ברירת מחדל: ±5px)
    """
    scroll_width = page.evaluate("() => document.documentElement.scrollWidth")
    client_width = page.evaluate("() => document.documentElement.clientWidth")

    overflow = scroll_width - client_width
    assert overflow <= tolerance_px, (
        f"גלילה אופקית לא צפויה: רוחב מסמך ({scroll_width}px) > "
        f"רוחב viewport ({client_width}px) + tolerance ({tolerance_px}px). "
        f"Overflow: {overflow}px"
    )


def assert_element_within_viewport(
    page: Page,
    locator: Locator,
    tolerance_px: int = 5
) -> None:
    """
    בדיקה שאלמנט נמצא בתוך ה-viewport.

    Args:
        page: הדף
        locator: האלמנט לבדיקה
        tolerance_px: סבילות בפיקסלים
    """
    box = locator.bounding_box()
    assert box is not None, "האלמנט לא נמצא או לא גלוי"

    viewport = page.viewport_size
    assert viewport is not None, "לא ניתן לקבל גודל viewport"

    assert box["x"] >= -tolerance_px, (
        f"האלמנט יוצא משמאל: x={box['x']}px"
    )
    assert box["y"] >= -tolerance_px, (
        f"האלמנט יוצא מלמעלה: y={box['y']}px"
    )
    assert box["x"] + box["width"] <= viewport["width"] + tolerance_px, (
        f"האלמנט יוצא מימין: right={box['x'] + box['width']}px > {viewport['width']}px"
    )
    assert box["y"] + box["height"] <= viewport["height"] + tolerance_px, (
        f"האלמנט יוצא מלמטה: bottom={box['y'] + box['height']}px > {viewport['height']}px"
    )


def assert_element_visible_with_tolerance(
    locator: Locator,
    expected_width: Optional[int] = None,
    expected_height: Optional[int] = None,
    tolerance_percent: float = 5.0
) -> None:
    """
    בדיקה שאלמנט גלוי עם סבילות לגודל.

    Args:
        locator: האלמנט לבדיקה
        expected_width: רוחב צפוי (אופציונלי)
        expected_height: גובה צפוי (אופציונלי)
        tolerance_percent: סבילות באחוזים (ברירת מחדל: ±5%)
    """
    expect(locator).to_be_visible()

    box = locator.bounding_box()
    assert box is not None, "האלמנט לא נמצא"

    if expected_width is not None:
        tolerance = expected_width * (tolerance_percent / 100)
        assert abs(box["width"] - expected_width) <= tolerance, (
            f"רוחב לא צפוי: {box['width']}px (צפוי: {expected_width}±{tolerance}px)"
        )

    if expected_height is not None:
        tolerance = expected_height * (tolerance_percent / 100)
        assert abs(box["height"] - expected_height) <= tolerance, (
            f"גובה לא צפוי: {box['height']}px (צפוי: {expected_height}±{tolerance}px)"
        )


def assert_elements_no_overlap(
    locator1: Locator,
    locator2: Locator
) -> None:
    """
    בדיקה שאין חפיפה בין שני אלמנטים.
    """
    box1 = locator1.bounding_box()
    box2 = locator2.bounding_box()

    assert box1 is not None and box2 is not None, "אחד האלמנטים לא נמצא"

    # Check for overlap
    no_overlap = (
        box1["x"] + box1["width"] <= box2["x"] or  # box1 is left of box2
        box2["x"] + box2["width"] <= box1["x"] or  # box2 is left of box1
        box1["y"] + box1["height"] <= box2["y"] or  # box1 is above box2
        box2["y"] + box2["height"] <= box1["y"]     # box2 is above box1
    )

    assert no_overlap, (
        f"חפיפה בין אלמנטים: "
        f"box1=({box1['x']}, {box1['y']}, {box1['width']}x{box1['height']}) "
        f"box2=({box2['x']}, {box2['y']}, {box2['width']}x{box2['height']})"
    )


# ========== CSS Variable Assertions ==========

def assert_css_variable_defined(
    page: Page,
    variable_name: str,
    expected_value: Optional[str] = None
) -> None:
    """
    בדיקה ש-CSS variable מוגדר.

    Args:
        page: הדף
        variable_name: שם המשתנה (עם -- בהתחלה)
        expected_value: ערך צפוי (אופציונלי)
    """
    if not variable_name.startswith("--"):
        variable_name = f"--{variable_name}"

    value = page.evaluate(f"""() => {{
        return getComputedStyle(document.documentElement)
            .getPropertyValue('{variable_name}').trim();
    }}""")

    assert value, f"CSS variable {variable_name} לא מוגדר"

    if expected_value is not None:
        assert value == expected_value, (
            f"ערך לא צפוי ל-{variable_name}: '{value}' (צפוי: '{expected_value}')"
        )


def assert_css_variables_defined(
    page: Page,
    variable_names: list
) -> None:
    """
    בדיקה שכל ה-CSS variables מוגדרים.
    """
    missing = []
    for var_name in variable_names:
        if not var_name.startswith("--"):
            var_name = f"--{var_name}"

        value = page.evaluate(f"""() => {{
            return getComputedStyle(document.documentElement)
                .getPropertyValue('{var_name}').trim();
        }}""")

        if not value:
            missing.append(var_name)

    assert not missing, f"CSS variables חסרים: {', '.join(missing)}"


# ========== Contrast Ratio Assertions ==========

def parse_color(color: str) -> Tuple[int, int, int]:
    """
    Parse CSS color to RGB tuple.
    Supports: rgb(), rgba(), hex.
    """
    color = color.strip().lower()

    # RGB/RGBA format
    rgb_match = re.match(r'rgba?\((\d+),\s*(\d+),\s*(\d+)', color)
    if rgb_match:
        return (int(rgb_match.group(1)), int(rgb_match.group(2)), int(rgb_match.group(3)))

    # Hex format
    hex_match = re.match(r'#([0-9a-f]{6})', color)
    if hex_match:
        hex_val = hex_match.group(1)
        return (
            int(hex_val[0:2], 16),
            int(hex_val[2:4], 16),
            int(hex_val[4:6], 16)
        )

    # Short hex format
    hex_short_match = re.match(r'#([0-9a-f]{3})', color)
    if hex_short_match:
        hex_val = hex_short_match.group(1)
        return (
            int(hex_val[0] * 2, 16),
            int(hex_val[1] * 2, 16),
            int(hex_val[2] * 2, 16)
        )

    raise ValueError(f"לא ניתן לפרסר צבע: {color}")


def get_luminance(rgb: Tuple[int, int, int]) -> float:
    """
    Calculate relative luminance per WCAG 2.1.
    """
    def channel_luminance(value: int) -> float:
        v = value / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * channel_luminance(r) + 0.7152 * channel_luminance(g) + 0.0722 * channel_luminance(b)


def calculate_contrast_ratio(color1: str, color2: str) -> float:
    """
    Calculate contrast ratio between two colors.
    """
    rgb1 = parse_color(color1)
    rgb2 = parse_color(color2)

    l1 = get_luminance(rgb1)
    l2 = get_luminance(rgb2)

    lighter = max(l1, l2)
    darker = min(l1, l2)

    return (lighter + 0.05) / (darker + 0.05)


def assert_contrast_ratio(
    foreground: str,
    background: str,
    min_ratio: float = 4.5,
    level: str = "AA"
) -> None:
    """
    בדיקת יחס ניגודיות לפי WCAG.

    Args:
        foreground: צבע הטקסט
        background: צבע הרקע
        min_ratio: יחס ניגודיות מינימלי (ברירת מחדל: 4.5 ל-AA)
        level: רמת WCAG (AA או AAA)
    """
    ratio = calculate_contrast_ratio(foreground, background)

    assert ratio >= min_ratio, (
        f"יחס ניגודיות נמוך מדי: {ratio:.2f} (נדרש: {min_ratio} לרמת {level}). "
        f"צבעים: {foreground} על {background}"
    )


# ========== Typography Assertions ==========

def assert_font_is_monospace(page: Page, locator: Locator) -> None:
    """
    בדיקה שהגופן הוא monospace.
    """
    font_family = page.evaluate(
        "(el) => getComputedStyle(el).fontFamily",
        locator.element_handle()
    )

    monospace_keywords = ["monospace", "consolas", "monaco", "courier", "source code", "fira code"]
    is_monospace = any(kw in font_family.lower() for kw in monospace_keywords)

    assert is_monospace, f"הגופן אינו monospace: {font_family}"


def assert_line_height_in_range(
    page: Page,
    locator: Locator,
    min_ratio: float = 1.2,
    max_ratio: float = 2.0
) -> None:
    """
    בדיקה שגובה השורה בטווח סביר.
    """
    line_height = page.evaluate(
        "(el) => parseFloat(getComputedStyle(el).lineHeight)",
        locator.element_handle()
    )
    font_size = page.evaluate(
        "(el) => parseFloat(getComputedStyle(el).fontSize)",
        locator.element_handle()
    )

    if math.isnan(line_height):
        # line-height: normal
        ratio = 1.2  # Approximate normal line height
    else:
        ratio = line_height / font_size

    assert min_ratio <= ratio <= max_ratio, (
        f"יחס גובה שורה מחוץ לטווח: {ratio:.2f} (טווח: {min_ratio}-{max_ratio})"
    )


def assert_text_direction_rtl(page: Page, locator: Locator) -> None:
    """
    בדיקה שכיוון הטקסט הוא RTL.
    """
    direction = page.evaluate(
        "(el) => getComputedStyle(el).direction",
        locator.element_handle()
    )

    assert direction == "rtl", f"כיוון טקסט לא צפוי: {direction} (צפוי: rtl)"


# ========== Accessibility Assertions ==========

def assert_focus_visible(page: Page, locator: Locator) -> None:
    """
    בדיקה שיש אינדיקציית פוקוס גלויה.
    """
    locator.focus()

    # Check outline
    outline = page.evaluate(
        "(el) => getComputedStyle(el).outline",
        locator.element_handle()
    )
    outline_width = page.evaluate(
        "(el) => parseFloat(getComputedStyle(el).outlineWidth)",
        locator.element_handle()
    )

    # Check box-shadow as alternative
    box_shadow = page.evaluate(
        "(el) => getComputedStyle(el).boxShadow",
        locator.element_handle()
    )

    has_outline = outline_width > 0 and "none" not in outline.lower()
    has_box_shadow = box_shadow and box_shadow != "none"

    assert has_outline or has_box_shadow, (
        f"אין אינדיקציית פוקוס גלויה. outline: {outline}, box-shadow: {box_shadow}"
    )


def assert_has_accessible_name(locator: Locator) -> None:
    """
    בדיקה שלאלמנט יש שם נגיש.
    """
    # Check for various accessible name sources
    aria_label = locator.get_attribute("aria-label")
    aria_labelledby = locator.get_attribute("aria-labelledby")
    title = locator.get_attribute("title")
    text_content = locator.text_content()

    has_name = (
        (aria_label and aria_label.strip()) or
        (aria_labelledby and aria_labelledby.strip()) or
        (title and title.strip()) or
        (text_content and text_content.strip())
    )

    assert has_name, "לאלמנט אין שם נגיש (aria-label, aria-labelledby, title, או תוכן טקסט)"


def assert_image_has_alt(locator: Locator) -> None:
    """
    בדיקה שלתמונה יש alt text.
    """
    alt = locator.get_attribute("alt")
    role = locator.get_attribute("role")

    # Decorative images may have role="presentation" or empty alt
    is_decorative = role == "presentation" or alt == ""

    assert alt is not None or is_decorative, (
        "לתמונה אין alt text ואינה מסומנת כדקורטיבית"
    )
