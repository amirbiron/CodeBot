"""
ניהול קבצים מתקדם - גרסאות, גיבויים, ארכיון ועוד
Advanced File Management - Versioning, Backups, Archive and more
"""

import asyncio
import difflib
import hashlib
import json
import logging
import os
import shutil
import tarfile
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional, Tuple

from code_processor import code_processor
from config import config
from database import CodeSnippet, db

logger = logging.getLogger(__name__)


@dataclass
class FileVersion:
    """ייצוג גרסת קובץ"""

    version: int
    content: str
    hash: str
    size: int
    created_at: datetime
    changes_summary: str = ""
    author_note: str = ""


@dataclass
class FileDiff:
    """ייצוג הבדלים בין גרסאות"""

    from_version: int
    to_version: int
    added_lines: int
    removed_lines: int
    modified_lines: int
    diff_text: str
    similarity_percentage: float


@dataclass
class BackupInfo:
    """מידע על גיבוי"""

    backup_id: str
    user_id: int
    created_at: datetime
    file_count: int
    total_size: int
    backup_type: str  # "manual", "automatic", "scheduled"
    status: str  # "completed", "in_progress", "failed"
    file_path: Optional[str] = None


class VersionManager:
    """מנהל גרסאות מתקדם"""

    def __init__(self):
        self.max_versions_per_file = 50
        self.auto_cleanup_days = 90

    def create_version(
        self, user_id: int, file_name: str, content: str, author_note: str = ""
    ) -> Optional[FileVersion]:
        """יצירת גרסה חדשה"""

        try:
            # קבלת הגרסה האחרונה
            latest = db.get_latest_version(user_id, file_name)
            new_version = 1 if not latest else latest["version"] + 1

            # חישוב hash
            content_hash = hashlib.sha256(content.encode()).hexdigest()

            # בדיקה אם התוכן זהה לגרסה הקיימת
            if latest and latest.get("hash") == content_hash:
                logger.info(f"תוכן זהה לגרסה קיימת: {file_name}")
                return None

            # יצירת סיכום שינויים
            changes_summary = ""
            if latest:
                changes_summary = self._generate_changes_summary(
                    latest["code"], content
                )

            # יצירת אובייקט גרסה
            version = FileVersion(
                version=new_version,
                content=content,
                hash=content_hash,
                size=len(content),
                created_at=datetime.now(),
                changes_summary=changes_summary,
                author_note=author_note,
            )

            logger.info(f"נוצרה גרסה {new_version} עבור {file_name}")
            return version

        except Exception as e:
            logger.error(f"שגיאה ביצירת גרסה: {e}")
            return None

    def _generate_changes_summary(self, old_content: str, new_content: str) -> str:
        """יצירת סיכום שינויים בין גרסאות"""

        old_lines = old_content.splitlines()
        new_lines = new_content.splitlines()

        differ = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile="version_old",
            tofile="version_new",
            lineterm="",
        )

        diff_lines = list(differ)

        added = len([line for line in diff_lines if line.startswith("+")])
        removed = len([line for line in diff_lines if line.startswith("-")])

        if added == 0 and removed == 0:
            return "ללא שינויים"

        summary = []
        if added > 0:
            summary.append(f"+{added} שורות")
        if removed > 0:
            summary.append(f"-{removed} שורות")

        return ", ".join(summary)

    def compare_versions(
        self, user_id: int, file_name: str, version1: int, version2: int
    ) -> Optional[FileDiff]:
        """השוואת שתי גרסאות"""

        try:
            versions = db.get_all_versions(user_id, file_name)

            v1_data = next((v for v in versions if v["version"] == version1), None)
            v2_data = next((v for v in versions if v["version"] == version2), None)

            if not v1_data or not v2_data:
                logger.error(f"לא נמצאו גרסאות {version1}, {version2} עבור {file_name}")
                return None

            content1 = v1_data["code"]
            content2 = v2_data["code"]

            # יצירת diff
            lines1 = content1.splitlines(keepends=True)
            lines2 = content2.splitlines(keepends=True)

            diff = difflib.unified_diff(
                lines1,
                lines2,
                fromfile=f"version_{version1}",
                tofile=f"version_{version2}",
                lineterm="",
            )

            diff_text = "\n".join(diff)

            # חישוב סטטיסטיקות
            diff_lines = diff_text.split("\n")
            added_lines = len([line for line in diff_lines if line.startswith("+")])
            removed_lines = len([line for line in diff_lines if line.startswith("-")])

            # חישוב דמיון
            matcher = difflib.SequenceMatcher(None, content1, content2)
            similarity = matcher.ratio() * 100

            file_diff = FileDiff(
                from_version=version1,
                to_version=version2,
                added_lines=added_lines,
                removed_lines=removed_lines,
                modified_lines=max(added_lines, removed_lines),
                diff_text=diff_text,
                similarity_percentage=similarity,
            )

            logger.info(f"הושוו גרסאות {version1}-{version2} של {file_name}")
            return file_diff

        except Exception as e:
            logger.error(f"שגיאה בהשוואת גרסאות: {e}")
            return None

    def cleanup_old_versions(self, user_id: int, file_name: str = None) -> int:
        """ניקוי גרסאות ישנות"""

        try:
            cleaned_count = 0

            if file_name:
                # ניקוי עבור קובץ ספציפי
                versions = db.get_all_versions(user_id, file_name)
                if len(versions) > self.max_versions_per_file:
                    # שמירת הגרסאות החדשות ביותר
                    to_keep = versions[: self.max_versions_per_file]
                    to_remove = versions[self.max_versions_per_file :]

                    for version in to_remove:
                        # במציאות כאן היה מחיקת הגרסה מה-DB
                        cleaned_count += 1
            else:
                # ניקוי כללי של גרסאות ישנות
                cutoff_date = datetime.now() - timedelta(days=self.auto_cleanup_days)
                # כאן היה שאילתת מחיקה למסד הנתונים
                pass

            if cleaned_count > 0:
                logger.info(f"נוקו {cleaned_count} גרסאות ישנות")

            return cleaned_count

        except Exception as e:
            logger.error(f"שגיאה בניקוי גרסאות: {e}")
            return 0


