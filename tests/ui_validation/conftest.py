"""
tests/ui_validation/conftest.py

Pytest fixtures for UI validation tests.
Uses pytest-playwright for browser automation.

הערות חשובות:
- לא דורסים את fixture 'page' המובנה של pytest-playwright
- BASE_URL מגיע מ-ENV עם ברירת מחדל
- headless/slowmo/viewport נשלטים דרך ENV
- credentials מגיעים מ-ENV/Secrets בלבד - לא מקודדים בקוד
"""

import os
from pathlib import Path
from typing import Generator

import pytest
from playwright.sync_api import Page, Browser, BrowserContext, Playwright

# Configuration from environment variables
BASE_URL = os.environ.get("UI_TEST_BASE_URL", "https://code-keeper.onrender.com")
HEADLESS = os.environ.get("UI_TEST_HEADLESS", "true").lower() == "true"
SLOW_MO = int(os.environ.get("UI_TEST_SLOW_MO", "0"))
DEFAULT_TIMEOUT = int(os.environ.get("UI_TEST_TIMEOUT", "30000"))

# Credentials from environment (never hardcoded)
TEST_USERNAME = os.environ.get("UI_TEST_USERNAME", "")
TEST_PASSWORD = os.environ.get("UI_TEST_PASSWORD", "")

# Snapshot configuration
SNAPSHOT_DIR = Path(__file__).parent / "snapshots"
SNAPSHOT_THRESHOLD = float(os.environ.get("UI_TEST_SNAPSHOT_THRESHOLD", "0.1"))


@pytest.fixture(scope="session")
def base_url() -> str:
    """
    Base URL לבדיקות UI.
    נשלט דרך משתנה סביבה UI_TEST_BASE_URL.
    """
    return BASE_URL


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args: dict) -> dict:
    """
    הגדרות context לדפדפן.
    מוסיף viewport ברירת מחדל ו-locale עברי.
    """
    return {
        **browser_context_args,
        "viewport": {"width": 1920, "height": 1080},
        "locale": "he-IL",
        "timezone_id": "Asia/Jerusalem",
        "ignore_https_errors": True,
    }


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args: dict) -> dict:
    """
    הגדרות הפעלת הדפדפן.
    headless ו-slowmo נשלטים דרך ENV.
    """
    return {
        **browser_type_launch_args,
        "headless": HEADLESS,
        "slow_mo": SLOW_MO,
    }


@pytest.fixture
def app_page(page: Page, base_url: str) -> Generator[Page, None, None]:
    """
    דף מוגדר לבדיקות UI עם timeout וניווט בסיסי.

    שימוש ב-app_page במקום page ישירות כדי:
    - לא לדרוס את ה-fixture המובנה
    - להוסיף הגדרות ספציפיות לאפליקציה
    - לנווט ל-base_url אוטומטית
    """
    page.set_default_timeout(DEFAULT_TIMEOUT)
    page.set_default_navigation_timeout(DEFAULT_TIMEOUT)

    # Navigate to base URL
    page.goto(base_url)
    page.wait_for_load_state("networkidle")

    yield page


@pytest.fixture
def authenticated_page(page: Page, base_url: str) -> Generator[Page, None, None]:
    """
    דף מאומת לבדיקות שדורשות התחברות.

    הערה: credentials מגיעים מ-ENV בלבד.
    אם אין credentials, הבדיקה תדלג.
    """
    if not TEST_USERNAME or not TEST_PASSWORD:
        pytest.skip("UI_TEST_USERNAME/UI_TEST_PASSWORD not set in environment")

    page.set_default_timeout(DEFAULT_TIMEOUT)
    page.set_default_navigation_timeout(DEFAULT_TIMEOUT)

    # Navigate to login page
    page.goto(f"{base_url}/login")
    page.wait_for_load_state("networkidle")

    # Login flow - using data-testid selectors
    # Implementation depends on actual login form structure
    # page.locator("[data-testid='username-input']").fill(TEST_USERNAME)
    # page.locator("[data-testid='password-input']").fill(TEST_PASSWORD)
    # page.locator("[data-testid='login-button']").click()
    # page.wait_for_load_state("networkidle")

    yield page


