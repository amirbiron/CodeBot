"""
Rules Storage - אחסון כללים ב-MongoDB (סינכרוני)
=================================================
מספק ממשק לשמירה, טעינה ועדכון כללים.

🔧 הערה: הפרויקט משתמש ב-PyMongo (sync), לא ב-Motor (async).
   לכן כל הפונקציות הן סינכרוניות.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# הגדרות ברירת מחדל
RULES_COLLECTION = "visual_rules"


class RulesStorage:
    """
    מנהל אחסון כללים ב-MongoDB.

    משתלב עם תשתית ה-MongoDB הקיימת (ראה monitoring/alerts_storage.py).

    🔧 שימוש:
    ```python
    from services.db_provider import get_db
    storage = RulesStorage(get_db())
    rules = storage.list_rules()
    ```
    """

    def __init__(self, db):
        """
        Args:
            db: MongoDB database instance (מתקבל מ-get_db() דרך services/db_provider.py)
        """
        self._db = db
        self._collection = db[RULES_COLLECTION]
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        """יצירת אינדקסים נדרשים."""
        try:
            self._collection.create_index("rule_id", unique=True)
            self._collection.create_index("enabled")
            self._collection.create_index("metadata.tags")
            self._collection.create_index("created_by")
        except Exception as e:
            logger.error(f"Failed to create indexes: {e}")

    def save_rule(self, rule: Dict[str, Any]) -> str:
        """שומר או מעדכן כלל (sync)."""
        rule_id = rule.get("rule_id")
        if not rule_id:
            rule_id = f"rule_{uuid.uuid4().hex[:12]}"
            rule["rule_id"] = rule_id

        now = datetime.now(timezone.utc)
        rule["updated_at"] = now.isoformat()
        if "created_at" not in rule:
            rule["created_at"] = now.isoformat()

        self._collection.update_one(
            {"rule_id": rule_id},
            {"$set": rule},
            upsert=True,
        )

        logger.info(f"Saved rule: {rule_id}")
        return rule_id

    def get_rule(self, rule_id: str) -> Optional[Dict[str, Any]]:
        """מחזיר כלל לפי ID (sync)."""
        doc = self._collection.find_one({"rule_id": rule_id})
        if doc:
            doc.pop("_id", None)
        return doc

    def get_enabled_rules(self) -> List[Dict[str, Any]]:
        """מחזיר את כל הכללים הפעילים (sync)."""
        cursor = self._collection.find({"enabled": True})
        rules = []
        for doc in cursor:
            doc.pop("_id", None)
            rules.append(doc)
        return rules

    def list_rules(
        self,
        enabled_only: bool = False,
        tags: Optional[List[str]] = None,
        created_by: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """מחזיר רשימת כללים עם סינון (sync)."""
        query: Dict[str, Any] = {}

        if enabled_only:
            query["enabled"] = True
        if tags:
            query["metadata.tags"] = {"$all": tags}
        if created_by:
            query["created_by"] = created_by

        cursor = (
            self._collection.find(query)
            .skip(offset)
            .limit(limit)
            .sort("updated_at", -1)
        )

        rules = []
        for doc in cursor:
            doc.pop("_id", None)
            rules.append(doc)
        return rules

    def delete_rule(self, rule_id: str) -> bool:
        """מוחק כלל (sync)."""
        result = self._collection.delete_one({"rule_id": rule_id})
        deleted = result.deleted_count > 0
        if deleted:
            logger.info(f"Deleted rule: {rule_id}")
        return deleted

    def toggle_rule(self, rule_id: str, enabled: bool) -> bool:
        """מפעיל/מכבה כלל (sync)."""
        result = self._collection.update_one(
            {"rule_id": rule_id},
            {"$set": {"enabled": enabled, "updated_at": datetime.now(timezone.utc).isoformat()}},
        )
        return result.modified_count > 0

    def count_rules(self, enabled_only: bool = False) -> int:
        """מחזיר מספר הכללים (sync)."""
        query = {"enabled": True} if enabled_only else {}
        return self._collection.count_documents(query)


# =============================================================================
# Factory function - תואם ל-Flask/PyMongo
# =============================================================================

_storage: Optional[RulesStorage] = None


def get_rules_storage(db=None) -> RulesStorage:
    """
    מחזיר את מנהל האחסון (singleton).

    Args:
        db: אופציונלי - אם לא מועבר, משתמש ב-get_db() מ-webapp/app.py

    🔧 שימוש ב-Flask route:
    ```python
    @app.route('/api/rules')
    def rules_list():
        storage = get_rules_storage(get_db())
        return jsonify(storage.list_rules())
    ```
    """
    global _storage
    if _storage is None:
        if db is None:
            # חשוב: לא לייבא מ-webapp.app כאן.
            # בזמן startup ייתכן ש-webapp/app.py עדיין באמצע import ואז get_db לא מוגדר עדיין,
            # מה שגורם ל: "cannot import name 'get_db' from partially initialized module".
            # במקום זה משתמשים ב-DB provider עצמאי (lazy) שלא תלוי ב-app.
            from services.db_provider import get_db

            db = get_db()
        _storage = RulesStorage(db)
    return _storage