class BackupManager:
    """מנהל גיבויים"""

    def __init__(self):
        self.backup_dir = Path(tempfile.gettempdir()) / "code_keeper_backups"
        self.backup_dir.mkdir(exist_ok=True)
        self.max_backup_size = 100 * 1024 * 1024  # 100MB

    async def create_backup(
        self, user_id: int, backup_type: str = "manual", include_versions: bool = True
    ) -> Optional[BackupInfo]:
        """יצירת גיבוי מלא"""

        try:
            backup_id = f"backup_{user_id}_{int(datetime.now().timestamp())}"
            backup_path = self.backup_dir / f"{backup_id}.zip"

            # קבלת כל הקבצים של המשתמש
            files = db.get_user_files(user_id, limit=1000)

            if not files:
                logger.warning(f"אין קבצים לגיבוי עבור משתמש {user_id}")
                return None

            total_size = 0
            file_count = 0

            # יצירת גיבוי
            with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zip_file:

                # הוספת מטאדטה
                metadata = {
                    "backup_id": backup_id,
                    "user_id": user_id,
                    "created_at": datetime.now().isoformat(),
                    "backup_type": backup_type,
                    "include_versions": include_versions,
                    "file_count": len(files),
                    "created_by": "Code Keeper Bot",
                }

                zip_file.writestr("metadata.json", json.dumps(metadata, indent=2))

                # הוספת קבצים
                for file_data in files:
                    file_name = file_data["file_name"]
                    content = file_data["code"]

                    # הוספת הגרסה הנוכחית
                    zip_file.writestr(f"current/{file_name}", content)
                    file_count += 1
                    total_size += len(content)

                    # הוספת כל הגרסאות אם נדרש
                    if include_versions:
                        versions = db.get_all_versions(user_id, file_name)

                        for version in versions[1:]:  # דלג על הגרסה הנוכחית
                            version_content = version["code"]
                            version_filename = (
                                f"versions/{file_name}/v{version['version']}.txt"
                            )
                            zip_file.writestr(version_filename, version_content)
                            total_size += len(version_content)

                    # בדיקת גודל מקסימלי
                    if total_size > self.max_backup_size:
                        logger.warning(f"גיבוי חרג מהגודל המקסימלי: {total_size}")
                        break

            backup_info = BackupInfo(
                backup_id=backup_id,
                user_id=user_id,
                created_at=datetime.now(),
                file_count=file_count,
                total_size=total_size,
                backup_type=backup_type,
                status="completed",
                file_path=str(backup_path),
            )

            logger.info(
                f"נוצר גיבוי: {backup_id} ({file_count} קבצים, {total_size} bytes)"
            )
            return backup_info

        except Exception as e:
            logger.error(f"שגיאה ביצירת גיבוי: {e}")
            return None

    def restore_from_backup(
        self, user_id: int, backup_path: str, overwrite: bool = False
    ) -> Dict[str, Any]:
        """שחזור מגיבוי"""

        try:
            results = {
                "restored_files": 0,
                "skipped_files": 0,
                "errors": [],
                "files": [],
            }

            if not os.path.exists(backup_path):
                results["errors"].append("קובץ הגיבוי לא נמצא")
                return results

            with zipfile.ZipFile(backup_path, "r") as zip_file:

                # קריאת מטאדטה
                try:
                    metadata_content = zip_file.read("metadata.json")
                    metadata = json.loads(metadata_content)

                    if metadata["user_id"] != user_id:
                        results["errors"].append("הגיבוי לא שייך למשתמש זה")
                        return results

                except KeyError:
                    results["errors"].append("גיבוי לא תקין - חסרה מטאדטה")
                    return results

                # שחזור קבצים נוכחיים
                current_files = [
                    name for name in zip_file.namelist() if name.startswith("current/")
                ]

                for file_path in current_files:
                    try:
                        file_name = file_path.replace("current/", "")
                        content = zip_file.read(file_path).decode("utf-8")

                        # בדיקה אם הקובץ קיים
                        existing = db.get_latest_version(user_id, file_name)

                        if existing and not overwrite:
                            results["skipped_files"] += 1
                            continue

                        # זיהוי שפה
                        language = code_processor.detect_language(content, file_name)

                        # יצירת קטע קוד חדש
                        snippet = CodeSnippet(
                            user_id=user_id,
                            file_name=file_name,
                            code=content,
                            programming_language=language,
                            description="שוחזר מגיבוי",
                        )

                        if db.save_code_snippet(snippet):
                            results["restored_files"] += 1
                            results["files"].append(file_name)
                        else:
                            results["errors"].append(f"שגיאה בשחזור {file_name}")

                    except Exception as e:
                        results["errors"].append(f"שגיאה בעיבוד {file_path}: {str(e)}")

            logger.info(f"שוחזרו {results['restored_files']} קבצים מגיבוי")
            return results

        except Exception as e:
            logger.error(f"שגיאה בשחזור מגיבוי: {e}")
            return {"restored_files": 0, "errors": [str(e)]}

    def list_backups(self, user_id: int) -> List[BackupInfo]:
        """רשימת גיבויים זמינים"""

        backups = []

        try:
            # חיפוש קבצי גיבוי
            pattern = f"backup_{user_id}_*.zip"

            for backup_file in self.backup_dir.glob(pattern):
                try:
                    # קריאת מטאדטה
                    with zipfile.ZipFile(backup_file, "r") as zip_file:
                        metadata_content = zip_file.read("metadata.json")
                        metadata = json.loads(metadata_content)

                        backup_info = BackupInfo(
                            backup_id=metadata["backup_id"],
                            user_id=metadata["user_id"],
                            created_at=datetime.fromisoformat(metadata["created_at"]),
                            file_count=metadata["file_count"],
                            total_size=backup_file.stat().st_size,
                            backup_type=metadata.get("backup_type", "unknown"),
                            status="completed",
                            file_path=str(backup_file),
                        )

                        backups.append(backup_info)

                except Exception as e:
                    logger.warning(f"שגיאה בקריאת גיבוי {backup_file}: {e}")
                    continue

            # מיון לפי תאריך יצירה
            backups.sort(key=lambda x: x.created_at, reverse=True)

        except Exception as e:
            logger.error(f"שגיאה ברשימת גיבויים: {e}")

        return backups

    def delete_backup(self, backup_id: str, user_id: int) -> bool:
        """מחיקת גיבוי"""

        try:
            backup_files = list(self.backup_dir.glob(f"{backup_id}.zip"))

            for backup_file in backup_files:
                # וידוא שהגיבוי שייך למשתמש
                with zipfile.ZipFile(backup_file, "r") as zip_file:
                    metadata_content = zip_file.read("metadata.json")
                    metadata = json.loads(metadata_content)

                    if metadata["user_id"] == user_id:
                        backup_file.unlink()
                        logger.info(f"נמחק גיבוי: {backup_id}")
                        return True

            logger.warning(f"גיבוי לא נמצא או לא שייך למשתמש: {backup_id}")
            return False

        except Exception as e:
            logger.error(f"שגיאה במחיקת גיבוי: {e}")
            return False


