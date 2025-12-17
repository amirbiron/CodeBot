"""
tests/ui_validation/pages/snippets_page.py

Page Object Model for the Snippets Library page.
מכיל סלקטורים ופעולות ספציפיות לספריית הסניפטים.
"""

from playwright.sync_api import Page, Locator
from .base_page import BasePage


class SnippetsPage(BasePage):
    """
    Page Object for Snippets Library (/snippets).
    """

    PATH = "/snippets"

    def __init__(self, page: Page, base_url: str):
        super().__init__(page, base_url)

    def navigate(self) -> None:
        """
        ניווט לספריית הסניפטים.
        """
        self.navigate_to(self.PATH)

    # ========== Snippets Page Specific Selectors ==========

    @property
    def search_input(self) -> Locator:
        """Search input field"""
        return self.page.locator(
            "#q, "
            "[data-testid='search-input'], "
            "input[placeholder*='חפש']"
        ).first

    @property
    def language_filter(self) -> Locator:
        """Language filter input"""
        return self.page.locator(
            "#language, "
            "[data-testid='language-filter'], "
            "input[placeholder*='שפה']"
        ).first

    @property
    def search_button(self) -> Locator:
        """Search button"""
        return self.page.locator(
            "#searchBtn, "
            "[data-testid='search-btn'], "
            "button:has-text('חיפוש')"
        ).first

    @property
    def language_picker_button(self) -> Locator:
        """Language picker button"""
        return self.page.locator(
            "#langPickerBtn, "
            "[data-testid='lang-picker-btn'], "
            "button:has-text('בחר')"
        ).first

    @property
    def language_overlay(self) -> Locator:
        """Language picker overlay/modal"""
        return self.page.locator(
            "#langOverlay, "
            "[data-testid='lang-overlay']"
        ).first

    @property
    def language_list(self) -> Locator:
        """Language list in overlay"""
        return self.page.locator(
            "#langList, "
            "[data-testid='lang-list']"
        ).first

    @property
    def results_grid(self) -> Locator:
        """Results grid container"""
        return self.page.locator(
            "#results, "
            "[data-testid='results-grid'], "
            ".community-grid"
        ).first

    @property
    def snippet_cards(self) -> Locator:
        """Individual snippet cards"""
        return self.page.locator(
            ".snippet-card, "
            "[data-testid*='snippet-card'], "
            ".community-grid > article, "
            ".community-grid > div"
        )

    @property
    def pagination(self) -> Locator:
        """Pagination controls"""
        return self.page.locator(
            "#pager, "
            "[data-testid='pagination'], "
            ".pager-nav"
        ).first

    @property
    def add_snippet_button(self) -> Locator:
        """Add new snippet button"""
        return self.page.locator(
            "a[href='/snippets/submit'], "
            "[data-testid='add-snippet'], "
            "a:has-text('הוסף סניפט')"
        ).first

    @property
    def community_header(self) -> Locator:
        """Page header section"""
        return self.page.locator(
            ".community-header, "
            "[data-testid='community-header']"
        ).first

    @property
    def community_controls(self) -> Locator:
        """Search and filter controls container"""
        return self.page.locator(
            ".community-controls, "
            "[data-testid='community-controls']"
        ).first

    @property
    def no_results_message(self) -> Locator:
        """No results message"""
        return self.page.locator(
            "[data-testid='no-results'], "
            ".no-results, "
            ":text('לא נמצאו תוצאות')"
        ).first

    # ========== Snippets Page Specific Actions ==========

    def search(self, query: str) -> None:
        """
        חיפוש סניפטים.
        """
        self.search_input.fill(query)
        self.search_button.click()
        self.wait_for_page_ready()

    def filter_by_language(self, language: str) -> None:
        """
        סינון לפי שפה.
        """
        self.language_filter.fill(language)
        self.search_button.click()
        self.wait_for_page_ready()

    def open_language_picker(self) -> None:
        """
        פתיחת בורר השפה.
        """
        self.language_picker_button.click()
        self.language_overlay.wait_for(state="visible")

    def close_language_picker(self) -> None:
        """
        סגירת בורר השפה.
        """
        close_btn = self.page.locator(
            "#langOverlayClose, "
            "[data-testid='lang-overlay-close']"
        )
        close_btn.click()
        self.language_overlay.wait_for(state="hidden")

    def select_language_from_picker(self, language: str) -> None:
        """
        בחירת שפה מהבורר.
        """
        self.open_language_picker()
        lang_option = self.language_list.locator(f"button:has-text('{language}')")
        lang_option.click()
        self.language_overlay.wait_for(state="hidden")

    def get_snippet_count(self) -> int:
        """
        ספירת סניפטים בתוצאות.
        """
        return self.snippet_cards.count()

    def click_snippet(self, index: int = 0) -> None:
        """
        לחיצה על סניפט לפי אינדקס.
        """
        self.snippet_cards.nth(index).click()

    def go_to_page(self, page_num: int) -> None:
        """
        מעבר לעמוד ספציפי.
        """
        page_btn = self.pagination.locator(f"button:has-text('{page_num}'), a:has-text('{page_num}')")
        page_btn.click()
        self.wait_for_page_ready()
