"""
tests/ui_validation/pages/settings_page.py

Page Object Model for the Settings page.
מכיל סלקטורים ופעולות ספציפיות להגדרות.
"""

from playwright.sync_api import Page, Locator
from .base_page import BasePage


class SettingsPage(BasePage):
    """
    Page Object for Settings (/settings).
    """

    PATH = "/settings"

    def __init__(self, page: Page, base_url: str):
        super().__init__(page, base_url)

    def navigate(self) -> None:
        """
        ניווט להגדרות.
        """
        self.navigate_to(self.PATH)

    # ========== Settings Page Specific Selectors ==========

    @property
    def theme_selector(self) -> Locator:
        """Theme selection dropdown/buttons"""
        return self.page.locator(
            "[data-testid='theme-selector'], "
            "#theme-select, "
            "[name='theme']"
        ).first

    @property
    def theme_options(self) -> Locator:
        """Theme option buttons"""
        return self.page.locator(
            "[data-testid*='theme-option'], "
            ".theme-option, "
            "[data-theme-option]"
        )

    @property
    def dark_mode_toggle(self) -> Locator:
        """Dark mode toggle"""
        return self.page.locator(
            "[data-testid='dark-mode-toggle'], "
            "[aria-label*='מצב כהה'], "
            "[aria-label*='dark mode']"
        ).first

    @property
    def font_size_control(self) -> Locator:
        """Font size control"""
        return self.page.locator(
            "[data-testid='font-size'], "
            "#font-size, "
            "[name='font_size']"
        ).first

    @property
    def notification_toggles(self) -> Locator:
        """Notification settings toggles"""
        return self.page.locator(
            "[data-testid*='notification'], "
            "[name*='notification']"
        )

    @property
    def language_selector(self) -> Locator:
        """UI language selector"""
        return self.page.locator(
            "[data-testid='language-selector'], "
            "#ui-language, "
            "[name='language']"
        ).first

    @property
    def save_button(self) -> Locator:
        """Save settings button"""
        return self.page.locator(
            "[data-testid='save-settings'], "
            "button:has-text('שמור'), "
            "button[type='submit']"
        ).first

    @property
    def reset_button(self) -> Locator:
        """Reset settings button"""
        return self.page.locator(
            "[data-testid='reset-settings'], "
            "button:has-text('אפס'), "
            "button:has-text('ברירת מחדל')"
        ).first

    @property
    def settings_sections(self) -> Locator:
        """Settings section containers"""
        return self.page.locator(
            ".settings-section, "
            "[data-testid*='settings-section'], "
            ".glass-card"
        )

    @property
    def success_message(self) -> Locator:
        """Success toast/message"""
        return self.page.locator(
            "[data-testid='success-message'], "
            ".toast-success, "
            ".alert-success, "
            "[role='alert']:has-text('נשמר')"
        ).first

    @property
    def error_message(self) -> Locator:
        """Error toast/message"""
        return self.page.locator(
            "[data-testid='error-message'], "
            ".toast-error, "
            ".alert-error, "
            "[role='alert']:has-text('שגיאה')"
        ).first

    @property
    def form_fields(self) -> Locator:
        """All form input fields"""
        return self.page.locator(
            "input, select, textarea, "
            "[role='switch'], [role='checkbox']"
        )

    @property
    def form_labels(self) -> Locator:
        """Form field labels"""
        return self.page.locator(
            "label, "
            "[data-testid*='label']"
        )

    # ========== Settings Page Specific Actions ==========

    def select_theme(self, theme_name: str) -> None:
        """
        בחירת תמה.
        """
        theme_option = self.theme_options.filter(has_text=theme_name).first
        if theme_option.count() > 0:
            theme_option.click()
        else:
            # Try dropdown
            self.theme_selector.select_option(theme_name)

    def toggle_dark_mode(self) -> None:
        """
        החלפת מצב כהה.
        """
        self.dark_mode_toggle.click()

    def set_font_size(self, size: str) -> None:
        """
        הגדרת גודל גופן.
        """
        self.font_size_control.fill(size)

    def save_settings(self) -> None:
        """
        שמירת ההגדרות.
        """
        self.save_button.click()
        self.wait_for_page_ready()

    def reset_settings(self) -> None:
        """
        איפוס ההגדרות לברירת מחדל.
        """
        self.reset_button.click()
        self.wait_for_page_ready()

    def get_current_theme(self) -> str:
        """
        קבלת התמה הנוכחית מההגדרות.
        """
        return self.get_theme()

    def is_setting_enabled(self, setting_locator: Locator) -> bool:
        """
        בדיקה האם הגדרה מופעלת.
        """
        return setting_locator.is_checked()

    def verify_settings_saved(self) -> bool:
        """
        אימות שההגדרות נשמרו.
        """
        return self.success_message.is_visible()

    def verify_form_labels_associated(self) -> bool:
        """
        אימות שכל שדות הטופס מקושרים ל-labels.
        """
        # Get all inputs with IDs
        inputs_with_id = self.page.locator("input[id], select[id], textarea[id]")
        count = inputs_with_id.count()

        for i in range(count):
            input_el = inputs_with_id.nth(i)
            input_id = input_el.get_attribute("id")
            if input_id:
                # Check if there's a label with for attribute pointing to this input
                associated_label = self.page.locator(f"label[for='{input_id}']")
                if associated_label.count() == 0:
                    # Check if input is wrapped in label
                    parent_label = input_el.locator("xpath=ancestor::label")
                    if parent_label.count() == 0:
                        return False

        return True
