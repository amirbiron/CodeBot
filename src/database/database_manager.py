import sqlite3
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path: str = "save_me_bot.db"):
        """אתחול מסד הנתונים"""
        self.db_path = db_path
        self.init_database()
    
    def init_database(self) -> None:
        """יצירת טבלאות מסד הנתונים"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # טבלת פריטים שמורים
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS saved_items (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        category TEXT NOT NULL,
                        subject TEXT NOT NULL,
                        content_type TEXT NOT NULL,
                        content TEXT DEFAULT '',
                        file_id TEXT DEFAULT '',
                        file_name TEXT DEFAULT '',
                        caption TEXT DEFAULT '',
                        note TEXT DEFAULT '',
                        is_pinned BOOLEAN DEFAULT FALSE,
                        reminder_at DATETIME NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # אינדקס לחיפוש מהיר
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_user_category 
                    ON saved_items(user_id, category)
                ''')
                
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_user_search 
                    ON saved_items(user_id, subject, content)
                ''')
                
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_reminder 
                    ON saved_items(reminder_at) 
                    WHERE reminder_at IS NOT NULL
                ''')
                
                conn.commit()
                logger.info("Database initialized successfully")
                
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            raise
    
    def save_item(self, user_id: int, category: str, subject: str, 
                  content_type: str, content: str = '', file_id: str = '', 
                  file_name: str = '', caption: str = '') -> int:
        """שמירת פריט חדש"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    INSERT INTO saved_items 
                    (user_id, category, subject, content_type, content, 
                     file_id, file_name, caption)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (user_id, category, subject, content_type, content, 
                      file_id, file_name, caption))
                
                item_id = cursor.lastrowid
                conn.commit()
                
                logger.info(f"Item saved successfully for user {user_id}, ID: {item_id}")
                return item_id
                
        except Exception as e:
            logger.error(f"Error saving item: {e}")
            raise
    
    def get_item(self, item_id: int) -> Optional[Dict[str, Any]]:
        """קבלת פריט לפי ID"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                cursor.execute('''
                    SELECT * FROM saved_items WHERE id = ?
                ''', (item_id,))
                
                row = cursor.fetchone()
                return dict(row) if row else None
                
        except Exception as e:
            logger.error(f"Error getting item {item_id}: {e}")
            return None
    
    def get_user_categories(self, user_id: int) -> List[str]:
        """קבלת רשימת קטגוריות של משתמש"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    SELECT DISTINCT category 
                    FROM saved_items 
                    WHERE user_id = ? 
                    ORDER BY category
                ''', (user_id,))
                
                return [row[0] for row in cursor.fetchall()]
                
        except Exception as e:
            logger.error(f"Error getting categories for user {user_id}: {e}")
            return []
    
    def get_category_count(self, user_id: int, category: str) -> int:
        """קבלת מספר פריטים בקטגוריה"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    SELECT COUNT(*) 
                    FROM saved_items 
                    WHERE user_id = ? AND category = ?
                ''', (user_id, category))
                
                return cursor.fetchone()[0]
                
        except Exception as e:
            logger.error(f"Error getting category count: {e}")
            return 0
    
    def get_category_items(self, user_id: int, category: str) -> List[Dict[str, Any]]:
        """קבלת פריטים בקטגוריה (קבועים בראש)"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                cursor.execute('''
                    SELECT * FROM saved_items 
                    WHERE user_id = ? AND category = ?
                    ORDER BY is_pinned DESC, created_at DESC
                ''', (user_id, category))
                
                return [dict(row) for row in cursor.fetchall()]
                
        except Exception as e:
            logger.error(f"Error getting category items: {e}")
            return []
    
    def search_items(self, user_id: int, query: str) -> List[Dict[str, Any]]:
        """חיפוש פריטים"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                search_query = f"%{query}%"
                
                cursor.execute('''
                    SELECT * FROM saved_items 
                    WHERE user_id = ? AND (
                        category LIKE ? OR 
                        subject LIKE ? OR 
                        content LIKE ? OR 
                        caption LIKE ? OR
                        note LIKE ?
                    )
                    ORDER BY is_pinned DESC, created_at DESC
                    LIMIT 50
                ''', (user_id, search_query, search_query, search_query, 
                      search_query, search_query))
                
                return [dict(row) for row in cursor.fetchall()]
                
        except Exception as e:
            logger.error(f"Error searching items: {e}")
            return []
    
    def toggle_pin(self, item_id: int) -> bool:
        """החלפת מצב קיבוע פריט"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # קבלת מצב נוכחי
                cursor.execute('SELECT is_pinned FROM saved_items WHERE id = ?', (item_id,))
                row = cursor.fetchone()
                
                if not row:
                    return False
                
                new_pinned = not row[0]
                
                cursor.execute('''
                    UPDATE saved_items 
                    SET is_pinned = ?, updated_at = CURRENT_TIMESTAMP 
                    WHERE id = ?
                ''', (new_pinned, item_id))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"Error toggling pin for item {item_id}: {e}")
            return False
    
    def set_reminder(self, item_id: int, reminder_time: datetime) -> bool:
        """קביעת תזכורת לפריט"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    UPDATE saved_items 
                    SET reminder_at = ?, updated_at = CURRENT_TIMESTAMP 
                    WHERE id = ?
                ''', (reminder_time.isoformat(), item_id))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"Error setting reminder for item {item_id}: {e}")
            return False
    
    def update_content(self, item_id: int, content_type: str, content: str = '', 
                      file_id: str = '', file_name: str = '', caption: str = '') -> bool:
        """עדכון תוכן פריט"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    UPDATE saved_items 
                    SET content_type = ?, content = ?, file_id = ?, 
                        file_name = ?, caption = ?, updated_at = CURRENT_TIMESTAMP 
                    WHERE id = ?
                ''', (content_type, content, file_id, file_name, caption, item_id))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"Error updating content for item {item_id}: {e}")
            return False
    
    def update_subject(self, item_id: int, subject: str) -> bool:
        """עדכון נושא הפריט"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE saved_items 
                    SET subject = ?, updated_at = CURRENT_TIMESTAMP 
                    WHERE id = ?
                ''', (subject, item_id))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error updating subject for item {item_id}: {e}")
            return False
    
    def update_note(self, item_id: int, note: str) -> bool:
        """עדכון הערה לפריט"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    UPDATE saved_items 
                    SET note = ?, updated_at = CURRENT_TIMESTAMP 
                    WHERE id = ?
                ''', (note, item_id))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"Error updating note for item {item_id}: {e}")
            return False
    
    def delete_item(self, item_id: int) -> bool:
        """מחיקת פריט"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute('DELETE FROM saved_items WHERE id = ?', (item_id,))
                conn.commit()
                
                return cursor.rowcount > 0
                
        except Exception as e:
            logger.error(f"Error deleting item {item_id}: {e}")
            return False
    
    def delete_note(self, item_id: int) -> bool:
        """מחיקת הערה מפריט"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    UPDATE saved_items 
                    SET note = '', updated_at = CURRENT_TIMESTAMP 
                    WHERE id = ?
                ''', (item_id,))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"Error deleting note for item {item_id}: {e}")
            return False
    
    def get_pending_reminders(self) -> List[Dict[str, Any]]:
        """קבלת תזכורות ממתינות"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                now = datetime.now().isoformat()
                
                cursor.execute('''
                    SELECT * FROM saved_items 
                    WHERE reminder_at IS NOT NULL AND reminder_at <= ?
                ''', (now,))
                
                return [dict(row) for row in cursor.fetchall()]
                
        except Exception as e:
            logger.error(f"Error getting pending reminders: {e}")
            return []
    
    def clear_reminder(self, item_id: int) -> bool:
        """ניקוי תזכורת לאחר שליחה"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    UPDATE saved_items 
                    SET reminder_at = NULL, updated_at = CURRENT_TIMESTAMP 
                    WHERE id = ?
                ''', (item_id,))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"Error clearing reminder for item {item_id}: {e}")
            return False
    
    def get_user_stats(self, user_id: int) -> Dict[str, Any]:
        """קבלת סטטיסטיקות משתמש"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # סה""" פריטים
                cursor.execute('SELECT COUNT(*) FROM saved_items WHERE user_id = ?', (user_id,))
                total_items = cursor.fetchone()[0]

                # פריטים קבועים
                cursor.execute('SELECT COUNT(*) FROM saved_items WHERE user_id = ? AND is_pinned = 1', (user_id,))
                pinned_items = cursor.fetchone()[0]

                # סה""" קטגוריות
                cursor.execute('SELECT COUNT(DISTINCT category) FROM saved_items WHERE user_id = ?', (user_id,))
                total_categories = cursor.fetchone()[0]

                # תזכורות פעילות
                cursor.execute('SELECT COUNT(*) FROM saved_items WHERE user_id = ? AND reminder_at IS NOT NULL', (user_id,))
                active_reminders = cursor.fetchone()[0]

                # פריטים עם הערות
                cursor.execute('SELECT COUNT(*) FROM saved_items WHERE user_id = ? AND note != ""', (user_id,))
                items_with_notes = cursor.fetchone()[0]

                return {
                    'total_items': total_items,
                    'pinned_items': pinned_items,
                    'total_categories': total_categories,
                    'active_reminders': active_reminders,
                    'items_with_notes': items_with_notes
                }

        except Exception as e:
            logger.error(f"Error getting user stats: {e}")
            return {}

    def export_user_data(self, user_id: int) -> List[Dict[str, Any]]:
        """ייצוא נתוני משתמש"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                cursor.execute('''
                    SELECT * FROM saved_items 
                    WHERE user_id = ?
                    ORDER BY category, created_at
                ''', (user_id,))

                return [dict(row) for row in cursor.fetchall()]

        except Exception as e:
            logger.error(f"Error exporting user data: {e}")
            return []

    def cleanup_old_reminders(self, days_old: int = 7) -> int:
        """ניקוי תזכורות ישנות"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                cutoff_date = datetime.now() - timedelta(days=days_old)

                cursor.execute('''
                    UPDATE saved_items 
                    SET reminder_at = NULL 
                    WHERE reminder_at IS NOT NULL AND reminder_at < ?
                ''', (cutoff_date.isoformat(),))

                conn.commit()
                return cursor.rowcount

        except Exception as e:
            logger.error(f"Error cleaning up old reminders: {e}")
            return 0