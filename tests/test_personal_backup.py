"""
טסטים ליחידת הגיבוי האישי.

חשוב: כל הפעולות על תיקיות זמניות (tmp_path) בלבד.
"""
import json
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def make_backup_zip(files_dict: dict) -> bytes:
    """בונה ZIP גיבוי מדומה. מילון/רשימה נכתבים כ-JSON, כל השאר כמחרוזת."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, content in files_dict.items():
            zf.writestr(path, json.dumps(content) if isinstance(content, (dict, list)) else str(content))
    return buf.getvalue()


class _BoardsColl:
    """אוסף ``note_boards`` עם מצב אמיתי, בתבנית ה-stub שכבר נהוגה בריפו.

    ‏``MagicMock`` שבו ``find_one`` מחזיר תמיד ``None`` הופך כל אימות
    בקריאה חוזרת לכישלון: השירות מדווח "לא נכתב בפועל" על כל לוח והספירה
    נשארת 0 — בעוד שטסט שבודק רק את קריאות ``insert_one`` עובר. זה ירוק
    שקרי, כי הוא עובר גם כשהשחזור לא עשה דבר. כאן ה-insert באמת נקלט,
    ולכן אפשר לטעון על מה שהשירות **מדווח** ולא רק על מה שהוא ניסה.

    ‏``drop_writes`` מדמה במכוון את המצב ההפוך — כתיבה שחוזרת עם
    ``inserted_id`` ולא נקלטה — כדי שנתיב הדיווח על כישלון יישאר מכוסה.
    """

    def __init__(self, docs=None, *, drop_writes=False, find_fails=False):
        self.docs = [dict(d) for d in (docs or [])]
        self.drop_writes = drop_writes
        self.find_fails = find_fails
        self.inserted = []
        self._next_id = 1

    @staticmethod
    def _matches(doc, query):
        return all(doc.get(key) == value for key, value in (query or {}).items())

    def find(self, query=None, *args, **kwargs):
        if self.find_fails:
            raise RuntimeError("connection reset")
        return [dict(d) for d in self.docs if self._matches(d, query)]

    def find_one(self, query=None, *args, **kwargs):
        for doc in self.docs:
            if self._matches(doc, query):
                return dict(doc)
        return None

    def insert_one(self, doc):
        doc = dict(doc)
        doc["_id"] = f"new-{self._next_id}"
        self._next_id += 1
        self.inserted.append(dict(doc))
        if not self.drop_writes:
            self.docs.append(doc)
        return SimpleNamespace(inserted_id=doc["_id"])

    def update_one(self, query, update):
        for doc in self.docs:
            if self._matches(doc, query):
                doc.update(update.get("$set", {}))
                return SimpleNamespace(matched_count=1, modified_count=1)
        return SimpleNamespace(matched_count=0, modified_count=0)

    def count_documents(self, query=None, *args, **kwargs):
        return len(self.find(query))

    def names_inserted(self):
        return [str(d.get("name") or "") for d in self.inserted]


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
    # note_boards מוגדר במפורש: MagicMock עצל מחזיר אובייקט truthy, ואז
    # בדיקות קיום ודה-דופליקציה קוראות אותו כ"כבר קיים" ומדלגות בשקט.
    mock_raw_db.note_boards.find.return_value = []
    mock_raw_db.note_boards.find_one.return_value = None
    mock_raw_db.note_boards.count_documents.return_value = 0
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


class TestOneClockPerRecord:
    """רשומה שנוצרת עכשיו חייבת לצאת עם ``created_at == updated_at`` בדיוק.

    שתי קריאות נפרדות ל-``datetime.now()`` נבדלות במיקרו-שניות, וזה מספיק
    כדי שהממשק יציג "עודכן" על רשומה שמעולם לא נערכה — בדיוק הבאג שה-PR
    הזה בא לתקן, רק בשחזור במקום בעריכה. אותו invariant כבר נאכף
    ב-``database/models.py``, ולא הוחל כאן.
    """

    def test_a_bookmark_without_dates_gets_one_clock(self, backup_service, mock_db):
        mock_db.get_file.return_value = {"_id": "f1", "file_name": "hello.py"}
        mock_db.db.file_bookmarks.find_one.return_value = None

        zip_bytes = make_backup_zip({
            "backup_info.json": {"version": 1},
            "metadata/bookmarks.json": [{"file_name": "hello.py", "line_number": 3}],
        })

        assert backup_service.restore_user_data(12345, zip_bytes)["ok"] is True
        doc = mock_db.db.file_bookmarks.insert_one.call_args.args[0]
        assert doc["created_at"] == doc["updated_at"]

    def test_a_board_note_without_dates_gets_one_clock(self, backup_service, mock_db):
        mock_db.db.note_boards = _BoardsColl()
        mock_db.db.sticky_notes.find_one.return_value = None
        mock_db.db.sticky_notes.count_documents.return_value = 0

        zip_bytes = make_backup_zip({
            "backup_info.json": {"version": 1},
            "metadata/note_boards.json": [{"name": "רעיונות", "is_default": False, "order": 1}],
            "metadata/sticky_notes.json": [{"board_name": "רעיונות", "content": "פתק"}],
        })

        assert backup_service.restore_user_data(12345, zip_bytes)["ok"] is True
        doc = mock_db.db.sticky_notes.insert_one.call_args.args[0]
        assert doc["created_at"] == doc["updated_at"]

    def test_a_file_note_without_dates_gets_one_clock(self, backup_service, mock_db):
        mock_db.get_file.return_value = {"_id": "f1", "file_name": "hello.py"}
        mock_db.db.sticky_notes.find_one.return_value = None

        zip_bytes = make_backup_zip({
            "backup_info.json": {"version": 1},
            "metadata/sticky_notes.json": [{"file_name": "hello.py", "content": "פתק"}],
        })

        assert backup_service.restore_user_data(12345, zip_bytes)["ok"] is True
        doc = mock_db.db.sticky_notes.insert_one.call_args.args[0]
        assert doc["created_at"] == doc["updated_at"]


# --- החוזה בין הייצוא לשחזור ---------------------------------------------------
#
# עד כאן שני הצדדים לא נפגשו באף בדיקה: TestExport בודק ZIP שנוצר, ו-TestRestore
# מזין ZIP שנבנה ידנית בטסט. לכן שדה שהשחזור קורא והייצוא לא כותב נראה כמו
# תיקון ועובר בשקט — בדיוק מה שקרה ל-updated_at של הסימניות.
#
# הבדיקה הזאת מריצה את שני מסלולי הקוד האמיתיים בזה אחר זה, ורק ה-DB מדומה.

RT_BOARD_NAME = "רעיונות"
RT_BOARD_NAME_2 = "משימות"
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
        mock_db.db.note_boards.find.return_value = [
            {
                "_id": "board-1", "user_id": 12345, "name": RT_BOARD_NAME,
                "is_default": False, "is_pinned": True, "order": 3,
                "created_at": RT_CREATED, "updated_at": RT_UPDATED,
            },
            {
                "_id": "board-2", "user_id": 12345, "name": RT_BOARD_NAME_2,
                "is_default": False, "is_pinned": False, "order": 7,
                "created_at": RT_CREATED, "updated_at": RT_UPDATED,
            },
        ]
        return mock_db

    def _round_trip(self, service, db):
        buffer = service.export_user_data(12345)
        zip_bytes = buffer.getvalue() if hasattr(buffer, "getvalue") else buffer

        # מנקים את צד הכתיבה כדי שהאסרשנים יתייחסו לשחזור בלבד
        db.save_code_snippet.reset_mock()
        db.save_large_file.reset_mock()
        db.db.file_bookmarks.insert_one.reset_mock()
        db.db.sticky_notes.insert_one.reset_mock()
        db.db.note_boards.insert_one.reset_mock()
        # השחזור מדמה חשבון נקי — אוסף עם מצב, לא MagicMock: רק כך האימות
        # בקריאה חוזרת שבשירות יכול להצליח, ורק אז יש טעם לטעון על התוצאה
        # שהוא מדווח ולא על קריאות הכתיבה שלו.
        db.db.note_boards = _BoardsColl()

        # get_file חייב להחזיר מסמך: גם שחזור הסימניות וגם שחזור הפתקיות
        # מדלגים על פריט שאי אפשר לשייך לקובץ. התוכן שונה מזה שבגיבוי כדי
        # שהשחזור לא ידלג על הקובץ עצמו כ"זהה".
        db.get_file.return_value = {"_id": "abc123", "file_name": "hello.py", "code": "print('OLD')"}
        db.get_large_file.return_value = {"file_name": "big.txt", "content": "OLD\n"}
        # ברירת המחדל של MagicMock אמיתית ולכן truthy — בדיקות הכפילות היו
        # מדלגות על כל פריט.
        db.db.file_bookmarks.find_one.return_value = None
        db.db.sticky_notes.find_one.return_value = None
        # המצב הקיים בחשבון חייב להתאים לנתונים שנזרעו: MagicMock מחזיר
        # אובייקט truthy, ולכן השחזור היה "מיישר" נעיצה ומועדפים שלא היו
        # ונכשל על ערך החזרה שאינו dict. שגיאה זו נבלעה עד שהטסטים כאן
        # התחילו לטעון על ``errors``.
        db.is_favorite.return_value = False
        db.is_pinned.return_value = False

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

    def test_note_board_survives_the_round_trip(self, backup_service, seeded_db):
        """הלוח עצמו נכנס לגיבוי וקם מחדש בשחזור.

        עד לתיקון הזה הייצוא קרא מ-``note_boards`` רק כדי להזליג ``board_name``
        על הפתקים, ומסמכי הלוח לא נשמרו כלל — כך שכל הלוחות נעלמו בשחזור
        לסביבה נקייה, וכל הפתקים נחתו על לוח ברירת המחדל.
        """
        result = self._round_trip(backup_service, seeded_db)

        # קודם כול מה שהשירות מדווח: ספירה ושגיאות. טענה על קריאות
        # ``insert_one`` בלבד הייתה עוברת גם כששני הלוחות נכשלו באימות
        # בקריאה חוזרת והשחזור בפועל לא הותיר דבר.
        assert result["errors"] == [], result["errors"]
        assert result["restored"]["note_boards"] == 2, result["restored"]

        inserted = [
            d for d in seeded_db.db.note_boards.inserted
            if str(d.get("name") or "") == RT_BOARD_NAME
        ]
        assert inserted, "הלוח לא שוחזר"
        board = inserted[0]
        assert board["is_pinned"] is True, "בלי is_pinned המשתמש מאבד את בורר הלוחות"
        assert board["created_at"] == RT_CREATED
        assert board["updated_at"] == RT_UPDATED
        # לעולם לא לוח ברירת מחדל שני — one_default_per_user ידחה אותו
        assert board["is_default"] is False

    def test_relative_board_order_survives_the_round_trip(self, backup_service, seeded_db):
        """‏``order`` ממוספר מחדש ולא מועתק — אבל הסדר היחסי נשמר.

        העתקת המספר המקורי הייתה מתנגשת עם לוחות קיימים בחשבון היעד;
        הייצוא ממוין לפי ``order``, ולכן מספור מחדש משמר את הסדר.
        """
        result = self._round_trip(backup_service, seeded_db)
        assert result["errors"] == [], result["errors"]

        by_name = {
            str(d.get("name") or ""): d
            for d in seeded_db.db.note_boards.inserted
        }
        assert RT_BOARD_NAME in by_name and RT_BOARD_NAME_2 in by_name, by_name.keys()
        assert by_name[RT_BOARD_NAME]["order"] < by_name[RT_BOARD_NAME_2]["order"]

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


class TestRestoreNoteBoards:
    """המלכודות של שחזור לוחות — כולן נגזרות מהמסד ומהתיעוד, לא מהערכה."""

    def _zip_with_boards(self, boards):
        return make_backup_zip({
            "backup_info.json": {"version": 1},
            "metadata/note_boards.json": boards,
        })

    def _restore(self, service, db, boards, existing=None, *, drop_writes=False, find_fails=False):
        """מחליף את ``note_boards`` באוסף עם מצב — ראו הדוקסטרינג של ``_BoardsColl``."""
        db.db.note_boards = _BoardsColl(existing, drop_writes=drop_writes, find_fails=find_fails)
        return service.restore_user_data(12345, self._zip_with_boards(boards), overwrite=True)

    def test_default_board_from_the_backup_is_never_inserted(self, backup_service, mock_db):
        """‏one_default_per_user הוא ייחודי-חלקי: לוח ברירת מחדל שני נדחה.

        ומעבר לאינדקס — זו גם ההחלטה המוצרית: השם שנקבע בחשבון היעד
        אינו נדרס, כי זו פעולה שאי אפשר לבטל.
        """
        self._restore(backup_service, mock_db, [
            {"name": "המשרד שלי", "is_default": True, "order": 0},
        ])
        assert "המשרד שלי" not in mock_db.db.note_boards.names_inserted()

    def test_a_board_that_already_exists_is_not_duplicated(self, backup_service, mock_db):
        """אידמפוטנטי, בדיוק כמו שחזור אוספים."""
        result = self._restore(
            backup_service, mock_db,
            [{"name": "רעיונות", "is_default": False, "order": 1}],
            existing=[{"_id": "b1", "user_id": 12345, "name": "רעיונות", "order": 1}],
        )
        assert result["restored"]["note_boards"] == 0
        assert mock_db.db.note_boards.names_inserted().count("רעיונות") == 0

    def test_board_name_from_the_backup_is_normalized(self, backup_service, mock_db):
        """ה-ZIP הוא קלט חיצוני שאפשר לערוך ביד — שם עובר את אותה נורמליזציה."""
        self._restore(backup_service, mock_db, [
            {"name": "  רעיונות   רבים  ", "is_default": False, "order": 1},
            {"name": "x" * 500, "is_default": False, "order": 2},
        ])
        names = mock_db.db.note_boards.names_inserted()
        assert "רעיונות רבים" in names, names
        assert all(len(n) <= 120 for n in names), [len(n) for n in names]

    def test_a_corrupt_order_does_not_break_the_restore(self, backup_service, mock_db):
        result = self._restore(backup_service, mock_db, [
            {"name": "רעיונות", "is_default": False, "order": "לא מספר"},
        ])
        assert result["ok"] is True
        board = [b for b in mock_db.db.note_boards.inserted if b.get("name") == "רעיונות"]
        assert board and isinstance(board[0]["order"], int)

    def test_the_board_quota_is_enforced_on_restore(self, backup_service, mock_db):
        """התקרה נאכפת גם כאן, אחרת זו אכיפה עם דלת אחורית."""
        from webapp.note_boards_api import MAX_BOARDS_PER_USER

        result = self._restore(
            backup_service, mock_db,
            [{"name": "אחד יותר מדי", "is_default": False, "order": 1}],
            existing=[
                {"_id": f"b{i}", "user_id": 12345, "name": f"לוח {i}", "order": i}
                for i in range(MAX_BOARDS_PER_USER)
            ],
        )
        assert result["restored"]["note_boards"] == 0
        assert any("תקרת" in e for e in result["errors"]), result["errors"]

    def test_an_insert_that_did_not_land_is_reported(self, backup_service, mock_db):
        """‏inserted_id אינו הוכחה — הסטנדרט בכל הריפו הוא אימות בקריאה חוזרת."""
        result = self._restore(
            backup_service, mock_db,
            [{"name": "רעיונות", "is_default": False, "order": 1}],
            drop_writes=True,  # ה-insert חוזר עם inserted_id ולא נקלט
        )
        assert result["restored"]["note_boards"] == 0
        assert any("לא נכתב בפועל" in e for e in result["errors"]), result["errors"]

    def test_a_namesake_board_does_not_confirm_an_insert_that_did_not_land(
        self, backup_service, mock_db
    ):
        """האימות חייב להיות לפי המזהה שהוכנס, לא לפי השם.

        אין אינדקס ייחודי על שם לוח, ובניית מפת הקיימים עטופה ב-try/except.
        כשהיא נכשלת הדה-דופליקציה לא רצה — ואז חיפוש לפי שם נענה על ידי הלוח
        הקיים באותו שם, ומאשר insert שכלל לא נקלט. זו בדיוק בדיקה שאינה
        מסוגלת להיכשל, והפעם היא נמצאה בקוד שנכתב כדי לאמת.
        """
        result = self._restore(
            backup_service, mock_db,
            [{"name": "רעיונות", "is_default": False, "order": 1}],
            existing=[{"_id": "b1", "user_id": 12345, "name": "רעיונות", "order": 1}],
            drop_writes=True,
            find_fails=True,
        )
        assert result["restored"]["note_boards"] == 0
        assert any("לא נכתב בפועל" in e for e in result["errors"]), result["errors"]

    def test_the_default_board_pin_is_restored(self, backup_service, mock_db):
        """הנעיצה היא ההעדפה היחידה שאפשר לשחזר על לוח ברירת המחדל.

        השם וה-``_id`` של היעד אינם נגעים, ולכן בלי זה מי שנעץ את לוח ברירת
        המחדל מאבד את בורר הלוחות המהיר — בעוד שמי שנעץ לוח רגיל מקבל אותו
        בחזרה. אותה העדפה בדיוק, שתי תוצאות שונות.
        """
        result = self._restore(backup_service, mock_db, [
            {"name": "המשרד שלי", "is_default": True, "is_pinned": True, "order": 0},
        ])
        assert result["errors"] == [], result["errors"]
        # לא נספר כלוח ששוחזר: לא נוצר לוח, רק עודכנה העדפה על לוח קיים
        assert result["restored"]["note_boards"] == 0

        default_board = mock_db.db.note_boards.find_one({"user_id": 12345, "is_default": True})
        assert default_board is not None, "לוח ברירת המחדל לא קיים"
        assert default_board["is_pinned"] is True
        # השם שנקבע בחשבון היעד לא נדרס — פעולה שאי אפשר לבטל
        assert default_board["name"] == "לוח עבודה", default_board["name"]
        assert "המשרד שלי" not in mock_db.db.note_boards.names_inserted()

    def test_the_default_board_pin_is_also_restored_when_it_was_off(
        self, backup_service, mock_db
    ):
        """שחזור מחזיר את המצב שבגיבוי, גם כשהוא "לא נעוץ".

        בלי הכיוון הזה הטענה הקודמת הייתה עוברת גם על קוד שקובע ``True``
        קשיח, בלי לקרוא את הגיבוי בכלל.
        """
        result = self._restore(
            backup_service, mock_db,
            [{"name": "המשרד שלי", "is_default": True, "is_pinned": False, "order": 0}],
            existing=[{
                "_id": "d1", "user_id": 12345, "name": "לוח עבודה",
                "is_default": True, "is_pinned": True, "order": 0,
            }],
        )
        assert result["errors"] == [], result["errors"]
        default_board = mock_db.db.note_boards.find_one({"user_id": 12345, "is_default": True})
        assert default_board["is_pinned"] is False


def test_a_failed_board_import_does_not_abort_the_whole_restore(backup_service, mock_db, monkeypatch):
    """כשל ייבוא בשחזור הלוחות מתנוון ל-``errors``, ואינו מפיל את השחזור.

    ‏``restore_user_data`` אינו עוטף את הקריאה ל-``_restore_note_boards``
    (אימות: אין ``try`` בפונקציה שמכסה את השורה), ולכן ייבוא שיושב **לפני**
    ה-``try`` הפנימי היה מפיל את כל השחזור — אחרי שקבצים, אוספים וסימניות
    כבר נכתבו. כל שלב אחר בשחזור מתנוון וממשיך; זה חייב להתנהג כמוהו.
    """
    import builtins

    real_import = builtins.__import__

    def _boom(name, *args, **kwargs):
        if name == "webapp.note_boards_api":
            raise ImportError("simulated")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _boom)

    zip_bytes = make_backup_zip({
        "backup_info.json": {"version": 1},
        "metadata/note_boards.json": [{"name": "רעיונות", "is_default": False, "order": 1}],
    })

    result = backup_service.restore_user_data(12345, zip_bytes, overwrite=True)

    assert result["ok"] is True, "כשל ייבוא הפיל את כל השחזור"
    assert result["restored"]["note_boards"] == 0
    assert any("לוחות" in e for e in result["errors"]), result["errors"]
