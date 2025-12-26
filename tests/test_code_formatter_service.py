"""
Tests for Code Formatter Service
================================
"""

import pytest
from services.code_formatter_service import (
    CodeFormatterService,
    FormattingResult,
    LintResult,
    AutoFixResult,
    get_code_formatter_service,
)


@pytest.fixture
def service():
    return CodeFormatterService()


class TestValidation:
    """בדיקות ולידציה."""

    def test_validate_empty_code(self, service):
        is_valid, error = service.validate_input("")
        assert is_valid is False
        assert "ריק" in error

    def test_validate_large_file(self, service):
        large_code = "x = 1\n" * 100000
        is_valid, error = service.validate_input(large_code)
        assert is_valid is False
        assert "גדול" in error

    def test_validate_syntax_error(self, service):
        bad_code = "def foo(\n    pass"
        is_valid, error = service.validate_input(bad_code, "python")
        assert is_valid is False
        assert "תחביר" in error

    def test_validate_good_code(self, service):
        good_code = "def foo():\n    pass"
        is_valid, error = service.validate_input(good_code, "python")
        assert is_valid is True
        assert error is None


class TestFormatting:
    """בדיקות עיצוב."""

    @pytest.mark.skipif(not CodeFormatterService().is_tool_available("black"), reason="Black not available")
    def test_format_with_black(self, service):
        messy_code = "x=1+2"
        result = service.format_code(messy_code, tool="black")

        assert result.success
        assert "x = 1 + 2" in result.formatted_code

    @pytest.mark.skipif(not CodeFormatterService().is_tool_available("isort"), reason="isort not available")
    def test_format_imports_with_isort(self, service):
        code = "import sys\nimport os"
        result = service.format_code(code, tool="isort")

        assert result.success
        # isort ממיין אלפבתית
        assert result.formatted_code.index("os") < result.formatted_code.index("sys")

    def test_format_unavailable_tool(self, service):
        result = service.format_code("x=1", tool="nonexistent")
        assert result.success is False
        assert "אינו" in (result.error_message or "")


class TestLinting:
    """בדיקות lint."""

    @pytest.mark.skipif(not CodeFormatterService().is_tool_available("flake8"), reason="flake8 not available")
    def test_lint_clean_code(self, service):
        clean_code = """def hello():
    \"\"\"Say hello.\"\"\"
    print("Hello")
"""
        result = service.lint_code(clean_code)

        assert result.success
        assert result.score >= 8.0

    @pytest.mark.skipif(not CodeFormatterService().is_tool_available("flake8"), reason="flake8 not available")
    def test_lint_bad_code(self, service):
        bad_code = "x=1+2;y=3"  # Multiple issues
        result = service.lint_code(bad_code)

        assert result.success
        assert len(result.issues) > 0

    def test_lint_score_calculation(self, service):
        # מוק את _run_flake8 כדי לבדוק חישוב
        from services.code_formatter_service import LintIssue

        issues = [
            LintIssue(1, 1, "E501", "line too long", "warning", True),
            LintIssue(2, 1, "W291", "trailing whitespace", "warning", True),
        ]

        score = service._calculate_score("x = 1\ny = 2\nz = 3", issues)
        assert 0 <= score <= 10


class TestAutoFix:
    """בדיקות תיקון אוטומטי."""

    @pytest.mark.skipif(not CodeFormatterService().is_tool_available("autopep8"), reason="autopep8 not available")
    def test_auto_fix_safe(self, service):
        code_with_whitespace = "x = 1   \ny = 2"  # Trailing whitespace
        result = service.auto_fix(code_with_whitespace, level="safe")

        assert result.success
        assert "   " not in result.fixed_code

    def test_auto_fix_preserves_syntax(self, service):
        code = "def foo():\n    return 1"
        result = service.auto_fix(code, level="aggressive")

        if result.success:
            # וודא שהקוד עדיין תקין
            import ast

            ast.parse(result.fixed_code)


class TestDiff:
    """בדיקות diff."""

    def test_get_diff(self, service):
        original = "x = 1"
        modified = "x = 2"

        diff = service.get_diff(original, modified)

        assert "-x = 1" in diff
        assert "+x = 2" in diff

    def test_count_changes(self, service):
        original = "a\nb\nc"
        modified = "a\nB\nc"

        count = service._count_changes(original, modified)
        assert count == 2  # One removal, one addition


class TestServiceSingleton:
    """בדיקות singleton."""

    def test_singleton(self):
        service1 = get_code_formatter_service()
        service2 = get_code_formatter_service()

        assert service1 is service2