@pytest.fixture
def mobile_page(page: Page, base_url: str) -> Generator[Page, None, None]:
    """
    דף עם viewport מובייל (375x667 - iPhone SE).
    """
    page.set_viewport_size({"width": 375, "height": 667})
    page.set_default_timeout(DEFAULT_TIMEOUT)
    page.goto(base_url)
    page.wait_for_load_state("networkidle")

    yield page


@pytest.fixture
def tablet_page(page: Page, base_url: str) -> Generator[Page, None, None]:
    """
    דף עם viewport טאבלט (768x1024 - iPad).
    """
    page.set_viewport_size({"width": 768, "height": 1024})
    page.set_default_timeout(DEFAULT_TIMEOUT)
    page.goto(base_url)
    page.wait_for_load_state("networkidle")

    yield page


@pytest.fixture
def desktop_page(page: Page, base_url: str) -> Generator[Page, None, None]:
    """
    דף עם viewport דסקטופ (1920x1080).
    """
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.set_default_timeout(DEFAULT_TIMEOUT)
    page.goto(base_url)
    page.wait_for_load_state("networkidle")

    yield page


@pytest.fixture
def snapshot_path() -> Path:
    """
    נתיב לתיקיית snapshots.
    """
    return SNAPSHOT_DIR


@pytest.fixture
def snapshot_threshold() -> float:
    """
    סף לסבילות snapshot (max_diff_ratio).
    """
    return SNAPSHOT_THRESHOLD


# Theme fixtures
@pytest.fixture(params=[
    "dark",
    "dim",
    "classic",
    "ocean",
    "rose-pine-dawn",
    "nebula",
    "high-contrast",
])
def theme_name(request) -> str:
    """
    Parametrized fixture לכל התמות.
    """
    return request.param


@pytest.fixture
def page_with_theme(page: Page, base_url: str, theme_name: str) -> Generator[Page, None, None]:
    """
    דף עם תמה מוגדרת.
    """
    page.set_default_timeout(DEFAULT_TIMEOUT)
    page.goto(base_url)
    page.wait_for_load_state("networkidle")

    # Set theme via JavaScript (localStorage + attribute)
    page.evaluate(f"""() => {{
        localStorage.setItem('dark_mode_preference', '{theme_name}');
        document.documentElement.setAttribute('data-theme', '{theme_name}');
    }}""")

    # Reload to apply theme
    page.reload()
    page.wait_for_load_state("networkidle")

    yield page


# Viewport parametrization fixtures
@pytest.fixture(params=[
    {"width": 320, "height": 568, "name": "mobile_320x568"},
    {"width": 375, "height": 667, "name": "mobile_375x667"},
    {"width": 414, "height": 896, "name": "mobile_414x896"},
    {"width": 768, "height": 1024, "name": "tablet_768x1024"},
    {"width": 1024, "height": 768, "name": "tablet_1024x768"},
    {"width": 1366, "height": 768, "name": "laptop_1366x768"},
    {"width": 1920, "height": 1080, "name": "desktop_1920x1080"},
])
def viewport_params(request) -> dict:
    """
    Parametrized fixture לכל גדלי ה-viewport.
    """
    return request.param


@pytest.fixture
def page_with_viewport(page: Page, base_url: str, viewport_params: dict) -> Generator[Page, None, None]:
    """
    דף עם viewport מוגדר.
    """
    page.set_viewport_size({
        "width": viewport_params["width"],
        "height": viewport_params["height"],
    })
    page.set_default_timeout(DEFAULT_TIMEOUT)
    page.goto(base_url)
    page.wait_for_load_state("networkidle")

    yield page
