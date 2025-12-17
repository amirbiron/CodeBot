"""
tests/ui_validation/pages/dashboard_page.py

Page Object Model for the Dashboard page.
מכיל סלקטורים ופעולות ספציפיות לדשבורד.
"""

from playwright.sync_api import Page, Locator
from .base_page import BasePage


class DashboardPage(BasePage):
    """
    Page Object for Dashboard (/dashboard).
    """

    PATH = "/dashboard"

    def __init__(self, page: Page, base_url: str):
        super().__init__(page, base_url)

    def navigate(self) -> None:
        """
        ניווט לדשבורד.
        """
        self.navigate_to(self.PATH)

    # ========== Dashboard Specific Selectors ==========

    @property
    def stats_grid(self) -> Locator:
        """Stats cards grid"""
        return self.page.locator(
            ".stats-grid, "
            "[data-testid='stats-grid'], "
            "[role='region'][aria-label*='סטטיסטיקות']"
        ).first

    @property
    def stat_cards(self) -> Locator:
        """Individual stat cards"""
        return self.page.locator(
            ".stat-card, "
            "[data-testid*='stat-card'], "
            ".stats-grid .glass-card"
        )

    @property
    def total_files_stat(self) -> Locator:
        """Total files statistic"""
        return self.stat_cards.filter(has_text="קבצים").first

    @property
    def total_size_stat(self) -> Locator:
        """Total size statistic"""
        return self.stat_cards.filter(has_text="נפח").first

    @property
    def dashboard_grid(self) -> Locator:
        """Main dashboard grid"""
        return self.page.locator(
            ".dashboard-grid, "
            "[data-testid='dashboard-grid']"
        ).first

    @property
    def languages_section(self) -> Locator:
        """Programming languages section"""
        return self.page.locator(
            "[data-testid='languages-section'], "
            ".glass-card:has-text('שפות תכנות')"
        ).first

    @property
    def recent_files_section(self) -> Locator:
        """Recent files section"""
        return self.page.locator(
            "[data-testid='recent-files'], "
            ".glass-card:has-text('קבצים אחרונים')"
        ).first

    @property
    def activity_timeline(self) -> Locator:
        """Activity timeline section"""
        return self.page.locator(
            "#activity-timeline, "
            "[data-testid='activity-timeline'], "
            ".activity-section"
        ).first

    @property
    def timeline_cards(self) -> Locator:
        """Timeline activity cards"""
        return self.page.locator(
            ".activity-card, "
            "[data-testid*='timeline-card']"
        )

    @property
    def timeline_filters(self) -> Locator:
        """Timeline filter buttons"""
        return self.page.locator(
            ".timeline-filter-btn, "
            "[data-testid*='timeline-filter']"
        )

    @property
    def view_all_files_button(self) -> Locator:
        """View all files button"""
        return self.page.locator(
            "a[href='/files'], "
            "[data-testid='view-all-files'], "
            "a:has-text('צפה בכל הקבצים')"
        ).first

    # ========== Dashboard Specific Actions ==========

    def get_stat_value(self, stat_locator: Locator) -> str:
        """
        קבלת ערך מכרטיס סטטיסטיקה.
        """
        value_locator = stat_locator.locator(".stat-value, [data-testid*='value']").first
        return value_locator.text_content() or ""

    def click_timeline_filter(self, filter_id: str) -> None:
        """
        לחיצה על פילטר בציר הזמן.
        """
        self.timeline_filters.filter(has=self.page.locator(f"[data-filter='{filter_id}']")).click()

    def get_visible_timeline_items_count(self) -> int:
        """
        ספירת פריטים גלויים בציר הזמן.
        """
        return self.page.locator(
            ".timeline-item:visible, "
            "[data-timeline-event]:visible"
        ).count()

    def expand_timeline_group(self, group_id: str) -> None:
        """
        הרחבת קבוצה בציר הזמן.
        """
        group = self.page.locator(f".timeline-group[data-group='{group_id}']")
        toggle = group.locator("[data-group-toggle]")
        toggle.click()
