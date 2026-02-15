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
    mock_raw_db.file_bookmarks = MagicMock()
    mock_raw_db.file_bookmarks.find.return_value = []
    mock_raw_db.file_bookmarks.find_one.return_value = None
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

    def test_export_includes_anchor_bookmark_fields(self, backup_service, mock_db):
        """ייצוא סימניות צריך לכלול שדות anchor_* ו-line_text_preview."""
        # provide raw bookmark doc with anchor fields
        mock_db.db.file_bookmarks.find.return_value = [
            {
                "user_id": 12345,
                "file_id": "file1",
                "file_name": "hello.py",
                "file_path": "hello.py",
                "line_number": 1000000123,
                "line_text_preview": "Heading",
                "note": "n",
                "color": "green",
                "anchor_id": "section-intro",
                "anchor_text": "Introduction",
                "anchor_type": "md_heading",
                "created_at": None,
                "valid": True,
            }
        ]

        buffer = backup_service.export_user_data(user_id=12345)
        with zipfile.ZipFile(buffer, "r") as zf:
            bms = json.loads(zf.read("metadata/bookmarks.json"))
            assert isinstance(bms, list)
            assert len(bms) == 1
            assert bms[0]["anchor_id"] == "section-intro"
            assert bms[0]["anchor_text"] == "Introduction"
            assert bms[0]["anchor_type"] == "md_heading"
            assert bms[0]["line_text_preview"] == "Heading"


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

    def test_restore_overwrite_can_unfavorite_and_unpin(self, backup_service, mock_db):
        """כש-overwrite=True ניתן להסיר מועדף/נעוץ לפי מטאדאטה של הגיבוי."""
        mock_db.get_file.return_value = {"file_name": "test.py", "code": "old"}
        mock_db.save_code_snippet.return_value = True

        # current state in DB
        mock_db.is_favorite.return_value = True
        mock_db.is_pinned.return_value = True
        mock_db.toggle_favorite.return_value = False
        mock_db.toggle_pin.return_value = {"success": True, "is_pinned": False}

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
                            "is_favorite": False,
                            "is_pinned": False,
                            "pin_order": 0,
                        }
                    ],
                    "large_files": [],
                },
                "files/test.py": "new content",
            }
        )

        result = backup_service.restore_user_data(12345, zip_bytes, overwrite=True)
        assert result["ok"] is True
        assert mock_db.toggle_favorite.call_count == 1
        assert mock_db.toggle_pin.call_count == 1

    def test_restore_overwrite_updates_metadata_even_if_content_matches(self, backup_service, mock_db):
        """כש-overwrite=True והתוכן זהה, עדיין צריך לשחזר מטאדאטה (שפה/תיאור/תגיות)."""
        mock_db.get_file.return_value = {
            "_id": "file1",
            "file_name": "test.py",
            "code": "same",
            "programming_language": "python",
            "description": "old",
            "tags": ["a"],
        }
        mock_db.save_code_snippet.return_value = True
        mock_db.is_favorite.return_value = False
        mock_db.is_pinned.return_value = False

        zip_bytes = self._make_zip(
            {
                "backup_info.json": {"version": 1},
                "metadata/files.json": {
                    "regular_files": [
                        {
                            "file_name": "test.py",
                            "programming_language": "text",
                            "description": "new",
                            "tags": ["b"],
                            "is_favorite": False,
                            "is_pinned": False,
                            "pin_order": 0,
                        }
                    ],
                    "large_files": [],
                },
                "files/test.py": "same",
            }
        )

        result = backup_service.restore_user_data(12345, zip_bytes, overwrite=True)
        assert result["ok"] is True
        assert result["restored"]["files"] == 1
        assert mock_db.save_code_snippet.call_count == 1

    def test_restore_preserves_empty_programming_language(self, backup_service, mock_db):
        """אם programming_language הוא מחרוזת ריקה בגיבוי, לא ממירים ל-'text'."""
        mock_db.get_file.return_value = None
        mock_db.save_code_snippet.return_value = True

        zip_bytes = self._make_zip(
            {
                "backup_info.json": {"version": 1},
                "metadata/files.json": {
                    "regular_files": [{"file_name": "x.txt", "programming_language": "", "description": "", "tags": []}],
                    "large_files": [],
                },
                "files/x.txt": "hi",
            }
        )

        result = backup_service.restore_user_data(12345, zip_bytes, overwrite=False)
        assert result["ok"] is True
        assert result["restored"]["files"] == 1
        args, _kwargs = mock_db.save_code_snippet.call_args
        snippet = args[0]
        assert getattr(snippet, "programming_language", None) == ""

    def test_restore_large_files_does_not_rewrite_when_language_empty_matches(self, backup_service, mock_db):
        """large_files: אם התוכן זהה והמטאדאטה זהה כולל שפה ריקה, לא עושים save_large_file."""
        mock_db.get_large_file.return_value = {
            "_id": "lf1",
            "file_name": "big.txt",
            "content": "same",
            "programming_language": "",
            "description": "",
            "tags": [],
        }
        mock_db.save_large_file.return_value = True

        zip_bytes = self._make_zip(
            {
                "backup_info.json": {"version": 1},
                "metadata/files.json": {
                    "regular_files": [],
                    "large_files": [
                        {"file_name": "big.txt", "programming_language": "", "description": "", "tags": []}
                    ],
                },
                "large_files/big.txt": "same",
            }
        )

        result = backup_service.restore_user_data(12345, zip_bytes, overwrite=True)
        assert result["ok"] is True
        assert result["restored"]["large_files"] == 0
        assert mock_db.save_large_file.call_count == 0

    def test_restore_bookmarks_use_line_text_preview(self, backup_service, mock_db):
        """שחזור סימניות צריך לכתוב line_text_preview (ולא line_text)."""
        # file exists so we can resolve file_id
        mock_db.get_file.return_value = {"_id": "file1", "file_name": "test.py", "code": "x"}
        mock_db.save_code_snippet.return_value = True

        zip_bytes = self._make_zip(
            {
                "backup_info.json": {"version": 1},
                "metadata/files.json": {"regular_files": [], "large_files": []},
                "metadata/bookmarks.json": [
                    {
                        "file_name": "test.py",
                        "file_path": "test.py",
                        "line_number": 12,
                        "line_text_preview": "print('hi')",
                        "note": "n",
                        "color": "yellow",
                    }
                ],
            }
        )

        result = backup_service.restore_user_data(12345, zip_bytes, overwrite=False)
        assert result["ok"] is True
        assert result["restored"]["bookmarks"] == 1
        args, _kwargs = mock_db.db.file_bookmarks.insert_one.call_args
        doc = args[0]
        assert "line_text_preview" in doc
        assert doc["line_text_preview"] == "print('hi')"
        assert "line_text" not in doc
        assert "anchor_id" not in doc
        assert "anchor_text" not in doc
        assert "anchor_type" not in doc
        assert doc.get("valid") is True

    def test_restore_preferences_allowlist_only(self, backup_service, mock_db):
        """שחזור העדפות לא צריך להזריק שדות שרירותיים."""
        zip_bytes = self._make_zip(
            {
                "backup_info.json": {"version": 1},
                "metadata/files.json": {"regular_files": [], "large_files": []},
                "metadata/preferences.json": {
                    "attention_settings": {
                        "enabled": True,
                        "stale_days": 30,
                        "max_items_per_group": 10,
                        "show_missing_description": True,
                        "show_missing_tags": False,
                        "show_stale_files": True,
                        "evil_extra": "nope",
                    },
                    "is_admin": True,
                    "role": "admin",
                },
            }
        )

        result = backup_service.restore_user_data(12345, zip_bytes, overwrite=False)
        assert result["ok"] is True
        assert result["restored"]["preferences"] is True

        _args, _kwargs = mock_db.db.user_preferences.update_one.call_args
        update_doc = _args[1]
        set_doc = update_doc.get("$set") or {}
        assert "is_admin" not in set_doc
        assert "role" not in set_doc
        assert "attention_settings.evil_extra" not in set_doc
        assert set_doc.get("attention_settings.enabled") is True

    def test_restore_overwrite_does_not_toggle_metadata_when_zip_file_missing(self, backup_service, mock_db):
        """אם קובץ חסר ב-ZIP, לא משנים מועדפים/נעיצה לפני continue."""
        mock_db.get_file.return_value = {"file_name": "test.py", "code": "old"}
        mock_db.is_favorite.return_value = True
        mock_db.is_pinned.return_value = True

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
                            "is_favorite": False,
                            "is_pinned": False,
                            "pin_order": 0,
                        }
                    ],
                    "large_files": [],
                },
                # בכוונה אין "files/test.py"
            }
        )

        result = backup_service.restore_user_data(12345, zip_bytes, overwrite=True)
        assert result["ok"] is True
        assert result["restored"]["files"] == 0
        assert mock_db.toggle_favorite.call_count == 0
        assert mock_db.toggle_pin.call_count == 0
        assert mock_db.reorder_pinned.call_count == 0

    def test_restore_large_files_overwrite_updates_metadata_when_content_matches(self, backup_service, mock_db):
        """ב-large_files, אם התוכן זהה אבל מטאדאטה שונה, עדיין צריך לשמור כדי לעדכן."""
        mock_db.get_large_file.return_value = {
            "_id": "lf1",
            "file_name": "big.txt",
            "content": "same",
            "programming_language": "text",
            "description": "old",
            "tags": ["a"],
        }
        mock_db.save_large_file.return_value = True

        zip_bytes = self._make_zip(
            {
                "backup_info.json": {"version": 1},
                "metadata/files.json": {
                    "regular_files": [],
                    "large_files": [
                        {
                            "file_name": "big.txt",
                            "programming_language": "markdown",
                            "description": "new",
                            "tags": ["b"],
                        }
                    ],
                },
                "large_files/big.txt": "same",
            }
        )

        result = backup_service.restore_user_data(12345, zip_bytes, overwrite=True)
        assert result["ok"] is True
        assert result["restored"]["large_files"] == 1
        assert mock_db.save_large_file.call_count == 1

    def test_restore_skips_sticky_note_when_file_cannot_be_resolved(self, backup_service, mock_db):
        """פתקית עם file_name שלא נפתר ל-file_id לא תישמר (כדי לא ליצור יתומות)."""
        mock_db.get_file.return_value = None

        zip_bytes = self._make_zip(
            {
                "backup_info.json": {"version": 1},
                "metadata/files.json": {"regular_files": [], "large_files": []},
                "metadata/sticky_notes.json": [
                    {"file_name": "missing.py", "content": "note", "color": "#fff"}
                ],
            }
        )

        result = backup_service.restore_user_data(12345, zip_bytes, overwrite=False)
        assert result["ok"] is True
        assert result["restored"]["sticky_notes"] == 0
        assert mock_db.db.sticky_notes.insert_one.call_count == 0

