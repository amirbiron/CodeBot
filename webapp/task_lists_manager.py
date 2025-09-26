#!/usr/bin/env python3
"""
Task Lists Manager for Code Keeper WebApp
ניהול ושמירת מצב Task Lists במסד הנתונים
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from pymongo import MongoClient
from bson import ObjectId


class TaskListsManager:
    """מנהל Task Lists עם סנכרון למסד נתונים"""
    
    def __init__(self, db):
        """
        אתחול המנהל
        
        Args:
            db: חיבור למסד נתונים MongoDB
        """
        self.db = db
        self.collection = db.task_lists
        
        # יצירת אינדקסים
        try:
            self.collection.create_index([
                ('user_id', 1),
                ('file_id', 1),
                ('task_id', 1)
            ], unique=True)
            self.collection.create_index('updated_at')
        except Exception:
            pass
    
    def get_task_states(self, user_id: int, file_id: str) -> Dict[str, bool]:
        """
        קבלת מצב כל ה-tasks עבור קובץ מסוים
        
        Returns:
            מילון של task_id -> checked status
        """
        try:
            tasks = self.collection.find({
                'user_id': user_id,
                'file_id': file_id
            })
            
            return {
                task['task_id']: task.get('checked', False)
                for task in tasks
            }
        except Exception as e:
            print(f"Error getting task states: {e}")
            return {}
    
    def update_task_state(self, user_id: int, file_id: str, task_id: str, 
                         checked: bool, task_text: str = "") -> bool:
        """
        עדכון מצב של task בודד
        
        Args:
            user_id: מזהה המשתמש
            file_id: מזהה הקובץ
            task_id: מזהה ה-task (hash של התוכן)
            checked: האם ה-task מסומן
            task_text: טקסט ה-task (אופציונלי)
        
        Returns:
            True אם העדכון הצליח
        """
        try:
            now = datetime.now(timezone.utc)
            
            result = self.collection.update_one(
                {
                    'user_id': user_id,
                    'file_id': file_id,
                    'task_id': task_id
                },
                {
                    '$set': {
                        'checked': checked,
                        'updated_at': now,
                        'task_text': task_text
                    },
                    '$setOnInsert': {
                        'created_at': now
                    }
                },
                upsert=True
            )
            
            return result.acknowledged
        except Exception as e:
            print(f"Error updating task state: {e}")
            return False
    
    def bulk_update_tasks(self, user_id: int, file_id: str, 
                          tasks: List[Dict[str, Any]]) -> bool:
        """
        עדכון מרובה של tasks
        
        Args:
            user_id: מזהה המשתמש
            file_id: מזהה הקובץ
            tasks: רשימת tasks עם task_id, checked, text
        
        Returns:
            True אם העדכון הצליח
        """
        try:
            now = datetime.now(timezone.utc)
            operations = []
            
            for task in tasks:
                operations.append({
                    'updateOne': {
                        'filter': {
                            'user_id': user_id,
                            'file_id': file_id,
                            'task_id': task['task_id']
                        },
                        'update': {
                            '$set': {
                                'checked': task.get('checked', False),
                                'task_text': task.get('text', ''),
                                'updated_at': now
                            },
                            '$setOnInsert': {
                                'created_at': now
                            }
                        },
                        'upsert': True
                    }
                })
            
            if operations:
                result = self.collection.bulk_write(operations)
                return result.acknowledged
            
            return True
        except Exception as e:
            print(f"Error bulk updating tasks: {e}")
            return False
    
    def delete_file_tasks(self, user_id: int, file_id: str) -> bool:
        """
        מחיקת כל ה-tasks של קובץ
        
        Args:
            user_id: מזהה המשתמש
            file_id: מזהה הקובץ
        
        Returns:
            True אם המחיקה הצליחה
        """
        try:
            result = self.collection.delete_many({
                'user_id': user_id,
                'file_id': file_id
            })
            return result.acknowledged
        except Exception as e:
            print(f"Error deleting file tasks: {e}")
            return False
    
    def get_user_statistics(self, user_id: int) -> Dict[str, Any]:
        """
        קבלת סטטיסטיקות task lists של משתמש
        
        Returns:
            מילון עם סטטיסטיקות
        """
        try:
            pipeline = [
                {'$match': {'user_id': user_id}},
                {'$group': {
                    '_id': None,
                    'total_tasks': {'$sum': 1},
                    'completed_tasks': {
                        '$sum': {'$cond': ['$checked', 1, 0]}
                    },
                    'files_count': {'$addToSet': '$file_id'}
                }},
                {'$project': {
                    'total_tasks': 1,
                    'completed_tasks': 1,
                    'pending_tasks': {
                        '$subtract': ['$total_tasks', '$completed_tasks']
                    },
                    'completion_rate': {
                        '$cond': {
                            'if': {'$eq': ['$total_tasks', 0]},
                            'then': 0,
                            'else': {
                                '$multiply': [
                                    {'$divide': ['$completed_tasks', '$total_tasks']},
                                    100
                                ]
                            }
                        }
                    },
                    'files_with_tasks': {'$size': '$files_count'}
                }}
            ]
            
            result = list(self.collection.aggregate(pipeline))
            
            if result:
                stats = result[0]
                stats.pop('_id', None)
                return stats
            
            return {
                'total_tasks': 0,
                'completed_tasks': 0,
                'pending_tasks': 0,
                'completion_rate': 0,
                'files_with_tasks': 0
            }
        except Exception as e:
            print(f"Error getting user statistics: {e}")
            return {
                'total_tasks': 0,
                'completed_tasks': 0,
                'pending_tasks': 0,
                'completion_rate': 0,
                'files_with_tasks': 0
            }
    
    @staticmethod
    def generate_task_id(text: str) -> str:
        """
        יצירת מזהה ייחודי ל-task על בסיס התוכן
        
        Args:
            text: טקסט ה-task
        
        Returns:
            מזהה hash קצר
        """
        return hashlib.md5(text.encode()).hexdigest()[:8]