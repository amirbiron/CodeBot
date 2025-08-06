#!/usr/bin/env python3
"""
Test for MongoDB lock mechanism to ensure it works without redundant _id index creation.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
import sys
import os
from datetime import datetime, timezone, timedelta

# Add the parent directory to the path so we can import from main
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class TestMongoLock(unittest.TestCase):
    """Test the MongoDB lock mechanism"""
    
    def setUp(self):
        """Set up test fixtures"""
        # Mock the database components to avoid needing real MongoDB
        self.mock_collection = MagicMock()
        self.mock_db = MagicMock()
        self.mock_client = Mock()
        self.mock_client.get_default_database.return_value = self.mock_db
        self.mock_db.__getitem__.return_value = self.mock_collection
        
    @patch('main.db')
    @patch('main.os.getpid')
    def test_manage_mongo_lock_no_existing_lock(self, mock_getpid, mock_db):
        """Test acquiring a new lock when no existing lock exists"""
        # Arrange
        mock_getpid.return_value = 12345
        mock_db.client = self.mock_client
        self.mock_collection.find_one.return_value = None  # No existing lock
        
        # Import the function after mocking
        from main import manage_mongo_lock
        
        # Act - this should not raise an exception
        try:
            manage_mongo_lock()
            success = True
        except Exception as e:
            success = False
            error = str(e)
        
        # Assert
        self.assertTrue(success, f"manage_mongo_lock() should not raise an exception, but got: {error if not success else ''}")
        
        # Verify that no index creation was attempted (the problematic line was removed)
        self.mock_collection.create_index.assert_not_called()
        
        # Verify that find_one was called to check for existing lock
        self.mock_collection.find_one.assert_called_once()
        
        # Verify that insert_one was called to create the lock
        self.mock_collection.insert_one.assert_called_once()
        
    @patch('main.db')
    @patch('main.os.getpid')
    def test_manage_mongo_lock_stale_lock_takeover(self, mock_getpid, mock_db):
        """Test taking over a stale lock"""
        # Arrange
        mock_getpid.return_value = 12345
        mock_db.client = self.mock_client
        
        # Create a stale lock (older than LOCK_TIMEOUT_MINUTES)
        old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        existing_lock = {
            "_id": "code_keeper_bot_lock",
            "pid": 99999,
            "timestamp": old_time
        }
        self.mock_collection.find_one.return_value = existing_lock
        
        # Import the function after mocking
        from main import manage_mongo_lock
        
        # Act
        try:
            manage_mongo_lock()
            success = True
        except Exception as e:
            success = False
            error = str(e)
        
        # Assert
        self.assertTrue(success, f"manage_mongo_lock() should not raise an exception, but got: {error if not success else ''}")
        
        # Verify that no index creation was attempted
        self.mock_collection.create_index.assert_not_called()
        
        # Verify that update_one was called to take over the stale lock
        self.mock_collection.update_one.assert_called_once()
        
    @patch('main.db')
    @patch('main.os.getpid') 
    @patch('main.sys.exit')
    def test_manage_mongo_lock_active_lock_exits(self, mock_exit, mock_getpid, mock_db):
        """Test that the function exits when there's an active lock"""
        # Arrange
        mock_getpid.return_value = 12345
        mock_db.client = self.mock_client
        
        # Create an active lock (recent timestamp)
        recent_time = datetime.now(timezone.utc) - timedelta(minutes=1)
        existing_lock = {
            "_id": "code_keeper_bot_lock", 
            "pid": 99999,
            "timestamp": recent_time
        }
        self.mock_collection.find_one.return_value = existing_lock
        
        # Import the function after mocking
        from main import manage_mongo_lock
        
        # Act
        manage_mongo_lock()
        
        # Assert
        # Should have called sys.exit(0) due to active lock
        mock_exit.assert_called_once_with(0)
        
        # Verify that no index creation was attempted
        self.mock_collection.create_index.assert_not_called()


if __name__ == '__main__':
    unittest.main()