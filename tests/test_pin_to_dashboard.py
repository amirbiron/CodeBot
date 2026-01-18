import pytest
from unittest.mock import MagicMock

from database.manager import toggle_pin, get_pinned_files, reorder_pinned


class TestPinToDashboard:
    """טסטים לפיצ'ר נעיצה לדשבורד"""

    @pytest.fixture
    def mock_db(self):
        """Mock ל-DB manager"""
        return MagicMock()

    def test_toggle_pin_success(self, mock_db):
        """נעיצת קובץ מצליחה"""
        mock_db.collection.find_one.return_value = {
            "user_id": 123,
            "file_name": "test.py",
            "is_pinned": False
        }
        mock_db.collection.count_documents.return_value = 2

        result = toggle_pin(mock_db, 123, "test.py")

        assert result["success"] is True
        assert result["is_pinned"] is True

    def test_toggle_pin_limit_reached(self, mock_db):
        """מגבלת נעיצות - 8 קבצים"""
        mock_db.collection.find_one.return_value = {
            "user_id": 123,
            "file_name": "test.py",
            "is_pinned": False
        }
        mock_db.collection.count_documents.return_value = 8  # מקסימום

        result = toggle_pin(mock_db, 123, "test.py")

        assert result["success"] is False
        assert "עד 8 קבצים" in result["error"]

    def test_toggle_unpin_success(self, mock_db):
        """ביטול נעיצה מצליח"""
        mock_db.collection.find_one.return_value = {
            "user_id": 123,
            "file_name": "test.py",
            "is_pinned": True,
            "pin_order": 2
        }

        result = toggle_pin(mock_db, 123, "test.py")

        assert result["success"] is True
        assert result["is_pinned"] is False

    def test_get_pinned_files_ordered(self, mock_db):
        """קבלת קבצים נעוצים בסדר נכון"""
        mock_db.collection.find.return_value.sort.return_value.limit.return_value = [
            {"file_name": "first.py", "pin_order": 0},
            {"file_name": "second.py", "pin_order": 1},
            {"file_name": "third.py", "pin_order": 2}
        ]

        result = get_pinned_files(mock_db, 123)

        assert len(result) == 3
        assert result[0]["file_name"] == "first.py"
        assert result[2]["file_name"] == "third.py"

    def test_reorder_pinned_down(self, mock_db):
        """הזזת קובץ למטה ברשימה"""
        mock_db.collection.find_one.return_value = {
            "user_id": 123,
            "file_name": "test.py",
            "is_pinned": True,
            "pin_order": 0
        }
        mock_db.collection.count_documents.return_value = 4

        result = reorder_pinned(mock_db, 123, "test.py", 2)

        assert result is True

    def test_file_not_found(self, mock_db):
        """קובץ לא קיים"""
        mock_db.collection.find_one.return_value = None

        result = toggle_pin(mock_db, 123, "nonexistent.py")

        assert result["success"] is False
        assert "לא נמצא" in result["error"]
