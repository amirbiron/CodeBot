"""
Diff Service
============

שירות עזר להשוואת קבצים וגרסאות באמצעות difflib.
מתוכנן לשימוש הן ב-WebApp והן בבוט בעתיד.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

try:
    from bson import ObjectId
except Exception:  # pragma: no cover - סביבת בדיקות ללא bson
    class ObjectId(str):  # type: ignore
        """Fallback פשוט עבור ObjectId."""

        pass


class DiffMode(str, Enum):
    """מצבי תצוגה אפשריים (לצורכי מטא-דאטה ב-API)."""

    UNIFIED = "unified"
    SIDE_BY_SIDE = "side_by_side"
    RAW = "raw"


@dataclass
class DiffLine:
    """שורה בודדת בתוצאה."""

    line_num_left: Optional[int] = None
    line_num_right: Optional[int] = None
    content_left: Optional[str] = None
    content_right: Optional[str] = None
    change_type: str = "unchanged"  # unchanged / added / removed / modified

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
    """עטיפה נוחה לפלט ההשוואה."""

    lines: List[DiffLine] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)
    left_info: Dict[str, Any] = field(default_factory=dict)
    right_info: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lines": [line.to_dict() for line in self.lines],
            "stats": dict(self.stats),
            "left_info": dict(self.left_info),
            "right_info": dict(self.right_info),
        }


class DiffService:
    """שירות להשוואת טקסטים/קבצים."""

    def __init__(self, db=None):
        self.db = db

    # -------- Public API -------- #
    def compute_diff(self, left_content: str, right_content: str) -> DiffResult:
        """השוואת שני טקסטים גולמיים."""

        left_text = _coerce_text(left_content)
        right_text = _coerce_text(right_content)
        left_lines = _split_lines(left_text)
        right_lines = _split_lines(right_text)

        matcher = difflib.SequenceMatcher(None, left_lines, right_lines)
        lines: List[DiffLine] = []
        stats = {"added": 0, "removed": 0, "modified": 0, "unchanged": 0}

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for li, ri in zip(range(i1, i2), range(j1, j2)):
                    lines.append(
                        DiffLine(
                            line_num_left=li + 1,
                            line_num_right=ri + 1,
                            content_left=left_lines[li],
                            content_right=right_lines[ri],
                            change_type="unchanged",
                        )
                    )
                    stats["unchanged"] += 1

            elif tag == "replace":
                left_chunk = left_lines[i1:i2]
                right_chunk = right_lines[j1:j2]
                paired = min(len(left_chunk), len(right_chunk))

                for offset in range(paired):
                    left_idx = i1 + offset
                    right_idx = j1 + offset
                    lines.append(
                        DiffLine(
                            line_num_left=left_idx + 1,
                            line_num_right=right_idx + 1,
                            content_left=left_lines[left_idx],
                            content_right=right_lines[right_idx],
                            change_type="modified",
                        )
                    )
                    stats["modified"] += 1

                if len(left_chunk) > paired:
                    for extra in range(paired, len(left_chunk)):
                        li = i1 + extra
                        lines.append(
                            DiffLine(
                                line_num_left=li + 1,
                                line_num_right=None,
                                content_left=left_lines[li],
                                content_right=None,
                                change_type="removed",
                            )
                        )
                        stats["removed"] += 1

                if len(right_chunk) > paired:
                    for extra in range(paired, len(right_chunk)):
                        ri = j1 + extra
                        lines.append(
                            DiffLine(
                                line_num_left=None,
                                line_num_right=ri + 1,
                                content_left=None,
                                content_right=right_lines[ri],
                                change_type="added",
                            )
                        )
                        stats["added"] += 1

            elif tag == "delete":
                for li in range(i1, i2):
                    lines.append(
                        DiffLine(
                            line_num_left=li + 1,
                            line_num_right=None,
                            content_left=left_lines[li],
                            content_right=None,
                            change_type="removed",
                        )
                    )
                    stats["removed"] += 1

            elif tag == "insert":
                for ri in range(j1, j2):
                    lines.append(
                        DiffLine(
                            line_num_left=None,
                            line_num_right=ri + 1,
                            content_left=None,
                            content_right=right_lines[ri],
                            change_type="added",
                        )
                    )
                    stats["added"] += 1

        return DiffResult(
            lines=lines,
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
        *,
        file_id: Optional[str] = None,
    ) -> Optional[DiffResult]:
        """השוואת שתי גרסאות של אותו קובץ."""

        collection = self._get_collection()
        if collection is None or not file_name:
            return None

        left_doc = collection.find_one(
            {
                "user_id": user_id,
                "file_name": file_name,
                "version": version_left,
            }
        )
        right_doc = collection.find_one(
            {
                "user_id": user_id,
                "file_name": file_name,
                "version": version_right,
            }
        )
        if not left_doc or not right_doc:
            return None

        result = self.compute_diff(left_doc.get("code", ""), right_doc.get("code", ""))
        result.left_info.update(
            {
                "version": version_left,
                "file_name": file_name,
                "file_id": file_id or _object_id_str(left_doc.get("_id")),
                "updated_at": _serialize_datetime(left_doc.get("updated_at")),
            }
        )
        result.right_info.update(
            {
                "version": version_right,
                "file_name": file_name,
                "file_id": file_id or _object_id_str(right_doc.get("_id")),
                "updated_at": _serialize_datetime(right_doc.get("updated_at")),
            }
        )
        return result

    def compare_files(
        self,
        user_id: int,
        file_id_left: str,
        file_id_right: str,
    ) -> Optional[DiffResult]:
        """השוואת שני קבצים (גרסאות אחרונות לכל קובץ)."""

        collection = self._get_collection()
        if collection is None:
            return None
        if not file_id_left or not file_id_right:
            return None

        left_doc = self._find_by_id(collection, file_id_left, user_id)
        right_doc = self._find_by_id(collection, file_id_right, user_id)
        if not left_doc or not right_doc:
            return None

        result = self.compute_diff(left_doc.get("code", ""), right_doc.get("code", ""))
        result.left_info.update(
            {
                "file_name": left_doc.get("file_name", ""),
                "file_id": _object_id_str(left_doc.get("_id")),
                "version": int(left_doc.get("version") or 0),
                "programming_language": left_doc.get("programming_language") or "",
                "updated_at": _serialize_datetime(left_doc.get("updated_at")),
            }
        )
        result.right_info.update(
            {
                "file_name": right_doc.get("file_name", ""),
                "file_id": _object_id_str(right_doc.get("_id")),
                "version": int(right_doc.get("version") or 0),
                "programming_language": right_doc.get("programming_language") or "",
                "updated_at": _serialize_datetime(right_doc.get("updated_at")),
            }
        )
        return result

    # -------- Internal helpers -------- #
    def _get_collection(self):
        if self.db is None:
            return None
        return getattr(self.db, "code_snippets", None)

    def _find_by_id(self, collection, file_id: str, user_id: int):
        try:
            obj_id = ObjectId(file_id)
        except Exception:
            return None
        return collection.find_one({"_id": obj_id, "user_id": user_id})


def _coerce_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


def _split_lines(text: str) -> List[str]:
    if not text:
        return []
    return text.splitlines()


def _serialize_datetime(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    try:
        return str(value)
    except Exception:
        return None


def _object_id_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, ObjectId):
        return str(value)
    try:
        return str(value)
    except Exception:
        return None

