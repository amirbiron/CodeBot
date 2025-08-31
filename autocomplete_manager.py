"""
מנהל אוטו-השלמה לשמות קבצים ותגיות
Autocomplete Manager for File Names and Tags
"""

import logging
from typing import Dict, List, Set

from fuzzywuzzy import fuzz, process

from cache_manager import cache, cached
from database import db

logger = logging.getLogger(__name__)


class AutocompleteManager:
    """מנהל אוטו-השלמה חכם"""

    def __init__(self):
        self.min_similarity = 60  # אחוז דמיון מינימלי לאוטו-השלמה

    @cached(expire_seconds=180, key_prefix="autocomplete_files")
    def get_user_filenames(self, user_id: int) -> List[str]:
        """קבלת כל שמות הקבצים של משתמש לאוטו-השלמה"""
        try:
            files = db.get_user_files(user_id, limit=1000)
            return [file["file_name"] for file in files]
        except Exception as e:
            logger.error(f"שגיאה בקבלת שמות קבצים לאוטו-השלמה: {e}")
            return []

    @cached(expire_seconds=300, key_prefix="autocomplete_tags")
    def get_user_tags(self, user_id: int) -> List[str]:
        """קבלת כל התגיות של משתמש לאוטו-השלמה"""
        try:
            files = db.get_user_files(user_id, limit=1000)
            all_tags = set()

            for file in files:
                tags = file.get("tags", [])
                if tags:
                    all_tags.update(tags)

            return sorted(list(all_tags))
        except Exception as e:
            logger.error(f"שגיאה בקבלת תגיות לאוטו-השלמה: {e}")
            return []

    def suggest_filenames(
        self, user_id: int, partial_name: str, limit: int = 5
    ) -> List[Dict[str, any]]:
        """הצעות שמות קבצים בהתבסס על קלט חלקי"""
        if not partial_name or len(partial_name) < 2:
            return []

        try:
            all_filenames = self.get_user_filenames(user_id)

            if not all_filenames:
                return []

            # חיפוש עם fuzzywuzzy
            matches = process.extract(
                partial_name, all_filenames, scorer=fuzz.partial_ratio, limit=limit
            )

            # סינון תוצאות עם דמיון גבוה מספיק
            suggestions = []
            for filename, score in matches:
                if score >= self.min_similarity:
                    suggestions.append(
                        {
                            "filename": filename,
                            "score": score,
                            "display": f"📄 {filename} ({score}%)",
                        }
                    )

            # מיון לפי ציון דמיון
            suggestions.sort(key=lambda x: x["score"], reverse=True)

            return suggestions

        except Exception as e:
            logger.error(f"שגיאה בהצעת שמות קבצים: {e}")
            return []

    def suggest_tags(self, user_id: int, partial_tag: str, limit: int = 5) -> List[Dict[str, any]]:
        """הצעות תגיות בהתבסס על קלט חלקי"""
        if not partial_tag or len(partial_tag) < 1:
            return []

        try:
            all_tags = self.get_user_tags(user_id)

            if not all_tags:
                return []

            # חיפוש עם fuzzywuzzy
            matches = process.extract(partial_tag, all_tags, scorer=fuzz.partial_ratio, limit=limit)

            # סינון תוצאות
            suggestions = []
            for tag, score in matches:
                if score >= self.min_similarity:
                    suggestions.append(
                        {"tag": tag, "score": score, "display": f"🏷️ {tag} ({score}%)"}
                    )

            # מיון לפי ציון דמיון
            suggestions.sort(key=lambda x: x["score"], reverse=True)

            return suggestions

        except Exception as e:
            logger.error(f"שגיאה בהצעת תגיות: {e}")
            return []

    def get_smart_suggestions(
        self, user_id: int, input_text: str, suggestion_type: str = "auto"
    ) -> List[str]:
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
                suggestions.extend([s["filename"] for s in file_suggestions])

            if suggestion_type in ["auto", "tag"]:
                # הצעות תגיות
                tag_suggestions = self.suggest_tags(user_id, last_word, limit=3)
                suggestions.extend([s["tag"] for s in tag_suggestions])

            return list(set(suggestions))  # הסרת כפילויות

        except Exception as e:
            logger.error(f"שגיאה בהצעות חכמות: {e}")
            return []

    def get_recent_files(self, user_id: int, limit: int = 5) -> List[str]:
        """קבלת שמות הקבצים שנערכו לאחרונה"""
        try:
            files = db.get_user_files(user_id, limit=limit)
            return [file["file_name"] for file in files]
        except Exception as e:
            logger.error(f"שגיאה בקבלת קבצים אחרונים: {e}")
            return []

    def invalidate_cache(self, user_id: int):
        """ביטול cache של אוטו-השלמה למשתמש"""
        cache.delete_pattern(f"autocomplete_*:*:user:{user_id}:*")


# יצירת instance גלובלי
autocomplete = AutocompleteManager()
