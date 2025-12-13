"""
Page Object Model (POM) classes for UI validation tests.

These classes encapsulate page-specific selectors and actions,
reducing duplication and improving test maintainability.
"""

from .base_page import BasePage
from .dashboard_page import DashboardPage
from .editor_page import EditorPage
from .snippets_page import SnippetsPage
from .settings_page import SettingsPage

__all__ = [
    "BasePage",
    "DashboardPage",
    "EditorPage",
    "SnippetsPage",
    "SettingsPage",
]
