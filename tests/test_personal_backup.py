"""
טסטים ליחידת הגיבוי האישי.

חשוב: כל הפעולות על תיקיות זמניות (tmp_path) בלבד.
"""
import json
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest


def make_backup_zip(files_dict: dict) -> bytes:
    """בונה ZIP גיבוי מדומה. מילון/רשימה נכתבים כ-JSON, כל השאר כמחרוזת."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, content in files_dict.items():
            zf.writestr(path, json.dumps(content) if isinstance(content, (dict, list)) else str(content))
    return buf.getvalue()


@pytest.fixture
def mock_db():
    """יוצר DatabaseManager מדומה עם נתוני דוגמה."""
    db = MagicMock()

    # קבצים רגילים
    db.get_user_files.return_value = [
        {
            "file_name": "hello.py",
            "code": "print('hello')",
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

    def test_export_does_not_call_get_file_per_file(self, backup_service, mock_db):
        """ביצועים: export לא אמור לעשות N+1 (get_file לכל קובץ)."""
        _ = backup_service.export_user_data(user_id=12345)
        assert mock_db.get_file.call_count == 0

    def test_export_prefers_uncached_collection_aggregate_over_get_user_files(self, mock_db):
        """נכונות: ייצוא גיבוי צריך לעקוף cache של get_user_files ולהשתמש ב-aggregate ישיר כשאפשר."""
        from services.personal_backup_service import PersonalBackupService

        # Arrange: emulate DatabaseManager.collection.aggregate path
        mock_db.collection = MagicMock()
        mock_db.collection.aggregate.return_value = [
            {
                "file_name": "hello.py",
                "code": "print('fresh')",
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

        svc = PersonalBackupService(mock_db)

        # Act
        buffer = svc.export_user_data(user_id=12345)

        # Assert: we didn't call cached get_user_files at all
        assert mock_db.get_user_files.call_count == 0
        with zipfile.ZipFile(buffer, "r") as zf:
            content = zf.read("files/hello.py").decode("utf-8")
            assert content == "print('fresh')"

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
    def test_restore_basic(self, backup_service, mock_db):
        """בדיקת שחזור בסיסי."""
        mock_db.get_file.return_value = None  # אין קובץ קיים
        mock_db.save_code_snippet.return_value = True

        zip_bytes = make_backup_zip(
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

        zip_bytes = make_backup_zip(
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

        zip_bytes = make_backup_zip(
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

        zip_bytes = make_backup_zip(
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

        zip_bytes = make_backup_zip(
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

        zip_bytes = make_backup_zip(
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

        zip_bytes = make_backup_zip(
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
        zip_bytes = make_backup_zip(
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

        zip_bytes = make_backup_zip(
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

        zip_bytes = make_backup_zip(
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

    def test_restore_board_note_lands_on_the_named_board(self, backup_service, mock_db):
        """פתק לוח משוחזר לפי **שם** הלוח.

        עד היום הוא נפל על ה-``continue`` שדורש ``file_name``, כלומר פתקי
        לוח לא שרדו גיבוי-שחזור — בשקט, בלי שורת שגיאה. הבדיקה הזו נופלת
        על הקוד שהיה כאן לפני התיקון.
        """
        mock_db.db.note_boards.find_one.return_value = {"_id": "board-77", "name": "לוח עבודה"}
        # ברירת המחדל של MagicMock היא אובייקט אמיתי, ובדיקת הכפילות הייתה
        # קוראת אותה כ"הפתק כבר קיים"
        mock_db.db.sticky_notes.find_one.return_value = None

        zip_bytes = make_backup_zip(
            {
                "backup_info.json": {"version": 1},
                "metadata/files.json": {"regular_files": [], "large_files": []},
                "metadata/sticky_notes.json": [
                    {"board_id": "old-id", "board_name": "לוח עבודה", "content": "משימה"}
                ],
            }
        )

        result = backup_service.restore_user_data(12345, zip_bytes, overwrite=False)

        assert result["ok"] is True
        assert result["restored"]["sticky_notes"] == 1
        doc = mock_db.db.sticky_notes.insert_one.call_args[0][0]
        assert doc["board_id"] == "board-77"
        assert "file_id" not in doc  # אילוץ "בדיוק אחד"

    def test_restore_skips_sticky_note_when_file_cannot_be_resolved(self, backup_service, mock_db):
        """פתקית עם file_name שלא נפתר ל-file_id לא תישמר (כדי לא ליצור יתומות)."""
        mock_db.get_file.return_value = None

        zip_bytes = make_backup_zip(
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



# --- שימור תאריכים בשחזור ------------------------------------------------------
#
# הייצוא כבר שומר created_at/updated_at כמחרוזות ISO. עד לתיקון הזה השחזור
# פשוט לא קרא אותן, ולכן כל קובץ, סימנייה או פתק שנעדר מהמסד קיבל את תאריך
# היום. הטסטים כאן בודקים את הארגומנטים שנמסרים בפועל — הטסטים הקיימים
# בודקים רק ש-save_code_snippet נקרא, ולכן אינם מסוגלים לתפוס את זה.

ORIGINAL_ISO = "2019-03-07T09:15:00+00:00"
EDITED_ISO = "2023-11-02T18:40:00+00:00"


class TestStoredDatetimeParsing:
    """‏_str_to_dt הוא ההפוך של _dt_to_str, והיעדרו הוא שורש הבאג."""

    def test_round_trip_preserves_the_moment(self):
        from services.personal_backup_service import _dt_to_str, _str_to_dt

        original = datetime(2019, 3, 7, 9, 15, tzinfo=timezone.utc)
        assert _str_to_dt(_dt_to_str(original)) == original

    def test_naive_input_is_read_as_utc(self):
        """מונגו שומר datetime בלי תווית אזור זמן, והוא תמיד UTC."""
        from services.personal_backup_service import _str_to_dt

        parsed = _str_to_dt("2019-03-07T09:15:00")
        assert parsed == datetime(2019, 3, 7, 9, 15, tzinfo=timezone.utc)
        assert parsed.tzinfo is not None

    def test_datetime_passes_through_as_aware(self):
        from services.personal_backup_service import _str_to_dt

        assert _str_to_dt(datetime(2019, 3, 7, 9, 15)) == datetime(2019, 3, 7, 9, 15, tzinfo=timezone.utc)

    @pytest.mark.parametrize("bad", [None, "", "   ", "לא תאריך", "2019-13-45", 1552000000, {"a": 1}, []])
    def test_malformed_input_falls_back_to_none(self, bad):
        """ה-ZIP הוא קלט חיצוני שהמשתמש מעלה ואפשר לערוך אותו ביד.

        None שקול בדיוק להתנהגות שלפני התיקון, ולכן גיבוי ישן או פגום
        מתנהג כמו קודם במקום להפיל את השחזור.
        """
        from services.personal_backup_service import _str_to_dt

        assert _str_to_dt(bad) is None


class TestRestorePreservesDates:
    def test_regular_file_carries_both_dates_from_the_backup(self, backup_service, mock_db):
        mock_db.get_file.return_value = None
        mock_db.save_code_snippet.return_value = True

        zip_bytes = make_backup_zip({
            "backup_info.json": {"version": 1},
            "metadata/files.json": {
                "regular_files": [{
                    "file_name": "test.py", "programming_language": "python",
                    "description": "", "tags": [],
                    "created_at": ORIGINAL_ISO, "updated_at": EDITED_ISO,
                }],
                "large_files": [],
            },
            "files/test.py": "# test file",
        })

        assert backup_service.restore_user_data(12345, zip_bytes)["ok"] is True
        snippet = mock_db.save_code_snippet.call_args.args[0]
        assert snippet.created_at == datetime(2019, 3, 7, 9, 15, tzinfo=timezone.utc)
        assert snippet.updated_at == datetime(2023, 11, 2, 18, 40, tzinfo=timezone.utc)

    def test_large_file_carries_the_date_from_the_backup(self, backup_service, mock_db):
        mock_db.get_large_file.return_value = None
        mock_db.save_large_file.return_value = True

        zip_bytes = make_backup_zip({
            "backup_info.json": {"version": 1},
            "metadata/files.json": {
                "regular_files": [],
                "large_files": [{
                    "file_name": "big.txt", "programming_language": "text",
                    "description": "", "tags": [], "created_at": ORIGINAL_ISO,
                }],
            },
            "large_files/big.txt": "x\n" * 10,
        })

        assert backup_service.restore_user_data(12345, zip_bytes)["ok"] is True
        large = mock_db.save_large_file.call_args.args[0]
        assert large.created_at == datetime(2019, 3, 7, 9, 15, tzinfo=timezone.utc)

    def test_backup_without_dates_behaves_exactly_as_before(self, backup_service, mock_db):
        """גיבוי ישן בלי השדות — created_at נופל ל-now, כמו קודם."""
        mock_db.get_file.return_value = None
        mock_db.save_code_snippet.return_value = True

        zip_bytes = make_backup_zip({
            "backup_info.json": {"version": 1},
            "metadata/files.json": {
                "regular_files": [{
                    "file_name": "test.py", "programming_language": "python",
                    "description": "", "tags": [],
                }],
                "large_files": [],
            },
            "files/test.py": "# test file",
        })

        before = datetime.now(timezone.utc)
        assert backup_service.restore_user_data(12345, zip_bytes)["ok"] is True
        snippet = mock_db.save_code_snippet.call_args.args[0]
        assert snippet.created_at >= before
        # וקובץ חדש: שני התאריכים זהים בדיוק
        assert snippet.updated_at == snippet.created_at


# --- החוזה בין הייצוא לשחזור ---------------------------------------------------
#
# עד כאן שני הצדדים לא נפגשו באף בדיקה: TestExport בודק ZIP שנוצר, ו-TestRestore
# מזין ZIP שנבנה ידנית בטסט. לכן שדה שהשחזור קורא והייצוא לא כותב נראה כמו
# תיקון ועובר בשקט — בדיוק מה שקרה ל-updated_at של הסימניות.
#
# הבדיקה הזאת מריצה את שני מסלולי הקוד האמיתיים בזה אחר זה, ורק ה-DB מדומה.

RT_CREATED = datetime(2019, 3, 7, 9, 15, tzinfo=timezone.utc)
RT_UPDATED = datetime(2023, 11, 2, 18, 40, tzinfo=timezone.utc)


class TestExportRestoreRoundTrip:
    @pytest.fixture
    def seeded_db(self, mock_db):
        """מזין למסד המדומה נתונים עם תאריכים היסטוריים, לכל ארבע הישויות."""
        mock_db.get_user_files.return_value = [{
            "file_name": "hello.py", "code": "print('hello')",
            "programming_language": "python", "description": "", "tags": [],
            "is_favorite": False, "is_pinned": False, "pin_order": 0, "version": 3,
            "created_at": RT_CREATED, "updated_at": RT_UPDATED,
        }]
        mock_db.get_user_large_files.return_value = ([{
            "file_name": "big.txt", "content": "x\n" * 10,
            "programming_language": "text", "description": "", "tags": [],
            "file_size": 20, "lines_count": 10,
            "created_at": RT_CREATED, "updated_at": RT_UPDATED,
        }], 1)
        mock_db.get_large_file.return_value = {"file_name": "big.txt", "content": "x\n" * 10}
        mock_db.db.file_bookmarks.find.return_value = [{
            "user_id": 12345, "file_name": "hello.py", "file_path": "hello.py",
            "line_number": 1, "line_text_preview": "print('hello')", "note": "",
            "color": "yellow", "valid": True,
            "created_at": RT_CREATED, "updated_at": RT_UPDATED,
        }]
        mock_db.db.sticky_notes.find.return_value = [{
            "user_id": 12345, "file_name": "hello.py", "content": "a note",
            "color": "#FFFFCC", "position_x": 10, "position_y": 10,
            "width": 250, "height": 200,
            "created_at": RT_CREATED, "updated_at": RT_UPDATED,
        }]
        return mock_db

    def _round_trip(self, service, db):
        buffer = service.export_user_data(12345)
        zip_bytes = buffer.getvalue() if hasattr(buffer, "getvalue") else buffer

        # מנקים את צד הכתיבה כדי שהאסרשנים יתייחסו לשחזור בלבד
        db.save_code_snippet.reset_mock()
        db.save_large_file.reset_mock()
        db.db.file_bookmarks.insert_one.reset_mock()
        db.db.sticky_notes.insert_one.reset_mock()

        # get_file חייב להחזיר מסמך: גם שחזור הסימניות וגם שחזור הפתקיות
        # מדלגים על פריט שאי אפשר לשייך לקובץ. התוכן שונה מזה שבגיבוי כדי
        # שהשחזור לא ידלג על הקובץ עצמו כ"זהה".
        db.get_file.return_value = {"_id": "abc123", "file_name": "hello.py", "code": "print('OLD')"}
        db.get_large_file.return_value = {"file_name": "big.txt", "content": "OLD\n"}
        # ברירת המחדל של MagicMock אמיתית ולכן truthy — בדיקות הכפילות היו
        # מדלגות על כל פריט.
        db.db.file_bookmarks.find_one.return_value = None
        db.db.sticky_notes.find_one.return_value = None

        result = service.restore_user_data(12345, zip_bytes, overwrite=True)
        assert result["ok"] is True, result
        return result

    def test_regular_file_dates_survive_the_round_trip(self, backup_service, seeded_db):
        self._round_trip(backup_service, seeded_db)
        snippet = seeded_db.save_code_snippet.call_args.args[0]
        assert snippet.created_at == RT_CREATED
        assert snippet.updated_at == RT_UPDATED

    def test_large_file_dates_survive_the_round_trip(self, backup_service, seeded_db):
        self._round_trip(backup_service, seeded_db)
        large = seeded_db.save_large_file.call_args.args[0]
        assert large.created_at == RT_CREATED
        assert large.updated_at == RT_UPDATED

    def test_bookmark_dates_survive_the_round_trip(self, backup_service, seeded_db):
        """זה הטסט שתופס שדה שהשחזור קורא והייצוא לא כותב."""
        self._round_trip(backup_service, seeded_db)
        doc = seeded_db.db.file_bookmarks.insert_one.call_args.args[0]
        assert doc["created_at"] == RT_CREATED
        assert doc["updated_at"] == RT_UPDATED

    def test_sticky_note_dates_survive_the_round_trip(self, backup_service, seeded_db):
        self._round_trip(backup_service, seeded_db)
        doc = seeded_db.db.sticky_notes.insert_one.call_args.args[0]
        assert doc["created_at"] == RT_CREATED
        assert doc["updated_at"] == RT_UPDATED

    def test_bookmark_dates_survive_the_round_trip_via_the_fallback_export(
        self, backup_service, seeded_db
    ):
        """לייצוא הסימניות שני מסלולים, וה-fallback נכנס כשהראשי זורק.

        בלי הבדיקה הזאת התיקון במסלול ה-fallback היה נשאר לא מאומת — מוטציה
        שמסירה אותו לא הפילה שום טסט.
        """
        seeded_db.db.file_bookmarks.find.side_effect = RuntimeError("אין תמיכה ב-find")

        class _FakeBookmarksManager:
            def __init__(self, _raw_db):
                pass

            def get_user_bookmarks(self, _user_id, limit=5000):
                return {
                    "ok": True,
                    "files": [{
                        "file_name": "hello.py",
                        "file_path": "hello.py",
                        "bookmarks": [{
                            "line_number": 1,
                            "line_text_preview": "print('hello')",
                            "note": "",
                            "color": "yellow",
                            "created_at": RT_CREATED,
                            "updated_at": RT_UPDATED,
                        }],
                    }],
                }

        with patch("database.bookmarks_manager.BookmarksManager", _FakeBookmarksManager):
            self._round_trip(backup_service, seeded_db)

        doc = seeded_db.db.file_bookmarks.insert_one.call_args.args[0]
        assert doc["created_at"] == RT_CREATED
        assert doc["updated_at"] == RT_UPDATED
