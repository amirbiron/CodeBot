"""
Diff Service - שירות השוואת קבצים
"""

import difflib
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any, Tuple
import re


class DiffMode(Enum):
    """מצבי תצוגת ההשוואה"""
    UNIFIED = "unified"         # תצוגה אחודה (כמו git diff)
    SIDE_BY_SIDE = "side_by_side"  # תצוגה צד-לצד
    INLINE = "inline"           # הדגשה inline בתוך הטקסט


@dataclass
class DiffLine:
    """שורה בודדת בתוצאת ההשוואה"""
    line_num_left: Optional[int] = None
    line_num_right: Optional[int] = None
    content_left: Optional[str] = None
    content_right: Optional[str] = None
    change_type: str = "unchanged"  # unchanged, added, removed, modified

    def to_dict(self) -> Dict[str, Any]:
        return {
            "line_num_left": self.line_num_left,
            "line_num_right": self.line_num_right,
            "content_left": self.content_left,
            "content_right": self.content_right,
            "change_type": self.change_type,
        }


@dataclass
class DiffResult:
    """תוצאת השוואה מלאה"""
    lines: List[DiffLine] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)
    left_info: Dict[str, Any] = field(default_factory=dict)
    right_info: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lines": [line.to_dict() for line in self.lines],
            "stats": self.stats,
            "left_info": self.left_info,
            "right_info": self.right_info,
        }


