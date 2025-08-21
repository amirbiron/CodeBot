"""
מעבד Batch לעיבוד מרובה קבצים
Batch Processor for Multiple Files
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Callable, Any
import re
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from database import db
from code_processor import code_processor
from cache_manager import cache
from html import escape as html_escape
import tempfile
import subprocess
import os

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
        self.max_workers = 3  # מספר threads מקסימלי כדי למנוע "סיום מיידי" לא ריאלי
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
                        # קבע הצלחה לוגית לפי תוצאת הפונקציה (למשל is_valid)
                        success_flag = True
                        if isinstance(result, dict) and ('is_valid' in result):
                            success_flag = bool(result.get('is_valid'))
                        job.results[file_name] = {
                            'success': success_flag,
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
                    # הוספת דיליי קטן כדי לאפשר חוויית התקדמות אמיתית (ולא "סיים בשנייה")
                    # נמוך מספיק כדי לא לעכב משמעותית, אך יוצר תחושה ריאלית ב-UI
                    try:
                        time.sleep(0.05)
                    except Exception:
                        pass
            
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
                
                # ניתוח הקוד (עמוק יותר עבור קבצים גדולים)
                analysis = code_processor.analyze_code(code, language)
                # סימולציית זמן עיבוד ריאלי: 1ms לכל 500 תווים, עד 150ms
                try:
                    delay = min(max(len(code) / 500_000.0, 0.02), 0.15)
                    time.sleep(delay)
                except Exception:
                    pass
                
                return {
                    'lines': len(code.split('\n')),
                    'chars': len(code),
                    'language': language,
                    'analysis': analysis
                }
                
            except Exception as e:
                return {'error': str(e)}
        
        # הרצה ברקע כדי לא לחסום את הלולאה הראשית
        asyncio.create_task(self.process_files_batch(job_id, analyze_single_file))
        return job_id
    
    async def validate_files_batch(self, user_id: int, file_names: List[str], enable_external_tools: bool = True) -> str:
        """בדיקת תקינות batch של קבצים"""
        job_id = self.create_job(user_id, "validate", file_names)
        
        def _run_local_cmd(args_list, cwd: str, timeout_sec: int = 20) -> Dict[str, Any]:
            try:
                completed = subprocess.run(
                    args_list,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=timeout_sec
                )
                output = (completed.stdout or "") + (completed.stderr or "")
                return {"returncode": completed.returncode, "output": output.strip()}
            except subprocess.TimeoutExpired as e:
                return {"returncode": 124, "output": "Timeout"}
            except FileNotFoundError:
                return {"returncode": 127, "output": "Tool not installed"}
            except Exception as e:
                return {"returncode": 1, "output": str(e)}

        def _advanced_python_checks(temp_dir: str, filename: str) -> Dict[str, Any]:
            results: Dict[str, Any] = {}
            # Prefer project configs if present in temp_dir (copied beforehand)
            if enable_external_tools:
                results["flake8"] = _run_local_cmd(["flake8", filename], temp_dir)
                results["mypy"] = _run_local_cmd(["mypy", filename], temp_dir)
                results["bandit"] = _run_local_cmd(["bandit", "-q", "-r", filename], temp_dir)
                results["black"] = _run_local_cmd(["black", "--check", filename], temp_dir)
            return results

        def _copy_lint_configs(temp_dir: str) -> None:
            """Copy lint/type/security config files into temp_dir if they exist in project root."""
            project_root = os.getcwd()
            configs = [
                (os.path.join(project_root, ".flake8"), os.path.join(temp_dir, ".flake8")),
                (os.path.join(project_root, "pyproject.toml"), os.path.join(temp_dir, "pyproject.toml")),
                (os.path.join(project_root, "mypy.ini"), os.path.join(temp_dir, "mypy.ini")),
                (os.path.join(project_root, "bandit.yaml"), os.path.join(temp_dir, "bandit.yaml")),
                # JS/TS linters/formatters
                (os.path.join(project_root, ".eslintrc.json"), os.path.join(temp_dir, ".eslintrc.json")),
                (os.path.join(project_root, ".eslintrc.js"), os.path.join(temp_dir, ".eslintrc.js")),
                (os.path.join(project_root, "package.json"), os.path.join(temp_dir, "package.json")),
                (os.path.join(project_root, ".prettierrc"), os.path.join(temp_dir, ".prettierrc")),
                (os.path.join(project_root, "prettier.config.js"), os.path.join(temp_dir, "prettier.config.js")),
                (os.path.join(project_root, "tsconfig.json"), os.path.join(temp_dir, "tsconfig.json")),
                # YAML/Docker/Semgrep
                (os.path.join(project_root, ".yamllint"), os.path.join(temp_dir, ".yamllint")),
                (os.path.join(project_root, ".hadolint.yaml"), os.path.join(temp_dir, ".hadolint.yaml")),
                (os.path.join(project_root, ".semgrep.yml"), os.path.join(temp_dir, ".semgrep.yml")),
                (os.path.join(project_root, ".semgrep.yaml"), os.path.join(temp_dir, ".semgrep.yaml")),
            ]
            for src, dst in configs:
                try:
                    if os.path.isfile(src):
                        with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
                            fdst.write(fsrc.read())
                except Exception:
                    continue

        def _guess_extension(file_name: str, language: str) -> str:
            name = (file_name or "").lower()
            lang = (language or "").lower()
            # Prefer existing extension if present
            if "." in name:
                return name.rsplit(".", 1)[-1]
            if lang in ("python", "py"):
                return "py"
            if lang in ("javascript", "js"):
                return "js"
            if lang in ("typescript", "ts"):
                return "ts"
            if lang in ("bash", "shell", "sh"):
                return "sh"
            if lang in ("yaml", "yml"):
                return "yml"
            if lang in ("json",):
                return "json"
            if "dockerfile" in name:
                return "dockerfile"
            return "txt"

        def _secrets_scan(code: str) -> Dict[str, Any]:
            """Very lightweight secret detection with regex patterns."""
            patterns = {
                "aws_access_key": r"AKIA[0-9A-Z]{16}",
                "aws_secret_key": r"(?i)aws(.{0,20})?(secret|access)[=:].{0,3}([A-Za-z0-9/+=]{40})",
                "github_token": r"ghp_[A-Za-z0-9]{36}",
                "google_api_key": r"AIza[0-9A-Za-z\-_]{35}",
                "private_key": r"-----BEGIN (RSA|EC|DSA|OPENSSH) PRIVATE KEY-----",
            }
            findings = []
            for name, pat in patterns.items():
                try:
                    if re.search(pat, code):
                        findings.append(name)
                except re.error:
                    continue
            return {
                "returncode": 0 if not findings else 1,
                "output": ", ".join(findings) if findings else "no-secrets-found",
            }

        def validate_single_file(user_id: int, file_name: str) -> Dict[str, Any]:
            """בדיקת תקינות קובץ יחיד"""
            try:
                file_data = db.get_latest_version(user_id, file_name)
                if not file_data:
                    return {'error': 'קובץ לא נמצא'}
                
                code = file_data['code']
                language = file_data['programming_language']
                
                # בדיקת תקינות
                is_valid, cleaned_code, error_msg = code_processor.validate_code_input(code, file_name, user_id)
                result: Dict[str, Any] = {
                    'is_valid': is_valid,
                    'error_message': error_msg,
                    'cleaned_code': cleaned_code,
                    'original_length': len(code) if isinstance(code, str) else 0,
                    'cleaned_length': len(cleaned_code) if isinstance(cleaned_code, str) else 0,
                    'language': language,
                    'advanced_checks': {}
                }

                # בדיקות מתקדמות לפי שפה
                with tempfile.TemporaryDirectory(prefix="validate_") as temp_dir:
                    # קבע שם קובץ זמני לפי השפה/הסיומת
                    ext = _guess_extension(file_name or "file", language or "")
                    base_name = (file_name or f"file.{ext}").replace("/", "_")
                    if not base_name.lower().endswith(f".{ext}") and ext not in ("dockerfile"):
                        base_name = f"{base_name}.{ext}"
                    temp_file = os.path.join(temp_dir, base_name)
                    os.makedirs(os.path.dirname(temp_file), exist_ok=True)
                    with open(temp_file, 'w', encoding='utf-8') as f:
                        f.write(code)
                    _copy_lint_configs(temp_dir)

                    adv: Dict[str, Any] = {}

                    # Python specific
                    if (language or "").lower() == 'python' or temp_file.endswith('.py'):
                        adv.update(_advanced_python_checks(temp_dir, os.path.basename(temp_file)))
                        if enable_external_tools:
                            # pylint, isort, radon (optional)
                            adv["pylint"] = _run_local_cmd(["pylint", "-sn", os.path.basename(temp_file)], temp_dir)
                            adv["isort"] = _run_local_cmd(["isort", "--check-only", os.path.basename(temp_file)], temp_dir)
                            adv["radon_cc"] = _run_local_cmd(["radon", "cc", "-s", "-a", os.path.basename(temp_file)], temp_dir)
                            adv["radon_mi"] = _run_local_cmd(["radon", "mi", os.path.basename(temp_file)], temp_dir)

                    # JavaScript / TypeScript
                    if (temp_file.endswith('.js') or temp_file.endswith('.ts')) and enable_external_tools:
                        adv["eslint"] = _run_local_cmd(["eslint", "-f", "stylish", os.path.basename(temp_file)], temp_dir)
                        if temp_file.endswith('.ts'):
                            adv["tsc"] = _run_local_cmd(["tsc", "--noEmit", os.path.basename(temp_file)], temp_dir)
                        adv["prettier"] = _run_local_cmd(["prettier", "--check", os.path.basename(temp_file)], temp_dir)

                    # Shell scripts
                    if temp_file.endswith('.sh') and enable_external_tools:
                        adv["shellcheck"] = _run_local_cmd(["shellcheck", os.path.basename(temp_file)], temp_dir)

                    # YAML
                    if (temp_file.endswith('.yml') or temp_file.endswith('.yaml')) and enable_external_tools:
                        adv["yamllint"] = _run_local_cmd(["yamllint", os.path.basename(temp_file)], temp_dir)

                    # Dockerfile
                    if (ext == 'dockerfile' or os.path.basename(temp_file).lower() == 'dockerfile') and enable_external_tools:
                        adv["hadolint"] = _run_local_cmd(["hadolint", os.path.basename(temp_file)], temp_dir)

                    # JSON
                    if temp_file.endswith('.json') and enable_external_tools:
                        adv["jq"] = _run_local_cmd(["jq", "-e", ".", os.path.basename(temp_file)], temp_dir)

                    # Semgrep (generic SAST) - optional and quiet
                    if enable_external_tools:
                        adv["semgrep"] = _run_local_cmd(["semgrep", "--quiet", "--config", "auto", os.path.basename(temp_file)], temp_dir)

                    # Internal secrets scan (always available)
                    adv["secrets_scan"] = _secrets_scan(code)

                    result['advanced_checks'] = adv
                # סימולציית זמן עיבוד ריאלי
                try:
                    delay = min(max(len(code) / 400_000.0, 0.03), 0.2)
                    time.sleep(delay)
                except Exception:
                    pass

                return result
                
            except Exception as e:
                return {'error': str(e)}
        
        # הרצה ברקע כדי לא לחסום את הלולאה הראשית
        asyncio.create_task(self.process_files_batch(job_id, validate_single_file))
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
        
        # הרצה ברקע כדי לא לחסום את הלולאה הראשית
        asyncio.create_task(self.process_files_batch(job_id, export_single_file, format=export_format))
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