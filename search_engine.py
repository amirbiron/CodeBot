"""
מנוע חיפוש מתקדם לקטעי קוד
Advanced Search Engine for Code Snippets
"""

import logging
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from fuzzywuzzy import fuzz, process

from code_processor import code_processor
from config import config
from database import db

logger = logging.getLogger(__name__)

class SearchType(Enum):
    """סוגי חיפוש"""
    TEXT = "text"
    REGEX = "regex"
    FUZZY = "fuzzy"
    SEMANTIC = "semantic"
    FUNCTION = "function"
    CONTENT = "content"

class SortOrder(Enum):
    """סדר מיון"""
    RELEVANCE = "relevance"
    DATE_DESC = "date_desc"
    DATE_ASC = "date_asc"
    NAME_ASC = "name_asc"
    NAME_DESC = "name_desc"
    SIZE_DESC = "size_desc"
    SIZE_ASC = "size_asc"

@dataclass
class SearchFilter:
    """מסנן חיפוש"""
    languages: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    min_size: Optional[int] = None
    max_size: Optional[int] = None
    has_functions: Optional[bool] = None
    has_classes: Optional[bool] = None
    file_pattern: Optional[str] = None

@dataclass
class SearchResult:
    """תוצאת חיפוש"""
    file_name: str
    content: str
    programming_language: str
    tags: List[str]
    created_at: datetime
    updated_at: datetime
    version: int
    relevance_score: float
    matches: List[Dict[str, Any]] = field(default_factory=list)
    snippet_preview: str = ""
    highlight_ranges: List[Tuple[int, int]] = field(default_factory=list)

class SearchIndex:
    """אינדקס חיפוש לביצועים טובים יותר"""
    
    def __init__(self):
        self.word_index: Dict[str, Set[str]] = defaultdict(set)  # מילה -> קבצים
        self.function_index: Dict[str, Set[str]] = defaultdict(set)  # פונקציה -> קבצים
        self.language_index: Dict[str, Set[str]] = defaultdict(set)  # שפה -> קבצים
        self.tag_index: Dict[str, Set[str]] = defaultdict(set)  # תגית -> קבצים
        self.last_update = datetime.min.replace(tzinfo=timezone.utc)
        
    def rebuild_index(self, user_id: int):
        """בניית האינדקס מחדש"""
        
        logger.info(f"בונה אינדקס חיפוש עבור משתמש {user_id}")
        
        # ניקוי אינדקס קיים
        self.word_index.clear()
        self.function_index.clear()
        self.language_index.clear()
        self.tag_index.clear()
        
        # קבלת כל הקבצים
        files = db.get_user_files(user_id, limit=10000)
        
        for file_data in files:
            file_key = f"{user_id}:{file_data['file_name']}"
            content = file_data['code'].lower()
            
            # אינדקס מילים
            words = re.findall(r'\b\w+\b', content)
            for word in set(words):
                if len(word) >= 2:  # רק מילים של 2+ תווים
                    self.word_index[word].add(file_key)
            
            # אינדקס פונקציות
            functions = code_processor.extract_functions(
                file_data['code'], file_data['programming_language']
            )
            for func in functions:
                self.function_index[func['name'].lower()].add(file_key)
            
            # אינדקס שפות
            self.language_index[file_data['programming_language']].add(file_key)
            
            # אינדקס תגיות
            for tag in file_data.get('tags', []):
                self.tag_index[tag.lower()].add(file_key)
        
        self.last_update = datetime.now(timezone.utc)
        logger.info(f"אינדקס נבנה: {len(self.word_index)} מילים, {len(self.function_index)} פונקציות")
    
    def should_rebuild(self, max_age_minutes: int = 30) -> bool:
        """בדיקה אם צריך לבנות אינדקס מחדש"""
        age = datetime.now(timezone.utc) - self.last_update
        return age.total_seconds() > (max_age_minutes * 60)

