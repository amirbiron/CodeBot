"""
tests/ui_validation/pages/editor_page.py

Page Object Model for the Editor/File view pages.
מכיל סלקטורים ופעולות ספציפיות לעורך.
"""

from playwright.sync_api import Page, Locator
from .base_page import BasePage


class EditorPage(BasePage):
    """
    Page Object for Editor pages (/edit_file, /view_file).
    """

    EDIT_PATH = "/edit_file"
    VIEW_PATH = "/file"

    def __init__(self, page: Page, base_url: str):
        super().__init__(page, base_url)

    def navigate_to_edit(self, file_id: str) -> None:
        """
        ניווט לעריכת קובץ.
        """
        self.navigate_to(f"{self.EDIT_PATH}/{file_id}")

    def navigate_to_view(self, file_id: str) -> None:
        """
        ניווט לצפייה בקובץ.
        """
        self.navigate_to(f"{self.VIEW_PATH}/{file_id}")

    # ========== Editor Specific Selectors ==========

    @property
    def code_editor(self) -> Locator:
        """CodeMirror editor container"""
        return self.page.locator(
            ".cm-editor, "
            "[data-testid='code-editor'], "
            ".CodeMirror, "
            "[role='textbox'][aria-multiline='true']"
        ).first

    @property
    def code_content(self) -> Locator:
        """Editor content area"""
        return self.page.locator(
            ".cm-content, "
            ".CodeMirror-code, "
            "[data-testid='code-content']"
        ).first

    @property
    def line_numbers(self) -> Locator:
        """Line numbers gutter"""
        return self.page.locator(
            ".cm-gutters, "
            ".CodeMirror-gutters, "
            "[data-testid='line-numbers']"
        ).first

    @property
    def file_name_input(self) -> Locator:
        """File name input field"""
        return self.page.locator(
            "[data-testid='file-name'], "
            "input[name='file_name'], "
            "#file-name"
        ).first

    @property
    def language_selector(self) -> Locator:
        """Programming language selector"""
        return self.page.locator(
            "[data-testid='language-selector'], "
            "select[name='language'], "
            "#language-select"
        ).first

    @property
    def save_button(self) -> Locator:
        """Save file button"""
        return self.page.locator(
            "[data-testid='save-btn'], "
            "button:has-text('שמור'), "
            "[aria-label*='שמור']"
        ).first

    @property
    def delete_button(self) -> Locator:
        """Delete file button"""
        return self.page.locator(
            "[data-testid='delete-btn'], "
            "button:has-text('מחק'), "
            "[aria-label*='מחק']"
        ).first

    @property
    def copy_button(self) -> Locator:
        """Copy code button"""
        return self.page.locator(
            "[data-testid='copy-btn'], "
            "button:has-text('העתק'), "
            "[aria-label*='העתק']"
        ).first

    @property
    def download_button(self) -> Locator:
        """Download file button"""
        return self.page.locator(
            "[data-testid='download-btn'], "
            "button:has-text('הורד'), "
            "[aria-label*='הורד']"
        ).first

    @property
    def editor_toolbar(self) -> Locator:
        """Editor toolbar"""
        return self.page.locator(
            ".editor-toolbar, "
            "[data-testid='editor-toolbar'], "
            "[role='toolbar']"
        ).first

    @property
    def syntax_highlight(self) -> Locator:
        """Syntax highlighted code elements"""
        return self.page.locator(
            ".cm-line span[class*='cm-'], "
            ".hljs span, "
            "[class*='token']"
        )

    @property
    def code_blocks(self) -> Locator:
        """Code block containers"""
        return self.page.locator(
            "pre, "
            "code, "
            ".code-block, "
            "[data-testid='code-block']"
        )

    # ========== Editor Specific Actions ==========

    def get_code_content(self) -> str:
        """
        קבלת תוכן הקוד בעורך.
        """
        return self.code_content.text_content() or ""

    def set_code_content(self, content: str) -> None:
        """
        הגדרת תוכן הקוד בעורך.
        """
        self.code_editor.click()
        self.page.keyboard.press("Control+a")
        self.page.keyboard.type(content)

    def get_selected_language(self) -> str:
        """
        קבלת השפה הנבחרת.
        """
        return self.language_selector.input_value()

    def select_language(self, language: str) -> None:
        """
        בחירת שפת תכנות.
        """
        self.language_selector.select_option(language)

    def save_file(self) -> None:
        """
        שמירת הקובץ.
        """
        self.save_button.click()
        self.wait_for_page_ready()

    def copy_code(self) -> None:
        """
        העתקת הקוד ללוח.
        """
        self.copy_button.click()

    def is_editor_monospace(self) -> bool:
        """
        בדיקה שהעורך משתמש בגופן monospace.
        """
        font_family = self.get_computed_style(self.code_content, "fontFamily")
        monospace_fonts = ["monospace", "Consolas", "Monaco", "Courier", "Source Code Pro"]
        return any(font.lower() in font_family.lower() for font in monospace_fonts)
