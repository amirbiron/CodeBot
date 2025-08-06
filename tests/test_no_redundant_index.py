#!/usr/bin/env python3
"""
Test to validate that the redundant _id index creation line has been removed.
"""

import unittest
import os
import re

class TestNoRedundantIndexCreation(unittest.TestCase):
    """Test that the problematic line has been removed from main.py"""
    
    def test_no_redundant_id_index_creation(self):
        """Test that line creating redundant unique index on _id has been removed"""
        # Read the main.py file
        main_py_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'main.py')
        
        with open(main_py_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that the problematic line is not present
        # The problematic pattern would be something like: create_index("_id", unique=True)
        problematic_patterns = [
            r'create_index\s*\(\s*["\']_id["\']\s*,\s*unique\s*=\s*True\s*\)',
            r'create_index\s*\(\s*["\']_id["\']\s*,.*unique.*=.*True',
            r'lock_collection\.create_index\s*\(\s*["\']_id["\'].*unique.*True'
        ]
        
        for pattern in problematic_patterns:
            matches = re.search(pattern, content, re.IGNORECASE)
            self.assertIsNone(matches, 
                f"Found problematic index creation pattern: {pattern}. "
                f"This should have been removed to fix the MongoDB error.")
    
    def test_manage_mongo_lock_function_exists(self):
        """Test that the manage_mongo_lock function still exists and is properly structured"""
        main_py_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'main.py')
        
        with open(main_py_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that the function still exists
        self.assertIn('def manage_mongo_lock()', content, 
                      "The manage_mongo_lock function should still exist")
        
        # Check that it still gets the lock collection
        self.assertIn('lock_collection = get_lock_collection()', content,
                      "The function should still get the lock collection")
        
        # Check that it still has the DuplicateKeyError handling
        self.assertIn('DuplicateKeyError', content,
                      "The function should still handle DuplicateKeyError")
        
        # Check that it still tries to insert the lock document
        self.assertIn('insert_one', content,
                      "The function should still insert lock documents")

if __name__ == '__main__':
    unittest.main()