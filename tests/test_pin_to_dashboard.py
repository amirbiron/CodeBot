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
        mock_db.collection.find_one.side_effect = [
            {
                "user_id": 123,
                "file_name": "test.py",
                "is_pinned": False,
                "is_active": True
            },
            None,
        ]
        mock_db.collection.distinct.return_value = ["a.py", "b.py"]
        mock_db.collection.find.return_value.sort.return_value = []

        result = toggle_pin(mock_db, 123, "test.py")

        assert result["success"] is True
        assert result["is_pinned"] is True

    def test_toggle_pin_limit_reached(self, mock_db):
        """מגבלת נעיצות - 8 קבצים"""
        mock_db.collection.find_one.side_effect = [
            {
                "user_id": 123,
                "file_name": "test.py",
                "is_pinned": False,
                "is_active": True
            },
            None,
        ]
        mock_db.collection.distinct.return_value = [f"f{i}.py" for i in range(8)]  # מקסימום
        mock_db.collection.find.return_value.sort.return_value = []

        result = toggle_pin(mock_db, 123, "test.py")

        assert result["success"] is False
        assert "עד 8 קבצים" in result["error"]

    def test_toggle_unpin_success(self, mock_db):
        """ביטול נעיצה מצליח"""
        mock_db.collection.find_one.side_effect = [
            {
                "user_id": 123,
                "file_name": "test.py",
                "is_pinned": True,
                "pin_order": 2,
                "is_active": True
            },
            {
                "user_id": 123,
                "file_name": "test.py",
                "is_pinned": True,
                "pin_order": 2,
                "is_active": True
            },
        ]
        mock_db.collection.find.return_value.sort.return_value = []

        result = toggle_pin(mock_db, 123, "test.py")

        assert result["success"] is True
        assert result["is_pinned"] is False

    def test_get_pinned_files_ordered(self, mock_db):
        """קבלת קבצים נעוצים בסדר נכון"""
        pinned = [
            {"file_name": "first.py", "pin_order": 0},
            {"file_name": "second.py", "pin_order": 1},
            {"file_name": "third.py", "pin_order": 2}
        ]
        # get_pinned_files משתמש ב-find().sort().limit()
        find_result = MagicMock()
        sort_result = MagicMock()
        sort_result.limit.return_value = pinned
        find_result.sort.return_value = sort_result
        mock_db.collection.find.return_value = find_result

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
        mock_db.collection.distinct.return_value = ["a.py", "b.py", "c.py", "d.py"]

        result = reorder_pinned(mock_db, 123, "test.py", 2)

        assert result is True

    def test_file_not_found(self, mock_db):
        """קובץ לא קיים"""
        mock_db.collection.find_one.return_value = None

        result = toggle_pin(mock_db, 123, "nonexistent.py")

        assert result["success"] is False
        assert "לא נמצא" in result["error"]


class TestPinDoesNotClaimAnEdit:
    """נעיצה היא מטא-דאטה, ולא עריכה של הקובץ.

    ``updated_at`` מציין מתי התוכן השתנה: ``file_was_edited`` נגזרת ממנו
    כדי להחליט אם להציג "עודכן", והדשבורד ממיין לפיו. חתימה עליו בנעיצה
    גרמה לקובץ שמעולם לא נערך להציג "עודכן", ולכל גרסאותיו לקפוץ לראש
    היסטוריית הפעולות בבת אחת. ``pinned_at`` הוא השדה שמתעד את הפעולה.
    """

    @pytest.fixture
    def mock_db(self):
        return MagicMock()

    @staticmethod
    def _set_fields(call):
        return (call.args[1] if len(call.args) > 1 else call.kwargs.get('update', {})).get('$set', {})

    def test_pinning_does_not_touch_updated_at(self, mock_db):
        mock_db.collection.find_one.side_effect = [
            {"user_id": 123, "file_name": "test.py", "is_pinned": False, "is_active": True},
            None,
        ]
        mock_db.collection.distinct.return_value = ["a.py"]
        mock_db.collection.find.return_value.sort.return_value = []

        assert toggle_pin(mock_db, 123, "test.py")["success"] is True

        writes = list(mock_db.collection.update_many.call_args_list) + list(
            mock_db.collection.update_one.call_args_list
        )
        assert writes, "לא בוצעה שום כתיבה"
        for call in writes:
            assert 'updated_at' not in self._set_fields(call), self._set_fields(call)
        # ובכל זאת הפעולה תועדה
        assert any('pinned_at' in self._set_fields(c) for c in writes)

    def test_unpinning_does_not_touch_updated_at(self, mock_db):
        mock_db.collection.find_one.side_effect = [
            {"user_id": 123, "file_name": "test.py", "is_pinned": True, "pin_order": 2, "is_active": True},
            {"_id": "x", "pin_order": 2},
        ]
        mock_db.collection.distinct.return_value = ["test.py"]
        mock_db.collection.find.return_value.sort.return_value = []

        assert toggle_pin(mock_db, 123, "test.py")["success"] is True

        writes = list(mock_db.collection.update_many.call_args_list) + list(
            mock_db.collection.update_one.call_args_list
        )
        assert writes, "לא בוצעה שום כתיבה"
        for call in writes:
            assert 'updated_at' not in self._set_fields(call), self._set_fields(call)
