"""
tests/ui_validation/pages/base_page.py

Base Page Object Model class for all pages.
מכיל סלקטורים ופעולות משותפות לכל הדפים.

שימוש בסלקטורים יציבים בלבד:
- data-testid
- aria-label
- role
- semantic HTML elements
"""

from playwright.sync_api import Page, Locator, expect


class BasePage:
    """
    Base class for all page objects.
    מכיל אלמנטים משותפים כמו header, footer, navigation.
    """

    def __init__(self, page: Page, base_url: str):
        self.page = page
        self.base_url = base_url

    # ========== Common Selectors (using stable selectors) ==========

    @property
    def header(self) -> Locator:
        """Header element"""
        return self.page.locator("header, [role='banner'], [data-testid='header']").first

    @property
    def footer(self) -> Locator:
        """Footer element"""
        return self.page.locator("footer, [role='contentinfo'], [data-testid='footer']").first

    @property
    def main_content(self) -> Locator:
        """Main content area"""
        return self.page.locator("main, [role='main'], [data-testid='main-content']").first

    @property
    def navigation(self) -> Locator:
        """Primary navigation"""
        return self.page.locator("nav, [role='navigation'], [data-testid='navigation']").first

    @property
    def mobile_menu_toggle(self) -> Locator:
        """Mobile menu toggle button"""
        return self.page.locator(
            "[data-testid='mobile-menu-toggle'], "
            "[aria-label*='תפריט'], "
            "[aria-label*='menu'], "
            "button.hamburger, "
            ".mobile-menu-btn"
        ).first

    @property
    def skip_to_content_link(self) -> Locator:
        """Skip to content accessibility link"""
        return self.page.locator(
            "[data-testid='skip-link'], "
            "a[href='#main'], "
            "a[href='#content'], "
            ".skip-link"
        ).first

    @property
    def page_title(self) -> Locator:
        """Page title (h1)"""
        return self.page.locator("h1, .page-title").first

    @property
    def modals(self) -> Locator:
        """All modal dialogs"""
        return self.page.locator(
            "[role='dialog'], "
            "[data-testid*='modal'], "
            ".modal, "
            "[aria-modal='true']"
        )

    @property
    def active_modal(self) -> Locator:
        """Currently visible modal"""
        return self.modals.filter(has=self.page.locator(":visible")).first

    @property
    def dropdowns(self) -> Locator:
        """All dropdown menus"""
        return self.page.locator(
            "[role='listbox'], "
            "[role='menu'], "
            "[data-testid*='dropdown'], "
            ".dropdown-menu"
        )

    @property
    def buttons(self) -> Locator:
        """All buttons"""
        return self.page.locator("button, [role='button'], input[type='button']")

    @property
    def primary_buttons(self) -> Locator:
        """Primary action buttons"""
        return self.page.locator(
            "button.btn-primary, "
            "[data-testid*='primary'], "
            ".btn.primary"
        )

    @property
    def loading_spinner(self) -> Locator:
        """Loading indicators"""
        return self.page.locator(
            "[data-testid='loading'], "
            "[aria-label*='טעינה'], "
            "[aria-label*='loading'], "
            ".spinner, "
            ".loading"
        )

    # ========== Common Actions ==========

    def navigate_to(self, path: str) -> None:
        """
        ניווט לנתיב ספציפי.
        """
        url = f"{self.base_url}{path}"
        self.page.goto(url)
        self.page.wait_for_load_state("networkidle")

    def wait_for_page_ready(self) -> None:
        """
        המתנה לטעינה מלאה של הדף.
        """
        self.page.wait_for_load_state("networkidle")
        # Wait for any loading spinners to disappear
        if self.loading_spinner.count() > 0:
            self.loading_spinner.first.wait_for(state="hidden", timeout=10000)

    def get_theme(self) -> str:
        """
        קבלת התמה הנוכחית.
        """
        return self.page.evaluate(
            "() => document.documentElement.getAttribute('data-theme') || 'default'"
        )

    def set_theme(self, theme: str) -> None:
        """
        הגדרת תמה חדשה.
        """
        self.page.evaluate(f"""() => {{
            localStorage.setItem('dark_mode_preference', '{theme}');
            document.documentElement.setAttribute('data-theme', '{theme}');
        }}""")

    def get_viewport_size(self) -> dict:
        """
        קבלת גודל ה-viewport הנוכחי.
        """
        return self.page.viewport_size

    def set_viewport_size(self, width: int, height: int) -> None:
        """
        הגדרת גודל viewport.
        """
        self.page.set_viewport_size({"width": width, "height": height})

    def scroll_to_element(self, locator: Locator) -> None:
        """
        גלילה לאלמנט ספציפי.
        """
        locator.scroll_into_view_if_needed()

    def scroll_to_bottom(self) -> None:
        """
        גלילה לתחתית הדף.
        """
        self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

    def scroll_to_top(self) -> None:
        """
        גלילה לראש הדף.
        """
        self.page.evaluate("window.scrollTo(0, 0)")

    def get_css_variable(self, variable_name: str) -> str:
        """
        קבלת ערך של CSS variable.
        """
        return self.page.evaluate(f"""() => {{
            return getComputedStyle(document.documentElement)
                .getPropertyValue('{variable_name}').trim();
        }}""")

    def get_computed_style(self, locator: Locator, property_name: str) -> str:
        """
        קבלת computed style של אלמנט.
        """
        element = locator.element_handle()
        if element:
            return self.page.evaluate(
                f"(el) => getComputedStyle(el).{property_name}",
                element
            )
        return ""

    def is_element_in_viewport(self, locator: Locator) -> bool:
        """
        בדיקה האם אלמנט נמצא בתוך ה-viewport.
        """
        return self.page.evaluate("""(selector) => {
            const el = document.querySelector(selector);
            if (!el) return false;
            const rect = el.getBoundingClientRect();
            return (
                rect.top >= 0 &&
                rect.left >= 0 &&
                rect.bottom <= window.innerHeight &&
                rect.right <= window.innerWidth
            );
        }""", locator.first.evaluate("el => el.tagName"))

    def get_element_bounding_box(self, locator: Locator) -> dict:
        """
        קבלת bounding box של אלמנט.
        """
        return locator.bounding_box()

    def has_horizontal_scroll(self) -> bool:
        """
        בדיקה האם יש גלילה אופקית.
        """
        return self.page.evaluate("""() => {
            return document.documentElement.scrollWidth > document.documentElement.clientWidth;
        }""")

    def get_document_width(self) -> int:
        """
        קבלת רוחב המסמך.
        """
        return self.page.evaluate("() => document.documentElement.scrollWidth")

    def get_viewport_width(self) -> int:
        """
        קבלת רוחב ה-viewport.
        """
        return self.page.evaluate("() => document.documentElement.clientWidth")

    def take_screenshot(self, path: str, full_page: bool = False) -> None:
        """
        צילום מסך.
        """
        self.page.screenshot(path=path, full_page=full_page)

    def take_element_screenshot(self, locator: Locator, path: str) -> None:
        """
        צילום מסך של אלמנט ספציפי.
        """
        locator.screenshot(path=path)