class FileExporter:
    """מייצא קבצים לפורמטים שונים"""

    def __init__(self):
        self.supported_formats = ["zip", "tar", "json", "html", "pdf"]

    async def export_files(
        self,
        user_id: int,
        file_names: List[str],
        export_format: str,
        options: Dict[str, Any] = None,
    ) -> Optional[bytes]:
        """ייצוא קבצים לפורמט נבחר"""

        if export_format not in self.supported_formats:
            logger.error(f"פורמט לא נתמך: {export_format}")
            return None

        if options is None:
            options = {}

        try:
            # קבלת הקבצים
            files_data = []
            for file_name in file_names:
                file_data = db.get_latest_version(user_id, file_name)
                if file_data:
                    files_data.append(file_data)

            if not files_data:
                logger.warning("אין קבצים לייצוא")
                return None

            # ייצוא לפי פורמט
            if export_format == "zip":
                return await self._export_zip(files_data, options)
            elif export_format == "json":
                return await self._export_json(files_data, options)
            elif export_format == "html":
                return await self._export_html(files_data, options)
            else:
                logger.error(f"ייצוא לפורמט {export_format} עדיין לא מוטמע")
                return None

        except Exception as e:
            logger.error(f"שגיאה בייצוא: {e}")
            return None

    async def _export_zip(self, files_data: List[Dict], options: Dict) -> bytes:
        """ייצוא כקובץ ZIP"""

        zip_buffer = BytesIO()

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:

            for file_data in files_data:
                file_name = file_data["file_name"]
                content = file_data["code"]

                # הוספת הקובץ ל-ZIP
                zip_file.writestr(file_name, content)

                # הוספת מידע נוסף אם נדרש
                if options.get("include_metadata", False):
                    metadata = {
                        "file_name": file_name,
                        "programming_language": file_data["programming_language"],
                        "created_at": file_data["created_at"].isoformat(),
                        "updated_at": file_data["updated_at"].isoformat(),
                        "version": file_data["version"],
                        "tags": file_data.get("tags", []),
                        "description": file_data.get("description", ""),
                    }

                    metadata_filename = f"{file_name}.metadata.json"
                    zip_file.writestr(metadata_filename, json.dumps(metadata, indent=2))

        return zip_buffer.getvalue()

    async def _export_json(self, files_data: List[Dict], options: Dict) -> bytes:
        """ייצוא כקובץ JSON"""

        export_data = {
            "export_info": {
                "created_at": datetime.now().isoformat(),
                "format": "json",
                "file_count": len(files_data),
                "exported_by": "Code Keeper Bot",
            },
            "files": [],
        }

        for file_data in files_data:
            file_export = {
                "file_name": file_data["file_name"],
                "code": file_data["code"],
                "programming_language": file_data["programming_language"],
                "created_at": file_data["created_at"].isoformat(),
                "updated_at": file_data["updated_at"].isoformat(),
                "version": file_data["version"],
                "tags": file_data.get("tags", []),
                "description": file_data.get("description", ""),
                "size": len(file_data["code"]),
            }

            # הוספת סטטיסטיקות אם נדרש
            if options.get("include_stats", False):
                stats = code_processor.get_code_stats(file_data["code"])
                file_export["stats"] = stats

            export_data["files"].append(file_export)

        json_content = json.dumps(export_data, ensure_ascii=False, indent=2)
        return json_content.encode("utf-8")

    async def _export_html(self, files_data: List[Dict], options: Dict) -> bytes:
        """ייצוא כדף HTML"""

        html_template = """
        <!DOCTYPE html>
        <html lang="he" dir="rtl">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Code Keeper - ייצוא קבצים</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 20px; }
                .file-container { margin-bottom: 30px; border: 1px solid #ddd; padding: 15px; }
                .file-header { background: #f5f5f5; padding: 10px; margin: -15px -15px 15px -15px; }
                .file-name { font-size: 18px; font-weight: bold; }
                .file-meta { color: #666; font-size: 14px; margin-top: 5px; }
                pre { background: #f8f8f8; padding: 15px; overflow-x: auto; }
                code { font-family: 'Courier New', monospace; }
                .tags { margin-top: 10px; }
                .tag { background: #e1f5fe; padding: 2px 8px; border-radius: 4px; font-size: 12px; margin-right: 5px; }
            </style>
        </head>
        <body>
            <h1>Code Keeper - ייצוא קבצים</h1>
            <p>יוצא ב: {export_date}</p>
            <p>סה"כ קבצים: {file_count}</p>
            
            {files_html}
        </body>
        </html>
        """

        files_html = ""

        for file_data in files_data:
            # הדגשת תחביר אם נדרש
            code_content = file_data["code"]
            if options.get("syntax_highlighting", True):
                highlighted = code_processor.highlight_code(
                    code_content, file_data["programming_language"], "html"
                )
                code_html = highlighted
            else:
                code_html = f"<pre><code>{code_content}</code></pre>"

            # תגיות
            tags_html = ""
            if file_data.get("tags"):
                tags_html = (
                    "<div class='tags'>"
                    + "".join(
                        [f"<span class='tag'>{tag}</span>" for tag in file_data["tags"]]
                    )
                    + "</div>"
                )

            file_html = f"""
            <div class="file-container">
                <div class="file-header">
                    <div class="file-name">{file_data['file_name']}</div>
                    <div class="file-meta">
                        שפה: {file_data['programming_language']} | 
                        גרסה: {file_data['version']} | 
                        עודכן: {file_data['updated_at'].strftime('%d/%m/%Y %H:%M')} |
                        גודל: {len(code_content)} תווים
                    </div>
                    {tags_html}
                </div>
                {code_html}
            </div>
            """

            files_html += file_html

        html_content = html_template.format(
            export_date=datetime.now().strftime("%d/%m/%Y %H:%M"),
            file_count=len(files_data),
            files_html=files_html,
        )

        return html_content.encode("utf-8")


# יצירת אינסטנסים גלובליים
version_manager = VersionManager()
backup_manager = BackupManager()
file_exporter = FileExporter()
