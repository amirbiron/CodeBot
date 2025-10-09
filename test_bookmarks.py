#!/usr/bin/env python3
"""
Test suite for Bookmarks feature
בדיקות למערכת הסימניות
"""

import unittest
import sys
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from database.bookmark import FileBookmark, MAX_BOOKMARKS_PER_FILE, MAX_BOOKMARKS_PER_USER
from database.bookmarks_manager import BookmarksManager


class TestFileBookmarkModel(unittest.TestCase):
    """Tests for FileBookmark model"""
    
    def test_bookmark_creation(self):
        """Test creating a bookmark"""
        bookmark = FileBookmark(
            user_id=123,
            file_id="abc123",
            file_name="test.py",
            file_path="/path/test.py",
            line_number=42,
            line_text_preview="def test():",
            note="Test note"
        )
        
        self.assertEqual(bookmark.user_id, 123)
        self.assertEqual(bookmark.line_number, 42)
        self.assertEqual(bookmark.note, "Test note")
        self.assertTrue(bookmark.valid)
    
    def test_bookmark_to_dict(self):
        """Test converting bookmark to dictionary"""
        bookmark = FileBookmark(
            user_id=123,
            file_id="abc123",
            file_name="test.py",
            file_path="/path/test.py",
            line_number=42
        )
        
        data = bookmark.to_dict()
        
        self.assertIn("user_id", data)
        self.assertIn("file_id", data)
        self.assertIn("line_number", data)
        self.assertEqual(data["user_id"], 123)
        self.assertEqual(data["line_number"], 42)
    
    def test_bookmark_from_dict(self):
        """Test creating bookmark from dictionary"""
        data = {
            "user_id": 456,
            "file_id": "def456",
            "file_name": "another.py",
            "file_path": "/another.py",
            "line_number": 100,
            "note": "Another note",
            "created_at": datetime.now(timezone.utc)
        }
        
        bookmark = FileBookmark.from_dict(data)
        
        self.assertEqual(bookmark.user_id, 456)
        self.assertEqual(bookmark.file_id, "def456")
        self.assertEqual(bookmark.line_number, 100)
        self.assertEqual(bookmark.note, "Another note")
    
    def test_text_length_limits(self):
        """Test that text fields are properly limited"""
        long_text = "x" * 1000
        
        bookmark = FileBookmark(
            user_id=123,
            file_id="abc",
            file_name="test.py",
            file_path="/test.py",
            line_number=1,
            line_text_preview=long_text,
            note=long_text,
            code_context=long_text
        )
        
        data = bookmark.to_dict()
        
        self.assertEqual(len(data["line_text_preview"]), 100)
        self.assertEqual(len(data["note"]), 500)
        self.assertEqual(len(data["code_context"]), 500)


