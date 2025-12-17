"""
tests/ui_validation/helpers/viewport_sizes.py

Viewport size definitions for responsive testing.
מכיל גדלי viewport סטנדרטיים למכשירים שונים.
"""

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class ViewportSize:
    """
    Represents a viewport size with metadata.
    """
    name: str
    width: int
    height: int
    device_type: str  # mobile, tablet, laptop, desktop
    description: str = ""

    def to_dict(self) -> Dict[str, int]:
        """Convert to Playwright viewport format."""
        return {"width": self.width, "height": self.height}


# Standard viewport sizes for testing
VIEWPORT_SIZES: Dict[str, ViewportSize] = {
    # Mobile devices
    "mobile_320x568": ViewportSize(
        name="mobile_320x568",
        width=320,
        height=568,
        device_type="mobile",
        description="iPhone SE (1st gen)"
    ),
    "mobile_375x667": ViewportSize(
        name="mobile_375x667",
        width=375,
        height=667,
        device_type="mobile",
        description="iPhone 6/7/8, standard mobile"
    ),
    "mobile_414x896": ViewportSize(
        name="mobile_414x896",
        width=414,
        height=896,
        device_type="mobile",
        description="iPhone XR/11"
    ),
    "mobile_390x844": ViewportSize(
        name="mobile_390x844",
        width=390,
        height=844,
        device_type="mobile",
        description="iPhone 12/13 Pro"
    ),

    # Tablet devices
    "tablet_768x1024": ViewportSize(
        name="tablet_768x1024",
        width=768,
        height=1024,
        device_type="tablet",
        description="iPad (portrait)"
    ),
    "tablet_1024x768": ViewportSize(
        name="tablet_1024x768",
        width=1024,
        height=768,
        device_type="tablet",
        description="iPad (landscape)"
    ),
    "tablet_810x1080": ViewportSize(
        name="tablet_810x1080",
        width=810,
        height=1080,
        device_type="tablet",
        description="iPad 10th gen"
    ),

    # Laptop screens
    "laptop_1366x768": ViewportSize(
        name="laptop_1366x768",
        width=1366,
        height=768,
        device_type="laptop",
        description="Common laptop resolution"
    ),
    "laptop_1440x900": ViewportSize(
        name="laptop_1440x900",
        width=1440,
        height=900,
        device_type="laptop",
        description="MacBook Air 13"
    ),
    "laptop_1536x864": ViewportSize(
        name="laptop_1536x864",
        width=1536,
        height=864,
        device_type="laptop",
        description="Full HD scaled 125%"
    ),

    # Desktop screens
    "desktop_1920x1080": ViewportSize(
        name="desktop_1920x1080",
        width=1920,
        height=1080,
        device_type="desktop",
        description="Full HD (1080p)"
    ),
    "desktop_2560x1440": ViewportSize(
        name="desktop_2560x1440",
        width=2560,
        height=1440,
        device_type="desktop",
        description="QHD (1440p)"
    ),
}


def get_mobile_viewports() -> List[ViewportSize]:
    """Get all mobile viewport sizes."""
    return [v for v in VIEWPORT_SIZES.values() if v.device_type == "mobile"]


def get_tablet_viewports() -> List[ViewportSize]:
    """Get all tablet viewport sizes."""
    return [v for v in VIEWPORT_SIZES.values() if v.device_type == "tablet"]


def get_laptop_viewports() -> List[ViewportSize]:
    """Get all laptop viewport sizes."""
    return [v for v in VIEWPORT_SIZES.values() if v.device_type == "laptop"]


def get_desktop_viewports() -> List[ViewportSize]:
    """Get all desktop viewport sizes."""
    return [v for v in VIEWPORT_SIZES.values() if v.device_type == "desktop"]


def get_all_viewports() -> List[ViewportSize]:
    """Get all viewport sizes."""
    return list(VIEWPORT_SIZES.values())


# Breakpoint thresholds (matching common CSS frameworks)
BREAKPOINTS = {
    "xs": 0,      # Extra small (mobile)
    "sm": 576,    # Small (large mobile)
    "md": 768,    # Medium (tablet)
    "lg": 992,    # Large (small laptop)
    "xl": 1200,   # Extra large (laptop)
    "xxl": 1400,  # Extra extra large (desktop)
}


def get_breakpoint_for_width(width: int) -> str:
    """
    Get breakpoint name for a given width.
    """
    if width < BREAKPOINTS["sm"]:
        return "xs"
    elif width < BREAKPOINTS["md"]:
        return "sm"
    elif width < BREAKPOINTS["lg"]:
        return "md"
    elif width < BREAKPOINTS["xl"]:
        return "lg"
    elif width < BREAKPOINTS["xxl"]:
        return "xl"
    else:
        return "xxl"
