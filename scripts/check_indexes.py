#!/usr/bin/env python3
"""
סקריפט לבדיקת מצב אינדקסים ב-code_snippets collection.
"""
import sys
import os

# הוספת הנתיב של הפרויקט
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from database.manager import DatabaseManager
except ImportError as e:
    print(f"Error importing DatabaseManager: {e}")
    sys.exit(1)

def main():
    try:
        print("Connecting to MongoDB...")
        db_manager = DatabaseManager()
        db = db_manager.db
        
        if db is None:
            print("ERROR: db is None - could not connect to MongoDB")
            sys.exit(1)
            
        collection = db['code_snippets']
        
        print("\n--- Current Indexes on code_snippets ---")
        try:
            indexes = list(collection.list_indexes())
            if not indexes:
                print("No indexes found (or stub collection)")
            else:
                for index in indexes:
                    print(f"  - {index.get('name', 'N/A')}: {index.get('key', {})}")
                    
                # בדיקה ספציפית ל-active_recent_idx
                active_recent_exists = any(idx.get('name') == 'active_recent_idx' for idx in indexes)
                print(f"\n✅ active_recent_idx exists: {active_recent_exists}")
                
                if active_recent_exists:
                    idx_info = next((idx for idx in indexes if idx.get('name') == 'active_recent_idx'), None)
                    if idx_info:
                        print(f"   Keys: {idx_info.get('key', {})}")
        except Exception as e:
            print(f"Error listing indexes: {e}")
        
        print("\n--- Current Operations (Is Index Building?) ---")
        try:
            # בדיקה אם יש בניית אינדקס שרצה כרגע
            current_ops = db.current_op()
            found_ops = False
            for op in current_ops.get('inprog', []):
                cmd = op.get('command', {})
                if 'createIndexes' in cmd or 'msg' in op:
                    found_ops = True
                    print(f"  Operation: {op.get('desc', 'N/A')}")
                    print(f"  Message: {op.get('msg', 'N/A')}")
                    print(f"  Progress: {op.get('progress', 'N/A')}")
                    print()
            if not found_ops:
                print("  No index building operations in progress")
        except Exception as e:
            print(f"Error checking current operations: {e}")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