class TestBookmarksManager(unittest.TestCase):
    """Tests for BookmarksManager"""
    
    def setUp(self):
        """Setup test database mock"""
        self.mock_db = MagicMock()
        self.mock_collection = MagicMock()
        self.mock_db.file_bookmarks = self.mock_collection
        self.mock_db.bookmark_events = MagicMock()
        self.mock_db.files = MagicMock()
        
        self.manager = BookmarksManager(self.mock_db)
    
    def test_toggle_bookmark_add(self):
        """Test adding a new bookmark"""
        # Mock that bookmark doesn't exist
        self.mock_collection.find_one.return_value = None
        self.mock_collection.count_documents.return_value = 0
        self.mock_collection.insert_one.return_value = Mock(inserted_id="new_id")
        
        result = self.manager.toggle_bookmark(
            user_id=123,
            file_id="file123",
            file_name="test.py",
            file_path="/test.py",
            line_number=42,
            line_text="def test():",
            note="Test bookmark"
        )
        
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "added")
        self.assertIsNotNone(result["bookmark"])
        
        # Verify insert was called
        self.mock_collection.insert_one.assert_called_once()
    
    def test_toggle_bookmark_remove(self):
        """Test removing an existing bookmark"""
        # Mock that bookmark exists
        existing = {"_id": "existing_id", "user_id": 123}
        self.mock_collection.find_one.return_value = existing
        
        result = self.manager.toggle_bookmark(
            user_id=123,
            file_id="file123",
            file_name="test.py",
            file_path="/test.py",
            line_number=42
        )
        
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "removed")
        self.assertIsNone(result["bookmark"])
        
        # Verify delete was called
        self.mock_collection.delete_one.assert_called_once_with({"_id": "existing_id"})
    
    def test_bookmark_limits_per_file(self):
        """Test that bookmarks are limited per file"""
        # Mock that bookmark doesn't exist
        self.mock_collection.find_one.return_value = None
        # Mock that we're at the limit
        self.mock_collection.count_documents.side_effect = [
            MAX_BOOKMARKS_PER_FILE,  # File limit check
            0  # User limit check
        ]
        
        result = self.manager.toggle_bookmark(
            user_id=123,
            file_id="file123",
            file_name="test.py",
            file_path="/test.py",
            line_number=42
        )
        
        self.assertFalse(result["ok"])
        self.assertEqual(result["action"], "error")
        self.assertIn(str(MAX_BOOKMARKS_PER_FILE), result["error"])
    
    def test_bookmark_limits_per_user(self):
        """Test that bookmarks are limited per user"""
        # Mock that bookmark doesn't exist
        self.mock_collection.find_one.return_value = None
        # Mock that we're at the user limit
        self.mock_collection.count_documents.side_effect = [
            0,  # File limit check (OK)
            MAX_BOOKMARKS_PER_USER  # User limit check (at limit)
        ]
        
        result = self.manager.toggle_bookmark(
            user_id=123,
            file_id="file123",
            file_name="test.py",
            file_path="/test.py",
            line_number=42
        )
        
        self.assertFalse(result["ok"])
        self.assertEqual(result["action"], "error")
        self.assertIn(str(MAX_BOOKMARKS_PER_USER), result["error"])
    
    def test_invalid_line_number(self):
        """Test that invalid line numbers are rejected"""
        result = self.manager.toggle_bookmark(
            user_id=123,
            file_id="file123",
            file_name="test.py",
            file_path="/test.py",
            line_number=0  # Invalid
        )
        
        self.assertFalse(result["ok"])
        self.assertEqual(result["action"], "error")
        self.assertIn("מספר שורה", result["error"])
    
    def test_get_file_bookmarks(self):
        """Test getting bookmarks for a file"""
        mock_bookmarks = [
            {
                "_id": "id1",
                "user_id": 123,
                "file_id": "file123",
                "line_number": 10,
                "note": "First"
            },
            {
                "_id": "id2",
                "user_id": 123,
                "file_id": "file123",
                "line_number": 20,
                "note": "Second"
            }
        ]
        
        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = mock_bookmarks
        self.mock_collection.find.return_value = mock_cursor
        
        bookmarks = self.manager.get_file_bookmarks(123, "file123")
        
        self.assertEqual(len(bookmarks), 2)
        self.assertEqual(bookmarks[0]["line_number"], 10)
        self.assertEqual(bookmarks[1]["line_number"], 20)
    
    def test_update_bookmark_note(self):
        """Test updating a bookmark's note"""
        self.mock_collection.update_one.return_value = Mock(modified_count=1)
        
        result = self.manager.update_bookmark_note(
            user_id=123,
            file_id="file123",
            line_number=42,
            note="Updated note"
        )
        
        self.assertTrue(result["ok"])
        self.assertIn("עודכנה", result["message"])
        
        # Verify update was called with correct data
        call_args = self.mock_collection.update_one.call_args
        self.assertEqual(call_args[0][0]["line_number"], 42)
        self.assertEqual(call_args[0][1]["$set"]["note"], "Updated note")
    
    def test_delete_bookmark(self):
        """Test deleting a specific bookmark"""
        self.mock_collection.delete_one.return_value = Mock(deleted_count=1)
        
        result = self.manager.delete_bookmark(
            user_id=123,
            file_id="file123",
            line_number=42
        )
        
        self.assertTrue(result["ok"])
        self.assertIn("נמחקה", result["message"])
        
        # Verify delete was called
        self.mock_collection.delete_one.assert_called_once()
    
    def test_delete_file_bookmarks(self):
        """Test deleting all bookmarks for a file"""
        self.mock_collection.delete_many.return_value = Mock(deleted_count=5)
        
        result = self.manager.delete_file_bookmarks(123, "file123")
        
        self.assertTrue(result["ok"])
        self.assertEqual(result["deleted"], 5)
        
        # Verify delete_many was called
        self.mock_collection.delete_many.assert_called_once()


