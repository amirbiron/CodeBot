import pytest
from services.diff_service import DiffService, DiffResult


class TestDiffService:
    """בדיקות לשירות ההשוואה."""

    @pytest.fixture
    def service(self):
        return DiffService()

    def test_compute_diff_identical(self, service):
        """קבצים זהים - אין שינויים."""
        content = "line1\nline2\nline3"
        result = service.compute_diff(content, content)

        assert result.stats['added'] == 0
        assert result.stats['removed'] == 0
        assert result.stats['modified'] == 0
        assert result.stats['unchanged'] == 3

    def test_compute_diff_added_lines(self, service):
        """זיהוי שורות שנוספו."""
        left = "line1\nline2"
        right = "line1\nline2\nline3"

        result = service.compute_diff(left, right)

        assert result.stats['added'] == 1
        assert result.stats['unchanged'] == 2

    def test_compute_diff_removed_lines(self, service):
        """זיהוי שורות שנמחקו."""
        left = "line1\nline2\nline3"
        right = "line1\nline3"

        result = service.compute_diff(left, right)

        assert result.stats['removed'] == 1

    def test_compute_diff_modified_lines(self, service):
        """זיהוי שורות ששונו."""
        left = "line1\nold content\nline3"
        right = "line1\nnew content\nline3"

        result = service.compute_diff(left, right)

        assert result.stats['modified'] == 1

    def test_format_unified_diff(self, service):
        """בדיקת פורמט unified."""
        left = "line1\nline2"
        right = "line1\nline2\nline3"

        result = service.compute_diff(left, right)
        unified = service.format_unified_diff(result)

        assert "+++" in unified
        assert "---" in unified
        assert "+line3" in unified

    def test_format_for_telegram(self, service):
        """בדיקת פורמט טלגרם."""
        left = "line1"
        right = "line1\nline2"

        result = service.compute_diff(left, right)
        telegram_text = service.format_for_telegram(result)

        assert "סיכום השוואה" in telegram_text
        assert "נוספו:" in telegram_text


class TestDiffServiceWithDB:
    """בדיקות עם מסד נתונים (mock)."""

    @pytest.fixture
    def mock_db(self, mocker):
        db = mocker.Mock()
        db.get_version.return_value = {
            "code": "test content",
            "version": 1,
            "file_name": "test.py",
            "updated_at": "2025-01-01",
        }
        db.get_file_by_id.return_value = {
            "user_id": 123,
            "code": "test content",
            "file_name": "test.py",
        }
        return db

    def test_compare_versions(self, mock_db):
        """השוואת גרסאות."""
        service = DiffService(mock_db)

        mock_db.get_version.side_effect = [
            {"code": "v1 content", "version": 1},
            {"code": "v2 content", "version": 2},
        ]

        result = service.compare_versions(123, "test.py", 1, 2)

        assert result is not None
        assert result.left_info['version'] == 1
        assert result.right_info['version'] == 2