class AdvancedSearchEngine:
    """מנוע חיפוש מתקדם"""
    
    def __init__(self):
        self.indexes: Dict[int, SearchIndex] = {}
        self.stop_words = {
            'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be', 'been',
            'את', 'של', 'על', 'עם', 'אל', 'מן', 'כמו', 'לא', 'לו', 'היא', 'הוא'
        }
    
    def get_index(self, user_id: int) -> SearchIndex:
        """קבלת אינדקס למשתמש"""
        
        if user_id not in self.indexes:
            self.indexes[user_id] = SearchIndex()
        
        index = self.indexes[user_id]
        if index.should_rebuild():
            index.rebuild_index(user_id)
        
        return index
    
    def search(self, user_id: int, query: str, search_type: SearchType = SearchType.TEXT,
               filters: Optional[SearchFilter] = None, sort_order: SortOrder = SortOrder.RELEVANCE,
               limit: int = 50) -> List[SearchResult]:
        """חיפוש מתקדם"""
        
        try:
            if not query.strip():
                return []
            
            # קבלת האינדקס
            index = self.get_index(user_id)
            
            # ביצוע החיפוש לפי סוג
            if search_type == SearchType.TEXT:
                candidates = self._text_search(query, index, user_id)
            elif search_type == SearchType.REGEX:
                candidates = self._regex_search(query, user_id)
            elif search_type == SearchType.FUZZY:
                candidates = self._fuzzy_search(query, index, user_id)
            elif search_type == SearchType.FUNCTION:
                candidates = self._function_search(query, index, user_id)
            elif search_type == SearchType.CONTENT:
                candidates = self._content_search(query, user_id)
            else:
                candidates = self._text_search(query, index, user_id)
            
            # החלת מסננים
            if filters:
                candidates = self._apply_filters(candidates, filters)
            
            # מיון
            candidates = self._sort_results(candidates, sort_order)
            
            # הגבלת תוצאות
            return candidates[:limit]
            
        except Exception as e:
            logger.error(f"שגיאה בחיפוש: {e}")
            return []
    
    def _text_search(self, query: str, index: SearchIndex, user_id: int) -> List[SearchResult]:
        """חיפוש טקסט רגיל"""
        
        # ניתוח השאילתה
        query_words = [word.lower() for word in re.findall(r'\b\w+\b', query)
                      if word.lower() not in self.stop_words and len(word) >= 2]
        
        if not query_words:
            return []
        
        # מציאת קבצים מתאימים
        file_scores = defaultdict(float)
        
        for word in query_words:
            matching_files = index.word_index.get(word, set())
            
            # חיפוש חלקי (prefix matching)
            for indexed_word, files in index.word_index.items():
                if indexed_word.startswith(word) or word in indexed_word:
                    matching_files.update(files)
            
            # הוספת ניקוד
            for file_key in matching_files:
                if word in index.word_index and file_key in index.word_index[word]:
                    file_scores[file_key] += 2.0  # התאמה מדויקת
                else:
                    file_scores[file_key] += 1.0  # התאמה חלקית
        
        # יצירת תוצאות
        results = []
        for file_key, score in file_scores.items():
            if score > 0:
                user_id_str, file_name = file_key.split(':', 1)
                if int(user_id_str) == user_id:
                    file_data = db.get_latest_version(user_id, file_name)
                    if file_data:
                        result = self._create_search_result(file_data, query, score)
                        results.append(result)
        
        return results
    
    def _regex_search(self, pattern: str, user_id: int) -> List[SearchResult]:
        """חיפוש עם ביטויים רגולריים"""
        
        try:
            compiled_pattern = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
        except re.error as e:
            logger.error(f"דפוס regex לא תקין: {e}")
            return []
        
        files = db.get_user_files(user_id, limit=1000)
        results = []
        
        for file_data in files:
            content = file_data['code']
            matches = list(compiled_pattern.finditer(content))
            
            if matches:
                score = len(matches)
                result = self._create_search_result(file_data, pattern, score)
                
                # הוספת מידע על ההתאמות
                result.matches = [
                    {
                        "start": match.start(),
                        "end": match.end(),
                        "text": match.group(),
                        "line": content[:match.start()].count('\n') + 1
                    }
                    for match in matches[:10]  # מקסימום 10 התאמות
                ]
                
                results.append(result)
        
        return results
    
    def _fuzzy_search(self, query: str, index: SearchIndex, user_id: int) -> List[SearchResult]:
        """חיפוש מטושטש (fuzzy)"""
        
        files = db.get_user_files(user_id, limit=1000)
        results = []
        
        for file_data in files:
            # חיפוש מטושטש בשם הקובץ
            name_ratio = fuzz.partial_ratio(query.lower(), file_data['file_name'].lower())
            
            # חיפוש מטושטש בתוכן
            content_ratio = fuzz.partial_ratio(query.lower(), file_data['code'].lower())
            
            # חיפוש מטושטש בתגיות
            tags_text = ' '.join(file_data.get('tags', []))
            tags_ratio = fuzz.partial_ratio(query.lower(), tags_text.lower())
            
            # ניקוד משולב
            max_ratio = max(name_ratio, content_ratio, tags_ratio)
            
            if max_ratio >= 60:  # סף מינימלי
                score = max_ratio / 100.0
                result = self._create_search_result(file_data, query, score)
                results.append(result)
        
        return results
    
    def _function_search(self, query: str, index: SearchIndex, user_id: int) -> List[SearchResult]:
        """חיפוש פונקציות"""
        
        query_lower = query.lower()
        file_scores = defaultdict(float)
        
        # חיפוש בשמות פונקציות
        for func_name, files in index.function_index.items():
            if query_lower in func_name:
                similarity = fuzz.ratio(query_lower, func_name) / 100.0
                for file_key in files:
                    file_scores[file_key] += similarity * 2.0
        
        # יצירת תוצאות
        results = []
        for file_key, score in file_scores.items():
            if score > 0:
                user_id_str, file_name = file_key.split(':', 1)
                if int(user_id_str) == user_id:
                    file_data = db.get_latest_version(user_id, file_name)
                    if file_data:
                        result = self._create_search_result(file_data, query, score)
                        results.append(result)
        
        return results
    
    def _content_search(self, query: str, user_id: int) -> List[SearchResult]:
        """חיפוש מלא בתוכן"""
        
        files = db.get_user_files(user_id, limit=1000)
        results = []
        
        query_lower = query.lower()
        
        for file_data in files:
            content = file_data['code']
            content_lower = content.lower()
            
            # ספירת הופעות
            occurrences = content_lower.count(query_lower)
            
            if occurrences > 0:
                # חישוב ניקוד לפי תדירות ואורך המסמך
                score = min(occurrences / (len(content) / 1000), 10.0)
                
                result = self._create_search_result(file_data, query, score)
                
                # יצירת קטע תצוגה מקדימה
                preview_start = content_lower.find(query_lower)
                if preview_start >= 0:
                    start = max(0, preview_start - 50)
                    end = min(len(content), preview_start + len(query) + 50)
                    result.snippet_preview = content[start:end]
                    
                    # סימון המילה שנמצאה
                    relative_start = preview_start - start
                    relative_end = relative_start + len(query)
                    result.highlight_ranges = [(relative_start, relative_end)]
                
                results.append(result)
        
        return results
    
    def _apply_filters(self, results: List[SearchResult], filters: SearchFilter) -> List[SearchResult]:
        """החלת מסננים על התוצאות"""
        
        filtered = []
        
        for result in results:
            # מסנן שפות
            if filters.languages and result.programming_language not in filters.languages:
                continue
            
            # מסנן תגיות
            if filters.tags:
                if not any(tag in result.tags for tag in filters.tags):
                    continue
            
            # מסנן תאריך
            if filters.date_from and result.updated_at < filters.date_from:
                continue
            
            if filters.date_to and result.updated_at > filters.date_to:
                continue
            
            # מסנן גודל
            content_size = len(result.content)
            
            if filters.min_size and content_size < filters.min_size:
                continue
            
            if filters.max_size and content_size > filters.max_size:
                continue
            
            # מסנן פונקציות
            if filters.has_functions is not None:
                functions = code_processor.extract_functions(result.content, result.programming_language)
                has_functions = len(functions) > 0
                
                if filters.has_functions != has_functions:
                    continue
            
            # מסנן מחלקות
            if filters.has_classes is not None:
                has_classes = 'class ' in result.content.lower()
                
                if filters.has_classes != has_classes:
                    continue
            
            # מסנן דפוס שם קובץ
            if filters.file_pattern:
                if not re.search(filters.file_pattern, result.file_name, re.IGNORECASE):
                    continue
            
            filtered.append(result)
        
        return filtered
    
    def _sort_results(self, results: List[SearchResult], sort_order: SortOrder) -> List[SearchResult]:
        """מיון התוצאות"""
        
        if sort_order == SortOrder.RELEVANCE:
            return sorted(results, key=lambda x: x.relevance_score, reverse=True)
        
        elif sort_order == SortOrder.DATE_DESC:
            return sorted(results, key=lambda x: x.updated_at, reverse=True)
        
        elif sort_order == SortOrder.DATE_ASC:
            return sorted(results, key=lambda x: x.updated_at)
        
        elif sort_order == SortOrder.NAME_ASC:
            return sorted(results, key=lambda x: x.file_name.lower())
        
        elif sort_order == SortOrder.NAME_DESC:
            return sorted(results, key=lambda x: x.file_name.lower(), reverse=True)
        
        elif sort_order == SortOrder.SIZE_DESC:
            return sorted(results, key=lambda x: len(x.content), reverse=True)
        
        elif sort_order == SortOrder.SIZE_ASC:
            return sorted(results, key=lambda x: len(x.content))
        
        return results
    
    def _create_search_result(self, file_data: Dict, query: str, score: float) -> SearchResult:
        """יצירת אובייקט תוצאת חיפוש"""
        
        return SearchResult(
            file_name=file_data['file_name'],
            content=file_data['code'],
            programming_language=file_data['programming_language'],
            tags=file_data.get('tags', []),
            created_at=file_data['created_at'],
            updated_at=file_data['updated_at'],
            version=file_data['version'],
            relevance_score=score
        )
    
    def suggest_completions(self, user_id: int, partial_query: str, limit: int = 10) -> List[str]:
        """הצעות השלמה לחיפוש"""
        
        if len(partial_query) < 2:
            return []
        
        index = self.get_index(user_id)
        suggestions = []
        
        # השלמות מאינדקס המילים
        for word in index.word_index.keys():
            if word.startswith(partial_query.lower()):
                suggestions.append(word)
        
        # השלמות משמות פונקציות
        for func_name in index.function_index.keys():
            if func_name.startswith(partial_query.lower()):
                suggestions.append(func_name)
        
        # השלמות משפות
        for lang in index.language_index.keys():
            if lang.startswith(partial_query.lower()):
                suggestions.append(lang)
        
        # השלמות מתגיות
        for tag in index.tag_index.keys():
            if tag.startswith(partial_query.lower()):
                suggestions.append(f"#{tag}")
        
        # מיון והגבלה
        suggestions = list(set(suggestions))
        suggestions.sort(key=len)
        
        return suggestions[:limit]
    
    def get_search_statistics(self, user_id: int) -> Dict[str, Any]:
        """סטטיסטיקות חיפוש"""
        
        index = self.get_index(user_id)
        
        return {
            "indexed_words": len(index.word_index),
            "indexed_functions": len(index.function_index),
            "indexed_languages": len(index.language_index),
            "indexed_tags": len(index.tag_index),
            "last_update": index.last_update.isoformat(),
            "most_common_words": self._get_most_common_words(index, 10),
            "most_common_languages": self._get_most_common_languages(index),
            "most_common_tags": self._get_most_common_tags(index)
        }
    
    def _get_most_common_words(self, index: SearchIndex, limit: int) -> List[Tuple[str, int]]:
        """המילים הנפוצות ביותר"""
        
        word_counts = [(word, len(files)) for word, files in index.word_index.items()]
        word_counts.sort(key=lambda x: x[1], reverse=True)
        
        return word_counts[:limit]
    
    def _get_most_common_languages(self, index: SearchIndex) -> List[Tuple[str, int]]:
        """השפות הנפוצות ביותר"""
        
        lang_counts = [(lang, len(files)) for lang, files in index.language_index.items()]
        lang_counts.sort(key=lambda x: x[1], reverse=True)
        
        return lang_counts
    
    def _get_most_common_tags(self, index: SearchIndex) -> List[Tuple[str, int]]:
        """התגיות הנפוצות ביותר"""
        
        tag_counts = [(tag, len(files)) for tag, files in index.tag_index.items()]
        tag_counts.sort(key=lambda x: x[1], reverse=True)
        
        return tag_counts[:20]