class TestSyncFunctionality(unittest.TestCase):
    """Tests for sync checking functionality"""
    
    def setUp(self):
        """Setup test environment"""
        self.mock_db = MagicMock()
        self.mock_collection = MagicMock()
        self.mock_db.file_bookmarks = self.mock_collection
        self.mock_db.bookmark_events = MagicMock()
        self.mock_db.files = MagicMock()
        
        self.manager = BookmarksManager(self.mock_db)
    
    def test_check_line_status_unchanged(self):
        """Test detecting unchanged lines"""
        old_text = "def test():"
        new_lines = ["import os", "def test():", "    pass"]
        
        from difflib import SequenceMatcher
        matcher = SequenceMatcher(None, [], new_lines)
        
        status = self.manager._check_line_status(2, old_text, new_lines, matcher)
        
        self.assertFalse(status["needs_update"])
    
    def test_check_line_status_modified(self):
        """Test detecting modified lines"""
        old_text = "def test():"
        new_lines = ["import os", "def test_modified():", "    pass"]
        
        from difflib import SequenceMatcher
        matcher = SequenceMatcher(None, [], new_lines)
        
        status = self.manager._check_line_status(2, old_text, new_lines, matcher)
        
        self.assertTrue(status["needs_update"])
        self.assertEqual(status["status"], "modified")
        self.assertEqual(status["new_line"], 2)
    
    def test_check_line_status_moved(self):
        """Test detecting moved lines"""
        old_text = "def specific_function():"
        new_lines = ["import os", "import sys", "", "def specific_function():", "    pass"]
        
        from difflib import SequenceMatcher
        matcher = SequenceMatcher(None, [], new_lines)
        
        status = self.manager._check_line_status(1, old_text, new_lines, matcher)
        
        self.assertTrue(status["needs_update"])
        self.assertEqual(status["status"], "moved")
        self.assertEqual(status["new_line"], 4)
    
    def test_check_line_status_deleted(self):
        """Test detecting deleted lines"""
        old_text = "def deleted_function():"
        new_lines = ["import os", "def other_function():", "    pass"]
        
        from difflib import SequenceMatcher
        matcher = SequenceMatcher(None, [], new_lines)
        
        status = self.manager._check_line_status(2, old_text, new_lines, matcher)
        
        self.assertTrue(status["needs_update"])
        self.assertEqual(status["status"], "deleted")
        self.assertIsNone(status["new_line"])


class TestIntegration(unittest.TestCase):
    """Integration tests"""
    
    @patch('database.bookmarks_manager.logger')
    def test_error_handling(self, mock_logger):
        """Test that errors are properly logged"""
        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_db.file_bookmarks = mock_collection
        mock_db.bookmark_events = MagicMock()
        mock_db.files = MagicMock()
        
        # Make insert_one raise an exception
        mock_collection.find_one.return_value = None
        mock_collection.count_documents.return_value = 0
        mock_collection.insert_one.side_effect = Exception("DB Error")
        
        manager = BookmarksManager(mock_db)
        
        result = manager.toggle_bookmark(
            user_id=123,
            file_id="file123",
            file_name="test.py",
            file_path="/test.py",
            line_number=42
        )
        
        self.assertFalse(result["ok"])
        self.assertEqual(result["action"], "error")
        
        # Check that error was logged
        mock_logger.error.assert_called()


def run_tests():
    """Run all tests"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestFileBookmarkModel))
    suite.addTests(loader.loadTestsFromTestCase(TestBookmarksManager))
    suite.addTests(loader.loadTestsFromTestCase(TestSyncFunctionality))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
