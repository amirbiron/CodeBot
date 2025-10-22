"""
מנהל אוטו-השלמה לשמות קבצים ותגיות
Autocomplete Manager for File Names and Tags
"""

import logging
from typing import Any, List, Dict, Set

fuzz: Any
process: Any
_HAS_FUZZY: bool = False

try:
    from rapidfuzz import fuzz as _rf_fuzz, process as _rf_process
    fuzz = _rf_fuzz
    process = _rf_process
    _HAS_FUZZY = True
except Exception:
    # Minimal fallbacks
    class _Fuzz:
        @staticmethod
        def partial_ratio(a: str, b: str) -> int:
            a = (a or "").lower()
            b = (b or "").lower()
            if not a or not b:
                return 0
            if a in b or b in a:
                return int(100 * min(len(a), len(b)) / max(len(a), len(b)))
            # crude overlap measure
            common = sum(1 for ch in set(a) if ch in b)
            return int(100 * common / max(len(set(a + b)), 1))
    fuzz = _Fuzz()
    class _Process:
        @staticmethod
        def extract(query: str, choices: List[str], scorer: Any = None, limit: int = 5) -> List[tuple[str, int]]:
            scorer = scorer or (lambda x, y: 0)
            scored: List[tuple[str, int]] = [(c, int(scorer(query, c))) for c in choices]
            scored.sort(key=lambda t: t[1], reverse=True)
            return [(c, s) for c, s in scored[:limit]]
    process = _Process()
from database import db
# ייבוא חסין: בטסטים לעיתים ממקפים את cache_manager כך שיכיל רק cache
try:
    from cache_manager import cache  # type: ignore
except Exception:  # pragma: no cover
    cache = None  # type: ignore[assignment]
try:
    from cache_manager import cached  # type: ignore
except Exception:  # pragma: no cover
    def cached(expire_seconds: int = 300, key_prefix: str = "default"):  # type: ignore[no-redef]
        def _decorator(func):
            return func
        return _decorator
if cache is None:  # pragma: no cover
    class _NullCache:
        def delete_pattern(self, *args, **kwargs):
            return 0
    cache = _NullCache()  # type: ignore[assignment]

logger = logging.getLogger(__name__)