class DiffService:
    """שירות להשוואת קבצים וגרסאות"""

    def __init__(self, db_manager=None):
        self.db = db_manager

    def compute_diff(
        self,
        left_content: str,
        right_content: str,
        context_lines: int = 3,
    ) -> DiffResult:
        """
        חישוב ההבדלים בין שני טקסטים.

        Args:
            left_content: תוכן הקובץ השמאלי (ישן/מקורי)
            right_content: תוכן הקובץ הימני (חדש/משונה)
            context_lines: מספר שורות הקשר סביב שינויים

        Returns:
            DiffResult עם כל פרטי ההשוואה
        """
        # שים לב: keepends=False כדי להימנע ממצב שבו אותו תוכן מזוהה כ-modified
        # רק בגלל newline חסר בשורה האחרונה (ע"פ difflib.SequenceMatcher).
        left_lines = left_content.splitlines(keepends=False)
        right_lines = right_content.splitlines(keepends=False)

        # שימוש ב-difflib לחישוב ההבדלים
        matcher = difflib.SequenceMatcher(None, left_lines, right_lines)

        result_lines: List[DiffLine] = []
        stats = {"added": 0, "removed": 0, "modified": 0, "unchanged": 0}

        left_idx = 0
        right_idx = 0

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for i, j in zip(range(i1, i2), range(j1, j2)):
                    result_lines.append(DiffLine(
                        line_num_left=i + 1,
                        line_num_right=j + 1,
                        content_left=left_lines[i],
                        content_right=right_lines[j],
                        change_type="unchanged",
                    ))
                    stats["unchanged"] += 1

            elif tag == "replace":
                # שורות שונות - נציג אותן כ-modified
                max_len = max(i2 - i1, j2 - j1)
                for k in range(max_len):
                    left_i = i1 + k if i1 + k < i2 else None
                    right_j = j1 + k if j1 + k < j2 else None

                    result_lines.append(DiffLine(
                        line_num_left=(left_i + 1) if left_i is not None else None,
                        line_num_right=(right_j + 1) if right_j is not None else None,
                        content_left=left_lines[left_i] if left_i is not None else None,
                        content_right=right_lines[right_j] if right_j is not None else None,
                        change_type="modified",
                    ))
                    stats["modified"] += 1

            elif tag == "delete":
                for i in range(i1, i2):
                    result_lines.append(DiffLine(
                        line_num_left=i + 1,
                        line_num_right=None,
                        content_left=left_lines[i],
                        content_right=None,
                        change_type="removed",
                    ))
                    stats["removed"] += 1

            elif tag == "insert":
                for j in range(j1, j2):
                    result_lines.append(DiffLine(
                        line_num_left=None,
                        line_num_right=j + 1,
                        content_left=None,
                        content_right=right_lines[j],
                        change_type="added",
                    ))
                    stats["added"] += 1

        return DiffResult(
            lines=result_lines,
            stats=stats,
            left_info={"total_lines": len(left_lines)},
            right_info={"total_lines": len(right_lines)},
        )

    def compare_versions(
        self,
        user_id: int,
        file_name: str,
        version_left: int,
        version_right: int,
    ) -> Optional[DiffResult]:
        """
        השוואה בין שתי גרסאות של אותו קובץ.

        Args:
            user_id: מזהה המשתמש
            file_name: שם הקובץ
            version_left: מספר הגרסה השמאלית (ישנה)
            version_right: מספר הגרסה הימנית (חדשה)

        Returns:
            DiffResult או None אם לא נמצאו הגרסאות
        """
        if self.db is None:
            return None

        left_doc = self.db.get_version(user_id, file_name, version_left)
        right_doc = self.db.get_version(user_id, file_name, version_right)

        if not left_doc or not right_doc:
            return None

        left_content = left_doc.get("code", "")
        right_content = right_doc.get("code", "")

        result = self.compute_diff(left_content, right_content)

        # הוספת מטאדאטה על הגרסאות
        result.left_info.update({
            "version": version_left,
            "file_name": file_name,
            "updated_at": str(left_doc.get("updated_at", "")),
            "file_id": str(left_doc.get("_id", "")),
        })
        result.right_info.update({
            "version": version_right,
            "file_name": file_name,
            "updated_at": str(right_doc.get("updated_at", "")),
            "file_id": str(right_doc.get("_id", "")),
        })

        return result

    def compare_files(
        self,
        user_id: int,
        file_id_left: str,
        file_id_right: str,
    ) -> Optional[DiffResult]:
        """
        השוואה בין שני קבצים שונים.

        Args:
            user_id: מזהה המשתמש
            file_id_left: מזהה הקובץ השמאלי
            file_id_right: מזהה הקובץ הימני

        Returns:
            DiffResult או None אם לא נמצאו הקבצים
        """
        if self.db is None:
            return None

        left_doc = self.db.get_file_by_id(file_id_left)
        right_doc = self.db.get_file_by_id(file_id_right)

        if not left_doc or not right_doc:
            return None

        # וידוא שהקבצים שייכים למשתמש
        if left_doc.get("user_id") != user_id or right_doc.get("user_id") != user_id:
            return None

        left_content = left_doc.get("code", "")
        right_content = right_doc.get("code", "")

        result = self.compute_diff(left_content, right_content)

        # הוספת מטאדאטה על הקבצים
        result.left_info.update({
            "file_name": left_doc.get("file_name", ""),
            "file_id": file_id_left,
            "programming_language": left_doc.get("programming_language", ""),
            "version": left_doc.get("version", 1),
        })
        result.right_info.update({
            "file_name": right_doc.get("file_name", ""),
            "file_id": file_id_right,
            "programming_language": right_doc.get("programming_language", ""),
            "version": right_doc.get("version", 1),
        })

        return result

    def format_unified_diff(
        self,
        diff_result: DiffResult,
        context_lines: int = 3,
    ) -> str:
        """
        פורמט unified diff (כמו git diff).

        Returns:
            מחרוזת בפורמט unified diff
        """
        left_name = diff_result.left_info.get("file_name", "left")
        right_name = diff_result.right_info.get("file_name", "right")

        output_lines = [
            f"--- {left_name}",
            f"+++ {right_name}",
        ]

        # קיבוץ שינויים ל-hunks
        current_hunk = []
        hunk_start_left = None
        hunk_start_right = None

        for line in diff_result.lines:
            if line.change_type == "unchanged":
                if current_hunk:
                    current_hunk.append(f" {line.content_left or ''}")
                continue

            if hunk_start_left is None:
                hunk_start_left = line.line_num_left or 1
                hunk_start_right = line.line_num_right or 1

            if line.change_type == "removed":
                current_hunk.append(f"-{line.content_left or ''}")
            elif line.change_type == "added":
                current_hunk.append(f"+{line.content_right or ''}")
            elif line.change_type == "modified":
                if line.content_left:
                    current_hunk.append(f"-{line.content_left}")
                if line.content_right:
                    current_hunk.append(f"+{line.content_right}")

        if current_hunk:
            hunk_header = f"@@ -{hunk_start_left},? +{hunk_start_right},? @@"
            output_lines.append(hunk_header)
            output_lines.extend(current_hunk)

        return "\n".join(output_lines)

    def format_for_telegram(
        self,
        diff_result: DiffResult,
        max_lines: int = 50,
    ) -> str:
        """
        פורמט מותאם לתצוגה בטלגרם.

        Args:
            diff_result: תוצאת ההשוואה
            max_lines: מספר שורות מקסימלי להצגה

        Returns:
            מחרוזת מעוצבת לטלגרם
        """
        stats = diff_result.stats

        header = (
            f"📊 **סיכום השוואה**\n"
            f"➕ נוספו: {stats.get('added', 0)} שורות\n"
            f"➖ נמחקו: {stats.get('removed', 0)} שורות\n"
            f"🔄 שונו: {stats.get('modified', 0)} שורות\n"
            f"━━━━━━━━━━━━━━━━\n"
        )

        changes = []
        shown = 0

        for line in diff_result.lines:
            if shown >= max_lines:
                changes.append(f"\n... ועוד {len(diff_result.lines) - shown} שורות")
                break

            if line.change_type == "added":
                changes.append(f"+ {line.content_right}")
                shown += 1
            elif line.change_type == "removed":
                changes.append(f"- {line.content_left}")
                shown += 1
            elif line.change_type == "modified":
                changes.append(f"- {line.content_left}")
                changes.append(f"+ {line.content_right}")
                shown += 2

        if not changes:
            return header + "✅ הקבצים זהים - אין שינויים"

        return header + "```diff\n" + "\n".join(changes) + "\n```"


# Singleton instance
_diff_service: Optional[DiffService] = None


def get_diff_service(db_manager=None) -> DiffService:
    """קבלת instance של שירות ההשוואה."""
    global _diff_service
    if _diff_service is None:
        _diff_service = DiffService(db_manager)
    return _diff_service