class SearchQueryParser:
    """מפרש שאילתות חיפוש מתקדמות"""
    
    def __init__(self):
        self.operators = {
            'AND': self._and_operator,
            'OR': self._or_operator,
            'NOT': self._not_operator,
            'lang:': self._language_filter,
            'tag:': self._tag_filter,
            'func:': self._function_filter,
            'size:': self._size_filter,
            'date:': self._date_filter
        }
    
    def parse_query(self, query: str) -> Dict[str, Any]:
        """פרסור שאילתת חיפוש מתקדמת"""
        
        # דוגמאות לשאילתות:
        # "python AND api"
        # "lang:python tag:web"
        # "func:connect size:>100"
        # "date:2024 NOT test"
        
        parsed = {
            'terms': [],
            'filters': SearchFilter(),
            'operators': []
        }
        
        # פרסור בסיסי (לצורך ההדגמה)
        tokens = query.split()
        
        for token in tokens:
            if ':' in token:
                # זה מסנן
                key, value = token.split(':', 1)
                self._apply_filter(parsed['filters'], key, value)
            elif token.upper() in ['AND', 'OR', 'NOT']:
                parsed['operators'].append(token.upper())
            else:
                parsed['terms'].append(token)
        
        return parsed
    
    def _apply_filter(self, filters: SearchFilter, key: str, value: str):
        """החלת מסנן"""
        
        if key == 'lang':
            filters.languages.append(value)
        elif key == 'tag':
            filters.tags.append(value)
        elif key == 'size':
            # פרסור size:>100, size:<50, size:100-500
            if value.startswith('>'):
                filters.min_size = int(value[1:])
            elif value.startswith('<'):
                filters.max_size = int(value[1:])
            elif '-' in value:
                min_val, max_val = value.split('-')
                filters.min_size = int(min_val)
                filters.max_size = int(max_val)
        # ועוד מסננים...

# יצירת אינסטנס גלובלי
search_engine = AdvancedSearchEngine()
query_parser = SearchQueryParser()