class AutocompleteManager:
    """מנהל אוטו-השלמה חכם"""
    
    def __init__(self) -> None:
        self.min_similarity = 60  # אחוז דמיון מינימלי לאוטו-השלמה
        
    @cached(expire_seconds=180, key_prefix="autocomplete_files")
    def get_user_filenames(self, user_id: int) -> List[str]:
        """קבלת שמות קבצים לאוטו-השלמה עם הקרנה קלה והגבלת כמות בטוחה."""
        try:
            # הקרנה מינימלית: רק file_name
            try:
                rows = db.get_user_files(user_id, limit=500, skip=0, projection={"file_name": 1})
            except TypeError:
                # תאימות ל-stubs בטסטים שלא מקבלים skip/projection
                rows = db.get_user_files(user_id, 500)
            return [str(r.get('file_name') or '') for r in rows if isinstance(r, dict) and r.get('file_name')]
        except Exception as e:
            logger.error(f"שגיאה בקבלת שמות קבצים לאוטו-השלמה: {e}")
            return []
    
    @cached(expire_seconds=300, key_prefix="autocomplete_tags")
    def get_user_tags(self, user_id: int) -> List[str]:
        """קבלת כל התגיות של משתמש לאוטו-השלמה"""
        try:
            # משיכת תגיות בלבד מהגרסאות האחרונות בכל קובץ באמצעות הקרנה
            try:
                rows = db.get_user_files(user_id, limit=500, projection={"tags": 1, "file_name": 1})
            except TypeError:
                rows = db.get_user_files(user_id, 500)
            all_tags: Set[str] = set()
            for doc in rows:
                try:
                    for t in list(doc.get('tags') or []):
                        ts = str(t or '').strip()
                        if ts:
                            all_tags.add(ts)
                except Exception:
                    continue
            return sorted(all_tags)
        except Exception as e:
            logger.error(f"שגיאה בקבלת תגיות לאוטו-השלמה: {e}")
            return []
    
    def suggest_filenames(self, user_id: int, partial_name: str, limit: int = 5) -> List[Dict[str, Any]]:
        """הצעות שמות קבצים בהתבסס על קלט חלקי"""
        if not partial_name or len(partial_name) < 2:
            return []
        
        try:
            all_filenames = self.get_user_filenames(user_id)
            
            if not all_filenames:
                return []
            
            # חיפוש עם rapidfuzz
            matches = process.extract(
                partial_name, 
                all_filenames, 
                scorer=fuzz.partial_ratio,
                limit=limit
            )
            
            # סינון תוצאות עם דמיון גבוה מספיק
            suggestions = []
            for entry in matches:
                try:
                    filename = entry[0]
                    score = int(entry[1])
                except Exception:
                    continue
                if int(score) >= self.min_similarity:
                    suggestions.append({
                        'filename': filename,
                        'score': score,
                        'display': f"📄 {filename} ({score}%)"
                    })
            
            # מיון לפי ציון דמיון
            suggestions.sort(key=lambda x: x['score'], reverse=True)
            
            return suggestions
            
        except Exception as e:
            logger.error(f"שגיאה בהצעת שמות קבצים: {e}")
            return []
    
    def suggest_tags(self, user_id: int, partial_tag: str, limit: int = 5) -> List[Dict[str, Any]]:
        """הצעות תגיות בהתבסס על קלט חלקי"""
        if not partial_tag or len(partial_tag) < 1:
            return []
        
        try:
            all_tags = self.get_user_tags(user_id)
            
            if not all_tags:
                return []
            
            # חיפוש עם rapidfuzz
            matches = process.extract(
                partial_tag, 
                all_tags, 
                scorer=fuzz.partial_ratio,
                limit=limit
            )
            
            # סינון תוצאות
            suggestions = []
            for entry in matches:
                try:
                    tag = entry[0]
                    score = int(entry[1])
                except Exception:
                    continue
                if int(score) >= self.min_similarity:
                    suggestions.append({
                        'tag': tag,
                        'score': score,
                        'display': f"🏷️ {tag} ({score}%)"
                    })
            
            # מיון לפי ציון דמיון
            suggestions.sort(key=lambda x: x['score'], reverse=True)
            
            return suggestions
            
        except Exception as e:
            logger.error(f"שגיאה בהצעת תגיות: {e}")
            return []
    
    def get_smart_suggestions(self, user_id: int, input_text: str, suggestion_type: str = "auto") -> List[str]:
        """הצעות חכמות בהתבסס על הקשר"""
        try:
            words = input_text.strip().split()
            if not words:
                return []
            
            last_word = words[-1]
            
            suggestions = []
            
            if suggestion_type in ["auto", "filename"]:
                # הצעות שמות קבצים
                file_suggestions = self.suggest_filenames(user_id, last_word, limit=3)
                suggestions.extend([s['filename'] for s in file_suggestions])
            
            if suggestion_type in ["auto", "tag"]:
                # הצעות תגיות
                tag_suggestions = self.suggest_tags(user_id, last_word, limit=3)
                suggestions.extend([s['tag'] for s in tag_suggestions])
            
            return list(set(suggestions))  # הסרת כפילויות
            
        except Exception as e:
            logger.error(f"שגיאה בהצעות חכמות: {e}")
            return []
    
    def get_recent_files(self, user_id: int, limit: int = 5) -> List[str]:
        """קבלת שמות הקבצים שנערכו לאחרונה"""
        try:
            files = db.get_user_files(user_id, limit=limit)
            return [file['file_name'] for file in files]
        except Exception as e:
            logger.error(f"שגיאה בקבלת קבצים אחרונים: {e}")
            return []
    
    def invalidate_cache(self, user_id: int) -> None:
        """ביטול cache של אוטו-השלמה למשתמש"""
        cache.delete_pattern(f"autocomplete_*:*:user:{user_id}:*")

# יצירת instance גלובלי
autocomplete = AutocompleteManager()