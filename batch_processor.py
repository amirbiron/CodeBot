"""
מעבד Batch לעיבוד מרובה קבצים
Batch Processor for Multiple Files
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from database import db
from code_processor import code_processor
from cache_manager import cache
from html import escape as html_escape

logger = logging.getLogger(__name__)

@dataclass
class BatchJob:
    """עבודת batch"""
    job_id: str
    user_id: int
    operation: str
    files: List[str]
    status: str = "pending"  # pending, running, completed, failed
    progress: int = 0
    total: int = 0
    results: Dict[str, Any] = None
    error_message: str = ""
    start_time: float = 0
    end_time: float = 0
    
    def __post_init__(self):
        if self.results is None:
            self.results = {}
        if self.total == 0:
            self.total = len(self.files)

class BatchProcessor:
    """מעבד batch לפעולות על מרובה קבצים"""
    
    def __init__(self):
        self.max_workers = 4  # מספר threads מקסימלי
        self.max_concurrent_jobs = 3  # מספר עבודות batch בו-זמנית
        self.active_jobs: Dict[str, BatchJob] = {}
        self.job_counter = 0
    
    def create_job(self, user_id: int, operation: str, files: List[str]) -> str:
        """יצירת עבודת batch חדשה"""
        self.job_counter += 1
        job_id = f"batch_{user_id}_{self.job_counter}_{int(time.time())}"
        
        job = BatchJob(
            job_id=job_id,
            user_id=user_id,
            operation=operation,
            files=files
        )
        
        self.active_jobs[job_id] = job
        logger.info(f"נוצרה עבודת batch: {job_id} עם {len(files)} קבצים")
        
        return job_id
    
    async def process_files_batch(self, job_id: str, operation_func: Callable, **kwargs) -> BatchJob:
        """עיבוד batch של קבצים"""
        if job_id not in self.active_jobs:
            raise ValueError(f"עבודת batch {job_id} לא נמצאה")
        
        job = self.active_jobs[job_id]
        job.status = "running"
        job.start_time = time.time()
        
        try:
            # עיבוד בparallel עם ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                # יצירת futures לכל קובץ
                future_to_file = {
                    executor.submit(operation_func, job.user_id, file_name, **kwargs): file_name
                    for file_name in job.files
                }
                
                # עיבוד התוצאות כשהן מוכנות
                for future in as_completed(future_to_file):
                    file_name = future_to_file[future]
                    
                    try:
                        result = future.result()
                        job.results[file_name] = {
                            'success': True,
                            'result': result
                        }
                    except Exception as e:
                        job.results[file_name] = {
                            'success': False,
                            'error': str(e)
                        }
                        logger.error(f"שגיאה בעיבוד {file_name}: {e}")
                    
                    # עדכון progress
                    job.progress += 1
                    logger.debug(f"Job {job_id}: {job.progress}/{job.total} completed")
            
            job.status = "completed"
            job.end_time = time.time()
            
            # חישוב סטטיסטיקות
            successful = sum(1 for r in job.results.values() if r['success'])
            failed = job.total - successful
            
            logger.info(f"עבודת batch {job_id} הושלמה: {successful} הצליחו, {failed} נכשלו")
            
        except Exception as e:
            job.status = "failed"
            job.error_message = str(e)
            job.end_time = time.time()
            logger.error(f"עבודת batch {job_id} נכשלה: {e}")
        
        return job
    
    async def analyze_files_batch(self, user_id: int, file_names: List[str]) -> str:
        """ניתוח batch של קבצים"""
        job_id = self.create_job(user_id, "analyze", file_names)
        
        def analyze_single_file(user_id: int, file_name: str) -> Dict[str, Any]:
            """ניתוח קובץ יחיד"""
            try:
                file_data = db.get_latest_version(user_id, file_name)
                if not file_data:
                    return {'error': 'קובץ לא נמצא'}
                
                code = file_data['code']
                language = file_data['programming_language']
                
                # ניתוח הקוד
                analysis = code_processor.analyze_code(code, language)
                
                return {
                    'lines': len(code.split('\n')),
                    'chars': len(code),
                    'language': language,
                    'analysis': analysis
                }
                
            except Exception as e:
                return {'error': str(e)}
        
        await self.process_files_batch(job_id, analyze_single_file)
        return job_id
    
    async def validate_files_batch(self, user_id: int, file_names: List[str]) -> str:
        """בדיקת תקינות batch של קבצים"""
        job_id = self.create_job(user_id, "validate", file_names)
        
        def validate_single_file(user_id: int, file_name: str) -> Dict[str, Any]:
            """בדיקת תקינות קובץ יחיד"""
            try:
                file_data = db.get_latest_version(user_id, file_name)
                if not file_data:
                    return {'error': 'קובץ לא נמצא'}
                
                code = file_data['code']
                language = file_data['programming_language']
                
                # בדיקת תקינות
                is_valid, error_msg, warnings = code_processor.validate_code_input(code, file_name, user_id)
                
                return {
                    'is_valid': is_valid,
                    'error_message': error_msg,
                    'warnings': warnings,
                    'language': language
                }
                
            except Exception as e:
                return {'error': str(e)}
        
        await self.process_files_batch(job_id, validate_single_file)
        return job_id
    
    async def export_files_batch(self, user_id: int, file_names: List[str], export_format: str = "zip") -> str:
        """ייצוא batch של קבצים"""
        job_id = self.create_job(user_id, "export", file_names)
        
        def export_single_file(user_id: int, file_name: str, format: str = "zip") -> Dict[str, Any]:
            """ייצוא קובץ יחיד"""
            try:
                file_data = db.get_latest_version(user_id, file_name)
                if not file_data:
                    return {'error': 'קובץ לא נמצא'}
                
                # הכנת הקובץ לייצוא
                return {
                    'file_name': file_name,
                    'content': file_data['code'],
                    'language': file_data['programming_language'],
                    'size': len(file_data['code'])
                }
                
            except Exception as e:
                return {'error': str(e)}
        
        await self.process_files_batch(job_id, export_single_file, format=export_format)
        return job_id
    
    def get_job_status(self, job_id: str) -> Optional[BatchJob]:
        """קבלת סטטוס עבודת batch"""
        return self.active_jobs.get(job_id)
    
    def cleanup_old_jobs(self, max_age_hours: int = 24):
        """ניקוי עבודות ישנות"""
        current_time = time.time()
        old_jobs = []
        
        for job_id, job in self.active_jobs.items():
            if job.end_time > 0:  # עבודה שהסתיימה
                age_hours = (current_time - job.end_time) / 3600
                if age_hours > max_age_hours:
                    old_jobs.append(job_id)
        
        for job_id in old_jobs:
            del self.active_jobs[job_id]
        
        if old_jobs:
            logger.info(f"נוקו {len(old_jobs)} עבודות batch ישנות")
    
    def format_job_summary(self, job: BatchJob) -> str:
        """פורמט סיכום עבודת batch"""
        try:
            duration = ""
            if job.end_time > 0:
                duration = f" ({job.end_time - job.start_time:.1f}s)"
            
            if job.status == "pending":
                return f"⏳ <b>עבודה ממתינה</b>\n📁 {job.total} קבצים לעיבוד"
            
            elif job.status == "running":
                progress_percent = (job.progress / job.total * 100) if job.total > 0 else 0
                progress_bar = "█" * int(progress_percent / 10) + "░" * (10 - int(progress_percent / 10))
                return (
                    f"⚡ <b>עבודה בעיבוד...</b>\n"
                    f"📊 {job.progress}/{job.total} ({progress_percent:.1f}%)\n"
                    f"[{progress_bar}]"
                )
            
            elif job.status == "completed":
                successful = sum(1 for r in job.results.values() if r.get('success', False))
                failed = job.total - successful
                
                status_emoji = "✅" if failed == 0 else "⚠️"
                
                return (
                    f"{status_emoji} <b>עבודה הושלמה</b>{duration}\n"
                    f"✅ הצליחו: {successful}\n"
                    f"❌ נכשלו: {failed}\n"
                    f"📁 סה\"כ: {job.total} קבצים"
                )
            
            elif job.status == "failed":
                return (
                    f"❌ <b>עבודה נכשלה</b>{duration}\n"
                    f"🚨 שגיאה: {html_escape(job.error_message)}\n"
                    f"📁 {job.total} קבצים"
                )
            
            return f"❓ סטטוס לא ידוע: {job.status}"
            
        except Exception as e:
            logger.error(f"שגיאה בפורמט סיכום job: {e}")
            return "❌ שגיאה בהצגת סיכום"

# יצירת instance גלובלי
batch_processor = BatchProcessor()