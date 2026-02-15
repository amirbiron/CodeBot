"""
טסטים ליחידת הגיבוי האישי.

חשוב: כל הפעולות על תיקיות זמניות (tmp_path) בלבד.
"""
import json
import zipfile
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_db():
    """יוצר DatabaseManager מדומה עם נתוני דוגמה."""
    db = MagicMock()

    # קבצים רגילים
    db.get_user_files.return_value = [
        {
            "file_name": "hello.py",
            "programming_language": "python",
            "description": "Hello world",
            "tags": ["python", "demo"],
            "is_favorite": True,
            "is_pinned": False,
            "pin_order": 0,
            "version": 1,
            "created_at": None,
            "updated_at": None,
        }
    ]
    db.get_file.return_value = {
        "_id": "abc123",
        "code": "print('hello')",
        "file_name": "hello.py",
    }

    # קבצים גדולים
    db.get_user_large_files.return_value = ([], 0)

    # Drive prefs
    db.get_drive_prefs.return_value = {}

    # Large file
    db.get_large_file.return_value = None

    # DB object (for direct collection access)
    mock_raw_db = MagicMock()
    mock_raw_db.sticky_notes.find.return_value = []
    mock_raw_db.user_preferences.find_one.return_value = {}
    db.db = mock_raw_db

    return db


@pytest.fixture
def backup_service(mock_db):
    from services.personal_backup_service import PersonalBackupService

    return PersonalBackupService(mock_db)


class TestExport:
    def test_export_creates_valid_zip(self, backup_service):
        """בדיקה שה-export מייצר ZIP תקין עם backup_info.json."""
        buffer = backup_service.export_user_data(user_id=12345)
        assert buffer is not None

        with zipfile.ZipFile(buffer, "r") as zf:
            names = zf.namelist()
            assert "backup_info.json" in names
            assert "metadata/files.json" in names

            info = json.loads(zf.read("backup_info.json"))
            assert info["user_id"] == 12345
            assert info["version"] == 1
            assert info["files_count"] == 1

    def test_export_includes_file_content(self, backup_service):
        """בדיקה שתוכן הקבצים נכלל ב-ZIP."""
        buffer = backup_service.export_user_data(user_id=12345)

        with zipfile.ZipFile(buffer, "r") as zf:
            content = zf.read("files/hello.py").decode("utf-8")
            assert content == "print('hello')"

    def test_export_includes_metadata(self, backup_service):
        """בדיקה שמטאדאטה נכללת ב-ZIP."""
        buffer = backup_service.export_user_data(user_id=12345)

        with zipfile.ZipFile(buffer, "r") as zf:
            meta = json.loads(zf.read("metadata/files.json"))
            regular = meta["regular_files"]
            assert len(regular) == 1
            assert regular[0]["file_name"] == "hello.py"
            assert regular[0]["is_favorite"] is True


class TestRestore:
    def _make_zip(self, files_dict: dict) -> bytes:
        """יוצר ZIP מדומה עם קבצים נתונים."""
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for path, content in files_dict.items():
                if isinstance(content, dict) or isinstance(content, list):
                    zf.writestr(path, json.dumps(content))
                else:
                    zf.writestr(path, str(content))
        return buf.getvalue()

    def test_restore_basic(self, backup_service, mock_db):
        """בדיקת שחזור בסיסי."""
        mock_db.get_file.return_value = None  # אין קובץ קיים
        mock_db.save_code_snippet.return_value = True

        zip_bytes = self._make_zip(
            {
                "backup_info.json": {"version": 1},
                "metadata/files.json": {
                    "regular_files": [
                        {
                            "file_name": "test.py",
                            "programming_language": "python",
                            "description": "",
                            "tags": [],
                        }
                    ],
                    "large_files": [],
                },
                "files/test.py": "# test file",
            }
        )

        result = backup_service.restore_user_data(12345, zip_bytes)
        assert result["ok"] is True
        assert result["restored"]["files"] == 1
        mock_db.save_code_snippet.assert_called_once()

    def test_restore_rejects_bad_zip(self, backup_service):
        """בדיקה ש-ZIP לא תקין נדחה."""
        result = backup_service.restore_user_data(12345, b"not a zip")
        assert result["ok"] is False
        assert "ZIP" in result["error"]

    def test_restore_rejects_oversized(self, backup_service):
        """בדיקה שקובץ גדול מדי נדחה."""
        from services.personal_backup_service import MAX_RESTORE_ZIP_SIZE

        fake_big = b"x" * (MAX_RESTORE_ZIP_SIZE + 1)
        result = backup_service.restore_user_data(12345, fake_big)
        assert result["ok"] is False
        assert "גדול" in result["error"]

    def test_restore_skip_existing_no_overwrite(self, backup_service, mock_db):
        """בדיקה שקבצים קיימים לא נדרסים כש-overwrite=False."""
        mock_db.get_file.return_value = {"file_name": "test.py", "code": "old"}

        zip_bytes = self._make_zip(
            {
                "backup_info.json": {"version": 1},
                "metadata/files.json": {
                    "regular_files": [{"file_name": "test.py", "programming_language": "python"}],
                    "large_files": [],
                },
                "files/test.py": "new content",
            }
        )

        result = backup_service.restore_user_data(12345, zip_bytes, overwrite=False)
        assert result["ok"] is True
        assert result["restored"]["files"] == 0  # לא נשמר כי כבר קיים

