"""
Helper utilities for UI validation tests.

Includes viewport sizes, custom assertions, and test utilities.
"""

from .viewport_sizes import VIEWPORT_SIZES, ViewportSize
from .assertions import (
    assert_no_horizontal_scroll,
    assert_element_within_viewport,
    assert_css_variable_defined,
    assert_css_variables_defined,
    assert_contrast_ratio,
    assert_element_visible_with_tolerance,
    assert_font_is_monospace,
    assert_line_height_in_range,
    assert_text_direction_rtl,
    assert_focus_visible,
    assert_has_accessible_name,
    assert_image_has_alt,
)

__all__ = [
    "VIEWPORT_SIZES",
    "ViewportSize",
    "assert_no_horizontal_scroll",
    "assert_element_within_viewport",
    "assert_css_variable_defined",
    "assert_css_variables_defined",
    "assert_contrast_ratio",
    "assert_element_visible_with_tolerance",
    "assert_font_is_monospace",
    "assert_line_height_in_range",
    "assert_text_direction_rtl",
    "assert_focus_visible",
    "assert_has_accessible_name",
    "assert_image_has_alt",
]
