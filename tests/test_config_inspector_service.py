"""Unit tests for ConfigService."""

import os
from unittest.mock import patch

import pytest

from services.config_inspector_service import (
    ConfigService,
    ConfigDefinition,
    ConfigStatus,
    ConfigSource,
)


class TestConfigService:
    """Test suite for ConfigService."""

    def setup_method(self):
        """Setup test instance."""
        self.service = ConfigService()

    def test_is_sensitive_key_by_pattern(self):
        """Test sensitive key detection by pattern."""
        assert self.service.is_sensitive_key("API_TOKEN") is True
        assert self.service.is_sensitive_key("DB_PASSWORD") is True
        assert self.service.is_sensitive_key("SECRET_KEY") is True
        assert self.service.is_sensitive_key("MONGODB_URI") is True
        assert self.service.is_sensitive_key("LOG_LEVEL") is False
        assert self.service.is_sensitive_key("MAX_RETRIES") is False

    def test_is_sensitive_key_by_definition(self):
        """Test sensitive key detection by definition."""
        # BOT_TOKEN is defined as sensitive
        assert self.service.is_sensitive_key("BOT_TOKEN") is True

    def test_mask_value(self):
        """Test value masking."""
        assert self.service.mask_value("my-secret", "API_KEY") == "********"
        assert self.service.mask_value("debug", "LOG_LEVEL") == "debug"
        assert self.service.mask_value("", "API_KEY") == ""

    def test_determine_status_default(self):
        """Test status determination - default case."""
        status = self.service.determine_status(None, "default_val")
        assert status == ConfigStatus.DEFAULT

    def test_determine_status_modified(self):
        """Test status determination - modified case."""
        status = self.service.determine_status("custom_val", "default_val")
        assert status == ConfigStatus.MODIFIED

    def test_determine_status_same_as_default(self):
        """Test status when env value equals default."""
        status = self.service.determine_status("default_val", "default_val")
        assert status == ConfigStatus.DEFAULT

    def test_determine_status_missing(self):
        """Test status determination - missing required."""
        status = self.service.determine_status(None, None, is_required=True)
        assert status == ConfigStatus.MISSING

    def test_determine_status_empty_string_is_missing(self):
        """Test that empty string env value is treated as missing for required vars."""
        # מחרוזת ריקה בסביבה + אין דיפולט + הכרחי = Missing
        status = self.service.determine_status("", None, is_required=True)
        assert status == ConfigStatus.MISSING

        # מחרוזת ריקה בסביבה + יש דיפולט = Default (משתמש בדיפולט)
        status = self.service.determine_status("", "fallback", is_required=True)
        assert status == ConfigStatus.DEFAULT

    def test_is_empty_value(self):
        """Test empty value detection consistency."""
        assert self.service._is_empty_value(None) is True
        assert self.service._is_empty_value("") is True
        assert self.service._is_empty_value("   ") is True
        assert self.service._is_empty_value("value") is False
        assert self.service._is_empty_value("  value  ") is False

    def test_determine_source(self):
        """Test source determination."""
        assert self.service.determine_source("value") == ConfigSource.ENVIRONMENT
        assert self.service.determine_source(None) == ConfigSource.DEFAULT

    @patch.dict(os.environ, {"LOG_LEVEL": "DEBUG"})
    def test_get_config_entry_from_env(self):
        """Test config entry retrieval from environment."""
        definition = ConfigDefinition(
            key="LOG_LEVEL",
            default="INFO",
            description="Log level",
            category="logging",
        )
        entry = self.service.get_config_entry(definition)

        assert entry.key == "LOG_LEVEL"
        assert entry.active_value == "DEBUG"
        assert entry.default_value == "INFO"
        assert entry.source == ConfigSource.ENVIRONMENT
        assert entry.status == ConfigStatus.MODIFIED

    def test_get_config_entry_with_default(self):
        """Test config entry using default value."""
        definition = ConfigDefinition(
            key="NONEXISTENT_VAR",
            default="fallback",
            description="Test var",
            category="test",
        )
        entry = self.service.get_config_entry(definition)

        assert entry.active_value == "fallback"
        assert entry.source == ConfigSource.DEFAULT
        assert entry.status == ConfigStatus.DEFAULT

    def test_get_config_entry_with_falsy_default_values(self):
        """Test that falsy defaults like 0/False are displayed correctly."""
        definition_zero = ConfigDefinition(
            key="TEST_DEFAULT_ZERO",
            default=0,
            description="Numeric default",
            category="test",
        )
        entry_zero = self.service.get_config_entry(definition_zero)
        assert entry_zero.active_value == "0"
        assert entry_zero.default_value == "0"
        assert entry_zero.source == ConfigSource.DEFAULT

        definition_false = ConfigDefinition(
            key="TEST_DEFAULT_FALSE",
            default=False,
            description="Boolean default",
            category="test",
        )
        entry_false = self.service.get_config_entry(definition_false)
        assert entry_false.active_value == "False"
        assert entry_false.default_value == "False"
        assert entry_false.source == ConfigSource.DEFAULT

    def test_get_config_entry_sensitive_masked(self):
        """Test that sensitive values are masked."""
        with patch.dict(os.environ, {"MY_SECRET_KEY": "super-secret-123"}):
            definition = ConfigDefinition(
                key="MY_SECRET_KEY",
                default="",
                description="Secret",
                category="security",
                sensitive=True,
            )
            entry = self.service.get_config_entry(definition)

            assert entry.active_value == "********"
            assert entry.is_sensitive is True

    def test_get_config_entry_sensitive_default_also_masked(self):
        """Test that sensitive DEFAULT values are also masked (security fix)."""
        # סימולציה: אין ערך בסביבה, יש דיפולט עם credentials
        with patch.dict(os.environ, {}, clear=False):
            # וודא שהמשתנה לא קיים בסביבה
            os.environ.pop("DB_CONNECTION_URI", None)

            definition = ConfigDefinition(
                key="DB_CONNECTION_URI",
                default="mongodb://user:password@localhost:27017/db",
                description="Database connection",
                category="database",
                sensitive=True,
            )
            entry = self.service.get_config_entry(definition)

            # שני הערכים צריכים להיות מוסתרים!
            assert entry.active_value == "********"
            assert entry.default_value == "********"
            assert entry.is_sensitive is True

    def test_get_config_overview(self):
        """Test full config overview generation."""
        overview = self.service.get_config_overview()

        assert overview.total_count > 0
        assert overview.generated_at != ""
        assert isinstance(overview.entries, list)
        assert len(overview.categories) > 0

    def test_get_config_overview_with_category_filter(self):
        """Test overview with category filter."""
        overview = self.service.get_config_overview(category_filter="database")

        for entry in overview.entries:
            assert entry.category == "database"

    def test_get_config_overview_with_status_filter(self):
        """Test overview with status filter."""
        overview = self.service.get_config_overview(status_filter=ConfigStatus.DEFAULT)

        for entry in overview.entries:
            assert entry.status == ConfigStatus.DEFAULT

    def test_validate_required_empty_env(self):
        """Test validation of required variables."""
        # Clear relevant env vars for test
        with patch.dict(os.environ, {}, clear=True):
            missing = self.service.validate_required()
            # Should contain required vars without defaults
            assert isinstance(missing, list)

    def test_validate_required_consistency_with_status(self):
        """Test that validate_required and determine_status are consistent."""
        # באג קודם: מחרוזת ריקה גרמה לסתירה בין השניים
        with patch.dict(os.environ, {"BOT_TOKEN": ""}, clear=False):
            # קבלת הסטטוס
            definition = ConfigDefinition(
                key="BOT_TOKEN",
                default="",
                description="Bot token",
                category="telegram",
                sensitive=True,
                required=True,
            )
            entry = self.service.get_config_entry(definition)

            # בדיקת עקביות: אם הסטטוס הוא Missing, הוא חייב להופיע ב-validate_required
            if entry.status == ConfigStatus.MISSING:
                # נשתמש במוק מצומצם רק עם המשתנה הזה
                test_service = ConfigService()
                test_service.CONFIG_DEFINITIONS = {"BOT_TOKEN": definition}
                missing = test_service.validate_required()
                assert "BOT_TOKEN" in missing, "Status is MISSING but validate_required didn't catch it!"

    def test_category_summary(self):
        """Test category summary generation."""
        summary = self.service.get_category_summary()

        assert isinstance(summary, dict)
        for _cat, stats in summary.items():
            assert "total" in stats
            assert "modified" in stats
            assert "missing" in stats
            assert "default" in stats

