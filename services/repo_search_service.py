"""
Repository Search Service

חיפוש בקוד עם git grep (מהיר וחזק!)
"""

from __future__ import annotations

import logging
import re  # חשוב! לצורך re.escape בחיפושי MongoDB
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from services.git_mirror_service import get_mirror_service

logger = logging.getLogger(__name__)

#: תקציב הזמן של חיפוש תוכן אחד, בשניות — **לשני המעברים יחד**: איסוף
#: התוצאות וספירת המופעים. היה כאן מספר קסם בגוף הקריאה; משקיבל שם אפשר
#: גם לקרוא אותו בתיעוד וגם לבדוק את מסלול ה-timeout בלי להמתין באמת.
CONTENT_SEARCH_TIMEOUT_SECONDS = 10


@dataclass
class SearchResult:
    """תוצאת חיפוש בודדת"""

    path: str
    line: int
    content: str
    context_before: List[str] = None
    context_after: List[str] = None


class RepoSearchService:
    """
    שירות חיפוש בקוד

    משלב:
    - git grep לחיפוש מלא בתוכן
    - MongoDB לחיפוש metadata
    """

    def __init__(self, db: Any = None):
        self.db = db
        self.git_service = get_mirror_service()

    def search(
        self,
        repo_name: str,
        query: str,
        search_type: str = "content",  # content, filename, function, class
        file_pattern: Optional[str] = None,
        language: Optional[str] = None,
        case_sensitive: bool = False,
        max_results: int = 50,
        context_lines: int = 0,
        regex: bool = False,
        include_vendored: bool = False,
        exclude_paths: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        חיפוש מאוחד בקוד

        Args:
            repo_name: שם הריפו
            query: מחרוזת לחיפוש
            search_type: סוג החיפוש
            file_pattern: סינון קבצים (*.py)
            language: סינון לפי שפה
            case_sensitive: case sensitive?
            max_results: מקסימום תוצאות
            regex: ``False`` (ברירת המחדל) = התאמה מילולית. ``True`` =
                 השאילתה היא ERE. רלוונטי ל-``search_type="content"`` בלבד,
                 כי שאר המסלולים הם שאילתות מונגו עם ``re.escape``.
            include_vendored: האם לכלול קוד חיצוני (``node_modules``) בחיפוש
                 ובספירה. ``search_type="content"`` בלבד.
            exclude_paths: תבניות נתיב נוספות להחרגה, שהקורא מספק —
                 ``search_type="content"`` בלבד.

        Returns:
            dict עם results, query info, ו**אחד** משדות הספירה: ``total``
            כשהוא מדויק, או ``total_at_least`` כשהספירה נקטעה. ראו
            :meth:`_search_content`.
        """
        # ה-``strip`` כאן מכריע **ריקנות בלבד**, והשאילתה עוברת הלאה כמו
        # שהיא: חיפוש הזחה (``"    return"``) הוא שימוש אמיתי, וקיצוץ היה
        # משנה בשקט את מה שביקשו. אותה הכרעה כמו ב-``file_query_error``.
        # והאורך נמדד על המחרוזת המקורית, ולכן ``" a"`` — רווח ואות —
        # הוא שאילתה תקפה בת שני תווים ולא "קצרה מדי".
        if not (query or "").strip() or len(query) < 2:
            return {"error": "Query too short", "results": []}

        # שליפת ה-default_branch מה-DB (לא לנחש שזה main!)
        # זה נשמר במהלך initial_import
        ref = "refs/heads/main"  # ברירת מחדל בטוחה ל-mirror
        if self.db is not None:
            meta = self.db.repo_metadata.find_one({"repo_name": repo_name})
            if meta and meta.get("default_branch"):
                ref = f"refs/heads/{meta['default_branch']}"

        # בחירת שיטת חיפוש
        if search_type == "content":
            return self._search_content(
                repo_name,
                query,
                file_pattern,
                case_sensitive,
                max_results,
                ref=ref,  # העברת ה-ref הנכון
                context_lines=context_lines,
                regex=regex,
                include_vendored=include_vendored,
                exclude_paths=exclude_paths,
            )
        elif search_type == "filename":
            return self._search_filename(repo_name, query, max_results)
        elif search_type == "function":
            return self._search_functions(repo_name, query, language, max_results)
        elif search_type == "class":
            return self._search_classes(repo_name, query, language, max_results)
        else:
            return {"error": f"Unknown search type: {search_type}", "results": []}

    def _search_content(
        self,
        repo_name: str,
        query: str,
        file_pattern: Optional[str],
        case_sensitive: bool,
        max_results: int,
        ref: str = "refs/heads/main",
        context_lines: int = 0,
        regex: bool = False,
        include_vendored: bool = False,
        exclude_paths: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """חיפוש תוכן עם git grep.

        ``context_lines`` נשלח כמות שהוא ל-``search_with_git_grep``; ``0``
        (ברירת המחדל) משאיר את הפקודה ואת צורת התוצאה זהות לקודם, וזה מה
        ששומר על הקוראים האחרים של השירות הזה.
        """

        # המרת file pattern לפורמט git grep
        git_pattern = None
        if file_pattern:
            # "*.py" -> "*.py"
            git_pattern = file_pattern

        result = self.git_service.search_with_git_grep(
            repo_name=repo_name,
            query=query,
            max_results=max_results,
            timeout=CONTENT_SEARCH_TIMEOUT_SECONDS,
            file_pattern=git_pattern,
            case_sensitive=case_sensitive,
            ref=ref,  # שימוש ב-ref הנכון מה-DB
            context_lines=context_lines,
            regex=regex,
            include_vendored=include_vendored,
            exclude_paths=exclude_paths,
        )

        if "error" in result:
            # מועבר כמות שהוא, על כל מפתחותיו. ``error`` ו-``message``
            # מבדילים בין דפוס שנדחה לבין כשל מנוע, ומי שיצמצם כאן ל-דגל
            # בוליאני יחזיר את הקורא בדיוק למצב שבו הוא לא יודע מה קרה.
            return result

        # העשרת התוצאות עם metadata מ-MongoDB
        if self.db is not None and result.get("results"):
            paths = list(set(r["path"] for r in result["results"]))

            # שליפת metadata
            metadata_map: Dict[str, Dict[str, Any]] = {}
            try:
                cursor = self.db.repo_files.find(
                    {"repo_name": repo_name, "path": {"$in": paths}},
                    {"path": 1, "language": 1, "size": 1},
                )
                for doc in cursor:
                    metadata_map[doc["path"]] = doc
            except Exception as e:
                logger.warning(f"Failed to fetch metadata: {e}")

            # הוספת metadata לתוצאות
            for r in result["results"]:
                meta = metadata_map.get(r["path"], {})
                r["language"] = meta.get("language", "unknown")
                r["size"] = meta.get("size", 0)

        out: Dict[str, Any] = {
            "results": result["results"],
            "truncated": result.get("truncated", False),
            "search_type": "content",
            "query": query,
        }
        # **``total`` עובר רק כשהמנוע נקב בו.** קודם עמד כאן
        # ``result.get("total_count", len(result["results"]))``, וברירת
        # המחדל הזו היא בדיוק השקר שה-PR הזה מסלק: היא מחזירה את מספר
        # התוצאות שהוחזרו ומכריזה עליו כסך הכול. אם המנוע לא ידע — גם כאן
        # לא יודעים, ומה שעובר הוא ``total_at_least``.
        if "total_count" in result:
            out["total"] = result["total_count"]
        if "total_at_least" in result:
            out["total_at_least"] = result["total_at_least"]
        if result.get("truncation_reason"):
            out["truncation_reason"] = result["truncation_reason"]
        return out

    def _search_filename(self, repo_name: str, query: str, max_results: int) -> Dict[str, Any]:
        """חיפוש לפי שם קובץ"""

        if self.db is None:
            # Fallback ל-git ls-tree
            all_files = self.git_service.list_all_files(repo_name) or []
            query_lower = query.lower()

            results = [{"path": f, "line": 0, "content": ""} for f in all_files if query_lower in f.lower()][
                :max_results
            ]

            return {"results": results, "total": len(results), "search_type": "filename", "query": query}

        # חיפוש ב-MongoDB (מהיר יותר)
        try:
            # תיקון Regex Injection: חובה לעשות escape לתווים מיוחדים!
            # בלי זה, חיפוש "config.py" ימצא גם "configXpy" (נקודה = any char)
            safe_query = re.escape(query)

            cursor = (
                self.db.repo_files.find(
                    {"repo_name": repo_name, "path": {"$regex": safe_query, "$options": "i"}},
                    {"path": 1, "language": 1, "size": 1, "lines": 1},
                )
                .limit(max_results)
            )

            results = [
                {
                    "path": doc["path"],
                    "language": doc.get("language", "unknown"),
                    "size": doc.get("size", 0),
                    "lines": doc.get("lines", 0),
                }
                for doc in cursor
            ]

            return {"results": results, "total": len(results), "search_type": "filename", "query": query}

        except Exception as e:
            logger.exception(f"Filename search failed: {e}")
            return {"error": "Internal filename search error", "results": []}

    def _search_functions(
        self, repo_name: str, query: str, language: Optional[str], max_results: int
    ) -> Dict[str, Any]:
        """חיפוש פונקציות"""

        if self.db is None:
            return {"error": "Database required for function search", "results": []}

        try:
            # תיקון Regex Injection
            safe_query = re.escape(query)

            filter_query: Dict[str, Any] = {"repo_name": repo_name, "functions": {"$regex": safe_query, "$options": "i"}}

            if language:
                filter_query["language"] = language

            cursor = self.db.repo_files.find(filter_query, {"path": 1, "language": 1, "functions": 1}).limit(
                max_results
            )

            results: List[Dict[str, Any]] = []
            for doc in cursor:
                # מציאת הפונקציות שמתאימות (חיפוש פשוט, לא regex)
                query_lower = query.lower()
                matching = [f for f in doc.get("functions", []) if query_lower in f.lower()]

                for func_name in matching:
                    results.append(
                        {"path": doc["path"], "function": func_name, "language": doc.get("language", "unknown")}
                    )

            return {
                "results": results[:max_results],
                "total": len(results),
                "search_type": "function",
                "query": query,
            }

        except Exception as e:
            logger.exception(f"Function search failed: {e}")
            return {"error": "Internal function search error", "results": []}

    def _search_classes(self, repo_name: str, query: str, language: Optional[str], max_results: int) -> Dict[str, Any]:
        """חיפוש מחלקות"""

        if self.db is None:
            return {"error": "Database required for class search", "results": []}

        try:
            # תיקון Regex Injection
            safe_query = re.escape(query)

            filter_query: Dict[str, Any] = {"repo_name": repo_name, "classes": {"$regex": safe_query, "$options": "i"}}

            if language:
                filter_query["language"] = language

            cursor = self.db.repo_files.find(filter_query, {"path": 1, "language": 1, "classes": 1}).limit(max_results)

            results: List[Dict[str, Any]] = []
            for doc in cursor:
                # חיפוש פשוט, לא regex
                query_lower = query.lower()
                matching = [c for c in doc.get("classes", []) if query_lower in c.lower()]

                for class_name in matching:
                    results.append({"path": doc["path"], "class": class_name, "language": doc.get("language", "unknown")})

            return {
                "results": results[:max_results],
                "total": len(results),
                "search_type": "class",
                "query": query,
            }

        except Exception as e:
            logger.exception(f"Class search failed: {e}")
            return {"error": "Internal class search error", "results": []}


def create_search_service(db: Any = None) -> RepoSearchService:
    """Factory function"""
    return RepoSearchService(db)

